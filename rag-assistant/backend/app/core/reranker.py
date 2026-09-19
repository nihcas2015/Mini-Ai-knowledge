import logging
import asyncio
from app.config import settings

logger = logging.getLogger(__name__)

class RerankerService:
    def __init__(self):
        self.cohere_client = None
        if settings.COHERE_API_KEY:
            try:
                import cohere
                self.cohere_client = cohere.Client(api_key=settings.COHERE_API_KEY)
                logger.info(f"Initialized Cohere reranker client with model: {settings.COHERE_RERANK_MODEL}")
            except Exception as e:
                logger.warning(f"Failed to initialize Cohere client: {e}")

        # Always initialize flashrank as lightweight fallback
        self.flashrank_ranker = None
        try:
            from flashrank import Ranker
            logger.info(f"Loading flashrank model: {settings.RERANKER_MODEL}")
            self.flashrank_ranker = Ranker(model_name=settings.RERANKER_MODEL)
            logger.info("Flashrank reranker model loaded successfully")
        except Exception as e:
            logger.warning(f"Could not load Flashrank: {e}")

    def rerank(self, query: str, documents: list[dict], top_n: int = 5) -> list[dict]:
        """Rerank documents using Cohere API if available, else Flashrank."""
        if not documents:
            return []

        # 1. Try Cohere Rerank if configured
        if self.cohere_client:
            try:
                doc_texts = [doc.get("child_text", doc.get("text", "")) for doc in documents]
                response = self.cohere_client.rerank(
                    model=settings.COHERE_RERANK_MODEL,
                    query=query,
                    documents=doc_texts,
                    top_n=top_n,
                )
                reranked = []
                for result in response.results:
                    doc = documents[result.index].copy()
                    doc["rerank_score"] = float(result.relevance_score)
                    reranked.append(doc)
                logger.info(f"Cohere successfully reranked {len(documents)} down to {len(reranked)}")
                return reranked
            except Exception as e:
                logger.warning(f"Cohere rerank failed: {e}. Falling back to Flashrank...")

        # 2. Try Flashrank
        if self.flashrank_ranker:
            try:
                from flashrank import RerankRequest
                passages = []
                for i, doc in enumerate(documents):
                    text = doc.get("child_text", doc.get("text", ""))
                    passages.append({"id": i, "text": text, "meta": doc})

                rerank_request = RerankRequest(query=query, passages=passages)
                results = self.flashrank_ranker.rerank(rerank_request)

                reranked = []
                for r in results[:top_n]:
                    doc = r["meta"].copy()
                    doc["rerank_score"] = float(r["score"])
                    reranked.append(doc)
                logger.info(f"Flashrank reranked {len(documents)} down to {len(reranked)}")
                return reranked
            except Exception as e:
                logger.warning(f"Flashrank rerank failed: {e}")

        # 3. Fallback: return original top candidates unchanged
        return documents[:top_n]


_instance = None
def get_reranker() -> RerankerService:
    global _instance
    if _instance is None:
        _instance = RerankerService()
    return _instance
