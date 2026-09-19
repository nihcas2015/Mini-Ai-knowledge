"""
POST /upload — upload a PDF to a session's user knowledge layer.
"""

import hashlib
import logging
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Request

from app.core.rate_limit import limiter
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


@router.post("/upload", response_model=UploadResponse)
@limiter.limit(settings.RATE_LIMIT)
async def upload_document(
    request: Request,
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
        return UploadResponse(
            session_id=session_id,
            filename=file.filename or "unknown",
            pages_processed=0,
            chunks_created=0,
            status="rejected",
            reason="Only PDF files are accepted.",
        )

    # Read file bytes
    file_bytes = await file.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    # Validate single file size (§4 step 3)
    if file_size_mb > settings.MAX_FILE_SIZE_MB:
        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            pages_processed=0,
            chunks_created=0,
            status="rejected",
            reason=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB limit ({file_size_mb:.1f} MB).",
        )

    # Validate total upload size per session (§4 step 3)
    current_total_mb = session.total_upload_bytes / (1024 * 1024)
    if (current_total_mb + file_size_mb) > settings.MAX_TOTAL_UPLOAD_MB:
        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            pages_processed=0,
            chunks_created=0,
            status="rejected",
            reason=f"Total upload limit of {settings.MAX_TOTAL_UPLOAD_MB} MB per session exceeded.",
        )

    # Content-hash dedup (§4 step 6)
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    if file_hash in session.file_hashes:
        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            pages_processed=0,
            chunks_created=0,
            status="rejected",
            reason="This file has already been uploaded in this session.",
        )

    try:
        # Step 1: Extract PDF elements (§4 step 1)
        elements = extract_pdf(file_bytes, file.filename)

        # Count unique pages processed
        pages = set()
        for el in elements:
            if "page_number" in el and el["page_number"] is not None:
                pages.add(el["page_number"])
        pages_processed = len(pages) if pages else 1

        # Step 2: Create hierarchical chunks (§4 step 5)
        parent_chunks, child_chunks = create_hierarchical_chunks(
            elements=elements,
            filename=file.filename,
            source_type="user",
        )

        if not child_chunks:
            return UploadResponse(
                session_id=session_id,
                filename=file.filename,
                pages_processed=pages_processed,
                chunks_created=0,
                status="rejected",
                reason="No indexable content found in PDF.",
            )

        # Step 3: Embed child chunks (§4 step 7)
        embedding_service = get_embedding_service()
        child_texts = [c["child_text"] for c in child_chunks]
        embeddings = embedding_service.embed_texts(child_texts)

        # Step 4: Index into session-scoped Qdrant collection (§4 step 8)
        vector_store = get_vector_store()
        user_client = vector_store.get_or_create_user_collection(session_id)
        collection_name = f"user_{session_id}"

        chunk_ids = [c["chunk_id"] for c in child_chunks]
        vector_store.upsert_chunks(
            client=user_client,
            collection_name=collection_name,
            chunk_ids=chunk_ids,
            embeddings=embeddings,
            payloads=child_chunks,
        )

        # Step 5: Index into session-scoped BM25 (§4 step 8)
        bm25_manager = get_bm25_manager()
        bm25_manager.add_to_index(collection_name, child_chunks)

        # Step 6: Update session state (§4 step 6)
        session.has_uploaded_docs = True
        session.total_upload_bytes += len(file_bytes)
        session.file_hashes.add(file_hash)

        logger.info(
            f"Uploaded {file.filename}: {pages_processed} pages, "
            f"{len(child_chunks)} chunks into {collection_name}"
        )

        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            pages_processed=pages_processed,
            chunks_created=len(child_chunks),
            status="success",
        )

    except ValueError as e:
        # e.g., scanned PDF with < 200 chars
        logger.warning(f"Upload rejected for {file.filename}: {e}")
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
