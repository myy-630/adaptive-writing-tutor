import argparse
import json
from pathlib import Path

from app.services.evaluation.report import (
    rescore_frozen_report,
    resolve_dataset_path,
    save_report,
)
from app.services.evaluation.schemas import EvaluationCase


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply current deterministic rules to frozen model outputs"
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.report.read_text(encoding="utf-8"))
    data_path = resolve_dataset_path(Path(raw["config"]["dataset_path"]))
    cases = [
        EvaluationCase.model_validate(json.loads(line))
        for line in data_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = rescore_frozen_report(args.report, cases)
    output = args.output or args.report.with_name(f"rescore-{report.run_id}.json")
    save_report(report, output)
    print(
        json.dumps(
            {
                "report": str(output),
                "ruleset_version": report.config.ruleset_version,
                "parent_report_sha256": report.parent_report_sha256,
                "summaries": {
                    key.value: value.model_dump(mode="json")
                    for key, value in report.summaries.items()
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
