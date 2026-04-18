"""Celery task definitions for structured LLM inference.

Each task uses bind=True so it can call self.retry().  On connection or JSON
parsing failures the task retries up to max_retries times with exponential
backoff (countdown doubles on each attempt, starting at 2 seconds).
"""

from __future__ import annotations

import asyncio
import json
import logging
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
        return result.model_dump()

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
