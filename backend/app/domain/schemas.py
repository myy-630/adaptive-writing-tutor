from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    AbilityDimension,
    EvaluationVerdict,
    EvidenceOutcome,
    PedagogyAction,
    ResourceOrigin,
    ResourceType,
    TeachingMode,
    TeachingStage,
    ToolCallStatus,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Student(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    grade: int = Field(ge=7, le=12)
    learning_goal: str = Field(min_length=1, max_length=500)
    proficiency: str | None = Field(default=None, max_length=100)
    preferences: dict[str, str] = Field(default_factory=dict)


class WritingTask(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    prompt: str = Field(min_length=1)
    genre: str = Field(min_length=1, max_length=100)
    grade: int = Field(ge=7, le=12)
    required_points: list[str] = Field(default_factory=list)


class Draft(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    task_id: UUID
    version: int = Field(ge=1)
    content: str = Field(min_length=1)
    created_at: datetime


class TeachingSession(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    task_id: UUID
    stage: TeachingStage
    mode: TeachingMode
    current_draft_id: UUID | None = None
    started_at: datetime
    updated_at: datetime


class AbilityState(DomainModel):
    dimension: AbilityDimension
    rubric_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=0)
    updated_at: datetime


class KnowledgeState(DomainModel):
    node_id: str = Field(min_length=1, max_length=160)
    mastery: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    path_mastered: bool = False
    evidence_count: int = Field(ge=0)
    occurrence_count: int = Field(ge=0)
    independent_discovery_count: int = Field(ge=0)
    independent_revision_count: int = Field(ge=0)
    hint_level_total: int = Field(ge=0)
    micro_lesson_count: int = Field(ge=0)
    post_lesson_success_count: int = Field(ge=0)
    transfer_success_count: int = Field(ge=0)
    next_essay_recurrence_count: int = Field(ge=0)
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_evidence_at: datetime | None = None


class ErrorRecord(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    session_id: UUID
    category: str = Field(min_length=1, max_length=100)
    knowledge_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    original_text: str = Field(min_length=1)
    count: int = Field(default=1, ge=1)
    observed_at: AwareDatetime


class LearningEvidence(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    session_id: UUID
    knowledge_node_id: str | None = Field(default=None, min_length=1, max_length=160)
    ability_dimension: AbilityDimension | None = None
    outcome: EvidenceOutcome
    independent_discovery: bool = False
    independent_revision: bool = False
    hint_level: int = Field(default=0, ge=0, le=4)
    required_micro_lesson: bool = False
    post_lesson_success: bool = False
    transfer_success: bool = False
    next_essay_recurrence: bool = False
    rubric_score: float | None = Field(default=None, ge=0, le=1)
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def target_required(self) -> "LearningEvidence":
        if self.knowledge_node_id is None and self.ability_dimension is None:
            raise ValueError("knowledge_node_id or ability_dimension is required")
        if self.rubric_score is not None and self.ability_dimension is None:
            raise ValueError("rubric_score requires ability_dimension")
        return self


class ActionScore(DomainModel):
    action: PedagogyAction
    score: float
    reasons: list[str] = Field(min_length=1)


class TeachingDecision(DomainModel):
    action: PedagogyAction
    target_knowledge_node_id: str | None = None
    scaffold_level: int = Field(ge=0, le=4)
    may_reveal_answer: bool
    needs_practice: bool
    practice_type: str | None = None
    pass_condition: str = Field(min_length=1)
    on_failure: PedagogyAction
    rationale: str = Field(min_length=1)
    ranking: list[ActionScore] = Field(default_factory=list)


class ToolCallRecord(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    actor: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]
    status: ToolCallStatus
    duration_ms: int = Field(ge=0)
    error_code: str | None = None
    called_at: datetime


class EvaluationResult(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    verdict: EvaluationVerdict
    violations: list[str] = Field(default_factory=list)
    directive: str | None = None
    evaluated_at: datetime


class RetrievalResource(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    content: str = Field(min_length=1)
    resource_type: ResourceType
    grade: int | None = Field(default=None, ge=7, le=12)
    genre: str | None = None
    knowledge_node_ids: list[str] = Field(default_factory=list)
    ability_dimensions: list[AbilityDimension] = Field(default_factory=list)
    difficulty: float | None = Field(default=None, ge=0, le=1)
    language_level: str | None = None
    source: str = Field(min_length=1)
    dataset_id: str | None = None
    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    origin: ResourceOrigin
    processing_notes: str = Field(min_length=1)


class RetrievalResult(DomainModel):
    resource: RetrievalResource
    rank: int = Field(ge=1)
    score: float
    match_reasons: list[str] = Field(default_factory=list)
