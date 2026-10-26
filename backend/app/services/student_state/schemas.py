from uuid import UUID

from app.domain.enums import TeachingMode, TeachingStage
from app.domain.schemas import AbilityState, DomainModel, KnowledgeState, Student
from pydantic import Field


class ErrorPattern(DomainModel):
    category: str
    knowledge_node_id: str | None
    count: int = Field(ge=0)


class PromptDependency(DomainModel):
    evidence_count: int = Field(ge=0)
    average_hint_level: float = Field(ge=0, le=4)
    independent_revision_count: int = Field(ge=0)
    micro_lesson_count: int = Field(ge=0)
    post_lesson_success_count: int = Field(ge=0)
    transfer_success_count: int = Field(ge=0)


class InteractionState(DomainModel):
    session_id: UUID | None
    task_id: UUID | None
    stage: TeachingStage | None
    mode: TeachingMode | None
    consecutive_failures: int = Field(ge=0)
    current_hint_level: int = Field(ge=0, le=4)
    confusion_score: float = Field(ge=0, le=1)


class StudentStateSnapshot(DomainModel):
    student: Student
    abilities: list[AbilityState]
    knowledge: list[KnowledgeState]
    error_patterns: list[ErrorPattern]
    prompt_dependency: PromptDependency
    interaction: InteractionState
    recent_knowledge_failures: dict[str, int] = Field(default_factory=dict)
