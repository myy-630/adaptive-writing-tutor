import hashlib
import json
from pathlib import Path
from shutil import copyfile
from uuid import uuid4

import numpy as np
import pytest
from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import create_database_engine, create_session_factory
from app.domain.enums import ResourceOrigin, ResourceType
from app.domain.schemas import RetrievalResource, RetrievalResult
from app.services.retrieval.hybrid import (
    HybridRetriever,
    reciprocal_rank_fusion,
    rewrite_query,
    tokenize,
)
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.store import ResourceStore


@pytest.fixture(scope="module")
def retrieval_system() -> tuple[HybridRetriever, ResourceStore]:
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        store = ResourceStore(create_session_factory(engine))
        retriever = HybridRetriever(store, settings)
        retriever.load_index()
        yield retriever, store
    finally:
        engine.dispose()


def test_public_data_import_is_attributed_and_idempotent(retrieval_system: tuple) -> None:
    _, store = retrieval_system
    path = Path("data/processed/tatoeba_sample.jsonl")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 133
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "f6feb35fdf8199f545bab468f799ff9e6673e2935c18633ee3fe6835ba43e982"
    )
    assert store.import_jsonl(path) == 0
    public = [item for item in store.list_resources() if item.origin == ResourceOrigin.PUBLIC]
    assert len(public) == 133
    assert all(
        item.dataset_id and item.source.startswith("https://tatoeba.org/") for item in public
    )
    assert all(item.license == "CC BY 2.0 FR" and "by " in item.attribution for item in public)
    assert all(
        item.processing_notes and item.resource_type == ResourceType.BASIC_SENTENCE
        for item in public
    )


def test_bm25_keyword_recall_and_dense_semantic_recall(retrieval_system: tuple) -> None:
    retriever, _ = retrieval_system
    assert retriever.bm25 is not None and retriever.model is not None
    assert retriever.vectors is not None
    lexical_scores = retriever.bm25.get_scores(tokenize("school"))
    lexical_best = int(np.argmax(lexical_scores))
    assert lexical_scores[lexical_best] > 0
    assert "school" in retriever.resources[lexical_best].content.casefold()

    semantic_query = "educational institution"
    semantic_vector = retriever._normalize(
        np.asarray(list(retriever.model.embed([semantic_query])), dtype=np.float32)
    )[0]
    dense_best = int(np.argmax(retriever.vectors @ semantic_vector))
    assert "school" in retriever.resources[dense_best].content.casefold()
    assert not set(tokenize(semantic_query)) & set(
        tokenize(retriever.resources[dense_best].content)
    )


def test_rrf_really_combines_two_rankings() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    scores = reciprocal_rank_fusion([first, second], [second, third], 60)
    assert scores[second] > scores[first] > scores[third]
    assert scores[second] == pytest.approx(1 / 62 + 1 / 61)


def test_metadata_filters_empty_and_no_results(retrieval_system: tuple) -> None:
    retriever, _ = retrieval_system
    assert retriever.search(RetrievalQuery(text="  ")) == []
    assert (
        retriever.search(RetrievalQuery(text="school", resource_types=[ResourceType.STUDENT_ESSAY]))
        == []
    )
    assert (
        retriever.search(
            RetrievalQuery(text="school", grade=12, resource_types=[ResourceType.WRITING_PROMPT])
        )
        == []
    )
    prompts = retriever.search(
        RetrievalQuery(text="school", grade=9, resource_types=[ResourceType.WRITING_PROMPT])
    )
    assert prompts and all(
        item.resource.resource_type == ResourceType.WRITING_PROMPT for item in prompts
    )
    lessons = retriever.search(
        RetrievalQuery(
            text="past tense yesterday",
            resource_types=[ResourceType.GRAMMAR_EXPLANATION],
            knowledge_node_id="simple_past",
        )
    )
    assert len(lessons) == 1


def test_rerank_can_change_fused_order(retrieval_system: tuple) -> None:
    retriever, _ = retrieval_system
    base = retriever.resources[0]
    unrelated = base.model_copy(update={"content": "Clouds gather above the city."})
    exact = base.model_copy(update={"content": "A memorable school day."})
    rewrite = rewrite_query("school day")
    assert retriever._rerank_score(exact, rewrite, 0.01) > retriever._rerank_score(
        unrelated, rewrite, 0.04
    )

    changed_on_real_corpus = False
    for text in ("school", "friend", "although", "past tense yesterday"):
        rewrite = rewrite_query(text)
        lexical_scores = retriever.bm25.get_scores(rewrite.bm25_terms)
        lexical_indices = sorted(
            (index for index, score in enumerate(lexical_scores) if score > 0),
            key=lambda index: (-lexical_scores[index], str(retriever.resources[index].id)),
        )
        vector = retriever._normalize(
            np.asarray(list(retriever.model.embed([rewrite.normalized])), dtype=np.float32)
        )[0]
        dense_scores = retriever.vectors @ vector
        dense_indices = sorted(
            range(len(retriever.resources)),
            key=lambda index: (-dense_scores[index], str(retriever.resources[index].id)),
        )
        fused = reciprocal_rank_fusion(
            [retriever.resources[index].id for index in lexical_indices],
            [retriever.resources[index].id for index in dense_indices],
            retriever.settings.rrf_k,
        )
        fused_top = sorted(fused, key=lambda item: (-fused[item], str(item)))[:5]
        reranked_top = [
            item.resource.id for item in retriever.search(RetrievalQuery(text=text, top_k=5))
        ]
        changed_on_real_corpus |= fused_top != reranked_top
    assert changed_on_real_corpus


def test_fixed_queries_top_k_schema_and_agent_adapters(retrieval_system: tuple) -> None:
    retriever, _ = retrieval_system
    cases = json.loads(Path("tests/fixtures/retrieval_queries.json").read_text())
    for case in cases:
        results = retriever.search(RetrievalQuery(text=case["query"], top_k=5))
        assert results and len(results) <= 5
        assert [item.rank for item in results] == list(range(1, len(results) + 1))
        assert any(
            case["expected_substring"] in item.resource.content.casefold() for item in results
        )
        assert RetrievalResult.model_validate_json(results[0].model_dump_json()) == results[0]
        assert {"dense", "rrf", "metadata_filter", "rerank"} <= set(results[0].match_reasons)
    assert retriever.find_writing_prompts("school day")
    assert retriever.find_teaching_material("past tense yesterday")


def test_index_rebuild_reproduces_vectors_and_results(retrieval_system: tuple) -> None:
    retriever, _ = retrieval_system
    before = retriever.search(RetrievalQuery(text="school", top_k=5))
    old_vectors = retriever.vectors.copy()
    old_metadata = retriever.metadata
    new_metadata = retriever.build_index()
    after = retriever.search(RetrievalQuery(text="school", top_k=5))
    assert new_metadata == old_metadata
    assert np.allclose(retriever.vectors, old_vectors, atol=1e-6)
    assert [item.resource.id for item in before] == [item.resource.id for item in after]


def test_stale_or_missing_index_and_invalid_source(retrieval_system: tuple, tmp_path: Path) -> None:
    retriever, store = retrieval_system
    settings = Settings(retrieval_index_path=tmp_path / "missing.npz")
    with pytest.raises(DomainError, match="not been built"):
        HybridRetriever(store, settings).load_index()
    copyfile(retriever.settings.retrieval_index_path, tmp_path / "resources.npz")
    metadata = retriever.metadata.model_copy(update={"corpus_sha256": "wrong"})
    (tmp_path / "resources.json").write_text(metadata.model_dump_json(), encoding="utf-8")
    with pytest.raises(DomainError, match="corpus changed"):
        HybridRetriever(
            store, Settings(retrieval_index_path=tmp_path / "resources.npz")
        ).load_index()
    bad_public = retriever.resources[0].model_copy(
        update={"id": uuid4(), "source": "unknown", "origin": ResourceOrigin.PUBLIC}
    )
    with pytest.raises(DomainError, match="source URL"):
        store.add_resources([bad_public])


def test_all_resource_types_have_stable_enum_values() -> None:
    assert len(ResourceType) == 10
    with pytest.raises(ValueError):
        RetrievalResource.model_validate(
            {
                "content": "Bad",
                "resource_type": "invented",
                "source": "test",
                "license": "CC0",
                "attribution": "test",
                "origin": "human",
                "processing_notes": "test",
            }
        )
