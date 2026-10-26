"""Require server-generated timestamps on core records."""

import sqlalchemy as sa
from alembic import op

revision = "0002_required_timestamps"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name, column_name in (
        ("students", "created_at"),
        ("writing_tasks", "created_at"),
        ("drafts", "created_at"),
        ("teaching_sessions", "started_at"),
        ("teaching_sessions", "updated_at"),
    ):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        )


def downgrade() -> None:
    for table_name, column_name in (
        ("students", "created_at"),
        ("writing_tasks", "created_at"),
        ("drafts", "created_at"),
        ("teaching_sessions", "started_at"),
        ("teaching_sessions", "updated_at"),
    ):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        )
