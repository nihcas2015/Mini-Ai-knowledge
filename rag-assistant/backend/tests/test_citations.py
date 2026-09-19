"""
Test citations: every citation must map to genuine retrieved context (§13).
Must assert every citation returned in a response maps to metadata that was
genuinely part of the retrieved context for that query — no fabricated citations.
"""

import pytest
from app.core.generation import parse_citations
from app.models.schemas import Citation


@pytest.fixture
def sample_chunks():
    """Chunks that were genuinely retrieved for a query."""
    return [
        {
            "chunk_id": "chunk_001",
            "parent_id": "parent_001",
            "filename": "report.pdf",
            "page_number": 4,
            "source_type": "base",
            "parent_text": "Revenue increased by 15% in Q3 2024 compared to Q2.",
            "child_text": "Revenue increased by 15%.",
        },
        {
            "chunk_id": "chunk_002",
            "parent_id": "parent_002",
            "filename": "analysis.pdf",
            "page_number": 12,
            "source_type": "base",
            "parent_text": "The company expanded into three new markets.",
            "child_text": "Expanded into new markets.",
        },
        {
            "chunk_id": "chunk_003",
            "parent_id": "parent_003",
            "filename": "user_doc.pdf",
            "page_number": 1,
            "source_type": "user",
            "parent_text": "Profit margins remained stable at 22%.",
            "child_text": "Profit margins stable.",
        },
    ]


class TestCitations:
    """Tests for citation validation and mapping (§13)."""

    def test_valid_citations_map_to_retrieved_context(self, sample_chunks):
        """
        Every citation in the answer must map to metadata from the
        genuinely retrieved context — no fabricated citations allowed.
        """
        # Simulate an LLM answer that cites [1] and [3]
        answer = (
            "Revenue grew by 15% in Q3 [1]. "
            "Profit margins held at 22% [3]."
        )

        citations = parse_citations(answer, sample_chunks)

        # All returned citations must reference valid chunk indices
        for citation in citations:
            assert 1 <= citation.marker <= len(sample_chunks), (
                f"Citation marker [{citation.marker}] is out of range "
                f"(only {len(sample_chunks)} chunks provided)"
            )

            # The citation metadata must match the corresponding chunk
            chunk = sample_chunks[citation.marker - 1]
            assert citation.filename == chunk["filename"], (
                f"Citation [{citation.marker}] filename mismatch: "
                f"'{citation.filename}' vs '{chunk['filename']}'"
            )
            assert citation.page_number == chunk["page_number"]
            assert citation.source_type == chunk["source_type"]

    def test_hallucinated_citation_is_dropped(self, sample_chunks):
        """
        If the LLM cites a number that wasn't in the provided context
        (hallucinated reference), it must be dropped, not crash (§6 step 6).
        """
        # Answer cites [5] which doesn't exist (only 3 chunks)
        answer = (
            "Revenue grew by 15% [1]. "
            "Some hallucinated claim [5]. "
            "Margins are stable [3]."
        )

        citations = parse_citations(answer, sample_chunks)

        # [5] should be dropped, only [1] and [3] remain
        markers = [c.marker for c in citations]
        assert 5 not in markers, (
            "Hallucinated citation [5] should be dropped"
        )
        assert 1 in markers, "Valid citation [1] should be kept"
        assert 3 in markers, "Valid citation [3] should be kept"

    def test_no_citations_in_answer(self, sample_chunks):
        """Answer with no citation markers should return empty citations list."""
        answer = "The data shows some interesting trends."
        citations = parse_citations(answer, sample_chunks)
        assert len(citations) == 0

    def test_duplicate_citations_handled(self, sample_chunks):
        """Duplicate citation markers should not create duplicate Citation objects."""
        answer = "Revenue grew [1] and continued to grow [1] in subsequent quarters."
        citations = parse_citations(answer, sample_chunks)

        markers = [c.marker for c in citations]
        # Should deduplicate
        assert markers.count(1) == 1, "Duplicate citations should be deduplicated"

    def test_citation_snippet_is_verbatim(self, sample_chunks):
        """Citation snippet must be verbatim parent_text, not paraphrased."""
        answer = "Revenue grew by 15% [1]."
        citations = parse_citations(answer, sample_chunks)

        citation_1 = next(c for c in citations if c.marker == 1)
        expected_snippet = sample_chunks[0]["parent_text"]
        assert citation_1.snippet == expected_snippet, (
            f"Citation snippet must be verbatim. "
            f"Got: '{citation_1.snippet}', Expected: '{expected_snippet}'"
        )

    def test_all_valid_citations_preserved(self, sample_chunks):
        """All valid citations in the answer should be preserved."""
        answer = "Growth was 15% [1], new markets [2], margins stable [3]."
        citations = parse_citations(answer, sample_chunks)

        markers = sorted([c.marker for c in citations])
        assert markers == [1, 2, 3], (
            f"All valid citations should be preserved. Got: {markers}"
        )

