from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.domain import ErrorRecord, LearningEvidence, Student, TeachingMode, TeachingStage
from app.domain.enums import EvidenceOutcome, PedagogyAction
from app.domain.schemas import TeachingDecision
from app.models import TeachingSessionRecord, WritingTaskRecord
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.seed import seed_canonical_graph
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.pedagogy.schemas import IntentLabel, PolicyContext, StudentIntent
from app.services.student_state.manager import StudentStateManager
from pydantic import ValidationError


def context(**changes: object) -> PolicyContext:
    base: dict[str, object] = {
        "stage": TeachingStage.GRAMMAR_REVISION,
        "issue_type": "subject_verb_agreement",
        "target_knowledge_node_id": "subject_verb_agreement",
        "mastery": 0.9,
        "mastery_confidence": 0.8,
        "historical_error_count": 1,
        "recent_error_recurrence": False,
        "mode": TeachingMode.GUIDED,
        "intent": StudentIntent(primary=IntentLabel.ATTEMPT),
        "consecutive_failures": 0,
        "average_hint_level": 0,
        "confusion_score": 0,
    }
    base.update(changes)
    return PolicyContext.model_validate(base)


def test_high_mastery_first_error_uses_light_scaffold() -> None:
    decision = PedagogyPolicy().decide(context())
    assert decision.action == PedagogyAction.SELF_CHECK
    assert decision.scaffold_level == 0
    assert decision.may_reveal_answer is False
    assert decision.on_failure == PedagogyAction.LOCATION_HINT
    uncertain = PedagogyPolicy().decide(context(mastery_confidence=0.1))
    assert uncertain.scaffold_level >= decision.scaffold_level


def test_failure_escalates_scaffold_and_guided_can_use_stronger_support() -> None:
    policy = PedagogyPolicy()
    initial = policy.decide(context())
    after_two = policy.decide(context(consecutive_failures=2, mastery=0.3))
    assert after_two.scaffold_level > initial.scaffold_level
    assert after_two.action != PedagogyAction.SELF_CHECK
    assert PedagogyAction.LOCAL_DEMONSTRATION in policy.allowed_actions(
        context(consecutive_failures=2, mastery=0.3)
    )
    assert PedagogyAction.LOCAL_DEMONSTRATION not in policy.allowed_actions(
        context(mode=TeachingMode.SEMI_GUIDED)
    )


def test_repeated_error_selects_knowledge_graph_micro_lesson() -> None:
    decision = PedagogyPolicy().decide(
        context(
            mastery=0.25,
            historical_error_count=3,
            recent_error_recurrence=True,
        )
    )
    assert decision.action == PedagogyAction.KG_MICRO_LESSON
    assert decision.target_knowledge_node_id == "subject_verb_agreement"
    assert decision.needs_practice is True
    assert decision.practice_type == "transfer"
    assert "repeated_error" in decision.ranking[0].reasons


def test_independent_mode_filters_all_hints_even_on_direct_request() -> None:
    policy = PedagogyPolicy()
    requested = StudentIntent(primary=IntentLabel.REQUEST_ANSWER, requests_direct_answer=True)
    independent = context(
        mode=TeachingMode.INDEPENDENT,
        intent=requested,
        consecutive_failures=5,
        last_action=PedagogyAction.KG_MICRO_LESSON,
        last_action_succeeded=False,
    )
    assert policy.allowed_actions(independent) == {PedagogyAction.INDEPENDENT_RETRY}
    decision = policy.decide(independent)
    assert decision.action == PedagogyAction.INDEPENDENT_RETRY
    assert decision.may_reveal_answer is False
    assert decision.scaffold_level == 0
    assert decision.on_failure == PedagogyAction.INDEPENDENT_RETRY
    assert len(decision.ranking) == 1


def test_direct_request_cannot_trigger_explanation_without_prior_support_failure() -> None:
    policy = PedagogyPolicy()
    requested = StudentIntent(primary=IntentLabel.REQUEST_ANSWER, requests_direct_answer=True)
    for candidate in (
        context(intent=requested),
        context(intent=requested, consecutive_failures=3),
        context(
            intent=requested,
            consecutive_failures=3,
            last_action=PedagogyAction.CONCEPT_HINT,
            last_action_succeeded=True,
        ),
    ):
        assert PedagogyAction.DIRECT_EXPLANATION not in policy.allowed_actions(candidate)
        assert policy.decide(candidate).may_reveal_answer is False

    justified = context(
        intent=requested,
        consecutive_failures=3,
        last_action=PedagogyAction.CONCEPT_HINT,
        last_action_succeeded=False,
        mastery=0.25,
    )
    assert PedagogyAction.DIRECT_EXPLANATION in policy.allowed_actions(justified)
    decision = policy.decide(justified)
    assert decision.action == PedagogyAction.DIRECT_EXPLANATION
    assert decision.may_reveal_answer is True
    assert "three_failures_after_strong_support" in decision.ranking[0].reasons


def test_stage_filtering_and_missing_graph_target() -> None:
    policy = PedagogyPolicy()
    assert policy.allowed_actions(context(stage=TeachingStage.SECOND_DRAFT)) == {
        PedagogyAction.INDEPENDENT_RETRY
    }
    content = policy.allowed_actions(context(stage=TeachingStage.CONTENT_EXPANSION))
    assert PedagogyAction.DIRECT_EXPLANATION not in content
    assert PedagogyAction.LOCAL_DEMONSTRATION not in content
    assert PedagogyAction.KG_MICRO_LESSON not in policy.allowed_actions(
        context(target_knowledge_node_id=None, historical_error_count=4)
    )
    assert PedagogyAction.TRANSFER_PRACTICE not in policy.allowed_actions(context())
    assert PedagogyAction.TRANSFER_PRACTICE in policy.allowed_actions(
        context(last_action=PedagogyAction.CONCEPT_HINT, last_action_succeeded=True)
    )


def test_ranking_is_explainable_stable_and_structured() -> None:
    policy = PedagogyPolicy()
    input_context = context(
        mastery=0.5,
        mastery_confidence=0.3,
        intent=StudentIntent(primary=IntentLabel.EXPRESS_CONFUSION, confusion=0.8),
    )
    first = policy.decide(input_context)
    second = policy.decide(input_context)
    assert first == second
    assert first.ranking
    assert first.ranking[0].action == first.action
    assert [item.score for item in first.ranking] == sorted(
        (item.score for item in first.ranking), reverse=True
    )
    assert all(item.reasons for item in first.ranking)
    assert all(item.action in policy.allowed_actions(input_context) for item in first.ranking)
    assert all(label in first.rationale for label in ("stage=", "issue=", "mastery=", "mode="))
    assert TeachingDecision.model_validate_json(first.model_dump_json()) == first
    assert "student_reply" not in TeachingDecision.model_fields
    assert "message" not in TeachingDecision.model_fields


def test_invalid_and_boundary_input_rejected_without_side_effects() -> None:
    for invalid in (
        {"mastery": -0.01},
        {"mastery_confidence": 1.01},
        {"consecutive_failures": -1},
        {"average_hint_level": 5},
        {"stage": "unknown"},
        {"mode": "free"},
        {"issue_type": ""},
        {"unexpected": "field"},
    ):
        with pytest.raises(ValidationError):
            context(**invalid)
    with pytest.raises(ValidationError):
        StudentIntent(primary=IntentLabel.OTHER, frustration=1.1)
    with pytest.raises(ValidationError):
        PolicyContext.model_validate({})
    assert PedagogyPolicy().decide(context(mastery=0, mastery_confidence=0)).action
    assert PedagogyPolicy().decide(context(mastery=1, mastery_confidence=1)).action


def test_actual_state_graph_and_diagnostic_feed_policy() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        sessions = create_session_factory(engine)
        seed_canonical_graph(sessions)
        graph = GrammarKnowledgeGraph(sessions)
        diagnostic = GrammarAnalyzer(graph).analyze("She go to school.").errors[0]
        assert diagnostic.knowledge_node_id == "subject_verb_agreement"
        manager = StudentStateManager(sessions, settings)
        student = Student(grade=9, learning_goal="Improve writing")
        manager.initialize_student(student)
        task_id, session_id = uuid4(), uuid4()
        with sessions.begin() as db:
            db.add(WritingTaskRecord(id=task_id, prompt="A school day", genre="narrative", grade=9))
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
        for _ in range(2):
            manager.record_evidence(
                LearningEvidence(
                    student_id=student.id,
                    session_id=session_id,
                    knowledge_node_id=diagnostic.knowledge_node_id,
                    outcome=EvidenceOutcome.FAILURE,
                    observed_at=datetime.now(UTC),
                )
            )
            manager.record_error(
                ErrorRecord(
                    student_id=student.id,
                    session_id=session_id,
                    category=diagnostic.primary_category,
                    knowledge_node_id=diagnostic.knowledge_node_id,
                    original_text=diagnostic.original_expression,
                    observed_at=datetime.now(UTC),
                )
            )
        snapshot = manager.read_student_state(student.id)
        assert snapshot.interaction.consecutive_failures == 2
        policy_context = PolicyContext.from_student_state(
            snapshot,
            stage=TeachingStage.GRAMMAR_REVISION,
            mode=TeachingMode.GUIDED,
            issue_type=diagnostic.primary_category,
            target_knowledge_node_id=diagnostic.knowledge_node_id,
            intent=StudentIntent(primary=IntentLabel.REQUEST_HELP),
            recent_error_recurrence=True,
        )
        assert policy_context.historical_error_count == 2
        assert policy_context.mastery < 0.2
        decision = PedagogyPolicy().decide(policy_context)
        assert decision.action == PedagogyAction.KG_MICRO_LESSON
        assert decision.target_knowledge_node_id == diagnostic.knowledge_node_id
        assert manager.read_student_state(student.id) == snapshot
    finally:
        engine.dispose()
