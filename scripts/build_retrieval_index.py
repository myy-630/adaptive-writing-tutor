import json

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.store import ResourceStore


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        retriever = HybridRetriever(ResourceStore(create_session_factory(engine)), settings)
        metadata = retriever.build_index()
        print(json.dumps(metadata.model_dump(), ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
