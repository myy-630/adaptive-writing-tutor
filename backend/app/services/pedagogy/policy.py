from app.domain.enums import PedagogyAction as Action
from app.domain.enums import TeachingMode, TeachingStage
from app.domain.schemas import ActionScore, TeachingDecision
from app.services.pedagogy.schemas import PolicyContext

SCAFFOLD_LEVEL = {
    Action.SELF_CHECK: 0,
    Action.INDEPENDENT_RETRY: 0,
    Action.LOCATION_HINT: 1,
    Action.SOCRATIC_QUESTION: 1,
    Action.TRANSFER_PRACTICE: 1,
    Action.CONCEPT_HINT: 2,
    Action.BREAK_DOWN: 2,
    Action.CONTRAST_EXAMPLE: 2,
    Action.KG_MICRO_LESSON: 3,
    Action.LOCAL_DEMONSTRATION: 3,
    Action.DIRECT_EXPLANATION: 4,
}

STAGE_ACTIONS = {
    TeachingStage.PROMPT_ANALYSIS: {
        Action.SELF_CHECK,
        Action.INDEPENDENT_RETRY,
        Action.LOCATION_HINT,
        Action.SOCRATIC_QUESTION,
        Action.BREAK_DOWN,
        Action.DIRECT_EXPLANATION,
    },
    TeachingStage.FIRST_DRAFT: {
        Action.INDEPENDENT_RETRY,
        Action.SOCRATIC_QUESTION,
        Action.BREAK_DOWN,
    },
    TeachingStage.GRAMMAR_REVISION: set(Action),
    TeachingStage.STRUCTURE_REVISION: {
        Action.SELF_CHECK,
        Action.INDEPENDENT_RETRY,
        Action.LOCATION_HINT,
        Action.SOCRATIC_QUESTION,
        Action.BREAK_DOWN,
        Action.CONTRAST_EXAMPLE,
        Action.LOCAL_DEMONSTRATION,
        Action.DIRECT_EXPLANATION,
        Action.TRANSFER_PRACTICE,
    },
    TeachingStage.CONTENT_EXPANSION: {
        Action.SELF_CHECK,
        Action.INDEPENDENT_RETRY,
        Action.SOCRATIC_QUESTION,
        Action.BREAK_DOWN,
        Action.CONTRAST_EXAMPLE,
        Action.TRANSFER_PRACTICE,
    },
    TeachingStage.LANGUAGE_REFINEMENT: {
        Action.SELF_CHECK,
        Action.INDEPENDENT_RETRY,
        Action.SOCRATIC_QUESTION,
        Action.CONCEPT_HINT,
        Action.CONTRAST_EXAMPLE,
        Action.LOCAL_DEMONSTRATION,
        Action.DIRECT_EXPLANATION,
        Action.TRANSFER_PRACTICE,
    },
    TeachingStage.SECOND_DRAFT: {Action.INDEPENDENT_RETRY},
    TeachingStage.FINAL_EVALUATION: {Action.SELF_CHECK, Action.INDEPENDENT_RETRY},
}

PASS_CONDITIONS = {
    Action.SELF_CHECK: "Student identifies and revises the issue independently.",
    Action.INDEPENDENT_RETRY: "Student submits an independent attempt.",
    Action.LOCATION_HINT: "Student locates the issue and revises it.",
    Action.CONCEPT_HINT: "Student applies the concept to revise the original text.",
    Action.SOCRATIC_QUESTION: "Student answers the question and revises independently.",
    Action.BREAK_DOWN: "Student completes each substep and revises independently.",
    Action.CONTRAST_EXAMPLE: "Student explains the contrast and applies it to own text.",
    Action.KG_MICRO_LESSON: "Student revises the original and succeeds on transfer practice.",
    Action.LOCAL_DEMONSTRATION: "Student applies the pattern to a different part of own text.",
    Action.DIRECT_EXPLANATION: "Student retries the original independently after explanation.",
    Action.TRANSFER_PRACTICE: "Student succeeds on a new transfer example independently.",
}

ESCALATION_ORDER = (
    Action.SELF_CHECK,
    Action.LOCATION_HINT,
    Action.SOCRATIC_QUESTION,
    Action.CONCEPT_HINT,
    Action.BREAK_DOWN,
    Action.CONTRAST_EXAMPLE,
    Action.KG_MICRO_LESSON,
    Action.LOCAL_DEMONSTRATION,
    Action.DIRECT_EXPLANATION,
)


class PedagogyPolicy:
    """Choose how to teach, without composing student-facing text or changing plans."""

    def decide(self, context: PolicyContext) -> TeachingDecision:
        candidates = self.allowed_actions(context)
        target_level = self._target_level(context)
        ranking = sorted(
            (self._score(action, context, target_level) for action in candidates),
            key=lambda item: (-item.score, item.action.value),
        )
        chosen = ranking[0].action
        return TeachingDecision(
            action=chosen,
            target_knowledge_node_id=context.target_knowledge_node_id,
            scaffold_level=SCAFFOLD_LEVEL[chosen],
            may_reveal_answer=chosen == Action.DIRECT_EXPLANATION,
            needs_practice=chosen in {Action.KG_MICRO_LESSON, Action.TRANSFER_PRACTICE},
            practice_type=(
                "transfer" if chosen in {Action.KG_MICRO_LESSON, Action.TRANSFER_PRACTICE} else None
            ),
            pass_condition=PASS_CONDITIONS[chosen],
            on_failure=self._next_on_failure(chosen, candidates, context.mode),
            rationale=(
                f"stage={context.stage.value}; issue={context.issue_type}; "
                f"target_scaffold={target_level}; mastery={context.mastery:.2f}; "
                f"confidence={context.mastery_confidence:.2f}; "
                f"failures={context.consecutive_failures}; mode={context.mode.value}; "
                f"intent={context.intent.primary.value}; "
                f"direct_request={context.intent.requests_direct_answer}; "
                f"selected_score={ranking[0].score:.2f}"
            ),
            ranking=ranking,
        )

    def allowed_actions(self, context: PolicyContext) -> set[Action]:
        candidates = set(STAGE_ACTIONS[context.stage])
        if context.mode == TeachingMode.INDEPENDENT:
            return {Action.INDEPENDENT_RETRY}
        if context.mode == TeachingMode.SEMI_GUIDED and context.consecutive_failures < 2:
            candidates.discard(Action.LOCAL_DEMONSTRATION)
        if context.target_knowledge_node_id is None or not (
            context.historical_error_count >= 2 or context.recent_error_recurrence
        ):
            candidates.discard(Action.KG_MICRO_LESSON)
        if not self._direct_explanation_trigger(context):
            candidates.discard(Action.DIRECT_EXPLANATION)
        if context.last_action_succeeded is not True:
            candidates.discard(Action.TRANSFER_PRACTICE)
        return candidates

    @staticmethod
    def _direct_explanation_trigger(context: PolicyContext) -> bool:
        return (
            context.mode != TeachingMode.INDEPENDENT
            and context.consecutive_failures >= 3
            and context.last_action_succeeded is False
            and context.last_action
            in {Action.CONCEPT_HINT, Action.KG_MICRO_LESSON, Action.LOCAL_DEMONSTRATION}
        )

    @staticmethod
    def _target_level(context: PolicyContext) -> int:
        if context.mode == TeachingMode.INDEPENDENT:
            return 0
        if (
            context.mastery >= 0.75
            and context.mastery_confidence >= 0.5
            and context.historical_error_count <= 1
        ):
            level = 0
        elif context.mastery <= 0.35 or context.historical_error_count >= 2:
            level = 2
        else:
            level = 1
        if context.recent_error_recurrence:
            level = max(level, 3)
        if context.consecutive_failures >= 2:
            level = max(level, 2)
        if context.consecutive_failures >= 3:
            level = max(level, 3)
        if max(context.confusion_score, context.intent.frustration) >= 0.7:
            level = max(level, 2)
        return min(level, 4)

    @staticmethod
    def _score(action: Action, context: PolicyContext, target_level: int) -> ActionScore:
        level = SCAFFOLD_LEVEL[action]
        score = 10 - 3 * abs(level - target_level)
        reasons = [f"scaffold_distance={abs(level - target_level)}"]
        if (
            action == Action.SELF_CHECK
            and context.mastery >= 0.75
            and context.mastery_confidence >= 0.5
            and context.historical_error_count <= 1
            and context.consecutive_failures == 0
        ):
            score += 4
            reasons.append("high_mastery_first_error")
        if action == Action.KG_MICRO_LESSON and (
            context.historical_error_count >= 2 or context.recent_error_recurrence
        ):
            score += 4
            reasons.append("repeated_error")
        if action == Action.DIRECT_EXPLANATION:
            score += 9
            reasons.append("three_failures_after_strong_support")
        if action == Action.TRANSFER_PRACTICE and context.last_action_succeeded:
            score += 5
            reasons.append("successful_prior_action")
        if action == Action.INDEPENDENT_RETRY and context.mode == TeachingMode.INDEPENDENT:
            score += 5
            reasons.append("independent_mode")
        elif action == Action.INDEPENDENT_RETRY:
            score -= 2
            reasons.append("guided_mode_prefers_targeted_action")
        if action == context.last_action and context.last_action_succeeded is False:
            score -= 5
            reasons.append("failed_action_penalty")
        if action == Action.SOCRATIC_QUESTION and context.intent.confusion >= 0.5:
            score += 1
            reasons.append("student_confusion")
        if action == Action.SELF_CHECK and context.average_hint_level >= 2:
            score += 1
            reasons.append("reduce_hint_dependence")
        return ActionScore(action=action, score=score, reasons=reasons)

    @staticmethod
    def _next_on_failure(chosen: Action, allowed: set[Action], mode: TeachingMode) -> Action:
        if mode == TeachingMode.INDEPENDENT or chosen == Action.DIRECT_EXPLANATION:
            return Action.INDEPENDENT_RETRY
        if chosen in ESCALATION_ORDER:
            position = ESCALATION_ORDER.index(chosen)
            for action in ESCALATION_ORDER[position + 1 :]:
                if action in allowed:
                    return action
        return chosen
