from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# History schemas
# ---------------------------------------------------------------------------


class HistoryCreate(BaseModel):
    """Payload for recording a new agent task execution."""

    run_id: str | None = None
    task_id: str
    role: str
    result: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    """Full representation of a History record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: str | None
    task_id: str
    role: str
    result: dict[str, Any] | None
    progress: dict[str, Any] | None
    created_at: datetime


class HistoryUpdate(BaseModel):
    """Partial update for a History record (e.g. appending translation result)."""

    result: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# GlobalSettings schemas
# ---------------------------------------------------------------------------


class SettingUpdate(BaseModel):
    """Payload for creating or replacing a single global setting.

    `value` accepts any valid JSONB type (int, float, bool, str, list, dict,
    or None) to accommodate settings like Top-K (int), max_debate_rounds (int),
    feature flags (bool), model IDs (str), etc.
    """

    value: Any


class SettingResponse(BaseModel):
    """Full representation of a GlobalSettings record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    updated_at: datetime


# ---------------------------------------------------------------------------
# Debate-node structured-output schemas
# ---------------------------------------------------------------------------


class DebateParticipantResponse(BaseModel):
    """Structured output for Advocate, Disrupter, and other debate participant agents.

    Used as the ``response_model_class_path`` target in
    ``app.tasks.run_structured_inference`` during debate rounds.
    """

    argument: str
    support_points: list[str]


class MediatorResponse(BaseModel):
    """Structured output for the Mediator agent's per-round consensus evaluation.

    ``consensus_reached`` acts as the termination flag: when True the
    :class:`~app.orchestrator.debate_controller.DebateController` exits the
    round-robin loop and forwards ``conclusion`` / ``reasoning`` to child DAG
    tasks.  The ``consensus_reached`` field is stripped before forwarding so
    child agents receive only the substantive conclusion.
    """

    consensus_reached: bool
    conclusion: str
    reasoning: str


# ---------------------------------------------------------------------------
# RoleTemplate schemas
# ---------------------------------------------------------------------------


class RoleTemplateCreate(BaseModel):
    """Payload for creating a new role template."""

    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = []
    default_params: dict[str, Any] = {}


class RoleTemplateUpdate(BaseModel):
    """Partial update payload for an existing role template."""

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    default_params: dict[str, Any] | None = None


class RoleTemplateResponse(BaseModel):
    """Full representation of a RoleTemplate record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    system_prompt: str
    tools: list[str]
    default_params: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# KnowledgeDocument schemas
# ---------------------------------------------------------------------------


class KnowledgeDocumentResponse(BaseModel):
    """Minimal KnowledgeDocument record returned immediately after upload (status=uploading)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: str
    error_message: str | None
    page_count: int | None
    chunk_count: int | None
    github_path: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeChunkResult(BaseModel):
    """A single search result chunk from the knowledge base."""

    id: str
    source_pdf: str
    section_title: str
    level: int
    start_page: int
    end_page: int
    markdown_path: str | None
    content: str
    distance: float


class KnowledgeSectionSummary(BaseModel):
    """Lightweight section descriptor — used in the document list view."""

    id: str
    section_title: str
    level: int
    start_page: int
    end_page: int


class KnowledgeDocumentListResponse(BaseModel):
    """KnowledgeDocument record enriched with its chapter/section hierarchy.

    Returned by ``GET /knowledge/`` so the frontend can display the document
    library with hierarchical structure, processing status, and metadata.
    """

    id: uuid.UUID
    filename: str
    status: str
    error_message: str | None
    page_count: int | None
    chunk_count: int | None
    github_path: str | None
    created_at: datetime
    updated_at: datetime
    # Ordered list of section descriptors from the ingested KnowledgeChunk rows.
    sections: list[KnowledgeSectionSummary] = []


class KnowledgeDocumentDetailResponse(KnowledgeDocumentListResponse):
    """Full document record with chapter/section tree and individual chunk previews.

    Returned by ``GET /knowledge/{doc_id}`` so the frontend can render the
    complete hierarchical structure and content previews for each section.
    """

    # Full chunk list including content — allows expandable previews in the UI.
    chunks: list[KnowledgeChunkResult] = []


class KnowledgeSearchRequest(BaseModel):
    """Payload for a semantic knowledge-base search."""

    query: str
    top_k: int = 5


class KnowledgeSearchResponse(BaseModel):
    """Top-K semantically similar chunks returned by a knowledge-base search."""

    results: list[KnowledgeChunkResult]
