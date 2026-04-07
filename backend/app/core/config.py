"""
Application configuration management.
Loads settings from environment variables using pydantic-settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "re-ink"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str

    # Database
    DATABASE_URL: str

    # Extraction backend: "landingai" (default), "openai", "anthropic", or "free"
    EXTRACTION_BACKEND: str = "landingai"

    # LandingAI Configuration (required only when EXTRACTION_BACKEND=landingai)
    LANDINGAI_API_KEY: str = ""
    LANDINGAI_PARSE_URL: str = "https://api.va.landing.ai/v1/ade/parse"
    LANDINGAI_EXTRACT_URL: str = "https://api.va.landing.ai/v1/ade/extract"
    LANDINGAI_PARSE_MODEL: str = "dpt-2-latest"
    LANDINGAI_EXTRACT_MODEL: str = "extract-latest"

    # Free Extraction Configuration (used when EXTRACTION_BACKEND=free)
    FREE_PARSE_BACKEND: str = "pypdf"            # "pypdf" (text PDFs only) or "glm-ocr" (scanned + complex PDFs)
    FREE_PARSE_MODEL: str = "glm-ocr"            # Ollama model name for parse step (only when FREE_PARSE_BACKEND=glm-ocr)
    FREE_MAX_PAGES: int = 10                     # max pages to process per document (GLM-OCR is slow on CPU)
    FREE_PARSE_DPI: int = 150                    # DPI for PDF→image conversion; 150 is sufficient for clear text
    FREE_LLM_PROVIDER: str = "openai"           # "openai" or "ollama"
    FREE_LLM_MODEL: str = "gpt-4o-mini"         # model name for the chosen provider
    FREE_OLLAMA_BASE_URL: str = "http://localhost:11434"  # Ollama server URL

    # OpenAI Configuration
    OPENAI_API_KEY: str = ""

    # Anthropic Configuration
    ANTHROPIC_API_KEY: str = ""

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
