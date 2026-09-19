"""
Application settings loaded from environment variables using pydantic-settings.
All API keys, feature flags, and tuning parameters are defined here.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Central configuration — all values come from environment variables."""

    # --- Groq API keys (3x for rotation, §15) ---
    GROQ_API_KEY_1: str = ""
    GROQ_API_KEY_2: str = ""
    GROQ_API_KEY_3: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # --- OpenRouter API keys (3x for rotation, §15) ---
    OPENROUTER_API_KEY_1: str = ""
    OPENROUTER_API_KEY_2: str = ""
    OPENROUTER_API_KEY_3: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "meta-llama/llama-3.1-8b-instruct:free"

    # --- Gemini API keys (3x for rotation, §15) ---
    GEMINI_API_KEY_1: str = ""
    GEMINI_API_KEY_2: str = ""
    GEMINI_API_KEY_3: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # --- Cohere API key (reranking, §5) ---
    COHERE_API_KEY: str = ""
    COHERE_RERANK_MODEL: str = "rerank-english-v3.0"

    # --- Telegram notifications (§16) ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    NOTIFICATION_COOLDOWN_SECONDS: int = 600  # 10 min per alert type

    # --- CORS (§8) ---
    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:3000"]
    )

    # --- Embedding model (§2) ---
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_BATCH_SIZE: int = 32

    # --- Qdrant paths (§3) ---
    QDRANT_BASE_PATH: str = "/app/data/qdrant_base"
    QDRANT_BASE_COLLECTION: str = "base_knowledge"

    # --- Knowledge base (§3) ---
    KNOWLEDGE_BASE_DIR: str = "knowledge_base"

    # --- Chunking parameters (§10) ---
    PARENT_CHUNK_TARGET_SIZE: int = 1750  # midpoint of 1500-2000
    CHILD_CHUNK_SIZE: int = 400
    CHILD_CHUNK_OVERLAP: int = 80
    CHILD_CHUNK_SEPARATORS: list[str] = Field(
        default=["\n\n", "\n", ". ", " "]
    )

    # --- Retrieval parameters (§10) ---
    DENSE_TOP_K: int = 20
    BM25_TOP_K: int = 20
    ENSEMBLE_DENSE_WEIGHT: float = 0.6
    ENSEMBLE_SPARSE_WEIGHT: float = 0.4
    RERANK_CANDIDATES_CAP: int = 30
    RERANK_TOP_N: int = 5
    RELEVANCE_THRESHOLD: float = 0.3
    RERANK_TIMEOUT: float = 5.0  # seconds

    # --- Upload limits (§10) ---
    MAX_FILE_SIZE_MB: int = 15
    MAX_TOTAL_UPLOAD_MB: int = 50
    MIN_EXTRACTED_TEXT_CHARS: int = 200

    # --- Session management (§10) ---
    SESSION_TTL_MINUTES: int = 30
    SESSION_SWEEP_INTERVAL_SECONDS: int = 120  # sweep every 2 min

    # --- LLM parameters (§10) ---
    LLM_TIMEOUT: float = 15.0  # seconds per provider attempt
    SUMMARY_MAX_TOKENS: int = 200

    # --- Rate limiting (§10) ---
    RATE_LIMIT: str = "20/minute"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }

    @property
    def groq_keys(self) -> list[str]:
        """Return list of non-empty Groq API keys."""
        return [k for k in [self.GROQ_API_KEY_1, self.GROQ_API_KEY_2, self.GROQ_API_KEY_3] if k]

    @property
    def openrouter_keys(self) -> list[str]:
        """Return list of non-empty OpenRouter API keys."""
        return [k for k in [self.OPENROUTER_API_KEY_1, self.OPENROUTER_API_KEY_2, self.OPENROUTER_API_KEY_3] if k]

    @property
    def gemini_keys(self) -> list[str]:
        """Return list of non-empty Gemini API keys."""
        return [k for k in [self.GEMINI_API_KEY_1, self.GEMINI_API_KEY_2, self.GEMINI_API_KEY_3] if k]


settings = Settings()

