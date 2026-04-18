"""Orchestrator Manager: task enqueueing and parent-result I/O.

Responsibilities
----------------
1. Accept a topologically-sorted ``list[DagNode]`` from :class:`DagParser`.
2. Dispatch each node as a Celery task to the broker.
3. After a task completes, extract **only** the ``result`` field (never
   ``progress``) from every parent and merge those results into the input
   messages for each child task, conserving context-window tokens.
4. Write ``result`` and ``progress`` back to the History table on completion.

Design notes
------------
- The manager runs inside the same process as the orchestrator caller (e.g. a
  FastAPI endpoint or a CLI runner).  It is *not* itself a Celery task.
- Parent results are retrieved via ``celery.result.AsyncResult`` with a
  configurable per-task timeout.  The manager blocks until each task finishes
  (or raises) before dispatching its dependants, guaranteeing that parent
  results are available when child prompt context is assembled.
- Only the flat ``result`` dict is forwarded to children – ``progress`` is
  intentionally omitted to save tokens (requirement_specification.md §6).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from celery.result import AsyncResult
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import History
from app.orchestrator.dag_parser import DagNode
from app.orchestrator.debate_controller import DebateController
from app.worker import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at module load; injected via environment variable)
# ---------------------------------------------------------------------------

_DEFAULT_TASK_TIMEOUT: float = float(
    os.environ.get("ORCHESTRATOR_TASK_TIMEOUT", "300")
)
"""Seconds to wait for a single task before raising TimeoutError."""

_TASK_NAME = "app.tasks.run_structured_inference"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class OrchestratorManager:
    """Enqueue DAG tasks and wire parent results to child task inputs.

    Parameters
    ----------
    model:
        Model identifier forwarded to every inference task.
    response_model_class_path:
        Dotted import path to the Pydantic ``BaseModel`` subclass used for
        structured output (e.g. ``"app.schemas.SomeModel"``).
    response_model_schema:
        JSON Schema dict produced by ``Model.model_json_schema()``.
    system_prompt_template:
        A format string used to build each task's system prompt.  The
        ``{role}`` placeholder is substituted with the node's role template
        name.
    task_timeout:
        Per-task wait timeout in seconds.  Defaults to the
        ``ORCHESTRATOR_TASK_TIMEOUT`` environment variable (300 s).
    db_session:
        Optional pre-wired SQLAlchemy session.  If ``None``, an independent
        session is opened and closed per-task.
    temperature:
        Sampling temperature forwarded to every inference task.
    max_tokens:
        Maximum tokens forwarded to every inference task.
    """

    def __init__(
        self,
        *,
        model: str,
        response_model_class_path: str,
        response_model_schema: dict[str, Any],
        system_prompt_template: str = "You are a {role} agent.",
        task_timeout: float = _DEFAULT_TASK_TIMEOUT,
        db_session: Session | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> None:
        self._model = model
        self._response_model_class_path = response_model_class_path
        self._response_model_schema = response_model_schema
        self._system_prompt_template = system_prompt_template
        self._task_timeout = task_timeout
        self._db_session = db_session
        self._temperature = temperature
        self._max_tokens = max_tokens

        # task_id (str) → completed result dict extracted from the Celery backend.
        self._completed_results: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        nodes: list[DagNode],
        user_query: str,
    ) -> dict[str, dict[str, Any]]:
        """Execute all *nodes* in topological order, returning a mapping of
        ``task_id → result``.

        Parameters
        ----------
        nodes:
            List returned by :meth:`DagParser.topological_sort`.  Must be
            ordered so that every node appears after all its parents.
        user_query:
            The original user query injected as the first human message for
            root tasks (nodes with no parents).

        Returns
        -------
        dict[str, dict[str, Any]]
            Mapping of ``task_id`` to the structured result dict.
        """
        for node in nodes:
            if node.task_type == "Debate":
                # Delegate to DebateController for round-robin multi-agent debate.
                parent_results = self._collect_parent_results(node.parent_ids)
                controller = DebateController(
                    model=self._model,
                    system_prompt_template=self._system_prompt_template,
                    task_timeout=self._task_timeout,
                    db_session=self._db_session,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                )
                final_result, debate_progress = controller.run(
                    node, parent_results, user_query
                )
                # Cache the mediator's final conclusion for child tasks.
                self._completed_results[node.task_id] = final_result
                # Persist the debate summary row via the standard _persist path.
                history_id = self._persist(node, final_result, debate_progress)
                logger.info(
                    "[manager] debate task_id=%r completed; history_id=%r",
                    node.task_id,
                    history_id,
                )
            else:
                messages = self._build_messages(node, user_query)
                history_id = self._enqueue_and_wait(node, messages)
                logger.info(
                    "[manager] task_id=%r completed; history_id=%r",
                    node.task_id,
                    history_id,
                )

        return dict(self._completed_results)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self, node: DagNode, user_query: str
    ) -> list[dict[str, Any]]:
        """Construct the OpenAI-format message list for *node*.

        For root nodes (no parents) the first human turn is the raw
        *user_query*.  For all other nodes, parent ``result`` dicts are
        serialised as a single assistant message so the child agent has
        exactly the structured conclusions it needs – with no ``progress``
        noise.
        """
        role_name = node.role if node.task_type == "Standard" else "Debate_Coordinator"
        system_content = self._system_prompt_template.format(role=role_name)

        # Inject dynamic params into the system prompt when present.
        if node.dynamic_params:
            params_str = "; ".join(
                f"{k}={v!r}" for k, v in node.dynamic_params.items()
            )
            system_content += f"\nParameters: {params_str}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content}
        ]

        if not node.parent_ids:
            # Root task: forward the raw user query directly.
            messages.append({"role": "user", "content": user_query})
        else:
            # Non-root: keep the original user_query as the first human turn so
            # the child agent always retains the original request, then append a
            # second message with parent result context (no progress, token-efficient).
            parent_context = self._collect_parent_results(node.parent_ids)
            messages.append({"role": "user", "content": user_query})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Context from preceding tasks:\n"
                        + json.dumps(parent_context, ensure_ascii=False, indent=2)
                    ),
                }
            )

        return messages

    def _collect_parent_results(
        self, parent_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Return ``{task_id: result}`` for each parent, extracting ONLY
        ``result`` and never ``progress`` to keep the prompt compact.
        """
        return {
            pid: self._completed_results[pid]
            for pid in parent_ids
            if pid in self._completed_results
        }

    def _enqueue_and_wait(
        self, node: DagNode, messages: list[dict[str, Any]]
    ) -> str | None:
        """Submit *node* to the Celery broker, block until complete, then
        persist the result to the History table.

        Returns the ``str(history_row.id)`` on successful DB write, or
        ``None`` if the DB write fails (task result is still cached in
        memory).
        """
        logger.info(
            "[manager] Enqueueing task_id=%r type=%r", node.task_id, node.task_type
        )
        async_result: AsyncResult = celery_app.send_task(
            _TASK_NAME,
            kwargs={
                "model": self._model,
                "messages": messages,
                "response_model_schema": self._response_model_schema,
                "response_model_class_path": self._response_model_class_path,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            },
        )

        # Block until the task finishes or the timeout elapses.
        # tasks.py returns {"result": ..., "progress": ...} – unpack both fields.
        task_output: dict[str, Any] = async_result.get(
            timeout=self._task_timeout, propagate=True
        )
        result_dict: dict[str, Any] = task_output["result"]
        progress_dict: dict[str, Any] = task_output.get("progress") or {}

        # Cache only the result so children receive compact structured context.
        self._completed_results[node.task_id] = result_dict

        # Persist to History table.
        history_id = self._persist(node, result_dict, progress_dict)
        return history_id

    def _persist(
        self,
        node: DagNode,
        result_dict: dict[str, Any],
        progress_dict: dict[str, Any],
    ) -> str | None:
        """Write the task outcome to the ``history`` table.

        Uses a caller-supplied session if available, otherwise opens an
        independent session for this write only.
        """
        close_session = False
        session: Session = self._db_session  # type: ignore[assignment]
        if session is None:
            session = SessionLocal()
            close_session = True

        try:
            role = node.role if node.task_type == "Standard" else "Debate_Coordinator"
            row = History(
                task_id=node.task_id,
                role=role,
                result=result_dict,
                progress=progress_dict if progress_dict else None,  # None only when worker sends no progress at all
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return str(row.id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[manager] Failed to persist history for task_id=%r", node.task_id
            )
            session.rollback()
            return None
        finally:
            if close_session:
                session.close()
