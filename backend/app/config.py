"""Application settings, loaded from environment / .env (pydantic-settings)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: str = "local"
    app_base_url: str = "http://localhost:3000"

    # Database. pgvector is enabled in the first migration so Phase 6 only has to add columns.
    database_url: str = "postgresql+psycopg://bh:bh@localhost:5432/buyinghouse"

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
