from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fixed embedding space for this schema. Changing models requires re-embedding
# every article and reclustering; never mix incompatible vectors in one index.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_SPACE = f"{EMBEDDING_MODEL}@{EMBEDDING_REVISION}"
EMBEDDING_DIMENSIONS = 384


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://news:news@localhost:5432/news"
    redis_url: str = "redis://localhost:6379/0"
    operator_api_key: str = ""
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_webhook_secrets: str = ""
    stripe_pro_price_id: str = ""
    stripe_success_url: str = "http://localhost:3000/settings/billing?checkout=success"
    stripe_cancel_url: str = "http://localhost:3000/settings/billing?checkout=canceled"
    stripe_portal_return_url: str = "http://localhost:3000/settings/billing"
    stripe_past_due_grace_days: int = Field(3, ge=0, le=30)
    user_agent: str = "AINewsAggregator/0.1"
    http_timeout_seconds: float = Field(20, gt=0, le=120)
    http_max_bytes: int = Field(5_000_000, gt=0)
    per_host_delay_seconds: float = Field(1, ge=0)
    source_limit: int = Field(100, ge=1, le=500)
    initial_lookback_days: int = Field(7, ge=1, le=30)
    cluster_window_hours: int = Field(72, ge=1, le=168)
    cluster_similarity: float = Field(0.85, gt=0, le=1)
    simhash_distance: int = Field(3, ge=0, le=8)
    simhash_min_words: int = Field(80, ge=30)
    enrich_articles: bool = True
    ingestion_interval_seconds: int = Field(1800, ge=60)
    deepseek_api_key: SecretStr = SecretStr("")
    analysis_enabled: bool = False
    summary_model: Literal["deepseek-flash", "deepseek-v4-pro"] = "deepseek-flash"
    analysis_model: Literal["deepseek-flash", "deepseek-v4-pro"] = "deepseek-v4-pro"
    analysis_cluster_limit: int = Field(10, ge=1, le=100)
    analysis_budget_usd: float = Field(0.25, gt=0, le=100, allow_inf_nan=False)
    analysis_timeout_seconds: float = Field(60, gt=0, le=180)
    summary_max_tokens: int = Field(768, ge=128, le=4096)
    analysis_max_tokens: int = Field(2048, ge=256, le=8192)


@lru_cache
def get_settings() -> Settings:
    return Settings()
