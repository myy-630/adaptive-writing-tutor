from enum import StrEnum

from app.domain.enums import PedagogyAction, TeachingMode, TeachingStage
from app.domain.schemas import DomainModel
from app.services.student_state.schemas import StudentStateSnapshot
from pydantic import Field


class IntentLabel(StrEnum):
    ATTEMPT = "attempt"
    REQUEST_HELP = "request_help"
    REQUEST_ANSWER = "request_answer"
    EXPRESS_CONFUSION = "express_confusion"
    OTHER = "other"


class StudentIntent(DomainModel):
    primary: IntentLabel
    secondary: list[IntentLabel] = Field(default_factory=list)
    confusion: float = Field(default=0, ge=0, le=1)
    frustration: float = Field(default=0, ge=0, le=1)
    requests_direct_answer: bool = False


class PolicyContext(DomainModel):
    stage: TeachingStage
    issue_type: str = Field(min_length=1)
    target_knowledge_node_id: str | None = None
    mastery: float = Field(ge=0, le=1)
    mastery_confidence: float = Field(ge=0, le=1)
    historical_error_count: int = Field(ge=0)
    recent_error_recurrence: bool
    last_action: PedagogyAction | None = None
    last_action_succeeded: bool | None = None
    mode: TeachingMode
    intent: StudentIntent
    consecutive_failures: int = Field(ge=0)
    average_hint_level: float = Field(ge=0, le=4)
    confusion_score: float = Field(ge=0, le=1)

    @classmethod
    def from_student_state(
        cls,
        state: StudentStateSnapshot,
        *,
        stage: TeachingStage,
        mode: TeachingMode,
        issue_type: str,
        target_knowledge_node_id: str | None,
        intent: StudentIntent,
        recent_error_recurrence: bool = False,
        last_action: PedagogyAction | None = None,
        last_action_succeeded: bool | None = None,
    ) -> "PolicyContext":
        knowledge = next(
            (item for item in state.knowledge if item.node_id == target_knowledge_node_id),
            None,
        )
        history = sum(
            item.count
            for item in state.error_patterns
            if item.knowledge_node_id == target_knowledge_node_id
        )
        return cls(
            stage=stage,
            issue_type=issue_type,
            target_knowledge_node_id=target_knowledge_node_id,
            mastery=knowledge.mastery if knowledge else 0.5,
            mastery_confidence=knowledge.confidence if knowledge else 0,
            historical_error_count=history,
            recent_error_recurrence=recent_error_recurrence,
            last_action=last_action,
            last_action_succeeded=last_action_succeeded,
            mode=mode,
            intent=intent,
            consecutive_failures=state.interaction.consecutive_failures,
            average_hint_level=state.prompt_dependency.average_hint_level,
            confusion_score=max(state.interaction.confusion_score, intent.confusion),
        )
