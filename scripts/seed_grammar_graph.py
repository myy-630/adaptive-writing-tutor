import json

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph
from app.services.knowledge_graph.seed import seed_canonical_graph


def main() -> None:
    engine = create_database_engine(Settings())
    try:
        sessions = create_session_factory(engine)
        seed_canonical_graph(sessions)
        result = GrammarKnowledgeGraph(sessions).assert_valid()
        print(json.dumps(result.model_dump(), ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
