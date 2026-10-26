from uuid import UUID

from sqlalchemy import Enum, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_values
from app.domain.enums import ResourceOrigin, ResourceType


class RetrievalResourceRecord(Base):
    __tablename__ = "retrieval_resources"
    __table_args__ = (UniqueConstraint("dataset_id", name="uq_resource_dataset_id"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, native_enum=False, create_constraint=True, values_callable=enum_values),
        nullable=False,
    )
    grade: Mapped[int | None] = mapped_column(Integer)
    genre: Mapped[str | None] = mapped_column(String(100))
    knowledge_node_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    ability_dimensions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    difficulty: Mapped[float | None] = mapped_column(Float)
    language_level: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(String(200))
    license: Mapped[str] = mapped_column(String(200), nullable=False)
    attribution: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[ResourceOrigin] = mapped_column(
        Enum(
            ResourceOrigin, native_enum=False, create_constraint=True, values_callable=enum_values
        ),
        nullable=False,
    )
    processing_notes: Mapped[str] = mapped_column(Text, nullable=False)
