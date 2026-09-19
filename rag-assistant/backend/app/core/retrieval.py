"""
Hybrid retrieval pipeline: dense + BM25, ensemble merging, Cohere reranking,
and relevance threshold check. Exact implementation per SPEC.md §5.
"""

import asyncio
import logging

import cohere

from app.config import settings

logger = logging.getLogger(__name__)


async def retrieve(
    query: str,
    session_id: str | None,
    embedding_service,
    vector_store,
    bm25_manager,
    source_filter: str = "both",
) -> list[dict]:
    """
    Full hybrid retrieval pipeline (§5):
    1. Embed query
    2-3. Dense search on base + user collections
    4-5. BM25 search on base + user indices
    6. Ensemble merge (0.6 dense / 0.4 sparse), dedupe, cap at 30
    7. Cohere rerank (with fallback to ensemble order)
    8. Relevance threshold check
    9. Return top-5 chunks

    source_filter: "base" (search only base knowledge), "user" (search only
    this session's uploaded docs), or "both" (default — search everything).
    Powers the frontend's "base only / my docs only / both" toggle.
    """
    search_base = source_filter in ("base", "both")
    search_user = source_filter in ("user", "both")

    # Step 1: Embed query
    query_vector = embedding_service.embed_query(query)

    # Step 2: Dense retrieval — base collection
    base_dense = []
    if search_base:
        try:
            base_dense = vector_store.search(
                client=vector_store.base_client,
                collection_name=settings.QDRANT_BASE_COLLECTION,
                query_vector=query_vector,
                top_k=settings.DENSE_TOP_K,
            )
        except Exception as e:
            logger.warning(f"Base dense search failed: {e}")

    # Step 3: Dense retrieval — user collection (if exists)
    user_dense = []
    if search_user and session_id and vector_store.has_user_collection(session_id):
        try:
            user_client = vector_store.user_clients[session_id]
            user_dense = vector_store.search(
                client=user_client,
                collection_name=f"user_{session_id}",
                query_vector=query_vector,
                top_k=settings.DENSE_TOP_K,
            )
        except Exception as e:
            logger.warning(f"User dense search failed: {e}")

    # Step 4: BM25 — base index
    base_sparse = []
    if search_base:
        try:
            base_sparse = bm25_manager.search(
                collection_name=settings.QDRANT_BASE_COLLECTION,
                query=query,
                top_k=settings.BM25_TOP_K,
            )
        except Exception as e:
            logger.warning(f"Base BM25 search failed: {e}")

    # Step 5: BM25 — user index (if exists)
    user_sparse = []
    if search_user and session_id:
        try:
            user_sparse = bm25_manager.search(
                collection_name=f"user_{session_id}",
                query=query,
                top_k=settings.BM25_TOP_K,
            )
        except Exception as e:
            logger.debug(f"User BM25 search returned nothing: {e}")

    # Step 6: Ensemble merge — dedupe by chunk_id, weighted scoring
    combined_scores: dict[str, float] = {}
    chunk_map: dict[str, dict] = {}

    # Dense results (weight 0.6)
    for r in base_dense + user_dense:
        cid = r.get("chunk_id", "")
        if not cid:
            continue
        chunk_map[cid] = r
        score = r.get("score", 0.5)
        combined_scores[cid] = combined_scores.get(cid, 0) + score * settings.ENSEMBLE_DENSE_WEIGHT

    # Sparse results (weight 0.4)
    for r in base_sparse + user_sparse:
        cid = r.get("chunk_id", "")
        if not cid:
            continue
        if cid not in chunk_map:
            chunk_map[cid] = r
        score = r.get("score", 0.5)
        combined_scores[cid] = combined_scores.get(cid, 0) + score * settings.ENSEMBLE_SPARSE_WEIGHT

    # Sort by combined score, cap at 30
    merged = sorted(
        [
            {**chunk_map[cid], "chunk_id": cid, "score": score}
            for cid, score in combined_scores.items()
        ],
        key=lambda x: x["score"],
        reverse=True,
    )[: settings.RERANK_CANDIDATES_CAP]

    if not merged:
        return []

    # Step 7: Cohere rerank (with fallback)
    reranked_chunks = []
    try:
        co = cohere.Client(api_key=settings.COHERE_API_KEY)
        docs = [m.get("parent_text", m.get("child_text", "")) for m in merged]

        rerank_response = await asyncio.wait_for(
            asyncio.to_thread(
                co.rerank,
                query=query,
                documents=docs,
                model=settings.COHERE_RERANK_MODEL,
                top_n=settings.RERANK_TOP_N,
            ),
            timeout=settings.RERANK_TIMEOUT,
        )

        for res in rerank_response.results:
            chunk = merged[res.index].copy()
            chunk["relevance_score"] = res.relevance_score
            reranked_chunks.append(chunk)

    except Exception as e:
        logger.warning(f"Cohere reranking failed, falling back to ensemble order: {e}")
        reranked_chunks = merged[: settings.RERANK_TOP_N]
        for c in reranked_chunks:
            c["relevance_score"] = c.get("score", 0)

    # Step 8: Relevance threshold check
    if not reranked_chunks:
        return []

    top_score = reranked_chunks[0].get("relevance_score", 0)
    if top_score < settings.RELEVANCE_THRESHOLD:
        logger.info(
            f"Top relevance score {top_score:.3f} below threshold "
            f"{settings.RELEVANCE_THRESHOLD} — returning empty"
        )
        return []

    # Step 9: Return top chunks
    return reranked_chunks
