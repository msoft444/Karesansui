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

    task_id: str
    role: str
    result: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    """Full representation of a History record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
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
