import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Literal

from pydantic import Field, model_validator

from app.domain.enums import AbilityDimension, TeachingMode, TeachingStage
from app.domain.schemas import DomainModel
from app.services.grammar.analyzer import GrammarAnalyzer
from app.workflows.schemas import WorkflowSubmission

WORD = re.compile(r"[a-z]+(?:'[a-z]+)?", re.IGNORECASE)
CONTENT_STOPWORDS = {
    "about",
    "after",
    "and",
    "from",
    "have",
    "into",
    "that",
    "their",
    "there",
    "these",
    "this",
    "those",
    "with",
    "would",
    "your",
}
TRANSITIONS = (
    "first",
    "next",
    "then",
    "finally",
    "after",
    "before",
    "while",
    "because",
    "although",
    "however",
    "therefore",
    "in the end",
    "at the end",
)


class RubricCriterion(DomainModel):
    code: str = Field(min_length=1)
    value: float = Field(ge=0, le=1)
    weight: float = Field(gt=0, le=1)


class RubricAssessment(DomainModel):
    version: Literal["observable-writing-v1"] = "observable-writing-v1"
    dimension: AbilityDimension
    score: float = Field(ge=0, le=1)
    criteria: list[RubricCriterion] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_score(self) -> "RubricAssessment":
        if abs(sum(item.weight for item in self.criteria) - 1) > 1e-6:
            raise ValueError("rubric weights must sum to one")
        expected = round(sum(item.value * item.weight for item in self.criteria), 4)
        if abs(self.score - expected) > 1e-6:
            raise ValueError("rubric score does not match criteria")
        return self


def _words(text: str) -> list[str]:
    return WORD.findall(text.casefold())


def _fraction(numerator: int, denominator: int) -> float:
    return numerator / denominator


def _assessment(
    dimension: AbilityDimension, values: list[tuple[str, float, float]]
) -> RubricAssessment:
    weight_total = sum(weight for _, _, weight in values)
    criteria = [
        RubricCriterion(code=code, value=round(value, 4), weight=weight / weight_total)
        for code, value, weight in values
    ]
    return RubricAssessment(
        dimension=dimension,
        score=round(sum(item.value * item.weight for item in criteria), 4),
        criteria=criteria,
    )


class ObservableWritingRubric:
    """Bounded, auditable process rubric; never uses a stage's pass/fail result."""

    def __init__(self, analyzer: GrammarAnalyzer) -> None:
        self.analyzer = analyzer

    def assess(
        self,
        *,
        stage: TeachingStage,
        mode: TeachingMode,
        submission: WorkflowSubmission,
        task_genre: str,
        task_required_points: list[str],
        current_draft: str | None,
        first_draft: str | None,
    ) -> RubricAssessment | None:
        if stage == TeachingStage.PROMPT_ANALYSIS:
            return self._prompt(submission, mode, task_genre, task_required_points)
        if stage == TeachingStage.GRAMMAR_REVISION:
            return self._grammar(current_draft, submission.text)
        if stage == TeachingStage.STRUCTURE_REVISION:
            return self._structure(submission)
        if stage == TeachingStage.CONTENT_EXPANSION:
            return self._content(submission, current_draft, task_required_points)
        if stage == TeachingStage.LANGUAGE_REFINEMENT:
            return self._expression(submission, current_draft)
        if stage == TeachingStage.FINAL_EVALUATION:
            return self._grammar(first_draft, current_draft)
        return None

    @staticmethod
    def _prompt(
        submission: WorkflowSubmission,
        mode: TeachingMode,
        task_genre: str,
        required_points: list[str],
    ) -> RubricAssessment | None:
        answer = submission.prompt_analysis
        text = submission.text or ""
        if mode == TeachingMode.INDEPENDENT:
            if not text.strip():
                return None
            lower = text.casefold()
            genre = float(bool(re.search(rf"\b{re.escape(task_genre.casefold())}\b", lower)))
            covered = sum(point.casefold().strip() in lower for point in required_points)
            specificity = min(len(_words(text)) / 18, 1)
        else:
            if answer is None:
                return None
            genre = float(answer.genre.casefold().strip() == task_genre.casefold().strip())
            supplied = {point.casefold().strip() for point in answer.required_points}
            covered = sum(point.casefold().strip() in supplied for point in required_points)
            specificity = min(
                len(_words(" ".join((answer.audience, answer.purpose, answer.constraints)))) / 18,
                1,
            )
        values = [
            ("genre_alignment", genre, 0.35),
            ("task_interpretation_detail", specificity, 0.20),
        ]
        if required_points:
            values.append(
                ("required_point_coverage", _fraction(covered, len(required_points)), 0.45)
            )
        return _assessment(AbilityDimension.PROMPT_ANALYSIS, values)

    def _grammar(self, before: str | None, after: str | None) -> RubricAssessment | None:
        if not before or not after or not after.strip():
            return None
        previous = Counter(item.knowledge_node_id for item in self.analyzer.analyze(before).errors)
        current = Counter(item.knowledge_node_id for item in self.analyzer.analyze(after).errors)
        prior_count, current_count = sum(previous.values()), sum(current.values())
        resolved = sum((previous - current).values())
        values = [("detected_pattern_accuracy", 1 / (1 + current_count), 0.60)]
        if prior_count:
            values.append(("detected_error_resolution", _fraction(resolved, prior_count), 0.40))
        return _assessment(AbilityDimension.GRAMMAR, values)

    @staticmethod
    def _structure(submission: WorkflowSubmission) -> RubricAssessment | None:
        text = submission.text or ""
        if not text.strip():
            return None
        paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
        lower = text.casefold()
        transitions = sum(bool(re.search(rf"\b{re.escape(term)}\b", lower)) for term in TRANSITIONS)
        values = [
            ("paragraph_organization", min(len(paragraphs) / 3, 1), 0.35),
            ("explicit_sequence", min(transitions / 2, 1), 0.25),
        ]
        if submission.structure_plan is not None:
            plan = submission.structure_plan
            detail = (
                sum(
                    min(len(_words(part)) / 8, 1)
                    for part in (plan.opening, plan.body, plan.conclusion)
                )
                / 3
            )
            values.append(("opening_body_conclusion_detail", detail, 0.40))
        return _assessment(AbilityDimension.STRUCTURE, values)

    @staticmethod
    def _content(
        submission: WorkflowSubmission, before: str | None, required_points: list[str]
    ) -> RubricAssessment | None:
        text = submission.text or ""
        if not text.strip() or before is None:
            return None
        after_words = set(_words(text)) - CONTENT_STOPWORDS
        before_words = set(_words(before)) - CONTENT_STOPWORDS
        novel = min(len(after_words - before_words) / 10, 1)
        values = [("new_content_vocabulary", novel, 0.35)]
        if required_points:
            coverage = _fraction(
                sum(
                    bool((set(_words(point)) - CONTENT_STOPWORDS) & after_words)
                    for point in required_points
                ),
                len(required_points),
            )
            values.append(("required_topic_coverage", coverage, 0.30))
        if submission.content_plan is not None:
            plan = submission.content_plan
            detail = (
                sum(
                    min(len(_words(part)) / 8, 1)
                    for part in (
                        plan.viewpoint,
                        plan.reason,
                        plan.example,
                        plan.detail,
                        plan.result_or_feeling,
                    )
                )
                / 5
            )
            values.append(("idea_expansion_detail", detail, 0.35))
        return _assessment(AbilityDimension.CONTENT, values)

    @staticmethod
    def _expression(submission: WorkflowSubmission, before: str | None) -> RubricAssessment | None:
        text = submission.text or ""
        if not text.strip() or before is None:
            return None
        previous, current = _words(before), _words(text)
        changed = sum(
            max(end_before - start_before, end_after - start_after)
            for operation, start_before, end_before, start_after, end_after in SequenceMatcher(
                a=previous, b=current
            ).get_opcodes()
            if operation != "equal"
        )
        lower = text.casefold()
        connectors = sum(bool(re.search(rf"\b{re.escape(term)}\b", lower)) for term in TRANSITIONS)
        values = [
            ("observed_expression_edits", min(changed / 3, 1), 0.30),
            ("relation_marker_variety", min(connectors / 2, 1), 0.30),
        ]
        if submission.relation_explanation:
            values.append(
                (
                    "sentence_relation_explanation",
                    min(len(_words(submission.relation_explanation)) / 12, 1),
                    0.40,
                )
            )
        return _assessment(AbilityDimension.SENTENCE_EXPRESSION, values)
