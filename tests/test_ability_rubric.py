from types import SimpleNamespace
from typing import cast

import pytest
from app.domain.enums import AbilityDimension, TeachingMode, TeachingStage
from app.services.grammar.analyzer import GrammarAnalyzer
from app.workflows.ability_rubric import ObservableWritingRubric, RubricAssessment
from app.workflows.schemas import (
    ContentPlan,
    PromptAnalysisAnswer,
    StructurePlan,
    WorkflowSubmission,
)
from pydantic import ValidationError


class PatternAnalyzer:
    def analyze(self, text: str) -> SimpleNamespace:
        errors = [
            SimpleNamespace(knowledge_node_id="subject_verb_agreement")
            for _ in range(text.count("She go "))
        ]
        return SimpleNamespace(errors=errors)


def score(
    stage: TeachingStage,
    submission: WorkflowSubmission,
    *,
    before: str | None = "She go to school.",
    first: str | None = "She go to school.",
    mode: TeachingMode = TeachingMode.GUIDED,
) -> RubricAssessment | None:
    scorer = ObservableWritingRubric(cast(GrammarAnalyzer, PatternAnalyzer()))
    return scorer.assess(
        stage=stage,
        mode=mode,
        submission=submission,
        task_genre="narrative",
        task_required_points=["school day"],
        current_draft=before,
        first_draft=first,
    )


def test_prompt_rubric_distinguishes_quality_with_same_gate_result() -> None:
    weak = PromptAnalysisAnswer(
        audience="friends",
        purpose="describe",
        genre="narrative",
        required_points=["school day"],
        tense="past",
        person="first",
        constraints="brief",
    )
    strong = weak.model_copy(
        update={
            "audience": "my classmates who do not know my school",
            "purpose": "explain how the school day changed my view of teamwork",
            "constraints": "include a beginning middle and ending with a personal reflection",
        }
    )
    weak_score = score(
        TeachingStage.PROMPT_ANALYSIS,
        WorkflowSubmission(kind="response", prompt_analysis=weak),
    )
    strong_score = score(
        TeachingStage.PROMPT_ANALYSIS,
        WorkflowSubmission(kind="response", prompt_analysis=strong),
    )
    assert weak_score is not None and strong_score is not None
    assert weak_score.dimension == AbilityDimension.PROMPT_ANALYSIS
    assert 0.5 < weak_score.score < strong_score.score == 1
    assert score(TeachingStage.PROMPT_ANALYSIS, WorkflowSubmission(kind="response")) is None


def test_revision_scores_come_from_artifacts_and_remain_bounded() -> None:
    grammar_failed = score(
        TeachingStage.GRAMMAR_REVISION,
        WorkflowSubmission(kind="response", text="She go to school."),
    )
    grammar_corrected = score(
        TeachingStage.GRAMMAR_REVISION,
        WorkflowSubmission(kind="response", text="She goes to school."),
    )
    assert grammar_failed is not None and grammar_corrected is not None
    assert grammar_failed.dimension == AbilityDimension.GRAMMAR
    assert grammar_failed.score == 0.3
    assert grammar_corrected.score == 1

    structure_weak = score(
        TeachingStage.STRUCTURE_REVISION,
        WorkflowSubmission(
            kind="response",
            text="She goes to school.",
            structure_plan=StructurePlan(opening="start", body="middle", conclusion="end"),
        ),
    )
    structure_strong = score(
        TeachingStage.STRUCTURE_REVISION,
        WorkflowSubmission(
            kind="response",
            text=(
                "First, I arrived at school.\n\n"
                "Then I learned with my friends.\n\nFinally, I went home."
            ),
            structure_plan=StructurePlan(
                opening="Introduce the school day and its opening challenge clearly",
                body="Describe the classroom project and how friends worked together",
                conclusion="Reflect on what the team learned by the end",
            ),
        ),
    )
    assert structure_weak is not None and structure_strong is not None
    assert structure_weak.score < structure_strong.score

    no_new_content = score(
        TeachingStage.CONTENT_EXPANSION,
        WorkflowSubmission(kind="response", text="She go to school."),
    )
    expanded = score(
        TeachingStage.CONTENT_EXPANSION,
        WorkflowSubmission(
            kind="response",
            text="She goes to school. During science class, our team designed a bridge from paper.",
            content_plan=ContentPlan(
                viewpoint="The school day taught me to work with classmates",
                reason="We had to solve a problem as a team",
                example="Our science group built a bridge from paper",
                detail="I folded paper strips while Mia tested each model",
                result_or_feeling="We felt proud because our bridge carried a book",
            ),
        ),
    )
    assert no_new_content is not None and expanded is not None
    assert no_new_content.score < expanded.score <= 1

    expression = score(
        TeachingStage.LANGUAGE_REFINEMENT,
        WorkflowSubmission(
            kind="response",
            text="First, she goes to school because her friends are there.",
            relation_explanation="Because links her reason to the action in the first clause.",
        ),
    )
    assert expression is not None
    assert expression.dimension == AbilityDimension.SENTENCE_EXPRESSION
    assert 0 <= expression.score <= 1


def test_final_score_and_rubric_validation() -> None:
    final = score(
        TeachingStage.FINAL_EVALUATION,
        WorkflowSubmission(kind="finalize"),
        before="She goes to school.",
    )
    assert final is not None and final.dimension == AbilityDimension.GRAMMAR
    assert final.score == 1
    assert (
        score(TeachingStage.FINAL_EVALUATION, WorkflowSubmission(kind="finalize"), before=None)
        is None
    )
    with pytest.raises(ValidationError, match="rubric score does not match criteria"):
        RubricAssessment.model_validate({**final.model_dump(), "score": 0.1})
    with pytest.raises(ValidationError):
        RubricAssessment.model_validate({**final.model_dump(), "score": 1.1})


def test_empty_artifacts_independent_mode_and_repeatability() -> None:
    submission = WorkflowSubmission(kind="response", text="This narrative is about my school day.")
    first = score(TeachingStage.PROMPT_ANALYSIS, submission, mode=TeachingMode.INDEPENDENT)
    second = score(TeachingStage.PROMPT_ANALYSIS, submission, mode=TeachingMode.INDEPENDENT)
    assert first is not None and first == second
    assert first.dimension == AbilityDimension.PROMPT_ANALYSIS
    assert 0 <= first.score <= 1
    assert score(TeachingStage.FIRST_DRAFT, submission) is None
    assert score(TeachingStage.SECOND_DRAFT, submission) is None
    assert score(TeachingStage.STRUCTURE_REVISION, WorkflowSubmission(kind="response")) is None

    no_content = score(
        TeachingStage.CONTENT_EXPANSION,
        WorkflowSubmission(kind="response", text="Plain words."),
        before="Plain words.",
    )
    assert no_content is not None and no_content.score == 0


def test_analyzer_error_is_not_silently_hidden() -> None:
    class FailingAnalyzer:
        def analyze(self, text: str) -> None:
            raise RuntimeError("analyzer unavailable")

    scorer = ObservableWritingRubric(cast(GrammarAnalyzer, FailingAnalyzer()))
    with pytest.raises(RuntimeError, match="analyzer unavailable"):
        scorer.assess(
            stage=TeachingStage.GRAMMAR_REVISION,
            mode=TeachingMode.GUIDED,
            submission=WorkflowSubmission(kind="response", text="She goes to school."),
            task_genre="narrative",
            task_required_points=[],
            current_draft="She go to school.",
            first_draft="She go to school.",
        )
