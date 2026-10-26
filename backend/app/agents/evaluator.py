import json
import re
from datetime import UTC, datetime

from app.agents.prompts import EVALUATOR_SYSTEM
from app.agents.schemas import EvaluatorJudgement, TeachingRequest, TeachingTurn
from app.core.provider import ModelProvider
from app.domain.enums import EvaluationVerdict, PedagogyAction, TeachingMode, TeachingStage
from app.domain.schemas import EvaluationResult
from app.services.pedagogy.policy import PedagogyPolicy


class PedagogyEvaluator:
    """Independent checker; never writes the reply shown to the student."""

    def __init__(self, provider: ModelProvider, policy: PedagogyPolicy) -> None:
        self.provider = provider
        self.policy = policy

    async def evaluate(self, request: TeachingRequest, turn: TeachingTurn) -> EvaluationResult:
        hard_violations = self._hard_violations(request, turn)
        if hard_violations:
            return self._result(
                request,
                EvaluationVerdict.BLOCK,
                hard_violations,
                "Regenerate under policy constraints.",
            )
        if request.plan.mode == TeachingMode.INDEPENDENT:
            return self._result(request, EvaluationVerdict.PASS, [], None)
        if turn.text is None:
            return self._result(
                request,
                EvaluationVerdict.DIRECTIVE,
                ["missing_teaching_reply"],
                "Provide a reply aligned with the teaching decision.",
            )
        prompt = {
            "stage": request.plan.stage.value,
            "mode": request.plan.mode.value,
            "action": request.decision.action.value,
            "scaffold_level": request.decision.scaffold_level,
            "may_reveal_answer": request.decision.may_reveal_answer,
            "issue": request.issue.model_dump(mode="json") if request.issue else None,
            "draft_text": request.draft_text,
            "teaching_reply": turn.text,
            "pass_condition": request.decision.pass_condition,
        }
        judgement = await self.provider.generate_structured(
            system_prompt=EVALUATOR_SYSTEM,
            user_prompt=json.dumps(prompt, ensure_ascii=False),
            response_type=EvaluatorJudgement,
        )
        if judgement.ghostwriting:
            return self._result(
                request,
                EvaluationVerdict.BLOCK,
                ["ghostwriting"],
                "Regenerate without writing the essay.",
            )
        violations = [
            name
            for name, passed in (
                ("wrong_issue", judgement.accurate_to_issue),
                ("no_actionable_step", judgement.actionable_next_step),
                ("stage_mismatch", judgement.stage_appropriate),
            )
            if not passed
        ]
        if judgement.scaffold_too_strong:
            violations.append("scaffold_too_strong")
        if judgement.scaffold_too_weak:
            violations.append("scaffold_too_weak")
        if violations:
            return self._result(
                request,
                EvaluationVerdict.DIRECTIVE,
                violations,
                judgement.rationale,
            )
        return self._result(request, EvaluationVerdict.PASS, [], None)

    def _hard_violations(self, request: TeachingRequest, turn: TeachingTurn) -> list[str]:
        violations: list[str] = []
        if request.decision != self.policy.decide(request.policy_context):
            violations.append("policy_mismatch")
        if (
            turn.session_id != request.session_id
            or turn.stage != request.plan.stage
            or turn.mode != request.plan.mode
            or turn.action != request.decision.action
            or turn.target_knowledge_node_id != request.decision.target_knowledge_node_id
        ):
            violations.append("turn_metadata_mismatch")
        if request.plan.mode == TeachingMode.INDEPENDENT and turn.text is not None:
            violations.append("independent_mode_intervention")
        if request.issue and turn.text and not request.decision.may_reveal_answer:
            corrected = request.issue.corrected_expression.strip()
            if request.issue.corrected_sentence.casefold() in turn.text.casefold() or (
                corrected and re.search(rf"\b{re.escape(corrected)}\b", turn.text, re.IGNORECASE)
            ):
                violations.append("answer_exposed")
        if (
            turn.text
            and request.decision.action == PedagogyAction.SELF_CHECK
            and re.search(r"\b(?:change|replace|correct form is)\b", turn.text, re.IGNORECASE)
        ):
            violations.append("scaffold_too_strong")
        if (
            turn.text
            and request.plan.stage
            not in {TeachingStage.SECOND_DRAFT, TeachingStage.FINAL_EVALUATION}
            and re.search(
                r"\b(?:have|has|had|got|getting|finished|completed|written|submitted)\b"
                r".{0,35}\b(?:second draft|draft 2)\b"
                r"|(?:已|已经|完成|提交了).{0,8}(?:第二稿|二次重写)",
                turn.text,
                re.IGNORECASE | re.DOTALL,
            )
        ):
            violations.append("premature_second_draft")
        return violations

    @staticmethod
    def _result(
        request: TeachingRequest,
        verdict: EvaluationVerdict,
        violations: list[str],
        directive: str | None,
    ) -> EvaluationResult:
        return EvaluationResult(
            session_id=request.session_id,
            verdict=verdict,
            violations=violations,
            directive=directive,
            evaluated_at=datetime.now(UTC),
        )
