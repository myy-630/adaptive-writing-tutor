from pathlib import Path

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.services.retrieval.store import ResourceStore


def main() -> None:
    engine = create_database_engine(Settings())
    try:
        store = ResourceStore(create_session_factory(engine))
        inserted = store.import_jsonl(Path("data/processed/tatoeba_sample.jsonl"))
        print(f"Imported {inserted} new Tatoeba resources")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
