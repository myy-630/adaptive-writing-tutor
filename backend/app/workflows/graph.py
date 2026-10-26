from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from app.agents.evaluator import PedagogyEvaluator
from app.agents.planner import PlannerAgent
from app.agents.schemas import PlannerPlan, TeachingRequest, TeachingTurn
from app.agents.teaching import TeachingAgent
from app.core.config import Settings
from app.domain.enums import EvaluationVerdict, TeachingMode, TeachingStage
from app.domain.schemas import EvaluationResult, TeachingDecision
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.grammar.schemas import GrammarAnalysis, GrammarError
from app.services.grammar.transfer import exercise_for
from app.services.pedagogy.intent import recognize_student_intent
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.pedagogy.schemas import PolicyContext
from app.services.student_state.manager import StudentStateManager
from app.workflows.draft_comparison import DraftComparison
from app.workflows.schemas import SharedState, WorkflowResult, WorkflowSubmission
from app.workflows.store import WorkflowStore


class WritingWorkflow:
    """LangGraph orchestration; stage gates and persistent writes live in services."""

    def __init__(
        self,
        *,
        store: WorkflowStore,
        manager: StudentStateManager,
        planner: PlannerAgent,
        analyzer: GrammarAnalyzer,
        policy: PedagogyPolicy,
        teacher: TeachingAgent,
        evaluator: PedagogyEvaluator,
        checkpointer: AsyncPostgresSaver,
        max_regenerations: int = 2,
    ) -> None:
        if max_regenerations < 0:
            raise ValueError("max_regenerations cannot be negative")
        self.store = store
        self.manager = manager
        self.planner = planner
        self.analyzer = analyzer
        self.policy = policy
        self.teacher = teacher
        self.evaluator = evaluator
        self.max_regenerations = max_regenerations
        builder = StateGraph(SharedState)
        builder.add_node("load", self._load)
        builder.add_node("apply_response", self._apply_response)
        builder.add_node("planner", self._plan)
        builder.add_node("diagnose", self._diagnose)
        builder.add_node("policy", self._policy)
        builder.add_node("teaching", self._teach)
        builder.add_node("evaluate", self._evaluate)
        builder.add_node("retry", self._retry)
        builder.add_node("finish", self._finish)
        builder.add_edge(START, "load")
        builder.add_edge("load", "apply_response")
        builder.add_conditional_edges("apply_response", self._after_response)
        builder.add_edge("planner", "diagnose")
        builder.add_edge("diagnose", "policy")
        builder.add_edge("policy", "teaching")
        builder.add_edge("teaching", "evaluate")
        builder.add_conditional_edges("evaluate", self._after_evaluation)
        builder.add_edge("retry", "teaching")
        builder.add_edge("finish", END)
        self.graph = builder.compile(checkpointer=checkpointer)

    @staticmethod
    @asynccontextmanager
    async def postgres_checkpointer(settings: Settings) -> AsyncIterator[AsyncPostgresSaver]:
        dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            await saver.setup()
            yield saver

    async def run(
        self, *, session_id: UUID, student_id: UUID, submission: WorkflowSubmission
    ) -> WorkflowResult:
        with self.store.run_lock(submission.request_id):
            cached = self.store.register(session_id, student_id, submission)
            if cached is not None:
                return cached
            config: RunnableConfig = {
                "configurable": {"thread_id": str(submission.request_id)},
                "recursion_limit": 50,
            }
            checkpoint = await self.graph.aget_state(config)
            initial: SharedState | None = None
            if not checkpoint.values:
                initial = {
                    "request_id": str(submission.request_id),
                    "session_id": str(session_id),
                    "student_id": str(student_id),
                    "submission": submission.model_dump(mode="json"),
                    "retry_count": 0,
                }
            result_state = await self.graph.ainvoke(initial, config=config, durability="sync")
            return WorkflowResult.model_validate(result_state["result"])

    async def _load(self, state: SharedState) -> SharedState:
        return self.store.context(UUID(state["request_id"]))  # type: ignore[return-value]

    async def _apply_response(self, state: SharedState) -> SharedState:
        outcome = self.store.apply(UUID(state["request_id"]))
        context = self.store.context(UUID(state["request_id"]))
        return {
            "stage": str(context["stage"]),
            "mode": str(context["mode"]),
            "current_draft": str(context["current_draft"]),
            "first_draft": str(context["first_draft"]),
            "stage_passed": outcome.passed,
            "completed": outcome.completed,
            "feedback": outcome.feedback,
            "final_comparison": outcome.comparison.model_dump(mode="json")
            if outcome.comparison
            else {},
        }  # type: ignore[return-value]

    @staticmethod
    def _after_response(state: SharedState) -> Literal["finish", "planner"]:
        return (
            "finish"
            if state["completed"] or state["stage"] == TeachingStage.FINAL_EVALUATION.value
            else "planner"
        )

    async def _plan(self, state: SharedState) -> SharedState:
        plan = await self.planner.plan(
            student_id=UUID(state["student_id"]),
            session_id=UUID(state["session_id"]),
            stage=TeachingStage(state["stage"]),
            mode=TeachingMode(state["mode"]),
            stage_passed=False,
        )
        return {"plan": plan.model_dump(mode="json"), "mode": plan.mode.value}

    async def _diagnose(self, state: SharedState) -> SharedState:
        text = state.get("current_draft") or ""
        analysis = self.analyzer.analyze(text)
        plan = await self.planner.incorporate_diagnosis(
            PlannerPlan.model_validate(state["plan"]),
            analysis,
            student_id=UUID(state["student_id"]),
            session_id=UUID(state["session_id"]),
        )
        return {
            "diagnosis": analysis.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
        }

    async def _policy(self, state: SharedState) -> SharedState:
        plan = PlannerPlan.model_validate(state["plan"])
        analysis = GrammarAnalysis.model_validate(state["diagnosis"])
        issue = self._target_issue(analysis, plan)
        snapshot = self.manager.read_student_state(UUID(state["student_id"]))
        submission = WorkflowSubmission.model_validate(state["submission"])
        context = PolicyContext.from_student_state(
            snapshot,
            stage=plan.stage,
            mode=plan.mode,
            issue_type=issue.primary_category if issue else plan.stage.value,
            target_knowledge_node_id=plan.target_knowledge_node_id,
            intent=recognize_student_intent(submission.message),
            recent_error_recurrence=bool(
                issue
                and any(
                    item.knowledge_node_id == issue.knowledge_node_id and item.count >= 2
                    for item in snapshot.error_patterns
                )
            ),
        )
        decision = self.policy.decide(context)
        return {
            "policy_context": context.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
        }

    async def _teach(self, state: SharedState) -> SharedState:
        request = self._teaching_request(state)
        turn = await self.teacher.generate(request)
        return {"teaching_turn": turn.model_dump(mode="json")}

    async def _evaluate(self, state: SharedState) -> SharedState:
        request = self._teaching_request(state)
        turn = TeachingTurn.model_validate(state["teaching_turn"])
        evaluation = await self.evaluator.evaluate(request, turn)
        return {"evaluation": evaluation.model_dump(mode="json")}

    def _after_evaluation(self, state: SharedState) -> Literal["retry", "finish"]:
        evaluation = EvaluationResult.model_validate(state["evaluation"])
        if evaluation.verdict == EvaluationVerdict.PASS:
            return "finish"
        return "retry" if state.get("retry_count", 0) < self.max_regenerations else "finish"

    async def _retry(self, state: SharedState) -> SharedState:
        return {"retry_count": state.get("retry_count", 0) + 1}

    async def _finish(self, state: SharedState) -> SharedState:
        evaluation = (
            EvaluationResult.model_validate(state["evaluation"]) if "evaluation" in state else None
        )
        passed = evaluation is None or evaluation.verdict == EvaluationVerdict.PASS
        turn = (
            TeachingTurn.model_validate(state["teaching_turn"])
            if passed and "teaching_turn" in state
            else None
        )
        result = WorkflowResult(
            request_id=UUID(state["request_id"]),
            session_id=UUID(state["session_id"]),
            stage=TeachingStage(state["stage"]),
            mode=TeachingMode(state["mode"]),
            stage_passed=state.get("stage_passed", False),
            completed=state.get("completed", False),
            feedback=state.get("feedback", ""),
            teaching_text=turn.text if turn else None,
            evaluation_verdict=evaluation.verdict if evaluation else None,
            transfer_prompt=self._transfer_prompt(state) if passed else None,
            final_comparison=(
                DraftComparison.model_validate(state["final_comparison"])
                if state.get("final_comparison")
                else None
            ),
            action=(
                TeachingDecision.model_validate(state["decision"]).action
                if "decision" in state
                else None
            ),
            target_knowledge_node_id=(
                TeachingDecision.model_validate(state["decision"]).target_knowledge_node_id
                if "decision" in state
                else None
            ),
            retries=state.get("retry_count", 0),
            blocked=not passed,
        )
        policy_decision = state.get("decision")
        stored = self.store.complete(UUID(state["request_id"]), result, policy_decision)
        return {"result": stored.model_dump(mode="json"), "blocked": stored.blocked}

    def _teaching_request(self, state: SharedState) -> TeachingRequest:
        plan = PlannerPlan.model_validate(state["plan"])
        analysis = GrammarAnalysis.model_validate(state["diagnosis"])
        evaluation = (
            EvaluationResult.model_validate(state["evaluation"])
            if state.get("retry_count", 0) and "evaluation" in state
            else None
        )
        return TeachingRequest(
            session_id=UUID(state["session_id"]),
            student_id=UUID(state["student_id"]),
            plan=plan,
            decision=TeachingDecision.model_validate(state["decision"]),
            policy_context=PolicyContext.model_validate(state["policy_context"]),
            draft_text=state.get("current_draft") or state["task_prompt"],
            issue=self._target_issue(analysis, plan),
            revision_directive=evaluation.directive if evaluation else None,
            transfer_prompt=self._transfer_prompt(state),
        )

    @staticmethod
    def _transfer_prompt(state: SharedState) -> str | None:
        if "decision" not in state:
            return None
        decision = TeachingDecision.model_validate(state["decision"])
        exercise = (
            exercise_for(decision.target_knowledge_node_id) if decision.needs_practice else None
        )
        return exercise.prompt if exercise else None

    @staticmethod
    def _target_issue(analysis: GrammarAnalysis, plan: PlannerPlan) -> GrammarError | None:
        return next(
            (
                issue
                for issue in analysis.errors
                if issue.knowledge_node_id == plan.target_knowledge_node_id
            ),
            None,
        )
