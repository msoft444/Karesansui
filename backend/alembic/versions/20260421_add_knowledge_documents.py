"""Add knowledge_documents table and document_id FK to knowledge_chunks

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Ordered list of valid pipeline status values (must match models.DocumentStatus).
_STATUS_VALUES = (
    "uploading",
    "splitting",
    "converting",
    "vectorizing",
    "syncing",
    "completed",
    "failed",
)
_STATUS_ENUM_NAME = "documentstatus"


def upgrade() -> None:
    """Create knowledge_documents table and add document_id FK to knowledge_chunks.

    All checks are idempotent (guard against re-runs on an already-migrated DB),
    but in the normal Alembic-managed execution path (see database.init_db) the
    objects will not pre-exist: ``create_all`` is deliberately skipped for
    Alembic-managed databases so that this upgrade function is the sole DDL owner
    of every object it creates.  That ownership guarantee is what makes
    ``downgrade`` fully and unconditionally reversible.
    """
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Create the documentstatus enum type (idempotent).
    # ------------------------------------------------------------------
    type_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": _STATUS_ENUM_NAME},
    ).fetchone()

    if type_exists is None:
        sa.Enum(*_STATUS_VALUES, name=_STATUS_ENUM_NAME).create(conn, checkfirst=True)

    # ------------------------------------------------------------------
    # 2. Create knowledge_documents table (idempotent).
    # ------------------------------------------------------------------
    table_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'knowledge_documents'"
        )
    ).fetchone()

    if table_exists is None:
        op.create_table(
            "knowledge_documents",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                nullable=False,
            ),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("source_pdf_path", sa.String(), nullable=True),
            sa.Column(
                "status",
                sa.Enum(*_STATUS_VALUES, name=_STATUS_ENUM_NAME, create_type=False),
                nullable=False,
                server_default="uploading",
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("chunk_count", sa.Integer(), nullable=True),
            sa.Column("github_path", sa.String(), nullable=True),
            sa.Column("output_dir", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    # ------------------------------------------------------------------
    # 3. Add document_id FK column to knowledge_chunks (idempotent).
    # ------------------------------------------------------------------
    col_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'knowledge_chunks' AND column_name = 'document_id'"
        )
    ).fetchone()

    if col_exists is None:
        op.add_column(
            "knowledge_chunks",
            sa.Column(
                "document_id",
                UUID(as_uuid=True),
                sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_knowledge_chunks_document_id",
            "knowledge_chunks",
            ["document_id"],
        )


def downgrade() -> None:
    """Reverse the additions made by upgrade().

    Because database.init_db() guarantees that upgrade() is the sole DDL
    owner of these objects on any Alembic-managed database (create_all() is
    not called in that code path), this function can unconditionally reverse
    every object that upgrade() created.  Existence guards are included only
    as a safety net against manual schema alterations.
    """
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Drop document_id FK column from knowledge_chunks.
    # ------------------------------------------------------------------
    col_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'knowledge_chunks' AND column_name = 'document_id'"
        )
    ).fetchone()
    if col_exists:
        op.drop_index(
            "ix_knowledge_chunks_document_id",
            table_name="knowledge_chunks",
            if_exists=True,
        )
        op.drop_column("knowledge_chunks", "document_id")

    # ------------------------------------------------------------------
    # 2. Drop knowledge_documents table.
    # ------------------------------------------------------------------
    table_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'knowledge_documents'"
        )
    ).fetchone()
    if table_exists:
        op.drop_table("knowledge_documents")

    # ------------------------------------------------------------------
    # 3. Drop documentstatus enum type.
    # ------------------------------------------------------------------
    sa.Enum(name=_STATUS_ENUM_NAME).drop(op.get_bind(), checkfirst=True)

