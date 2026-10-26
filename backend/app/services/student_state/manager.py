from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.errors import DomainError
from app.domain.enums import AbilityDimension, EvidenceOutcome
from app.domain.schemas import AbilityState, ErrorRecord, KnowledgeState, LearningEvidence, Student
from app.models import (
    AbilityStateRecord,
    ErrorEventRecord,
    KnowledgeStateRecord,
    LearningEvidenceRecord,
    StudentRecord,
    StudentStateRecord,
    TeachingSessionRecord,
)
from app.services.student_state.path_mastery import PathMasteryRules
from app.services.student_state.schemas import (
    ErrorPattern,
    InteractionState,
    PromptDependency,
    StudentStateSnapshot,
)
from app.services.student_state.tracing import evidence_confidence, update_ability, update_bkt
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker


class StudentStateReader(Protocol):
    def read_student_state(self, student_id: UUID) -> StudentStateSnapshot: ...


class StudentStateManager:
    """Transactional, deterministic owner of long-term student state."""

    def __init__(self, sessions: sessionmaker[Session], settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings
        self.path_rules = PathMasteryRules()

    def initialize_student(self, student: Student) -> StudentStateSnapshot:
        with self.sessions.begin() as db:
            existing = db.get(StudentRecord, student.id)
            if existing is not None:
                if (
                    existing.grade != student.grade
                    or existing.learning_goal != student.learning_goal
                    or existing.proficiency != student.proficiency
                    or existing.preferences != student.preferences
                ):
                    raise DomainError(
                        "student_conflict", "Student ID already has a different profile", 409
                    )
            else:
                db.add(
                    StudentRecord(
                        id=student.id,
                        grade=student.grade,
                        learning_goal=student.learning_goal,
                        proficiency=student.proficiency,
                        preferences=student.preferences,
                    )
                )
            if db.get(StudentStateRecord, student.id) is None:
                db.add(StudentStateRecord(student_id=student.id))
            for dimension in AbilityDimension:
                if db.get(AbilityStateRecord, (student.id, dimension)) is None:
                    db.add(
                        AbilityStateRecord(
                            student_id=student.id,
                            dimension=dimension,
                            rubric_score=self.settings.ability_initial_score,
                            confidence=0,
                            evidence_count=0,
                            updated_at=datetime.now(UTC),
                        )
                    )
        return self.read_student_state(student.id)

    def set_current_session(self, student_id: UUID, session_id: UUID) -> None:
        with self.sessions.begin() as db:
            self._require_matching_session(db, session_id, student_id)
            summary = db.get(StudentStateRecord, student_id, with_for_update=True)
            if summary is None:
                raise DomainError("state_missing", "Student state has not been initialized", 409)
            summary.current_session_id = session_id

    def set_confusion_score(self, student_id: UUID, session_id: UUID, score: float) -> None:
        if not 0 <= score <= 1:
            raise DomainError("invalid_confusion", "Confusion score must be between 0 and 1")
        with self.sessions.begin() as db:
            self._require_matching_session(db, session_id, student_id)
            summary = db.get(StudentStateRecord, student_id, with_for_update=True)
            if summary is None:
                raise DomainError("state_missing", "Student state has not been initialized", 409)
            summary.current_session_id = session_id
            summary.confusion_score = score

    def record_evidence(self, evidence: LearningEvidence) -> bool:
        values = evidence.model_dump()
        with self.sessions.begin() as db:
            session = self._require_matching_session(db, evidence.session_id, evidence.student_id)
            statement = (
                insert(LearningEvidenceRecord)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(LearningEvidenceRecord.id)
            )
            if db.execute(statement).scalar_one_or_none() is None:
                prior = db.get(LearningEvidenceRecord, evidence.id)
                if prior is None or not self._same_values(prior, values):
                    raise DomainError("evidence_conflict", "Evidence ID has different content", 409)
                return False
            summary = db.get(StudentStateRecord, evidence.student_id, with_for_update=True)
            if summary is None:
                raise DomainError("state_missing", "Student state has not been initialized", 409)
            summary.current_session_id = session.id
            summary.evidence_count += 1
            summary.hint_level_total += evidence.hint_level
            summary.current_hint_level = evidence.hint_level
            summary.independent_revision_count += int(evidence.independent_revision)
            summary.micro_lesson_count += int(evidence.required_micro_lesson)
            summary.post_lesson_success_count += int(evidence.post_lesson_success)
            summary.transfer_success_count += int(evidence.transfer_success)
            if evidence.outcome == EvidenceOutcome.FAILURE:
                summary.consecutive_failures += 1
            elif evidence.outcome == EvidenceOutcome.SUCCESS:
                summary.consecutive_failures = 0
            if evidence.knowledge_node_id is not None:
                self._update_knowledge(db, evidence)
            if evidence.ability_dimension is not None and evidence.rubric_score is not None:
                self._update_ability(db, evidence)
        return True

    def record_error(self, error: ErrorRecord) -> bool:
        values = error.model_dump()
        with self.sessions.begin() as db:
            self._require_matching_session(db, error.session_id, error.student_id)
            statement = (
                insert(ErrorEventRecord)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(ErrorEventRecord.id)
            )
            if db.execute(statement).scalar_one_or_none() is None:
                prior = db.get(ErrorEventRecord, error.id)
                if prior is None or not self._same_values(prior, values):
                    raise DomainError("error_conflict", "Error ID has different content", 409)
                return False
            if error.knowledge_node_id is not None:
                knowledge = db.get(
                    KnowledgeStateRecord,
                    (error.student_id, error.knowledge_node_id),
                    with_for_update=True,
                )
                if (
                    knowledge is not None
                    and self._recent_failure_counts(db, error.student_id).get(
                        error.knowledge_node_id, 0
                    )
                    >= self.path_rules.recent_failure_reopen_count
                ):
                    knowledge.path_mastered = False
        return True

    def error_counts(
        self, student_id: UUID, start: datetime | None = None, end: datetime | None = None
    ) -> list[ErrorPattern]:
        with self.sessions() as db:
            self._require_student(db, student_id)
            return self._error_counts(db, student_id, start, end)

    @staticmethod
    def _error_counts(
        db: Session,
        student_id: UUID,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ErrorPattern]:
        if start is not None and end is not None and start >= end:
            raise DomainError("invalid_window", "start must be before end")
        query = (
            select(
                ErrorEventRecord.category,
                ErrorEventRecord.knowledge_node_id,
                func.sum(ErrorEventRecord.count).label("total"),
            )
            .where(ErrorEventRecord.student_id == student_id)
            .group_by(ErrorEventRecord.category, ErrorEventRecord.knowledge_node_id)
            .order_by(ErrorEventRecord.category, ErrorEventRecord.knowledge_node_id)
        )
        if start is not None:
            query = query.where(ErrorEventRecord.observed_at >= start)
        if end is not None:
            query = query.where(ErrorEventRecord.observed_at < end)
        return [
            ErrorPattern(category=category, knowledge_node_id=node_id, count=count)
            for category, node_id, count in db.execute(query)
        ]

    def read_student_state(self, student_id: UUID) -> StudentStateSnapshot:
        with self.sessions() as db:
            student = self._require_student(db, student_id)
            summary = db.get(StudentStateRecord, student_id)
            if summary is None:
                raise DomainError("state_missing", "Student state has not been initialized", 409)
            abilities = db.scalars(
                select(AbilityStateRecord)
                .where(AbilityStateRecord.student_id == student_id)
                .order_by(AbilityStateRecord.dimension)
            ).all()
            knowledge = db.scalars(
                select(KnowledgeStateRecord)
                .where(KnowledgeStateRecord.student_id == student_id)
                .order_by(KnowledgeStateRecord.node_id)
            ).all()
            active_session = (
                db.get(TeachingSessionRecord, summary.current_session_id)
                if summary.current_session_id is not None
                else None
            )
            patterns = self._error_counts(db, student_id)
            recent_failures = self._recent_failure_counts(db, student_id)
            return StudentStateSnapshot(
                student=Student(
                    id=student.id,
                    grade=student.grade,
                    learning_goal=student.learning_goal,
                    proficiency=student.proficiency,
                    preferences=student.preferences,
                ),
                abilities=[
                    AbilityState(
                        dimension=row.dimension,
                        rubric_score=row.rubric_score,
                        confidence=row.confidence,
                        evidence_count=row.evidence_count,
                        updated_at=row.updated_at,
                    )
                    for row in abilities
                ],
                knowledge=[self._knowledge_schema(row) for row in knowledge],
                error_patterns=patterns,
                recent_knowledge_failures=recent_failures,
                prompt_dependency=PromptDependency(
                    evidence_count=summary.evidence_count,
                    average_hint_level=(
                        summary.hint_level_total / summary.evidence_count
                        if summary.evidence_count
                        else 0
                    ),
                    independent_revision_count=summary.independent_revision_count,
                    micro_lesson_count=summary.micro_lesson_count,
                    post_lesson_success_count=summary.post_lesson_success_count,
                    transfer_success_count=summary.transfer_success_count,
                ),
                interaction=InteractionState(
                    session_id=summary.current_session_id,
                    task_id=active_session.task_id if active_session else None,
                    stage=active_session.stage if active_session else None,
                    mode=active_session.mode if active_session else None,
                    consecutive_failures=summary.consecutive_failures,
                    current_hint_level=summary.current_hint_level,
                    confusion_score=summary.confusion_score,
                ),
            )

    def _update_knowledge(self, db: Session, evidence: LearningEvidence) -> None:
        node_id = evidence.knowledge_node_id
        assert node_id is not None
        db.execute(
            insert(KnowledgeStateRecord)
            .values(
                student_id=evidence.student_id,
                node_id=node_id,
                mastery=self.settings.bkt_initial_mastery,
                confidence=0,
            )
            .on_conflict_do_nothing(index_elements=["student_id", "node_id"])
        )
        row = db.get(KnowledgeStateRecord, (evidence.student_id, node_id), with_for_update=True)
        assert row is not None
        row.occurrence_count += 1
        row.independent_discovery_count += int(evidence.independent_discovery)
        row.independent_revision_count += int(evidence.independent_revision)
        row.hint_level_total += evidence.hint_level
        row.micro_lesson_count += int(evidence.required_micro_lesson)
        row.post_lesson_success_count += int(evidence.post_lesson_success)
        row.transfer_success_count += int(evidence.transfer_success)
        row.next_essay_recurrence_count += int(evidence.next_essay_recurrence)
        if evidence.outcome != EvidenceOutcome.UNCERTAIN:
            row.mastery = update_bkt(
                row.mastery, evidence.outcome == EvidenceOutcome.SUCCESS, self.settings
            )
            row.evidence_count += 1
            row.confidence = evidence_confidence(row.evidence_count, self.settings)
            if evidence.outcome == EvidenceOutcome.SUCCESS:
                row.last_success_at = self._latest(row.last_success_at, evidence.observed_at)
            else:
                row.last_failure_at = self._latest(row.last_failure_at, evidence.observed_at)
        row.last_evidence_at = self._latest(row.last_evidence_at, evidence.observed_at)
        independent_successes = (
            db.scalar(
                select(func.count())
                .select_from(LearningEvidenceRecord)
                .where(
                    LearningEvidenceRecord.student_id == evidence.student_id,
                    LearningEvidenceRecord.knowledge_node_id == node_id,
                    LearningEvidenceRecord.outcome == EvidenceOutcome.SUCCESS,
                LearningEvidenceRecord.hint_level <= 1,
                    or_(
                        LearningEvidenceRecord.independent_revision.is_(True),
                        LearningEvidenceRecord.hint_level == 0,
                    ),
                )
            )
            or 0
        )
        row.path_mastered = self.path_rules.advance(
            was_mastered=row.path_mastered,
            mastery=row.mastery,
            confidence=row.confidence,
            independent_successes=independent_successes,
            transfer_successes=row.transfer_success_count,
            recent_failures=self._recent_failure_counts(db, evidence.student_id).get(node_id, 0),
            verified_after_failure=self._verified_after_latest_failure(
                db, evidence.student_id, node_id
            ),
        )

    def _update_ability(self, db: Session, evidence: LearningEvidence) -> None:
        dimension = evidence.ability_dimension
        score = evidence.rubric_score
        assert dimension is not None and score is not None
        row = db.get(AbilityStateRecord, (evidence.student_id, dimension), with_for_update=True)
        if row is None:
            raise DomainError(
                "ability_missing", "Student ability state has not been initialized", 409
            )
        row.rubric_score = update_ability(row.rubric_score, score, self.settings)
        row.evidence_count += 1
        row.confidence = evidence_confidence(row.evidence_count, self.settings)
        row.updated_at = self._latest(row.updated_at, evidence.observed_at)

    @staticmethod
    def _latest(previous: datetime | None, current: datetime) -> datetime:
        return max(previous, current) if previous is not None else current

    @staticmethod
    def _same_values(record: object, values: Mapping[str, object]) -> bool:
        return all(getattr(record, key) == value for key, value in values.items())

    @staticmethod
    def _require_student(db: Session, student_id: UUID) -> StudentRecord:
        student = db.get(StudentRecord, student_id)
        if student is None:
            raise DomainError("student_not_found", "Student not found", 404)
        return student

    @staticmethod
    def _require_matching_session(
        db: Session, session_id: UUID, student_id: UUID
    ) -> TeachingSessionRecord:
        session = db.get(TeachingSessionRecord, session_id)
        if session is None or session.student_id != student_id:
            raise DomainError("session_not_found", "Session not found for student", 404)
        return session

    @staticmethod
    def _knowledge_schema(row: KnowledgeStateRecord) -> KnowledgeState:
        return KnowledgeState(
            node_id=row.node_id,
            mastery=row.mastery,
            confidence=row.confidence,
            path_mastered=row.path_mastered,
            evidence_count=row.evidence_count,
            occurrence_count=row.occurrence_count,
            independent_discovery_count=row.independent_discovery_count,
            independent_revision_count=row.independent_revision_count,
            hint_level_total=row.hint_level_total,
            micro_lesson_count=row.micro_lesson_count,
            post_lesson_success_count=row.post_lesson_success_count,
            transfer_success_count=row.transfer_success_count,
            next_essay_recurrence_count=row.next_essay_recurrence_count,
            last_success_at=row.last_success_at,
            last_failure_at=row.last_failure_at,
            last_evidence_at=row.last_evidence_at,
        )

    def _recent_failure_counts(self, db: Session, student_id: UUID) -> dict[str, int]:
        since = datetime.now(UTC) - timedelta(days=self.path_rules.recent_window_days)
        evidence_counts = {
            node_id: int(count)
            for node_id, count in db.execute(
                select(
                    LearningEvidenceRecord.knowledge_node_id,
                    func.count(LearningEvidenceRecord.id),
                )
                .where(
                    LearningEvidenceRecord.student_id == student_id,
                    LearningEvidenceRecord.knowledge_node_id.is_not(None),
                    LearningEvidenceRecord.outcome == EvidenceOutcome.FAILURE,
                    LearningEvidenceRecord.observed_at >= since,
                )
                .group_by(LearningEvidenceRecord.knowledge_node_id)
            )
            if node_id is not None
        }
        error_counts = {
            node_id: int(count)
            for node_id, count in db.execute(
                select(ErrorEventRecord.knowledge_node_id, func.sum(ErrorEventRecord.count))
                .where(
                    ErrorEventRecord.student_id == student_id,
                    ErrorEventRecord.knowledge_node_id.is_not(None),
                    ErrorEventRecord.observed_at >= since,
                )
                .group_by(ErrorEventRecord.knowledge_node_id)
            )
            if node_id is not None
        }
        return {
            node_id: max(int(evidence_counts.get(node_id, 0)), int(error_counts.get(node_id, 0)))
            for node_id in evidence_counts.keys() | error_counts.keys()
            if node_id is not None
        }

    def _verified_after_latest_failure(self, db: Session, student_id: UUID, node_id: str) -> bool:
        evidence_failure = db.scalar(
            select(func.max(LearningEvidenceRecord.observed_at)).where(
                LearningEvidenceRecord.student_id == student_id,
                LearningEvidenceRecord.knowledge_node_id == node_id,
                LearningEvidenceRecord.outcome == EvidenceOutcome.FAILURE,
            )
        )
        error_failure = db.scalar(
            select(func.max(ErrorEventRecord.observed_at)).where(
                ErrorEventRecord.student_id == student_id,
                ErrorEventRecord.knowledge_node_id == node_id,
            )
        )
        latest_failure = max(
            (value for value in (evidence_failure, error_failure) if value is not None),
            default=None,
        )
        if latest_failure is None:
            return True
        independent_successes = (
            db.scalar(
                select(func.count())
                .select_from(LearningEvidenceRecord)
                .where(
                    LearningEvidenceRecord.student_id == student_id,
                    LearningEvidenceRecord.knowledge_node_id == node_id,
                    LearningEvidenceRecord.outcome == EvidenceOutcome.SUCCESS,
                    LearningEvidenceRecord.observed_at > latest_failure,
                LearningEvidenceRecord.hint_level <= 1,
                    or_(
                        LearningEvidenceRecord.independent_revision.is_(True),
                        LearningEvidenceRecord.hint_level == 0,
                    ),
                )
            )
            or 0
        )
        transfer_successes = (
            db.scalar(
                select(func.count())
                .select_from(LearningEvidenceRecord)
                .where(
                    LearningEvidenceRecord.student_id == student_id,
                    LearningEvidenceRecord.knowledge_node_id == node_id,
                    LearningEvidenceRecord.outcome == EvidenceOutcome.SUCCESS,
                    LearningEvidenceRecord.observed_at > latest_failure,
                    LearningEvidenceRecord.transfer_success.is_(True),
                )
            )
            or 0
        )
        return (
            independent_successes >= self.path_rules.independent_successes
            or transfer_successes >= 1
        )
