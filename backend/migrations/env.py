from logging.config import fileConfig

import app.models  # noqa: F401
from alembic import context
from app.core.config import Settings
from app.db.base import Base
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name and config.get_section(config.config_ini_section, {}).get("handlers"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
database_url = Settings().database_url  # type: ignore[call-arg]
LANGGRAPH_CHECKPOINT_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def include_name(name: str | None, type_: str, _parent_names: dict[str, str]) -> bool:
    return type_ != "table" or name not in LANGGRAPH_CHECKPOINT_TABLES


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_name=include_name,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
