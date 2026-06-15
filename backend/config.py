from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Ollama local inference server
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # ChromaDB — empty string = embedded PersistentClient (local dev)
    #            set to service name (e.g. "vector-db") → HttpClient (Docker)
    chroma_host: str = ""
    chroma_port: int = 8000

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # CORS — all common local dev ports; set CORS_ORIGINS in .env for production
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
