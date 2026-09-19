from typing import Literal, Optional, List, Tuple
from pydantic import BaseModel, Field


class Citation(BaseModel):
    marker: int
    filename: str
    page_number: int
    source_type: Literal["base", "user"]
    snippet: str


class AskRequest(BaseModel):
    session_id: str
    question: str
    source_filter: Literal["base", "user", "both"] = "both"


class AskResponse(BaseModel):
    answer: str
    citations: List[Citation]
    provider_used: str = "Mini AI Knowledge System"


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    pages_processed: int
    chunks_created: int
    status: Literal["success", "rejected"]
    reason: Optional[str] = None


class SessionState(BaseModel):
    session_id: str
    created_at: float
    last_active: float
    running_summary: str = ""
    last_turn: Optional[Tuple[str, str]] = None
    recent_turns: List[Tuple[str, str]] = Field(default_factory=list)
    has_uploaded_docs: bool = False
