import json
from collections.abc import Awaitable, Callable

from app.agents.evaluator import PedagogyEvaluator
from app.agents.prompts import TEACHING_SYSTEM
from app.agents.schemas import PlannerPlan, TeachingRequest, TeachingText, TeachingTurn
from app.core.provider import ModelProvider, ResponseT
from app.domain.enums import STAGE_ORDER, EvaluationVerdict, TeachingMode
from app.services.evaluation.schemas import (
    VARIANTS,
    EvaluationCase,
    ResponseRecord,
    VariantName,
)
from app.services.pedagogy.policy import PedagogyPolicy
from app.services.pedagogy.schemas import IntentLabel, PolicyContext, StudentIntent
from app.services.student_state.schemas import StudentStateSnapshot

FullSystemRun = Callable[[EvaluationCase], Awaitable[ResponseRecord]]

ORDINARY_SYSTEM = "You are an English writing tutor. Respond to the student's writing."
FIXED_SYSTEM = """You are an English writing tutor. Guide the student's next step.
Ask the student to inspect their own writing before giving a correction. Do not write
the student's essay. Keep the response focused on the current writing stage."""


class CountingProvider:
    def __init__(self, delegate: ModelProvider) -> None:
        self.delegate = delegate
        self.calls = 0

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type[ResponseT]
    ) -> ResponseT:
        self.calls += 1
        return await self.delegate.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_type=response_type,
        )


class AblationRunner:
    """Runs explicit baseline components; the full variant delegates to the real workflow."""

    def __init__(
        self,
        provider: ModelProvider,
        provider_model: str,
        *,
        policy: PedagogyPolicy | None = None,
        full_system_run: FullSystemRun | None = None,
        max_regenerations: int = 1,
    ) -> None:
        if max_regenerations < 0:
            raise ValueError("max_regenerations must be nonnegative")
        self.provider = provider
        self.provider_model = provider_model
        self.policy = policy or PedagogyPolicy()
        self.full_system_run = full_system_run
        self.max_regenerations = max_regenerations

    async def run(
        self,
        case: EvaluationCase,
        variant: VariantName,
        *,
        student_state: StudentStateSnapshot | None = None,
    ) -> ResponseRecord:
        config = VARIANTS[variant]
        if config.full_workflow:
            if self.full_system_run is None:
                raise ValueError("full system workflow runner is required")
            result = await self.full_system_run(case)
            if result.variant != variant or result.case_id != case.id:
                raise ValueError("full workflow result identity mismatch")
            return result
        if config.student_state and student_state is None:
            raise ValueError(f"{variant.value} requires real Student State")
        context = None
        decision = None
        if config.pedagogy_policy:
            if student_state is None:
                raise ValueError("policy variant requires Student State")
            context = PolicyContext.from_student_state(
                student_state,
                stage=case.stage,
                mode=case.mode,
                issue_type=case.issue_category or "writing",
                target_knowledge_node_id=case.target_knowledge_node_id,
                intent=StudentIntent(primary=IntentLabel.ATTEMPT),
            )
            decision = self.policy.decide(context)
            if case.mode == TeachingMode.INDEPENDENT:
                return ResponseRecord(
                    case_id=case.id,
                    variant=variant,
                    text=None,
                    stage=case.stage,
                    mode=case.mode,
                    action=decision.action,
                    stage_history=[case.stage],
                    evaluator_verdict="pass" if config.pedagogy_evaluator else None,
                    model_calls=0,
                    provider_model=self.provider_model,
                )
        payload: dict[str, object] = {
            "task_prompt": case.task_prompt,
            "stage": case.stage.value,
            "mode": case.mode.value,
            "student_text": case.student_text,
            "issue_category": case.issue_category,
            "issue_location": case.issue_location,
        }
        if config.student_state and student_state is not None:
            payload["student_state"] = {
                "grade": student_state.student.grade,
                "goal": student_state.student.learning_goal,
                "knowledge": [
                    {"node_id": item.node_id, "mastery": item.mastery}
                    for item in student_state.knowledge
                ],
            }
        if decision is not None:
            payload["policy_decision"] = {
                "action": decision.action.value,
                "scaffold_level": decision.scaffold_level,
                "may_reveal_answer": decision.may_reveal_answer,
                "pass_condition": decision.pass_condition,
            }
        if decision is not None:
            system_prompt = TEACHING_SYSTEM
        elif config.fixed_prompt:
            system_prompt = FIXED_SYSTEM
        else:
            system_prompt = ORDINARY_SYSTEM
        meter = CountingProvider(self.provider)
        evaluator = PedagogyEvaluator(meter, self.policy) if config.pedagogy_evaluator else None
        request = self._teaching_request(case, context) if evaluator and context else None
        directive = None
        verdict = None
        text = None
        for attempt in range(self.max_regenerations + 1):
            if directive is not None:
                payload["revision_directive"] = directive
            generated = await meter.generate_structured(
                system_prompt=system_prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                response_type=TeachingText,
            )
            text = generated.text
            if evaluator is None or request is None or decision is None:
                break
            evaluation = await evaluator.evaluate(
                request,
                TeachingTurn(
                    session_id=case.session_id,
                    stage=case.stage,
                    mode=case.mode,
                    action=decision.action,
                    target_knowledge_node_id=decision.target_knowledge_node_id,
                    text=text,
                ),
            )
            verdict = evaluation.verdict.value
            if evaluation.verdict == EvaluationVerdict.PASS:
                break
            directive = evaluation.directive
            if attempt == self.max_regenerations:
                text = None
        return ResponseRecord(
            case_id=case.id,
            variant=variant,
            text=text,
            stage=case.stage,
            mode=case.mode,
            action=decision.action if decision else None,
            stage_history=[case.stage],
            evaluator_verdict=verdict,
            model_calls=meter.calls,
            provider_model=self.provider_model,
        )

    def _teaching_request(
        self, case: EvaluationCase, context: PolicyContext | None
    ) -> TeachingRequest:
        if context is None or case.student_id is None:
            raise ValueError("evaluator variant requires a student ID and policy context")
        decision = self.policy.decide(context)
        position = STAGE_ORDER.index(case.stage)
        next_stage = STAGE_ORDER[position + 1] if position + 1 < len(STAGE_ORDER) else None
        return TeachingRequest(
            session_id=case.session_id,
            student_id=case.student_id,
            plan=PlannerPlan(
                stage=case.stage,
                next_stage=next_stage,
                mode=case.mode,
                target_knowledge_node_id=case.target_knowledge_node_id,
                scaffold_adjustment="hold",
                rationale="Offline ablation retains the supplied stage and target.",
            ),
            decision=decision,
            policy_context=context,
            draft_text=case.student_text,
        )
