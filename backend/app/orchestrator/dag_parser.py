"""DAG parsing and topological sort for the Karesansui orchestrator.

Expects the Planner to emit a JSON payload that follows the schema documented
in requirement_specification.md §4 / §5.  Each node in the DAG represents one
agent task; edges represent dependency relationships (parent → child).

Public API
----------
    dag = DagParser(payload)
    ordered: list[DagNode] = dag.topological_sort()

Raises
------
    DagValidationError  – payload is malformed, a referenced node is missing,
                          or a circular dependency is detected.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DagValidationError(Exception):
    """Raised when the DAG payload is invalid or contains a cycle."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class DagNode:
    """Represents a single task node parsed from the Planner's DAG payload.

    Attributes
    ----------
    task_id:
        Unique identifier for this task (must be unique within the DAG).
    task_type:
        ``"Standard"`` for single-agent tasks or ``"Debate"`` for multi-agent
        round-robin debate nodes.
    role:
        Role template name assigned to this task (Standard tasks only).
        Ignored when ``task_type == "Debate"``; use ``participants`` instead.
    participants:
        List of role template names for debate participant agents
        (Debate tasks only).
    mediator:
        Role template name for the mediator agent (Debate tasks only).
    parent_ids:
        List of ``task_id`` values that must complete before this task runs.
    dynamic_params:
        Arbitrary key/value pairs injected as dynamic parameters into the
        agent's system prompt (e.g. standpoint, tone).
    """

    __slots__ = (
        "task_id",
        "task_type",
        "role",
        "participants",
        "mediator",
        "parent_ids",
        "dynamic_params",
    )

    def __init__(
        self,
        task_id: str,
        task_type: Literal["Standard", "Debate"],
        role: str | None,
        participants: list[str],
        mediator: str | None,
        parent_ids: list[str],
        dynamic_params: dict[str, Any],
    ) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.role = role
        self.participants = participants
        self.mediator = mediator
        self.parent_ids = parent_ids
        self.dynamic_params = dynamic_params

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DagNode(task_id={self.task_id!r}, task_type={self.task_type!r}, "
            f"parents={self.parent_ids!r})"
        )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class DagParser:
    """Parse and validate a Planner-emitted DAG JSON payload.

    Parameters
    ----------
    payload:
        The raw deserialized Python object produced by ``json.loads()`` on
        the Planner's output.  Expected top-level shape::

            {
                "tasks": [
                    {
                        "task_id": "t1",
                        "task_type": "Standard",
                        "role": "Data_Gatherer",
                        "parent_ids": [],
                        "dynamic_params": {}
                    },
                    {
                        "task_id": "t2",
                        "task_type": "Debate",
                        "participants": ["Advocate", "Disrupter"],
                        "mediator": "Mediator",
                        "parent_ids": ["t1"],
                        "dynamic_params": {"standpoint": "pro"}
                    }
                ]
            }
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self._nodes: dict[str, DagNode] = {}
        self._parse(payload)
        self._validate_references()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    # Only key allowed at the top level of the DAG payload.
    _TOP_LEVEL_KEYS: frozenset[str] = frozenset({"tasks"})

    def _parse(self, payload: dict[str, Any]) -> None:
        """Extract nodes from *payload* and populate ``self._nodes``."""
        if not isinstance(payload, dict):
            raise DagValidationError("DAG payload must be a JSON object.")

        extra_top = set(payload.keys()) - self._TOP_LEVEL_KEYS
        if extra_top:
            raise DagValidationError(
                f"DAG payload contains unexpected top-level keys: "
                f"{sorted(extra_top)!r}.  Only 'tasks' is allowed."
            )

        raw_tasks: Any = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise DagValidationError(
                "DAG payload must contain a non-empty 'tasks' list."
            )

        for raw in raw_tasks:
            node = self._parse_node(raw)
            if node.task_id in self._nodes:
                raise DagValidationError(
                    f"Duplicate task_id detected: {node.task_id!r}."
                )
            self._nodes[node.task_id] = node

    # Allowed keys per task type.  Any key outside the applicable set is
    # rejected so that malformed Planner output cannot silently pass through.
    _COMMON_KEYS: frozenset[str] = frozenset(
        {"task_id", "task_type", "parent_ids", "dynamic_params"}
    )
    _STANDARD_KEYS: frozenset[str] = _COMMON_KEYS | frozenset({"role"})
    _DEBATE_KEYS: frozenset[str] = _COMMON_KEYS | frozenset(
        {"participants", "mediator"}
    )

    def _parse_node(self, raw: Any) -> DagNode:
        """Validate and construct a single :class:`DagNode` from a raw dict.

        Enforces a strict discriminated-union schema: only the keys defined for
        the resolved ``task_type`` are allowed.  Any unexpected key raises
        :class:`DagValidationError`.
        """
        if not isinstance(raw, dict):
            raise DagValidationError(
                f"Each task entry must be a JSON object; got {type(raw).__name__!r}."
            )

        task_id: Any = raw.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise DagValidationError(
                f"Each task must have a non-empty string 'task_id'; got {task_id!r}."
            )
        task_id = task_id.strip()

        task_type: Any = raw.get("task_type")
        if task_type not in ("Standard", "Debate"):
            raise DagValidationError(
                f"task_id={task_id!r}: 'task_type' must be 'Standard' or 'Debate'; "
                f"got {task_type!r}."
            )

        # Enforce strict key set for the resolved task type.
        allowed_keys = (
            self._STANDARD_KEYS if task_type == "Standard" else self._DEBATE_KEYS
        )
        extra_keys = set(raw.keys()) - allowed_keys
        if extra_keys:
            raise DagValidationError(
                f"task_id={task_id!r}: unexpected keys for a {task_type!r} task: "
                f"{sorted(extra_keys)!r}.  Allowed keys: {sorted(allowed_keys)!r}."
            )

        # parent_ids and dynamic_params are required fields; no default fallback.
        if "parent_ids" not in raw:
            raise DagValidationError(
                f"task_id={task_id!r}: missing required field 'parent_ids'."
            )
        parent_ids: Any = raw["parent_ids"]
        if not isinstance(parent_ids, list):
            raise DagValidationError(
                f"task_id={task_id!r}: 'parent_ids' must be a list."
            )
        for pid in parent_ids:
            if not isinstance(pid, str) or not pid.strip():
                raise DagValidationError(
                    f"task_id={task_id!r}: every entry in 'parent_ids' must be a "
                    f"non-empty string; got {pid!r}."
                )

        if "dynamic_params" not in raw:
            raise DagValidationError(
                f"task_id={task_id!r}: missing required field 'dynamic_params'."
            )
        dynamic_params: Any = raw["dynamic_params"]
        if not isinstance(dynamic_params, dict):
            raise DagValidationError(
                f"task_id={task_id!r}: 'dynamic_params' must be a JSON object."
            )

        role: str | None = None
        participants: list[str] = []
        mediator: str | None = None

        if task_type == "Standard":
            role = raw.get("role")
            if not isinstance(role, str) or not role.strip():
                raise DagValidationError(
                    f"task_id={task_id!r}: Standard tasks must have a non-empty "
                    f"string 'role'."
                )
            role = role.strip()
        else:  # Debate
            participants = raw.get("participants", [])
            if not isinstance(participants, list) or len(participants) < 2:
                raise DagValidationError(
                    f"task_id={task_id!r}: Debate tasks must have at least two "
                    f"'participants'."
                )
            for p in participants:
                if not isinstance(p, str) or not p.strip():
                    raise DagValidationError(
                        f"task_id={task_id!r}: each participant must be a "
                        f"non-empty string; got {p!r}."
                    )
            participants = [p.strip() for p in participants]

            mediator = raw.get("mediator")
            if not isinstance(mediator, str) or not mediator.strip():
                raise DagValidationError(
                    f"task_id={task_id!r}: Debate tasks must have a non-empty "
                    f"string 'mediator'."
                )
            mediator = mediator.strip()

        return DagNode(
            task_id=task_id,
            task_type=task_type,
            role=role,
            participants=participants,
            mediator=mediator,
            parent_ids=[pid.strip() for pid in parent_ids],
            dynamic_params=dynamic_params,
        )

    def _validate_references(self) -> None:
        """Ensure every parent_id references an existing task_id."""
        for node in self._nodes.values():
            for pid in node.parent_ids:
                if pid not in self._nodes:
                    raise DagValidationError(
                        f"task_id={node.task_id!r} references unknown parent "
                        f"{pid!r}."
                    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def nodes(self) -> dict[str, DagNode]:
        """Read-only view of all parsed nodes keyed by task_id."""
        return dict(self._nodes)

    def topological_sort(self) -> list[DagNode]:
        """Return nodes in a valid execution order (Kahn's algorithm).

        Tasks with no unresolved parents are ready to run first; the returned
        list respects all dependency constraints so tasks later in the list can
        safely consume the results of earlier ones.

        Raises
        ------
        DagValidationError
            If a circular dependency is detected (i.e. the graph contains a
            cycle and a full ordering cannot be produced).

        Returns
        -------
        list[DagNode]
            All nodes ordered so that every node appears after each of its
            dependencies.
        """
        # Build adjacency and in-degree maps.
        in_degree: dict[str, int] = {tid: 0 for tid in self._nodes}
        children: dict[str, list[str]] = {tid: [] for tid in self._nodes}

        for node in self._nodes.values():
            for pid in node.parent_ids:
                in_degree[node.task_id] += 1
                children[pid].append(node.task_id)

        # Initialise the queue with all source nodes (no incoming edges).
        # Sort for deterministic ordering when multiple roots exist.
        queue: deque[str] = deque(
            sorted(tid for tid, deg in in_degree.items() if deg == 0)
        )

        sorted_nodes: list[DagNode] = []

        while queue:
            tid = queue.popleft()
            sorted_nodes.append(self._nodes[tid])

            # Reduce in-degree for each child and enqueue newly unblocked nodes.
            for child_id in sorted(children[tid]):
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        if len(sorted_nodes) != len(self._nodes):
            # Some nodes were never added → a cycle exists.
            cycle_nodes = {
                tid for tid, deg in in_degree.items() if deg > 0
            }
            raise DagValidationError(
                f"Circular dependency detected among tasks: "
                f"{sorted(cycle_nodes)!r}."
            )

        return sorted_nodes
