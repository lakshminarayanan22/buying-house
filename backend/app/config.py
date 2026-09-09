"""Application settings, loaded from environment / .env (pydantic-settings)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: str = "local"
    app_base_url: str = "http://localhost:3000"

    # Database. pgvector is enabled in the first migration so Phase 6 only has to add columns.
    database_url: str = "postgresql+psycopg://bh:bh@localhost:5432/ecolink"

    # --- Chatbot ---
    # stub: keyword routing and templated answers. No key, no spend, and it makes the graph
    #       testable. It is not a chatbot and reindex-style warnings say so.
    # claude: the real thing.
    llm_backend: str = "stub"
    anthropic_api_key: str | None = None
    classifier_model: str = "claude-haiku-4-5-20251001"
    branch_model: str = "claude-sonnet-5"
    classifier_confidence_floor: float = 0.6
    allow_secondary_category: bool = True
    sql_statement_timeout_ms: int = 2000
    sql_row_cap: int = 500
    database_url_readonly: str | None = None

    # --- Retrieval ---
    # stub: deterministic, no network, no model download. Exercises the pipeline and the
    #       lexical half of hybrid search honestly; the vector half is meaningless.
    # voyage: voyage-3, 1024 dimensions. Needs VOYAGE_API_KEY.
    # local: sentence-transformers. Needs the package and a model download.
    embedding_backend: str = "stub"
    embedding_model: str = "voyage-3"
    embedding_dimensions: int = 1024
    voyage_api_key: str | None = None

    similarity_floor: float = 0.40
    retrieval_top_k: int = 8
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 80

    # Uploaded files. A folder per deal on local disk — see api/documents.py.
    file_storage_dir: str = "~/buying-house-files"

    # Redis / Celery — notification outbox dispatch, nightly performance rollups,
    # certificate-expiry sweeps.
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False

    # JWT: session tokens, invite magic links, and supplier save-and-resume links.
    jwt_secret: str = "dev-only-change-me-to-a-32char-plus-random-secret"
    jwt_algorithm: str = "HS256"
    session_token_ttl_hours: int = 12
    invite_token_ttl_days: int = 14
    resume_token_ttl_days: int = 30

    # OTP login for suppliers (low-tech users: phone + 6 digits, no password to forget).
    otp_length: int = 6
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5

    # Object storage — tech packs, certificates, inspection photos.
    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket: str = "buying-house-documents"
    s3_region: str = "us-east-1"

    # Notification channels. Everything writes to the outbox table first (§7); the dispatcher
    # is swappable so WhatsApp Cloud API / Resend drop in later without touching business logic.
    email_backend: str = "console"     # console | smtp
    whatsapp_backend: str = "console"  # console | cloud_api
    email_from: str = "no-reply@buyinghouse.example"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None

    # --- Natural-language record editor (Super Admin only) ---
    # Records only: DML against an allowlist. Schema changes stay in Alembic, where they are
    # reviewed and reversible.
    nlsql_backend: str = "stub"          # stub | claude
    nlsql_model: str = "claude-opus-5"   # do not downgrade for cost without intent
    anthropic_api_key: str | None = None
    nlsql_max_rows: int = 200

    # i18n — keys exist from commit one; only English strings are populated today.
    default_language: str = "en"
    supported_languages: list[str] = ["en", "ta"]

    @property
    def is_local(self) -> bool:
        return self.environment.lower() in {"local", "dev", "development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
