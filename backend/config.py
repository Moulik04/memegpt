from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Required — must be set in .env or environment
    anthropic_api_key: str

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # CORS — comma-separated origins allowed for browser access
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("anthropic_api_key")
    @classmethod
    def key_must_not_be_placeholder(cls, v: str) -> str:
        if not v or v.startswith("sk-ant-YOUR"):
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Copy backend/.env.example to backend/.env "
                "and fill in your key from https://console.anthropic.com/"
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
