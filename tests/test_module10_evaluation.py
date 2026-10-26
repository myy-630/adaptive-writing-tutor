import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.schemas import EvaluatorJudgement, TeachingText
from app.domain.enums import TeachingMode, TeachingStage
from app.domain.schemas import Student
from app.services.evaluation.ablation import AblationRunner
from app.services.evaluation.benchmark import load_mrbench_mathdial
from app.services.evaluation.calibration import (
    calibrate_mrbench,
    replay_calibration,
    save_calibration,
)
from app.services.evaluation.judge import StructuredTutorJudge
from app.services.evaluation.report import (
    build_report,
    replay_report,
    rescore_frozen_report,
    save_report,
)
from app.services.evaluation.rules import RuleEvaluator
from app.services.evaluation.schemas import (
    VARIANTS,
    EvaluationCase,
    EvaluationConfig,
    JudgedRecord,
    JudgeInput,
    JudgeScores,
    ObservedToolCall,
    ResponseRecord,
    VariantName,
)
from app.services.student_state.schemas import (
    InteractionState,
    PromptDependency,
    StudentStateSnapshot,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
WRITING_DATA = ROOT / "data/processed/writing_eval_cases.jsonl"
MRBENCH_DATA = ROOT / "data/processed/mrbench_mathdial_v1_sample.jsonl"
MRBENCH_META = ROOT / "data/processed/mrbench_mathdial_v1_sample.meta.json"


class ScriptedEvaluationProvider:
    def __init__(self) -> None:
        self.types: list[type] = []

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type
    ) -> object:
        self.types.append(response_type)
        if response_type is TeachingText:
            return TeachingText(text="Can you check the verb after she and revise it yourself?")
        if response_type is EvaluatorJudgement:
            return EvaluatorJudgement(
                accurate_to_issue=True,
                scaffold_too_strong=False,
                scaffold_too_weak=False,
                actionable_next_step=True,
                stage_appropriate=True,
                ghostwriting=False,
                rationale="Appropriate",
            )
        if response_type is JudgeScores:
            return JudgeScores(
                problem_identification=0.9,
                problem_location=0.8,
                answer_exposure=False,
                ghostwriting=False,
                pedagogy_match=None,
                actionability=0.9,
                scaffold_strength=0.8,
                mode_compliance=None,
                coherence=0.9,
                rationale="The reply asks for a student attempt.",
            )
        raise AssertionError(response_type)


def writing_case(student_id=None) -> EvaluationCase:
    raw = json.loads(WRITING_DATA.read_text(encoding="utf-8").splitlines()[0])
    raw["student_id"] = str(student_id or uuid4())
    return EvaluationCase.model_validate(raw)


def snapshot(student_id) -> StudentStateSnapshot:
    return StudentStateSnapshot(
        student=Student(id=student_id, grade=9, learning_goal="Improve self-revision"),
        abilities=[],
        knowledge=[],
        error_patterns=[],
        prompt_dependency=PromptDependency(
            evidence_count=0,
            average_hint_level=0,
            independent_revision_count=0,
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


def response(
    case: EvaluationCase, text: str | None = "Can you check the verb after she?"
) -> ResponseRecord:
    return ResponseRecord(
        case_id=case.id,
        variant=VariantName.ORDINARY_LLM,
        text=text,
        stage=case.stage,
        mode=case.mode,
        model_calls=1,
        provider_model="scripted",
    )


def test_mrbench_adapter_and_license_guard(tmp_path) -> None:
    examples = load_mrbench_mathdial(MRBENCH_DATA, MRBENCH_META, tutor_names={"Expert", "GPT4"})
    assert len(examples) == 8
    assert len({item.conversation_id for item in examples}) == 4
    assert all(item.source == "MRBench_V1:MathDial" for item in examples)
    assert all(item.gold_annotations for item in examples)
    assert examples[0].judge_input().mode is None
    changed = tmp_path / "changed.jsonl"
    changed.write_bytes(MRBENCH_DATA.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash"):
        load_mrbench_mathdial(changed, MRBENCH_META)


def test_rules_detect_permissions_modes_and_answer_leaks() -> None:
    case = writing_case()
    evaluator = RuleEvaluator()
    assert all(item.passed for item in evaluator.evaluate(case, response(case)))
    leaked = response(case, "Replace go with goes.")
    failed = {item.code for item in evaluator.evaluate(case, leaked) if not item.passed}
    assert {"student_self_check", "early_answer_exposure"} <= failed
    markdown_leak = response(case, "Check the pattern: she go**es**. What do you notice?")
    assert "early_answer_exposure" in {
        item.code for item in evaluator.evaluate(case, markdown_leak) if not item.passed
    }
    good_hint = response(case, "Look at the verb. What small change does it need?")
    assert next(
        item for item in evaluator.evaluate(case, good_hint) if item.code == "student_self_check"
    ).passed
    forbidden = response(case)
    forbidden.tool_calls = [ObservedToolCall(actor="teaching", name="write_state")]
    assert "tool_permission" in {
        item.code for item in evaluator.evaluate(case, forbidden) if not item.passed
    }
    skipped = response(case)
    skipped.stage_history = [TeachingStage.PROMPT_ANALYSIS, TeachingStage.GRAMMAR_REVISION]
    assert "workflow_order" in {
        item.code for item in evaluator.evaluate(case, skipped) if not item.passed
    }
    independent = case.model_copy(update={"mode": TeachingMode.INDEPENDENT})
    assert {"independent_mode_intervention", "mode_transition"} <= {
        item.code for item in evaluator.evaluate(independent, response(case)) if not item.passed
    }
    with pytest.raises(ValueError, match="different evaluation case"):
        evaluator.evaluate(case, response(case).model_copy(update={"case_id": "other"}))


def test_content_ghostwriting_rule_is_conservative() -> None:
    case = writing_case().model_copy(
        update={
            "stage": TeachingStage.CONTENT_EXPANSION,
            "student_text": "I enjoy science projects. " * 30,
        }
    )
    copied = response(case, case.student_text)
    assert "content_ghostwriting" in {
        item.code for item in RuleEvaluator().evaluate(case, copied) if not item.passed
    }


def test_structured_judge_and_schema_boundaries() -> None:
    provider = ScriptedEvaluationProvider()
    item = JudgeInput(
        domain="writing", context="Student wrote She go.", tutor_response="Check the verb."
    )
    result = asyncio.run(StructuredTutorJudge(provider).judge(item))
    assert result.problem_identification == 0.9
    assert provider.types == [JudgeScores]
    with pytest.raises(ValidationError):
        JudgeScores(
            problem_identification=1.2,
            answer_exposure=False,
            ghostwriting=False,
            actionability=0.5,
            coherence=0.5,
            rationale="Invalid score",
        )


def test_all_six_ablation_variants_run_independently() -> None:
    case = writing_case()
    provider = ScriptedEvaluationProvider()

    async def full(item: EvaluationCase) -> ResponseRecord:
        return ResponseRecord(
            case_id=item.id,
            variant=VariantName.FULL_SYSTEM,
            text="Can you check your verb?",
            stage=item.stage,
            mode=item.mode,
            provider_model="scripted",
        )

    async def run_all() -> list[ResponseRecord]:
        runner = AblationRunner(provider, "scripted", full_system_run=full)
        return [
            await runner.run(case, variant, student_state=snapshot(case.student_id))
            for variant in VariantName
        ]

    results = asyncio.run(run_all())
    assert [item.variant for item in results] == list(VariantName)
    assert set(VARIANTS) == set(VariantName)
    assert results[0].action is None
    assert results[3].action is not None
    assert results[4].evaluator_verdict == "pass"
    assert results[4].model_calls == 2
    assert results[5].model_calls is None


def test_ablation_requires_state_and_full_runner() -> None:
    case = writing_case()
    runner = AblationRunner(ScriptedEvaluationProvider(), "scripted")
    with pytest.raises(ValueError, match="Student State"):
        asyncio.run(runner.run(case, VariantName.STUDENT_STATE))
    with pytest.raises(ValueError, match="full system workflow"):
        asyncio.run(runner.run(case, VariantName.FULL_SYSTEM))


def test_policy_independent_mode_has_no_teaching_model_call() -> None:
    case = writing_case().model_copy(update={"mode": TeachingMode.INDEPENDENT})
    provider = ScriptedEvaluationProvider()
    runner = AblationRunner(provider, "scripted")
    result = asyncio.run(
        runner.run(case, VariantName.PEDAGOGY_EVALUATOR, student_state=snapshot(case.student_id))
    )
    assert result.text is None
    assert result.model_calls == 0
    assert result.evaluator_verdict == "pass"
    assert provider.types == []
    assert all(
        finding.passed for finding in RuleEvaluator().evaluate(case, result) if finding.applicable
    )


def test_report_save_and_replay_recomputes_real_records(tmp_path) -> None:
    case = writing_case()
    observed = JudgedRecord(
        response=response(case),
        rules=RuleEvaluator().evaluate(case, response(case)),
        judge=JudgeScores(
            problem_identification=0.7,
            problem_location=0.8,
            answer_exposure=False,
            ghostwriting=False,
            pedagogy_match=None,
            actionability=0.9,
            scaffold_strength=0.7,
            mode_compliance=1.0,
            coherence=0.8,
            rationale="Observed scripted response",
        ),
    )
    config = EvaluationConfig(
        variants=[VariantName.ORDINARY_LLM],
        dataset_id="writing-fixture",
        dataset_path=WRITING_DATA,
        dataset_sha256=hashlib.sha256(WRITING_DATA.read_bytes()).hexdigest(),
        provider_model="scripted",
        judge_model="scripted",
    )
    report = build_report(config, [observed])
    path = tmp_path / "report.json"
    save_report(report, path)
    assert replay_report(path).summaries == report.summaries
    rescored = rescore_frozen_report(path, [case])
    assert rescored.config.ruleset_version == "3"
    assert rescored.parent_report_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert rescored.config.variant_settings == {}
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["summaries"][VariantName.ORDINARY_LLM.value]["count"] = 99
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="summary"):
        replay_report(path)


def test_mrbench_calibration_tracks_gold_and_replays(tmp_path) -> None:
    examples = load_mrbench_mathdial(MRBENCH_DATA, MRBENCH_META, tutor_names={"Expert"})[:2]
    provider = ScriptedEvaluationProvider()
    report = asyncio.run(
        calibrate_mrbench(
            examples,
            StructuredTutorJudge(provider),
            sample_path=MRBENCH_DATA,
            metadata_path=MRBENCH_META,
            judge_model="scripted",
        )
    )
    assert len(report.items) == 2
    assert report.source_license == "CC BY-SA 4.0"
    assert report.compared_counts
    path = tmp_path / "mrbench-calibration-test.json"
    save_calibration(report, path)
    assert replay_calibration(path, MRBENCH_DATA).agreement == report.agreement
