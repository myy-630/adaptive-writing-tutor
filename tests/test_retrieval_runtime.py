import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from app.agents.schemas import EvaluatorJudgement, TeachingText
from app.api.main import create_app
from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.runtime import RetrievalRuntime
from app.services.retrieval.schemas import IndexMetadata, RetrievalQuery
from app.services.retrieval.store import ResourceStore
from fastapi.testclient import TestClient


class ScriptedProvider:
    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type
    ) -> object:
        if response_type is TeachingText:
            return TeachingText(text="Look at the task and make your own next attempt.")
        if response_type is EvaluatorJudgement:
            return EvaluatorJudgement(
                accurate_to_issue=True,
                scaffold_too_strong=False,
                scaffold_too_weak=False,
                actionable_next_step=True,
                stage_appropriate=True,
                ghostwriting=False,
                rationale="Aligned with the stage and policy",
            )
        raise AssertionError(response_type)


def test_lifespan_reuses_loaded_retriever_across_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads = 0
    original = HybridRetriever.load_index

    def counted_load(self: HybridRetriever) -> IndexMetadata:
        nonlocal loads
        loads += 1
        return original(self)

    monkeypatch.setattr(HybridRetriever, "load_index", counted_load)
    student_id, task_id, session_id = (str(uuid4()) for _ in range(3))
    provider = ScriptedProvider()
    with TestClient(create_app(Settings(), provider)) as client:
        runtime = client.app.state.retrieval_runtime
        first = runtime.current()
        assert first.metadata is not None
        assert runtime.current() is first
        assert client.app.state.model_provider is provider
        assert (
            client.post(
                "/students",
                json={"id": student_id, "grade": 9, "learning_goal": "Write more clearly"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/tasks",
                json={
                    "id": task_id,
                    "prompt": "Describe your classes and friends",
                    "genre": "narrative",
                    "grade": 9,
                    "required_points": ["classes", "friends"],
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/sessions",
                json={"id": session_id, "student_id": student_id, "task_id": task_id},
            ).status_code
            == 200
        )
        for submission in (
            {"kind": "start"},
            {
                "kind": "response",
                "prompt_analysis": {
                    "audience": "my classmates",
                    "purpose": "describe our day",
                    "genre": "narrative",
                    "required_points": ["classes", "friends"],
                    "tense": "present",
                    "person": "first",
                    "constraints": "include both topics",
                },
            },
        ):
            response = client.post(
                f"/sessions/{session_id}/turn",
                json={"student_id": student_id, "submission": submission},
            )
            assert response.status_code == 200, response.text
            assert runtime.current() is first
        assert loads == 1


def test_missing_index_recovers_and_reloads_on_new_version(tmp_path: Path) -> None:
    settings = Settings(retrieval_index_path=tmp_path / "resources.npz")
    engine = create_database_engine(settings)
    try:
        store = ResourceStore(create_session_factory(engine))
        runtime = RetrievalRuntime(store, settings)
        unloaded = runtime.current()
        assert unloaded.metadata is None
        assert runtime.current() is unloaded

        builder = HybridRetriever(store, settings)
        first_version = builder.build_index().index_version
        first = runtime.current()
        assert first is not unloaded
        assert runtime.loaded_version == first_version
        assert first.search(RetrievalQuery(text="school", top_k=3))
        assert runtime.current() is first

        meta_path = settings.retrieval_index_path.with_suffix(".json")
        original_metadata = meta_path.read_text(encoding="utf-8")
        partial = IndexMetadata.model_validate_json(original_metadata).model_copy(
            update={"index_version": "publication-in-progress"}
        )
        meta_path.write_text(partial.model_dump_json(), encoding="utf-8")
        assert runtime.current() is first
        meta_path.write_text(original_metadata, encoding="utf-8")
        assert runtime.current() is first

        meta_path.write_text("{", encoding="utf-8")
        assert runtime.current().metadata is None
        meta_path.write_text(original_metadata, encoding="utf-8")
        restored = runtime.current()
        assert restored.metadata is not None
        assert restored.metadata.index_version == first_version

        second_version = builder.build_index().index_version
        with ThreadPoolExecutor(max_workers=6) as workers:
            snapshots = list(workers.map(lambda _: runtime.current(), range(6)))
        second = snapshots[0]
        assert second_version != first_version
        assert all(item is second for item in snapshots)
        assert second is not restored
        assert second.metadata is not None and second.metadata.index_version == second_version
        assert first.metadata is not None and first.metadata.index_version == first_version
        assert [item.resource.id for item in second.search(RetrievalQuery(text="school"))] == [
            item.resource.id for item in first.search(RetrievalQuery(text="school"))
        ]
        runtime.close()
    finally:
        engine.dispose()


def test_legacy_index_can_load_without_rebuilding(tmp_path: Path) -> None:
    source_path = Settings().retrieval_index_path
    legacy_path = tmp_path / "legacy.npz"
    with np.load(source_path, allow_pickle=False) as archive:
        np.savez_compressed(legacy_path, ids=archive["ids"], vectors=archive["vectors"])
    current_metadata = IndexMetadata.model_validate_json(
        source_path.with_suffix(".json").read_text(encoding="utf-8")
    )
    legacy_path.with_suffix(".json").write_text(
        json.dumps(current_metadata.model_dump(exclude={"index_version"})), encoding="utf-8"
    )
    settings = Settings(retrieval_index_path=legacy_path)
    engine = create_database_engine(settings)
    try:
        runtime = RetrievalRuntime(ResourceStore(create_session_factory(engine)), settings)
        assert runtime.current().metadata is not None
        assert runtime.loaded_version == "legacy"
    finally:
        engine.dispose()
