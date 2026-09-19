"""
Script to populate Qdrant Cloud with curated base knowledge:
- Computer Science & Algorithms (Sorting, Searching, Data Structures)
- Artificial Intelligence & Machine Learning (RAG, Embeddings, LLMs)
- Software Engineering & System Architecture
- System Identity: Mini AI Knowledge System built by Sachin
"""

import uuid
import logging
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QDRANT_URL = "https://625902a1-61df-45e9-9aa3-89874262ef45.australia-southeast1-0.gcp.cloud.qdrant.io"
QDRANT_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6NWU0NjVmMzgtZmI4ZS00ZDdhLWFhNWMtMzc2MmUzMGY4MDQ5In0.s2KG4r8C4J4tVBjSMGsRruLoHsz6T-nPbtPoHXvwJMs"
COLLECTION_NAME = "base_knowledge"
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"

DOCUMENTS = [
    {
        "filename": "System_Overview.md",
        "page": 1,
        "title": "Mini AI Knowledge System Architecture",
        "text": (
            "The Mini AI Knowledge System is an advanced AI assistant created and built by Sachin. "
            "It combines dense vector retrieval via Qdrant Cloud, sparse lexical retrieval via BM25, "
            "reranking powered by Cohere and FlashRank, and token-by-token streaming LLM synthesis. "
            "The system is engineered by Sachin to provide grounded document analysis, multi-turn conversational "
            "memory, running summaries, and interactive inline citations."
        )
    },
    {
        "filename": "Computer_Science_Algorithms.md",
        "page": 1,
        "title": "Sorting Algorithms Overview and Complexity",
        "text": (
            "Sorting algorithms organize elements in a specified order (numerical or lexicographical). "
            "1. QuickSort: Divide-and-conquer algorithm with average time complexity O(n log n) and worst-case O(n^2). Space complexity O(log n). Not stable by default.\n"
            "2. MergeSort: Stable divide-and-conquer algorithm with guaranteed O(n log n) time complexity in all cases. Space complexity O(n).\n"
            "3. HeapSort: Comparison-based sorting using a binary heap. Time complexity O(n log n) in all cases, space complexity O(1). Not stable.\n"
            "4. TimSort: Hybrid stable sorting algorithm derived from MergeSort and InsertionSort. Used by Python and Java. Time complexity O(n log n), best-case O(n).\n"
            "5. InsertionSort: Simple comparison sort efficient for small datasets or nearly sorted arrays. Time complexity O(n^2), best-case O(n), space O(1)."
        )
    },
    {
        "filename": "Computer_Science_Algorithms.md",
        "page": 2,
        "title": "Graph and Search Algorithms",
        "text": (
            "Search algorithms locate target data within collections or graph structures:\n"
            "1. Binary Search: Efficient search on sorted arrays with time complexity O(log n) and space complexity O(1).\n"
            "2. Breadth-First Search (BFS): Graph traversal exploring neighbors level-by-level using a FIFO queue. Time complexity O(V + E). Finds the shortest path in unweighted graphs.\n"
            "3. Depth-First Search (DFS): Graph traversal exploring as deep as possible before backtracking using a stack or recursion. Time complexity O(V + E).\n"
            "4. Dijkstra's Algorithm: Greedy algorithm finding single-source shortest paths in graphs with non-negative edge weights using a priority queue. Time complexity O((V + E) log V).\n"
            "5. A* Search: Best-first graph search algorithm using heuristics (f(n) = g(n) + h(n)) to find optimal paths efficiently."
        )
    },
    {
        "filename": "Data_Structures.md",
        "page": 1,
        "title": "Core Data Structures: Trees, Hash Tables, and Heaps",
        "text": (
            "Essential computer science data structures:\n"
            "1. Hash Table: Key-value mapping utilizing hash functions. Average search, insert, and delete complexity O(1). Worst-case O(n) during hash collisions.\n"
            "2. Binary Search Tree (BST): Node-based binary tree where left child < parent < right child. Average lookup O(log n), worst-case O(n) if unbalanced.\n"
            "3. AVL Tree & Red-Black Tree: Self-balancing BSTs guaranteeing O(log n) time complexity for search, insertion, and deletion.\n"
            "4. Binary Heap (Min/Max): Complete binary tree satisfying the heap property. Find-min/max is O(1), insert and extract-min/max are O(log n).\n"
            "5. Trie (Prefix Tree): Tree data structure used for efficient retrieval of strings, autocomplete, and dictionary prefix searches with O(L) complexity where L is key length."
        )
    },
    {
        "filename": "AI_and_Machine_Learning.md",
        "page": 1,
        "title": "Retrieval-Augmented Generation (RAG) and Vector Search",
        "text": (
            "Retrieval-Augmented Generation (RAG) is an AI architecture that enhances Large Language Models (LLMs) "
            "by retrieving relevant factual knowledge from external vector databases before generating a response. "
            "RAG pipelines consist of: 1) Document ingestion and hierarchical chunking; 2) Dense embedding generation "
            "via models like BAAI/bge-base-en-v1.5; 3) Approximate Nearest Neighbor (ANN) vector indexing (e.g. HNSW in Qdrant); "
            "4) Hybrid retrieval combining BM25 sparse keyword search and dense cosine similarity; 5) Cross-encoder reranking "
            "(e.g. Cohere Rerank); and 6) Context-augmented prompt generation with strict citations to eliminate hallucinations."
        )
    },
    {
        "filename": "Software_Architecture.md",
        "page": 1,
        "title": "Modern Cloud Architecture, Microservices, and APIs",
        "text": (
            "Software architecture fundamentals for scalable web systems:\n"
            "1. Microservices vs Monolith: Microservices decouple business domains into independently deployable services communicating over HTTP/gRPC or message brokers (Kafka, RabbitMQ).\n"
            "2. RESTful APIs: Stateless architectural style using standard HTTP verbs (GET, POST, PUT, DELETE) and JSON payloads for client-server communication.\n"
            "3. Server-Sent Events (SSE): Unidirectional HTTP streaming protocol enabling servers to push real-time token streams to browser clients without WebSocket overhead.\n"
            "4. Caching Strategies: Cache-Aside, Write-Through, and Write-Back using Redis or Memcached to reduce database load and achieve sub-millisecond read latency.\n"
            "5. Horizontal Scaling: Distributing workload across multiple stateless computing instances (e.g. AWS EC2) behind a load balancer."
        )
    }
]

def chunk_id_to_point_id(chunk_id: str) -> int:
    digest = hashlib.sha256(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)

def main():
    logger.info("Initializing Qdrant Cloud client...")
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_KEY)

    # Re-create or ensure collection
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        logger.info(f"Creating collection {COLLECTION_NAME}...")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )

    logger.info(f"Loading embedding model {EMBEDDING_MODEL}...")
    embedder = TextEmbedding(model_name=EMBEDDING_MODEL)

    texts = [doc["text"] for doc in DOCUMENTS]
    logger.info(f"Embedding {len(texts)} base knowledge passages...")
    embeddings = list(embedder.embed(texts))

    points = []
    for i, (doc, emb) in enumerate(zip(DOCUMENTS, embeddings)):
        cid = str(uuid.uuid4())
        payload = {
            "chunk_id": cid,
            "parent_id": f"parent-{i}",
            "filename": doc["filename"],
            "page_number": doc["page"],
            "source_type": "base",
            "parent_text": doc["text"],
            "child_text": doc["text"],
            "title": doc["title"],
        }
        points.append(
            PointStruct(
                id=chunk_id_to_point_id(cid),
                vector=emb.tolist(),
                payload=payload,
            )
        )

    logger.info(f"Upserting {len(points)} points into Qdrant Cloud '{COLLECTION_NAME}'...")
    client.upsert(collection_name=COLLECTION_NAME, points=points)

    count = client.count(collection_name=COLLECTION_NAME).count
    logger.info(f"SUCCESS! '{COLLECTION_NAME}' now contains {count} base knowledge vectors!")

if __name__ == "__main__":
    main()

