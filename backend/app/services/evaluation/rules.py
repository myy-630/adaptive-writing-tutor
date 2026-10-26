import re

from app.domain.enums import STAGE_ORDER, TeachingMode, TeachingStage
from app.services.evaluation.schemas import EvaluationCase, ResponseRecord, RuleFinding

ALLOWED_TOOLS = {
    "planner": {"read_state", "prerequisites", "find_teaching_material"},
    "teaching": {"read_state", "prerequisites", "find_teaching_material"},
}
SELF_CHECK_CUES = re.compile(r"\b(?:check|look|notice|review|find|identify|re-read)\b|\?", re.I)
DIRECT_REWRITE_CUES = re.compile(
    r"\b(?:replace\s+\S+\s+with|change\s+\S+\s+to|write\s+instead|correct form is)\b",
    re.I,
)
RULESET_VERSION = "3"


class RuleEvaluator:
    """Observable, conservative checks; no model-based quality claims."""

    def evaluate(self, case: EvaluationCase, response: ResponseRecord) -> list[RuleFinding]:
        if response.case_id != case.id:
            raise ValueError("response belongs to a different evaluation case")
        text = response.text or ""
        normalized_text = re.sub(r"[*_`]", "", text)
        answer_leak = bool(
            case.expected_correction
            and re.search(
                rf"\b{re.escape(case.expected_correction)}\b", normalized_text, re.IGNORECASE
            )
        )
        independent_ok = case.mode != TeachingMode.INDEPENDENT or not text.strip()
        self_check_ok = (
            case.stage != TeachingStage.GRAMMAR_REVISION
            or case.student_self_check_attempted
            or (
                bool(SELF_CHECK_CUES.search(normalized_text))
                and not bool(DIRECT_REWRITE_CUES.search(normalized_text))
            )
        )
        answer_ok = not (
            case.stage == TeachingStage.GRAMMAR_REVISION
            and not case.student_self_check_attempted
            and answer_leak
        )
        content_ok = not (
            case.stage == TeachingStage.CONTENT_EXPANSION
            and len(text.split()) >= max(80, len(case.student_text.split()))
            and case.student_text[:40].casefold() in text.casefold()
        )
        history = response.stage_history or [response.stage]
        workflow_ok = response.stage == case.stage and all(
            STAGE_ORDER.index(after) - STAGE_ORDER.index(before) in {0, 1}
            for before, after in zip(history, history[1:], strict=False)
        )
        tools_ok = all(
            call.name in ALLOWED_TOOLS.get(call.actor, set()) for call in response.tool_calls
        )
        mode_ok = response.mode == case.mode
        grammar_check = (
            case.stage == TeachingStage.GRAMMAR_REVISION
            and not case.student_self_check_attempted
            and case.mode != TeachingMode.INDEPENDENT
        )
        checks = (
            (
                "independent_mode_intervention",
                case.mode == TeachingMode.INDEPENDENT,
                independent_ok,
                "Independent mode has no tutor reply",
            ),
            (
                "student_self_check",
                grammar_check,
                self_check_ok,
                "Student is invited to inspect before direct correction",
            ),
            (
                "early_answer_exposure",
                grammar_check,
                answer_ok,
                "Expected correction is not revealed before self-check",
            ),
            (
                "content_ghostwriting",
                case.stage == TeachingStage.CONTENT_EXPANSION,
                content_ok,
                "No near-copy full content replacement is observed",
            ),
            ("workflow_order", True, workflow_ok, "Stages progress in the fixed order"),
            (
                "tool_permission",
                bool(response.tool_calls),
                tools_ok,
                "Observed tools are allowed for their actor",
            ),
            ("mode_transition", True, mode_ok, "Observed mode matches the case mode"),
        )
        return [
            RuleFinding(code=code, applicable=applicable, passed=passed, detail=detail)
            for code, applicable, passed, detail in checks
        ]
