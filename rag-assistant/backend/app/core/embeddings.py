import logging
from sentence_transformers import SentenceTransformer
from app.config import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
        self.model = SentenceTransformer(settings.EMBEDDING_MODEL)
        
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        logger.debug(f"Embedding {len(texts)} texts")
        embeddings = self.model.encode(texts, batch_size=32, normalize_embeddings=True)
        return [embedding.tolist() for embedding in embeddings]
        
    def embed_query(self, query: str) -> list[float]:
        logger.debug("Embedding query")
        embedding = self.model.encode(query, normalize_embeddings=True)
        return embedding.tolist()

_embedding_service = None

def get_embedding_service() -> EmbeddingService:
    """Singleton pattern to get the EmbeddingService instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
