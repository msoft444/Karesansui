"""Remove stale 'karesansui' model placeholder from global_settings

The initial deployment seeded the GlobalSettings 'model' key with the
application name ("karesansui") as a placeholder value before the
INFERENCE_MODEL environment variable was introduced.  mlx_lm does not
recognise "karesansui" as a valid model identifier, causing every Planner
call to return HTTP 404.

This migration removes the stale row so that the INFERENCE_MODEL env var
(injected by docker-compose.yml) is used as the effective default by
_load_settings() in backend/app/tasks.py.  The operator can set a
persistent model value at any time via the Settings UI (PUT /settings/model),
at which point the DB row takes precedence as normal.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Delete the 'model' row that holds the placeholder value 'karesansui'.

    The DELETE is conditional on the stored JSONB value being exactly the
    JSON string "karesansui" so that rows already updated to a valid model ID
    (e.g. via the Settings UI) are never touched.
    """
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM global_settings "
            "WHERE key = 'model' "
            "AND value = '\"karesansui\"'::jsonb"
        )
    )


def downgrade() -> None:
    """Restore the placeholder row on rollback.

    Inserts the original placeholder only when no 'model' row is present,
    so a rollback is idempotent if the operator has already set a real value.
    """
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT 1 FROM global_settings WHERE key = 'model'")
    ).fetchone()
    if existing is None:
        conn.execute(
            sa.text(
                "INSERT INTO global_settings (key, value, updated_at) "
                "VALUES ('model', '\"karesansui\"'::jsonb, now())"
            )
        )
