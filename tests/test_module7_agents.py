import asyncio
import json
from datetime import UTC, datetime
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agents.evaluator import PedagogyEvaluator
from app.agents.planner import PlannerAgent
from app.agents.schemas import (
    PlannerPlan,
    TeachingRequest,
    TeachingText,
    TeachingTurn,
)
from app.agents.teaching import TeachingAgent
from app.agents.tool_runtime import AgentToolRuntime, ReadStateArgs, ToolSpec, build_agent_tools
from app.agents.tracing import ToolTraceStore
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.responses_provider import ResponsesModelProvider, configured_responses_provider
from app.db.session import create_database_engine, create_session_factory
from app.domain import AbilityState, KnowledgeState, Student, TeachingMode, TeachingStage
from app.domain.enums import (
    AbilityDimension,
    EvaluationVerdict,
    EvidenceOutcome,
    PedagogyAction,
    ToolCallStatus,
)
from app.domain.schemas import ErrorRecord, LearningEvidence
from app.models import TeachingSessionRecord, WritingTaskRecord
from app.services.grammar.schemas import GrammarError
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.seed import seed_canonical_graph
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.pedagogy.schemas import IntentLabel, PolicyContext, StudentIntent
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.store import ResourceStore
from app.services.student_state.manager import StudentStateManager
from app.services.student_state.schemas import (
    InteractionState,
    PromptDependency,
    StudentStateSnapshot,
)
from httpx import AsyncClient, MockTransport, Request, Response
from openai import AsyncOpenAI
from pydantic import SecretStr, ValidationError


class ScriptedProvider:
    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, type]] = []

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type
    ) -> object:
        self.calls.append((system_prompt, user_prompt, response_type))
        return response_type.model_validate(self.replies.pop(0))


def snapshot(
    *,
    mastery: float | None = None,
    ability_score: float = 0.5,
    independent_revisions: int = 0,
    hints: float = 0,
) -> StudentStateSnapshot:
    student = Student(grade=9, learning_goal="Improve English writing")
    abilities = [
        AbilityState(
            dimension=dimension,
            rubric_score=ability_score,
            confidence=0.5,
            evidence_count=1,
            updated_at=datetime.now(UTC),
        )
        for dimension in AbilityDimension
    ]
    knowledge = (
        [
            KnowledgeState(
                node_id="subject_verb_agreement",
                mastery=mastery,
                confidence=0.6,
                evidence_count=3,
                occurrence_count=3,
                independent_discovery_count=0,
                independent_revision_count=0,
                hint_level_total=0,
                micro_lesson_count=0,
                post_lesson_success_count=0,
                transfer_success_count=0,
                next_essay_recurrence_count=0,
            )
        ]
        if mastery is not None
        else []
    )
    return StudentStateSnapshot(
        student=student,
        abilities=abilities,
        knowledge=knowledge,
        error_patterns=[],
        prompt_dependency=PromptDependency(
            evidence_count=4,
            average_hint_level=hints,
            independent_revision_count=independent_revisions,
            micro_lesson_count=0,
            post_lesson_success_count=0,
            transfer_success_count=0,
        ),
        interaction=InteractionState(
            session_id=None,
            task_id=None,
            stage=None,
            mode=None,
            consecutive_failures=0,
            current_hint_level=0,
            confusion_score=0,
        ),
    )


def policy_context(
    *, mode: TeachingMode = TeachingMode.GUIDED, repeated: bool = False
) -> PolicyContext:
    return PolicyContext(
        stage=TeachingStage.GRAMMAR_REVISION,
        issue_type="subject_verb_agreement",
        target_knowledge_node_id="subject_verb_agreement",
        mastery=0.25 if repeated else 0.9,
        mastery_confidence=0.8,
        historical_error_count=3 if repeated else 1,
        recent_error_recurrence=repeated,
        mode=mode,
        intent=StudentIntent(primary=IntentLabel.REQUEST_HELP),
        consecutive_failures=2 if repeated else 0,
        average_hint_level=0,
        confusion_score=0,
    )


def grammar_issue() -> GrammarError:
    return GrammarError(
        start_offset=4,
        end_offset=6,
        original_expression="go",
        corrected_expression="goes",
        original_sentence="She go to school.",
        corrected_sentence="She goes to school.",
        primary_category="subject_verb_agreement",
        knowledge_node_id="subject_verb_agreement",
        subtype="subject_verb_agreement",
        original_structure="subject_predicate",
        corrected_structure="subject_predicate",
        structure_change="verb agreement",
        reason="The verb must agree with the subject.",
        confidence=0.93,
        severity="moderate",
    )


def request(*, mode: TeachingMode = TeachingMode.GUIDED, repeated: bool = False) -> TeachingRequest:
    ctx = policy_context(mode=mode, repeated=repeated)
    decision = PedagogyPolicy().decide(ctx)
    return TeachingRequest(
        session_id=uuid4(),
        student_id=uuid4(),
        plan=PlannerPlan(
            stage=ctx.stage,
            next_stage=ctx.stage,
            mode=mode,
            target_knowledge_node_id=ctx.target_knowledge_node_id,
            target_ability_dimension=AbilityDimension.GRAMMAR,
            scaffold_adjustment="hold",
            rationale="Grammar target from prior evidence",
        ),
        decision=decision,
        policy_context=ctx,
        draft_text="She go to school.",
        issue=grammar_issue(),
    )


def tools_with_state(state: StudentStateSnapshot) -> AgentToolRuntime:
    tools = AgentToolRuntime()
    tools.register(
        "read_state",
        ToolSpec(frozenset({"planner", "teaching"}), ReadStateArgs, lambda _args: state),
    )
    return tools


def test_tool_permission_validation_retry_fallback_and_trace() -> None:
    state = snapshot()
    tools = tools_with_state(state)
    session_id = uuid4()

    async def run() -> None:
        with pytest.raises(DomainError, match="cannot call"):
            await tools.invoke(
                actor="evaluator", session_id=session_id, name="read_state", arguments={}
            )
        with pytest.raises(ValidationError):
            await tools.invoke(
                actor="planner", session_id=session_id, name="read_state", arguments={}
            )
        assert (
            await tools.invoke(
                actor="planner",
                session_id=session_id,
                name="read_state",
                arguments={"student_id": state.student.id},
            )
            == state
        )
        attempts = []

        def fail_once(_args: ReadStateArgs) -> StudentStateSnapshot:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("temporary")
            return state

        tools.register(
            "retry_read",
            ToolSpec(frozenset({"planner"}), ReadStateArgs, fail_once, retries=1),
        )
        await tools.invoke(
            actor="planner",
            session_id=session_id,
            name="retry_read",
            arguments={"student_id": state.student.id},
        )
        assert len(attempts) == 2
        tools.register(
            "degraded_read",
            ToolSpec(
                frozenset({"planner"}),
                ReadStateArgs,
                lambda _args: (_ for _ in ()).throw(RuntimeError("down")),
                fallback=lambda _args: state,
                retries=0,
            ),
        )
        await tools.invoke(
            actor="planner",
            session_id=session_id,
            name="degraded_read",
            arguments={"student_id": state.student.id},
        )
        tools.register(
            "failed_read",
            ToolSpec(
                frozenset({"planner"}),
                ReadStateArgs,
                lambda _args: (_ for _ in ()).throw(RuntimeError("down")),
                retries=0,
            ),
        )
        with pytest.raises(DomainError, match="failed"):
            await tools.invoke(
                actor="planner",
                session_id=session_id,
                name="failed_read",
                arguments={"student_id": state.student.id},
            )
        tools.register(
            "timeout_read",
            ToolSpec(
                frozenset({"planner"}),
                ReadStateArgs,
                lambda _args: (sleep(0.05), state)[1],
                timeout_seconds=0.001,
                retries=0,
            ),
        )
        with pytest.raises(DomainError, match="failed"):
            await tools.invoke(
                actor="planner",
                session_id=session_id,
                name="timeout_read",
                arguments={"student_id": state.student.id},
            )

    asyncio.run(run())
    assert [item.status for item in tools.trace] == [
        ToolCallStatus.FAILURE,
        ToolCallStatus.FAILURE,
        ToolCallStatus.SUCCESS,
        ToolCallStatus.SUCCESS,
        ToolCallStatus.DEGRADED,
        ToolCallStatus.FAILURE,
        ToolCallStatus.FAILURE,
    ]
    assert [item.error_code for item in tools.trace if item.status == ToolCallStatus.FAILURE] == [
        "tool_forbidden",
        "invalid_arguments",
        "RuntimeError",
        "TimeoutError",
    ]


def test_planner_structured_stage_mode_and_no_state_mutation() -> None:
    state = snapshot(mastery=0.2, ability_score=0.3)
    tools = tools_with_state(state)
    from app.agents.tool_runtime import LearningPathArgs, NodeArgs
    from app.domain.enums import NodeKind
    from app.services.knowledge_graph.schemas import KnowledgeNode, LearningPath, LearningPathStep

    tools.register(
        "prerequisites",
        ToolSpec(frozenset({"planner"}), NodeArgs, lambda _args: []),
    )
    node = KnowledgeNode(
        id="subject_verb_agreement",
        label="Subject-verb agreement",
        kind=NodeKind.CONCEPT,
        description="Agreement between subject and verb",
    )
    tools.register(
        "plan_learning_path",
        ToolSpec(
            frozenset({"planner"}),
            LearningPathArgs,
            lambda _args: LearningPath(
                goal_node_id=node.id,
                steps=[
                    LearningPathStep(
                        node=node,
                        prerequisite_node_ids=[],
                        status="ready",
                        reason="Needs practice",
                    )
                ],
                next_node_id=node.id,
                completed=False,
                mastery_threshold=0.8,
                confidence_threshold=0.5,
            ),
        ),
    )
    planner = PlannerAgent(tools)
    before = state.model_dump_json()
    plan = asyncio.run(
        planner.plan(
            student_id=state.student.id,
            session_id=uuid4(),
            stage=TeachingStage.GRAMMAR_REVISION,
            mode=TeachingMode.SEMI_GUIDED,
            stage_passed=False,
        )
    )
    assert plan.stage == plan.next_stage == TeachingStage.GRAMMAR_REVISION
    assert plan.mode == TeachingMode.GUIDED
    assert plan.target_knowledge_node_id == "subject_verb_agreement"
    assert plan.long_term_priority_node_id == "subject_verb_agreement"
    assert plan.scaffold_adjustment == "increase"
    assert state.model_dump_json() == before
    assert "text" not in PlannerPlan.model_fields
    assert "reply" not in PlannerPlan.model_fields
    assert PlannerPlan.model_validate_json(plan.model_dump_json()) == plan
    assert PlannerAgent._next_stage(TeachingStage.FIRST_DRAFT) == (TeachingStage.GRAMMAR_REVISION)
    assert PlannerAgent._next_stage(TeachingStage.FINAL_EVALUATION) is None
    content_plan = asyncio.run(
        planner.plan(
            student_id=state.student.id,
            session_id=uuid4(),
            stage=TeachingStage.CONTENT_EXPANSION,
            mode=TeachingMode.GUIDED,
            stage_passed=False,
        )
    )
    assert content_plan.target_knowledge_node_id is None
    assert content_plan.long_term_priority_node_id == "subject_verb_agreement"
    assert content_plan.target_ability_dimension == AbilityDimension.CONTENT
    independent = snapshot(mastery=0.9, ability_score=0.9, independent_revisions=3)
    assert PlannerAgent._mode(independent) == TeachingMode.INDEPENDENT


def test_teaching_agent_respects_plan_policy_and_uses_no_corrected_answer() -> None:
    req = request()
    provider = ScriptedProvider(
        {"text": "Check the verb in your sentence. What matches the subject?"}
    )
    tools = tools_with_state(snapshot())
    agent = TeachingAgent(provider, tools, PedagogyPolicy())
    turn = asyncio.run(agent.generate(req))
    assert turn.action == req.decision.action
    assert turn.stage == req.plan.stage and turn.mode == req.plan.mode
    assert turn.target_knowledge_node_id == req.plan.target_knowledge_node_id
    assert "goes" not in provider.calls[0][1]
    assert 'may_reveal_answer": false' in provider.calls[0][1]
    assert len(tools.trace) == 1 and tools.trace[0].tool_name == "read_state"
    assert TeachingTurn.model_validate_json(turn.model_dump_json()) == turn

    changed_mode = req.model_copy(
        update={"plan": req.plan.model_copy(update={"mode": TeachingMode.INDEPENDENT})}
    )
    with pytest.raises(DomainError, match="stage or mode"):
        asyncio.run(agent.generate(changed_mode))
    changed_decision = req.model_copy(
        update={"decision": req.decision.model_copy(update={"may_reveal_answer": True})}
    )
    with pytest.raises(DomainError, match="differs from policy"):
        asyncio.run(agent.generate(changed_decision))
    assert len(provider.calls) == 1


def test_independent_mode_has_no_reply_and_no_tool_or_model_call() -> None:
    req = request(mode=TeachingMode.INDEPENDENT)
    provider = ScriptedProvider()
    tools = tools_with_state(snapshot())
    turn = asyncio.run(TeachingAgent(provider, tools, PedagogyPolicy()).generate(req))
    assert turn.text is None
    assert turn.used_resource_ids == []
    assert provider.calls == [] and tools.trace == []
    result = asyncio.run(PedagogyEvaluator(provider, PedagogyPolicy()).evaluate(req, turn))
    assert result.verdict == EvaluationVerdict.PASS


def test_evaluator_blocks_answer_leak_mode_violation_and_policy_mismatch() -> None:
    req = request()
    base = TeachingTurn(
        session_id=req.session_id,
        stage=req.plan.stage,
        mode=req.plan.mode,
        action=req.decision.action,
        target_knowledge_node_id=req.decision.target_knowledge_node_id,
        text="Check the verb yourself.",
    )
    provider = ScriptedProvider()
    evaluator = PedagogyEvaluator(provider, PedagogyPolicy())
    leak = asyncio.run(
        evaluator.evaluate(req, base.model_copy(update={"text": "She goes to school."}))
    )
    assert leak.verdict == EvaluationVerdict.BLOCK
    assert "answer_exposed" in leak.violations
    too_strong = asyncio.run(
        evaluator.evaluate(req, base.model_copy(update={"text": "Change the verb now."}))
    )
    assert "scaffold_too_strong" in too_strong.violations
    premature_draft = asyncio.run(
        evaluator.evaluate(
            req,
            base.model_copy(update={"text": "Good work getting a full second draft down."}),
        )
    )
    assert "premature_second_draft" in premature_draft.violations
    stage = asyncio.run(
        evaluator.evaluate(req, base.model_copy(update={"stage": TeachingStage.CONTENT_EXPANSION}))
    )
    assert "turn_metadata_mismatch" in stage.violations
    changed_decision = req.model_copy(
        update={"decision": req.decision.model_copy(update={"action": PedagogyAction.CONCEPT_HINT})}
    )
    policy_block = asyncio.run(evaluator.evaluate(changed_decision, base))
    assert "policy_mismatch" in policy_block.violations
    independent_req = request(mode=TeachingMode.INDEPENDENT)
    independent_turn = base.model_copy(
        update={
            "session_id": independent_req.session_id,
            "mode": TeachingMode.INDEPENDENT,
            "action": PedagogyAction.INDEPENDENT_RETRY,
            "text": "Here is a grammar hint.",
        }
    )
    mode_block = asyncio.run(evaluator.evaluate(independent_req, independent_turn))
    assert "independent_mode_intervention" in mode_block.violations
    assert provider.calls == []


def test_evaluator_directive_and_ghostwriting_regeneration() -> None:
    req = request()
    turn = TeachingTurn(
        session_id=req.session_id,
        stage=req.plan.stage,
        mode=req.plan.mode,
        action=req.decision.action,
        target_knowledge_node_id=req.decision.target_knowledge_node_id,
        text="Check your sentence again.",
    )
    provider = ScriptedProvider(
        {
            "accurate_to_issue": True,
            "scaffold_too_strong": False,
            "scaffold_too_weak": True,
            "actionable_next_step": False,
            "stage_appropriate": True,
            "ghostwriting": False,
            "rationale": "Give a precise self-check step.",
        },
        {
            "accurate_to_issue": True,
            "scaffold_too_strong": False,
            "scaffold_too_weak": False,
            "actionable_next_step": True,
            "stage_appropriate": True,
            "ghostwriting": True,
            "rationale": "Draft written for the student.",
        },
    )
    evaluator = PedagogyEvaluator(provider, PedagogyPolicy())
    directive = asyncio.run(evaluator.evaluate(req, turn))
    assert directive.verdict == EvaluationVerdict.DIRECTIVE
    assert "scaffold_too_weak" in directive.violations
    assert "no_actionable_step" in directive.violations
    ghostwriting = asyncio.run(evaluator.evaluate(req, turn))
    assert ghostwriting.verdict == EvaluationVerdict.BLOCK
    assert "ghostwriting" in ghostwriting.violations
    assert "text" not in type(directive).model_fields


def test_invalid_agent_schema_and_unapproved_resource() -> None:
    with pytest.raises(ValidationError):
        TeachingText(text="")
    with pytest.raises(ValidationError):
        TeachingTurn.model_validate({"text": "hello"})
    req = request()
    provider = ScriptedProvider({"text": "Check the verb.", "used_resource_ids": [str(uuid4())]})
    with pytest.raises(DomainError, match="unavailable resource"):
        asyncio.run(
            TeachingAgent(provider, tools_with_state(snapshot()), PedagogyPolicy()).generate(req)
        )


def test_real_state_graph_and_retrieval_feed_agents() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        sessions = create_session_factory(engine)
        seed_canonical_graph(sessions)
        graph = GrammarKnowledgeGraph(sessions)
        retriever = HybridRetriever(ResourceStore(sessions), settings)
        retriever.load_index()
        manager = StudentStateManager(sessions, settings)
        student = Student(grade=9, learning_goal="Write about school")
        manager.initialize_student(student)
        task_id, session_id = uuid4(), uuid4()
        with sessions.begin() as db:
            db.add(WritingTaskRecord(id=task_id, prompt="School day", genre="narrative", grade=9))
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
                    knowledge_node_id="subject_verb_agreement",
                    outcome=EvidenceOutcome.FAILURE,
                    observed_at=datetime.now(UTC),
                )
            )
            manager.record_error(
                ErrorRecord(
                    student_id=student.id,
                    session_id=session_id,
                    category="subject_verb_agreement",
                    knowledge_node_id="subject_verb_agreement",
                    original_text="She go",
                    observed_at=datetime.now(UTC),
                )
            )
        state_before = manager.read_student_state(student.id)
        trace_store = ToolTraceStore(sessions)
        tools = build_agent_tools(manager, graph, retriever, recorder=trace_store.record)
        plan = asyncio.run(
            PlannerAgent(tools).plan(
                student_id=student.id,
                session_id=session_id,
                stage=TeachingStage.GRAMMAR_REVISION,
                mode=TeachingMode.GUIDED,
                stage_passed=False,
            )
        )
        assert plan.target_knowledge_node_id == "subject_verb_agreement"
        known_prerequisites = {item.id for item in graph.prerequisites("subject_verb_agreement")}
        assert plan.prerequisite_node_id == "subject_predicate"
        assert plan.prerequisite_node_id in known_prerequisites
        ctx = PolicyContext.from_student_state(
            state_before,
            stage=plan.stage,
            mode=plan.mode,
            issue_type="subject_verb_agreement",
            target_knowledge_node_id=plan.target_knowledge_node_id,
            intent=StudentIntent(primary=IntentLabel.REQUEST_HELP),
            recent_error_recurrence=True,
        )
        decision = PedagogyPolicy().decide(ctx)
        assert decision.action == PedagogyAction.KG_MICRO_LESSON
        teaching_request = TeachingRequest(
            session_id=session_id,
            student_id=student.id,
            plan=plan,
            decision=decision,
            policy_context=ctx,
            draft_text="She go to school.",
            issue=grammar_issue(),
        )
        provider = ScriptedProvider(
            {
                "text": (
                    "The subject and verb need to agree. Check the verb for 'She', "
                    "then revise your own sentence and try another example."
                )
            },
            {
                "accurate_to_issue": True,
                "scaffold_too_strong": False,
                "scaffold_too_weak": False,
                "actionable_next_step": True,
                "stage_appropriate": True,
                "ghostwriting": False,
                "rationale": "Aligned with the micro lesson decision.",
            },
        )
        turn = asyncio.run(
            TeachingAgent(provider, tools, PedagogyPolicy()).generate(teaching_request)
        )
        evaluation = asyncio.run(
            PedagogyEvaluator(provider, PedagogyPolicy()).evaluate(teaching_request, turn)
        )
        assert evaluation.verdict == EvaluationVerdict.PASS
        assert turn.action == PedagogyAction.KG_MICRO_LESSON
        assert any(item.tool_name == "find_teaching_material" for item in tools.trace)
        assert manager.read_student_state(student.id) == state_before
        materials = asyncio.run(
            tools.invoke(
                actor="teaching",
                session_id=session_id,
                name="find_teaching_material",
                arguments={"text": "simple past yesterday", "knowledge_node_id": "simple_past"},
            )
        )
        assert materials
        assert any(item.resource.knowledge_node_ids == ["simple_past"] for item in materials)
        past_context = ctx.model_copy(
            update={
                "target_knowledge_node_id": "simple_past",
                "issue_type": "simple past yesterday",
            }
        )
        past_decision = PedagogyPolicy().decide(past_context)
        past_request = TeachingRequest(
            session_id=session_id,
            student_id=student.id,
            plan=plan.model_copy(update={"target_knowledge_node_id": "simple_past"}),
            decision=past_decision,
            policy_context=past_context,
            draft_text="Yesterday, I go to school.",
        )
        resource_id = materials[0].resource.id
        material_provider = ScriptedProvider(
            {
                "text": "Look at the past-time pattern in the example, then revise your sentence.",
                "used_resource_ids": [str(resource_id)],
            }
        )
        material_turn = asyncio.run(
            TeachingAgent(material_provider, tools, PedagogyPolicy()).generate(past_request)
        )
        assert material_turn.used_resource_ids == [resource_id]
        assert str(resource_id) in material_provider.calls[0][1]
        transfer = asyncio.run(
            PlannerAgent(tools).plan(
                student_id=student.id,
                session_id=session_id,
                stage=TeachingStage.FINAL_EVALUATION,
                mode=TeachingMode.GUIDED,
                stage_passed=True,
            )
        )
        assert transfer.next_stage is None
        assert transfer.next_transfer_task_id is not None
        persisted_trace = trace_store.for_session(session_id)
        assert [item.id for item in persisted_trace] == [item.id for item in tools.trace]
        assert all(item.status == ToolCallStatus.SUCCESS for item in persisted_trace)
    finally:
        engine.dispose()


def test_openai_adapter_contract_without_external_request() -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.parsed: object = TeachingText(text="Check the subject and verb.")
            self.arguments: dict[str, object] = {}

        async def parse(self, **kwargs: object) -> SimpleNamespace:
            self.arguments = kwargs
            return SimpleNamespace(output_parsed=self.parsed)

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    with pytest.raises(DomainError, match="not configured"):
        ResponsesModelProvider(api_key=None, model="test-model")
    client = FakeClient()
    adapter = ResponsesModelProvider(
        api_key=SecretStr("test-only"), model="test-model", client=client
    )
    result = asyncio.run(
        adapter.generate_structured(
            system_prompt="system", user_prompt="user", response_type=TeachingText
        )
    )
    assert result.text == "Check the subject and verb."
    assert client.responses.arguments["model"] == "test-model"
    assert client.responses.arguments["text_format"] is TeachingText
    assert client.responses.arguments["store"] is False
    assert client.responses.arguments["input"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    client.responses.parsed = None
    with pytest.raises(DomainError, match="no structured output"):
        asyncio.run(
            adapter.generate_structured(
                system_prompt="system", user_prompt="user", response_type=TeachingText
            )
        )
    client.responses.parsed = "invalid"
    with pytest.raises(DomainError, match="did not match schema"):
        asyncio.run(
            adapter.generate_structured(
                system_prompt="system", user_prompt="user", response_type=TeachingText
            )
        )
    asyncio.run(adapter.aclose())
    assert client.closed is True


def test_deepseek_is_selected_without_exposing_key() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://localhost/test",
        model_provider="deepseek",
        deepseek_api_key=SecretStr("test-only-secret"),
    )
    provider = configured_responses_provider(settings)
    assert provider is not None
    assert provider.model == "deepseek-flash"
    assert str(provider.client.base_url).rstrip("/") == "https://api.deepseek.com"
    assert "test-only-secret" not in repr(settings)
    asyncio.run(provider.aclose())
    without_key = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://localhost/test",
        model_provider="deepseek",
    )
    assert configured_responses_provider(without_key) is None


def test_deepseek_responses_wire_format_with_local_http_transport() -> None:
    sent: dict[str, object] = {}

    def handler(request: Request) -> Response:
        sent["url"] = str(request.url)
        sent["body"] = json.loads(request.content)
        return Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "model": "deepseek-flash",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"text":"Check your verb.","used_resource_ids":[]}',
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    async def run() -> TeachingText:
        http_client = AsyncClient(transport=MockTransport(handler))
        client = AsyncOpenAI(
            api_key="test-only",
            base_url="https://api.deepseek.com",
            http_client=http_client,
        )
        provider = ResponsesModelProvider(
            api_key=SecretStr("test-only"), model="deepseek-flash", client=client
        )
        try:
            return await provider.generate_structured(
                system_prompt="Return structured JSON.",
                user_prompt="Help with grammar.",
                response_type=TeachingText,
            )
        finally:
            await provider.aclose()

    output = asyncio.run(run())
    assert output.text == "Check your verb."
    assert sent["url"] == "https://api.deepseek.com/responses"
    body = sent["body"]
    assert isinstance(body, dict)
    assert body["model"] == "deepseek-flash"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["store"] is False
