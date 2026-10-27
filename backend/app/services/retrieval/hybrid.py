import hashlib
import json
import re
import tempfile
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import BadZipFile

import numpy as np
from app.core.config import Settings
from app.core.errors import DomainError
from app.domain.enums import ResourceType
from app.domain.schemas import RetrievalResource, RetrievalResult
from app.services.retrieval.cache import RedisRetrievalCache
from app.services.retrieval.schemas import IndexMetadata, QueryRewrite, RetrievalQuery
from app.services.retrieval.store import ResourceStore
from fastembed import TextEmbedding
from pydantic import ValidationError
from rank_bm25 import BM25Okapi

TOKEN_PATTERN = re.compile(r"[a-z]+(?:'[a-z]+)?")
SYNONYMS = {"pupil": "student", "pupils": "students", "classroom": "school", "kid": "child"}


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.casefold())


def rewrite_query(text: str) -> QueryRewrite:
    normalized = " ".join(text.casefold().split())
    terms = tokenize(normalized)
    expansions = [SYNONYMS[term] for term in terms if term in SYNONYMS]
    return QueryRewrite(original=text, normalized=normalized, bm25_terms=terms + expansions)


def reciprocal_rank_fusion(
    lexical_ids: list[UUID], dense_ids: list[UUID], k: int
) -> dict[UUID, float]:
    scores: dict[UUID, float] = defaultdict(float)
    for ranking in (lexical_ids, dense_ids):
        for rank, resource_id in enumerate(ranking, start=1):
            scores[resource_id] += 1 / (k + rank)
    return dict(scores)


class HybridRetriever:
    def __init__(
        self, store: ResourceStore, settings: Settings, cache: RedisRetrievalCache | None = None
    ) -> None:
        self.store = store
        self.settings = settings
        self.cache = cache
        self.resources: list[RetrievalResource] = []
        self.vectors: np.ndarray | None = None
        self.bm25: BM25Okapi | None = None
        self.model: TextEmbedding | None = None
        self.metadata: IndexMetadata | None = None

    def build_index(self) -> IndexMetadata:
        resources = self.store.list_resources()
        if not resources:
            raise DomainError("empty_corpus", "Cannot build index without resources", 409)
        model = self._embedding_model(local_files_only=True)
        vectors = np.asarray(
            list(model.embed([item.content for item in resources])), dtype=np.float32
        )
        vectors = self._normalize(vectors)
        metadata = IndexMetadata(
            index_version=uuid4().hex,
            corpus_sha256=self._corpus_hash(resources),
            model_name=self.settings.embedding_model,
            fastembed_version=version("fastembed"),
            resource_count=len(resources),
            embedding_dimension=vectors.shape[1],
        )
        path = self.settings.retrieval_index_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as handle:
            np.savez_compressed(
                handle,
                ids=np.array([str(item.id) for item in resources]),
                vectors=vectors,
                index_version=np.array(metadata.index_version),
            )
            temporary_index = Path(handle.name)
        temporary_index.replace(path)
        meta_path = path.with_suffix(".json")
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".json", delete=False
        ) as handle:
            handle.write(metadata.model_dump_json(indent=2))
            temporary_metadata = Path(handle.name)
        temporary_metadata.replace(meta_path)
        self._activate(resources, vectors, model, metadata)
        return metadata

    def load_index(self) -> IndexMetadata:
        path = self.settings.retrieval_index_path
        meta_path = path.with_suffix(".json")
        if not path.exists() or not meta_path.exists():
            raise DomainError("index_missing", "Retrieval index has not been built", 409)
        try:
            metadata = IndexMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise DomainError("index_corrupt", "Retrieval index metadata is invalid", 409) from exc
        resources = self.store.list_resources()
        if metadata.corpus_sha256 != self._corpus_hash(resources):
            raise DomainError(
                "index_stale", "Resource corpus changed; rebuild retrieval index", 409
            )
        if metadata.model_name != self.settings.embedding_model:
            raise DomainError("index_model_mismatch", "Embedding model differs from index", 409)
        if metadata.fastembed_version != version("fastembed"):
            raise DomainError("index_version_mismatch", "FastEmbed version differs from index", 409)
        try:
            with np.load(path, allow_pickle=False) as archive:
                ids = archive["ids"].tolist()
                vectors = archive["vectors"]
                archive_version = (
                    str(archive["index_version"].item())
                    if "index_version" in archive.files
                    else "legacy"
                )
        except (OSError, ValueError, KeyError, EOFError, BadZipFile) as exc:
            raise DomainError("index_corrupt", "Retrieval index data is invalid", 409) from exc
        if archive_version != metadata.index_version:
            raise DomainError("index_version_mismatch", "Index files have different versions", 409)
        if ids != [str(item.id) for item in resources] or vectors.shape != (
            len(resources),
            metadata.embedding_dimension,
        ):
            raise DomainError("index_corrupt", "Retrieval index shape or IDs are invalid", 409)
        model = self._embedding_model(local_files_only=True)
        self._activate(resources, vectors, model, metadata)
        return metadata

    def search(self, query: RetrievalQuery) -> list[RetrievalResult]:
        if not query.text.strip():
            return []
        if self.vectors is None or self.bm25 is None or self.model is None:
            raise DomainError(
                "index_missing", "Load or build the retrieval index before search", 409
            )
        if self.cache is not None and self.metadata is not None:
            cached = self.cache.get(self.metadata.index_version, query)
            if cached is not None:
                return cached
        rewrite = rewrite_query(query.text)
        lexical_scores = self.bm25.get_scores(rewrite.bm25_terms)
        query_vector = self._normalize(
            np.asarray(list(self.model.embed([rewrite.normalized])), dtype=np.float32)
        )[0]
        dense_scores = self.vectors @ query_vector
        lexical_indices = sorted(
            (index for index, score in enumerate(lexical_scores) if score > 0),
            key=lambda index: (-lexical_scores[index], str(self.resources[index].id)),
        )
        dense_indices = sorted(
            range(len(self.resources)),
            key=lambda index: (-dense_scores[index], str(self.resources[index].id)),
        )
        fused = reciprocal_rank_fusion(
            [self.resources[index].id for index in lexical_indices],
            [self.resources[index].id for index in dense_indices],
            self.settings.rrf_k,
        )
        filtered = [
            item for item in self.resources if self._matches(item, query) and item.id in fused
        ]
        ranked = sorted(
            filtered,
            key=lambda item: (-self._rerank_score(item, rewrite, fused[item.id]), str(item.id)),
        )[: query.top_k]
        lexical_set = {self.resources[index].id for index in lexical_indices}
        results = [
            RetrievalResult(
                resource=item,
                rank=rank,
                score=self._rerank_score(item, rewrite, fused[item.id]),
                match_reasons=[
                    *(["bm25"] if item.id in lexical_set else []),
                    "dense",
                    "rrf",
                    "metadata_filter",
                    "rerank",
                ],
            )
            for rank, item in enumerate(ranked, start=1)
        ]
        if self.cache is not None and self.metadata is not None:
            self.cache.put(self.metadata.index_version, query, results)
        return results

    def find_writing_prompts(self, text: str, top_k: int = 3) -> list[RetrievalResult]:
        return self.search(
            RetrievalQuery(text=text, top_k=top_k, resource_types=[ResourceType.WRITING_PROMPT])
        )

    def find_teaching_material(self, text: str, top_k: int = 5) -> list[RetrievalResult]:
        return self.search(
            RetrievalQuery(
                text=text,
                top_k=top_k,
                resource_types=[
                    ResourceType.BASIC_SENTENCE,
                    ResourceType.GRAMMAR_EXPLANATION,
                    ResourceType.GRAMMAR_ERROR,
                    ResourceType.SENTENCE_TRANSFORMATION,
                    ResourceType.STRUCTURE_EXAMPLE,
                    ResourceType.TRANSFER_EXERCISE,
                ],
            )
        )

    def _activate(
        self,
        resources: list[RetrievalResource],
        vectors: np.ndarray,
        model: TextEmbedding,
        metadata: IndexMetadata,
    ) -> None:
        self.resources = resources
        self.vectors = vectors
        self.model = model
        self.metadata = metadata
        self.bm25 = BM25Okapi([tokenize(item.content) for item in resources])

    def _embedding_model(self, *, local_files_only: bool) -> TextEmbedding:
        return TextEmbedding(
            model_name=self.settings.embedding_model,
            cache_dir=str(self.settings.embedding_cache_dir),
            local_files_only=local_files_only,
        )

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)

    @staticmethod
    def _corpus_hash(resources: list[RetrievalResource]) -> str:
        content = json.dumps(
            [item.model_dump(mode="json") for item in resources],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _matches(resource: RetrievalResource, query: RetrievalQuery) -> bool:
        return all(
            (
                query.resource_types is None or resource.resource_type in query.resource_types,
                query.grade is None or resource.grade == query.grade,
                query.genre is None or resource.genre == query.genre,
                query.knowledge_node_id is None
                or query.knowledge_node_id in resource.knowledge_node_ids,
                query.ability_dimension is None
                or query.ability_dimension in resource.ability_dimensions,
                query.max_difficulty is None
                or (
                    resource.difficulty is not None and resource.difficulty <= query.max_difficulty
                ),
                query.language_level is None or resource.language_level == query.language_level,
            )
        )

    @staticmethod
    def _rerank_score(resource: RetrievalResource, rewrite: QueryRewrite, fusion: float) -> float:
        terms = set(rewrite.bm25_terms)
        content_terms = set(tokenize(resource.content))
        coverage = len(terms & content_terms) / len(terms) if terms else 0
        phrase = int(rewrite.normalized in resource.content.casefold())
        length = len(tokenize(resource.content))
        example_length = max(0.0, 1 - abs(length - 12) / 24)
        return 0.5 * fusion + 0.35 * coverage + 0.1 * phrase + 0.05 * example_length
