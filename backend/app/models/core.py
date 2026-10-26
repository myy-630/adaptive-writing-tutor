from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.types import enum_values
from app.domain.enums import TeachingMode, TeachingStage


class StudentRecord(Base):
    __tablename__ = "students"
    __table_args__ = (CheckConstraint("grade BETWEEN 7 AND 12", name="ck_students_grade"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    learning_goal: Mapped[str] = mapped_column(String(500), nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(100))
    preferences: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WritingTaskRecord(Base):
    __tablename__ = "writing_tasks"
    __table_args__ = (CheckConstraint("grade BETWEEN 7 AND 12", name="ck_tasks_grade"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    genre: Mapped[str] = mapped_column(String(100), nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    required_points: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DraftRecord(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_drafts_version"),
        UniqueConstraint("student_id", "task_id", "version", name="uq_draft_version"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id"), nullable=False)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("writing_tasks.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    student: Mapped[StudentRecord] = relationship()
    task: Mapped[WritingTaskRecord] = relationship()


class TeachingSessionRecord(Base):
    __tablename__ = "teaching_sessions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id"), nullable=False)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("writing_tasks.id"), nullable=False)
    stage: Mapped[TeachingStage] = mapped_column(
        Enum(
            TeachingStage,
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    mode: Mapped[TeachingMode] = mapped_column(
        Enum(
            TeachingMode,
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    current_draft_id: Mapped[UUID | None] = mapped_column(ForeignKey("drafts.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
