"""Celery task definitions for structured LLM inference.

Each task uses bind=True so it can call self.retry().  On connection or JSON
parsing failures the task retries up to max_retries times with exponential
backoff (countdown doubles on each attempt, starting at 2 seconds).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Type

from celery import Task
from pydantic import BaseModel

from app.worker import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base retry configuration
# ---------------------------------------------------------------------------
_BASE_RETRY_COUNTDOWN_SECONDS: int = 2  # first retry waits 2 s, then 4, then 8


def _backoff(self: Task) -> int:
    """Return exponential backoff delay in seconds for the current retry attempt."""
    return _BASE_RETRY_COUNTDOWN_SECONDS * (2 ** self.request.retries)


# ---------------------------------------------------------------------------
# Task: run_structured_inference
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.tasks.run_structured_inference",
)
def run_structured_inference(
    self: Task,
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_model_schema: dict[str, Any],
    response_model_class_path: str,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute a structured LLM inference request and return a validated JSON dict.

    The task accepts a serialisable representation of the target Pydantic model
    so that it can be dispatched via the Redis broker without pickling class
    objects.

    Args:
        model: Model identifier string forwarded to the inference engine.
        messages: OpenAI-format message list (role/content dicts).
        response_model_schema: JSON Schema dict produced by
            ``ResponseModel.model_json_schema()``.  Kept for documentation /
            logging purposes; the class is resolved via *response_model_class_path*.
        response_model_class_path: Dotted import path to the Pydantic BaseModel
            subclass, e.g. ``"app.schemas.SomeModel"``.  The class is imported at
            runtime inside the worker so no live class object crosses the broker.
        temperature: Sampling temperature (default 0.0).
        max_tokens: Maximum tokens to generate.
        timeout: Per-call timeout in seconds (None → module default).

    Returns:
        The validated Pydantic model serialised via ``model_dump()``.

    Raises:
        celery.exceptions.Retry: Transparently raised by ``self.retry()`` on
            transient connection or JSON parsing failures (up to max_retries).
        RuntimeError: Propagated from the inference client on non-retryable API
            errors.
    """
    # --- Resolve the Pydantic model class from its dotted path ---------------
    module_path, class_name = response_model_class_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    response_model: Type[BaseModel] = getattr(module, class_name)

    # --- Import here to avoid circular imports at module load time -----------
    from app.llm.structured_output import generate_structured

    try:
        result: BaseModel = asyncio.run(
            generate_structured(
                model=model,
                messages=messages,
                response_model=response_model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        )
        # progress captures the grounds that produced the result:
        # the full input context (messages) and inference parameters.
        # This is the agent's "thought process / grounds" as defined by
        # requirement_specification.md §6.
        return {
            "result": result.model_dump(),
            "progress": {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        }

    # Transient connection and schema-validation failures → retry with exponential backoff.
    # generate_structured() normalises all InstructorRetryException / APIConnectionError
    # variants into RuntimeError with a known prefix, so both categories are caught here:
    #   "[structured_output] connectivity-failure: ..."
    #   "[inference_client] Connection failed: ..."          (unchanged in inference_client.py)
    #   "... timed out ..."                                  (timeout messages still contain this)
    #   "[structured_output] schema-validation-failure: ..."  (replaces raw InstructorRetryException)
    except RuntimeError as exc:
        error_msg = str(exc)
        if (
            "connectivity-failure" in error_msg
            or "Connection failed" in error_msg
            or "timed out" in error_msg
            or "schema-validation-failure" in error_msg
        ):
            logger.warning(
                "[run_structured_inference] Transient error (attempt %d/%d): %s",
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            raise self.retry(exc=exc, countdown=_backoff(self))
        raise

    # Defensive fallback: catch any raw InstructorRetryException / ValidationError
    # that somehow bypasses generate_structured()'s normalisation layer.
    except Exception as exc:  # noqa: BLE001
        exc_name = type(exc).__name__
        if "InstructorRetryException" in exc_name or "ValidationError" in exc_name:
            logger.warning(
                "[run_structured_inference] Structured output validation failure "
                "(attempt %d/%d): %s",
                self.request.retries + 1,
                self.max_retries + 1,
                exc_name,
            )
            raise self.retry(exc=exc, countdown=_backoff(self))
        raise


# ---------------------------------------------------------------------------
# Task: process_knowledge_document
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    max_retries=0,
    name="app.tasks.process_knowledge_document",
)
def process_knowledge_document(
    self: Task,
    *,
    doc_id: str,
    pdf_path: str,
    output_dir: str,
) -> dict[str, Any]:
    """Run the full knowledge-base ingestion pipeline for a single PDF document.

    Stages:
        splitting   — parse_and_split() splits the PDF by TOC and converts to Markdown.
        vectorizing — each section's Markdown content is embedded and stored in pgvector.
        syncing     — converted Markdown files are pushed to the GitHub repository.

    KnowledgeDocument.status is updated at each stage transition so the frontend
    can display real-time pipeline progress.

    Args:
        doc_id:     UUID string of the KnowledgeDocument tracking record.
        pdf_path:   Absolute path to the uploaded PDF file.
        output_dir: Directory where split PDFs and Markdown files will be written.

    Returns:
        Dict with ``doc_id``, ``status``, and ``chunk_count`` on success.
    """
    import uuid as _uuid

    from app.database import SessionLocal
    from app.models import DocumentStatus, KnowledgeDocument
    from app.services import document_parser, github_sync, vector_store

    db = SessionLocal()

    def _set_status(new_status: DocumentStatus, **fields: Any) -> None:
        """Update KnowledgeDocument.status and any extra fields in a single commit."""
        doc = db.get(KnowledgeDocument, _uuid.UUID(doc_id))
        if doc is None:
            return
        doc.status = new_status
        for key, val in fields.items():
            setattr(doc, key, val)
        db.commit()

    try:
        # Stage 1: split PDF into sections and convert each to Markdown
        _set_status(DocumentStatus.splitting)
        sections = document_parser.parse_and_split(pdf_path, output_dir)

        # parse_and_split performs both TOC-based splitting and MarkItDown
        # conversion in a single call; transition to "converting" status here
        # to reflect the completed conversion stage before vectorization begins.
        _set_status(DocumentStatus.converting)

        # Determine total page count from the original PDF
        try:
            import pypdf  # type: ignore[import]
            total_pages: int = len(pypdf.PdfReader(pdf_path).pages)
        except Exception:
            total_pages = sections[-1]["end"] if sections else 0

        # Stage 2: embed each section and persist to pgvector
        _set_status(DocumentStatus.vectorizing, page_count=total_pages)
        chunk_count = 0
        for section in sections:
            md_path: str | None = section.get("markdown")
            if md_path:
                try:
                    content = Path(md_path).read_text(encoding="utf-8")
                except Exception:
                    content = section.get("title", "")
            else:
                content = section.get("title", "")

            if not content.strip():
                continue

            vector_store.insert_chunk(
                db=db,
                source_pdf=pdf_path,
                section_title=section["title"],
                level=section["level"],
                start_page=section["start"],
                end_page=section["end"],
                content=content,
                markdown_path=md_path,
                document_id=doc_id,
            )
            chunk_count += 1

        db.commit()

        # Stage 3: push Markdown files to GitHub repository.
        # Each document is stored under a unique per-document subtree
        # (knowledge_base/<doc_id>/) so that per-document deletion via
        # DELETE /knowledge/{doc_id} targets exactly the right repository path.
        _set_status(DocumentStatus.syncing, chunk_count=chunk_count)
        doc_repo_base = f"knowledge_base/{doc_id}"
        try:
            github_sync.push_markdown_files(output_dir, repo_base_path=doc_repo_base)
            github_path: str = doc_repo_base
        except RuntimeError as exc:
            # GitHub sync failed (e.g. GITHUB_TOKEN not set or repository
            # inaccessible). Mark the document as failed so the frontend can
            # display a clear failure indicator instead of a misleading
            # "completed" status for a document whose files were never synced.
            logger.warning(
                "[process_knowledge_document] GitHub sync failed for doc %s: %s",
                doc_id,
                exc,
            )
            _set_status(DocumentStatus.failed, error_message=f"GitHub sync failed: {exc}")
            return {"doc_id": doc_id, "status": "failed", "chunk_count": chunk_count}

        _set_status(DocumentStatus.completed, chunk_count=chunk_count, github_path=github_path)
        logger.info(
            "[process_knowledge_document] Completed doc %s: %d chunks", doc_id, chunk_count
        )
        return {"doc_id": doc_id, "status": "completed", "chunk_count": chunk_count}

    except Exception as exc:
        logger.exception(
            "[process_knowledge_document] Pipeline failed for doc %s", doc_id
        )
        try:
            _set_status(DocumentStatus.failed, error_message=str(exc))
        except Exception:
            pass
        raise

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task: run_orchestration_pipeline
# ---------------------------------------------------------------------------

# Default Planner system prompt — instructs the LLM to output a strict DAG JSON.
_PLANNER_SYSTEM_PROMPT = (
    "You are the Planner agent in the Karesansui multi-agent system.\n"
    "Analyze the user query and decompose it into a Directed Acyclic Graph (DAG) of tasks.\n\n"
    "You MUST respond with a valid JSON object that contains exactly one top-level key 'tasks'\n"
    "whose value is a non-empty array of task objects.  No markdown fences, no prose — pure JSON only.\n\n"
    "Each task object MUST contain these fields:\n"
    "  task_id       : a unique non-empty string identifying this task\n"
    "  task_type     : exactly the string 'Standard' or 'Debate'\n"
    "  parent_ids    : array of task_id strings this task depends on (empty array for root tasks)\n"
    "  dynamic_params: object of arbitrary key/value pairs (use empty object {} if none)\n\n"
    "For task_type=Standard also include:\n"
    "  role          : one of: Data_Gatherer, Logical_Analyst, Critical_Reviewer, Report_Synthesizer, Translator\n\n"
    "For task_type=Debate also include:\n"
    "  participants  : non-empty array of role names chosen from: Advocate, Disrupter, Persona_Writer\n"
    "  mediator      : exactly 'Mediator'\n\n"
    "Do NOT include 'role' in Debate tasks. Do NOT include 'participants' or 'mediator' in Standard tasks.\n"
    "Always end the DAG with a Report_Synthesizer or Persona_Writer task that synthesizes the final answer."
)

# Settings key names in the GlobalSettings table.
_SETTING_MODEL = "model"
_SETTING_TEMPERATURE = "temperature"
_SETTING_MAX_TOKENS = "max_tokens"
_SETTING_PLANNER_SYSTEM_PROMPT = "planner_system_prompt"
_SETTING_RESPONSE_MODEL_CLASS_PATH = "response_model_class_path"


def _load_settings(db: Any) -> dict[str, Any]:
    """Read orchestration settings from the GlobalSettings table.

    Returns a dict with keys: model, temperature, max_tokens,
    planner_system_prompt, response_model_class_path.  Each key falls back to
    a sensible default when absent from the DB.
    """
    import os as _os
    from app.models import GlobalSettings as _GS

    defaults: dict[str, Any] = {
        _SETTING_MODEL: _os.environ.get("INFERENCE_MODEL", "karesansui"),
        _SETTING_TEMPERATURE: 0.0,
        _SETTING_MAX_TOKENS: 2048,
        _SETTING_PLANNER_SYSTEM_PROMPT: _PLANNER_SYSTEM_PROMPT,
        _SETTING_RESPONSE_MODEL_CLASS_PATH: "app.schemas.ReportSynthesizerResponse",
    }
    for key in list(defaults.keys()):
        row = db.get(_GS, key)
        if row is not None:
            defaults[key] = row.value
    return defaults


@celery_app.task(
    bind=True,
    max_retries=2,
    name="app.tasks.run_orchestration_pipeline",
)
def run_orchestration_pipeline(
    self: Task,
    *,
    user_query: str,
    run_id: str,
) -> dict[str, Any]:
    """Run the full orchestration pipeline for a user query.

    Stages:
        1. Load inference settings from GlobalSettings (with defaults).
        2. Call the Planner LLM to generate a DAG JSON.
        3. Parse and validate the DAG with DagParser.
        4. Execute all tasks via OrchestratorManager (blocks until done).

    The *run_id* is supplied by the HTTP endpoint so the caller can redirect
    the user to the Live Trace view before execution completes.

    Args:
        user_query: The raw user query string.
        run_id:     Pre-assigned run identifier returned to the frontend.

    Returns:
        Dict with ``run_id`` and a ``task_results`` mapping on success.
    """
    from app.database import SessionLocal as _SessionLocal
    from app.llm.structured_output import generate_structured as _generate_structured
    from app.orchestrator.dag_parser import DagParser as _DagParser
    from app.orchestrator.manager import OrchestratorManager as _OrchestratorManager
    from app.schemas import DagPayload as _DagPayload
    from app.schemas import ReportSynthesizerResponse as _ReportSynthesizerResponse

    db = _SessionLocal()
    # Tracks which pipeline stage was active when a terminal exception occurs.
    # Initialized before the try block so the outer except can always read it.
    _pipeline_stage = "planner"
    try:
        settings = _load_settings(db)
        model: str = settings[_SETTING_MODEL]
        temperature: float = float(settings[_SETTING_TEMPERATURE])
        max_tokens: int = int(settings[_SETTING_MAX_TOKENS])
        planner_prompt: str = settings[_SETTING_PLANNER_SYSTEM_PROMPT]
        response_class_path: str = settings[_SETTING_RESPONSE_MODEL_CLASS_PATH]

        # --- Stage 1: Invoke the Planner LLM to produce a structured DAG ----
        # Use generate_structured() with DagPayload as the response model so
        # the instructor library enforces the DAG JSON schema at the logits
        # level, satisfying requirement_specification.md §9 (Error Handling).
        planner_messages: list[dict[str, Any]] = [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": user_query},
        ]
        # Planner needs room for the full DAG JSON — use 4 × the agent token
        # budget but cap at 8192 to avoid overshooting model limits.
        planner_max_tokens = min(max_tokens * 4, 8192)

        # Write planner-started lifecycle row so GET /history and
        # GET /stream/progress surface the run state before the first
        # structured-output call completes or fails.  Check for an existing
        # row first so Celery retries do not create duplicates.
        try:
            from app.models import History as _HistoryPS
            _ps_task_id = f"planner_started_{run_id}"
            if not db.query(_HistoryPS).filter(
                _HistoryPS.task_id == _ps_task_id
            ).first():
                db.add(_HistoryPS(
                    run_id=run_id,
                    task_id=_ps_task_id,
                    role="Planner",
                    result={"status": "planner-started"},
                    progress=None,
                ))
                db.commit()
        except Exception:
            # Rollback the failed transaction so the same session remains
            # usable for subsequent orchestration writes.
            db.rollback()
            logger.warning(
                "[run_orchestration_pipeline] Could not persist planner-started row"
                " for run_id=%s",
                run_id,
            )

        try:
            dag_schema_obj: _DagPayload = asyncio.run(
                _generate_structured(
                    model=model,
                    messages=planner_messages,
                    response_model=_DagPayload,
                    temperature=0.0,  # Deterministic planning
                    max_tokens=planner_max_tokens,
                )
            )
        except Exception as exc:
            logger.error(
                "[run_orchestration_pipeline] Planner structured generation failed: %s", exc
            )
            raise self.retry(exc=exc, countdown=_backoff(self))

        logger.info(
            "[run_orchestration_pipeline] Planner produced %d task(s)",
            len(dag_schema_obj.tasks),
        )

        # --- Stage 2: Parse and validate the DAG ----------------------------
        # Convert the Pydantic DagPayload back to a plain dict so DagParser
        # can validate cross-references and detect cycles as usual.
        dag_payload: dict[str, Any] = dag_schema_obj.model_dump()
        try:
            parser = _DagParser(dag_payload)
            nodes = parser.topological_sort()
        except Exception as exc:
            logger.error(
                "[run_orchestration_pipeline] DAG validation error: %s", exc
            )
            raise self.retry(exc=exc, countdown=_backoff(self))

        # Stages 1 (planner LLM) and 2 (DAG validation) have completed.
        # From this point forward any terminal failure is orchestration-level.
        _pipeline_stage = "orchestration"

        # --- Stage 3: Resolve the structured-output Pydantic model -----------
        try:
            module_path, class_name = response_class_path.rsplit(".", 1)
            import importlib as _importlib
            _module = _importlib.import_module(module_path)
            response_model_cls = getattr(_module, class_name)
            response_model_schema = response_model_cls.model_json_schema()
        except Exception as exc:
            logger.warning(
                "[run_orchestration_pipeline] Could not resolve response model %r, "
                "falling back to ReportSynthesizerResponse: %s",
                response_class_path,
                exc,
            )
            response_model_cls = _ReportSynthesizerResponse
            response_model_schema = _ReportSynthesizerResponse.model_json_schema()
            response_class_path = "app.schemas.ReportSynthesizerResponse"

        # --- Stage 4: Execute all tasks via OrchestratorManager --------------
        manager = _OrchestratorManager(
            model=model,
            response_model_class_path=response_class_path,
            response_model_schema=response_model_schema,
            task_timeout=float(os.environ.get("ORCHESTRATOR_TASK_TIMEOUT", "300")),
            db_session=db,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        task_results = manager.run(nodes, user_query, run_id=run_id)
        logger.info(
            "[run_orchestration_pipeline] run_id=%s completed with %d tasks",
            run_id,
            len(task_results),
        )
        return {"run_id": run_id, "task_results": task_results}

    except Exception as exc:
        # Only write a terminal-failure row when the pipeline is truly dead
        # (not merely being retried by Celery).
        from celery.exceptions import Retry as _CeleryRetry
        if not isinstance(exc, _CeleryRetry):
            # Use stage-specific status so history / live trace can distinguish
            # planner failures from orchestration-level failures.
            _terminal_status = (
                "planner-failed" if _pipeline_stage == "planner" else "orchestration-failed"
            )
            # Classify the error type so consumers can distinguish connectivity
            # problems from schema-validation failures without parsing the error string.
            _err_msg = str(exc)
            if "connectivity-failure" in _err_msg or "Connection failed" in _err_msg:
                _error_type = "connectivity"
            elif "schema-validation-failure" in _err_msg:
                _error_type = "validation"
            else:
                _error_type = "inference"
            try:
                from app.models import History as _History
                db.add(_History(
                    run_id=run_id,
                    task_id=f"pipeline_failed_{run_id}",
                    role="Planner",
                    result={
                        "status": _terminal_status,
                        "error": _err_msg[:800],
                        "error_type": _error_type,
                    },
                    progress=None,
                ))
                db.commit()
            except Exception:
                logger.exception(
                    "[run_orchestration_pipeline] Could not persist failure row for run_id=%s",
                    run_id,
                )
        logger.exception(
            "[run_orchestration_pipeline] Pipeline failed for run_id=%s", run_id
        )
        raise

    finally:
        db.close()
