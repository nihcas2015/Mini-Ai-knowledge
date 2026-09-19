"""
Pydantic models and schemas.
"""

from typing import Literal, Optional, List, Tuple, Set
from pydantic import BaseModel, Field


class Citation(BaseModel):
    """A citation mapping a bracket marker to its source."""
    marker: int
    filename: str
    page_number: int
    source_type: Literal["base", "user"]
    snippet: str


class AskRequest(BaseModel):
    """Request body for POST /ask."""
    session_id: str
    question: str
    source_filter: Literal["base", "user", "both"] = "both"


class AskResponse(BaseModel):
    """Final response payload from POST /ask."""
    answer: str
    citations: List[Citation]
    provider_used: str = "Mini AI Knowledge System"


class UploadResponse(BaseModel):
    """Response payload from POST /upload."""
    session_id: str
    filename: str
    pages_processed: int
    chunks_created: int
    status: Literal["success", "rejected"]
    reason: Optional[str] = None


class SessionState(BaseModel):
    """State for a single user session."""
    session_id: str
    created_at: float
    last_active: float
    running_summary: str = ""
    last_turn: Optional[Tuple[str, str]] = None
    recent_turns: List[Tuple[str, str]] = Field(default_factory=list)
    has_uploaded_docs: bool = False
    total_upload_bytes: int = 0
    file_hashes: Set[str] = Field(default_factory=set)
