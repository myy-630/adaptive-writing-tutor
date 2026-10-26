from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.schemas import RetrievalQuery
from app.services.retrieval.store import ResourceStore


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        retriever = HybridRetriever(ResourceStore(create_session_factory(engine)), settings)
        retriever.load_index()
        for query in ("school", "children learn in a classroom", "a friend helped me"):
            print(f"QUERY: {query}")
            for result in retriever.search(RetrievalQuery(text=query, top_k=3)):
                print(f"{result.rank}. {result.resource.content} [{result.resource.dataset_id}]")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
