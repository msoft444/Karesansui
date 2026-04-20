"""Celery task definitions for structured LLM inference.

Each task uses bind=True so it can call self.retry().  On connection or JSON
parsing failures the task retries up to max_retries times with exponential
backoff (countdown doubles on each attempt, starting at 2 seconds).
"""

from __future__ import annotations

import asyncio
import json
import logging
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

    # Transient connection failures → retry with exponential backoff
    except RuntimeError as exc:
        error_msg = str(exc)
        if "Connection failed" in error_msg or "timed out" in error_msg:
            logger.warning(
                "[run_structured_inference] Transient error (attempt %d/%d): %s",
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            raise self.retry(exc=exc, countdown=_backoff(self))
        raise

    # JSON / schema validation failures from instructor → retry with backoff
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
