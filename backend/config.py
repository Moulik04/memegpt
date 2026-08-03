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
    # Resilience follow-up: Groq's rate limits are per-model (confirmed
    # live against their docs — each model gets its own separate RPM/RPD/
    # TPM/TPD budget, not a shared account-wide pool), so a second model
    # is a genuine fallback, not a no-op. openai/gpt-oss-120b is the exact
    # model scripts/eval_intent_models.py already evaluated as the best
    # available secondary — less reliable than qwen (~25%+ genuine
    # json-parse failure rate in that eval), but still a real fallback
    # ahead of the static hardcoded meme. Empty string disables the
    # fallback attempt entirely, matching this file's existing "empty =
    # disabled" convention (e.g. anthropic_api_key).
    groq_fallback_model: str = "openai/gpt-oss-120b"

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

    # Watermark — see image_processing/compositor.py's _draw_watermark()
    watermark_enabled: bool = True
    watermark_text: str = "memegpt"

    # Gemini embeddings (fixes Render's 512MB OOM — replaces ChromaDB's
    # default in-process local embedding model with a hosted API call).
    # Empty = local embedding fallback, the zero-cost/zero-config default
    # for local dev. See vector_db/gemini_embedding_function.py.
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-2"

    # Durable storage (Growth Phase B) — see storage/ and db/.
    # All empty by default: local disk + no Postgres is the fully-functional
    # zero-cost fallback, not a degraded mode. Setting these switches
    # storage.save_meme() to Cloudflare R2 and enables the Postgres layer.
    database_url: str = ""
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_public_base_url: str = ""

    # ChromaDB — empty string = embedded PersistentClient (local dev)
    #            set to service name (e.g. "vector-db") → HttpClient (Docker)
    chroma_host: str = ""
    chroma_port: int = 8000

    # Growth Phase G — Discord /meme slash command. Discord's own ed25519
    # signature verification happens in the Cloudflare Worker (the entity
    # Discord actually talks to, not this backend — see routers/discord.py's
    # module docstring for why), so this backend never needs
    # discord_public_key for verification; it's declared here anyway,
    # alongside discord_app_id, purely so a developer can keep both in
    # backend/.env without pydantic-settings' strict extra="forbid"
    # rejecting the whole Settings object on startup. discord_bot_token is
    # only ever needed transiently for the one-time slash-command
    # registration call — also declared here for the same reason.
    # discord_worker_shared_secret is the only one the backend actually
    # checks (routers/discord.py) — an internal Worker<->backend secret,
    # not a Discord credential at all.
    discord_app_id: str = ""
    discord_public_key: str = ""
    discord_bot_token: str = ""
    discord_worker_shared_secret: str = ""
    discord_rate_limit: str = "20/minute"

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
