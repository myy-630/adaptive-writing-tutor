from app.core.config import Settings
from fastembed import TextEmbedding


def main() -> None:
    settings = Settings()
    model = TextEmbedding(
        model_name=settings.embedding_model,
        cache_dir=str(settings.embedding_cache_dir),
    )
    dimension = len(next(model.embed(["English writing practice."])))
    print(f"Cached {settings.embedding_model} ({dimension} dimensions)")


if __name__ == "__main__":
    main()
