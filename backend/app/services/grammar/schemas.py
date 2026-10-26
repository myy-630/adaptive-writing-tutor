from app.domain.enums import DiagnosticSeverity
from app.domain.schemas import DomainModel
from pydantic import Field, model_validator


class GrammarError(DomainModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    original_expression: str = Field(min_length=1)
    corrected_expression: str
    original_sentence: str = Field(min_length=1)
    corrected_sentence: str = Field(min_length=1)
    primary_category: str = Field(min_length=1)
    knowledge_node_id: str = Field(min_length=1)
    subtype: str = Field(min_length=1)
    original_structure: str = Field(min_length=1)
    corrected_structure: str = Field(min_length=1)
    structure_change: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    severity: DiagnosticSeverity

    @model_validator(mode="after")
    def valid_span(self) -> "GrammarError":
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be after start_offset")
        return self


class GrammarAnalysis(DomainModel):
    input_text: str
    errors: list[GrammarError]
