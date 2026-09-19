"""
Application configuration loaded from environment variables.
"""

from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Groq (Primary LLM) ---
    GROQ_API_KEY_1: str = ""
    GROQ_API_KEY_2: str = ""
    GROQ_API_KEY_3: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-20b"

    # --- OpenRouter (Fallback LLM) ---
    OPENROUTER_API_KEY_1: str = ""
    OPENROUTER_API_KEY_2: str = ""
    OPENROUTER_API_KEY_3: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "meta-llama/llama-3.1-8b-instruct:free"

    # --- Google Gemini (Fallback LLM) ---
    GEMINI_API_KEY_1: str = ""
    GEMINI_API_KEY_2: str = ""
    GEMINI_API_KEY_3: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # --- Cohere Reranker (Primary) ---
    COHERE_API_KEY: str = ""
    COHERE_RERANK_MODEL: str = "rerank-english-v3.0"

    # --- FlashRank Reranker (Local Fallback) ---
    RERANKER_MODEL: str = "ms-marco-MiniLM-L-12-v2"

    # --- Embedding model ---
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_BATCH_SIZE: int = 32

    # --- Qdrant Cloud ---
    QDRANT_CLOUD_URL: str = ""
    QDRANT_CLOUD_API_KEY: str = ""
    QDRANT_BASE_PATH: str = "/app/data/qdrant_base"
    QDRANT_BASE_COLLECTION: str = "base_knowledge"

    # --- Knowledge Base Directory ---
    KNOWLEDGE_BASE_DIR: str = "knowledge_base"

    # --- Chunking & Retrieval parameters ---
    PARENT_CHUNK_TARGET_SIZE: int = 1750
    PARENT_CHUNK_OVERLAP: int = 0
    CHILD_CHUNK_TARGET_SIZE: int = 400
    CHILD_CHUNK_OVERLAP: int = 80

    DENSE_TOP_K: int = 20
    BM25_TOP_K: int = 20
    ENSEMBLE_DENSE_WEIGHT: float = 0.6
    ENSEMBLE_SPARSE_WEIGHT: float = 0.4
    RERANK_CANDIDATES_CAP: int = 30
    RERANK_TOP_N: int = 5
    RELEVANCE_THRESHOLD: float = 0.3

    # --- Sessions & Limits ---
    SESSION_TTL_MINUTES: int = 30
    RATE_LIMIT_PER_MINUTE: int = 10
    MAX_UPLOAD_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    # --- CORS ---
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "*"]
    )

    @property
    def groq_keys(self) -> List[str]:
        return [k for k in [self.GROQ_API_KEY_1, self.GROQ_API_KEY_2, self.GROQ_API_KEY_3] if k]

    @property
    def openrouter_keys(self) -> List[str]:
        return [k for k in [self.OPENROUTER_API_KEY_1, self.OPENROUTER_API_KEY_2, self.OPENROUTER_API_KEY_3] if k]

    @property
    def gemini_keys(self) -> List[str]:
        return [k for k in [self.GEMINI_API_KEY_1, self.GEMINI_API_KEY_2, self.GEMINI_API_KEY_3] if k]


settings = Settings()
