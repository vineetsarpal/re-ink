"""
Application configuration management.
Loads settings from environment variables using pydantic-settings.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
from typing import List
from urllib.parse import urlsplit

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

    # The customer workflow integration stays unavailable until configured.
    WORKFLOW_CUSTOMER_ORG_ID: str = ""
    WORKFLOW_WEBHOOK_URL: str = ""
    WORKFLOW_DISPATCH_TOKEN: str = Field(default="", repr=False)
    WORKFLOW_SERVICE_TOKEN: str = Field(default="", repr=False)
    WORKFLOW_WORKER_DATABASE_URL: str = Field(default="", repr=False)
    WORKFLOW_QUEUE_TIMEOUT_SECONDS: int = Field(default=600, gt=0)
    WORKFLOW_PROCESSING_TIMEOUT_SECONDS: int = Field(default=600, gt=0)
    WORKFLOW_LEASE_SECONDS: int = Field(default=60, gt=0)
    WORKFLOW_HTTP_TIMEOUT_SECONDS: int = Field(default=20, gt=0)
    WORKFLOW_UPLOADS_ENABLED: bool = False

    STORAGE_BACKEND: str = "r2"
    R2_ENDPOINT_URL: str = ""
    R2_BUCKET: str = ""
    R2_REGION: str = "auto"
    R2_ACCESS_KEY_ID: str = Field(default="", repr=False)
    R2_SECRET_ACCESS_KEY: str = Field(default="", repr=False)

    @model_validator(mode="after")
    def validate_workflow_configuration(self):
        for name in ("WORKFLOW_WEBHOOK_URL", "R2_ENDPOINT_URL"):
            value = getattr(self, name)
            if value:
                parsed = urlsplit(value)
                if (parsed.scheme != "https" or not parsed.hostname
                        or parsed.username or parsed.password or parsed.fragment
                        or parsed.query):
                    raise ValueError(f"{name} must be a trusted HTTPS URL without credentials, query or fragment")
        for name in ("WORKFLOW_DISPATCH_TOKEN", "WORKFLOW_SERVICE_TOKEN"):
            value = getattr(self, name)
            if value and (len(value) < 32 or value.strip() != value):
                raise ValueError(f"{name} must contain at least 32 characters without surrounding whitespace")
        if (self.WORKFLOW_SERVICE_TOKEN and self.WORKFLOW_SERVICE_TOKEN == self.WORKFLOW_DISPATCH_TOKEN):
            raise ValueError("Workflow credentials must differ for independent revocation")
        if self.WORKFLOW_HTTP_TIMEOUT_SECONDS >= self.WORKFLOW_LEASE_SECONDS:
            raise ValueError("Workflow HTTP timeout must be shorter than the dispatch lease")
        if self.WORKFLOW_UPLOADS_ENABLED and not self.workflow_configured:
            raise ValueError("Workflow uploads require complete integration configuration")
        return self

    @property
    def workflow_configured(self) -> bool:
        return bool(self.WORKFLOW_CUSTOMER_ORG_ID and self.WORKFLOW_WEBHOOK_URL
                    and self.WORKFLOW_DISPATCH_TOKEN and self.WORKFLOW_SERVICE_TOKEN)

    @property
    def WORKFLOW_CONFIGURED(self) -> bool:
        return self.workflow_configured

    # WorkOS Authentication
    # The issuer and JWKS URL for access-token validation are derived from the
    # client id. The API key is only needed for server-side WorkOS API calls
    # (not used in the auth slice), so it defaults to empty.
    WORKOS_CLIENT_ID: str = ""
    WORKOS_API_KEY: str = ""

    # File Upload
    MAX_UPLOAD_SIZE: int = 52428800  # 50MB default
    UPLOAD_DIR: str = "./uploads"
    ALLOWED_EXTENSIONS: List[str] = Field(default=[".pdf", ".docx"])

    # CORS
    # Note: In .env file, use JSON format: ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
    ALLOWED_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:5173"])

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        hide_input_in_errors=True,
        env_ignore_empty=True,
        # Ignore unknown env vars so retired settings in CI/deploy envs don't
        # break startup.
        extra="ignore",
    )


# Global settings instance
settings = Settings()
