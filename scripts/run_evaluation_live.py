import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from app.core.config import Settings
from app.core.responses_provider import configured_responses_provider
from app.db.session import create_database_engine, create_session_factory
from app.domain.schemas import Student
from app.services.evaluation.ablation import AblationRunner
from app.services.evaluation.benchmark import load_mrbench_mathdial
from app.services.evaluation.calibration import calibrate_mrbench, save_calibration
from app.services.evaluation.full_workflow import FullWorkflowEvaluation
from app.services.evaluation.judge import StructuredTutorJudge
from app.services.evaluation.report import build_report, save_report
from app.services.evaluation.rules import RuleEvaluator
from app.services.evaluation.schemas import (
    VARIANTS,
    EvaluationCase,
    EvaluationConfig,
    JudgedRecord,
    JudgeInput,
    VariantName,
)
from app.services.student_state.manager import StudentStateManager

ROOT = Path(__file__).resolve().parents[1]
WRITING_DATA = ROOT / "data/processed/writing_eval_cases.jsonl"
MRBENCH_DATA = ROOT / "data/processed/mrbench_mathdial_v1_sample.jsonl"
MRBENCH_META = ROOT / "data/processed/mrbench_mathdial_v1_sample.meta.json"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run measured offline tutor evaluations")
    parser.add_argument(
        "--variants",
        default="ordinary_llm,full_system",
        help="Comma-separated ablation names; all six are supported",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/evaluation")
    parser.add_argument("--skip-calibration", action="store_true")
    return parser.parse_args()


async def run() -> None:
    args = arguments()
    variants = [VariantName(item.strip()) for item in args.variants.split(",")]
    settings = Settings()
    provider = configured_responses_provider(settings)
    if provider is None:
        raise RuntimeError("Configured model API key is required for live evaluation")
    model_name = (
        settings.deepseek_model if settings.model_provider == "deepseek" else settings.openai_model
    )
    engine = create_database_engine(settings)
    try:
        sessions = create_session_factory(engine)
        manager = StudentStateManager(sessions, settings)
        raw = json.loads(WRITING_DATA.read_text(encoding="utf-8").splitlines()[0])
        case = EvaluationCase.model_validate(raw)
        student = Student(grade=case.grade, learning_goal="Improve grammar through self-revision")
        manager.initialize_student(student)
        case = case.model_copy(update={"student_id": student.id})
        snapshot = manager.read_student_state(student.id)
        judge = StructuredTutorJudge(provider)
        runner = AblationRunner(
            provider,
            model_name,
            full_system_run=FullWorkflowEvaluation(settings),
            max_regenerations=settings.workflow_max_regenerations,
        )
        rules = RuleEvaluator()
        records = []
        for variant in variants:
            response = await runner.run(case, variant, student_state=snapshot)
            judgement = None
            if response.text:
                judgement = await judge.judge(
                    JudgeInput(
                        domain="English writing tutoring",
                        context=f"Task: {case.task_prompt}\nStudent draft: {case.student_text}",
                        tutor_response=response.text,
                        issue=f"{case.issue_category} at {case.issue_location}",
                        expected_correction=case.expected_correction,
                        stage=case.stage.value,
                        mode=case.mode.value,
                        policy_action=response.action.value if response.action else None,
                    )
                )
            records.append(
                JudgedRecord(
                    response=response, rules=rules.evaluate(case, response), judge=judgement
                )
            )
        config = EvaluationConfig(
            variants=variants,
            variant_settings={name: VARIANTS[name] for name in variants},
            dataset_id="project-authored-writing-eval-v1",
            dataset_path=WRITING_DATA.relative_to(ROOT),
            dataset_sha256=hashlib.sha256(WRITING_DATA.read_bytes()).hexdigest(),
            provider_model=model_name,
            judge_model=model_name,
            max_regenerations=settings.workflow_max_regenerations,
        )
        report = build_report(config, records)
        output = args.output_dir / f"writing-{report.run_id}.json"
        save_report(report, output)
        print(
            json.dumps(
                {
                    "writing_report": str(output),
                    "variants": [item.value for item in variants],
                    "summaries": {
                        key.value: value.model_dump(mode="json")
                        for key, value in report.summaries.items()
                    },
                },
                ensure_ascii=False,
            )
        )
        if not args.skip_calibration:
            examples = load_mrbench_mathdial(
                MRBENCH_DATA, MRBENCH_META, tutor_names={"Expert", "GPT4"}
            )
            first_id = examples[0].conversation_id
            selected = [example for example in examples if example.conversation_id == first_id]
            calibration = await calibrate_mrbench(
                selected,
                judge,
                sample_path=MRBENCH_DATA,
                metadata_path=MRBENCH_META,
                judge_model=model_name,
            )
            calibration_path = args.output_dir / f"mrbench-calibration-{report.run_id}.json"
            save_calibration(calibration, calibration_path)
            print(
                json.dumps(
                    {
                        "calibration_report": str(calibration_path),
                        "sample_size": len(calibration.items),
                        "agreement": calibration.agreement,
                        "compared_counts": calibration.compared_counts,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        engine.dispose()
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(run())
