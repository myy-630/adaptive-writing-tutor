from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(min_length=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    bkt_initial_mastery: float = Field(default=0.2, ge=0, le=1)
    bkt_learn: float = Field(default=0.05, ge=0, le=1)
    bkt_guess: float = Field(default=0.2, ge=0, lt=1)
    bkt_slip: float = Field(default=0.1, ge=0, lt=1)
    ability_initial_score: float = Field(default=0.5, ge=0, le=1)
    ability_ema_alpha: float = Field(default=0.3, gt=0, le=1)
    confidence_prior_weight: float = Field(default=3.0, gt=0)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: Path = Path("data/indexes/model_cache")
    retrieval_index_path: Path = Path("data/indexes/resources.npz")
    retrieval_cache_enabled: bool = True
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    retrieval_cache_ttl_seconds: int = Field(default=300, ge=1)
    retrieval_cache_timeout_seconds: float = Field(default=0.2, gt=0, le=5)
    retrieval_cache_retry_seconds: int = Field(default=30, ge=1)
    rrf_k: int = Field(default=60, ge=1)
    model_provider: Literal["deepseek", "openai"] = "deepseek"
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str = Field(default="deepseek-flash", min_length=1)
    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-4o-mini", min_length=1)
    workflow_max_regenerations: int = Field(default=2, ge=0, le=5)
    workflow_min_draft_words: int = Field(default=20, ge=1)

    @model_validator(mode="after")
    def valid_bkt(self) -> "Settings":
        if self.bkt_guess + self.bkt_slip >= 1:
            raise ValueError("bkt_guess + bkt_slip must be less than 1")
        return self
