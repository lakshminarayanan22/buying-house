"""Application settings, loaded from environment / .env (pydantic-settings)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: str = "local"
    app_base_url: str = "http://localhost:3000"

    # Database. pgvector is enabled in the first migration so Phase 6 only has to add columns.
    database_url: str = "postgresql+psycopg://bh:bh@localhost:5432/ecolink"

    # --- Sign-in ---
    # Google is the front door; only this Workspace domain gets through it. `hd` is checked as
    # well as the address, because `hd` is set by Google from the Workspace an account belongs
    # to and cannot be chosen by the person signing in.
    #
    # google: verify real ID tokens. Needs GOOGLE_CLIENT_ID.
    # stub:   accept a typed address as if Google had vouched for it, so the approval flow can
    #         be exercised with no Google project. Refused outright outside a local environment
    #         — see check_sign_in_config().
    google_auth_backend: str = "stub"
    google_client_id: str | None = None
    allowed_email_domain: str = "ecolinksolutions.in"
    # Comma-separated. These addresses are approved as ADMIN on their first Google sign-in, which
    # is how the very first request ever gets approved. Adding someone here later also promotes
    # them the next time they sign in.
    bootstrap_admin_emails: str = ""
    password_min_length: int = 10

    @property
    def bootstrap_admins(self) -> set[str]:
        return {e.strip().lower() for e in self.bootstrap_admin_emails.split(",") if e.strip()}

    # --- Chatbot ---
    # stub: keyword routing and templated answers. No key, no spend, and it makes the graph
    #       testable. It is not a chatbot and reindex-style warnings say so.
    # ollama: a local open model — Qwen by default. Free, no key, nothing leaves the machine.
    #         For trying the whole flow before paying for anything; weaker than Claude at
    #         text-to-SQL, so judge the system's design on it, not its ceiling.
    # claude: the real thing.
    llm_backend: str = "stub"
    anthropic_api_key: str | None = None
    classifier_model: str = "claude-haiku-4-5-20251001"
    branch_model: str = "claude-sonnet-5"
    # Ollama. One model serves both the classifier and the branches: a second local model
    # would double the memory held, on a machine that is also running Postgres and the app.
    ollama_model: str = "qwen3:8b"
    # Optional SQL specialist for the one step that writes queries, e.g.
    # hf.co/mradermacher/XiYanSQL-QwenCoder-7B-2504-GGUF:Q4_K_M. Classifying and phrasing stay
    # on ollama_model: a SQL-trained model is not built for prose. Unset = one model for all.
    ollama_sql_model: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    # Ollama's default context is a few thousand tokens and it truncates from the *front*,
    # silently — the database prompt carries the whole schema, so an overflow would cut the
    # schema off and leave the model inventing columns. 16K holds schema + question + rows.
    ollama_num_ctx: int = 16384
    classifier_confidence_floor: float = 0.6
    allow_secondary_category: bool = True
    sql_statement_timeout_ms: int = 2000
    sql_row_cap: int = 500
    database_url_readonly: str | None = None

    # --- Retrieval ---
    # stub: deterministic, no network, no model download. Exercises the pipeline and the
    #       lexical half of hybrid search honestly; the vector half is meaningless.
    # voyage: voyage-4-large, 1024 dimensions. Needs VOYAGE_API_KEY. (voyage-3, the original
    #         choice, is legacy as of 2026; voyage-4 and voyage-4-lite are cheaper and also
    #         1024-d, so switching between them needs a reindex but no migration.)
    # local: sentence-transformers. Needs the package and a model download.
    embedding_backend: str = "stub"
    embedding_model: str = "voyage-4-large"
    embedding_dimensions: int = 1024
    voyage_api_key: str | None = None

    # Semantic-only matches below this are dropped; keyword matches always survive. 0.40 was a
    # guess made when only stub vectors existed. First probes with voyage-4-large (Sept 2026):
    # a reworded question matched its document at 0.37, an unrelated one topped out at 0.16.
    # 0.30 keeps the first and refuses the second. Provisional — retune with
    # scripts/eval_retrieval.py once real brochures are uploaded.
    similarity_floor: float = 0.30
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

    # Email — used to tell admins someone is waiting, and to tell that person they are in.
    # console: log the message instead of sending it.
    # smtp:    send it. On Google Workspace that is smtp.gmail.com:587 with an app password for
    #          the sending mailbox, or smtp-relay.gmail.com if the Workspace admin prefers the
    #          relay. docs/sign-in.md has the steps.
    email_backend: str = "console"     # console | smtp
    whatsapp_backend: str = "console"  # console | cloud_api
    email_from: str = "Ecolink <no-reply@ecolinksolutions.in>"
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

    def check_sign_in_config(self) -> None:
        """Refuse to start with a sign-in setup that would let the wrong people in.

        The stub backend believes whatever address it is given. That is the point of it on a
        laptop and a hole anywhere else, so outside a local environment it is a startup error
        rather than a warning somebody might not read.
        """
        backend = self.google_auth_backend.lower()
        if backend not in {"google", "stub"}:
            raise RuntimeError(f"GOOGLE_AUTH_BACKEND must be 'google' or 'stub', not {backend!r}")
        if backend == "stub" and not self.is_local:
            raise RuntimeError(
                "GOOGLE_AUTH_BACKEND=stub accepts any typed address and is only allowed when "
                f"ENVIRONMENT is local. ENVIRONMENT is {self.environment!r}."
            )
        if backend == "google" and not self.google_client_id:
            raise RuntimeError("GOOGLE_AUTH_BACKEND=google needs GOOGLE_CLIENT_ID")
        if "@" in self.allowed_email_domain or not self.allowed_email_domain.strip():
            raise RuntimeError("ALLOWED_EMAIL_DOMAIN is a bare domain, e.g. ecolinksolutions.in")
        if not self.is_local and self.jwt_secret.startswith("dev-only"):
            raise RuntimeError("JWT_SECRET is still the development default")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
