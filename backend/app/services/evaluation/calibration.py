import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.domain.schemas import DomainModel
from app.services.evaluation.benchmark import MRBenchResponse
from app.services.evaluation.judge import StructuredTutorJudge
from app.services.evaluation.schemas import JudgeScores
from pydantic import Field


class CalibrationItem(DomainModel):
    response_id: str
    gold_annotations: dict[str, str]
    judge: JudgeScores


class CalibrationReport(DomainModel):
    created_at: str
    benchmark_id: str
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_license: str
    underlying_source_license: str
    judge_model: str
    items: list[CalibrationItem] = Field(min_length=1)
    agreement: dict[str, float]
    compared_counts: dict[str, int]


ALIGNMENTS = {
    "Mistake_Identification": "problem_identification",
    "Mistake_Location": "problem_location",
    "Revealing_of_the_Answer": "answer_exposure",
    "Actionability": "actionability",
    "Coherence": "coherence",
}


def _binary_gold(label: str) -> bool | None:
    lowered = label.strip().casefold()
    if lowered.startswith("yes"):
        return True
    if lowered == "no":
        return False
    return None


def agreement(items: list[CalibrationItem]) -> tuple[dict[str, float], dict[str, int]]:
    correct: dict[str, int] = {}
    counts: dict[str, int] = {}
    for item in items:
        normalized_gold = {key.casefold(): value for key, value in item.gold_annotations.items()}
        for gold_key, judge_key in ALIGNMENTS.items():
            label = normalized_gold.get(gold_key.casefold())
            if label is None or (gold := _binary_gold(label)) is None:
                continue
            prediction = getattr(item.judge, judge_key)
            if prediction is None:
                continue
            predicted = prediction if isinstance(prediction, bool) else prediction >= 0.5
            counts[gold_key] = counts.get(gold_key, 0) + 1
            correct[gold_key] = correct.get(gold_key, 0) + (predicted == gold)
    return {key: correct[key] / count for key, count in counts.items()}, counts


async def calibrate_mrbench(
    examples: list[MRBenchResponse],
    judge: StructuredTutorJudge,
    *,
    sample_path: Path,
    metadata_path: Path,
    judge_model: str,
) -> CalibrationReport:
    if not examples:
        raise ValueError("calibration requires observed benchmark examples")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(sample_path.read_bytes()).hexdigest()
    if digest != metadata.get("sample_sha256"):
        raise ValueError("benchmark sample hash mismatch")
    items = []
    for example in examples:
        result = await judge.judge(example.judge_input())
        items.append(
            CalibrationItem(
                response_id=example.response_id,
                gold_annotations=example.gold_annotations,
                judge=result,
            )
        )
    rates, counts = agreement(items)
    return CalibrationReport(
        created_at=datetime.now(UTC).isoformat(),
        benchmark_id="MRBench_V1:MathDial:test:sample4",
        sample_sha256=digest,
        source_license=metadata["source_license"],
        underlying_source_license=metadata["underlying_source_license"],
        judge_model=judge_model,
        items=items,
        agreement=rates,
        compared_counts=counts,
    )


def save_calibration(report: CalibrationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def replay_calibration(path: Path, sample_path: Path) -> CalibrationReport:
    report = CalibrationReport.model_validate_json(path.read_text(encoding="utf-8"))
    if hashlib.sha256(sample_path.read_bytes()).hexdigest() != report.sample_sha256:
        raise ValueError("calibration source hash mismatch")
    rates, counts = agreement(report.items)
    if rates != report.agreement or counts != report.compared_counts:
        raise ValueError("calibration summary differs from frozen judgements")
    return report
