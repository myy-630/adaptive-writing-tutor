"""Create core student, task, draft, and session tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("learning_goal", sa.String(500), nullable=False),
        sa.Column("proficiency", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint("grade BETWEEN 7 AND 12", name="ck_students_grade"),
    )
    op.create_table(
        "writing_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("genre", sa.String(100), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint("grade BETWEEN 7 AND 12", name="ck_tasks_grade"),
    )
    op.create_table(
        "drafts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", UUID(as_uuid=True), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("writing_tasks.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint("version >= 1", name="ck_drafts_version"),
        sa.UniqueConstraint("student_id", "task_id", "version", name="uq_draft_version"),
    )
    op.create_table(
        "teaching_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", UUID(as_uuid=True), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("writing_tasks.id"), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "prompt_analysis",
                "first_draft",
                "grammar_revision",
                "structure_revision",
                "content_expansion",
                "language_refinement",
                "second_draft",
                "final_evaluation",
                name="teachingstage",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.Enum(
                "guided",
                "semi_guided",
                "independent",
                name="teachingmode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("current_draft_id", UUID(as_uuid=True), sa.ForeignKey("drafts.id")),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    )


def downgrade() -> None:
    op.drop_table("teaching_sessions")
    op.drop_table("drafts")
    op.drop_table("writing_tasks")
    op.drop_table("students")
