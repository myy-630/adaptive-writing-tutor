from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import DomainError
from app.domain.enums import TeachingStage
from app.domain.schemas import LearningEvidence
from app.models import DraftRecord, TeachingSessionRecord, WorkflowEventRecord, WritingTaskRecord
from app.services.student_state.manager import StudentStateManager
from app.workflows.draft_comparison import DraftComparison
from app.workflows.schemas import WorkflowResult, WorkflowSubmission
from app.workflows.stage_gate import StageGate, StageOutcome


class WorkflowStore:
    """Owns workflow event idempotency and transactional stage/draft writes."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        state_manager: StudentStateManager,
        stage_gate: StageGate,
    ) -> None:
        self.sessions = sessions
        self.state_manager = state_manager
        self.stage_gate = stage_gate

    @contextmanager
    def run_lock(self, request_id: UUID) -> Iterator[None]:
        """Serialize concurrent runs of one request without changing durable event state."""
        engine = self.sessions.kw["bind"]
        key = request_id.int & ((1 << 63) - 1)
        with engine.connect() as connection:
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            connection.commit()
            if not acquired:
                raise DomainError("request_in_progress", "Workflow request is already running", 409)
            try:
                yield
            finally:
                connection.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()

    def register(
        self, session_id: UUID, student_id: UUID, submission: WorkflowSubmission
    ) -> WorkflowResult | None:
        payload = submission.model_dump(mode="json")
        try:
            with self.sessions.begin() as db:
                event = db.get(WorkflowEventRecord, submission.request_id)
                if event is not None:
                    if (
                        event.session_id != session_id
                        or event.student_id != student_id
                        or event.payload != payload
                    ):
                        raise DomainError("request_conflict", "Request ID was already used", 409)
                    return WorkflowResult.model_validate(event.result) if event.result else None
                session = db.get(TeachingSessionRecord, session_id, with_for_update=True)
                if session is None or session.student_id != student_id:
                    raise DomainError("session_missing", "Teaching session was not found", 404)
                if session.completed_at is not None:
                    raise DomainError("session_completed", "Teaching session is complete", 409)
                db.add(
                    WorkflowEventRecord(
                        id=submission.request_id,
                        session_id=session_id,
                        student_id=student_id,
                        payload=payload,
                        stage_before=session.stage.value,
                    )
                )
        except IntegrityError as exc:
            with self.sessions() as db:
                event = db.get(WorkflowEventRecord, submission.request_id)
                if (
                    event is not None
                    and event.session_id == session_id
                    and event.student_id == student_id
                    and event.payload == payload
                ):
                    return WorkflowResult.model_validate(event.result) if event.result else None
            raise DomainError("request_conflict", "Request ID was already used", 409) from exc
        return None

    def apply(self, request_id: UUID) -> StageOutcome:
        with self.sessions.begin() as db:
            event = db.get(WorkflowEventRecord, request_id, with_for_update=True)
            if event is None:
                raise DomainError("request_missing", "Workflow request was not registered", 404)
            if event.applied:
                if event.stage_outcome is None:
                    raise DomainError("outcome_missing", "Applied event has no outcome", 500)
                outcome = self._outcome(event.stage_outcome)
            else:
                outcome = self._apply_new(db, event)
        if outcome.evidence is not None:
            self.state_manager.record_evidence(outcome.evidence)
        return outcome

    def _apply_new(self, db: Session, event: WorkflowEventRecord) -> StageOutcome:
        session = db.get(TeachingSessionRecord, event.session_id, with_for_update=True)
        if session is None or session.student_id != event.student_id:
            raise DomainError("session_missing", "Teaching session was not found", 404)
        if session.stage.value != event.stage_before:
            raise DomainError("stage_conflict", "Session stage changed before request", 409)
        task = db.get(WritingTaskRecord, session.task_id)
        if task is None:
            raise DomainError("task_missing", "Writing task was not found", 404)
        current, first = self._drafts(db, session)
        previous = db.scalar(
            select(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.session_id == event.session_id,
                WorkflowEventRecord.stage_before == event.stage_before,
                WorkflowEventRecord.completed.is_(True),
                WorkflowEventRecord.result["blocked"].as_boolean().is_(False),
                WorkflowEventRecord.id != event.id,
            )
            .order_by(WorkflowEventRecord.created_at.desc(), WorkflowEventRecord.id.desc())
            .limit(1)
        )
        prior_policy = previous.policy_decision if previous else None
        submission = WorkflowSubmission.model_validate(event.payload)
        outcome = self.stage_gate.assess(
            request_id=event.id,
            student_id=event.student_id,
            session_id=event.session_id,
            observed_at=event.created_at,
            stage=session.stage,
            mode=session.mode,
            submission=submission,
            task_genre=task.genre,
            task_required_points=task.required_points,
            current_draft=current,
            first_draft=first,
            needs_transfer=bool(prior_policy and prior_policy.get("needs_practice")),
            transfer_node_id=(
                str(prior_policy.get("target_knowledge_node_id"))
                if prior_policy and prior_policy.get("target_knowledge_node_id")
                else None
            ),
            prior_hint_level=int(prior_policy.get("scaffold_level", 0)) if prior_policy else 0,
        )
        if outcome.save_draft and submission.text:
            version = (
                db.scalar(
                    select(func.max(DraftRecord.version)).where(
                        DraftRecord.student_id == event.student_id,
                        DraftRecord.task_id == session.task_id,
                    )
                )
                or 0
            )
            draft = DraftRecord(
                id=uuid4(),
                student_id=event.student_id,
                task_id=session.task_id,
                version=version + 1,
                content=submission.text,
            )
            db.add(draft)
            session.current_draft_id = draft.id
        session.stage = outcome.stage_after
        if outcome.completed:
            session.completed_at = datetime.now(UTC)
        event.applied = True
        event.stage_outcome = {
            "stage_after": outcome.stage_after.value,
            "passed": outcome.passed,
            "completed": outcome.completed,
            "feedback": outcome.feedback,
            "evidence": outcome.evidence.model_dump(mode="json") if outcome.evidence else None,
            "comparison": outcome.comparison.model_dump(mode="json")
            if outcome.comparison
            else None,
        }
        return outcome

    def context(self, request_id: UUID) -> dict[str, object]:
        with self.sessions() as db:
            event = db.get(WorkflowEventRecord, request_id)
            if event is None:
                raise DomainError("request_missing", "Workflow request was not registered", 404)
            session = db.get(TeachingSessionRecord, event.session_id)
            if session is None:
                raise DomainError("session_missing", "Teaching session was not found", 404)
            task = db.get(WritingTaskRecord, session.task_id)
            if task is None:
                raise DomainError("task_missing", "Writing task was not found", 404)
            current, first = self._drafts(db, session)
            return {
                "request_id": str(event.id),
                "session_id": str(event.session_id),
                "student_id": str(event.student_id),
                "submission": event.payload,
                "stage": session.stage.value,
                "mode": session.mode.value,
                "task_prompt": task.prompt,
                "task_genre": task.genre,
                "current_draft": current or "",
                "first_draft": first or "",
            }

    def complete(
        self, request_id: UUID, result: WorkflowResult, policy_decision: dict | None
    ) -> WorkflowResult:
        with self.sessions.begin() as db:
            event = db.get(WorkflowEventRecord, request_id, with_for_update=True)
            if event is None:
                raise DomainError("request_missing", "Workflow request was not registered", 404)
            if event.result is not None:
                return WorkflowResult.model_validate(event.result)
            session = db.get(TeachingSessionRecord, event.session_id, with_for_update=True)
            if session is None:
                raise DomainError("session_missing", "Teaching session was not found", 404)
            session.mode = result.mode
            event.policy_decision = policy_decision
            event.completed = True
            event.result = result.model_dump(mode="json")
        return result

    @staticmethod
    def _drafts(db: Session, session: TeachingSessionRecord) -> tuple[str | None, str | None]:
        current = (
            db.get(DraftRecord, session.current_draft_id) if session.current_draft_id else None
        )
        first = db.scalar(
            select(DraftRecord)
            .where(
                DraftRecord.student_id == session.student_id,
                DraftRecord.task_id == session.task_id,
            )
            .order_by(DraftRecord.version)
            .limit(1)
        )
        return current.content if current else None, first.content if first else None

    @staticmethod
    def _outcome(raw: dict) -> StageOutcome:
        return StageOutcome(
            stage_after=TeachingStage(raw["stage_after"]),
            passed=bool(raw["passed"]),
            completed=bool(raw["completed"]),
            feedback=str(raw["feedback"]),
            evidence=(
                LearningEvidence.model_validate(raw["evidence"]) if raw.get("evidence") else None
            ),
            comparison=(
                DraftComparison.model_validate(raw["comparison"]) if raw.get("comparison") else None
            ),
        )
