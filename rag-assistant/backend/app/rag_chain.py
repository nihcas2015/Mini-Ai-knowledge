import os
import re
import uuid
import time
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple, AsyncGenerator

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langchain_core.runnables import (
    RunnablePassthrough,
    RunnableLambda,
)

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from rank_bm25 import BM25Okapi
from fastembed import TextEmbedding

from app.config import settings
from app.models import Citation, SessionState

logger = logging.getLogger(__name__)

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


def parse_pdf_file(file_bytes: bytes, filename: str) -> List[Document]:
    import io

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        documents = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.strip()
            if len(text) > 10:
                documents.append(
                    Document(
                        page_content=text,
                        metadata={"filename": filename, "page_number": i + 1}
                    )
                )
        if documents:
            return documents
    except Exception as e:
        logger.warning(f"pypdf fast extraction failed for {filename}: {e}. Trying unstructured...")

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


def _chunk_id_to_int(chunk_id: str) -> int:
    digest = hashlib.sha256(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


class VectorStoreManager:
    def __init__(self):
        logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
        self.embedder = TextEmbedding(model_name=settings.EMBEDDING_MODEL)

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
            logger.info("Loaded FlashRank reranker")
        except Exception as e:
            logger.warning(f"Could not initialize FlashRank: {e}")

    def rerank(self, query: str, documents: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        if not documents:
            return []

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

    base_dense = vector_store.search_dense(vector_store.base_client, settings.QDRANT_BASE_COLLECTION, query_vec, settings.DENSE_TOP_K) if search_base else []
    user_dense = vector_store.search_dense(vector_store.user_clients[session_id], f"user_{session_id}", query_vec, settings.DENSE_TOP_K) if search_user else []

    base_sparse = bm25.search(settings.QDRANT_BASE_COLLECTION, query, settings.BM25_TOP_K) if search_base else []
    user_sparse = bm25.search(f"user_{session_id}", query, settings.BM25_TOP_K) if search_user else []

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

    reranked = reranker.rerank(query, candidates, top_n=settings.RERANK_TOP_N)

    if reranked and reranked[0].get("rerank_score", reranked[0].get("ensemble_score", 0)) < settings.RELEVANCE_THRESHOLD:
        return []

    return reranked[:settings.RERANK_TOP_N]


def get_langchain_chat_model(provider: str, key: str) -> ChatOpenAI:
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

        candidate_models = []
        for k in settings.groq_keys:
            candidate_models.append(get_langchain_chat_model("groq", k))
        for k in settings.openrouter_keys:
            candidate_models.append(get_langchain_chat_model("openrouter", k))
        for k in settings.gemini_keys:
            candidate_models.append(get_langchain_chat_model("gemini", k))

        if candidate_models:
            self.llm = candidate_models[0].with_fallbacks(candidate_models[1:]) if len(candidate_models) > 1 else candidate_models[0]
        else:
            self.llm = get_langchain_chat_model("groq", "dummy")

        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", (
                "{history_block}\n\n"
                "Document Context:\n{context_block}\n\n"
                "Question: {question}"
            ))
        ])

        self.retriever_runnable = RunnableLambda(self._retrieve_step)
        self.context_formatter = RunnableLambda(self._format_context)
        self.history_formatter = RunnableLambda(self._format_history)

        self.rag_prep_chain = (
            RunnablePassthrough.assign(chunks=self.retriever_runnable)
            .assign(
                context_block=lambda x: self.context_formatter.invoke(x["chunks"]),
                history_block=lambda x: self.history_formatter.invoke(x["session"]),
            )
        )

        self.generation_chain = (
            self.prompt_template
            | self.llm
            | StrOutputParser()
        )

        self.full_rag_chain = self.rag_prep_chain | self.generation_chain

    async def _retrieve_step(self, inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        sid = inputs.get("session_id") or (inputs["session"].session_id if "session" in inputs else None)
        return await hybrid_retrieve(
            query=inputs["question"],
            session_id=sid,
            source_filter=inputs.get("source_filter", "both"),
            vector_store=self.vector_store,
            bm25=self.bm25,
            reranker=self.reranker,
        )

    def _format_context(self, chunks: List[Dict[str, Any]]) -> str:
        if not chunks:
            return (
                "(No matching document passages found. Answer with general knowledge and "
                "offer to assist with any uploaded documents.)"
            )
        context_parts = []
        for i, c in enumerate(chunks, 1):
            fn = c.get("filename", "unknown")
            p = c.get("page_number", 1)
            text = c.get("parent_text", c.get("child_text", ""))
            context_parts.append(f"[{i}] (Source: {fn}, Page {p})\n{text}")
        return "\n\n".join(context_parts)

    def _format_history(self, session: SessionState) -> str:
        history_parts = []
        if session.running_summary:
            history_parts.append(f"Prior Conversation Summary: {session.running_summary}")
        if session.recent_turns:
            history_parts.append("Recent Conversation:")
            for q, a in session.recent_turns:
                history_parts.append(f"User: {q}\nAssistant: {a}")
        return "\n".join(history_parts) if history_parts else "(No prior conversation history)"

    async def astream_rag(
        self,
        question: str,
        session: SessionState,
        source_filter: str = "both",
    ) -> Tuple[List[Dict[str, Any]], AsyncGenerator[str, None]]:
        inputs = {
            "question": question,
            "session": session,
            "session_id": session.session_id,
            "source_filter": source_filter,
        }
        prep_data = await self.rag_prep_chain.ainvoke(inputs)
        chunks = prep_data["chunks"]

        async def token_stream():
            try:
                async for token in self.generation_chain.astream(prep_data):
                    yield token
            except Exception as e:
                logger.error(f"Generation error: {e}", exc_info=True)
                yield f"\n\n[Error generating response: {e}]"

        return chunks, token_stream()


def parse_bracket_citations(answer: str, chunks: List[Dict[str, Any]]) -> List[Citation]:
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
