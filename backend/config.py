# backend/config.py
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str    = Field(default="AI Content Studio")
    app_version: str = Field(default="1.0.0")
    debug: bool      = Field(default=True)
    backend_url: str = Field(default="http://localhost:8000")

    # ── LLM ──────────────────────────────────────────────────────────────────
    groq_api_key: str = Field(default="")
    groq_model: str   = Field(default="llama-3.3-70b-versatile")

    # ── Web Search ───────────────────────────────────────────────────────────
    tavily_api_key: str = Field(default="")

    # ── Security ─────────────────────────────────────────────────────────────
    api_secret_key: str = Field(default="")  # MUST be set in .env
    api_key_header: str = Field(default="X-API-Key")
    master_api_key: str = Field(default="")  # MUST be set in .env — no default allowed

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, e.g. "https://myapp.hf.space"
    # Set to "*" ONLY for local dev. Always restrict in production.
    allowed_origins: str = Field(default="http://localhost:8501,http://localhost:8000")

    # ── Rate Limiting ────────────────────────────────────────────────────────
    rate_limit_requests: int = Field(default=60)
    rate_limit_window:   int = Field(default=60)

    # ── RAG ──────────────────────────────────────────────────────────────────
    chunk_size:          int   = Field(default=512)
    chunk_overlap:       int   = Field(default=50)
    top_k_retrieval:     int   = Field(default=5)
    rerank_top_n:        int   = Field(default=3)
    similarity_threshold: float = Field(default=0.3)

    # ── Agents ───────────────────────────────────────────────────────────────
    max_retries:        int   = Field(default=3)
    critique_threshold: float = Field(default=0.75)
    max_search_results: int   = Field(default=5)

    # ── Cache ────────────────────────────────────────────────────────────────
    cache_similarity_threshold: float = Field(default=0.92)
    cache_max_size:             int   = Field(default=100)

    # ── Paths ────────────────────────────────────────────────────────────────
    faiss_db_path:       str = Field(default="./data/faissdb")
    knowledge_base_path: str = Field(default="./data/knowledge_base")

    # ── Twitter/X ────────────────────────────────────────────────────────────
    twitter_api_key:      str = Field(default="")
    twitter_api_secret:   str = Field(default="")
    twitter_access_token: str = Field(default="")
    twitter_access_secret: str = Field(default="")
    twitter_bearer_token:  str = Field(default="")
    twitter_client_id:     str = Field(default="")
    twitter_client_secret: str = Field(default="")

    # ── LinkedIn ─────────────────────────────────────────────────────────────
    linkedin_client_id:     str = Field(default="")
    linkedin_client_secret: str = Field(default="")
    linkedin_access_token:  str = Field(default="")

    # ── Dev.to ───────────────────────────────────────────────────────────────
    devto_api_key: str = Field(default="")

    # ── Bluesky (free API, instant setup) ────────────────────────────────────
    bluesky_handle:       str = Field(default="")
    bluesky_app_password: str = Field(default="")

    # ── Gemini (optional — for image prompts) ─────────────────────────────────
    gemini_api_key: str = Field(default="")
    gemini_model:   str = Field(default="gemini-2.0-flash")

    # ─── Pexels (free contextual stock photos — pexels.com/api) ───────────────
    pexels_api_key: str = Field(default="")
    pixabay_api_key: str = Field(default="")

        # ─── Telegram Bot (free, instant — t.me/BotFather) ─────────────────────────
    telegram_bot_token:  str = Field(default="")    # from @BotFather
    telegram_channel_id: str = Field(default="")    # TELEGRAM_CHANNEL_ID in .env — @channelname
    telegram_chat_id:    str = Field(default="")    # legacy alias — use TELEGRAM_CHANNEL_ID

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",   # ← ignores any extra .env keys not defined here
    }

    def get_faiss_path(self) -> Path:
        p = Path(self.faiss_db_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_knowledge_base_path(self) -> Path:
        p = Path(self.knowledge_base_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def publishing_configured(self) -> dict:
        return {
            "twitter": all([
                self.twitter_api_key, self.twitter_api_secret,
                self.twitter_access_token, self.twitter_access_secret,
            ]),
            "linkedin": bool(self.linkedin_client_id and self.linkedin_access_token),
            "blog":     bool(self.devto_api_key),
            "bluesky":  bool(self.bluesky_handle and self.bluesky_app_password),
            "images":   True,
        }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def validate_settings() -> bool:
    s = get_settings()
    errors = []
    if not s.groq_api_key:   errors.append("❌ GROQ_API_KEY missing")
    if not s.tavily_api_key: errors.append("❌ TAVILY_API_KEY missing")
    if errors:
        print("\n".join(errors))
        return False
    print("✅ All core settings validated")
    print(f"   Model: {s.groq_model}")
    pub   = s.publishing_configured()
    ready = [k for k,v in pub.items() if v and k != "images"]
    not_r = [k for k,v in pub.items() if not v and k != "images"]
    if ready: print(f"   Publishing ready:        {ready}")
    if not_r: print(f"   Publishing not configured: {not_r}")
    return True