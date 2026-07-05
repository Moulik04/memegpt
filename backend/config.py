from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM provider: "ollama" (local) | "groq" (cloud, free tier)
    llm_provider: str = "ollama"

    # Ollama — local inference (default for dev)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # Groq — cloud inference, free tier (https://console.groq.com)
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.6-27b"

    # Multimodal — image uploads (Phase 0 safety gate + Phase 1 vision)
    max_image_bytes: int = 10 * 1024 * 1024   # 10MB
    max_image_dimension_px: int = 8000
    moderation_model: str = "qwen/qwen3.6-27b"  # vision model + safety rubric — see uploads/moderation.py
    vision_provider: str = "groq"
    vision_model: str = "qwen/qwen3.6-27b"       # same model already used for text routing
    anthropic_api_key: str = ""                    # optional vision fallback — see nlp/vision.py
    anthropic_model: str = "claude-sonnet-5"
    upload_rate_limit: str = "5/minute"
    upload_retention_seconds: int = 3600

    # Multi-context, multi-meme generation — see nlp/segmentation.py
    max_memes_per_request: int = 5     # requested_count is clamped to this, never rejected
    max_images_per_request: int = 6    # independent of the above — bounds moderation/vision cost
    segmentation_text_threshold_chars: int = 240  # longer text triggers segmentation
    max_dump_chars: int = 20000  # Lore mode's big-paste ceiling — clamped, never rejected

    # ChromaDB — empty string = embedded PersistentClient (local dev)
    #            set to service name (e.g. "vector-db") → HttpClient (Docker)
    chroma_host: str = ""
    chroma_port: int = 8000

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # CORS — set CORS_ALLOW_ALL_ORIGINS=true in production (Render/Railway)
    cors_allow_all_origins: bool = False
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
