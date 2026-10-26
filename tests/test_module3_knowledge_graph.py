from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import create_database_engine, create_session_factory
from app.domain import LearningEvidence, Student, TeachingMode, TeachingStage
from app.domain.enums import EdgeRelation, EvidenceOutcome, NodeKind
from app.models import TeachingSessionRecord, WritingTaskRecord
from app.models.knowledge_graph import KnowledgeEdgeRecord, KnowledgeNodeRecord
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.seed import CORE_REQUIRED_IDS, seed_canonical_graph
from app.services.student_state.manager import StudentStateManager
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def graph_service() -> tuple[GrammarKnowledgeGraph, sessionmaker[Session], Engine]:
    engine = create_database_engine(Settings())
    sessions = create_session_factory(engine)
    seed_canonical_graph(sessions)
    yield GrammarKnowledgeGraph(sessions), sessions, engine
    engine.dispose()


def test_core_nodes_relationships_and_idempotent_seed(graph_service: tuple) -> None:
    graph, sessions, _ = graph_service
    validation = graph.assert_valid()
    assert validation.node_count == 50
    assert validation.edge_count == 56
    assert CORE_REQUIRED_IDS <= graph.nodes.keys()
    assert [node.id for node in graph.children("grammar")] == [
        "clauses_connectors",
        "punctuation_writing",
        "sentence_structure",
        "word_classes",
    ]
    assert graph.parent("subject_verb_agreement").id == "verb"
    assert graph.parent("grammar") is None
    assert graph.get_node("subject_verb_agreement").kind == NodeKind.CONCEPT
    seed_canonical_graph(sessions)
    graph.refresh()
    assert graph.validate() == validation
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeNodeRecord)) == 50
        assert db.scalar(select(func.count()).select_from(KnowledgeEdgeRecord)) == 56


def test_prerequisites_related_concepts_and_error_linking(graph_service: tuple) -> None:
    graph, _, _ = graph_service
    assert [item.id for item in graph.prerequisites("complex_sentence")] == ["simple_sentence"]
    assert "simple_sentence" in {
        item.id for item in graph.prerequisites("clauses_connectors", transitive=True)
    }
    assert "present_perfect" in {item.id for item in graph.related_concepts("simple_past")}
    assert graph.link_error("SVA").id == "subject_verb_agreement"
    assert graph.link_error("article_error").id == "article"
    assert graph.link_error("unknown-error") is None


def test_missing_nodes_and_invalid_cycle_handled(graph_service: tuple) -> None:
    graph, _, _ = graph_service
    assert graph.get_node("missing") is None
    assert graph.parent("missing") is None
    assert graph.children("missing") == []
    assert graph.prerequisites("missing") == []
    assert graph.related_concepts("missing") == []
    graph.graph.add_edge(
        "complex_sentence", "simple_sentence", key=EdgeRelation.PREREQUISITE_FOR.value
    )
    assert set(graph.validate().prerequisite_cycle_ids) == {"simple_sentence", "complex_sentence"}
    with pytest.raises(DomainError, match="validation failed"):
        graph.assert_valid()


def test_all_relation_types_and_direction_validation(graph_service: tuple) -> None:
    graph, _, _ = graph_service
    relations = {relation for _, _, relation in graph.graph.edges(keys=True)}
    assert relations == {relation.value for relation in EdgeRelation}
    graph.graph.add_edge("error:sva", "subject_verb_agreement", key=EdgeRelation.COMMON_ERROR.value)
    assert any(
        issue.startswith("auxiliary-direction:") for issue in graph.validate().invalid_relationships
    )


def test_overlay_reads_real_student_state(graph_service: tuple) -> None:
    graph, sessions, _ = graph_service
    manager = StudentStateManager(sessions, Settings())
    student = Student(grade=9, learning_goal="Improve grammar")
    manager.initialize_student(student)
    task_id, session_id = uuid4(), uuid4()
    with sessions.begin() as db:
        db.add(
            WritingTaskRecord(
                id=task_id, prompt="Write about a friend", genre="description", grade=9
            )
        )
        db.flush()
        db.add(
            TeachingSessionRecord(
                id=session_id,
                student_id=student.id,
                task_id=task_id,
                stage=TeachingStage.GRAMMAR_REVISION,
                mode=TeachingMode.GUIDED,
            )
        )
    manager.record_evidence(
        LearningEvidence(
            student_id=student.id,
            session_id=session_id,
            knowledge_node_id="subject_verb_agreement",
            outcome=EvidenceOutcome.SUCCESS,
            observed_at=datetime.now(UTC),
        )
    )
    overlay = {entry.node.id: entry for entry in graph.overlay(student.id, manager)}
    assert overlay["subject_verb_agreement"].mastery is not None
    assert overlay["subject_verb_agreement"].confidence == pytest.approx(0.25)
    assert overlay["article"].mastery is None
    assert overlay["article"].evidence_count == 0


def test_database_rejects_orphan_edges(graph_service: tuple) -> None:
    _, sessions, _ = graph_service
    with pytest.raises(IntegrityError):
        with sessions.begin() as db:
            db.add(
                KnowledgeEdgeRecord(
                    source_id="missing-source",
                    target_id="grammar",
                    relation=EdgeRelation.BELONGS_TO,
                )
            )


def test_small_graph_query_speed(graph_service: tuple) -> None:
    graph, _, _ = graph_service
    start = perf_counter()
    for _ in range(100):
        assert graph.get_node("tense") is not None
        graph.parent("tense")
        graph.children("verb")
        graph.prerequisites("complex_sentence")
        graph.related_concepts("simple_past")
        graph.link_error("sva")
    assert perf_counter() - start < 2.0
