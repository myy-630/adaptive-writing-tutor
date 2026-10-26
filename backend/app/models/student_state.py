from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_values
from app.domain.enums import AbilityDimension, EvidenceOutcome


class StudentStateRecord(Base):
    __tablename__ = "student_states"

    student_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("students.id"), primary_key=True
    )
    current_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("teaching_sessions.id"))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_hint_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confusion_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hint_level_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    independent_revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    micro_lesson_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    post_lesson_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transfer_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AbilityStateRecord(Base):
    __tablename__ = "ability_states"
    __table_args__ = (
        CheckConstraint("rubric_score BETWEEN 0 AND 1", name="ck_ability_score"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_ability_confidence"),
    )

    student_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("students.id"), primary_key=True
    )
    dimension: Mapped[AbilityDimension] = mapped_column(
        Enum(
            AbilityDimension,
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        primary_key=True,
    )
    rubric_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeStateRecord(Base):
    __tablename__ = "knowledge_states"
    __table_args__ = (
        CheckConstraint("mastery BETWEEN 0 AND 1", name="ck_knowledge_mastery"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_knowledge_confidence"),
    )

    student_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("students.id"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    mastery: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    path_mastered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    independent_discovery_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    independent_revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hint_level_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    micro_lesson_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    post_lesson_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transfer_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_essay_recurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningEvidenceRecord(Base):
    __tablename__ = "learning_evidence"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_sessions.id"), nullable=False)
    knowledge_node_id: Mapped[str | None] = mapped_column(String(160))
    ability_dimension: Mapped[AbilityDimension | None] = mapped_column(
        Enum(
            AbilityDimension,
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        )
    )
    outcome: Mapped[EvidenceOutcome] = mapped_column(
        Enum(
            EvidenceOutcome,
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    independent_discovery: Mapped[bool] = mapped_column(Boolean, nullable=False)
    independent_revision: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False)
    required_micro_lesson: Mapped[bool] = mapped_column(Boolean, nullable=False)
    post_lesson_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    transfer_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    next_essay_recurrence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rubric_score: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ErrorEventRecord(Base):
    __tablename__ = "error_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_sessions.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    knowledge_node_id: Mapped[str | None] = mapped_column(String(160))
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
