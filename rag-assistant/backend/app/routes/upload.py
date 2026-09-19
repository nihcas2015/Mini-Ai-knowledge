"""
Upload route.
POST /upload — upload a PDF to a session's user knowledge layer.
"""

import hashlib
import logging
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.models.schemas import UploadResponse
from app.core.memory import get_session_manager
from app.core.extraction import extract_pdf
from app.core.chunking import create_hierarchical_chunks
from app.core.embeddings import get_embedding_service
from app.core.vector_store import get_vector_store
from app.core.bm25_index import get_bm25_manager

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/upload", response_model=UploadResponse)
@limiter.limit(settings.RATE_LIMIT)
async def upload_document(
    http_request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a PDF file for session-scoped indexing."""
    # Validate session exists
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are accepted."
        )

    # Read file bytes
    file_bytes = await file.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    # Validate file size (§4 step 3)
    if file_size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit ({file_size_mb:.1f} MB)."
        )

    # Validate total upload size per session (§4 step 3)
    new_total = session.total_upload_bytes + len(file_bytes)
    if new_total > settings.MAX_TOTAL_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"Total upload limit of {settings.MAX_TOTAL_UPLOAD_MB} MB per session exceeded."
        )

    # Content-hash dedup (§4 step 6)
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    if file_hash in session.file_hashes:
        raise HTTPException(
            status_code=409,
            detail="This file has already been uploaded in this session."
        )

    try:
        # Extract PDF (§4 step 1-2)
        elements = extract_pdf(file_bytes, file.filename)

        # Get unique page numbers for reporting
        page_numbers = set()
        for elem in elements:
            if "page_number" in elem:
                page_numbers.add(elem["page_number"])

        # Hierarchical chunking (§4 step 5)
        parent_chunks, child_chunks = create_hierarchical_chunks(
            elements, file.filename, "user"
        )

        if not child_chunks:
            return UploadResponse(
                session_id=session_id,
                filename=file.filename,
                pages_processed=len(page_numbers),
                chunks_created=0,
                status="rejected",
                reason="No processable content found in the PDF.",
            )

        # Embed child chunks (§4 step 7)
        embedding_service = get_embedding_service()
        texts = [c["child_text"] for c in child_chunks]
        embeddings = embedding_service.embed_texts(texts)

        # Store in user Qdrant collection (§4 step 8)
        vs = get_vector_store()
        collection_name = f"user_{session_id}"
        client = vs.get_or_create_user_collection(session_id)
        chunk_ids = [c["chunk_id"] for c in child_chunks]
        vs.upsert_chunks(client, collection_name, chunk_ids, embeddings, child_chunks)

        # Build/update BM25 index
        bm25 = get_bm25_manager()
        bm25.add_to_index(collection_name, child_chunks)

        # Update session state
        session.has_uploaded_docs = True
        session.total_upload_bytes = new_total
        session.file_hashes.add(file_hash)

        logger.info(
            f"Upload success: {file.filename} -> {len(child_chunks)} chunks "
            f"for session {session_id}"
        )

        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            pages_processed=len(page_numbers),
            chunks_created=len(child_chunks),
            status="success",
        )

    except ValueError as e:
        # Extraction validation errors (e.g., scanned PDF)
        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            pages_processed=0,
            chunks_created=0,
            status="rejected",
            reason=str(e),
        )
    except Exception as e:
        logger.error(f"Upload failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process PDF: {str(e)}",
        )

