import asyncio
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from langchain_core.documents import Document

from app.config import settings
from app.routes import router, limiter
from app.rag_chain import (
    get_rag_pipeline,
    parse_pdf_file,
    split_into_hierarchical_chunks,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app.main")


async def index_base_knowledge():
    try:
        rag = get_rag_pipeline()
        rag.vector_store.init_base_collection()

        kb_dir = settings.KNOWLEDGE_BASE_DIR
        if not os.path.isabs(kb_dir):
            kb_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), kb_dir)

        if not os.path.exists(kb_dir):
            logger.warning(f"Knowledge base directory not found: {kb_dir}")
            return

        files = [f for f in os.listdir(kb_dir) if f.lower().endswith((".pdf", ".txt", ".md"))]
        if not files:
            logger.info("No base documents found in knowledge_base/. Starting with empty base.")
            return

        all_child_chunks = []
        for f in files:
            file_path = os.path.join(kb_dir, f)
            try:
                if f.lower().endswith(".pdf"):
                    with open(file_path, "rb") as pdf_f:
                        docs = parse_pdf_file(pdf_f.read(), f)
                else:
                    with open(file_path, "r", encoding="utf-8") as txt_f:
                        content = txt_f.read()
                    paragraphs = [p.strip() for p in content.split("\n\n") if len(p.strip()) > 10]
                    docs = [
                        Document(page_content=p, metadata={"filename": f, "page_number": 1})
                        for p in paragraphs
                    ]

                _, children = split_into_hierarchical_chunks(docs, f, source_type="base")
                rag.vector_store.upsert_chunks(rag.vector_store.base_client, settings.QDRANT_BASE_COLLECTION, children)
                all_child_chunks.extend(children)
                logger.info(f"Indexed base document {f}: {len(children)} chunks")
            except Exception as e:
                logger.error(f"Failed to index {f}: {e}")

        if all_child_chunks:
            rag.bm25.build_index(settings.QDRANT_BASE_COLLECTION, all_child_chunks)
            logger.info(f"Base knowledge ready: {len(all_child_chunks)} chunks indexed")

    except Exception as e:
        logger.error(f"Base knowledge indexing failed: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(index_base_knowledge())
    yield


app = FastAPI(
    title="Mini AI Knowledge System",
    description="Knowledge Assistant built by Sachin",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
