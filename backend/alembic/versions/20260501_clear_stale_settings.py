"""Clear stale planner_system_prompt and response_model_class_path from global_settings

Earlier deployments may have persisted legacy values for these two keys via the
Settings UI or seed scripts:

  planner_system_prompt  — old shallow-summary prompt that produced one-paragraph
                           responses with no multi-section DAG planning.
  response_model_class_path — "app.schemas.ReportSynthesizerResponse", the
                               predecessor of DetailedReportResponse.

When these rows exist they silently override the updated code defaults in
_load_settings() (backend/app/tasks.py), preventing the detailed-report
remediation from taking effect on existing environments.

This migration removes both rows unconditionally so that the new defaults
activate on the next pipeline execution.  An operator can re-persist custom
values at any time via PUT /settings/<key> after migration.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STALE_KEYS = ("planner_system_prompt", "response_model_class_path")


def upgrade() -> None:
    for key in _STALE_KEYS:
        op.execute(
            sa.text("DELETE FROM global_settings WHERE key = :key").bindparams(key=key)
        )


def downgrade() -> None:
    # Downgrade is intentionally a no-op: the old prompt and class path are
    # not restored because they would re-introduce the shallow-summary defect.
    pass
