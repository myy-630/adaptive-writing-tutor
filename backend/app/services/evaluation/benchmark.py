import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from app.domain.schemas import DomainModel
from app.services.evaluation.schemas import JudgeInput
from pydantic import Field


class MRBenchResponse(DomainModel):
    conversation_id: str
    response_id: str
    context: str = Field(min_length=1)
    tutor_response: str = Field(min_length=1)
    reference_solution: str | None
    gold_annotations: dict[str, str]
    source: str = "MRBench_V1:MathDial"

    def judge_input(self) -> JudgeInput:
        return JudgeInput(
            domain="math tutoring",
            context=self.context,
            tutor_response=self.tutor_response,
            issue="Student's mathematical misconception in the dialogue",
            expected_correction=self.reference_solution,
            stage="feedback after a student error",
        )


def load_mrbench_mathdial(
    data_path: Path, metadata_path: Path, *, tutor_names: set[str] | None = None
) -> list[MRBenchResponse]:
    """Load the licensed local MathDial subset, retaining gold provenance."""
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if digest != metadata.get("sample_sha256"):
        raise ValueError("MRBench sample hash differs from its provenance manifest")
    if metadata.get("source_license") != "CC BY-SA 4.0":
        raise ValueError("MRBench sample license metadata is missing")

    def rows() -> Iterator[MRBenchResponse]:
        for line_number, line in enumerate(data_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            if raw.get("Data") != "MathDial" or raw.get("Split") != "test":
                raise ValueError(f"Unexpected MRBench provenance at line {line_number}")
            responses = raw.get("anno_llm_responses")
            if not isinstance(responses, dict) or not responses:
                raise ValueError(f"Missing MRBench responses at line {line_number}")
            for tutor_name, value in responses.items():
                if tutor_names is not None and tutor_name not in tutor_names:
                    continue
                yield MRBenchResponse(
                    conversation_id=str(raw["conversation_id"]),
                    response_id=f"{raw['conversation_id']}:{tutor_name}",
                    context=str(raw["conversation_history"]),
                    tutor_response=str(value["response"]),
                    reference_solution=(
                        str(raw["Ground_Truth_Solution"])
                        if raw.get("Ground_Truth_Solution") not in {None, "Not Available"}
                        else None
                    ),
                    gold_annotations={
                        str(key): str(item) for key, item in value["annotation"].items()
                    },
                )

    return list(rows())
