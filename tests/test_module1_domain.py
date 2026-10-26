from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain import (
    AbilityDimension,
    AbilityState,
    Draft,
    ErrorRecord,
    EvaluationResult,
    KnowledgeState,
    LearningEvidence,
    RetrievalResource,
    RetrievalResult,
    Student,
    TeachingDecision,
    TeachingMode,
    TeachingSession,
    TeachingStage,
    ToolCallRecord,
    WritingTask,
)
from app.domain.enums import (
    STAGE_ORDER,
    EvaluationVerdict,
    EvidenceOutcome,
    PedagogyAction,
    ResourceOrigin,
    ResourceType,
    ToolCallStatus,
)
from pydantic import ValidationError


def test_all_shared_schemas_create_and_serialize() -> None:
    now = datetime.now(UTC)
    student = Student(grade=9, learning_goal="Write clear English essays")
    task = WritingTask(prompt="Describe a memorable day", genre="narrative", grade=9)
    session = TeachingSession(
        student_id=student.id,
        task_id=task.id,
        stage=TeachingStage.PROMPT_ANALYSIS,
        mode=TeachingMode.GUIDED,
        started_at=now,
        updated_at=now,
    )
    draft = Draft(
        student_id=student.id,
        task_id=task.id,
        version=1,
        content="I visited a museum.",
        created_at=now,
    )
    objects = [
        student,
        task,
        session,
        draft,
        AbilityState(
            dimension=AbilityDimension.GRAMMAR,
            rubric_score=0.5,
            confidence=0.4,
            evidence_count=1,
            updated_at=now,
        ),
        KnowledgeState(
            node_id="subject_verb_agreement",
            mastery=0.4,
            confidence=0.3,
            evidence_count=2,
            occurrence_count=2,
            independent_discovery_count=0,
            independent_revision_count=1,
            hint_level_total=2,
            micro_lesson_count=0,
            post_lesson_success_count=0,
            transfer_success_count=0,
            next_essay_recurrence_count=0,
        ),
        ErrorRecord(
            student_id=student.id,
            session_id=session.id,
            category="grammar",
            original_text="He go",
            observed_at=now,
        ),
        LearningEvidence(
            student_id=student.id,
            session_id=session.id,
            knowledge_node_id="subject_verb_agreement",
            outcome=EvidenceOutcome.SUCCESS,
            observed_at=now,
        ),
        TeachingDecision(
            action=PedagogyAction.SELF_CHECK,
            scaffold_level=0,
            may_reveal_answer=False,
            needs_practice=False,
            pass_condition="Student identifies issue",
            on_failure=PedagogyAction.LOCATION_HINT,
            rationale="First attempt",
        ),
        ToolCallRecord(
            session_id=session.id,
            actor="planner",
            tool_name="read_state",
            arguments={},
            status=ToolCallStatus.SUCCESS,
            duration_ms=2,
            called_at=now,
        ),
        EvaluationResult(session_id=session.id, verdict=EvaluationVerdict.PASS, evaluated_at=now),
        RetrievalResource(
            content="She goes to school.",
            resource_type=ResourceType.BASIC_SENTENCE,
            source="human-authored",
            license="CC0",
            attribution="AWT",
            origin=ResourceOrigin.HUMAN,
            processing_notes="Original example",
        ),
    ]
    result = RetrievalResult(resource=objects[-1], rank=1, score=0.9)
    for obj in [*objects, result]:
        assert type(obj).model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (Student, {"grade": 6, "learning_goal": "goal"}),
        (Student, {"grade": 9, "learning_goal": ""}),
        (Student, {"grade": 9, "learning_goal": "goal", "unknown": True}),
        (WritingTask, {"prompt": "", "genre": "essay", "grade": 9}),
        (
            TeachingSession,
            {
                "student_id": uuid4(),
                "task_id": uuid4(),
                "stage": "invented",
                "mode": "guided",
                "started_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        ),
        (
            KnowledgeState,
            {
                "node_id": "a",
                "mastery": 1.1,
                "confidence": 0.2,
                "evidence_count": 0,
                "occurrence_count": 0,
                "independent_discovery_count": 0,
                "independent_revision_count": 0,
                "hint_level_total": 0,
                "micro_lesson_count": 0,
                "post_lesson_success_count": 0,
                "transfer_success_count": 0,
                "next_essay_recurrence_count": 0,
            },
        ),
        (
            LearningEvidence,
            {
                "student_id": uuid4(),
                "session_id": uuid4(),
                "outcome": "success",
                "observed_at": datetime.now(UTC),
            },
        ),
    ],
)
def test_invalid_or_missing_fields_rejected(model: type, payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_enum_order_and_boundaries() -> None:
    assert len(STAGE_ORDER) == 8
    assert STAGE_ORDER[0] == TeachingStage.PROMPT_ANALYSIS
    assert STAGE_ORDER[-1] == TeachingStage.FINAL_EVALUATION
    assert Student(grade=7, learning_goal="Learn").grade == 7
    assert Student(grade=12, learning_goal="Learn").grade == 12
    with pytest.raises(ValidationError):
        Student(grade=13, learning_goal="Learn")


def test_repeated_creation_has_independent_defaults() -> None:
    first = Student(grade=9, learning_goal="A")
    second = Student(grade=9, learning_goal="B")
    first.preferences["pace"] = "slow"
    assert first.id != second.id
    assert second.preferences == {}
