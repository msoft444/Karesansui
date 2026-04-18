"""Add run_id column to history table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-04-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'history' AND column_name = 'run_id'"
        )
    ).fetchone()
    if row is None:
        op.add_column("history", sa.Column("run_id", sa.String(), nullable=True))
        op.create_index(op.f("ix_history_run_id"), "history", ["run_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_history_run_id"), table_name="history")
    op.drop_column("history", "run_id")
