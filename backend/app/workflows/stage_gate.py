from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.errors import DomainError
from app.domain.enums import (
    STAGE_ORDER,
    AbilityDimension,
    EvidenceOutcome,
    TeachingMode,
    TeachingStage,
)
from app.domain.schemas import LearningEvidence
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.grammar.transfer import transfer_succeeded
from app.workflows.draft_comparison import DraftComparison, compare_drafts
from app.workflows.schemas import WorkflowSubmission

STAGE_ABILITY = {
    TeachingStage.PROMPT_ANALYSIS: AbilityDimension.PROMPT_ANALYSIS,
    TeachingStage.STRUCTURE_REVISION: AbilityDimension.STRUCTURE,
    TeachingStage.CONTENT_EXPANSION: AbilityDimension.CONTENT,
    TeachingStage.LANGUAGE_REFINEMENT: AbilityDimension.SENTENCE_EXPRESSION,
    TeachingStage.FINAL_EVALUATION: AbilityDimension.GRAMMAR,
}


@dataclass(frozen=True)
class StageOutcome:
    stage_after: TeachingStage
    passed: bool
    completed: bool
    feedback: str
    save_draft: bool = False
    evidence: LearningEvidence | None = None
    comparison: DraftComparison | None = None


class StageGate:
    """Deterministic entry/exit checks and observable evidence construction."""

    def __init__(self, analyzer: GrammarAnalyzer, min_draft_words: int = 20) -> None:
        if min_draft_words < 1:
            raise ValueError("min_draft_words must be positive")
        self.analyzer = analyzer
        self.min_draft_words = min_draft_words

    def assess(
        self,
        *,
        request_id: UUID,
        student_id: UUID,
        session_id: UUID,
        observed_at: datetime,
        stage: TeachingStage,
        mode: TeachingMode,
        submission: WorkflowSubmission,
        task_genre: str,
        task_required_points: list[str],
        current_draft: str | None,
        first_draft: str | None,
        needs_transfer: bool = False,
        transfer_node_id: str | None = None,
        prior_hint_level: int = 0,
    ) -> StageOutcome:
        if submission.kind == "start":
            return StageOutcome(stage, False, False, "Begin the current stage when ready.")
        if stage == TeachingStage.FINAL_EVALUATION:
            if submission.kind != "finalize" or not current_draft or not first_draft:
                raise DomainError("finalization_not_ready", "Draft 1 and Draft 2 are required", 409)
            comparison = compare_drafts(self.analyzer, first_draft, current_draft)
            return StageOutcome(
                stage,
                True,
                True,
                comparison.feedback(),
                evidence=self._evidence(
                    request_id,
                    student_id,
                    session_id,
                    observed_at,
                    stage,
                    EvidenceOutcome.SUCCESS
                    if comparison.remaining_count == 0
                    else EvidenceOutcome.UNCERTAIN,
                    prior_hint_level,
                ),
                comparison=comparison,
            )
        if submission.kind != "response":
            raise DomainError("invalid_submission_kind", "Student response is required", 422)
        transfer_verified = (
            transfer_succeeded(transfer_node_id, submission.transfer_response)
            if needs_transfer
            else False
        )
        passed, feedback, save_draft = self._check_stage(
            stage,
            mode,
            submission,
            task_genre,
            task_required_points,
            current_draft,
            first_draft,
            needs_transfer,
            transfer_verified,
        )
        index = STAGE_ORDER.index(stage)
        next_stage = STAGE_ORDER[index + 1] if passed else stage
        knowledge_node = None
        if stage == TeachingStage.GRAMMAR_REVISION and current_draft:
            original_errors = self.analyzer.analyze(current_draft).errors
            knowledge_node = original_errors[0].knowledge_node_id if original_errors else None
        return StageOutcome(
            next_stage,
            passed,
            False,
            feedback,
            save_draft=save_draft,
            evidence=self._evidence(
                request_id,
                student_id,
                session_id,
                observed_at,
                stage,
                EvidenceOutcome.SUCCESS if passed else EvidenceOutcome.FAILURE,
                prior_hint_level,
                knowledge_node,
                submission.independent_revision,
                transfer_verified and passed,
            ),
        )

    def _check_stage(
        self,
        stage: TeachingStage,
        mode: TeachingMode,
        submission: WorkflowSubmission,
        task_genre: str,
        task_required_points: list[str],
        current_draft: str | None,
        first_draft: str | None,
        needs_transfer: bool,
        transfer_verified: bool,
    ) -> tuple[bool, str, bool]:
        text = submission.text or ""
        if (
            stage
            in {
                TeachingStage.GRAMMAR_REVISION,
                TeachingStage.STRUCTURE_REVISION,
                TeachingStage.CONTENT_EXPANSION,
                TeachingStage.LANGUAGE_REFINEMENT,
                TeachingStage.SECOND_DRAFT,
            }
            and current_draft is None
        ):
            raise DomainError("stage_not_ready", "A prior draft is required", 409)
        if stage == TeachingStage.PROMPT_ANALYSIS:
            if mode == TeachingMode.INDEPENDENT:
                normalized = text.casefold()
                passed = (
                    bool(text.strip())
                    and task_genre.casefold() in normalized
                    and all(point.casefold() in normalized for point in task_required_points)
                )
                return (
                    passed,
                    (
                        "Independent prompt analysis recorded."
                        if passed
                        else "Describe the task and include its required points in your own words."
                    ),
                    False,
                )
            answer = submission.prompt_analysis
            covered = (
                {point.casefold().strip() for point in task_required_points}
                <= {point.casefold().strip() for point in answer.required_points}
                if answer
                else False
            )
            passed = (
                answer is not None and answer.genre.casefold() == task_genre.casefold() and covered
            )
            return (
                passed,
                (
                    "Prompt analysis recorded."
                    if passed
                    else "Complete the prompt analysis and match the task genre."
                ),
                False,
            )
        if stage == TeachingStage.FIRST_DRAFT:
            passed = len(text.split()) >= self.min_draft_words
            return passed, self._draft_feedback(passed), passed
        if stage == TeachingStage.GRAMMAR_REVISION:
            if not current_draft or not text.strip():
                return False, "Submit a revised draft to check grammar.", False
            errors = self.analyzer.analyze(text).errors
            passed = not errors and (not needs_transfer or transfer_verified)
            feedback = (
                "Detected grammar issues are resolved."
                if passed
                else (
                    "Revise detected grammar issues and complete the transfer attempt "
                    "when requested."
                )
            )
            return passed, feedback, True
        if stage == TeachingStage.STRUCTURE_REVISION:
            passed = (
                (mode == TeachingMode.INDEPENDENT or submission.structure_plan is not None)
                and len(text.split()) >= self.min_draft_words
                and (mode != TeachingMode.INDEPENDENT or text != current_draft)
            )
            return (
                passed,
                "Structure revision recorded."
                if passed
                else "Add opening, body, conclusion and revise the draft.",
                passed,
            )
        if stage == TeachingStage.CONTENT_EXPANSION:
            passed = (
                (mode == TeachingMode.INDEPENDENT or submission.content_plan is not None)
                and bool(text.strip())
                and text != current_draft
            )
            return (
                passed,
                "Content expansion recorded."
                if passed
                else "Add your own reason, example and detail, then revise the draft.",
                passed,
            )
        if stage == TeachingStage.LANGUAGE_REFINEMENT:
            passed = (
                (mode == TeachingMode.INDEPENDENT or bool(submission.relation_explanation))
                and bool(text.strip())
                and text != current_draft
            )
            return (
                passed,
                "Language refinement recorded."
                if passed
                else "Explain a sentence relationship and revise your own wording.",
                passed,
            )
        if stage == TeachingStage.SECOND_DRAFT:
            passed = (
                submission.independent_revision
                and len(text.split()) >= self.min_draft_words
                and bool(first_draft)
                and text != first_draft
            )
            return (
                passed,
                "Independent Draft 2 recorded."
                if passed
                else "Write Draft 2 independently from the revision checklist.",
                passed,
            )
        raise DomainError("unknown_stage", "Unsupported teaching stage", 422)

    def _draft_feedback(self, passed: bool) -> str:
        return (
            "Draft 1 recorded."
            if passed
            else f"Draft 1 needs at least {self.min_draft_words} words before revision."
        )

    @staticmethod
    def _evidence(
        request_id: UUID,
        student_id: UUID,
        session_id: UUID,
        observed_at: datetime,
        stage: TeachingStage,
        outcome: EvidenceOutcome,
        hint_level: int,
        knowledge_node: str | None = None,
        independent_revision: bool = False,
        transfer_success: bool = False,
    ) -> LearningEvidence:
        ability = STAGE_ABILITY.get(stage)
        if ability is None and knowledge_node is None:
            ability = AbilityDimension.GRAMMAR if stage == TeachingStage.GRAMMAR_REVISION else None
        if ability is None and knowledge_node is None:
            ability = AbilityDimension.SENTENCE_EXPRESSION
        return LearningEvidence(
            id=uuid5(NAMESPACE_URL, f"workflow:{request_id}:{stage.value}"),
            student_id=student_id,
            session_id=session_id,
            knowledge_node_id=knowledge_node,
            ability_dimension=ability,
            outcome=outcome,
            independent_revision=independent_revision,
            hint_level=hint_level,
            transfer_success=transfer_success,
            observed_at=observed_at,
        )
