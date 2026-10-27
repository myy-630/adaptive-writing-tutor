"""Redis cache-aside for public retrieval results; no student state or model replies."""

import hashlib
import json
import logging
from threading import Lock
from time import monotonic

from app.core.config import Settings
from app.domain.enums import ResourceType
from app.domain.schemas import RetrievalResult
from app.services.retrieval.schemas import RetrievalQuery
from pydantic import TypeAdapter, ValidationError
from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)
RESULTS_ADAPTER = TypeAdapter(list[RetrievalResult])
PRIVATE_RESOURCE_TYPES = frozenset({ResourceType.STUDENT_ESSAY, ResourceType.HUMAN_CORRECTION})


class RedisRetrievalCache:
    """Cache complete search results under a query and immutable index version."""

    def __init__(self, settings: Settings, client: Redis | None = None) -> None:
        self._client = (
            client
            if client is not None
            else Redis.from_url(
                settings.redis_url.get_secret_value(),
                decode_responses=False,
                socket_connect_timeout=settings.retrieval_cache_timeout_seconds,
                socket_timeout=settings.retrieval_cache_timeout_seconds,
            )
        )
        self._ttl = settings.retrieval_cache_ttl_seconds
        self._rrf_k = settings.rrf_k
        self._retry_seconds = settings.retrieval_cache_retry_seconds
        self._offline_until = 0.0
        self._lock = Lock()

    def key(self, index_version: str, query: RetrievalQuery) -> str:
        """Hash the full query so Redis keys do not expose student-entered text."""
        payload = json.dumps(
            {"query": query.model_dump(mode="json"), "rrf_k": self._rrf_k},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"awt:retrieval:v1:{index_version}:{digest}"

    def get(self, index_version: str, query: RetrievalQuery) -> list[RetrievalResult] | None:
        if not self._available():
            return None
        key = self.key(index_version, query)
        try:
            cached = self._client.get(key)
        except RedisError as exc:
            self._mark_unavailable("read", exc)
            return None
        if cached is None:
            return None
        try:
            results = RESULTS_ADAPTER.validate_json(cached)
        except (ValidationError, ValueError, TypeError):
            logger.warning("invalid retrieval cache entry discarded")
            try:
                self._client.delete(key)
            except RedisError as exc:
                self._mark_unavailable("delete", exc)
            return None
        if self._private_results(results):
            logger.warning("private retrieval results found in cache; entry discarded")
            try:
                self._client.delete(key)
            except RedisError as exc:
                self._mark_unavailable("delete", exc)
            return None
        return results

    def put(
        self, index_version: str, query: RetrievalQuery, results: list[RetrievalResult]
    ) -> None:
        if not self._available() or self._private_results(results):
            return
        try:
            self._client.set(
                self.key(index_version, query), RESULTS_ADAPTER.dump_json(results), ex=self._ttl
            )
        except RedisError as exc:
            self._mark_unavailable("write", exc)

    def close(self) -> None:
        try:
            self._client.close()
        except RedisError as exc:
            logger.warning("retrieval cache close failed: %s", type(exc).__name__)

    def _available(self) -> bool:
        with self._lock:
            return monotonic() >= self._offline_until

    def _mark_unavailable(self, operation: str, exc: RedisError) -> None:
        with self._lock:
            if monotonic() >= self._offline_until:
                logger.warning(
                    "retrieval cache %s unavailable; using live search: %s",
                    operation,
                    type(exc).__name__,
                )
            self._offline_until = monotonic() + self._retry_seconds

    @staticmethod
    def _private_results(results: list[RetrievalResult]) -> bool:
        return any(item.resource.resource_type in PRIVATE_RESOURCE_TYPES for item in results)
