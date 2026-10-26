"""Persist grammar path mastery hysteresis.

Revision ID: 8ce71d8e49aa
Revises: 57fbac462abb
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8ce71d8e49aa"
down_revision: str | None = "57fbac462abb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_states",
        sa.Column("path_mastered", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Existing records start conservatively. New evidence can promote them after
    # the BKT estimate and independently verified evidence satisfy the gate.


def downgrade() -> None:
    op.drop_column("knowledge_states", "path_mastered")
