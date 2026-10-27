import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.workflow import router as workflow_router
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.core.provider import ModelProvider, UnconfiguredModelProvider
from app.core.responses_provider import ResponsesModelProvider, configured_responses_provider
from app.db.session import create_database_engine, create_session_factory
from app.services.retrieval.runtime import RetrievalRuntime
from app.services.retrieval.store import ResourceStore

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, provider: ModelProvider | None = None) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(settings)
        app.state.engine = engine
        app.state.sessions = create_session_factory(engine)
        app.state.settings = settings
        selected_provider = (
            provider or configured_responses_provider(settings) or UnconfiguredModelProvider()
        )
        app.state.model_provider = selected_provider
        retrieval_runtime = RetrievalRuntime(ResourceStore(app.state.sessions), settings)
        app.state.retrieval_runtime = retrieval_runtime
        try:
            retrieval_runtime.current()
            yield
        finally:
            retrieval_runtime.close()
            if isinstance(selected_provider, ResponsesModelProvider):
                await selected_provider.aclose()
            engine.dispose()

    app = FastAPI(title="Adaptive Writing Tutor", version="0.1.0", lifespan=lifespan)
    app.include_router(workflow_router)

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(request: Request) -> JSONResponse:
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.exception("database readiness check failed")
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(content={"status": "ok"})

    return app


app = create_app()
