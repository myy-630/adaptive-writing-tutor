from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_values
from app.domain.enums import EdgeRelation, NodeKind


class KnowledgeNodeRecord(Base):
    __tablename__ = "kg_nodes"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[NodeKind] = mapped_column(
        Enum(NodeKind, native_enum=False, create_constraint=True, values_callable=enum_values),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)


class KnowledgeEdgeRecord(Base):
    __tablename__ = "kg_edges"

    source_id: Mapped[str] = mapped_column(String(160), ForeignKey("kg_nodes.id"), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(160), ForeignKey("kg_nodes.id"), primary_key=True)
    relation: Mapped[EdgeRelation] = mapped_column(
        Enum(EdgeRelation, native_enum=False, create_constraint=True, values_callable=enum_values),
        primary_key=True,
    )
