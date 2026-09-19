import logging
from flashrank import Ranker, RerankRequest
from app.config import settings

logger = logging.getLogger(__name__)

class RerankerService:
    def __init__(self):
        logger.info(f"Loading flashrank model: {settings.RERANKER_MODEL}")
        self.ranker = Ranker(model_name=settings.RERANKER_MODEL)
        logger.info("Reranker model loaded successfully")

    def rerank(self, query: str, documents: list[dict], top_n: int = 5) -> list[dict]:
        """Rerank documents using flashrank. Each doc dict must have 'child_text' key."""
        if not documents:
            return []

        passages = []
        for i, doc in enumerate(documents):
            text = doc.get("child_text", doc.get("text", ""))
            passages.append({"id": i, "text": text, "meta": doc})

        rerank_request = RerankRequest(query=query, passages=passages)
        results = self.ranker.rerank(rerank_request)

        reranked = []
        for r in results[:top_n]:
            doc = r["meta"]
            doc["rerank_score"] = r["score"]
            reranked.append(doc)

        return reranked

_instance = None
def get_reranker() -> RerankerService:
    global _instance
    if _instance is None:
        _instance = RerankerService()
    return _instance
