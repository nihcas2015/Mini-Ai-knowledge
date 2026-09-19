import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.models import AskRequest, AskResponse, UploadResponse
from app.rag_chain import (
    get_rag_pipeline,
    get_session_manager,
    parse_pdf_file,
    split_into_hierarchical_chunks,
    parse_bracket_citations,
)

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ready"}


@router.post("/session")
async def create_session():
    sid = get_session_manager().create_session()
    return {"session_id": sid}


@router.delete("/session/{session_id}")
async def end_session(session_id: str):
    sm = get_session_manager()
    rag = get_rag_pipeline()
    sm.delete_session(session_id)
    rag.vector_store.delete_user_collection(session_id)
    return {"message": "Session ended and memory cleared"}


@router.delete("/session/{session_id}/documents")
async def clear_documents(session_id: str):
    rag = get_rag_pipeline()
    rag.vector_store.delete_user_collection(session_id)
    return {"message": "Documents cleared"}


@router.post("/upload", response_model=UploadResponse)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def upload_document(
    request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds 10MB limit.")

    session = get_session_manager().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        rag = get_rag_pipeline()

        docs = parse_pdf_file(file_bytes, file.filename)
        if not docs:
            raise HTTPException(status_code=422, detail="No readable text found in PDF.")

        _, child_chunks = split_into_hierarchical_chunks(docs, file.filename, source_type="user")

        user_client = rag.vector_store.get_or_create_user_client(session_id)
        rag.vector_store.upsert_chunks(user_client, f"user_{session_id}", child_chunks)
        rag.bm25.build_index(f"user_{session_id}", child_chunks)

        session.has_uploaded_docs = True

        return UploadResponse(
            session_id=session_id,
            filename=file.filename,
            pages_processed=len(set(d.metadata.get("page_number", 1) for d in docs)),
            chunks_created=len(child_chunks),
            status="success",
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask")
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def ask_question(request: Request, payload: AskRequest):
    session = get_session_manager().get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    rag = get_rag_pipeline()

    async def sse_event_stream() -> AsyncGenerator[str, None]:
        try:
            chunks, token_stream = await rag.astream_rag(
                question=payload.question,
                session=session,
                source_filter=payload.source_filter,
            )

            full_text = ""
            async for token in token_stream:
                full_text += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            citations = parse_bracket_citations(full_text, chunks)

            final_res = AskResponse(
                answer=full_text,
                citations=citations,
                provider_used="Mini AI Knowledge System",
            )
            yield f"data: {json.dumps({'type': 'final', 'data': final_res.model_dump()})}\n\n"
            yield "data: [DONE]\n\n"

            get_session_manager().update_turn(payload.session_id, payload.question, full_text)

        except Exception as e:
            logger.error(f"Ask pipeline error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
