import asyncio
from uuid import uuid4

import pytest
from app.api.main import create_app
from app.core.config import Settings
from app.core.errors import ProviderUnavailable
from app.core.logging import configure_logging
from app.core.provider import ModelProvider, UnconfiguredModelProvider
from app.db.session import create_database_engine, create_session_factory
from app.domain.enums import TeachingMode, TeachingStage
from app.models import DraftRecord, StudentRecord, TeachingSessionRecord, WritingTaskRecord
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError


class ProviderResponse(BaseModel):
    value: str


class FakeProvider:
    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type[ProviderResponse]
    ) -> ProviderResponse:
        return response_type(value=f"{system_prompt}:{user_prompt}")


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test@localhost/test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.database_url.endswith("/test")
    assert settings.log_level == "DEBUG"
    monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")
    with pytest.raises(ValidationError):
        Settings()


def test_logging_is_configurable() -> None:
    import logging

    configure_logging("DEBUG")
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_model_provider_can_be_replaced() -> None:
    provider: ModelProvider = FakeProvider()
    result = asyncio.run(
        provider.generate_structured(
            system_prompt="system", user_prompt="user", response_type=ProviderResponse
        )
    )
    assert result.value == "system:user"
    with pytest.raises(ProviderUnavailable):
        asyncio.run(
            UnconfiguredModelProvider().generate_structured(
                system_prompt="system", user_prompt="user", response_type=ProviderResponse
            )
        )


def test_api_starts_and_reports_postgres_readiness() -> None:
    with TestClient(create_app(settings=Settings(), provider=FakeProvider())) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ok"}
        assert client.app.state.model_provider.__class__ is FakeProvider


def test_unavailable_database_has_explicit_response() -> None:
    settings = Settings(database_url="postgresql+psycopg://myy@127.0.0.1:1/missing")
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}


def test_migration_schema_and_real_database_roundtrip() -> None:
    engine = create_database_engine(Settings())
    tables = set(inspect(engine).get_table_names())
    assert {"alembic_version", "students", "writing_tasks", "drafts", "teaching_sessions"} <= tables
    factory = create_session_factory(engine)
    student_id, task_id, draft_id, session_id = (uuid4() for _ in range(4))
    with factory.begin() as db:
        db.add(StudentRecord(id=student_id, grade=9, learning_goal="Write better essays"))
        db.add(
            WritingTaskRecord(
                id=task_id, prompt="Describe your school", genre="description", grade=9
            )
        )
        db.flush()
        db.add(
            DraftRecord(
                id=draft_id,
                student_id=student_id,
                task_id=task_id,
                version=1,
                content="My school is nice.",
            )
        )
        db.flush()
        db.add(
            TeachingSessionRecord(
                id=session_id,
                student_id=student_id,
                task_id=task_id,
                stage=TeachingStage.PROMPT_ANALYSIS,
                mode=TeachingMode.GUIDED,
                current_draft_id=draft_id,
            )
        )
    with factory() as db:
        saved = db.scalar(
            select(TeachingSessionRecord).where(TeachingSessionRecord.id == session_id)
        )
        assert saved is not None
        assert saved.stage == TeachingStage.PROMPT_ANALYSIS
        assert saved.current_draft_id == draft_id
        assert (
            db.scalar(select(DraftRecord.content).where(DraftRecord.id == draft_id))
            == "My school is nice."
        )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()


def test_database_rejects_invalid_grade() -> None:
    engine = create_database_engine(Settings())
    factory = create_session_factory(engine)
    with pytest.raises(IntegrityError):
        with factory.begin() as db:
            db.add(StudentRecord(id=uuid4(), grade=13, learning_goal="Invalid"))
    engine.dispose()
