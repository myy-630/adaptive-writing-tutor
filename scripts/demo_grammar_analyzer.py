from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.grammar.analyzer import GrammarAnalyzer
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph


def main() -> None:
    engine = create_database_engine(Settings())
    try:
        graph = GrammarKnowledgeGraph(create_session_factory(engine))
        analyzer = GrammarAnalyzer(graph)
        result = analyzer.analyze("She go to school. I saw dog.")
        print(result.model_dump_json(indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
