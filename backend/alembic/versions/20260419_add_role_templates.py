"""Add role_templates table with initial seed data

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-19

"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Seed data: role templates from requirement_specification.md §4
# ---------------------------------------------------------------------------
_NOW = datetime(2026, 4, 19, 0, 0, 0, tzinfo=timezone.utc)

_SEED_TEMPLATES = [
    # --- A. Fact-Based ---
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Data_Gatherer")),
        "name": "Data_Gatherer",
        "description": (
            "Specializes in collecting objective facts and data using tools "
            "(RAG, MCP, Web Search, etc.). Does not interject personal opinions."
        ),
        "system_prompt": (
            "You are Data_Gatherer. Your sole responsibility is to collect accurate, "
            "objective facts and data relevant to the assigned task using available "
            "tools such as RAG retrieval, MCP servers, and web search. "
            "Do not add personal opinions or interpretations. "
            "Return all gathered information in structured English."
        ),
        "tools": ["rag_search", "web_search", "mcp_call"],
        "default_params": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Logical_Analyst")),
        "name": "Logical_Analyst",
        "description": (
            "Builds logical interpretations and structures based on collected data."
        ),
        "system_prompt": (
            "You are Logical_Analyst. Given the collected data provided as context, "
            "perform rigorous logical analysis: identify patterns, causal relationships, "
            "and derive well-reasoned interpretations. "
            "Structure your output clearly with a conclusion and supporting reasoning. "
            "Work entirely in English."
        ),
        "tools": [],
        "default_params": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Critical_Reviewer")),
        "name": "Critical_Reviewer",
        "description": (
            "Points out logical leaps or lack of evidence in deliverables "
            "and requests reconsideration."
        ),
        "system_prompt": (
            "You are Critical_Reviewer. Examine the provided analysis or report with a "
            "highly critical eye. Identify logical leaps, unsupported claims, missing "
            "evidence, or flawed reasoning. "
            "For each issue found, clearly state the problem and request a specific "
            "correction or additional evidence. Work entirely in English."
        ),
        "tools": [],
        "default_params": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Report_Synthesizer")),
        "name": "Report_Synthesizer",
        "description": (
            "Objectively integrates verified information and creates the final report."
        ),
        "system_prompt": (
            "You are Report_Synthesizer. Integrate all verified information, analyses, "
            "and debate conclusions provided in the context into a coherent, objective "
            "final report. Ensure completeness, accuracy, and clarity. "
            "Structure the report with an executive summary, detailed findings, and "
            "conclusions. Work entirely in English."
        ),
        "tools": [],
        "default_params": {},
    },
    # --- B. Debate/Roleplay-Based ---
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Advocate")),
        "name": "Advocate",
        "description": (
            "Strongly asserts the legitimacy and merits of a specific "
            "Standpoint designated by the Planner."
        ),
        "system_prompt": (
            "You are Advocate. You have been assigned a specific standpoint: "
            "{{standpoint}}. "
            "Argue forcefully and persuasively for the legitimacy and merits of this "
            "standpoint using all available evidence. "
            "Counter opposing arguments where possible. Work entirely in English."
        ),
        "tools": [],
        "default_params": {"standpoint": ""},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Disrupter")),
        "name": "Disrupter",
        "description": (
            "Forcibly introduces a specified different concept into existing "
            "discussions to enforce multi-dimensional perspectives."
        ),
        "system_prompt": (
            "You are Disrupter. Your role is to challenge the current consensus by "
            "introducing the following disruptive concept: {{disrupt_concept}}. "
            "Force the debate to consider this perspective, highlight overlooked "
            "dimensions, and break any premature consensus. Work entirely in English."
        ),
        "tools": [],
        "default_params": {"disrupt_concept": ""},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Mediator")),
        "name": "Mediator",
        "description": (
            "Exclusive to Debate nodes. Integrates opinions of other agents and "
            "aims for consensus. Outputs a Termination Flag and Final Conclusion "
            "upon reaching agreement."
        ),
        "system_prompt": (
            "You are Mediator. Review all arguments presented in this debate round. "
            "Objectively evaluate whether a meaningful consensus has been reached. "
            "If consensus is reached, set consensus_reached=true and provide a clear "
            "conclusion and reasoning. "
            "If not, set consensus_reached=false and summarize remaining disagreements. "
            "Work entirely in English."
        ),
        "tools": [],
        "default_params": {},
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Persona_Writer")),
        "name": "Persona_Writer",
        "description": (
            "Creates a final report summarizing discussion results according to "
            "a specified Tone & Manner."
        ),
        "system_prompt": (
            "You are Persona_Writer. Using the discussion results and conclusions "
            "provided in the context, write a final report in the following "
            "tone and manner: {{tone}}. "
            "Adapt your language style, formality, and emphasis accordingly while "
            "preserving all key insights. Work entirely in English."
        ),
        "tools": [],
        "default_params": {"tone": "professional"},
    },
    # --- C. System Utility ---
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "Translator")),
        "name": "Translator",
        "description": (
            "Specializes in bidirectional English-Japanese translation. "
            "Does not perform logical inference; maintains format and nuance only."
        ),
        "system_prompt": (
            "You are Translator. Translate the provided text between English and "
            "Japanese as directed: {{direction}}. "
            "Preserve the original format, structure, and nuance exactly. "
            "Do not add, remove, or reinterpret any content."
        ),
        "tools": [],
        "default_params": {"direction": "en_to_ja"},
    },
]


def upgrade() -> None:
    """Create role_templates table and seed initial templates.

    Idempotent: if Base.metadata.create_all() already created the table during
    the same startup cycle, skip CREATE TABLE but still apply the seed rows so
    that the initial data is always present regardless of execution order.
    """
    conn = op.get_bind()

    # Guard against DuplicateTable when create_all() runs before alembic upgrade.
    table_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'role_templates'"
        )
    ).fetchone()

    if table_exists is None:
        op.create_table(
            "role_templates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("system_prompt", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("tools", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("default_params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("name", name="uq_role_templates_name"),
        )

    # Seed initial role templates from requirement_specification.md §4.
    # Use ON CONFLICT (name) DO NOTHING so this is safe to run more than once.
    for row in _SEED_TEMPLATES:
        conn.execute(
            sa.text(
                "INSERT INTO role_templates "
                "(id, name, description, system_prompt, tools, default_params, created_at, updated_at) "
                "VALUES (:id, :name, :description, :system_prompt, "
                "CAST(:tools AS jsonb), CAST(:default_params AS jsonb), :created_at, :updated_at) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "system_prompt": row["system_prompt"],
                "tools": json.dumps(row["tools"]),
                "default_params": json.dumps(row["default_params"]),
                "created_at": _NOW,
                "updated_at": _NOW,
            },
        )


def downgrade() -> None:
    """Drop role_templates table."""
    op.drop_table("role_templates")
