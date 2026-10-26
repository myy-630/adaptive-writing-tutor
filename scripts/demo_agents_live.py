"""Run a live Teaching Agent/Evaluator sample after configuring DEEPSEEK_API_KEY."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.agents.evaluator import PedagogyEvaluator
from app.agents.planner import PlannerAgent
from app.agents.schemas import TeachingRequest
from app.agents.teaching import TeachingAgent
from app.agents.tool_runtime import build_agent_tools
from app.agents.tracing import ToolTraceStore
from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.core.responses_provider import configured_responses_provider
from app.db.session import create_database_engine, create_session_factory
from app.domain import ErrorRecord, LearningEvidence, Student, TeachingMode, TeachingStage
from app.domain.enums import EvidenceOutcome
from app.models import TeachingSessionRecord, WritingTaskRecord
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.pedagogy.schemas import IntentLabel, PolicyContext, StudentIntent
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.store import ResourceStore
from app.services.student_state.manager import StudentStateManager


async def main() -> None:
    settings = Settings()
    provider = configured_responses_provider(settings)
    if provider is None:
        raise ProviderUnavailable()
    engine = create_database_engine(settings)
    try:
        sessions = create_session_factory(engine)
        graph = GrammarKnowledgeGraph(sessions)
        retriever = HybridRetriever(ResourceStore(sessions), settings)
        retriever.load_index()
        manager = StudentStateManager(sessions, settings)
        student = Student(grade=9, learning_goal="Improve English writing")
        manager.initialize_student(student)
        task_id, session_id = uuid4(), uuid4()
        with sessions.begin() as db:
            db.add(
                WritingTaskRecord(id=task_id, prompt="My school day", genre="narrative", grade=9)
            )
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
        issue = GrammarAnalyzer(graph).analyze("She go to school.").errors[0]
        for _ in range(2):
            manager.record_error(
                ErrorRecord(
                    student_id=student.id,
                    session_id=session_id,
                    category=issue.primary_category,
                    knowledge_node_id=issue.knowledge_node_id,
                    original_text=issue.original_expression,
                    observed_at=datetime.now(UTC),
                )
            )
            manager.record_evidence(
                LearningEvidence(
                    student_id=student.id,
                    session_id=session_id,
                    knowledge_node_id=issue.knowledge_node_id,
                    outcome=EvidenceOutcome.FAILURE,
                    observed_at=datetime.now(UTC),
                )
            )
        trace_store = ToolTraceStore(sessions)
        tools = build_agent_tools(manager, graph, retriever, recorder=trace_store.record)
        plan = await PlannerAgent(tools).plan(
            student_id=student.id,
            session_id=session_id,
            stage=TeachingStage.GRAMMAR_REVISION,
            mode=TeachingMode.GUIDED,
            stage_passed=False,
        )
        state = manager.read_student_state(student.id)
        policy_input = PolicyContext.from_student_state(
            state,
            stage=plan.stage,
            mode=plan.mode,
            issue_type=issue.primary_category,
            target_knowledge_node_id=issue.knowledge_node_id,
            intent=StudentIntent(primary=IntentLabel.REQUEST_HELP),
            recent_error_recurrence=True,
        )
        policy = PedagogyPolicy()
        decision = policy.decide(policy_input)
        request = TeachingRequest(
            session_id=session_id,
            student_id=student.id,
            plan=plan,
            decision=decision,
            policy_context=policy_input,
            draft_text="She go to school.",
            issue=issue,
        )
        turn = await TeachingAgent(provider, tools, policy).generate(request)
        evaluation = await PedagogyEvaluator(provider, policy).evaluate(request, turn)
        print(
            {
                "plan": plan.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "teaching_turn": turn.model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json"),
                "persisted_tool_calls": len(trace_store.for_session(session_id)),
                "student_state_unchanged": manager.read_student_state(student.id) == state,
            }
        )
    finally:
        await provider.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
