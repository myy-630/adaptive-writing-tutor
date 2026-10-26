import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.services.evaluation.rules import RULESET_VERSION, RuleEvaluator
from app.services.evaluation.schemas import (
    EvaluationCase,
    EvaluationConfig,
    EvaluationReport,
    JudgedRecord,
    MetricSummary,
    VariantName,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def resolve_dataset_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def config_hash(config: EvaluationConfig) -> str:
    payload = config.model_dump(mode="json")
    if not config.variant_settings:
        payload.pop("variant_settings")
    return hashlib.sha256(_canonical(payload)).hexdigest()


def summarize(records: list[JudgedRecord]) -> dict[VariantName, MetricSummary]:
    grouped: dict[VariantName, list[JudgedRecord]] = defaultdict(list)
    for record in records:
        grouped[record.response.variant].append(record)
    summaries: dict[VariantName, MetricSummary] = {}
    for variant, items in grouped.items():
        findings = [finding for item in items for finding in item.rules if finding.applicable]
        judged = [item.judge for item in items if item.judge is not None]
        means: dict[str, float] = {}
        for field in (
            "problem_identification",
            "problem_location",
            "pedagogy_match",
            "actionability",
            "scaffold_strength",
            "mode_compliance",
            "coherence",
        ):
            values = [value for judge in judged if (value := getattr(judge, field)) is not None]
            if values:
                means[field] = sum(values) / len(values)
        failures: dict[str, int] = {}
        for finding in findings:
            if not finding.passed:
                failures[finding.code] = failures.get(finding.code, 0) + 1
        summaries[variant] = MetricSummary(
            count=len(items),
            rule_pass_rate=(sum(item.passed for item in findings) / len(findings))
            if findings
            else None,
            rule_violation_counts=failures,
            judge_mean=means,
            judge_answer_exposure_rate=(
                sum(judge.answer_exposure for judge in judged) / len(judged) if judged else None
            ),
        )
    return summaries


def build_report(
    config: EvaluationConfig,
    records: list[JudgedRecord],
    *,
    parent_report_sha256: str | None = None,
) -> EvaluationReport:
    if not records:
        raise ValueError("evaluation report requires observed records")
    unexpected = {record.response.variant for record in records} - set(config.variants)
    if unexpected:
        raise ValueError(f"records include variants absent from config: {unexpected}")
    dataset_bytes = resolve_dataset_path(config.dataset_path).read_bytes()
    actual_dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()
    if actual_dataset_hash != config.dataset_sha256:
        raise ValueError("dataset file changed after configuration")
    return EvaluationReport(
        created_at=datetime.now(UTC).isoformat(),
        config=config,
        config_sha256=config_hash(config),
        parent_report_sha256=parent_report_sha256,
        records=records,
        summaries=summarize(records),
    )


def save_report(report: EvaluationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def replay_report(path: Path) -> EvaluationReport:
    report = EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
    if report.config_sha256 != config_hash(report.config):
        raise ValueError("evaluation configuration hash mismatch")
    if (
        report.config.dataset_sha256
        != hashlib.sha256(resolve_dataset_path(report.config.dataset_path).read_bytes()).hexdigest()
    ):
        raise ValueError("evaluation dataset hash mismatch")
    if report.summaries != summarize(report.records):
        raise ValueError("evaluation summary differs from frozen records")
    return report


def rescore_frozen_report(path: Path, cases: list[EvaluationCase]) -> EvaluationReport:
    original = replay_report(path)
    indexed = {case.id: case for case in cases}
    if len(indexed) != len(cases):
        raise ValueError("evaluation case IDs must be unique")
    rules = RuleEvaluator()
    updated = []
    for item in original.records:
        case = indexed.get(item.response.case_id)
        if case is None:
            raise ValueError(f"missing evaluation case: {item.response.case_id}")
        updated.append(
            JudgedRecord(
                response=item.response,
                rules=rules.evaluate(case, item.response),
                judge=item.judge,
            )
        )
    config = original.config.model_copy(update={"ruleset_version": RULESET_VERSION})
    return build_report(
        config,
        updated,
        parent_report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
