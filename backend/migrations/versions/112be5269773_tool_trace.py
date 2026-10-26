"""tool_trace

Revision ID: 112be5269773
Revises: bf4904baa42f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "112be5269773"
down_revision: str | None = "bf4904baa42f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_call_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("actor", sa.String(length=40), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "success",
                "failure",
                "degraded",
                name="toolcallstatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("duration_ms >= 0", name="ck_tool_call_duration"),
        sa.ForeignKeyConstraint(["session_id"], ["teaching_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("tool_call_records")
