"""Exercise Redis cache hits, TTL and index-version misses against a real Redis server."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.retrieval.cache import RedisRetrievalCache
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.runtime import RetrievalRuntime
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.store import ResourceStore
from redis import Redis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="school")
    options = parser.parse_args()
    with TemporaryDirectory(prefix="awt-retrieval-cache-") as directory:
        settings = Settings(  # type: ignore[call-arg]
            retrieval_index_path=Path(directory) / "resources.npz"
        )
        client = Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=False)
        client.ping()
        engine = create_database_engine(settings)
        runtime: RetrievalRuntime | None = None
        keys: list[str] = []
        try:
            store = ResourceStore(create_session_factory(engine))
            builder = HybridRetriever(store, settings)
            first_version = builder.build_index().index_version
            runtime = RetrievalRuntime(store, settings)
            query = RetrievalQuery(text=options.query, top_k=3)
            first = runtime.current().search(query)
            assert runtime.cache is not None
            old_key = runtime.cache.key(first_version, query)
            keys.append(old_key)
            assert client.ttl(old_key) > 0
            assert runtime.current().search(query) == first
            second_client = RedisRetrievalCache(settings)
            cross_client_hit = second_client.get(first_version, query) == first
            second_client.close()
            assert cross_client_hit

            second_version = builder.build_index().index_version
            assert second_version != first_version
            new_key = runtime.cache.key(second_version, query)
            keys.append(new_key)
            assert client.exists(new_key) == 0
            second = runtime.current().search(query)
            assert second == first
            assert client.ttl(new_key) > 0
            print(
                json.dumps(
                    {
                        "resource_count": len(runtime.current().resources),
                        "cache_hit": runtime.cache.get(second_version, query) == second,
                        "cross_client_hit": cross_client_hit,
                        "version_change_missed_old_cache": old_key != new_key,
                        "ttl_seconds": client.ttl(new_key),
                    }
                )
            )
        finally:
            if keys:
                client.delete(*keys)
            if runtime is not None:
                runtime.close()
            engine.dispose()
            client.close()


if __name__ == "__main__":
    main()
