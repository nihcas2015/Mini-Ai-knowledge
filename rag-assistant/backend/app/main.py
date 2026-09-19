"""
FastAPI application entry point.
- Lifespan: indexes base knowledge on startup, sweeps sessions in background.
- Routes: /health, /session, /upload, /ask
- Middleware: CORS, rate limiting
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.rate_limit import limiter
from app.config import settings
from app.routes import session, upload, ask
from app.core.notifications import notify_admin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global readiness flag — health endpoint returns 503 until indexing is done (§3.1)
_ready = False


async def _index_base_knowledge():
    """Parse, chunk, embed, and index all base PDFs on startup (§3.1)."""
    global _ready
    import os
    from app.core.extraction import extract_pdf
    from app.core.chunking import create_hierarchical_chunks
    from app.core.embeddings import get_embedding_service
    from app.core.vector_store import get_vector_store
    from app.core.bm25_index import get_bm25_manager

    try:
        embedding_service = get_embedding_service()
        vs = get_vector_store()
        bm25 = get_bm25_manager()

        # Initialize base collection
        vs.init_base_collection()

        kb_dir = settings.KNOWLEDGE_BASE_DIR
        if not os.path.isabs(kb_dir):
            kb_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), kb_dir)

        if not os.path.exists(kb_dir):
            logger.warning(f"Knowledge base directory not found: {kb_dir}")
            _ready = True
            return

        kb_files = [f for f in os.listdir(kb_dir) if f.lower().endswith((".pdf", ".txt", ".md"))]
        if not kb_files:
            logger.info("No base documents found in knowledge_base/. Starting with empty base.")
            _ready = True
            return

        all_child_chunks = []

        for kb_file in kb_files:
            file_path = os.path.join(kb_dir, kb_file)
            logger.info(f"Indexing base document: {kb_file}")

            try:
                if kb_file.lower().endswith(".pdf"):
                    with open(file_path, "rb") as f:
                        file_bytes = f.read()
                    elements = extract_pdf(file_bytes, kb_file)
                else:
                    with open(file_path, "r", encoding="utf-8") as f:
                        text_content = f.read()
                    paragraphs = [p.strip() for p in text_content.split("\n\n") if len(p.strip()) > 10]
                    elements = [
                        {"type": "narrative", "text": p, "page_number": 1, "metadata": {}}
                        for p in paragraphs
                    ]

                parent_chunks, child_chunks = create_hierarchical_chunks(
                    elements, kb_file, "base"
                )

                if child_chunks:
                    # Embed
                    texts = [c["child_text"] for c in child_chunks]
                    embeddings = embedding_service.embed_texts(texts)

                    # Upsert to base collection
                    chunk_ids = [c["chunk_id"] for c in child_chunks]
                    vs.upsert_chunks(
                        vs.base_client,
                        settings.QDRANT_BASE_COLLECTION,
                        chunk_ids,
                        embeddings,
                        child_chunks,
                    )
                    all_child_chunks.extend(child_chunks)

                    logger.info(
                        f"  Indexed {pdf_file}: {len(child_chunks)} chunks"
                    )
                else:
                    logger.warning(f"  No chunks produced for {pdf_file}")

            except Exception as e:
                logger.error(f"  Failed to index {pdf_file}: {e}", exc_info=True)

        # Build BM25 index for base knowledge
        if all_child_chunks:
            bm25.build_index(settings.QDRANT_BASE_COLLECTION, all_child_chunks)
            logger.info(
                f"Base knowledge indexed: {len(all_child_chunks)} total chunks "
                f"from {len(pdf_files)} PDFs"
            )

        _ready = True
        logger.info("Base knowledge indexing complete. Server is ready.")

    except Exception as e:
        logger.critical(f"Base knowledge indexing failed: {e}", exc_info=True)
        # Notify admin of startup failure (§16.3)
        try:
            await notify_admin(
                "STARTUP_FAILURE",
                f"Base knowledge index failed to build: {str(e)}"
            )
        except Exception:
            pass
        # Still mark as ready so the server doesn't hang, but with degraded state
        _ready = True


async def _session_sweeper():
    """Background task that sweeps expired sessions every few minutes (§9)."""
    from app.core.memory import get_session_manager
    from app.core.vector_store import get_vector_store
    from app.core.bm25_index import get_bm25_manager

    while True:
        try:
            await asyncio.sleep(settings.SESSION_SWEEP_INTERVAL_SECONDS)
            manager = get_session_manager()
            expired = manager.get_expired_sessions()

            if expired:
                vs = get_vector_store()
                bm25 = get_bm25_manager()

                for sid in expired:
                    # Clean up user collections
                    if vs.has_user_collection(sid):
                        vs.delete_user_collection(sid)
                    bm25.delete_index(f"user_{sid}")

                swept = manager.sweep_sessions()
                if swept:
                    logger.info(f"Swept {len(swept)} expired sessions")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Session sweeper error: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup indexing + background sweeper."""
    # Startup: index base knowledge
    await _index_base_knowledge()

    # Start background session sweeper
    sweeper_task = asyncio.create_task(_session_sweeper())

    yield

    # Shutdown: cancel sweeper
    sweeper_task.cancel()
    try:
        await sweeper_task
    except asyncio.CancelledError:
        pass
    logger.info("Application shutdown complete.")


# --- Create FastAPI app ---

app = FastAPI(
    title="Mini AI Knowledge Assistant",
    description="RAG application with two-tier knowledge and multi-provider LLM fallback",
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS middleware (§8) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rate limiting (§8) — reuse the single shared Limiter instance so every
# route's @limiter.limit(...) decorator shares the same storage/state as
# the one registered on app.state (see app/core/rate_limit.py). ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Health endpoint (§3.1, §8) ---
@app.get("/health")
async def health():
    """Liveness/readiness check. Returns 503 until base indexing is complete."""
    if _ready:
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "indexing"})


# --- Include routers ---
app.include_router(session.router, tags=["session"])
app.include_router(upload.router, tags=["upload"])
app.include_router(ask.router, tags=["ask"])

