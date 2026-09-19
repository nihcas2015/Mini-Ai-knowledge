import hashlib
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.config import settings

logger = logging.getLogger(__name__)


def _chunk_id_to_point_id(chunk_id: str) -> int:
    digest = hashlib.sha256(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


class VectorStoreManager:
    def __init__(self):
        # Base collection lives in Qdrant Cloud
        if settings.QDRANT_CLOUD_URL and settings.QDRANT_CLOUD_API_KEY:
            logger.info(f"Connecting to Qdrant Cloud: {settings.QDRANT_CLOUD_URL}")
            self.base_client = QdrantClient(
                url=settings.QDRANT_CLOUD_URL,
                api_key=settings.QDRANT_CLOUD_API_KEY,
            )
        else:
            logger.info(f"Using local Qdrant at {settings.QDRANT_BASE_PATH}")
            self.base_client = QdrantClient(path=settings.QDRANT_BASE_PATH)

        self.user_clients: dict[str, QdrantClient] = {}

    def init_base_collection(self, dimension: int = 768):
        collections = self.base_client.get_collections().collections
        exists = any(c.name == settings.QDRANT_BASE_COLLECTION for c in collections)
        if not exists:
            self.base_client.create_collection(
                collection_name=settings.QDRANT_BASE_COLLECTION,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            logger.info(f"Created base collection: {settings.QDRANT_BASE_COLLECTION}")
        else:
            logger.info(f"Base collection already exists: {settings.QDRANT_BASE_COLLECTION}")

    def get_or_create_user_collection(self, session_id: str, dimension: int = 768) -> QdrantClient:
        if session_id not in self.user_clients:
            client = QdrantClient(location=":memory:")
            collection_name = f"user_{session_id}"
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            self.user_clients[session_id] = client
            logger.info(f"Created user collection: {collection_name}")
        return self.user_clients[session_id]

    def upsert_chunks(self, client, collection_name, chunk_ids, embeddings, payloads):
        logger.info(f"Upserting {len(chunk_ids)} chunks into {collection_name}")
        points = [
            PointStruct(
                id=_chunk_id_to_point_id(cid),
                vector=vec,
                payload=payload,
            )
            for cid, vec, payload in zip(chunk_ids, embeddings, payloads)
        ]
        client.upsert(collection_name=collection_name, points=points)

    def search(self, client, collection_name, query_vector, top_k=20):
        results = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True,
        ).points
        return [
            {**point.payload, "score": point.score}
            for point in results
        ]

    def delete_user_collection(self, session_id: str):
        if session_id in self.user_clients:
            del self.user_clients[session_id]
            logger.info(f"Deleted user collection for session {session_id}")

    def has_user_collection(self, session_id: str) -> bool:
        return session_id in self.user_clients


_instance = None
def get_vector_store() -> VectorStoreManager:
    global _instance
    if _instance is None:
        _instance = VectorStoreManager()
    return _instance
