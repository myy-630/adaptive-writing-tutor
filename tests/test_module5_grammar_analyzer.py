import pytest
from app.api.main import create_app
from app.core.config import Settings
from app.core.errors import DomainError
from app.db.session import create_database_engine, create_session_factory
from app.domain.enums import DiagnosticSeverity, EdgeRelation
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.grammar.schemas import GrammarAnalysis, GrammarError
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.seed import seed_canonical_graph
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture(scope="module")
def analyzer() -> GrammarAnalyzer:
    engine = create_database_engine(Settings())
    try:
        sessions = create_session_factory(engine)
        seed_canonical_graph(sessions)
        yield GrammarAnalyzer(GrammarKnowledgeGraph(sessions))
    finally:
        engine.dispose()


def test_no_error_and_empty_inputs(analyzer: GrammarAnalyzer) -> None:
    assert analyzer.analyze("She goes to school every day.").errors == []
    assert analyzer.analyze("I saw a dog.").errors == []
    assert analyzer.analyze("").errors == []
    assert analyzer.analyze("  \n").errors == []
    assert analyzer.analyze("Perhaps this expression is valid.").errors == []


def test_subject_verb_agreement(analyzer: GrammarAnalyzer) -> None:
    result = analyzer.analyze("She go to school.")
    assert len(result.errors) == 1
    error = result.errors[0]
    assert result.input_text[error.start_offset : error.end_offset] == "go"
    assert error.corrected_expression == "goes"
    assert error.corrected_sentence == "She goes to school."
    assert error.knowledge_node_id == "subject_verb_agreement"
    assert error.subtype == "subject_verb_agreement"
    assert error.original_structure == error.corrected_structure == "subject_predicate"
    assert 0 <= error.confidence <= 1
    assert error.severity == DiagnosticSeverity.MODERATE


def test_past_tense_and_article(analyzer: GrammarAnalyzer) -> None:
    tense = analyzer.analyze("Yesterday, I go to school.").errors[0]
    assert tense.knowledge_node_id == "tense"
    assert tense.corrected_sentence == "Yesterday, I went to school."
    assert tense.subtype == "past_tense"
    article = analyzer.analyze("I saw dog.").errors[0]
    assert article.knowledge_node_id == "article"
    assert article.corrected_sentence == "I saw a dog."
    assert article.original_structure == article.corrected_structure == "subject_verb_object"
    assert analyzer.analyze("I saw a apple.").errors[0].corrected_sentence == "I saw an apple."


def test_sentence_structure_errors(analyzer: GrammarAnalyzer) -> None:
    fragment = analyzer.analyze("Because I was tired.").errors[0]
    assert fragment.knowledge_node_id == "simple_sentence"
    assert fragment.corrected_sentence == "I was tired."
    assert fragment.original_structure == "dependent_clause_only"
    assert fragment.corrected_structure == "subject_linking_predicative"
    assert fragment.confidence < 0.8
    run_on = analyzer.analyze("I like apples I like bananas.").errors[0]
    assert run_on.knowledge_node_id == "complex_sentence"
    assert run_on.corrected_sentence == "I like apples. I like bananas."
    assert run_on.original_structure == "two_independent_clauses_without_connector"
    assert run_on.corrected_structure == "two_simple_sentences"


def test_multiple_errors_offsets_and_order_are_stable(analyzer: GrammarAnalyzer) -> None:
    text = "She go to school.\nI saw dog."
    first = analyzer.analyze(text)
    second = analyzer.analyze(text)
    assert first == second
    assert len(first.errors) == 2
    assert [item.knowledge_node_id for item in first.errors] == [
        "subject_verb_agreement",
        "article",
    ]
    assert [item.start_offset for item in first.errors] == sorted(
        item.start_offset for item in first.errors
    )
    assert [text[item.start_offset : item.end_offset] for item in first.errors] == ["go", "dog"]
    assert GrammarAnalysis.model_validate_json(first.model_dump_json()) == first


def test_schema_rejects_invalid_confidence_severity_and_span(analyzer: GrammarAnalyzer) -> None:
    valid = analyzer.analyze("She go to school.").errors[0].model_dump()
    for mutation in (
        {"confidence": 1.5},
        {"severity": "catastrophic"},
        {"end_offset": valid["start_offset"]},
        {"knowledge_node_id": ""},
    ):
        with pytest.raises(ValidationError):
            GrammarError.model_validate({**valid, **mutation})


def test_missing_graph_mapping_fails_explicitly(analyzer: GrammarAnalyzer) -> None:
    graph = analyzer.graph
    graph.graph.remove_edge(
        "subject_verb_agreement", "error:sva", key=EdgeRelation.COMMON_ERROR.value
    )
    try:
        with pytest.raises(DomainError, match="No Knowledge Graph node"):
            analyzer.analyze("She go to school.")
    finally:
        graph.refresh()


def test_raw_diagnostics_not_exposed_on_student_api() -> None:
    with TestClient(create_app(settings=Settings())) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert all("grammar" not in path and "diagnos" not in path for path in paths)
    assert "action" not in GrammarError.model_fields
    assert "teaching_decision" not in GrammarAnalysis.model_fields
