"""
Test retrieval: reranker fallback path still returns results (§13).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_chunks():
    """Create mock chunks for retrieval testing."""
    return [
        {
            "chunk_id": f"chunk_{i}",
            "parent_id": f"parent_{i // 3}",
            "filename": "test.pdf",
            "page_number": i + 1,
            "source_type": "base",
            "parent_text": f"Parent text for chunk {i} with detailed information.",
            "child_text": f"Child text for chunk {i} about testing retrieval.",
            "score": 0.9 - (i * 0.05),
        }
        for i in range(10)
    ]


@pytest.fixture
def mock_embedding_service():
    """Mock embedding service."""
    service = MagicMock()
    service.embed_query.return_value = [0.1] * 768
    return service


@pytest.fixture
def mock_vector_store(mock_chunks):
    """Mock vector store that returns test chunks."""
    vs = MagicMock()
    vs.has_user_collection.return_value = False

    # Return mock search results
    vs.search.return_value = mock_chunks[:5]
    vs.base_client = MagicMock()
    return vs


@pytest.fixture
def mock_bm25_manager(mock_chunks):
    """Mock BM25 manager."""
    bm25 = MagicMock()
    bm25.search.return_value = mock_chunks[3:8]
    return bm25


class TestRetrieval:
    """Tests for the hybrid retrieval pipeline (§13)."""

    @pytest.mark.asyncio
    async def test_reranker_failure_fallback_returns_results(
        self, mock_embedding_service, mock_vector_store, mock_bm25_manager
    ):
        """
        Assert the reranker-failure fallback path still returns results.
        When Cohere rerank fails, we should fall back to ensemble order (§5 step 5).
        """
        from app.core.retrieval import retrieve
        from app.config import settings

        # Mock Cohere to raise an exception (simulating rerank failure)
        with patch("app.core.retrieval.cohere") as mock_cohere:
            mock_client = MagicMock()
            mock_client.rerank.side_effect = Exception("Cohere API unavailable")
            mock_cohere.Client.return_value = mock_client

            results = await retrieve(
                query="test query about machine learning",
                session_id=None,
                embedding_service=mock_embedding_service,
                vector_store=mock_vector_store,
                bm25_manager=mock_bm25_manager,
            )

            # Should still return results even without reranker
            assert len(results) > 0, (
                "Retrieval must return results even when Cohere rerank fails"
            )
            assert len(results) <= settings.RERANK_TOP_N

    @pytest.mark.asyncio
    async def test_retrieval_with_working_reranker(
        self, mock_embedding_service, mock_vector_store, mock_bm25_manager, mock_chunks
    ):
        """Test normal retrieval path with working reranker."""
        from app.core.retrieval import retrieve

        # Mock Cohere to succeed
        with patch("app.core.retrieval.cohere") as mock_cohere:
            mock_result = MagicMock()
            mock_result.results = [
                MagicMock(index=i, relevance_score=0.9 - (i * 0.1))
                for i in range(5)
            ]
            mock_client = MagicMock()
            mock_client.rerank.return_value = mock_result
            mock_cohere.Client.return_value = mock_client

            results = await retrieve(
                query="what is machine learning",
                session_id=None,
                embedding_service=mock_embedding_service,
                vector_store=mock_vector_store,
                bm25_manager=mock_bm25_manager,
            )

            assert len(results) > 0

    @pytest.mark.asyncio
    async def test_retrieval_below_threshold_returns_empty(
        self, mock_embedding_service, mock_vector_store, mock_bm25_manager
    ):
        """When top score is below threshold (0.3), return empty (§5 step 6)."""
        from app.core.retrieval import retrieve

        with patch("app.core.retrieval.cohere") as mock_cohere:
            # All scores below threshold
            mock_result = MagicMock()
            mock_result.results = [
                MagicMock(index=i, relevance_score=0.1)  # below 0.3 threshold
                for i in range(5)
            ]
            mock_client = MagicMock()
            mock_client.rerank.return_value = mock_result
            mock_cohere.Client.return_value = mock_client

            results = await retrieve(
                query="completely irrelevant query xyz123",
                session_id=None,
                embedding_service=mock_embedding_service,
                vector_store=mock_vector_store,
                bm25_manager=mock_bm25_manager,
            )

            # Should return empty when below relevance threshold
            assert len(results) == 0, (
                "Retrieval should return empty list when relevance is below threshold"
            )

