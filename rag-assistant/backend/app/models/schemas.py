"""
Pydantic data models — exact schemas from SPEC.md §7.
"""

from pydantic import BaseModel
from typing import Literal, Optional


class ChunkMetadata(BaseModel):
    """Metadata for a single child chunk stored in Qdrant."""
    chunk_id: str
    parent_id: str
    filename: str
    page_number: int
    source_type: Literal["base", "user"]
    parent_text: str   # full parent chunk, returned to LLM
    child_text: str    # the embedded/matched text


class Citation(BaseModel):
    """A single citation in an answer, mapping a bracket marker to its source."""
    marker: int
    filename: str
    page_number: int
    source_type: Literal["base", "user"]
    snippet: str  # verbatim, not paraphrased


class AskRequest(BaseModel):
    """Request body for POST /ask."""
    session_id: str
    question: str


class AskResponse(BaseModel):
    """Final response payload from POST /ask."""
    answer: str
    citations: list[Citation]
    provider_used: str  # "groq" | "openrouter" | "gemini"


class UploadResponse(BaseModel):
    """Response payload from POST /upload."""
    session_id: str
    filename: str
    pages_processed: int
    chunks_created: int
    status: Literal["success", "rejected"]
    reason: str | None = None  # populated if rejected


class SessionState(BaseModel):
    """In-memory state for a single user session."""
    session_id: str
    created_at: float
    last_active: float
    running_summary: str = ""
    last_turn: tuple[str, str] | None = None  # (question, answer)
    has_uploaded_docs: bool = False
    total_upload_bytes: int = 0  # track cumulative upload size
    file_hashes: set[str] = set()  # SHA-256 hashes for dedup (§4 step 6)

    model_config = {"arbitrary_types_allowed": True}

