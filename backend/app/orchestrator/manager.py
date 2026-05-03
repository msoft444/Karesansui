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
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import History
from app.orchestrator.dag_parser import DagNode
from app.orchestrator.debate_controller import DebateController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at module load; injected via environment variable)
# ---------------------------------------------------------------------------

_DEFAULT_TASK_TIMEOUT: float = float(
    os.environ.get("ORCHESTRATOR_TASK_TIMEOUT", "300")
)
"""Seconds to wait for a single task before raising TimeoutError."""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_INFERENCE_MAX_RETRIES: int = 3
_INFERENCE_BASE_RETRY_COUNTDOWN: float = 2.0

# Cap for the per-inference-call timeout forwarded to generate_structured().
# This bounds a single LLM HTTP request independently of the overall
# ORCHESTRATOR_TASK_TIMEOUT so that a stalled call does not hold the task
# for the full task-level budget (300 s by default).
_DEFAULT_INFERENCE_CALL_TIMEOUT: float = float(
    os.environ.get("INFERENCE_CALL_TIMEOUT", "90")
)


def _run_inference_direct(
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_model_class_path: str,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    json_mode: bool = False,
    timeout: float | None = None,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Run structured inference in-process without dispatching a Celery subtask.

    OrchestratorManager is called from inside ``run_orchestration_pipeline``,
    which is itself a Celery task.  Celery forbids blocking on a dispatched
    subtask result from within a task (raises RuntimeError: "Never call
    result.get() within a task!").  This helper calls ``generate_structured``
    directly, bypassing the broker entirely, while preserving the same
    transient-error retry contract as ``app.tasks.run_structured_inference``
    (up to ``_INFERENCE_MAX_RETRIES`` retries with exponential back-off for
    connectivity / timeout failures only; schema-validation failures are NOT
    retried at the outer level since instructor already exhausts its internal
    retries before raising).

    Parameters
    ----------
    json_mode:
        When ``True``, uses ``instructor.Mode.JSON`` (application-layer Pydantic
        validation) instead of the default ``Mode.JSON_SCHEMA`` (logits-level
        schema enforcement).  Pass ``True`` for inference backends that do not
        implement ``response_format.json_schema`` at the logits level (e.g.
        mlx_lm).  Defaults to ``False`` so that backends which support native
        JSON Schema enforcement are not downgraded.

    The returned dict matches the ``{"result": ..., "progress": ...}`` envelope
    produced by the ``run_structured_inference`` Celery task.
    """
    import asyncio
    import importlib
    import time

    # Deferred import to avoid circular imports at module load time.
    from app.llm.structured_output import generate_structured

    module_path, class_name = response_model_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    response_model = getattr(module, class_name)

    last_exc: BaseException | None = None
    for attempt in range(_INFERENCE_MAX_RETRIES + 1):
        try:
            result = asyncio.run(
                generate_structured(
                    model=model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=max_retries,
                    json_mode=json_mode,
                    timeout=timeout,
                )
            )
            return {
                "result": result.model_dump(),
                "progress": {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            }
        except RuntimeError as exc:
            error_msg = str(exc)
            # Only retry transient network/timeout failures at the outer level.
            # Schema-validation failures are already retried internally by
            # instructor (via max_retries passed to generate_structured); a
            # second outer attempt with the same model and prompt almost never
            # succeeds and wastes wall-clock time, causing T4/Report_Synthesizer
            # to block far longer than the dc polling window.
            if (
                "connectivity-failure" in error_msg
                or "Connection failed" in error_msg
                or "timed out" in error_msg
            ):
                last_exc = exc
                if attempt < _INFERENCE_MAX_RETRIES:
                    wait = _INFERENCE_BASE_RETRY_COUNTDOWN * (2 ** attempt)
                    logger.warning(
                        "[_run_inference_direct] Transient error (attempt %d/%d), "
                        "retrying in %.1f s: %s",
                        attempt + 1,
                        _INFERENCE_MAX_RETRIES + 1,
                        wait,
                        error_msg,
                    )
                    time.sleep(wait)
                    continue
            raise
        except Exception as exc:  # noqa: BLE001
            # Defensive fallback for InstructorRetryException / ValidationError
            # that bypasses generate_structured()'s normalisation layer.
            # Do NOT retry at the outer level — instructor already exhausted its
            # internal retries; repeating with the same prompt and model is unlikely
            # to recover and only extends wall-clock time.
            raise
    # All retries exhausted — re-raise the last transient exception.
    raise last_exc  # type: ignore[misc]


def _extract_search_query(user_query: str) -> str:
    """Derive a compact, search-engine-friendly query from a verbose task instruction.

    When the Planner does not supply a ``search_query`` in ``dynamic_params``,
    the raw user instruction (e.g. ``"Create a detailed report about X.  Use web
    search..."`` ) would be forwarded to DuckDuckGo as-is, yielding poor results.
    This helper strips common instructional prefixes and suffixes so that the
    actual subject entity is extracted and used as the search query.

    Falls back to the original query when no simplification applies.
    """
    import re as _re

    # Pattern: "report/summary/analysis/overview about X" — extract X
    m = _re.search(
        r"\b(?:report|summary|analysis|overview|information)\s+"
        r"(?:about|on|regarding|for)\s+(.+?)"
        r"(?:\.\s|\?\s|$|,?\s*(?:use|using|include|with)\s)",
        user_query,
        _re.IGNORECASE,
    )
    if m:
        subject = m.group(1).strip().rstrip(".,'\"")
        if subject and len(subject) >= 3:
            return subject

    # Fallback pattern: "about X" anywhere in the query
    m = _re.search(
        r"\babout\s+(.+?)(?:\.\s|\?\s|$|,?\s*(?:use|include|with)\s)",
        user_query,
        _re.IGNORECASE,
    )
    if m:
        subject = m.group(1).strip().rstrip(".,'\"")
        if subject and len(subject) >= 3:
            return subject

    return user_query


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
        task_timeout: float = _DEFAULT_TASK_TIMEOUT,
        db_session: Session | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> None:
        self._model = model
        self._response_model_class_path = response_model_class_path
        self._response_model_schema = response_model_schema
        self._task_timeout = task_timeout
        self._db_session = db_session
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._json_mode = json_mode

        # task_id (str) → completed result dict extracted from the Celery backend.
        self._completed_results: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        nodes: list[DagNode],
        user_query: str,
        *,
        run_id: str | None = None,
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
        run_id:
            Optional externally-provided run identifier.  When supplied (e.g.
            by the ``/api/query/`` endpoint so it can return the id
            immediately), this value is used instead of a freshly generated
            one.  If ``None``, a new UUID hex string is generated.

        Returns
        -------
        dict[str, dict[str, Any]]
            Mapping of ``task_id`` to the structured result dict.
        """
        # Use the caller-supplied run_id when provided so the HTTP endpoint
        # can return it before orchestration completes; otherwise generate one.
        run_id = run_id if run_id is not None else uuid.uuid4().hex

        # Persist the Planner DAG topology so the management console can
        # reconstruct and visualise the full graph for this run.
        self._persist_planner_dag(nodes, run_id=run_id)

        from app.services.role_templates import TemplateNotFoundError

        for node in nodes:
            if node.task_type == "Debate":
                # Delegate to DebateController for round-robin multi-agent debate.
                parent_results = self._collect_parent_results(node.parent_ids)
                controller = DebateController(
                    model=self._model,
                    task_timeout=self._task_timeout,
                    db_session=self._db_session,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    json_mode=self._json_mode,
                    run_id=run_id,
                )
                try:
                    final_result, debate_progress = controller.run(
                        node, parent_results, user_query
                    )
                except TemplateNotFoundError as exc:
                    logger.error(
                        "[manager] RoleTemplate not found for debate task_id=%r: %s",
                        node.task_id,
                        exc,
                    )
                    self._persist(
                        node,
                        {"error": str(exc), "error_type": "template_not_found"},
                        {"template_lookup_failed": True},
                        run_id=run_id,
                    )
                    raise
                # Cache the mediator's final conclusion for child tasks.
                self._completed_results[node.task_id] = final_result
                # Persist the debate summary row via the standard _persist path.
                history_id = self._persist(node, final_result, debate_progress, run_id=run_id)
                logger.info(
                    "[manager] debate task_id=%r completed; history_id=%r",
                    node.task_id,
                    history_id,
                )
            else:
                try:
                    messages, tmpl_meta = self._build_messages(node, user_query)
                except TemplateNotFoundError as exc:
                    logger.error(
                        "[manager] RoleTemplate not found for task_id=%r role=%r: %s",
                        node.task_id,
                        node.role,
                        exc,
                    )
                    self._persist(
                        node,
                        {"error": str(exc), "error_type": "template_not_found"},
                        {"template_lookup_failed": True, "role_name": node.role},
                        run_id=run_id,
                    )
                    raise
                history_id = self._enqueue_and_wait(
                    node, messages, run_id=run_id, template_meta=tmpl_meta,
                    user_query=user_query,
                )
                logger.info(
                    "[manager] task_id=%r completed; history_id=%r",
                    node.task_id,
                    history_id,
                )

        return dict(self._completed_results)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist_planner_dag(self, nodes: list[DagNode], *, run_id: str) -> str | None:
        """Write a Planner DAG row to History before task execution begins.

        The row uses ``role='Planner'`` and stores the full DAG topology inside
        ``result.tasks``.  The management console's DAG visualiser queries for
        these rows to populate the run selector and reconstruct node graphs.
        """
        serialized_tasks = [
            {
                "task_id": node.task_id,
                "task_type": node.task_type,
                "role": node.role,
                "participants": node.participants,
                "mediator": node.mediator,
                "parent_ids": node.parent_ids,
                "dynamic_params": node.dynamic_params,
            }
            for node in nodes
        ]
        close_session = False
        session: Session = self._db_session  # type: ignore[assignment]
        if session is None:
            session = SessionLocal()
            close_session = True
        try:
            row = History(
                run_id=run_id,
                task_id=f"planner_run_{run_id}",
                role="Planner",
                result={"tasks": serialized_tasks},
                progress=None,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            logger.info("[manager] persisted Planner DAG; history_id=%r", str(row.id))
            return str(row.id)
        except Exception:  # noqa: BLE001
            logger.exception("[manager] Failed to persist Planner DAG row")
            session.rollback()
            return None
        finally:
            if close_session:
                session.close()

    def _build_messages(
        self, node: DagNode, user_query: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Resolve RoleTemplate from DB and construct the OpenAI-format message list.

        Returns
        -------
        tuple[list[dict], dict]
            ``(messages, template_metadata)`` where ``template_metadata``
            contains ``template_name``, ``resolved_params``, and ``tools``
            for persistence in the History progress column.

        Raises
        ------
        TemplateNotFoundError
            When the node's role has no matching RoleTemplate record in the DB.
        """
        from app.services.role_templates import resolve_role_template

        role_name = node.role if node.task_type == "Standard" else "Debate_Coordinator"

        close_session = False
        session: Session = self._db_session  # type: ignore[assignment]
        if session is None:
            session = SessionLocal()
            close_session = True
        try:
            resolved = resolve_role_template(role_name, node.dynamic_params, session)
        finally:
            if close_session:
                session.close()

        system_content = resolved.system_prompt

        # Inject merged (template default + Planner override) params when present.
        if resolved.resolved_params:
            params_str = "; ".join(
                f"{k}={v!r}" for k, v in resolved.resolved_params.items()
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

        template_metadata: dict[str, Any] = {
            "template_name": resolved.template_name,
            "resolved_params": resolved.resolved_params,
            "tools": resolved.tools,
        }
        return messages, template_metadata

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
        self,
        node: DagNode,
        messages: list[dict[str, Any]],
        *,
        run_id: str,
        template_meta: dict[str, Any] | None = None,
        user_query: str = "",
    ) -> str | None:
        """Submit *node* to the Celery broker, block until complete, then
        persist the result to the History table.

        Returns the ``str(history_row.id)`` on successful DB write, or
        ``None`` if the DB write fails (task result is still cached in
        memory).
        """
        logger.info(
            "[manager] Running task_id=%r type=%r", node.task_id, node.task_type
        )

        # Dispatch tools declared by the template before inference so that
        # research results are injected into the prompt as grounding evidence.
        _tool_results: list = []
        _declared_tools: list[str] = (template_meta or {}).get("tools") or []
        if _declared_tools:
            from app.services.tool_dispatch import (
                dispatch_tools,
                format_tool_results_for_prompt,
            )
            # Prefer a template-specific search_query param when present
            # (e.g. Data_Gatherer uses resolved_params["search_query"]), and
            # fall back to a cleaned-up version of the user query so that
            # instructional phrases ("Create a detailed report about ...") are
            # stripped before the query is sent to DuckDuckGo.
            _dispatch_query: str = (
                ((template_meta or {}).get("resolved_params") or {}).get("search_query")
                or _extract_search_query(user_query)
            )
            _tool_results = dispatch_tools(_declared_tools, _dispatch_query)
            _tool_prompt = format_tool_results_for_prompt(_tool_results)
            if _tool_prompt:
                # Embed tool evidence into the first user message (RAG pattern).
                # External content is placed at user-context trust level — not
                # system-instruction authority — and does not add a standalone
                # untrusted message turn.  messages[1] is always the user_query
                # turn constructed by _build_messages; the guard ensures we never
                # mutate an unexpected layout.
                _amended = list(messages)
                if len(_amended) > 1 and _amended[1]["role"] == "user":
                    # Place evidence BEFORE the user query so the model reads
                    # the research context first and grounds its response in it.
                    _amended[1] = {
                        "role": "user",
                        "content": _tool_prompt + "\n\n" + _amended[1]["content"],
                    }
                    messages = _amended

        # Call inference directly (in-process) rather than dispatching a
        # Celery subtask.  OrchestratorManager runs inside the
        # run_orchestration_pipeline Celery task; Celery forbids blocking on
        # a dispatched subtask result from within a task with result.get().
        task_output: dict[str, Any] = _run_inference_direct(
            model=self._model,
            messages=messages,
            response_model_class_path=self._response_model_class_path,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            json_mode=self._json_mode,
            # Cap per-call timeout so a single stalled LLM request does not
            # hold the task for the full task-level budget (300 s default).
            timeout=min(self._task_timeout, _DEFAULT_INFERENCE_CALL_TIMEOUT),
            # Use the same instructor retry budget as the Planner so that small
            # quantized models (e.g. 2-bit) get enough attempts to produce
            # valid structured JSON.  The Planner uses max_retries=5 and
            # succeeds; the default of 1 is too low for Standard tasks.
            max_retries=5,
        )
        result_dict: dict[str, Any] = task_output["result"]
        progress_dict: dict[str, Any] = task_output.get("progress") or {}

        # Enrich progress with resolved template metadata for history inspection.
        if template_meta:
            progress_dict["template_name"] = template_meta.get("template_name")
            progress_dict["resolved_params"] = template_meta.get("resolved_params")
            progress_dict["tools"] = template_meta.get("tools")
        # Record tool dispatch results (eligibility, status, diagnostics) for
        # history inspection regardless of whether any results were injected.
        if _tool_results:
            progress_dict["tool_results"] = [r.to_dict() for r in _tool_results]

        # Cache only the result so children receive compact structured context.
        self._completed_results[node.task_id] = result_dict

        # Persist to History table.
        history_id = self._persist(node, result_dict, progress_dict, run_id=run_id)
        return history_id

    def _persist(
        self,
        node: DagNode,
        result_dict: dict[str, Any],
        progress_dict: dict[str, Any],
        *,
        run_id: str,
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
                run_id=run_id,
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
