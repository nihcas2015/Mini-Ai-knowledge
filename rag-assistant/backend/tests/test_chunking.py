"""
Test chunking: parent/child relationships and size bounds (§13).
"""

import pytest
from app.core.chunking import create_hierarchical_chunks


def _make_elements(texts: list[str], element_type: str = "NarrativeText") -> list[dict]:
    """Create mock elements as returned by extraction."""
    return [
        {
            "type": element_type,
            "text": text,
            "page_number": i + 1,
            "metadata": {},
        }
        for i, text in enumerate(texts)
    ]


class TestChunking:
    """Tests for hierarchical parent/child chunking (§13)."""

    def test_parent_child_relationships_linked(self):
        """Assert parent/child relationships are correctly linked."""
        # Create enough text to produce multiple chunks
        long_text = "This is a test sentence with enough content. " * 30
        elements = _make_elements([long_text])

        parent_chunks, child_chunks = create_hierarchical_chunks(
            elements, "test.pdf", "base"
        )

        assert len(parent_chunks) > 0, "Should produce at least one parent"
        assert len(child_chunks) > 0, "Should produce at least one child"

        # Every child must reference a valid parent
        parent_ids = {p["chunk_id"] for p in parent_chunks}
        for child in child_chunks:
            assert child["parent_id"] in parent_ids, (
                f"Child {child['chunk_id']} references parent {child['parent_id']} "
                f"which doesn't exist in parent set"
            )

    def test_child_chunk_size_bounds(self):
        """Assert no child chunk exceeds the configured size."""
        # Use a large block of text
        long_text = "A" * 5000
        elements = _make_elements([long_text])

        _, child_chunks = create_hierarchical_chunks(
            elements, "test.pdf", "base"
        )

        max_expected = 400 + 80 + 50  # chunk_size + overlap + safety margin
        for child in child_chunks:
            assert len(child["child_text"]) <= max_expected, (
                f"Child chunk too large: {len(child['child_text'])} chars "
                f"(max expected ~{max_expected})"
            )

    def test_metadata_preserved(self):
        """Assert filename, page_number, source_type are correct on all chunks."""
        elements = _make_elements(
            ["Some content about machine learning and artificial intelligence. " * 15]
        )

        parent_chunks, child_chunks = create_hierarchical_chunks(
            elements, "research.pdf", "user"
        )

        for chunk in child_chunks:
            assert chunk["filename"] == "research.pdf"
            assert chunk["source_type"] == "user"
            assert isinstance(chunk["page_number"], int)
            assert chunk["page_number"] >= 1

    def test_empty_elements_produce_no_chunks(self):
        """Empty input should produce no chunks."""
        parent_chunks, child_chunks = create_hierarchical_chunks(
            [], "empty.pdf", "base"
        )
        assert len(parent_chunks) == 0
        assert len(child_chunks) == 0

    def test_table_elements_not_split(self):
        """Table elements should be kept as single chunks, never split mid-table."""
        table_text = (
            "| Column A | Column B | Column C |\n"
            "| --- | --- | --- |\n"
            "| data1 | data2 | data3 |\n"
            "| data4 | data5 | data6 |\n"
        )
        elements = _make_elements([table_text], element_type="Table")

        _, child_chunks = create_hierarchical_chunks(
            elements, "tables.pdf", "base"
        )

        # Find chunks containing table content — the table should not be split
        table_chunks = [c for c in child_chunks if "|" in c["child_text"]]
        # Table rows should stay together in at least one chunk
        if table_chunks:
            any_full = any("data1" in c["child_text"] and "data6" in c["child_text"]
                          for c in table_chunks)
            # If table is small enough, it should be in one chunk
            if len(table_text) <= 400:
                assert any_full, "Small table should remain in a single chunk"

    def test_child_has_parent_text(self):
        """Each child chunk must carry its parent's full text."""
        text = "Detailed explanation of retrieval augmented generation systems. " * 20
        elements = _make_elements([text])

        parent_chunks, child_chunks = create_hierarchical_chunks(
            elements, "rag.pdf", "base"
        )

        parent_map = {p["chunk_id"]: p for p in parent_chunks}
        for child in child_chunks:
            parent = parent_map.get(child["parent_id"])
            assert parent is not None
            assert child["parent_text"] == parent["parent_text"]
            assert len(child["parent_text"]) > 0

