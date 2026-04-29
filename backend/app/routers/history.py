import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import History
from app.schemas import HistoryCreate, HistoryResponse, HistoryUpdate, RunDetail, RunSummary
from app.services.history_runs import aggregate_run_detail, aggregate_runs

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=List[HistoryResponse])
def list_history(
    task_id: str | None = None,
    run_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Return all history records, optionally filtered by task_id or run_id."""
    query = db.query(History)
    if task_id:
        query = query.filter(History.task_id == task_id)
    if run_id:
        query = query.filter(History.run_id == run_id)
    return query.order_by(History.created_at.desc()).all()


@router.get("/runs", response_model=List[RunSummary])
def list_runs(db: Session = Depends(get_db)):
    """Return one RunSummary per Query Run, ordered by created_at descending."""
    records = db.query(History).order_by(History.created_at.asc()).all()
    # aggregate_runs already returns summaries sorted newest-first by created_at.
    return aggregate_runs(records)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)):
    """Return the full RunDetail for a single Query Run."""
    records = (
        db.query(History)
        .filter(History.run_id == run_id)
        .order_by(History.created_at.asc())
        .all()
    )
    detail = aggregate_run_detail(run_id, records)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return detail


@router.get("/{history_id}", response_model=HistoryResponse)
def get_history(history_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return a single history record by ID."""
    record = db.get(History, history_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="History record not found"
        )
    return record


@router.post("", response_model=HistoryResponse, status_code=status.HTTP_201_CREATED)
def create_history(payload: HistoryCreate, db: Session = Depends(get_db)):
    """Record a new agent task execution."""
    record = History(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.put("/{history_id}", response_model=HistoryResponse)
def update_history(
    history_id: uuid.UUID, payload: HistoryUpdate, db: Session = Depends(get_db)
):
    """Partially update a history record (e.g. append translation result)."""
    record = db.get(History, history_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="History record not found"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    db.commit()
    db.refresh(record)
    return record
