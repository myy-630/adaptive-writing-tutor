import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import fakeredis
import pytest
from app.agents.tool_runtime import build_agent_tools
from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import create_database_engine, create_session_factory
from app.domain.enums import AbilityDimension, ResourceOrigin, ResourceType, ToolCallStatus
from app.domain.schemas import RetrievalResource, RetrievalResult
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.retrieval.cache import RedisRetrievalCache
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.runtime import RetrievalRuntime
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.store import ResourceStore
from app.services.student_state.manager import StudentStateManager


def _result() -> RetrievalResult:
    return RetrievalResult(
        resource=RetrievalResource(
            id=UUID("00000000-0000-0000-0000-000000000123"),
            content="My school day begins with English class.",
            resource_type=ResourceType.BASIC_SENTENCE,
            source="https://example.org/public-sentence",
            license="CC BY 2.0",
            attribution="Example Author",
            origin=ResourceOrigin.PUBLIC,
            processing_notes="Cache schema test",
        ),
        rank=1,
        score=0.9,
        match_reasons=["dense", "rrf"],
    )


def test_cache_key_covers_full_query_filters_top_k_and_index_version() -> None:
    cache = RedisRetrievalCache(Settings(), fakeredis.FakeRedis())
    base = RetrievalQuery(text="private student query", top_k=3)
    key = cache.key("version-one", base)
    changes = (
        {"text": "other query"},
        {"top_k": 5},
        {"resource_types": [ResourceType.WRITING_PROMPT]},
        {"grade": 9},
        {"genre": "narrative"},
        {"knowledge_node_id": "simple_past"},
        {"ability_dimension": AbilityDimension.GRAMMAR},
        {"max_difficulty": 0.5},
        {"language_level": "B1"},
    )
    assert all(
        cache.key("version-one", base.model_copy(update=change)) != key for change in changes
    )
    assert cache.key("version-two", base) != key
    assert "private student query" not in key


def test_cache_round_trip_ttl_empty_results_and_corrupt_value() -> None:
    client = fakeredis.FakeRedis()
    cache = RedisRetrievalCache(Settings(retrieval_cache_ttl_seconds=5), client)
    query = RetrievalQuery(text="school", top_k=1)
    key = cache.key("version-one", query)
    assert cache.get("version-one", query) is None
    cache.put("version-one", query, [_result()])
    assert 0 < client.ttl(key) <= 5
    assert cache.get("version-one", query) == [_result()]
    assert cache.get("version-two", query) is None

    client.set(key, b"broken JSON", ex=5)
    assert cache.get("version-one", query) is None
    assert not client.exists(key)
    cache.put("version-one", query, [])
    assert cache.get("version-one", query) == []
    client.expire(key, 0)
    assert cache.get("version-one", query) is None


def test_two_clients_share_redis_results() -> None:
    server = fakeredis.FakeServer()
    first = RedisRetrievalCache(Settings(), fakeredis.FakeRedis(server=server))
    second = RedisRetrievalCache(Settings(), fakeredis.FakeRedis(server=server))
    query = RetrievalQuery(text="school", knowledge_node_id="simple_past", top_k=2)
    first.put("same-version", query, [_result()])
    assert second.get("same-version", query) == [_result()]


def test_student_essay_and_human_correction_results_are_not_shared() -> None:
    client = fakeredis.FakeRedis()
    cache = RedisRetrievalCache(Settings(), client)
    query = RetrievalQuery(text="student writing")
    key = cache.key("v1", query)
    for resource_type in (ResourceType.STUDENT_ESSAY, ResourceType.HUMAN_CORRECTION):
        result = _result()
        result.resource.resource_type = resource_type
        cache.put("v1", query, [result])
        assert not client.exists(key)
        client.set(key, f"[{result.model_dump_json()}]", ex=5)
        assert cache.get("v1", query) is None
        assert not client.exists(key)


def test_real_retriever_uses_cache_and_rebuild_changes_namespace(tmp_path: Path) -> None:
    settings = Settings(retrieval_index_path=tmp_path / "resources.npz")
    engine = create_database_engine(settings)
    try:
        store = ResourceStore(create_session_factory(engine))
        builder = HybridRetriever(store, settings)
        first_version = builder.build_index().index_version
        server = fakeredis.FakeServer()
        client = fakeredis.FakeRedis(server=server)
        cache = RedisRetrievalCache(settings, client)
        runtime = RetrievalRuntime(store, settings, cache)
        first = runtime.current()
        query = RetrievalQuery(text="school", top_k=3)
        results = first.search(query)
        assert results
        assert client.exists(cache.key(first_version, query))

        def should_not_search(*_args: object) -> float:
            raise AssertionError("cache hit recomputed retrieval")

        first._rerank_score = should_not_search  # type: ignore[method-assign]
        assert first.search(query) == results
        second_version = builder.build_index().index_version
        assert second_version != first_version
        second = runtime.current()
        assert second is not first
        assert not client.exists(cache.key(second_version, query))
        assert second.search(query) == results
        assert client.exists(cache.key(second_version, query))
        server.connected = False
        assert second.search(RetrievalQuery(text="friend", top_k=2))
        runtime.close()
    finally:
        engine.dispose()


def test_redis_failure_falls_back_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr("app.services.retrieval.cache.monotonic", lambda: clock[0])
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server)
    cache = RedisRetrievalCache(Settings(retrieval_cache_retry_seconds=2), client)
    query = RetrievalQuery(text="school")
    server.connected = False
    assert cache.get("v1", query) is None
    cache.put("v1", query, [_result()])
    server.connected = True
    assert cache.get("v1", query) is None
    clock[0] = 103.0
    cache.put("v1", query, [_result()])
    assert cache.get("v1", query) == [_result()]


def test_tool_trace_and_permissions_still_run_on_cache_hits(tmp_path: Path) -> None:
    settings = Settings(retrieval_index_path=tmp_path / "resources.npz")
    engine = create_database_engine(settings)
    try:
        sessions = create_session_factory(engine)
        store = ResourceStore(sessions)
        HybridRetriever(store, settings).build_index()
        client = fakeredis.FakeRedis()
        runtime = RetrievalRuntime(store, settings, RedisRetrievalCache(settings, client))
        retriever = runtime.current()
        calls = []
        tools = build_agent_tools(
            StudentStateManager(sessions, settings),
            GrammarKnowledgeGraph(sessions),
            retriever,
            calls.append,
        )
        session_id = uuid4()
        arguments = {"text": "past tense yesterday", "top_k": 3, "knowledge_node_id": "simple_past"}
        first = asyncio.run(
            tools.invoke(
                actor="planner",
                session_id=session_id,
                name="find_teaching_material",
                arguments=arguments,
            )
        )
        assert first
        second = asyncio.run(
            tools.invoke(
                actor="planner",
                session_id=session_id,
                name="find_teaching_material",
                arguments=arguments,
            )
        )
        assert first == second
        assert [call.status for call in calls] == [ToolCallStatus.SUCCESS, ToolCallStatus.SUCCESS]
        with pytest.raises(DomainError, match="cannot call"):
            asyncio.run(
                tools.invoke(
                    actor="evaluator",
                    session_id=session_id,
                    name="find_teaching_material",
                    arguments=arguments,
                )
            )
        assert calls[-1].status == ToolCallStatus.FAILURE
        runtime.close()
    finally:
        engine.dispose()
