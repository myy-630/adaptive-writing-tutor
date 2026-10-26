from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_values
from app.domain.enums import ToolCallStatus


class ToolCallRecordRow(Base):
    __tablename__ = "tool_call_records"
    __table_args__ = (CheckConstraint("duration_ms >= 0", name="ck_tool_call_duration"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_sessions.id"), nullable=False)
    actor: Mapped[str] = mapped_column(String(40), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[ToolCallStatus] = mapped_column(
        Enum(
            ToolCallStatus, native_enum=False, create_constraint=True, values_callable=enum_values
        ),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
