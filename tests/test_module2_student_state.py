from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import create_database_engine, create_session_factory
from app.domain import (
    AbilityDimension,
    ErrorRecord,
    LearningEvidence,
    Student,
    TeachingMode,
    TeachingStage,
)
from app.domain.enums import EvidenceOutcome
from app.models import (
    LearningEvidenceRecord,
    StudentRecord,
    TeachingSessionRecord,
    WritingTaskRecord,
)
from app.services.student_state.manager import StudentStateManager, StudentStateReader
from app.services.student_state.tracing import evidence_confidence, update_ability, update_bkt
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def state_service() -> tuple[StudentStateManager, sessionmaker[Session], Engine]:
    settings = Settings()
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    yield StudentStateManager(sessions, settings), sessions, engine
    engine.dispose()


def create_student_session(
    manager: StudentStateManager,
    sessions: sessionmaker[Session],
    *,
    student: Student | None = None,
) -> tuple[Student, UUID]:
    student = student or Student(grade=9, learning_goal="Improve writing")
    manager.initialize_student(student)
    task_id, session_id = uuid4(), uuid4()
    with sessions.begin() as db:
        db.add(WritingTaskRecord(id=task_id, prompt="Describe a day", genre="narrative", grade=9))
        db.flush()
        db.add(
            TeachingSessionRecord(
                id=session_id,
                student_id=student.id,
                task_id=task_id,
                stage=TeachingStage.GRAMMAR_REVISION,
                mode=TeachingMode.GUIDED,
            )
        )
    return student, session_id


def make_evidence(
    student_id: UUID,
    session_id: UUID,
    outcome: EvidenceOutcome,
    *,
    node_id: str = "subject_verb_agreement",
    observed_at: datetime | None = None,
    **kwargs: object,
) -> LearningEvidence:
    return LearningEvidence(
        student_id=student_id,
        session_id=session_id,
        knowledge_node_id=node_id,
        outcome=outcome,
        observed_at=observed_at or datetime.now(UTC),
        **kwargs,
    )


def test_initialize_is_idempotent_and_profile_conflict_is_explicit(state_service: tuple) -> None:
    manager, _, _ = state_service
    student = Student(grade=9, learning_goal="Improve writing", preferences={"pace": "slow"})
    first = manager.initialize_student(student)
    second = manager.initialize_student(student)
    assert first == second
    assert len(first.abilities) == 5
    assert first.knowledge == []
    assert first.prompt_dependency.evidence_count == 0
    assert first.interaction.session_id is None
    with pytest.raises(DomainError, match="different profile"):
        manager.initialize_student(student.model_copy(update={"learning_goal": "Different"}))


def test_initialization_backfills_module1_student(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    student = Student(grade=10, learning_goal="Prepare for exams")
    with sessions.begin() as db:
        db.add(
            StudentRecord(
                id=student.id,
                grade=student.grade,
                learning_goal=student.learning_goal,
                preferences={},
            )
        )
    state = manager.initialize_student(student)
    assert len(state.abilities) == 5
    assert state.student.id == student.id


def test_success_failure_bkt_confidence_hints_and_idempotency(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    student, session_id = create_student_session(manager, sessions)
    first = make_evidence(
        student.id,
        session_id,
        EvidenceOutcome.SUCCESS,
        independent_discovery=True,
        independent_revision=True,
        hint_level=1,
        required_micro_lesson=True,
        post_lesson_success=True,
        transfer_success=True,
    )
    assert manager.record_evidence(first)
    assert manager.record_evidence(first) is False
    for _ in range(2):
        assert manager.record_evidence(
            make_evidence(student.id, session_id, EvidenceOutcome.SUCCESS)
        )
    state = manager.read_student_state(student.id)
    skill = state.knowledge[0]
    assert skill.mastery > 0.2
    assert skill.confidence == pytest.approx(0.5)
    assert skill.occurrence_count == 3
    assert skill.independent_discovery_count == 1
    assert skill.independent_revision_count == 1
    assert skill.hint_level_total == 1
    assert skill.micro_lesson_count == 1
    assert skill.post_lesson_success_count == 1
    assert skill.transfer_success_count == 1
    assert state.prompt_dependency.average_hint_level == pytest.approx(1 / 3)
    assert state.prompt_dependency.independent_revision_count == 1
    assert state.interaction.stage == TeachingStage.GRAMMAR_REVISION
    assert state.interaction.mode == TeachingMode.GUIDED
    assert state.interaction.consecutive_failures == 0
    with sessions() as db:
        assert db.scalar(
            select(LearningEvidenceRecord).where(LearningEvidenceRecord.id == first.id)
        )

    for _ in range(3):
        manager.record_evidence(
            make_evidence(student.id, session_id, EvidenceOutcome.FAILURE, node_id="articles")
        )
    state = manager.read_student_state(student.id)
    articles = next(skill for skill in state.knowledge if skill.node_id == "articles")
    assert articles.mastery < 0.2
    assert articles.confidence == pytest.approx(0.5)
    assert articles.last_failure_at is not None
    assert state.interaction.consecutive_failures == 3


def test_path_mastery_reopens_after_repeated_errors_and_reverification(
    state_service: tuple,
) -> None:
    manager, sessions, _ = state_service
    student, session_id = create_student_session(manager, sessions)
    for _ in range(3):
        manager.record_evidence(
            make_evidence(student.id, session_id, EvidenceOutcome.SUCCESS, hint_level=0)
        )
    skill = manager.read_student_state(student.id).knowledge[0]
    assert skill.path_mastered

    manager.record_evidence(make_evidence(student.id, session_id, EvidenceOutcome.FAILURE))
    assert manager.read_student_state(student.id).knowledge[0].path_mastered
    manager.record_evidence(make_evidence(student.id, session_id, EvidenceOutcome.FAILURE))
    state = manager.read_student_state(student.id)
    assert not state.knowledge[0].path_mastered
    assert state.recent_knowledge_failures["subject_verb_agreement"] == 2

    for _ in range(2):
        manager.record_evidence(
            make_evidence(student.id, session_id, EvidenceOutcome.SUCCESS, hint_level=0)
        )
    assert manager.read_student_state(student.id).knowledge[0].path_mastered


def test_open_ability_ema_and_reader_interface(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    student, session_id = create_student_session(manager, sessions)
    reader: StudentStateReader = manager
    for score in (1.0, 0.0):
        manager.record_evidence(
            LearningEvidence(
                student_id=student.id,
                session_id=session_id,
                ability_dimension=AbilityDimension.CONTENT,
                outcome=EvidenceOutcome.SUCCESS,
                rubric_score=score,
                observed_at=datetime.now(UTC),
            )
        )
    content = next(
        ability
        for ability in reader.read_student_state(student.id).abilities
        if ability.dimension == AbilityDimension.CONTENT
    )
    assert content.rubric_score == pytest.approx(0.455)
    assert content.confidence == pytest.approx(0.4)
    assert content.evidence_count == 2
    grammar = next(
        ability
        for ability in reader.read_student_state(student.id).abilities
        if ability.dimension == AbilityDimension.GRAMMAR
    )
    assert grammar.rubric_score == 0.5
    assert grammar.evidence_count == 0


def test_error_counts_use_half_open_time_window(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    student, session_id = create_student_session(manager, sessions)
    base = datetime(2026, 10, 1, tzinfo=UTC)
    first = ErrorRecord(
        student_id=student.id,
        session_id=session_id,
        category="grammar",
        knowledge_node_id="articles",
        original_text="I saw dog",
        count=2,
        observed_at=base,
    )
    assert manager.record_error(first)
    assert manager.record_error(first) is False
    manager.record_error(
        first.model_copy(
            update={"id": uuid4(), "count": 1, "observed_at": base + timedelta(days=1)}
        )
    )
    assert manager.error_counts(student.id, base, base + timedelta(days=1))[0].count == 2
    assert manager.error_counts(student.id, base, base + timedelta(days=2))[0].count == 3
    assert manager.read_student_state(student.id).error_patterns[0].count == 3
    with pytest.raises(DomainError, match="start must be before end"):
        manager.error_counts(student.id, base, base)


def test_students_are_isolated_and_invalid_session_rejected(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    first, first_session = create_student_session(manager, sessions)
    second, second_session = create_student_session(manager, sessions)
    manager.record_evidence(make_evidence(first.id, first_session, EvidenceOutcome.FAILURE))
    assert manager.read_student_state(second.id).knowledge == []
    assert manager.read_student_state(second.id).interaction.consecutive_failures == 0
    with pytest.raises(DomainError, match="Session not found"):
        manager.record_evidence(make_evidence(first.id, second_session, EvidenceOutcome.SUCCESS))
    with pytest.raises(DomainError, match="Student not found"):
        manager.read_student_state(uuid4())


def test_current_session_and_confusion_are_managed_by_service(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    student, session_id = create_student_session(manager, sessions)
    manager.set_current_session(student.id, session_id)
    manager.set_confusion_score(student.id, session_id, 0.7)
    state = manager.read_student_state(student.id)
    assert state.interaction.session_id == session_id
    assert state.interaction.stage == TeachingStage.GRAMMAR_REVISION
    assert state.interaction.confusion_score == pytest.approx(0.7)
    with pytest.raises(DomainError, match="between 0 and 1"):
        manager.set_confusion_score(student.id, session_id, 1.2)


def test_same_evidence_id_with_changed_content_is_rejected(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    student, session_id = create_student_session(manager, sessions)
    evidence = make_evidence(student.id, session_id, EvidenceOutcome.SUCCESS)
    manager.record_evidence(evidence)
    with pytest.raises(DomainError, match="different content"):
        manager.record_evidence(evidence.model_copy(update={"outcome": EvidenceOutcome.FAILURE}))
    assert manager.read_student_state(student.id).knowledge[0].evidence_count == 1


def test_state_survives_new_engine_and_manager(state_service: tuple) -> None:
    manager, sessions, _ = state_service
    student, session_id = create_student_session(manager, sessions)
    manager.record_evidence(make_evidence(student.id, session_id, EvidenceOutcome.SUCCESS))
    second_engine = create_database_engine(Settings())
    try:
        restarted_manager = StudentStateManager(create_session_factory(second_engine), Settings())
        assert restarted_manager.read_student_state(student.id).knowledge[0].evidence_count == 1
    finally:
        second_engine.dispose()


def test_tracing_formulas_and_edge_values() -> None:
    settings = Settings()
    assert update_bkt(0.2, True, settings) > 0.2
    assert update_bkt(0.2, False, settings) < 0.2
    assert 0 <= update_bkt(0.0, False, settings) <= 1
    assert 0 <= update_bkt(1.0, True, settings) <= 1
    assert update_ability(0.5, 1.0, settings) == pytest.approx(0.65)
    assert evidence_confidence(0, settings) == 0
    assert evidence_confidence(100, settings) < 1


def test_evidence_rejects_empty_node_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        LearningEvidence(
            student_id=uuid4(),
            session_id=uuid4(),
            knowledge_node_id="",
            outcome=EvidenceOutcome.SUCCESS,
            observed_at=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        LearningEvidence(
            student_id=uuid4(),
            session_id=uuid4(),
            knowledge_node_id="articles",
            outcome=EvidenceOutcome.SUCCESS,
            observed_at=datetime(2026, 10, 1),
        )
