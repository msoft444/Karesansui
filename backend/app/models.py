import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class History(Base):
    """Records each agent task execution: role, structured result, and progress log."""

    __tablename__ = "history"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    task_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    result = Column(JSONB, nullable=True)
    progress = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )


class GlobalSettings(Base):
    """Key-value store for dynamic system-wide configuration (inference params, RAG, DAG controls, etc.)."""

    __tablename__ = "global_settings"

    key = Column(String, primary_key=True, nullable=False)
    value = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
