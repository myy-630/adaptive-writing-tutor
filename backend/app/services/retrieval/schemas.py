from app.domain.enums import AbilityDimension, ResourceType
from app.domain.schemas import DomainModel
from pydantic import Field


class RetrievalQuery(DomainModel):
    text: str
    top_k: int = Field(default=5, ge=1, le=50)
    resource_types: list[ResourceType] | None = None
    grade: int | None = Field(default=None, ge=7, le=12)
    genre: str | None = None
    knowledge_node_id: str | None = None
    ability_dimension: AbilityDimension | None = None
    max_difficulty: float | None = Field(default=None, ge=0, le=1)
    language_level: str | None = None


class QueryRewrite(DomainModel):
    original: str
    normalized: str
    bm25_terms: list[str]


class IndexMetadata(DomainModel):
    corpus_sha256: str
    model_name: str
    fastembed_version: str
    resource_count: int = Field(ge=0)
    embedding_dimension: int = Field(gt=0)
