import logging
from app.config import settings
from app.core.reranker import get_reranker

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
    Full hybrid retrieval pipeline:
    1. Embed query
    2-3. Dense search (base + user)
    4-5. BM25 search (base + user)
    6. Ensemble merge (0.6 dense + 0.4 sparse)
    7. Rerank with flashrank
    8. Relevance threshold check
    9. Return top-5 chunks
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

    # Step 3: Dense retrieval — user collection
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

    # Step 5: BM25 — user index
    user_sparse = []
    if search_user and session_id:
        try:
            user_sparse = bm25_manager.search(
                collection_name=f"user_{session_id}",
                query=query,
                top_k=settings.BM25_TOP_K,
            )
        except Exception as e:
            logger.warning(f"User BM25 search failed: {e}")

    # Step 6: Ensemble merge
    scored: dict[str, dict] = {}

    for chunk in base_dense + user_dense:
        cid = chunk.get("chunk_id", "")
        score = chunk.get("score", 0.0) * settings.ENSEMBLE_DENSE_WEIGHT
        if cid in scored:
            scored[cid]["ensemble_score"] += score
        else:
            scored[cid] = {**chunk, "ensemble_score": score}

    for chunk in base_sparse + user_sparse:
        cid = chunk.get("chunk_id", "")
        score = chunk.get("score", 0.0) * settings.ENSEMBLE_SPARSE_WEIGHT
        if cid in scored:
            scored[cid]["ensemble_score"] += score
        else:
            scored[cid] = {**chunk, "ensemble_score": score}

    # Sort by ensemble score, cap at 30
    candidates = sorted(scored.values(), key=lambda x: x["ensemble_score"], reverse=True)
    candidates = candidates[:settings.RERANK_CANDIDATES_CAP]

    if not candidates:
        return []

    # Step 7: Rerank with flashrank
    try:
        reranker = get_reranker()
        reranked = reranker.rerank(
            query=query,
            documents=candidates,
            top_n=settings.RERANK_TOP_N,
        )
        logger.info(f"Reranked {len(candidates)} candidates to {len(reranked)} results")
    except Exception as e:
        logger.warning(f"Reranking failed, using ensemble order: {e}")
        reranked = candidates[:settings.RERANK_TOP_N]

    # Step 8: Relevance threshold
    if reranked and reranked[0].get("rerank_score", reranked[0].get("ensemble_score", 0)) < settings.RELEVANCE_THRESHOLD:
        logger.info("Top result below relevance threshold, returning empty")
        return []

    return reranked[:settings.RERANK_TOP_N]
