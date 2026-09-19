# Mini AI Knowledge Assistant

A production-grade RAG (Retrieval-Augmented Generation) web application with two knowledge layers, hybrid retrieval, multi-provider LLM fallback, and citation-grounded answers.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Next.js Frontend                         │
│   Chat UI │ Upload Panel │ Citation Popovers │ Source Filter    │
└───────────────────────┬─────────────────────────────────────────┘
                        │ SSE / REST
┌───────────────────────▼─────────────────────────────────────────┐
│                       FastAPI Backend                            │
│                                                                  │
│  ┌────────────┐  ┌───────────────┐  ┌────────────────────────┐  │
│  │  Ingestion  │  │   Retrieval   │  │      Generation        │  │
│  │            │  │               │  │                        │  │
│  │ Unstructured│  │ Dense (Qdrant)│  │ Groq → OpenRouter     │  │
│  │ PDF Parsing │  │ + BM25 Sparse │  │ → Gemini (3 keys ea.) │  │
│  │ Hierarchical│  │ Ensemble 0.6/ │  │ Citation validation   │  │
│  │ Chunking   │  │ 0.4 weighting │  │ SSE streaming         │  │
│  │ bge-base   │  │ Cohere Rerank │  │ Conversation memory   │  │
│  │ Embeddings │  │ Threshold 0.3 │  │                        │  │
│  └────────────┘  └───────────────┘  └────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  Two Knowledge Layers                     │   │
│  │  Base (Qdrant local disk) │ User (Qdrant in-memory)      │   │
│  │  Persists across requests │ Scoped to session, ephemeral │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Two-Tier Knowledge System
1. **Base Knowledge** — Fixed PDFs shipped with the app, indexed at startup into Qdrant local-disk mode. Persists for the app's lifetime.
2. **User Knowledge** — Visitor-uploaded PDFs indexed into in-memory Qdrant, scoped to their session, discarded on reload/session expiry. Never touches disk.

### Hybrid Retrieval Pipeline
- **Dense retrieval** via Qdrant vector search (bge-base-en-v1.5 embeddings)
- **Sparse retrieval** via BM25 keyword matching
- **Ensemble** with 0.6 dense / 0.4 sparse weighting
- **Cohere Rerank** (with graceful fallback to ensemble order on failure)
- **Relevance threshold** (0.3) — below-threshold queries return a fixed fallback message instead of hallucinated answers

### Multi-Provider LLM Fallback Chain
Groq → OpenRouter → Gemini, with **3 API keys per provider** (9 total attempts per request):
- Round-robin key rotation spreads load across free-tier quotas
- 429s try the next key; 401/403s mark the key as dead and trigger a Telegram admin alert
- On total failure, returns a graceful message and notifies the admin

---

## Design Decisions

### Why self-hosted embeddings (bge-base-en-v1.5) over an API?
- Zero per-query cost, no external dependency for embeddings
- Consistent latency (no network round-trip)
- Model baked into Docker image at build time — no runtime download

### Why Qdrant over FAISS or Pinecone?
- Qdrant supports both local-disk and in-memory modes from the same client, fitting the two-layer architecture perfectly
- Rich payload storage means parent chunk text lives alongside vectors — no separate database needed
- FAISS lacks payload storage; Pinecone adds external service complexity and cost

### Why no Redis or Postgres?
- Single-instance architecture (App Runner min=max=1) means in-process Python dicts work fine for sessions
- No horizontal scaling needed, so no shared state to coordinate
- Simpler deployment, fewer moving parts, lower cost

### Why in-memory-only for user data?
- Privacy: user documents never touch disk or cloud storage
- Simplicity: no cleanup jobs, no storage costs, no data retention concerns
- Natural lifecycle: session expiry or page reload = clean slate

---

## Grounding & Anti-Hallucination

1. **Relevance threshold** — if the best reranked result scores below 0.3, the system returns the fixed message _"I don't have enough information..."_ without calling the LLM at all.
2. **Strict system prompt** — the LLM is instructed to use ONLY the provided context and cite every claim with bracket numbers.
3. **Citation validation** — after generation, bracket markers are parsed and validated against actual retrieved chunks. Hallucinated citation numbers are silently dropped and logged.
4. **Tests** — `test_grounding.py` asserts that unrelated questions receive the exact fallback message, not a hallucinated answer.

---

## Known Limitations & Trade-offs

- **Single instance only** — App Runner min=max=1, no horizontal scaling. Adequate for the review window, not for production traffic.
- **In-memory state** — all sessions, user vectors, conversation summaries are lost on process restart. By design (§9), not a bug.
- **No persistent user uploads** — user PDFs are processed and discarded. Users must re-upload after page refresh.
- **Free-tier LLM quotas** — 3 keys per provider gives redundancy, but sustained heavy traffic could exhaust all 9 keys.
- **PDF-only** — no support for DOCX, TXT, or other document formats (spec constraint).
- **English-only reranking** — Cohere rerank model is English-specific.

---

## Running Locally

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill environment variables
cp .env.example .env
# Edit .env with your API keys

# Place base PDFs in knowledge_base/
# (Optional — the app starts with empty base knowledge if none provided)

# Run
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Copy environment
cp .env.local.example .env.local
# Edit .env.local: NEXT_PUBLIC_API_URL=http://localhost:8000

# Run
npm run dev
```

### Running Tests

```bash
cd backend
pytest tests/ -v
```

### Running Evaluation

```bash
cd backend
# Requires the backend server to be running
python -m eval.ragas_eval
```

---

## Deployment

- **Backend**: Docker image → AWS ECR → AWS App Runner (1 vCPU / 2 GB, min instances = 1)
- **Frontend**: Next.js → Vercel
- **Region**: `us-east-1` (ECR + App Runner co-located)

```bash
# Build and push Docker image
cd backend
docker build -t rag-assistant-backend .
docker tag rag-assistant-backend:latest <ECR_URI>:latest
docker push <ECR_URI>:latest

# App Runner picks up the new image automatically
```

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Readiness check (503 while indexing, 200 when ready) |
| POST | `/session` | Create new session |
| POST | `/upload` | Upload PDF to session (multipart) |
| DELETE | `/session/{id}/documents` | Clear user uploads |
| POST | `/ask` | Ask question (SSE stream) |
| DELETE | `/session/{id}` | End session |

---

## Project Structure

```
rag-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, routes
│   │   ├── config.py            # All settings from env vars
│   │   ├── models/schemas.py    # Pydantic data models
│   │   ├── core/
│   │   │   ├── extraction.py    # PDF parsing (unstructured)
│   │   │   ├── chunking.py      # Hierarchical parent/child splitter
│   │   │   ├── embeddings.py    # bge-base-en-v1.5 wrapper
│   │   │   ├── vector_store.py  # Qdrant (base + per-session)
│   │   │   ├── bm25_index.py    # BM25 sparse index
│   │   │   ├── retrieval.py     # Hybrid retrieval + rerank
│   │   │   ├── llm_router.py    # 3-provider × 3-key fallback
│   │   │   ├── generation.py    # Prompt building + citation mapping
│   │   │   ├── memory.py        # Session state management
│   │   │   └── notifications.py # Telegram admin alerts
│   │   └── routes/
│   │       ├── session.py
│   │       ├── upload.py
│   │       └── ask.py
│   ├── knowledge_base/          # Base PDFs
│   ├── tests/                   # pytest test suite
│   ├── eval/ragas_eval.py       # Evaluation script
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                    # Next.js app
├── SPEC.md                      # Locked specification
├── CHECKPOINT.md                # Build session log
└── README.md                    # This file
```

