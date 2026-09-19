# Mini AI Knowledge Assistant — Complete Locked Specification

This document is the single source of truth for implementation, covering architecture, exact tech choices, API-key redundancy, admin alerting, and the multi-session build/handoff process. Every choice below is final — do not substitute alternatives during build unless something is provably broken (missing package, dead API, etc.), in which case document the deviation and why.

---

## 1. Project Overview

A RAG (Retrieval-Augmented Generation) web application with two knowledge layers:
1. **Base knowledge** — a fixed set of PDFs shipped with the app, indexed once at server startup, persists for the app's lifetime.
2. **User-uploaded knowledge** — any visitor can upload their own PDF(s); these are indexed in memory, scoped to their session, and discarded on reload/session expiry. Nothing from this layer is ever written to disk or cloud storage.

Queries retrieve from both layers (filterable), are reranked, grounded with verified citations, and answered with a multi-provider LLM fallback chain for reliability. Conversation memory is a running summary + last raw turns, in-memory, per session.

---

## 2. Final Tech Stack (exact, no substitutions)

| Concern | Choice | Package / Service |
|---|---|---|
| Backend framework | FastAPI | `fastapi`, `uvicorn[standard]` |
| Frontend framework | Next.js (React, TypeScript) | `next`, `react`, `typescript` |
| PDF parsing | `unstructured` (with `hi_res` PDF strategy) | `unstructured[pdf]` |
| Chunking | Custom hierarchical splitter using LangChain primitives | `langchain-text-splitters` |
| Embeddings | Self-hosted, in-process | `sentence-transformers`, model: `BAAI/bge-base-en-v1.5` |
| Vector store (base layer) | Qdrant, in-process local mode, persisted to local disk inside container | `qdrant-client` (`path=` local mode, not `:memory:`) |
| Vector store (user layer) | Qdrant, in-process local mode, **pure in-memory** | `qdrant-client` (`location=":memory:"`) |
| Sparse/keyword retrieval | BM25 | `rank_bm25` |
| Hybrid retrieval orchestration | LangChain `EnsembleRetriever` | `langchain`, `langchain-community` |
| Reranking | Cohere Rerank API (`rerank-english-v3.0`) with fallback to skip-rerank on failure | `cohere` |
| LLM generation — primary | Groq (`llama-3.3-70b-versatile`) | `groq` |
| LLM generation — fallback 1 | OpenRouter (auto-routed free model, e.g. `meta-llama/llama-3.1-8b-instruct:free`) | `openai` SDK pointed at OpenRouter base URL |
| LLM generation — fallback 2 | Google Gemini (`gemini-2.0-flash`) | `google-generativeai` |
| Orchestration/chains | LangChain LCEL | `langchain-core` |
| Session/conversation state | Plain in-process Python dict, keyed by `session_id`, TTL-swept by a background task | stdlib (`asyncio`, `time`) — no Redis |
| Backend hosting | AWS App Runner (1 vCPU / 2 GB, min instances = 1) | AWS ECR + App Runner |
| Frontend hosting | Vercel | — |
| Containerization | Docker, single image for backend | `Dockerfile` |
| Testing | `pytest` | `pytest`, `pytest-asyncio` |
| Evaluation | RAGAS-style scripted eval | `ragas` (or a hand-rolled equivalent if `ragas` version conflicts arise) |

**Explicitly excluded** (do not add): Redis, Postgres, Pinecone, Weaviate, Neo4j/graph DB, LangGraph, multi-agent frameworks, Docker Compose multi-service orchestration, Celery/background job queues, Streamlit/Gradio.

---

## 3. Knowledge Base Design

### 3.1 Base layer
- Source PDFs live at `backend/knowledge_base/*.pdf`, committed to the repo.
- On container startup, a startup hook (`@app.on_event("startup")` or FastAPI lifespan) parses, chunks, embeds, and loads all base PDFs into a Qdrant **local-disk-mode** collection named `base_knowledge`, stored at a path inside the container (e.g. `/app/data/qdrant_base`). This path is inside the container filesystem, rebuilt fresh on every deploy — not an external volume, not S3.
- `/health` endpoint returns `200` only after this startup indexing completes. Until then, return `503`.

### 3.2 User layer
- On file upload, a new (or existing) **in-memory** Qdrant collection is created per `session_id`, e.g. `user_{session_id}`.
- Never written to disk. Never uploaded to any cloud storage. The raw PDF bytes are processed directly from the upload stream and discarded immediately after chunking — the file itself is never saved anywhere.
- Collection is deleted when: session TTL expires, or explicit "clear my documents" action, or process restart (implicit, since it's in-memory).

### 3.3 Combined retrieval
- At query time, both collections are queried (if the user collection exists for this session); results merged before reranking.
- Every retrieved point carries metadata: `source_type: "base" | "user"`, `filename`, `page_number`, `chunk_id`, `parent_id`.

---

## 4. Ingestion Pipeline (exact steps)

1. **Extract**: `unstructured.partition.pdf.partition_pdf(filename, strategy="hi_res")` → list of structural elements (titles, narrative text, tables, list items) with page numbers attached.
2. **Validate**: if extracted text (concatenated) is under a minimum threshold (e.g. < 200 characters), reject with a clear error: `"No extractable text found — this PDF may be a scanned image."`
3. **File size cap**: reject uploads over **15 MB per file**, and over **50 MB total per session**. Return a clear 413-style error, not a silent truncation.
4. **Table handling**: elements classified as tables by `unstructured` are converted to Markdown table syntax and kept as a single chunk (never split mid-table).
5. **Hierarchical chunking**:
   - **Parent chunks**: group consecutive elements by section/heading boundary, target ~1500-2000 characters each.
   - **Child chunks**: within each parent, split further using `RecursiveCharacterTextSplitter` (`chunk_size=400`, `chunk_overlap=80`, separators `["\n\n", "\n", ". ", " "]`), targeting ~300-500 characters each. Every child chunk stores a `parent_id` reference.
   - Child chunks are what gets embedded and indexed for retrieval matching. Parent chunk text is what gets passed to the LLM as context once a child chunk is matched (better precision on match, better context on generation).
6. **Content-hash dedup**: hash each uploaded file's bytes (SHA-256); if a file with the same hash was already processed in this session, skip reprocessing and reuse existing chunks.
7. **Embed**: batch child chunks in groups of 32, embed via `bge-base-en-v1.5` locally (`sentence-transformers`, `.encode(texts, batch_size=32, normalize_embeddings=True)`).
8. **Store**: upsert embedded child chunks into the appropriate Qdrant collection (base or session-scoped), with full metadata payload (see §7 data model). Store parent chunk text in the payload as well (`parent_text` field) — no separate DB needed since Qdrant payloads can hold this.

---

## 5. Retrieval Pipeline (exact steps)

1. **Query condensation** (only if conversation history exists for this session): call the primary LLM with a fixed prompt to rewrite the latest user message as a standalone question, using the running summary + last raw turn as context. Skip this step entirely on the first message of a session.
2. **Dense retrieval**: embed the (condensed) query with the same `bge-base-en-v1.5` model, search each active Qdrant collection (base always; user-scoped if it exists), `top_k=20` each.
3. **Sparse retrieval (BM25)**: maintain an in-memory BM25 index per collection (rebuilt incrementally on ingestion), retrieve `top_k=20`.
4. **Ensemble**: combine dense + BM25 results via `EnsembleRetriever` with weights `[0.6 dense, 0.4 sparse]`, dedupe by `chunk_id`, producing a merged candidate list (cap at 30 candidates before rerank).
5. **Rerank**: send merged candidates + condensed query to Cohere Rerank, take `top_n=5`. **On Cohere failure/timeout (wrap in try/except with a 5s timeout)**: fall back to the ensemble's own ranked order, take top 5, log the fallback event.
6. **Relevance threshold check**: if the top reranked result's relevance score is below a fixed threshold (e.g. `0.3` on Cohere's 0-1 relevance scale, tune during testing), treat as "no relevant context found" and skip generation — return the fixed fallback message (§6, step 4) directly without calling the LLM.

---

## 6. Generation Pipeline (exact steps)

1. **Build numbered context block**: for each of the top-5 reranked chunks, format as:
   ```
   [1] (source: report.pdf, page 4, base knowledge)
   <parent_text>
   ```
2. **System prompt** (fixed, do not let the LLM improvise beyond this):
   ```
   You are a knowledge assistant. Answer the user's question using ONLY the numbered context provided below. Every factual claim in your answer must be followed by the bracket number(s) of the source(s) it came from, e.g. [1] or [1][3]. If the context does not contain enough information to answer the question, respond exactly: "I don't have enough information in the provided documents to answer that." Do not use any outside knowledge. Do not guess.
   ```
3. **User message**: running summary + last raw turn (if any) + condensed question + numbered context block + original question.
4. **LLM call with fallback chain**:
   - Try Groq (`llama-3.3-70b-versatile`), timeout 15s.
   - On `429`/`5xx`/timeout → try OpenRouter free model, timeout 15s.
   - On failure → try Gemini `2.0-flash`, timeout 15s.
   - On all three failing → return a graceful error to the frontend: `"The assistant is temporarily unavailable. Please try again in a moment."` (never a raw stack trace or 500 with no message).
   - Log which provider actually served each request.
5. **Streaming**: use each provider's streaming API, forward tokens to the frontend via Server-Sent Events (SSE) as they arrive.
6. **Post-generation citation validation**: parse the bracket numbers `[n]` the LLM actually used; map each back to its stored chunk metadata (`filename`, `page_number`, `source_type`, verbatim `parent_text` snippet). If the LLM cites a number that wasn't in the provided context (hallucinated reference), drop that citation and log a warning — do not crash.
7. **Return payload**: `{ answer_text, citations: [{ marker, filename, page_number, source_type, snippet }] }`.
8. **Update conversation memory** (async, after response is sent — doesn't block the reply): append this Q&A as the new "last raw turn," and call the LLM once more to fold the previous summary + this turn into an updated running summary (cap at ~200 tokens, always keep it concise).

---

## 7. Data Models (Pydantic schemas — backend)

```python
class ChunkMetadata(BaseModel):
    chunk_id: str
    parent_id: str
    filename: str
    page_number: int
    source_type: Literal["base", "user"]
    parent_text: str  # full parent chunk, returned to LLM
    child_text: str   # the embedded/matched text

class Citation(BaseModel):
    marker: int
    filename: str
    page_number: int
    source_type: Literal["base", "user"]
    snippet: str  # verbatim, not paraphrased

class AskRequest(BaseModel):
    session_id: str
    question: str

class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    provider_used: str  # "groq" | "openrouter" | "gemini"

class UploadResponse(BaseModel):
    session_id: str
    filename: str
    pages_processed: int
    chunks_created: int
    status: Literal["success", "rejected"]
    reason: str | None = None  # populated if rejected

class SessionState(BaseModel):
    session_id: str
    created_at: float
    last_active: float
    running_summary: str = ""
    last_turn: tuple[str, str] | None = None  # (question, answer)
    has_uploaded_docs: bool = False
```

---

## 8. API Endpoint Contracts

| Method | Path | Purpose | Request | Response |
|---|---|---|---|---|
| GET | `/health` | Liveness/readiness | — | `200 {"status": "ready"}` or `503 {"status": "indexing"}` |
| POST | `/session` | Create a new session | — | `{"session_id": "..."}` |
| POST | `/upload` | Upload one PDF to a session | multipart form: `session_id`, `file` | `UploadResponse` |
| DELETE | `/session/{session_id}/documents` | Clear user-uploaded docs for a session | — | `{"status": "cleared"}` |
| POST | `/ask` | Ask a question (SSE streamed) | `AskRequest` (JSON) | SSE stream of tokens, final event with full `AskResponse` |
| DELETE | `/session/{session_id}` | Explicitly end a session | — | `{"status": "ended"}` |

- **CORS**: allow only the deployed Vercel frontend origin (and `localhost:3000` for dev). Never `allow_origins=["*"]` in production config.
- **Rate limiting**: simple per-`session_id` and per-IP limiter (e.g. `slowapi`), cap at something like 20 requests/minute — protects shared free-tier LLM quotas from being exhausted by one user during the review window.
- **API keys**: Groq, OpenRouter, Gemini, Cohere keys live only in backend environment variables (App Runner environment configuration), never sent to or readable by the frontend.

---

## 9. Session Lifecycle

- `session_id` is a UUID, generated by calling `POST /session` on every fresh page load. The frontend must **never** persist it in `localStorage`/cookies — hold it only in React state (in memory), so a browser refresh naturally results in a new session.
- Backend keeps a dict: `sessions: dict[str, SessionState]`, plus `dict[str, QdrantClient]` for in-memory user collections.
- A background `asyncio` task runs every few minutes, sweeping sessions where `last_active` is older than **30 minutes**, deleting their in-memory Qdrant collection and dict entries.
- No session data — summaries, uploaded chunks, vectors — is ever written to disk or any external store.

---

## 10. Chunking/Retrieval Parameters (exact numbers, tune only with evidence from testing)

| Parameter | Value |
|---|---|
| Parent chunk target size | 1500–2000 chars |
| Child chunk size | 400 chars |
| Child chunk overlap | 80 chars |
| Dense retrieval top_k | 20 |
| BM25 retrieval top_k | 20 |
| Ensemble weights | dense 0.6 / sparse 0.4 |
| Candidates sent to reranker | up to 30 |
| Final chunks after rerank | 5 |
| Relevance threshold (reject/fallback) | 0.3 (Cohere relevance score) |
| Max file size | 15 MB per file |
| Max total upload per session | 50 MB |
| Session TTL | 30 min inactivity |
| Conversation summary cap | ~200 tokens |
| LLM per-provider timeout | 15 seconds |
| Rate limit | 20 requests/min per session/IP |

---

## 11. Repository Structure

```
rag-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan/startup hook, routes
│   │   ├── config.py                # env vars, settings (pydantic-settings)
│   │   ├── models/
│   │   │   └── schemas.py           # Pydantic models from §7
│   │   ├── core/
│   │   │   ├── extraction.py        # unstructured PDF parsing
│   │   │   ├── chunking.py          # hierarchical parent/child splitter
│   │   │   ├── embeddings.py        # bge-base-en-v1.5 wrapper
│   │   │   ├── vector_store.py      # Qdrant wrapper (base + per-session)
│   │   │   ├── bm25_index.py        # BM25 index management
│   │   │   ├── retrieval.py         # hybrid retrieval + rerank + threshold logic
│   │   │   ├── llm_router.py        # Groq → OpenRouter → Gemini fallback chain
│   │   │   ├── generation.py        # prompt building, streaming, citation mapping
│   │   │   └── memory.py            # running summary + session state management
│   │   └── routes/
│   │       ├── session.py
│   │       ├── upload.py
│   │       └── ask.py
│   ├── knowledge_base/              # base PDFs, committed to repo
│   ├── tests/
│   │   ├── test_chunking.py
│   │   ├── test_retrieval.py
│   │   ├── test_grounding.py        # explicit hallucination/out-of-scope test
│   │   └── test_citations.py
│   ├── eval/
│   │   └── ragas_eval.py            # scripted eval with handwritten Q&A pairs
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/                         # Next.js app router
│   │   ├── page.tsx                 # main chat UI
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ChatWindow.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── CitationBadge.tsx        # clickable citation with source popover
│   │   ├── UploadPanel.tsx
│   │   └── SourceFilterToggle.tsx   # "base only / my docs only / both"
│   ├── lib/
│   │   └── api.ts                   # fetch wrappers for backend endpoints
│   ├── package.json
│   └── .env.local.example
└── README.md                         # architecture + design-decision writeup
```

---

## 12. Deployment Specification

- **Backend**: single Dockerfile, multi-stage build (install deps, bake `bge-base-en-v1.5` model weights into the image at build time via a `sentence-transformers` download step, so no runtime download dependency). Push to ECR, deploy via App Runner, instance size 1 vCPU / 2 GB, **min instances = 1** (always warm, no cold start), auto-scaling max = 1 (no need for more given expected load).
- **Frontend**: Next.js deployed to Vercel, environment variable `NEXT_PUBLIC_API_URL` pointing to the App Runner service URL.
- **Region**: pick one AWS region where App Runner is available (e.g. `us-east-1`) and keep ECR + App Runner in that same region.
- **Runtime window**: deploy ~1 day before submission, keep running through the review week, tear down after.

---

## 13. Testing & Evaluation Requirements

- `test_grounding.py` must include at least one test that asks a question **unrelated to any indexed document** and asserts the response is the exact fallback message, not a hallucinated answer.
- `test_citations.py` must assert every citation returned in a response maps to metadata that was genuinely part of the retrieved context for that query (no fabricated citations).
- `test_chunking.py` must assert parent/child relationships are correctly linked and no chunk exceeds size bounds.
- `test_retrieval.py` must assert the reranker-failure fallback path still returns results (mock Cohere failure).
- `eval/ragas_eval.py`: a small fixed set (8-10) of handwritten question/expected-answer/expected-source pairs run against the base knowledge base, scoring faithfulness and answer relevancy, printed as a summary report.

---

## 14. README Requirements (for the final submission)

The README must explicitly state, in plain language:
1. Architecture diagram/description (two-tier knowledge, hybrid retrieval, fallback chain).
2. Why each major tool was chosen over alternatives (self-hosted embeddings vs API, Qdrant vs FAISS/Pinecone, no Redis/Postgres given single-instance scope, in-memory-only for privacy).
3. How grounding/anti-hallucination is enforced (threshold + citation validation + fixed fallback message).
4. Known limitations and explicit trade-offs (single-instance only, in-memory means no horizontal scaling, session data is fully lost on restart by design).
5. How to run locally and how it's deployed.

---

**End of spec. Build in the order given in §11's structure: config/schemas → extraction/chunking → embeddings/vector store → retrieval → generation/LLM router → memory → API routes → frontend → tests/eval → deployment.**

---

## 15. Multi-Key Rotation (9 total fallback attempts)

You will provision **3 API keys per provider** — 3× Groq, 3× OpenRouter, 3× Gemini — giving 9 total attempts per request before the system gives up. Free-tier keys are usually tied to separate accounts/emails, so this is legitimate (not abuse) — it's exactly the kind of redundancy a real system uses when relying on free tiers.

### 15.1 Key storage
Environment variables, indexed:
```
GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3
OPENROUTER_API_KEY_1, OPENROUTER_API_KEY_2, OPENROUTER_API_KEY_3
GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3
```
Never hardcode these anywhere. All live only in App Runner's environment configuration.

### 15.2 Rotation logic (`llm_router.py`)
- Maintain an in-memory pool per provider: `[key_1, key_2, key_3]`, plus a rotating index (round-robin) so load spreads across keys over time rather than always hammering key 1 first.
- **Attempt order**: Groq (key A, then B, then C on failure) → OpenRouter (key A, B, C) → Gemini (key A, B, C). That's up to 9 attempts total for one request.
- **Distinguish failure types** — this matters, don't treat them the same:
  - `429` (rate limited) → try next key in the same provider immediately (this is the case the multi-key setup is specifically for).
  - `401`/`403` (invalid/revoked key) → mark that specific key as "dead" in memory for this process's lifetime (don't keep retrying a dead key every request — wastes a request slot), move to next key, **and trigger an admin notification** (see §16) since this needs manual fixing, unlike a transient rate limit.
  - `5xx`/timeout → treat as transient, try next key, no notification needed unless it becomes a pattern.
- Stop and return success on the first attempt that succeeds. Log which exact key/provider served each request (e.g. `"groq_key_2"`) for your own debugging, not shown to the end user.
- If **all 9 attempts fail**, return the graceful fallback message to the user (§6 step 4) **and trigger an admin notification** (§16) — this is the "everything is actually broken" case you want to know about immediately.

### 15.3 Where this changes the spec's data flow
Same flow as §6 step 4, just replace "Try Groq" with "Try Groq key 1 → key 2 → key 3" and so on for each provider before moving to the next provider.

---

## 16. Admin Failure Notification

**Mechanism: Telegram Bot API.** Chosen over email/Slack because it's free, requires no SMTP setup, delivers instantly as a push notification to your phone, and is a single HTTP POST — minimal code.

### 16.1 One-time setup (do this before build starts)
1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts, get a **bot token**.
2. Message your new bot anything (so it can message you back), then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser — find your **chat_id** in the JSON response.
3. Store both as env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### 16.2 Notification function (`core/notifications.py`)
```python
import httpx
import time

_last_alert_time: dict[str, float] = {}
COOLDOWN_SECONDS = 600  # don't spam — max one alert per alert-type per 10 min

async def notify_admin(alert_type: str, message: str):
    now = time.time()
    if now - _last_alert_time.get(alert_type, 0) < COOLDOWN_SECONDS:
        return  # suppressed, already alerted recently for this type
    _last_alert_time[alert_type] = now
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": f"[RAG Assistant] {alert_type}: {message}"},
            timeout=5.0,
        )
```
Wrap the call itself in try/except — a failed notification must never crash the actual request being served to the user.

### 16.3 Trigger points
- **All 9 LLM attempts exhausted** → `notify_admin("LLM_TOTAL_FAILURE", f"All providers/keys failed for a request at {timestamp}")`
- **A key returns 401/403** (looks revoked/invalid, not just rate-limited) → `notify_admin("KEY_INVALID", f"{provider} key #{n} appears invalid/revoked")`
- **Cohere rerank fails** (optional, lower priority — degrades quality, not a hard failure) → can skip notifying for this one, just log it, since the system still works via fallback.
- **Base knowledge index fails to build at startup** → this is the most critical one, notify immediately, since the app is unusable without it: `notify_admin("STARTUP_FAILURE", "Base knowledge index failed to build")`.

### 16.4 Cooldown
The 10-minute cooldown per alert type (§16.2) is essential — without it, a burst of failing requests would flood your phone with identical alerts. One alert per type per 10 minutes is enough to know something's wrong without noise.

---

## 17. Multi-Session Build System (Checkpoint-Driven Handoff)

Since you'll be starting a **new Claude Code chat for different parts of the build**, each session needs to know exactly what already exists, what's next, and not redo or contradict prior work. This is solved with a single tracked file: **`CHECKPOINT.md`**, kept at the repo root, updated at the end of every session.

### 17.1 `CHECKPOINT.md` — format, and who creates it

You do **not** need to create this file yourself. Every agent session's first job (per §17.2, step 2) is to **check the repo root for `CHECKPOINT.md`**:
- **If it doesn't exist yet** (first-ever session), the agent creates it with a `Session 0` entry using the template below, marking the project as just started, then proceeds to build the first step.
- **If it already exists**, the agent reads the most recent session entry's "Next steps" and continues from there — it does not create a new file or overwrite history.

Template (every session, including the first, appends an entry in this exact format):

```markdown
# Build Checkpoint

## Session Log

### Session N — [DATE] — [one-line summary]
- Status: [not started | in progress | phase complete]
- Completed: [what was actually built/changed this session, or "Nothing yet" for Session 0]
- Current phase: [Phase name — referencing §11 build order]
- Next steps:
  1. ...
  2. ...
- Known issues / deviations from spec: [None, or specifics with reasoning]
- Test status: [what passes/fails, or "No tests written yet"]
- Files touched this session: [list, or "none"]

---
(New sessions append below, most recent at the bottom, using the same template. Never edit or delete a previous session's entry — only append.)
```

### 17.2 Rules every agent session must follow
1. **Read `SPEC.md` (this document) in full first** — it is the locked spec, non-negotiable unless something is provably broken.
2. **Check the repo root for `CHECKPOINT.md`.** If it exists, read it in full, especially the most recent session's "Next steps." If it does not exist, this is the first session — create it now using the §17.1 template with a `Session 0` entry before doing anything else.
3. **Only work on the next incomplete step(s)** from the checkpoint (or, for a brand-new project, Phase 1 of §11's build order) — don't jump ahead into later build-order phases, even if it seems efficient, since that risks two sessions building overlapping/conflicting pieces.
4. **Write or update tests** for whatever is built this session (per §13), don't defer testing to "later."
5. **Before ending the session, append a new entry to `CHECKPOINT.md`** using the exact template in §17.1: incremented session number, date, what was completed, current phase, explicit next steps, any deviations/issues (be honest here — if something in the spec had to be adjusted, say what and why, don't silently change it), test status, and exact files touched. Never overwrite or delete earlier entries — only append.
6. **If blocked** (e.g., missing API key, ambiguous spec point) — do not guess silently. Note it clearly under "Known issues" in the checkpoint and, if it blocks further progress, stop and flag it rather than improvising a workaround that isn't in the spec.

### 17.3 Exact prompt to paste at the start of every new session

Use this verbatim (or near-verbatim) as your first message in each new Claude Code chat — it works identically whether this is the very first session or the tenth:

```
You are continuing work on the "Mini AI Knowledge Assistant" project — a RAG application.
Before doing anything else:

1. Read SPEC.md in full. This is the complete locked technical specification —
   architecture, exact tech stack, data models, API contracts, multi-key API
   rotation, admin notifications, and the build-order/handoff process are all
   in this single file. Follow it exactly — do not substitute technologies,
   change parameters, or redesign anything unless something is provably broken,
   in which case explain why in the checkpoint (see step 5).

2. Check the repo root for CHECKPOINT.md.
   - If it exists, read it in full, especially the most recent session
     entry's "Next steps" section. This tells you exactly what has been
     done so far and what to do next. Do not redo completed work. Do not
     skip ahead of the listed next steps.
   - If it does NOT exist, this is the very first session on this project.
     Create CHECKPOINT.md now, following the template in SPEC.md section 17.1,
     with a Session 0 entry, then proceed to Phase 1 of the build order in
     SPEC.md section 11.

3. Implement only the next incomplete step(s) (from the checkpoint, or Phase 1
   if this is a fresh start), following the build order in SPEC.md section 11.
   Write working code, following the exact repo structure, data models, and
   API contracts in the spec. Also follow the multi-key rotation (section 15)
   and admin notification (section 16) requirements wherever the current step
   touches the LLM router or startup logic.

4. Write or update tests for whatever you build this session, per SPEC.md
   section 13.

5. Before you finish, append a new entry to CHECKPOINT.md using the template
   in SPEC.md section 17.1: increment the session number, note the date, list
   exactly what you completed, the current phase, explicit next steps for the
   following session, any deviations from spec or known issues (be specific
   and honest), test status (what passes/fails), and the exact list of files
   you touched. Never overwrite or delete earlier entries — only append.

6. If you are blocked or must deviate from the spec, do not silently improvise —
   note it clearly in the checkpoint under "Known issues" and explain your
   reasoning.

Start now: read SPEC.md, then check for CHECKPOINT.md and read or create it
as appropriate, then tell me which step you're about to work on before you
begin writing code.
```

### 17.4 Why this works
- Every session is self-contained and stateless from the AI's point of view, but the **checkpoint file carries state across sessions** — this is exactly the same pattern as the app's own conversation-summary design (§6 step 8), just applied to your build process instead of the chat.
- You always know, at a glance, exactly how far the build has progressed and what's left, without having to re-explain context every time you open a new chat.
- If something breaks later, `CHECKPOINT.md`'s session log is a build history you can scroll back through to see exactly when and why a decision was made — useful both for debugging and for writing your README's design-decisions section later.

---

## 18. Summary of files you'll have at the end

```
rag-assistant/
├── SPEC.md                                # this entire document — the locked spec
├── CHECKPOINT.md                          # living build log, updated every session
├── backend/ ...
├── frontend/ ...
└── README.md                              # final write-up, uses checkpoint history as reference
```

Save this entire document as `SPEC.md` in the repo root. You do not need to create `CHECKPOINT.md` yourself — the first agent session will check for it, find it missing, and create it automatically per §17. Just start Session 1 using the exact prompt in §17.3, every time, in every new chat.
