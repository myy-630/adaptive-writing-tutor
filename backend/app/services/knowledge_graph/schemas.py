from typing import Literal
from uuid import UUID

from app.domain.enums import EdgeRelation, NodeKind
from app.domain.schemas import DomainModel
from pydantic import Field


class KnowledgeNode(DomainModel):
    id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=160)
    kind: NodeKind
    description: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)


class KnowledgeEdge(DomainModel):
    source_id: str = Field(min_length=1, max_length=160)
    target_id: str = Field(min_length=1, max_length=160)
    relation: EdgeRelation


class NodeOverlay(DomainModel):
    student_id: UUID
    node: KnowledgeNode
    mastery: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_count: int = Field(default=0, ge=0)


class LearningPathStep(DomainModel):
    node: KnowledgeNode
    prerequisite_node_ids: list[str]
    mastery: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["mastered", "ready", "blocked"]
    mastery_state: Literal["learn", "verify", "mastered"] = "learn"
    purpose: Literal["current", "review"] = "current"
    blocked_by_node_ids: list[str] = Field(default_factory=list)
    reason: str


class LearningPath(DomainModel):
    goal_node_id: str
    review_node_ids: list[str] = Field(default_factory=list)
    steps: list[LearningPathStep] = Field(min_length=1)
    next_node_id: str | None
    completed: bool
    mastery_threshold: float = Field(ge=0, le=1)
    exit_threshold: float = Field(default=0.65, ge=0, le=1)
    confidence_threshold: float = Field(ge=0, le=1)


class GraphValidation(DomainModel):
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    isolated_node_ids: list[str]
    prerequisite_cycle_ids: list[str]
    missing_core_node_ids: list[str]
    invalid_relationships: list[str]
