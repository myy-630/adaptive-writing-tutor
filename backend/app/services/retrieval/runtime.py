"""Process-local, versioned retrieval snapshot for FastAPI lifespan."""

import logging
from pathlib import Path
from threading import Lock

from app.core.config import Settings
from app.core.errors import DomainError
from app.services.retrieval.cache import RedisRetrievalCache
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.schemas import IndexMetadata
from app.services.retrieval.store import ResourceStore
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class RetrievalRuntime:
    """Load one immutable retriever per index version, swapping complete snapshots only."""

    def __init__(
        self,
        store: ResourceStore,
        settings: Settings,
        cache: RedisRetrievalCache | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self._lock = Lock()
        self.cache = (
            (cache if cache is not None else RedisRetrievalCache(settings))
            if settings.retrieval_cache_enabled
            else None
        )
        self._retriever = HybridRetriever(store, settings, self.cache)
        self._checked_version: str | None = None
        self._initialized = False

    @property
    def loaded_version(self) -> str | None:
        return self._retriever.metadata.index_version if self._retriever.metadata else None

    def current(self) -> HybridRetriever:
        """Check a tiny manifest; rebuild the in-memory snapshot only on version change."""
        with self._lock:
            try:
                published_version = self._published_version()
            except DomainError as exc:
                logger.warning("retrieval index metadata unavailable: %s", exc.code)
                self._unload()
                self._initialized = False
                self._checked_version = None
                return self._retriever
            if self._initialized and published_version == self._checked_version:
                return self._retriever
            if published_version is None:
                logger.warning(
                    "retrieval index unavailable; tool fallback will be used: index_missing"
                )
                self._unload()
                self._checked_version = None
                self._initialized = True
                return self._retriever

            candidate = HybridRetriever(self.store, self.settings, self.cache)
            try:
                metadata = candidate.load_index()
            except DomainError as exc:
                if exc.code == "index_version_mismatch":
                    logger.warning(
                        "retrieval index publication in progress; keeping prior snapshot"
                    )
                    return self._retriever
                logger.warning(
                    "retrieval index unavailable; tool fallback will be used: %s", exc.code
                )
                self._unload()
                self._checked_version = published_version
                self._initialized = True
                return self._retriever
            except SQLAlchemyError:
                logger.exception("retrieval corpus unavailable; retrying on the next request")
                return self._retriever

            if metadata.index_version != published_version:
                logger.warning("retrieval index version changed during load; retrying next request")
                return self._retriever
            self._retriever = candidate
            self._checked_version = published_version
            self._initialized = True
            logger.info(
                "retrieval index loaded: version=%s resources=%d",
                published_version,
                metadata.resource_count,
            )
            return self._retriever

    def close(self) -> None:
        with self._lock:
            self._unload()
            self._initialized = False
            self._checked_version = None
            if self.cache is not None:
                self.cache.close()

    def _unload(self) -> None:
        self._retriever = HybridRetriever(self.store, self.settings, self.cache)

    def _published_version(self) -> str | None:
        path = self.settings.retrieval_index_path
        meta_path = Path(path).with_suffix(".json")
        if not path.is_file() or not meta_path.is_file():
            return None
        try:
            metadata = IndexMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise DomainError("index_corrupt", "Retrieval index metadata is invalid", 409) from exc
        return metadata.index_version
