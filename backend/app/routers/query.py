"""Query submission router.

Provides the ``POST /api/query/`` endpoint that accepts a user query, enqueues
the full orchestration pipeline as a background Celery task, and immediately
returns the ``run_id`` so the frontend can redirect to the Live Trace view.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.schemas import QueryRequest, QueryResponse

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=QueryResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_query(payload: QueryRequest) -> QueryResponse:
    """Enqueue a new orchestration run and return the run_id immediately.

    The orchestration pipeline (Planner → DAG → OrchestratorManager) is
    executed asynchronously in a Celery worker.  The returned ``run_id`` can
    be used to track progress via ``GET /stream?run_id=<id>`` or the DAG
    Visualizer.
    """
    if not payload.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="クエリを入力してください。",
        )

    # Pre-generate the run_id so the endpoint can return it before the
    # pipeline completes.  The same id is passed into the Celery task and
    # forwarded to OrchestratorManager.run() as the shared run identifier
    # for all History rows produced during this run.
    run_id: str = uuid.uuid4().hex

    # Import lazily to avoid circular imports at module load time and to keep
    # the task registry decoupled from the router layer.
    from app.tasks import run_orchestration_pipeline  # noqa: PLC0415

    run_orchestration_pipeline.delay(user_query=payload.query, run_id=run_id)

    return QueryResponse(run_id=run_id)
