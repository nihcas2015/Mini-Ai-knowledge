import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.config import settings

logger = logging.getLogger(__name__)

class VectorStoreManager:
    def __init__(self):
        logger.info(f"Initializing base Qdrant client at {settings.QDRANT_BASE_PATH}")
        self.base_client = QdrantClient(path=settings.QDRANT_BASE_PATH)
        self.user_clients: dict[str, QdrantClient] = {}
        
    def init_base_collection(self, dimension: int = 768):
        collection_name = 'base_knowledge'
        try:
            self.base_client.recreate_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
            )
            logger.info(f"Recreated base collection: {collection_name}")
        except Exception as e:
            logger.error(f"Error initializing base collection: {e}")
            raise
            
    def get_or_create_user_collection(self, session_id: str, dimension: int = 768) -> QdrantClient:
        collection_name = f'user_{session_id}'
        if session_id not in self.user_clients:
            logger.info(f"Creating in-memory Qdrant client for session {session_id}")
            client = QdrantClient(location=':memory:')
            client.recreate_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
            )
            self.user_clients[session_id] = client
        return self.user_clients[session_id]
        
    def upsert_chunks(self, client: QdrantClient, collection_name: str, chunk_ids: list[str], embeddings: list[list[float]], payloads: list[dict]):
        logger.info(f"Upserting {len(chunk_ids)} chunks into {collection_name}")
        points = [
            PointStruct(
                id=abs(hash(cid)) % (2**63),  # Qdrant needs int IDs
                vector=vec,
                payload=payload,
            )
            for cid, vec, payload in zip(chunk_ids, embeddings, payloads)
        ]
        client.upsert(collection_name=collection_name, points=points)
        
    def search(self, client: QdrantClient, collection_name: str, query_vector: list[float], top_k: int = 20) -> list[dict]:
        logger.debug(f"Searching {collection_name} for top {top_k} results")
        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k
        )
        # Return payload dicts with score attached
        output = []
        for hit in results:
            item = dict(hit.payload) if hit.payload else {}
            item["score"] = hit.score
            output.append(item)
        return output
        
    def delete_user_collection(self, session_id: str):
        if session_id in self.user_clients:
            logger.info(f"Deleting user collection for session {session_id}")
            del self.user_clients[session_id]
            
    def has_user_collection(self, session_id: str) -> bool:
        return session_id in self.user_clients

_vector_store_manager = None

def get_vector_store() -> VectorStoreManager:
    """Singleton pattern to get the VectorStoreManager instance."""
    global _vector_store_manager
    if _vector_store_manager is None:
        _vector_store_manager = VectorStoreManager()
    return _vector_store_manager
