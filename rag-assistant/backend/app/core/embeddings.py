import logging
from fastembed import TextEmbedding
from app.config import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        logger.info(f"Loading fastembed model: {settings.EMBEDDING_MODEL}")
        self.model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)
        logger.info("Embedding model loaded successfully")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = list(self.model.embed(texts, batch_size=settings.EMBEDDING_BATCH_SIZE))
        return [e.tolist() for e in embeddings]

    def embed_query(self, query: str) -> list[float]:
        embeddings = list(self.model.embed([query]))
        return embeddings[0].tolist()

_instance = None
def get_embedding_service() -> EmbeddingService:
    global _instance
    if _instance is None:
        _instance = EmbeddingService()
    return _instance
