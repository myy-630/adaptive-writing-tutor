from uuid import UUID

from app.domain.schemas import ToolCallRecord
from app.models.tool_trace import ToolCallRecordRow
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class ToolTraceStore:
    """Persist tool audit records separately from Student State evidence."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def record(self, item: ToolCallRecord) -> None:
        with self.sessions.begin() as db:
            db.add(ToolCallRecordRow(**item.model_dump()))

    def for_session(self, session_id: UUID) -> list[ToolCallRecord]:
        with self.sessions() as db:
            rows = db.scalars(
                select(ToolCallRecordRow)
                .where(ToolCallRecordRow.session_id == session_id)
                .order_by(ToolCallRecordRow.called_at, ToolCallRecordRow.id)
            ).all()
            return [
                ToolCallRecord.model_validate(
                    {name: getattr(row, name) for name in ToolCallRecord.model_fields}
                )
                for row in rows
            ]
