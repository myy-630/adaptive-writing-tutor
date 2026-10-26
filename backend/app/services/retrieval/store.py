from pathlib import Path
from uuid import UUID

from app.core.errors import DomainError
from app.domain.enums import AbilityDimension, ResourceOrigin
from app.domain.schemas import RetrievalResource
from app.models.retrieval import RetrievalResourceRecord
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker


class ResourceStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def import_jsonl(self, path: Path) -> int:
        resources = [
            RetrievalResource.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return self.add_resources(resources)

    def add_resources(self, resources: list[RetrievalResource]) -> int:
        inserted = 0
        with self.sessions.begin() as db:
            for resource in resources:
                if resource.origin == ResourceOrigin.PUBLIC and (
                    not resource.dataset_id or not resource.source.startswith("https://")
                ):
                    raise DomainError(
                        "invalid_public_source", "Public resources need dataset ID and source URL"
                    )
                values = resource.model_dump()
                values["ability_dimensions"] = [item.value for item in resource.ability_dimensions]
                statement = (
                    insert(RetrievalResourceRecord)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["id"])
                    .returning(RetrievalResourceRecord.id)
                )
                if db.execute(statement).scalar_one_or_none() is not None:
                    inserted += 1
                    continue
                existing = db.get(RetrievalResourceRecord, resource.id)
                if existing is None or any(
                    getattr(existing, key) != value for key, value in values.items()
                ):
                    raise DomainError("resource_conflict", "Resource ID has different content", 409)
        return inserted

    def list_resources(self) -> list[RetrievalResource]:
        with self.sessions() as db:
            rows = db.scalars(
                select(RetrievalResourceRecord).order_by(RetrievalResourceRecord.id)
            ).all()
            return [self._to_schema(row) for row in rows]

    def get_resource(self, resource_id: UUID) -> RetrievalResource | None:
        with self.sessions() as db:
            row = db.get(RetrievalResourceRecord, resource_id)
            return self._to_schema(row) if row else None

    @staticmethod
    def _to_schema(row: RetrievalResourceRecord) -> RetrievalResource:
        return RetrievalResource(
            id=row.id,
            content=row.content,
            resource_type=row.resource_type,
            grade=row.grade,
            genre=row.genre,
            knowledge_node_ids=row.knowledge_node_ids,
            ability_dimensions=[AbilityDimension(item) for item in row.ability_dimensions],
            difficulty=row.difficulty,
            language_level=row.language_level,
            source=row.source,
            dataset_id=row.dataset_id,
            license=row.license,
            attribution=row.attribution,
            origin=row.origin,
            processing_notes=row.processing_notes,
        )
