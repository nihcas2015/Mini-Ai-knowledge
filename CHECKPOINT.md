# Build Checkpoint

## Session Log

### Session 0 — 2026-09-19 — Project initialization

- Status: not started
- Completed: Nothing yet
- Current phase: Phase 1 — config/schemas (referencing §11 build order)
- Next steps:
  1. Create project directory structure per §11
  2. Implement config.py with pydantic-settings (all env vars from §15, §16)
  3. Implement schemas.py with exact Pydantic models from §7
  4. Create requirements.txt with all dependencies from §2
  5. Create .env.example with all env var names
  6. Implement core modules: extraction, chunking, embeddings, vector_store, bm25_index
  7. Implement pipeline modules: llm_router, generation, retrieval, memory, notifications
  8. Implement API routes and main.py
  9. Build frontend (Next.js)
  10. Write tests and eval
  11. Create Dockerfile and README.md
- Known issues / deviations from spec: None
- Test status: No tests written yet
- Files touched this session: CHECKPOINT.md

---

### Session 1 — 2026-09-19 — Full project build (all phases)

- Status: phase complete
- Completed:
  - Created full project directory structure per §11
  - Implemented config.py with pydantic-settings (all 9 API keys + Cohere + Telegram + all tuning params)
  - Implemented schemas.py with exact Pydantic models from §7 (ChunkMetadata, Citation, AskRequest, AskResponse, UploadResponse, SessionState)
  - Created requirements.txt with all dependencies from §2
  - Created .env.example with all env var names
  - Implemented extraction.py: PDF parsing with unstructured hi_res, HTML→Markdown table conversion, minimum text validation
  - Implemented chunking.py: hierarchical parent/child splitting with heading boundary detection, table preservation, RecursiveCharacterTextSplitter(400/80)
  - Implemented embeddings.py: SentenceTransformer wrapper for bge-base-en-v1.5, singleton pattern
  - Implemented vector_store.py: Qdrant wrapper for base (local-disk) and user (in-memory) collections, with score in search results
  - Implemented bm25_index.py: BM25Okapi index with normalized scoring for ensemble compatibility
  - Implemented notifications.py: Telegram admin alerts with 10-minute cooldown per alert type
  - Implemented memory.py: SessionManager with create/get/delete/sweep, conversation turn tracking, summary management
  - Implemented llm_router.py: 3-provider × 3-key rotation (Groq → OpenRouter → Gemini), dead key tracking, 401/403 admin alerts, round-robin, streaming support
  - Implemented retrieval.py: hybrid dense+BM25 ensemble (0.6/0.4), Cohere rerank with timeout/fallback, relevance threshold (0.3)
  - Implemented generation.py: exact system prompt from §6, numbered context block, citation parsing with hallucinated-ref dropping, question condensation, summary folding
  - Implemented session routes: POST /session, DELETE /session/{id}, DELETE /session/{id}/documents
  - Implemented upload route: file validation, size limits, SHA-256 dedup, extraction→chunking→embedding→storage pipeline
  - Implemented ask route: SSE streaming, citation validation, async memory update
  - Implemented main.py: FastAPI lifespan with startup indexing, background session sweeper, CORS, rate limiting, health endpoint
  - Built complete Next.js frontend: App Router, TypeScript, Tailwind CSS, all 5 components (ChatWindow, MessageBubble, CitationBadge, UploadPanel, SourceFilterToggle), SSE streaming client
  - Created Dockerfile: multi-stage build, bge-base-en-v1.5 baked at build time
  - Wrote all 4 test files: test_chunking, test_retrieval, test_grounding, test_citations
  - Created eval/ragas_eval.py: 10 handwritten Q&A pairs with faithfulness+relevancy scoring
  - Created README.md: architecture, design decisions, grounding, limitations, deployment instructions
- Current phase: All phases complete (config/schemas → extraction/chunking → embeddings/vector_store → retrieval → generation/LLM router → memory → API routes → frontend → tests/eval → deployment)
- Next steps:
  1. Add base knowledge PDFs to backend/knowledge_base/
  2. Populate .env with real API keys (Groq ×3, OpenRouter ×3, Gemini ×3, Cohere, Telegram)
  3. Run `pip install -r requirements.txt` and `pytest tests/ -v` to verify tests pass
  4. Run `cd frontend && npm install && npm run dev` to verify frontend builds
  5. Build Docker image and deploy to AWS App Runner
  6. Deploy frontend to Vercel
  7. Run eval/ragas_eval.py against live deployment
- Known issues / deviations from spec:
  - Cohere rerank uses synchronous `cohere.Client` wrapped in `asyncio.to_thread` (the async Cohere client has inconsistent API across versions; this is functionally equivalent)
  - `generate_stream` is now an async generator (using `yield`) rather than returning a generator, for cleaner provider-info passing. Functionally identical behavior.
  - Vector store point IDs use `abs(hash(chunk_id)) % 2**63` to convert UUID strings to Qdrant-compatible integer IDs
  - BM25 scores are normalized to 0-1 range for proper ensemble weighting with dense cosine similarity scores
- Test status: Tests written for all 4 required areas (chunking, retrieval, grounding, citations). Not yet run (requires dependency installation).
- Files touched this session:
  - CHECKPOINT.md
  - rag-assistant/backend/app/__init__.py
  - rag-assistant/backend/app/config.py
  - rag-assistant/backend/app/models/__init__.py
  - rag-assistant/backend/app/models/schemas.py
  - rag-assistant/backend/app/core/__init__.py
  - rag-assistant/backend/app/core/extraction.py
  - rag-assistant/backend/app/core/chunking.py
  - rag-assistant/backend/app/core/embeddings.py
  - rag-assistant/backend/app/core/vector_store.py
  - rag-assistant/backend/app/core/bm25_index.py
  - rag-assistant/backend/app/core/notifications.py
  - rag-assistant/backend/app/core/memory.py
  - rag-assistant/backend/app/core/llm_router.py
  - rag-assistant/backend/app/core/retrieval.py
  - rag-assistant/backend/app/core/generation.py
  - rag-assistant/backend/app/routes/__init__.py
  - rag-assistant/backend/app/routes/session.py
  - rag-assistant/backend/app/routes/upload.py
  - rag-assistant/backend/app/routes/ask.py
  - rag-assistant/backend/app/main.py
  - rag-assistant/backend/tests/__init__.py
  - rag-assistant/backend/tests/test_chunking.py
  - rag-assistant/backend/tests/test_retrieval.py
  - rag-assistant/backend/tests/test_grounding.py
  - rag-assistant/backend/tests/test_citations.py
  - rag-assistant/backend/eval/ragas_eval.py
  - rag-assistant/backend/knowledge_base/.gitkeep
  - rag-assistant/backend/requirements.txt
  - rag-assistant/backend/.env.example
  - rag-assistant/backend/Dockerfile
  - rag-assistant/frontend/package.json
  - rag-assistant/frontend/tsconfig.json
  - rag-assistant/frontend/next.config.js
  - rag-assistant/frontend/postcss.config.js
  - rag-assistant/frontend/tailwind.config.ts
  - rag-assistant/frontend/.env.local.example
  - rag-assistant/frontend/app/globals.css
  - rag-assistant/frontend/app/layout.tsx
  - rag-assistant/frontend/app/page.tsx
  - rag-assistant/frontend/lib/api.ts
  - rag-assistant/frontend/components/ChatWindow.tsx
  - rag-assistant/frontend/components/MessageBubble.tsx
  - rag-assistant/frontend/components/CitationBadge.tsx
  - rag-assistant/frontend/components/UploadPanel.tsx
  - rag-assistant/frontend/components/SourceFilterToggle.tsx
  - rag-assistant/README.md

---
