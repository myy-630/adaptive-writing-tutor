"""Measure local retrieval setup and search before considering a result cache."""

import argparse
import json
from statistics import median
from time import perf_counter

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.runtime import RetrievalRuntime
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.store import ResourceStore


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="past tense yesterday")
    parser.add_argument("--knowledge-node", default="simple_past")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    options = parser.parse_args()
    if options.iterations < 3:
        parser.error("--iterations must be at least 3")
    query = RetrievalQuery(
        text=options.query,
        knowledge_node_id=options.knowledge_node,
        top_k=options.top_k,
    )
    settings = Settings()  # type: ignore[call-arg]
    engine = create_database_engine(settings)
    try:
        store = ResourceStore(create_session_factory(engine))
        baseline_loads = []
        for _ in range(min(options.iterations, 5)):
            retriever = HybridRetriever(store, settings)
            started = perf_counter()
            retriever.load_index()
            baseline_loads.append(_elapsed_ms(started))

        runtime = RetrievalRuntime(store, settings)
        started = perf_counter()
        shared = runtime.current()
        startup_ms = _elapsed_ms(started)
        version_checks = []
        searches = []
        for _ in range(options.iterations):
            started = perf_counter()
            current = runtime.current()
            version_checks.append(_elapsed_ms(started))
            assert current is shared
            started = perf_counter()
            current.search(query)
            searches.append(_elapsed_ms(started))
        print(
            json.dumps(
                {
                    "corpus_count": len(shared.resources),
                    "index_version": runtime.loaded_version,
                    "iterations": options.iterations,
                    "baseline_load_ms_median": round(median(baseline_loads), 3),
                    "baseline_load_ms_range": [
                        round(min(baseline_loads), 3),
                        round(max(baseline_loads), 3),
                    ],
                    "startup_load_ms": round(startup_ms, 3),
                    "version_check_ms_median": round(median(version_checks), 3),
                    "search_ms_median": round(median(searches), 3),
                    "search_ms_max": round(max(searches), 3),
                },
                ensure_ascii=False,
            )
        )
        runtime.close()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
