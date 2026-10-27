import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.agents.evaluator import PedagogyEvaluator
from app.agents.planner import PlannerAgent
from app.agents.schemas import EvaluatorJudgement, TeachingText
from app.agents.teaching import TeachingAgent
from app.agents.tool_runtime import build_agent_tools
from app.agents.tracing import ToolTraceStore
from app.api.main import create_app
from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import create_database_engine, create_session_factory
from app.domain import Student, TeachingMode, TeachingStage
from app.domain.enums import EvidenceOutcome, ToolCallStatus
from app.domain.schemas import ErrorRecord, LearningEvidence
from app.models import (
    AbilityStateRecord,
    DraftRecord,
    StudentStateRecord,
    TeachingSessionRecord,
    WorkflowEventRecord,
    WritingTaskRecord,
)
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.grammar.transfer import transfer_succeeded
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.seed import seed_canonical_graph
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.store import ResourceStore
from app.services.student_state.manager import StudentStateManager
from app.workflows.graph import WritingWorkflow
from app.workflows.schemas import (
    ContentPlan,
    PromptAnalysisAnswer,
    StructurePlan,
    WorkflowSubmission,
)
from app.workflows.stage_gate import StageGate
from app.workflows.store import WorkflowStore
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select


class ScriptedProvider:
    def __init__(self) -> None:
        self.teaching_calls = 0
        self.evaluation_calls = 0

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type
    ) -> object:
        if response_type is TeachingText:
            self.teaching_calls += 1
            return TeachingText(text="Check the current stage and make your own next attempt.")
        if response_type is EvaluatorJudgement:
            self.evaluation_calls += 1
            return EvaluatorJudgement(
                accurate_to_issue=True,
                scaffold_too_strong=False,
                scaffold_too_weak=False,
                actionable_next_step=True,
                stage_appropriate=True,
                ghostwriting=False,
                rationale="Aligned with stage and policy",
            )
        raise AssertionError(response_type)


class RejectingProvider(ScriptedProvider):
    def __init__(self, rejects: int) -> None:
        super().__init__()
        self.rejects = rejects

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type
    ) -> object:
        result = await super().generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_type=response_type,
        )
        if response_type is EvaluatorJudgement and self.evaluation_calls <= self.rejects:
            return EvaluatorJudgement(
                accurate_to_issue=True,
                scaffold_too_strong=False,
                scaffold_too_weak=False,
                actionable_next_step=True,
                stage_appropriate=True,
                ghostwriting=True,
                rationale="The reply writes the student's essay",
            )
        return result


class FailingOnceProvider(ScriptedProvider):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type
    ) -> object:
        if response_type is TeachingText and not self.failed:
            self.failed = True
            raise RuntimeError("temporary model interruption")
        return await super().generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_type=response_type,
        )


def setup_workflow(provider: ScriptedProvider):
    settings = Settings()
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    graph = GrammarKnowledgeGraph(sessions)
    seed_canonical_graph(sessions)
    retriever = HybridRetriever(ResourceStore(sessions), settings)
    retriever.load_index()
    manager = StudentStateManager(sessions, settings)
    student = Student(grade=9, learning_goal="Improve English writing")
    manager.initialize_student(student)
    task_id, session_id = uuid4(), uuid4()
    with sessions.begin() as db:
        db.add(
            WritingTaskRecord(
                id=task_id, prompt="Describe your school day", genre="narrative", grade=9
            )
        )
        db.flush()
        db.add(
            TeachingSessionRecord(
                id=session_id,
                student_id=student.id,
                task_id=task_id,
                stage=TeachingStage.PROMPT_ANALYSIS,
                mode=TeachingMode.GUIDED,
            )
        )
    manager.set_current_session(student.id, session_id)
    tools = build_agent_tools(manager, graph, retriever, ToolTraceStore(sessions).record)
    policy = PedagogyPolicy()
    analyzer = GrammarAnalyzer(graph)
    store = WorkflowStore(sessions, manager, StageGate(analyzer))
    return (
        settings,
        engine,
        sessions,
        manager,
        student.id,
        session_id,
        store,
        PlannerAgent(tools),
        analyzer,
        policy,
        TeachingAgent(provider, tools, policy),
        PedagogyEvaluator(provider, policy),
    )


INITIAL = (
    "She go to school every morning. I enjoy studying with my classmates after school. "
    "We discuss books and plan small projects together. "
    "Our teacher encourages us to share ideas clearly."
)
CORRECTED = INITIAL.replace("She go to school", "She goes to school")


def test_full_essay_workflow_and_idempotent_response() -> None:
    provider = ScriptedProvider()
    setup = setup_workflow(provider)
    (
        settings,
        engine,
        sessions,
        manager,
        student_id,
        session_id,
        store,
        planner,
        analyzer,
        policy,
        teacher,
        evaluator,
    ) = setup

    async def run():
        async with WritingWorkflow.postgres_checkpointer(settings) as saver:
            workflow = WritingWorkflow(
                store=store,
                manager=manager,
                planner=planner,
                analyzer=analyzer,
                policy=policy,
                teacher=teacher,
                evaluator=evaluator,
                checkpointer=saver,
            )
            submissions = [
                WorkflowSubmission(kind="start"),
                WorkflowSubmission(
                    kind="response",
                    prompt_analysis=PromptAnalysisAnswer(
                        audience="classmates",
                        purpose="describe",
                        genre="narrative",
                        required_points=["school day"],
                        tense="present",
                        person="first",
                        constraints="stay on topic",
                    ),
                ),
                WorkflowSubmission(kind="response", text=INITIAL),
                WorkflowSubmission(kind="response", text=CORRECTED, transfer_response="rides"),
                WorkflowSubmission(
                    kind="response",
                    text=CORRECTED,
                    structure_plan=StructurePlan(
                        opening="introduce my day",
                        body="explain classes",
                        conclusion="reflect on learning",
                    ),
                ),
                WorkflowSubmission(
                    kind="response",
                    text=CORRECTED + " I remember one science project in detail.",
                    content_plan=ContentPlan(
                        viewpoint="School is interesting",
                        reason="I learn with friends",
                        example="Science project",
                        detail="We built a model",
                        result_or_feeling="I felt proud",
                    ),
                ),
                WorkflowSubmission(
                    kind="response",
                    text=CORRECTED
                    + " I remember one science project in detail. We worked together.",
                    relation_explanation="The last sentence adds a result.",
                ),
                WorkflowSubmission(
                    kind="response",
                    text=CORRECTED + " I remember one science project in detail. "
                    "We worked together and felt proud.",
                    independent_revision=True,
                ),
                WorkflowSubmission(kind="finalize"),
            ]
            results = []
            for index, submission in enumerate(submissions):
                result = await workflow.run(
                    session_id=session_id,
                    student_id=student_id,
                    submission=submission,
                )
                results.append(result)
                assert result.blocked is False
                if index == 2:
                    checkpoint = await workflow.graph.aget_state(
                        {"configurable": {"thread_id": str(submission.request_id)}}
                    )
                    assert checkpoint.values["plan"]["target_knowledge_node_id"] == (
                        "subject_verb_agreement"
                    )
                    assert {
                        "stage",
                        "mode",
                        "current_draft",
                        "first_draft",
                        "plan",
                        "diagnosis",
                        "policy_context",
                        "decision",
                        "teaching_turn",
                        "evaluation",
                        "retry_count",
                        "result",
                    } <= checkpoint.values.keys()
            repeated = await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=submissions[1],
            )
            assert repeated == results[1]
            return results

    try:
        results = asyncio.run(run())
        assert [result.stage for result in results] == list(TeachingStage) + [
            TeachingStage.FINAL_EVALUATION
        ]
        assert results[-2].feedback == "Independent Draft 2 recorded."
        assert results[-2].teaching_text is None
        assert results[-2].evaluation_verdict is None
        assert results[-1].completed is True
        assert results[-1].teaching_text is None
        assert results[-1].final_comparison is not None
        assert results[-1].final_comparison.resolved == {"subject_verb_agreement": 1}
        with sessions() as db:
            session = db.get(TeachingSessionRecord, session_id)
            assert session is not None and session.completed_at is not None
            assert (
                db.scalar(
                    select(func.count(DraftRecord.id)).where(DraftRecord.task_id == session.task_id)
                )
                == 6
            )
            assert (
                db.scalar(
                    select(func.count(WorkflowEventRecord.id)).where(
                        WorkflowEventRecord.session_id == session_id
                    )
                )
                == 9
            )
            events = db.scalars(
                select(WorkflowEventRecord).where(WorkflowEventRecord.session_id == session_id)
            ).all()
            scored = [
                event.stage_outcome
                for event in events
                if event.stage_outcome and event.stage_outcome.get("rubric")
            ]
            assert len(scored) == 6
            for outcome in scored:
                assert outcome["evidence"]["rubric_score"] == outcome["rubric"]["score"]
                assert outcome["rubric"]["version"] == "observable-writing-v1"
        abilities = {
            item.dimension.value: item for item in manager.read_student_state(student_id).abilities
        }
        assert {name: item.evidence_count for name, item in abilities.items()} == {
            "content": 1,
            "grammar": 2,
            "prompt_analysis": 1,
            "sentence_expression": 1,
            "structure": 1,
        }
        expected_scores = {name: settings.ability_initial_score for name in abilities}
        for event in sorted(events, key=lambda item: item.created_at):
            outcome = event.stage_outcome or {}
            if outcome.get("rubric"):
                dimension = outcome["evidence"]["ability_dimension"]
                expected_scores[dimension] = (
                    settings.ability_ema_alpha * outcome["rubric"]["score"]
                    + (1 - settings.ability_ema_alpha) * expected_scores[dimension]
                )
        for name, ability in abilities.items():
            assert ability.rubric_score == pytest.approx(expected_scores[name])
        assert sum(ability.evidence_count for ability in abilities.values()) == 6
        assert manager.read_student_state(student_id).prompt_dependency.evidence_count == 8
    finally:
        engine.dispose()


def test_scored_evidence_recovery_after_stage_commit() -> None:
    setup = setup_workflow(ScriptedProvider())
    _, engine, sessions, manager, student_id, session_id, store, *_ = setup
    submission = WorkflowSubmission(
        kind="response",
        prompt_analysis=PromptAnalysisAnswer(
            audience="my classmates at school",
            purpose="describe the events of our school day",
            genre="narrative",
            required_points=["school day"],
            tense="present",
            person="first",
            constraints="include the classes and my own feelings",
        ),
    )
    try:
        assert store.register(session_id, student_id, submission) is None
        with sessions.begin() as db:
            event = db.get(WorkflowEventRecord, submission.request_id, with_for_update=True)
            assert event is not None
            committed_outcome = store._apply_new(db, event)
        assert committed_outcome.rubric is not None
        prompt_before = next(
            item
            for item in manager.read_student_state(student_id).abilities
            if item.dimension.value == "prompt_analysis"
        )
        assert prompt_before.evidence_count == 0

        recovered = store.apply(submission.request_id)
        assert recovered.rubric == committed_outcome.rubric
        assert recovered.evidence is not None
        assert recovered.evidence.rubric_score == recovered.rubric.score
        assert store.apply(submission.request_id) == recovered
        prompt_after = next(
            item
            for item in manager.read_student_state(student_id).abilities
            if item.dimension.value == "prompt_analysis"
        )
        assert prompt_after.evidence_count == 1
        assert prompt_after.rubric_score > prompt_before.rubric_score
        with sessions() as db:
            session = db.get(TeachingSessionRecord, session_id)
            assert session is not None and session.stage == TeachingStage.FIRST_DRAFT
    finally:
        engine.dispose()


def test_stage_failure_invalid_input_and_entry_gate() -> None:
    provider = ScriptedProvider()
    setup = setup_workflow(provider)
    (
        settings,
        engine,
        sessions,
        manager,
        student_id,
        session_id,
        store,
        planner,
        analyzer,
        policy,
        teacher,
        evaluator,
    ) = setup

    async def run():
        async with WritingWorkflow.postgres_checkpointer(settings) as saver:
            workflow = WritingWorkflow(
                store=store,
                manager=manager,
                planner=planner,
                analyzer=analyzer,
                policy=policy,
                teacher=teacher,
                evaluator=evaluator,
                checkpointer=saver,
            )
            wrong = WorkflowSubmission(
                kind="response",
                prompt_analysis=PromptAnalysisAnswer(
                    audience="classmates",
                    purpose="describe",
                    genre="argumentative",
                    required_points=["school"],
                    tense="present",
                    person="first",
                    constraints="none",
                ),
            )
            first = await workflow.run(
                session_id=session_id, student_id=student_id, submission=wrong
            )
            assert first.stage == TeachingStage.PROMPT_ANALYSIS
            assert first.stage_passed is False
            state = manager.read_student_state(student_id)
            assert state.interaction.consecutive_failures == 1
            prompt_ability = next(
                item for item in state.abilities if item.dimension.value == "prompt_analysis"
            )
            assert prompt_ability.evidence_count == 1
            assert prompt_ability.rubric_score < 0.5
            assert (
                prompt_ability.rubric_score
                > (1 - settings.ability_ema_alpha) * settings.ability_initial_score
            )
            return first

    try:
        asyncio.run(run())
        with pytest.raises(ValidationError):
            WorkflowSubmission(kind="response", text="")
        with pytest.raises(ValidationError):
            WorkflowSubmission(kind="start", text="not allowed")
        with sessions.begin() as db:
            session = db.get(TeachingSessionRecord, session_id)
            assert session is not None
            session.stage = TeachingStage.GRAMMAR_REVISION
        with pytest.raises(DomainError, match="prior draft"):
            store.apply(
                next_event_id_for_stage(
                    sessions, session_id, student_id, TeachingStage.GRAMMAR_REVISION
                )
            )
    finally:
        engine.dispose()


def next_event_id_for_stage(sessions, session_id, student_id, stage):
    request_id = uuid4()
    submission = WorkflowSubmission(request_id=request_id, kind="response", text=CORRECTED)
    with sessions.begin() as db:
        db.add(
            WorkflowEventRecord(
                id=request_id,
                session_id=session_id,
                student_id=student_id,
                payload=submission.model_dump(mode="json"),
                stage_before=stage.value,
            )
        )
    return request_id


def test_evaluator_regeneration_limit_and_blocked_output() -> None:
    provider = RejectingProvider(rejects=10)
    setup = setup_workflow(provider)
    (
        settings,
        engine,
        _sessions,
        manager,
        student_id,
        session_id,
        store,
        planner,
        analyzer,
        policy,
        teacher,
        evaluator,
    ) = setup

    async def run():
        async with WritingWorkflow.postgres_checkpointer(settings) as saver:
            workflow = WritingWorkflow(
                store=store,
                manager=manager,
                planner=planner,
                analyzer=analyzer,
                policy=policy,
                teacher=teacher,
                evaluator=evaluator,
                checkpointer=saver,
                max_regenerations=2,
            )
            return await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=WorkflowSubmission(kind="start"),
            )

    try:
        result = asyncio.run(run())
        assert result.blocked is True
        assert result.teaching_text is None
        assert result.retries == 2
        assert provider.teaching_calls == 3
        assert provider.evaluation_calls == 3
    finally:
        engine.dispose()


def test_evaluator_rejection_regenerates_then_passes() -> None:
    provider = RejectingProvider(rejects=1)
    setup = setup_workflow(provider)
    (
        settings,
        engine,
        _sessions,
        manager,
        student_id,
        session_id,
        store,
        planner,
        analyzer,
        policy,
        teacher,
        evaluator,
    ) = setup

    async def run():
        async with WritingWorkflow.postgres_checkpointer(settings) as saver:
            workflow = WritingWorkflow(
                store=store,
                manager=manager,
                planner=planner,
                analyzer=analyzer,
                policy=policy,
                teacher=teacher,
                evaluator=evaluator,
                checkpointer=saver,
                max_regenerations=2,
            )
            return await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=WorkflowSubmission(kind="start"),
            )

    try:
        result = asyncio.run(run())
        assert result.blocked is False
        assert result.evaluation_verdict == "pass"
        assert result.retries == 1
        assert provider.teaching_calls == 2
        assert provider.evaluation_calls == 2
    finally:
        engine.dispose()


def test_resume_after_model_interruption_without_duplicate_evidence() -> None:
    provider = FailingOnceProvider()
    setup = setup_workflow(provider)
    (
        settings,
        engine,
        sessions,
        manager,
        student_id,
        session_id,
        store,
        planner,
        analyzer,
        policy,
        teacher,
        evaluator,
    ) = setup

    async def run():
        async with WritingWorkflow.postgres_checkpointer(settings) as saver:
            submission = WorkflowSubmission(
                kind="response",
                prompt_analysis=PromptAnalysisAnswer(
                    audience="classmates",
                    purpose="describe",
                    genre="narrative",
                    required_points=["school"],
                    tense="present",
                    person="first",
                    constraints="none",
                ),
            )
            workflow = WritingWorkflow(
                store=store,
                manager=manager,
                planner=planner,
                analyzer=analyzer,
                policy=policy,
                teacher=teacher,
                evaluator=evaluator,
                checkpointer=saver,
            )
            with pytest.raises(RuntimeError, match="temporary model interruption"):
                await workflow.run(
                    session_id=session_id, student_id=student_id, submission=submission
                )
            assert manager.read_student_state(student_id).prompt_dependency.evidence_count == 1
            restarted = WritingWorkflow(
                store=store,
                manager=manager,
                planner=planner,
                analyzer=analyzer,
                policy=policy,
                teacher=teacher,
                evaluator=evaluator,
                checkpointer=saver,
            )
            result = await restarted.run(
                session_id=session_id, student_id=student_id, submission=submission
            )
            assert manager.read_student_state(student_id).prompt_dependency.evidence_count == 1
            return result

    try:
        result = asyncio.run(run())
        assert result.stage == TeachingStage.FIRST_DRAFT
        assert result.blocked is False
        with sessions() as db:
            assert (
                db.scalar(
                    select(func.count(WorkflowEventRecord.id)).where(
                        WorkflowEventRecord.session_id == session_id
                    )
                )
                == 1
            )
    finally:
        engine.dispose()


def test_independent_mode_suppresses_teaching_generation() -> None:
    provider = ScriptedProvider()
    setup = setup_workflow(provider)
    (
        settings,
        engine,
        sessions,
        manager,
        student_id,
        session_id,
        store,
        planner,
        analyzer,
        policy,
        teacher,
        evaluator,
    ) = setup
    with sessions.begin() as db:
        for ability in db.scalars(
            select(AbilityStateRecord).where(AbilityStateRecord.student_id == student_id)
        ):
            ability.rubric_score = 0.9
            ability.evidence_count = 5
        summary = db.get(StudentStateRecord, student_id)
        assert summary is not None
        summary.independent_revision_count = 3
        summary.evidence_count = 3

    async def run():
        async with WritingWorkflow.postgres_checkpointer(settings) as saver:
            workflow = WritingWorkflow(
                store=store,
                manager=manager,
                planner=planner,
                analyzer=analyzer,
                policy=policy,
                teacher=teacher,
                evaluator=evaluator,
                checkpointer=saver,
            )
            start = await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=WorkflowSubmission(kind="start"),
            )
            next_turn = await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=WorkflowSubmission(
                    kind="response",
                    text="I will write a narrative about my school day for a friend.",
                ),
            )
            return start, next_turn

    try:
        start, next_turn = asyncio.run(run())
        assert start.mode == TeachingMode.INDEPENDENT
        assert start.teaching_text is None
        assert next_turn.stage == TeachingStage.FIRST_DRAFT
        assert next_turn.teaching_text is None
        assert provider.teaching_calls == 0
        assert provider.evaluation_calls == 0
        prompt_ability = next(
            item
            for item in manager.read_student_state(student_id).abilities
            if item.dimension.value == "prompt_analysis"
        )
        assert prompt_ability.evidence_count == 6
    finally:
        engine.dispose()


def test_workflow_http_contract_and_missing_index_fallback(tmp_path) -> None:
    settings = Settings(retrieval_index_path=tmp_path / "missing.npz")
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    seed_canonical_graph(sessions)
    provider = ScriptedProvider()
    student = Student(grade=9, learning_goal="Improve English writing")
    task_id = uuid4()
    session_id = uuid4()
    request_id = uuid4()
    try:
        with TestClient(create_app(settings, provider)) as client:
            student_response = client.post("/students", json=student.model_dump(mode="json"))
            assert student_response.status_code == 200
            task_response = client.post(
                "/tasks",
                json={
                    "id": str(task_id),
                    "prompt": "Describe your school day",
                    "genre": "narrative",
                    "grade": 9,
                    "required_points": ["classes", "friends"],
                },
            )
            assert task_response.status_code == 200
            session_response = client.post(
                "/sessions",
                json={
                    "id": str(session_id),
                    "student_id": str(student.id),
                    "task_id": str(task_id),
                },
            )
            assert session_response.status_code == 200
            assert session_response.json()["task"]["required_points"] == ["classes", "friends"]
            payload = {
                "student_id": str(student.id),
                "submission": {"request_id": str(request_id), "kind": "start"},
            }
            result = client.post(f"/sessions/{session_id}/turn", json=payload)
            assert result.status_code == 200
            assert result.json()["stage"] == "prompt_analysis"
            repeated = client.post(f"/sessions/{session_id}/turn", json=payload)
            assert repeated.json() == result.json()
            view = client.get(f"/sessions/{session_id}", params={"student_id": str(student.id)})
            assert view.status_code == 200
            assert view.json()["mode"] == "guided"
            assert (
                client.get(
                    f"/sessions/{session_id}", params={"student_id": str(uuid4())}
                ).status_code
                == 404
            )
    finally:
        engine.dispose()


def test_workflow_degrades_when_retrieval_index_is_missing(tmp_path) -> None:
    provider = ScriptedProvider()
    setup = setup_workflow(provider)
    (
        settings,
        engine,
        sessions,
        manager,
        student_id,
        session_id,
        store,
        _planner,
        analyzer,
        policy,
        _teacher,
        evaluator,
    ) = setup
    settings.retrieval_index_path = tmp_path / "missing.npz"
    issue = analyzer.analyze(INITIAL).errors[0]
    with sessions.begin() as db:
        session = db.get(TeachingSessionRecord, session_id)
        assert session is not None
        session.stage = TeachingStage.GRAMMAR_REVISION
        draft = DraftRecord(
            id=uuid4(),
            student_id=student_id,
            task_id=session.task_id,
            version=1,
            content=INITIAL,
        )
        db.add(draft)
        session.current_draft_id = draft.id
    for _ in range(2):
        manager.record_error(
            ErrorRecord(
                student_id=student_id,
                session_id=session_id,
                category=issue.primary_category,
                knowledge_node_id=issue.knowledge_node_id,
                original_text=issue.original_expression,
                observed_at=datetime.now(UTC),
            )
        )
        manager.record_evidence(
            LearningEvidence(
                student_id=student_id,
                session_id=session_id,
                knowledge_node_id=issue.knowledge_node_id,
                outcome=EvidenceOutcome.FAILURE,
                observed_at=datetime.now(UTC),
            )
        )
    graph = GrammarKnowledgeGraph(sessions)
    retriever = HybridRetriever(ResourceStore(sessions), settings)
    trace_store = ToolTraceStore(sessions)
    tools = build_agent_tools(manager, graph, retriever, trace_store.record)

    async def run():
        async with WritingWorkflow.postgres_checkpointer(settings) as saver:
            workflow = WritingWorkflow(
                store=store,
                manager=manager,
                planner=PlannerAgent(tools),
                analyzer=analyzer,
                policy=policy,
                teacher=TeachingAgent(provider, tools, policy),
                evaluator=evaluator,
                checkpointer=saver,
            )
            start = await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=WorkflowSubmission(kind="start"),
            )
            wrong = await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=WorkflowSubmission(
                    kind="response", text=CORRECTED, transfer_response="rides"
                ),
            )
            correct = await workflow.run(
                session_id=session_id,
                student_id=student_id,
                submission=WorkflowSubmission(
                    kind="response",
                    text=CORRECTED,
                    transfer_response="He goes to school.",
                ),
            )
            return start, wrong, correct

    try:
        start, wrong, correct = asyncio.run(run())
        assert start.blocked is False
        assert start.transfer_prompt == "Correct this new sentence: He go to school."
        assert wrong.stage == TeachingStage.GRAMMAR_REVISION
        assert wrong.stage_passed is False
        assert correct.stage == TeachingStage.STRUCTURE_REVISION
        assert correct.stage_passed is True
        assert manager.read_student_state(student_id).prompt_dependency.transfer_success_count == 1
        assert any(
            item.tool_name == "find_teaching_material" and item.status == ToolCallStatus.DEGRADED
            for item in trace_store.for_session(session_id)
        )
    finally:
        engine.dispose()


def test_transfer_answer_requires_verified_correction() -> None:
    assert transfer_succeeded("subject_verb_agreement", "rides") is False
    assert transfer_succeeded("subject_verb_agreement", "He goes to school.") is True
    assert transfer_succeeded("unknown", "anything") is False


def test_same_request_cannot_run_concurrently() -> None:
    provider = ScriptedProvider()
    setup = setup_workflow(provider)
    engine, store = setup[1], setup[6]
    request_id = uuid4()
    try:
        with store.run_lock(request_id):
            with pytest.raises(DomainError, match="already running"):
                with store.run_lock(request_id):
                    pass
        with store.run_lock(request_id):
            pass
    finally:
        engine.dispose()
