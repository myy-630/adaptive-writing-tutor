from typing import Literal, TypedDict
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from app.domain.enums import EvaluationVerdict, PedagogyAction, TeachingMode, TeachingStage
from app.domain.schemas import DomainModel, WritingTask
from app.services.knowledge_graph.schemas import LearningPath, NodeOverlay
from app.services.student_state.schemas import StudentStateSnapshot
from app.workflows.draft_comparison import DraftComparison


class PromptAnalysisAnswer(DomainModel):
    audience: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    required_points: list[str] = Field(min_length=1)
    tense: str = Field(min_length=1)
    person: str = Field(min_length=1)
    constraints: str = Field(min_length=1)


class StructurePlan(DomainModel):
    opening: str = Field(min_length=1)
    body: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)


class ContentPlan(DomainModel):
    viewpoint: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    example: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    result_or_feeling: str = Field(min_length=1)


class WorkflowSubmission(DomainModel):
    request_id: UUID = Field(default_factory=uuid4)
    kind: Literal["start", "response", "finalize"]
    text: str | None = Field(default=None, min_length=1)
    message: str | None = Field(default=None, min_length=1)
    prompt_analysis: PromptAnalysisAnswer | None = None
    structure_plan: StructurePlan | None = None
    content_plan: ContentPlan | None = None
    relation_explanation: str | None = Field(default=None, min_length=1)
    transfer_response: str | None = Field(default=None, min_length=1)
    independent_revision: bool = False

    @model_validator(mode="after")
    def valid_kind(self) -> "WorkflowSubmission":
        if self.kind == "start" and any(
            (self.text, self.prompt_analysis, self.structure_plan, self.content_plan)
        ):
            raise ValueError("start cannot contain a student response")
        if self.kind == "finalize" and self.text is not None:
            raise ValueError("finalize cannot contain draft text")
        return self


class WorkflowResult(DomainModel):
    request_id: UUID
    session_id: UUID
    stage: TeachingStage
    mode: TeachingMode
    stage_passed: bool
    completed: bool
    feedback: str
    teaching_text: str | None = None
    evaluation_verdict: EvaluationVerdict | None = None
    transfer_prompt: str | None = None
    final_comparison: DraftComparison | None = None
    action: PedagogyAction | None = None
    target_knowledge_node_id: str | None = None
    retries: int = Field(ge=0)
    blocked: bool = False


class SessionCreate(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    task_id: UUID
    mode: TeachingMode = TeachingMode.GUIDED


class WorkflowTurnInput(DomainModel):
    student_id: UUID
    submission: WorkflowSubmission


class SessionView(DomainModel):
    id: UUID
    student_id: UUID
    task: WritingTask
    stage: TeachingStage
    mode: TeachingMode
    current_draft: str | None
    completed: bool
    student_state: StudentStateSnapshot
    last_result: WorkflowResult | None = None
    grammar_hints: list["GrammarHint"] = Field(default_factory=list)
    knowledge_paths: list["KnowledgePath"] = Field(default_factory=list)


class GrammarHint(DomainModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    original_expression: str
    category: str
    knowledge_node_id: str


class KnowledgePath(DomainModel):
    target: NodeOverlay
    prerequisites: list[NodeOverlay]
    learning_path: LearningPath | None = None


class SharedState(TypedDict, total=False):
    request_id: str
    session_id: str
    student_id: str
    submission: dict[str, object]
    stage: str
    mode: str
    task_prompt: str
    task_genre: str
    current_draft: str
    first_draft: str
    stage_passed: bool
    completed: bool
    feedback: str
    plan: dict[str, object]
    diagnosis: dict[str, object]
    policy_context: dict[str, object]
    decision: dict[str, object]
    teaching_turn: dict[str, object]
    evaluation: dict[str, object]
    retry_count: int
    blocked: bool
    result: dict[str, object]
    final_comparison: dict[str, object]
