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
