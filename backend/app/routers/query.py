"""Query submission router.

Provides the ``POST /api/query/`` endpoint that accepts a user query, enqueues
the full orchestration pipeline as a background Celery task, and immediately
returns the ``run_id`` so the frontend can redirect to the Live Trace view.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import History
from app.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=QueryResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_query(payload: QueryRequest, db: Session = Depends(get_db)) -> QueryResponse:
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

    # Write a bootstrap History row synchronously BEFORE enqueuing the task so
    # that GET /history and GET /stream/progress always see at least one record
    # the moment the 202 response reaches the caller.
    #
    # Failure contract (step 1 requirement):
    #   - If the bootstrap DB write fails  → do NOT enqueue; return 503.
    #   - If the broker enqueue fails      → mark the bootstrap row as
    #     enqueue_failed and return 503 so no phantom "queued" record is left.
    bootstrap_task_id = f"bootstrap_{run_id}"
    bootstrap_row = History(
        run_id=run_id,
        task_id=bootstrap_task_id,
        role="Planner",
        result={"status": "queued"},
        progress=None,
    )
    try:
        db.add(bootstrap_row)
        db.commit()
        db.refresh(bootstrap_row)
    except Exception:
        logger.exception(
            "[submit_query] Could not persist bootstrap row for run_id=%s", run_id
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="タスクの受付に失敗しました。しばらくしてから再試行してください。",
        )

    # Import lazily to avoid circular imports at module load time and to keep
    # the task registry decoupled from the router layer.
    from app.tasks import run_orchestration_pipeline  # noqa: PLC0415

    try:
        run_orchestration_pipeline.delay(user_query=payload.query, run_id=run_id)
    except Exception:
        logger.exception(
            "[submit_query] Could not enqueue pipeline for run_id=%s; marking bootstrap row failed",
            run_id,
        )
        # Compensate: use a fresh, independent session so that the update
        # is not affected by the current session's state after the enqueue
        # failure.  This guarantees no phantom "queued" row survives.
        comp_db = SessionLocal()
        try:
            comp_row = comp_db.query(History).filter_by(task_id=bootstrap_task_id).first()
            if comp_row is not None:
                comp_row.result = {"status": "enqueue_failed"}
                comp_db.commit()
        except Exception:
            logger.exception(
                "[submit_query] Could not update bootstrap row to enqueue_failed for run_id=%s",
                run_id,
            )
            comp_db.rollback()
        finally:
            comp_db.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="タスクのキューへの追加に失敗しました。しばらくしてから再試行してください。",
        )

    return QueryResponse(run_id=run_id)
