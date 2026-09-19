"""
LangChain-powered RAG Pipeline for the Mini AI Knowledge System.
Integrates:
- LangChain Document and TextSplitters
- FastEmbed embeddings & Qdrant Cloud vector search
- BM25 sparse keyword search
- Cohere / FlashRank neural reranking
- LangChain LCEL (LangChain Expression Language) streaming chains
- Identity: Mini AI Knowledge System built by Sachin
"""

import os
import re
import uuid
import time
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple, AsyncGenerator

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from rank_bm25 import BM25Okapi
from fastembed import TextEmbedding

from app.config import settings
from app.models import Citation, SessionState

logger = logging.getLogger(__name__)

# =============================================================================
# 1. System Prompt & Instructions
# =============================================================================
SYSTEM_PROMPT = (
    "You are the Mini AI Knowledge System, an advanced intelligent assistant designed and built by Sachin.\n\n"
    "Identity Rules (STRICT):\n"
    "- If asked who you are, what you are, or who created/built you, ALWAYS state that you are the 'Mini AI Knowledge System built by Sachin'.\n"
    "- NEVER mention, acknowledge, or cite any underlying AI models or companies (do NOT mention OpenAI, GPT, Google, Gemini, Meta, LLaMA, Anthropic, Groq, etc.). You are solely the Mini AI Knowledge System built by Sachin.\n\n"
    "Answering Guidelines:\n"
    "1. When numbered context passages ([1], [2], etc.) are provided: Ground your core answer in that context and cite every claim using [1], [2], etc. "
    "In addition to the grounded facts, provide helpful explanations, code snippets, or background so the answer is thorough, clear, and comprehensive.\n"
    "2. When no context passages match (e.g. greetings, casual chat, broad knowledge questions): "
    "Answer politely, thoroughly, and intelligently from your broad knowledge, and gently mention that the user can also upload PDFs to query specific documents."
)


# =============================================================================
# 2. Document Extraction & Hierarchical Chunking (LangChain)
# =============================================================================
def parse_pdf_file(file_bytes: bytes, filename: str) -> List[Document]:
    """Parse PDF file bytes into LangChain Document objects."""
    import tempfile
    from unstructured.partition.pdf import partition_pdf

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        elements = partition_pdf(filename=tmp_path, strategy="fast")
        documents = []
        for el in elements:
            text = str(el).strip()
            if len(text) > 10:
                page_num = getattr(el.metadata, "page_number", 1) or 1
                documents.append(
                    Document(
                        page_content=text,
                        metadata={"filename": filename, "page_number": page_num}
                    )
                )
        return documents
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def split_into_hierarchical_chunks(
    docs: List[Document], filename: str, source_type: str = "user"
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Hierarchical chunking using LangChain's RecursiveCharacterTextSplitter:
    - Parent chunks: ~1750 characters (returned to LLM for full context)
    - Child chunks: ~400 characters (dense vector search & BM25)
    """
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.PARENT_CHUNK_TARGET_SIZE,
        chunk_overlap=settings.PARENT_CHUNK_OVERLAP,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHILD_CHUNK_TARGET_SIZE,
        chunk_overlap=settings.CHILD_CHUNK_OVERLAP,
    )

    parent_chunks = []
    child_chunks = []

    # Group document text by page
    pages_text: Dict[int, List[str]] = {}
    for d in docs:
        p = d.metadata.get("page_number", 1)
        pages_text.setdefault(p, []).append(d.page_content)

    for page_num, text_parts in pages_text.items():
        full_page_text = "\n\n".join(text_parts)
        parents = parent_splitter.split_text(full_page_text)

        for p_idx, parent_text in enumerate(parents):
            parent_id = f"{filename}_p{page_num}_{p_idx}"
            parent_chunks.append({
                "parent_id": parent_id,
                "filename": filename,
                "page_number": page_num,
                "source_type": source_type,
                "text": parent_text,
            })

            children = child_splitter.split_text(parent_text)
            for c_idx, child_text in enumerate(children):
                child_chunks.append({
                    "chunk_id": f"{parent_id}_c{c_idx}",
                    "parent_id": parent_id,
                    "filename": filename,
                    "page_number": page_num,
                    "source_type": source_type,
                    "parent_text": parent_text,
                    "child_text": child_text,
                })

    return parent_chunks, child_chunks


# =============================================================================
# 3. Embeddings & Vector Storage
# =============================================================================
def _chunk_id_to_int(chunk_id: str) -> int:
    digest = hashlib.sha256(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


class VectorStoreManager:
    def __init__(self):
        logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
        self.embedder = TextEmbedding(model_name=settings.EMBEDDING_MODEL)

        # Base collection in Qdrant Cloud
        if settings.QDRANT_CLOUD_URL and settings.QDRANT_CLOUD_API_KEY:
            logger.info(f"Connecting to Qdrant Cloud: {settings.QDRANT_CLOUD_URL}")
            self.base_client = QdrantClient(
                url=settings.QDRANT_CLOUD_URL,
                api_key=settings.QDRANT_CLOUD_API_KEY,
            )
        else:
            logger.info(f"Using local Qdrant at {settings.QDRANT_BASE_PATH}")
            self.base_client = QdrantClient(path=settings.QDRANT_BASE_PATH)

        self.user_clients: Dict[str, QdrantClient] = {}

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        embeddings = list(self.embedder.embed(texts, batch_size=settings.EMBEDDING_BATCH_SIZE))
        return [e.tolist() for e in embeddings]

    def embed_query(self, query: str) -> List[float]:
        return list(self.embedder.embed([query]))[0].tolist()

    def init_base_collection(self, dimension: int = 768):
        collections = [c.name for c in self.base_client.get_collections().collections]
        if settings.QDRANT_BASE_COLLECTION not in collections:
            self.base_client.create_collection(
                collection_name=settings.QDRANT_BASE_COLLECTION,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            logger.info(f"Created base collection: {settings.QDRANT_BASE_COLLECTION}")

    def get_or_create_user_client(self, session_id: str, dimension: int = 768) -> QdrantClient:
        if session_id not in self.user_clients:
            client = QdrantClient(location=":memory:")
            client.create_collection(
                collection_name=f"user_{session_id}",
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            self.user_clients[session_id] = client
        return self.user_clients[session_id]

    def upsert_chunks(self, client: QdrantClient, collection_name: str, chunks: List[Dict[str, Any]]):
        if not chunks:
            return
        texts = [c["child_text"] for c in chunks]
        embeddings = self.embed_texts(texts)
        points = [
            PointStruct(
                id=_chunk_id_to_int(c["chunk_id"]),
                vector=emb,
                payload=c,
            )
            for c, emb in zip(chunks, embeddings)
        ]
        client.upsert(collection_name=collection_name, points=points)

    def search_dense(self, client: QdrantClient, collection_name: str, query_vector: List[float], top_k: int = 20) -> List[Dict[str, Any]]:
        results = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True,
        ).points
        return [{**p.payload, "score": p.score} for p in results]

    def delete_user_collection(self, session_id: str):
        if session_id in self.user_clients:
            del self.user_clients[session_id]


# =============================================================================
# 4. Sparse BM25 Keyword Search
# =============================================================================
class BM25IndexManager:
    def __init__(self):
        self.indexes: Dict[str, Tuple[BM25Okapi, List[Dict[str, Any]]]] = {}

    def build_index(self, collection_name: str, chunks: List[Dict[str, Any]]):
        if not chunks:
            return
        tokenized_corpus = [c["child_text"].lower().split() for c in chunks]
        self.indexes[collection_name] = (BM25Okapi(tokenized_corpus), chunks)

    def search(self, collection_name: str, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        if collection_name not in self.indexes:
            return []
        bm25, chunks = self.indexes[collection_name]
        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)
        scored_pairs = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [{**chunks[i], "score": float(score)} for i, score in scored_pairs if score > 0]


# =============================================================================
# 5. Reranking Service (Cohere API + FlashRank Fallback)
# =============================================================================
class RerankerService:
    def __init__(self):
        self.cohere_client = None
        if settings.COHERE_API_KEY:
            try:
                import cohere
                self.cohere_client = cohere.Client(api_key=settings.COHERE_API_KEY)
                logger.info("Initialized Cohere reranker client")
            except Exception as e:
                logger.warning(f"Could not initialize Cohere: {e}")

        self.flashrank = None
        try:
            from flashrank import Ranker
            self.flashrank = Ranker(model_name=settings.RERANKER_MODEL)
            logger.info("Loaded FlashRank fallback reranker")
        except Exception as e:
            logger.warning(f"Could not initialize FlashRank: {e}")

    def rerank(self, query: str, documents: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        if not documents:
            return []

        # 1. Try Cohere
        if self.cohere_client:
            try:
                texts = [d.get("child_text", d.get("parent_text", "")) for d in documents]
                resp = self.cohere_client.rerank(
                    model=settings.COHERE_RERANK_MODEL,
                    query=query,
                    documents=texts,
                    top_n=top_n,
                )
                reranked = []
                for res in resp.results:
                    doc = documents[res.index].copy()
                    doc["rerank_score"] = float(res.relevance_score)
                    reranked.append(doc)
                return reranked
            except Exception as e:
                logger.warning(f"Cohere rerank failed: {e}. Falling back to FlashRank.")

        # 2. Try FlashRank
        if self.flashrank:
            try:
                from flashrank import RerankRequest
                passages = [{"id": i, "text": d.get("child_text", ""), "meta": d} for i, d in enumerate(documents)]
                results = self.flashrank.rerank(RerankRequest(query=query, passages=passages))
                reranked = []
                for r in results[:top_n]:
                    doc = r["meta"].copy()
                    doc["rerank_score"] = float(r["score"])
                    reranked.append(doc)
                return reranked
            except Exception as e:
                logger.warning(f"FlashRank rerank failed: {e}")

        return documents[:top_n]


# =============================================================================
# 6. Hybrid Retrieval Pipeline
# =============================================================================
async def hybrid_retrieve(
    query: str,
    session_id: Optional[str],
    source_filter: str,
    vector_store: VectorStoreManager,
    bm25: BM25IndexManager,
    reranker: RerankerService,
) -> List[Dict[str, Any]]:
    search_base = source_filter in ("base", "both")
    search_user = source_filter in ("user", "both") and session_id and (session_id in vector_store.user_clients)

    query_vec = vector_store.embed_query(query)

    # Dense retrieval
    base_dense = vector_store.search_dense(vector_store.base_client, settings.QDRANT_BASE_COLLECTION, query_vec, settings.DENSE_TOP_K) if search_base else []
    user_dense = vector_store.search_dense(vector_store.user_clients[session_id], f"user_{session_id}", query_vec, settings.DENSE_TOP_K) if search_user else []

    # Sparse retrieval
    base_sparse = bm25.search(settings.QDRANT_BASE_COLLECTION, query, settings.BM25_TOP_K) if search_base else []
    user_sparse = bm25.search(f"user_{session_id}", query, settings.BM25_TOP_K) if search_user else []

    # Weighted Ensemble Merge (0.6 dense + 0.4 sparse)
    merged: Dict[str, Dict[str, Any]] = {}
    for chunk in base_dense + user_dense:
        cid = chunk.get("chunk_id", "")
        score = chunk.get("score", 0.0) * settings.ENSEMBLE_DENSE_WEIGHT
        if cid in merged:
            merged[cid]["ensemble_score"] += score
        else:
            merged[cid] = {**chunk, "ensemble_score": score}

    for chunk in base_sparse + user_sparse:
        cid = chunk.get("chunk_id", "")
        score = chunk.get("score", 0.0) * settings.ENSEMBLE_SPARSE_WEIGHT
        if cid in merged:
            merged[cid]["ensemble_score"] += score
        else:
            merged[cid] = {**chunk, "ensemble_score": score}

    candidates = sorted(merged.values(), key=lambda x: x["ensemble_score"], reverse=True)[:settings.RERANK_CANDIDATES_CAP]
    if not candidates:
        return []

    # Rerank
    reranked = reranker.rerank(query, candidates, top_n=settings.RERANK_TOP_N)

    # Threshold filter
    if reranked and reranked[0].get("rerank_score", reranked[0].get("ensemble_score", 0)) < settings.RELEVANCE_THRESHOLD:
        return []

    return reranked[:settings.RERANK_TOP_N]


# =============================================================================
# 7. LangChain Multi-Provider Model Factory & LCEL Chains
# =============================================================================
def get_langchain_chat_model(provider: str = "groq", key: str = ""):
    """Build a standard LangChain ChatModel instance."""
    if provider == "groq":
        return ChatOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=key,
            model=settings.GROQ_MODEL,
            temperature=0.3,
            streaming=True,
        )
    elif provider == "openrouter":
        return ChatOpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=key,
            model=settings.OPENROUTER_MODEL,
            temperature=0.3,
            streaming=True,
        )
    elif provider == "gemini":
        return ChatOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=key,
            model=settings.GEMINI_MODEL,
            temperature=0.3,
            streaming=True,
        )
    raise ValueError(f"Unknown provider {provider}")


class LangChainRAGPipeline:
    def __init__(self):
        self.vector_store = VectorStoreManager()
        self.bm25 = BM25IndexManager()
        self.reranker = RerankerService()

        # Build prompt template using standard LangChain
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", (
                "{history_block}\n\n"
                "Document Context:\n{context_block}\n\n"
                "Question: {question}"
            ))
        ])

    def get_llm_candidates(self) -> List[Tuple[str, str]]:
        candidates = []
        for k in settings.groq_keys:
            candidates.append(("groq", k))
        for k in settings.openrouter_keys:
            candidates.append(("openrouter", k))
        for k in settings.gemini_keys:
            candidates.append(("gemini", k))
        return candidates

    async def astream_rag_answer(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        session: SessionState,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens using LangChain LCEL chain: prompt | llm | StrOutputParser()."""
        # Format context block with numbered citations [1], [2]
        if chunks:
            context_parts = []
            for i, c in enumerate(chunks, 1):
                fn = c.get("filename", "unknown")
                p = c.get("page_number", 1)
                text = c.get("parent_text", c.get("child_text", ""))
                context_parts.append(f"[{i}] (Source: {fn}, Page {p})\n{text}")
            context_block = "\n\n".join(context_parts)
        else:
            context_block = (
                "(No matching document passages found. Answer with general knowledge and "
                "offer to assist with any uploaded documents.)"
            )

        # Format conversation history
        history_parts = []
        if session.running_summary:
            history_parts.append(f"Prior Conversation Summary: {session.running_summary}")
        if session.recent_turns:
            history_parts.append("Recent Conversation:")
            for q, a in session.recent_turns:
                history_parts.append(f"User: {q}\nAssistant: {a}")
        history_block = "\n".join(history_parts) if history_parts else "(No prior conversation history)"

        # Fallback rotation over candidate LLMs
        for provider, key in self.get_llm_candidates():
            try:
                llm = get_langchain_chat_model(provider, key)
                chain = self.prompt_template | llm | StrOutputParser()

                async for token in chain.astream({
                    "history_block": history_block,
                    "context_block": context_block,
                    "question": question,
                }):
                    yield token
                return
            except Exception as e:
                logger.warning(f"Provider {provider} failed: {e}. Trying next in chain...")

        yield "The assistant is temporarily unavailable. Please try again in a moment."


# =============================================================================
# 8. Citation Parser
# =============================================================================
def parse_bracket_citations(answer: str, chunks: List[Dict[str, Any]]) -> List[Citation]:
    """Parse [n] citations from answer and link to chunk metadata."""
    citations = []
    seen = set()
    for match in re.finditer(r"\[(\d+)\]", answer):
        marker = int(match.group(1))
        if marker in seen or marker < 1 or marker > len(chunks):
            continue
        seen.add(marker)
        chunk = chunks[marker - 1]
        citations.append(
            Citation(
                marker=marker,
                filename=chunk.get("filename", "unknown"),
                page_number=chunk.get("page_number", 1),
                source_type=chunk.get("source_type", "base"),
                snippet=chunk.get("parent_text", chunk.get("child_text", "")),
            )
        )
    return citations


# =============================================================================
# 9. Session Manager
# =============================================================================
class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}

    def create_session(self) -> str:
        sid = str(uuid.uuid4())
        now = time.time()
        self.sessions[sid] = SessionState(
            session_id=sid,
            created_at=now,
            last_active=now,
        )
        return sid

    def get_session(self, sid: str) -> Optional[SessionState]:
        s = self.sessions.get(sid)
        if s:
            s.last_active = time.time()
        return s

    def update_turn(self, sid: str, question: str, answer: str):
        s = self.get_session(sid)
        if s:
            s.last_turn = (question, answer)
            s.recent_turns.append((question, answer))
            if len(s.recent_turns) > 3:
                s.recent_turns = s.recent_turns[-3:]

    def delete_session(self, sid: str):
        if sid in self.sessions:
            del self.sessions[sid]


# Global singletons
_rag_pipeline = None
_session_manager = None

def get_rag_pipeline() -> LangChainRAGPipeline:
    global _rag_pipeline
    if _rag_pipeline is None:
        _rag_pipeline = LangChainRAGPipeline()
    return _rag_pipeline

def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
