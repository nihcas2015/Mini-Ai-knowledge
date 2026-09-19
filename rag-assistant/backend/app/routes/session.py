"""
Session management routes.
POST /session — create new session
DELETE /session/{session_id} — end session
DELETE /session/{session_id}/documents — clear user-uploaded docs
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.core.memory import get_session_manager
from app.core.vector_store import get_vector_store
from app.core.bm25_index import get_bm25_manager

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/session")
@limiter.limit(settings.RATE_LIMIT)
async def create_session(request: Request):
    """Create a new session and return its ID."""
    manager = get_session_manager()
    session_id = manager.create_session()
    logger.info(f"Session created: {session_id}")
    return {"session_id": session_id}


@router.delete("/session/{session_id}")
@limiter.limit(settings.RATE_LIMIT)
async def end_session(session_id: str, request: Request):
    """Explicitly end a session, cleaning up all resources."""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Clean up user vector collection
    vs = get_vector_store()
    if vs.has_user_collection(session_id):
        vs.delete_user_collection(session_id)

    # Clean up BM25 index
    bm25 = get_bm25_manager()
    collection_name = f"user_{session_id}"
    bm25.delete_index(collection_name)

    # Delete session state
    manager.delete_session(session_id)
    logger.info(f"Session ended: {session_id}")
    return {"status": "ended"}


@router.delete("/session/{session_id}/documents")
@limiter.limit(settings.RATE_LIMIT)
async def clear_documents(session_id: str, request: Request):
    """Clear all user-uploaded documents for a session."""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Clean up user vector collection
    vs = get_vector_store()
    if vs.has_user_collection(session_id):
        vs.delete_user_collection(session_id)

    # Clean up BM25 index
    bm25 = get_bm25_manager()
    collection_name = f"user_{session_id}"
    bm25.delete_index(collection_name)

    # Reset session upload state
    session.has_uploaded_docs = False
    session.total_upload_bytes = 0
    session.file_hashes = set()

    logger.info(f"Documents cleared for session: {session_id}")
    return {"status": "cleared"}

