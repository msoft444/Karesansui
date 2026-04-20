import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import ForeignKey

from app.base import Base


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
    run_id = Column(String, nullable=True, index=True)
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


class KnowledgeChunk(Base):
    """Stores a single knowledge-base chunk with its embedding vector for RAG retrieval.

    Each row corresponds to one physically split PDF section produced by
    document_parser.parse_and_split(). The embedding column is a fixed-width
    pgvector Vector(384) compatible with the all-MiniLM-L6-v2 model.
    """

    __tablename__ = "knowledge_chunks"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    source_pdf = Column(String, nullable=False, index=True)
    section_title = Column(String, nullable=False)
    level = Column(Integer, nullable=False)
    start_page = Column(Integer, nullable=False)
    end_page = Column(Integer, nullable=False)
    markdown_path = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(384), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )


class RoleTemplate(Base):
    """Predefined agent role templates selectable by the Planner when building a DAG.

    Each template encapsulates a system prompt, an optional list of available
    tool names, and default dynamic parameters that can be overridden at
    task-assignment time.
    """

    __tablename__ = "role_templates"
    __table_args__ = (UniqueConstraint("name", name="uq_role_templates_name"),)

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    system_prompt = Column(Text, nullable=False, default="")
    tools = Column(JSONB, nullable=False, default=list)
    default_params = Column(JSONB, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class KnowledgeDocument(Base):
    """Tracks a PDF document through the knowledge-base ingestion pipeline.

    Status transitions: uploading → splitting → vectorizing → syncing → completed | failed.
    """

    __tablename__ = "knowledge_documents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    filename = Column(String, nullable=False)
    source_pdf_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="uploading")
    error_message = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    github_path = Column(String, nullable=True)
    output_dir = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
