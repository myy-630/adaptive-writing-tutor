from typing import Literal
from uuid import UUID

from app.domain.enums import AbilityDimension, PedagogyAction, TeachingMode, TeachingStage
from app.domain.schemas import DomainModel, TeachingDecision
from app.services.grammar.schemas import GrammarError
from app.services.knowledge_graph.schemas import LearningPath
from app.services.pedagogy.schemas import PolicyContext
from pydantic import Field


class PlannerPlan(DomainModel):
    stage: TeachingStage
    next_stage: TeachingStage | None
    mode: TeachingMode
    target_knowledge_node_id: str | None = None
    long_term_priority_node_id: str | None = None
    target_ability_dimension: AbilityDimension | None = None
    prerequisite_node_id: str | None = None
    learning_path: LearningPath | None = None
    next_transfer_task_id: UUID | None = None
    scaffold_adjustment: Literal["increase", "decrease", "hold"]
    rationale: str = Field(min_length=1)


class TeachingRequest(DomainModel):
    session_id: UUID
    student_id: UUID
    plan: PlannerPlan
    decision: TeachingDecision
    policy_context: PolicyContext
    draft_text: str = Field(min_length=1)
    issue: GrammarError | None = None
    revision_directive: str | None = None
    transfer_prompt: str | None = None


class TeachingText(DomainModel):
    text: str = Field(min_length=1)
    used_resource_ids: list[UUID] = Field(default_factory=list)


class TeachingTurn(DomainModel):
    session_id: UUID
    stage: TeachingStage
    mode: TeachingMode
    action: PedagogyAction
    target_knowledge_node_id: str | None
    text: str | None = Field(default=None, min_length=1)
    used_resource_ids: list[UUID] = Field(default_factory=list)


class EvaluatorJudgement(DomainModel):
    accurate_to_issue: bool
    scaffold_too_strong: bool
    scaffold_too_weak: bool
    actionable_next_step: bool
    stage_appropriate: bool
    ghostwriting: bool
    rationale: str = Field(min_length=1)
