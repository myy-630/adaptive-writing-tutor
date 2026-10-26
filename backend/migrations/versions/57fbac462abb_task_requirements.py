"""Persist required points for prompt analysis

Revision ID: 57fbac462abb
Revises: 3e72a192d801
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "57fbac462abb"
down_revision: str | None = "3e72a192d801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "writing_tasks",
        sa.Column(
            "required_points",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("writing_tasks", "required_points")
