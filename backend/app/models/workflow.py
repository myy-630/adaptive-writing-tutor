from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class WorkflowEventRecord(Base):
    __tablename__ = "workflow_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_sessions.id"), nullable=False)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id"), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    stage_before: Mapped[str] = mapped_column(String(40), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    stage_outcome: Mapped[dict | None] = mapped_column(JSONB)
    policy_decision: Mapped[dict | None] = mapped_column(JSONB)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
