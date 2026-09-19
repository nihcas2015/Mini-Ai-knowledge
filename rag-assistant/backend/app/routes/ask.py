"""
Ask route.
POST /ask — ask a question, streamed via SSE.
"""

import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.rate_limit import limiter
from app.config import settings
from app.models.schemas import AskRequest, AskResponse, Citation
from app.core.memory import get_session_manager
from app.core.embeddings import get_embedding_service
from app.core.vector_store import get_vector_store
from app.core.bm25_index import get_bm25_manager
from app.core.llm_router import get_llm_router
from app.core.retrieval import retrieve
from app.core.generation import (
    build_context_block,
    build_user_message,
    parse_citations,
    condense_question,
    update_running_summary,
    SYSTEM_PROMPT,
    FALLBACK_MESSAGE,
    UNAVAILABLE_MESSAGE,
)

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/ask")
@limiter.limit(settings.RATE_LIMIT)
async def ask_question(request: AskRequest, http_request: Request):
    """
    Ask a question against the knowledge base.
    Returns an SSE stream of tokens, with a final event containing the full AskResponse.
    """
    session_manager = get_session_manager()
    session = session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    embedding_service = get_embedding_service()
    vector_store = get_vector_store()
    bm25_manager = get_bm25_manager()
    llm_router = get_llm_router()

    async def event_stream():
        question = request.question
        provider_used = "none"

        try:
            # Step 1: Condense question if conversation history exists (§5 step 1)
            condensed = question
            if session.last_turn:
                try:
                    condensed = await condense_question(
                        question,
                        session.running_summary,
                        session.last_turn,
                        llm_router,
                    )
                    logger.info(f"Condensed question: {condensed}")
                except Exception as e:
                    logger.warning(f"Question condensation failed, using original: {e}")
                    condensed = question

            # Step 2: Retrieve relevant chunks (§5)
            chunks = await retrieve(
                query=condensed,
                session_id=request.session_id,
                embedding_service=embedding_service,
                vector_store=vector_store,
                bm25_manager=bm25_manager,
            )

            # Step 3: If no relevant chunks found (below threshold), return fallback
            if not chunks:
                yield f"data: {json.dumps({'type': 'token', 'content': FALLBACK_MESSAGE})}\n\n"
                final = AskResponse(
                    answer=FALLBACK_MESSAGE,
                    citations=[],
                    provider_used="none",
                )
                yield f"data: {json.dumps({'type': 'final', 'data': final.model_dump()})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Step 4: Build context and prompt (§6 steps 1-3)
            context_block = build_context_block(chunks)
            user_message = build_user_message(
                question=question,
                context_block=context_block,
                running_summary=session.running_summary,
                last_turn=session.last_turn,
            )

            # Step 5: Stream LLM response (§6 steps 4-5)
            full_answer = ""
            try:
                async for token_data in llm_router.generate_stream(
                    system_prompt=SYSTEM_PROMPT,
                    user_message=user_message,
                ):
                    if isinstance(token_data, dict):
                        # Provider info
                        provider_used = token_data.get("provider", "unknown")
                    else:
                        # Token text
                        full_answer += token_data
                        yield f"data: {json.dumps({'type': 'token', 'content': token_data})}\n\n"
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                full_answer = UNAVAILABLE_MESSAGE
                yield f"data: {json.dumps({'type': 'token', 'content': UNAVAILABLE_MESSAGE})}\n\n"

            # Step 6: Parse and validate citations (§6 step 6)
            citations = parse_citations(full_answer, chunks)

            # Step 7: Send final response (§6 step 7)
            final = AskResponse(
                answer=full_answer,
                citations=citations,
                provider_used=provider_used,
            )
            yield f"data: {json.dumps({'type': 'final', 'data': final.model_dump()})}\n\n"
            yield "data: [DONE]\n\n"

            # Step 8: Update conversation memory async (§6 step 8)
            asyncio.create_task(_update_memory(
                session_manager=session_manager,
                session_id=request.session_id,
                question=question,
                answer=full_answer,
                llm_router=llm_router,
            ))

        except Exception as e:
            logger.error(f"Ask endpoint error: {e}", exc_info=True)
            error_msg = "An unexpected error occurred. Please try again."
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _update_memory(
    session_manager,
    session_id: str,
    question: str,
    answer: str,
    llm_router,
):
    """Update conversation memory asynchronously — does not block the response."""
    try:
        session = session_manager.get_session(session_id)
        if not session:
            return

        # Update last turn
        session_manager.update_conversation(session_id, question, answer)

        # Update running summary
        try:
            new_summary = await update_running_summary(
                current_summary=session.running_summary,
                question=question,
                answer=answer,
                llm_router=llm_router,
            )
            session_manager.update_summary(session_id, new_summary)
            logger.debug(f"Memory updated for session {session_id}")
        except Exception as e:
            logger.warning(f"Summary update failed for session {session_id}: {e}")

    except Exception as e:
        logger.error(f"Memory update failed: {e}", exc_info=True)

