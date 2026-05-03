from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


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


class ReportSynthesizerResponse(BaseModel):
    """Structured output for Standard agents (Data_Gatherer, Logical_Analyst,
    Critical_Reviewer, Report_Synthesizer, Translator, Persona_Writer, etc.).

    ``summary`` holds the agent's main conclusion and ``details`` captures
    supporting points, evidence, or reasoning steps.
    """

    summary: str
    details: list[str] = []


class DetailedReportResponse(BaseModel):
    """Richer structured output for synthesis tasks that require multi-section,
    evidence-grounded final reports.

    Extends the base ``summary / details`` contract with ``sources``
    (citations / URLs) and ``conclusion`` fields so that ``Report_Synthesizer``
    produces a substantive, evidence-grounded final report.

    ``details`` and ``conclusion`` are required and must be non-empty so that
    shallow one-paragraph responses are rejected and trigger instructor's retry
    budget rather than passing as valid output.
    """

    summary: str
    details: list[str] = Field(min_length=1)
    sources: list[str] = []
    conclusion: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Planner DAG structured-output schemas
# ---------------------------------------------------------------------------

class StandardTaskNode(BaseModel):
    """A single Standard-type task node in the Planner's DAG output."""

    task_id: str
    task_type: Literal["Standard"]
    role: str
    parent_ids: list[str] = []
    dynamic_params: dict[str, Any] = {}


class DebateTaskNode(BaseModel):
    """A single Debate-type task node in the Planner's DAG output."""

    task_id: str
    task_type: Literal["Debate"]
    participants: list[str]
    mediator: str
    parent_ids: list[str] = []
    dynamic_params: dict[str, Any] = {}


DagTaskNode = Annotated[
    Union[StandardTaskNode, DebateTaskNode],
    Field(discriminator="task_type"),
]


class DagPayload(BaseModel):
    """Structured output schema for the Planner agent.

    The instructor library enforces this schema at the logits level so the
    Planner always emits a well-formed DAG JSON, satisfying
    requirement_specification.md §9 (JSON Schema constraints).
    ``model_dump()`` on an instance produces the exact dict shape that
    ``DagParser`` accepts.
    """

    tasks: list[DagTaskNode]


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


# ---------------------------------------------------------------------------
# Query submission schemas
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """Payload for submitting a new user query to the orchestration pipeline."""

    query: str


class QueryResponse(BaseModel):
    """Response returned immediately after enqueuing a new orchestration run."""

    run_id: str


# ---------------------------------------------------------------------------
# Run-oriented read-model schemas (used by GET /history/runs endpoints)
# ---------------------------------------------------------------------------


class RunStatus(str, enum.Enum):
    """Lifecycle status for a complete Query Run (across all its tasks)."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskStatus(str, enum.Enum):
    """Execution status for a single Display Task within a Query Run."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class DisplayTask(BaseModel):
    """A user-visible task item derived from the Planner DAG topology.

    One Display Task corresponds to one Planner ``task_id``.  Internal rows
    (Debate rounds, raw sub-steps) are aggregated into ``sub_records`` rather
    than being promoted to top-level tasks.
    """

    task_id: str
    task_type: Literal["Standard", "Debate"]
    role: str | None
    participants: list[str] | None = None
    mediator: str | None = None
    parent_ids: list[str] = []
    dynamic_params: dict[str, Any] = {}
    status: TaskStatus
    created_at: datetime | None = None
    result: dict[str, Any] | None
    progress: dict[str, Any] | None = None
    sub_records: list["HistoryResponse"] = []


class RunSummary(BaseModel):
    """Lightweight per-run summary for the execution history list.

    Returned by ``GET /history/runs``.  One item per ``run_id``.
    """

    run_id: str
    status: RunStatus
    created_at: datetime
    final_result_preview: str | None = None
    task_count: int


class RunDetail(BaseModel):
    """Full detail payload for a single Query Run.

    Returned by ``GET /history/runs/{run_id}``.  Contains the final result,
    ordered Display Task list, and raw DAG topology so the frontend can render
    all three sections (final result, task drill-down, DAG) from one response.
    """

    run_id: str
    status: RunStatus
    created_at: datetime
    final_result: dict[str, Any] | None = None
    final_result_preview: str | None = None
    dag_topology: list[dict[str, Any]] | None = None
    tasks: list[DisplayTask] = []
