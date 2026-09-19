import logging
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

class BM25Index:
    def __init__(self, bm25: BM25Okapi, chunks: list[dict]):
        self.bm25 = bm25
        self.chunks = chunks

class BM25IndexManager:
    def __init__(self):
        self.indices: dict[str, BM25Index] = {}
        
    def _tokenize(self, text: str) -> list[str]:
        """Simple whitespace tokenizer for BM25."""
        if not text:
            return []
        return text.lower().split()
        
    def build_index(self, collection_name: str, chunks: list[dict]):
        """Builds a new BM25 index for the given chunks."""
        logger.info(f"Building BM25 index for {collection_name} with {len(chunks)} chunks")
        tokenized_corpus = [self._tokenize(chunk.get("child_text", "")) for chunk in chunks]
        bm25 = BM25Okapi(tokenized_corpus)
        self.indices[collection_name] = BM25Index(bm25, chunks)
        
    def add_to_index(self, collection_name: str, chunks: list[dict]):
        """Adds new chunks to an existing index by rebuilding it."""
        logger.info(f"Adding {len(chunks)} chunks to BM25 index for {collection_name}")
        existing_chunks = []
        if collection_name in self.indices:
            existing_chunks = self.indices[collection_name].chunks
        all_chunks = existing_chunks + chunks
        self.build_index(collection_name, all_chunks)
        
    def search(self, collection_name: str, query: str, top_k: int = 20) -> list[dict]:
        """Searches the BM25 index and returns chunk metadata dicts with scores."""
        if collection_name not in self.indices:
            logger.debug(f"No BM25 index found for {collection_name}")
            return []
            
        logger.debug(f"Searching BM25 index for {collection_name}")
        tokenized_query = self._tokenize(query)
        if not tokenized_query:
            return []

        index = self.indices[collection_name]
        scores = index.bm25.get_scores(tokenized_query)
        
        # Normalize scores to 0-1 range for ensemble compatibility
        max_score = max(scores) if len(scores) > 0 and max(scores) > 0 else 1.0
        
        # Zip scores with chunks and sort
        scored_chunks = list(zip(scores, index.chunks))
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        
        # Return top_k non-zero results with normalized score
        results = []
        for score, chunk in scored_chunks[:top_k]:
            if score > 0:
                result = dict(chunk)
                result["score"] = score / max_score  # normalize to 0-1
                results.append(result)
        return results
        
    def delete_index(self, collection_name: str):
        """Deletes a BM25 index."""
        if collection_name in self.indices:
            logger.info(f"Deleting BM25 index for {collection_name}")
            del self.indices[collection_name]

_bm25_manager = None

def get_bm25_manager() -> BM25IndexManager:
    """Singleton pattern to get the BM25IndexManager instance."""
    global _bm25_manager
    if _bm25_manager is None:
        _bm25_manager = BM25IndexManager()
    return _bm25_manager
