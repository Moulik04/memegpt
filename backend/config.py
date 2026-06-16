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
    groq_model: str = "llama-3.1-8b-instant"

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
