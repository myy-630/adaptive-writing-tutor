import argparse
import json
from pathlib import Path

from app.services.evaluation.calibration import replay_calibration
from app.services.evaluation.report import replay_report

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute metrics from frozen evaluation outputs")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    if "benchmark_id" in payload:
        sample = ROOT / "data/processed/mrbench_mathdial_v1_sample.jsonl"
        result = replay_calibration(args.report, sample)
        print(f"verified MRBench calibration: {len(result.items)} responses")
    else:
        result = replay_report(args.report)
        print(f"verified writing evaluation: {len(result.records)} responses")


if __name__ == "__main__":
    main()
