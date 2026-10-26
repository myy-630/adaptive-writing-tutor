"""workflow events and completion marker

Revision ID: 3e72a192d801
Revises: 112be5269773
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3e72a192d801"
down_revision: str | None = "112be5269773"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("teaching_sessions", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("stage_before", sa.String(length=40), nullable=False),
        sa.Column("applied", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("stage_outcome", postgresql.JSONB()),
        sa.Column("policy_decision", postgresql.JSONB()),
        sa.Column("completed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["teaching_sessions.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("workflow_events")
    op.drop_column("teaching_sessions", "completed_at")
