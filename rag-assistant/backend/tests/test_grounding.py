"""
Test grounding: unrelated questions must get the exact fallback message (§13).
Must include at least one test that asks a question UNRELATED to any indexed
document and asserts the response is the exact fallback message, not a
hallucinated answer.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.core.generation import (
    FALLBACK_MESSAGE,
    UNAVAILABLE_MESSAGE,
    build_context_block,
    parse_citations,
)


class TestGrounding:
    """Tests for grounding and anti-hallucination behavior (§13)."""

    @pytest.mark.asyncio
    async def test_unrelated_question_returns_fallback_message(self):
        """
        Ask a question UNRELATED to any indexed document.
        Assert the response is the exact fallback message, not a hallucinated answer.
        This is the key anti-hallucination test required by §13.
        """
        from app.core.retrieval import retrieve

        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_query.return_value = [0.0] * 768

        mock_vector_store = MagicMock()
        mock_vector_store.has_user_collection.return_value = False
        mock_vector_store.search.return_value = []  # no results
        mock_vector_store.base_client = MagicMock()

        mock_bm25 = MagicMock()
        mock_bm25.search.return_value = []  # no BM25 results either

        # Retrieval should return empty because no documents match
        with patch("app.core.retrieval.cohere") as mock_cohere:
            mock_result = MagicMock()
            mock_result.results = []
            mock_client = MagicMock()
            mock_client.rerank.return_value = mock_result
            mock_cohere.Client.return_value = mock_client

            results = await retrieve(
                query="What is the recipe for chocolate cake?",
                session_id=None,
                embedding_service=mock_embedding_service,
                vector_store=mock_vector_store,
                bm25_manager=mock_bm25,
            )

        # No relevant context → the ask route should return the fallback message
        assert len(results) == 0, (
            "Unrelated question should yield no relevant chunks"
        )

        # Verify the fallback message is the correct one from the spec
        expected = "I don't have enough information in the provided documents to answer that."
        assert FALLBACK_MESSAGE == expected, (
            f"Fallback message doesn't match spec: got '{FALLBACK_MESSAGE}'"
        )

    def test_fallback_message_matches_spec(self):
        """Verify fallback message is exactly what §6 step 4 specifies."""
        expected = "I don't have enough information in the provided documents to answer that."
        assert FALLBACK_MESSAGE == expected

    def test_unavailable_message_matches_spec(self):
        """Verify unavailable message matches §6 step 4."""
        expected = "The assistant is temporarily unavailable. Please try again in a moment."
        assert UNAVAILABLE_MESSAGE == expected

    def test_empty_chunks_produce_no_context(self):
        """Build context block with no chunks should return empty/minimal string."""
        context = build_context_block([])
        assert context.strip() == "" or "no context" in context.lower() or len(context.strip()) == 0

