from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from app.domain.enums import PedagogyAction, TeachingMode, TeachingStage
from app.domain.schemas import DomainModel
from pydantic import Field, model_validator


class VariantName(StrEnum):
    ORDINARY_LLM = "ordinary_llm"
    FIXED_PROMPT = "fixed_prompt"
    STUDENT_STATE = "student_state"
    PEDAGOGY_POLICY = "pedagogy_policy"
    PEDAGOGY_EVALUATOR = "pedagogy_evaluator"
    FULL_SYSTEM = "full_system"


class VariantConfig(DomainModel):
    name: VariantName
    fixed_prompt: bool
    student_state: bool
    pedagogy_policy: bool
    pedagogy_evaluator: bool
    full_workflow: bool


VARIANTS: dict[VariantName, VariantConfig] = {
    VariantName.ORDINARY_LLM: VariantConfig(
        name=VariantName.ORDINARY_LLM,
        fixed_prompt=False,
        student_state=False,
        pedagogy_policy=False,
        pedagogy_evaluator=False,
        full_workflow=False,
    ),
    VariantName.FIXED_PROMPT: VariantConfig(
        name=VariantName.FIXED_PROMPT,
        fixed_prompt=True,
        student_state=False,
        pedagogy_policy=False,
        pedagogy_evaluator=False,
        full_workflow=False,
    ),
    VariantName.STUDENT_STATE: VariantConfig(
        name=VariantName.STUDENT_STATE,
        fixed_prompt=True,
        student_state=True,
        pedagogy_policy=False,
        pedagogy_evaluator=False,
        full_workflow=False,
    ),
    VariantName.PEDAGOGY_POLICY: VariantConfig(
        name=VariantName.PEDAGOGY_POLICY,
        fixed_prompt=True,
        student_state=True,
        pedagogy_policy=True,
        pedagogy_evaluator=False,
        full_workflow=False,
    ),
    VariantName.PEDAGOGY_EVALUATOR: VariantConfig(
        name=VariantName.PEDAGOGY_EVALUATOR,
        fixed_prompt=True,
        student_state=True,
        pedagogy_policy=True,
        pedagogy_evaluator=True,
        full_workflow=False,
    ),
    VariantName.FULL_SYSTEM: VariantConfig(
        name=VariantName.FULL_SYSTEM,
        fixed_prompt=True,
        student_state=True,
        pedagogy_policy=True,
        pedagogy_evaluator=True,
        full_workflow=True,
    ),
}


class EvaluationCase(DomainModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    grade: int = Field(ge=7, le=12)
    stage: TeachingStage
    mode: TeachingMode
    task_prompt: str = Field(min_length=1)
    task_genre: str = Field(min_length=1)
    required_points: list[str] = Field(min_length=1)
    student_text: str = Field(min_length=1)
    issue_category: str | None = None
    issue_location: str | None = None
    expected_correction: str | None = None
    target_knowledge_node_id: str | None = None
    student_self_check_attempted: bool = False
    student_id: UUID | None = None
    session_id: UUID = Field(default_factory=uuid4)


class ResponseRecord(DomainModel):
    case_id: str
    variant: VariantName
    text: str | None = None
    stage: TeachingStage
    mode: TeachingMode
    action: PedagogyAction | None = None
    tool_calls: list["ObservedToolCall"] = Field(default_factory=list)
    stage_history: list[TeachingStage] = Field(default_factory=list)
    evaluator_verdict: str | None = None
    model_calls: int | None = Field(default=None, ge=0)
    provider_model: str


class ObservedToolCall(DomainModel):
    actor: str
    name: str


class RuleFinding(DomainModel):
    code: str
    applicable: bool = True
    passed: bool
    detail: str


class JudgeInput(DomainModel):
    domain: str = Field(min_length=1)
    context: str = Field(min_length=1)
    tutor_response: str = Field(min_length=1)
    issue: str | None = None
    expected_correction: str | None = None
    stage: str | None = None
    mode: str | None = None
    policy_action: str | None = None


class JudgeScores(DomainModel):
    problem_identification: float | None = Field(default=None, ge=0, le=1)
    problem_location: float | None = Field(default=None, ge=0, le=1)
    answer_exposure: bool
    ghostwriting: bool
    pedagogy_match: float | None = Field(default=None, ge=0, le=1)
    actionability: float = Field(ge=0, le=1)
    scaffold_strength: float | None = Field(default=None, ge=0, le=1)
    mode_compliance: float | None = Field(default=None, ge=0, le=1)
    coherence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class JudgedRecord(DomainModel):
    response: ResponseRecord
    rules: list[RuleFinding]
    judge: JudgeScores | None = None


class EvaluationConfig(DomainModel):
    variants: list[VariantName] = Field(min_length=1)
    variant_settings: dict[VariantName, VariantConfig] = Field(default_factory=dict)
    dataset_id: str = Field(min_length=1)
    dataset_path: Path
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_model: str = Field(min_length=1)
    judge_model: str | None = None
    ruleset_version: str = "3"
    max_regenerations: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def unique_variants(self) -> "EvaluationConfig":
        if len(self.variants) != len(set(self.variants)):
            raise ValueError("variant names must be unique")
        if self.variant_settings and set(self.variant_settings) != set(self.variants):
            raise ValueError("variant settings must match selected variants")
        return self


class MetricSummary(DomainModel):
    count: int = Field(ge=0)
    rule_pass_rate: float | None = Field(default=None, ge=0, le=1)
    rule_violation_counts: dict[str, int] = Field(default_factory=dict)
    judge_mean: dict[str, float] = Field(default_factory=dict)
    judge_answer_exposure_rate: float | None = Field(default=None, ge=0, le=1)


class EvaluationReport(DomainModel):
    run_id: UUID = Field(default_factory=uuid4)
    created_at: str
    config: EvaluationConfig
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    records: list[JudgedRecord]
    summaries: dict[VariantName, MetricSummary]
