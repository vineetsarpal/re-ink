"""
Application configuration management.
Loads settings from environment variables using pydantic-settings.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List


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
    SECRET_KEY: str

    # Database
    DATABASE_URL: str

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

    # CORS
    # Note: In .env file, use JSON format: ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
    ALLOWED_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:5173"])

    # Security
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        env_ignore_empty=True,
    )


# Global settings instance
settings = Settings()
