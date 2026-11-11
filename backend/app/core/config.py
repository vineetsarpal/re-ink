"""
Application configuration management.
Loads settings from environment variables using pydantic-settings.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
from typing import List
import base64
import binascii
import re
from urllib.parse import urlsplit


def _decoded_secret(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid Cloudflare signing key") from exc
    if len(raw) != 32:
        raise ValueError("Cloudflare signing key must be 32 bytes")
    return raw


def _database_target(url):
    host = (url.host or "").lower()
    # Neon uses the same endpoint name with a -pooler suffix for pooled access.
    if host.endswith(".aws.neon.tech"):
        first, dot, rest = host.partition(".")
        host = first.removesuffix("-pooler") + dot + rest
    return host, url.port or 5432, url.database

def _read_version() -> str:
    """
    Read version from VERSION file (backend/ or repo root).
    Falls back to pyproject.toml, then 'dev'.
    """
    # Injected by CI deploy workflow into backend/
    local = Path(__file__).parents[2] / "VERSION"
    if local.exists():
        return local.read_text().strip()
    # Repo root (works in local dev when full repo is present)
    root = Path(__file__).parents[3] / "VERSION"
    if root.exists():
        return root.read_text().strip()
    return "dev"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "re-ink"
    APP_VERSION: str = _read_version()
    DEBUG: bool = False

    # Database
    DATABASE_URL: str
    PROVIDER_CREDENTIAL_ENCRYPTION_KEY: str = Field(default="", repr=False)

    # Disabled until the complete asynchronous trial path is configured.
    EXTRACTION_QUOTA_ENABLED: bool = False
    EXTRACTION_MONTHLY_LIMIT: int = Field(default=50, ge=0)
    EXTRACTION_FREE_LIMIT: int = Field(default=5, ge=0)
    EXTRACTION_MONTHLY_ATTEMPT_LIMIT: int = Field(default=200, ge=0)
    EXTRACTION_ATTEMPTS_PER_MINUTE: int = Field(default=10, ge=1)
    EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT: int = Field(default=0, ge=0)
    EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT: int = Field(default=0, ge=0)
    CLEANUP_BATCH_LIMIT: int = Field(default=25, ge=1, le=200)
    CLEANUP_TIME_BUDGET_SECONDS: float = Field(default=10, gt=0, le=12)
    LANDINGAI_TRIAL_API_KEY: str = Field(default="", repr=False)
    WORKFLOW_QUEUE_TIMEOUT_SECONDS: int = Field(default=600, gt=0)
    WORKFLOW_PROCESSING_TIMEOUT_SECONDS: int = Field(default=600, gt=0)
    WORKFLOW_LEASE_SECONDS: int = Field(default=60, gt=0)
    CLOUDFLARE_ENABLED: bool = False
    CLOUDFLARE_TRIAL_ENABLED: bool = False
    TRIAL_ALLOWED_ORGANIZATION_IDS: List[str] = Field(default_factory=list)
    CLOUDFLARE_MACHINE_DATABASE_URL: str = Field(default="", repr=False)
    CLOUDFLARE_DISPATCH_DATABASE_URL: str = Field(default="", repr=False)
    CLOUDFLARE_EXPIRY_DATABASE_URL: str = Field(default="", repr=False)
    CLOUDFLARE_CLEANUP_DATABASE_URL: str = Field(default="", repr=False)
    CLOUDFLARE_MACHINE_TOKEN: str = Field(default="", repr=False)
    CLOUDFLARE_DISPATCH_TOKEN: str = Field(default="", repr=False)
    CLOUDFLARE_EXPIRY_TOKEN: str = Field(default="", repr=False)
    CLOUDFLARE_CLEANUP_TOKEN: str = Field(default="", repr=False)
    CLOUDFLARE_CAPABILITY_KEY: str = Field(default="", repr=False)
    CLOUDFLARE_PREVIOUS_CAPABILITY_KEY: str = Field(default="", repr=False)
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_QUEUE_ID: str = ""
    CLOUDFLARE_QUEUE_API_TOKEN: str = Field(default="", repr=False)

    # WorkOS Authentication
    # The issuer and JWKS URL for access-token validation are derived from the
    # client id. The API key is only needed for server-side WorkOS API calls
    # (not used in the auth slice), so it defaults to empty.
    WORKOS_CLIENT_ID: str = ""
    WORKOS_API_KEY: str = ""

    # LandingAI Configuration
    LANDINGAI_API_KEY: str = ""
    LANDINGAI_PARSE_URL: str = "https://api.va.landing.ai/v1/ade/parse"
    LANDINGAI_EXTRACT_URL: str = "https://api.va.landing.ai/v1/ade/extract"
    LANDINGAI_PARSE_MODEL: str = "dpt-2-latest"
    LANDINGAI_EXTRACT_MODEL: str = "extract-latest"

    # LLM Provider Configuration
    # Supported values: "openai", "ollama"
    LLM_PROVIDER: str = "openai"

    # OpenAI Configuration
    OPENAI_API_KEY: str = ""

    # Ollama Configuration
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1"

    # Agent Configuration
    AGENT_OFFLINE_MODE: bool = False
    AGENT_MODEL: str = "gpt-4o"
    AGENT_TEMPERATURE: float = 0.1

    # File Upload
    MAX_UPLOAD_SIZE: int = 52428800  # 50MB default
    UPLOAD_DIR: str = "./uploads"
    ALLOWED_EXTENSIONS: List[str] = Field(default=[".pdf", ".docx"])

    # Private storage for the optional asynchronous extraction path.
    STORAGE_BACKEND: str = "r2"
    R2_ENDPOINT_URL: str = ""
    R2_BUCKET: str = ""
    R2_REGION: str = "auto"
    R2_ACCESS_KEY_ID: str = Field(default="", repr=False)
    R2_SECRET_ACCESS_KEY: str = Field(default="", repr=False)

    @model_validator(mode="after")
    def validate_cloudflare_configuration(self):
        if self.CLOUDFLARE_TRIAL_ENABLED and (not self.CLOUDFLARE_ENABLED or not self.EXTRACTION_QUOTA_ENABLED
                or not self.LANDINGAI_TRIAL_API_KEY or self.EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT <= 0
                or self.EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT <= 0):
            raise ValueError("Cloudflare trial requires quotas, a trial key, and positive global limits")
        if not self.CLOUDFLARE_ENABLED:
            return self
        from sqlalchemy.engine import make_url
        try:
            urls = [make_url(value) for value in (self.CLOUDFLARE_MACHINE_DATABASE_URL,
                    self.CLOUDFLARE_DISPATCH_DATABASE_URL, self.CLOUDFLARE_EXPIRY_DATABASE_URL,
                    self.CLOUDFLARE_CLEANUP_DATABASE_URL)]
            app_url = make_url(self.DATABASE_URL)
            app_identity = app_url.username
        except Exception as exc:
            raise ValueError("Invalid Cloudflare database configuration") from exc
        if (not app_identity or any(u.get_backend_name() != "postgresql" or not u.host or not u.username
                                    or u.query.get("sslmode") != "verify-full" for u in urls)
                or len({app_identity, *(u.username for u in urls)}) != 5):
            raise ValueError("Cloudflare databases require separate PostgreSQL identities and verified TLS")
        target = _database_target(app_url)
        if (app_url.get_backend_name() != "postgresql" or not target[0] or not target[2]
                or any(_database_target(url) != target for url in urls)):
            raise ValueError("Cloudflare and application connections must target the same database")
        tokens = (self.CLOUDFLARE_MACHINE_TOKEN, self.CLOUDFLARE_DISPATCH_TOKEN,
                  self.CLOUDFLARE_EXPIRY_TOKEN, self.CLOUDFLARE_CLEANUP_TOKEN)
        if len(set(tokens)) != 4 or any(len(s) < 32 or not s.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in s) for s in tokens):
            raise ValueError("Cloudflare machine credentials must be distinct printable secrets")
        signing = _decoded_secret(self.CLOUDFLARE_CAPABILITY_KEY)
        encryption = _decoded_secret(self.PROVIDER_CREDENTIAL_ENCRYPTION_KEY)
        if signing == encryption or (self.CLOUDFLARE_PREVIOUS_CAPABILITY_KEY and
                _decoded_secret(self.CLOUDFLARE_PREVIOUS_CAPABILITY_KEY) in (signing, encryption)):
            raise ValueError("Cloudflare signing and encryption keys must differ")
        if (not re.fullmatch(r"[0-9a-fA-F]{32}", self.CLOUDFLARE_ACCOUNT_ID)
                or not re.fullmatch(r"[0-9a-fA-F]{32}", self.CLOUDFLARE_QUEUE_ID)
                or not self.CLOUDFLARE_QUEUE_API_TOKEN or not self.CLOUDFLARE_QUEUE_API_TOKEN.isascii()
                or any(ord(c) < 33 or ord(c) > 126 for c in self.CLOUDFLARE_QUEUE_API_TOKEN)):
            raise ValueError("Cloudflare queue configuration is incomplete")
        endpoint = urlsplit(self.R2_ENDPOINT_URL)
        if (self.STORAGE_BACKEND != "r2" or endpoint.scheme != "https" or not endpoint.hostname
                or not all((self.R2_BUCKET, self.R2_ACCESS_KEY_ID, self.R2_SECRET_ACCESS_KEY))):
            raise ValueError("Cloudflare extraction requires private R2 storage configuration")
        if self.WORKFLOW_QUEUE_TIMEOUT_SECONDS + self.WORKFLOW_PROCESSING_TIMEOUT_SECONDS + 60 > 3600:
            raise ValueError("Cloudflare capability lifetime is shorter than workflow timeouts")
        return self

    # CORS
    # Note: In .env file, use JSON format: ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
    ALLOWED_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:5173"])

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        env_ignore_empty=True,
        hide_input_in_errors=True,
        # Ignore unknown env vars so retired settings in CI/deploy envs don't
        # break startup.
        extra="ignore",
    )


# Global settings instance
settings = Settings()
