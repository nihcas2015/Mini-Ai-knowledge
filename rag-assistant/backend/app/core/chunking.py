"""
Hierarchical parent/child chunking (§4 step 5).
Groups consecutive elements into parent chunks by heading boundary (~1500-2000 chars),
then splits the full parent text into child chunks (400 chars, 80 overlap).
Tables are never split mid-table.
"""

import uuid
import logging
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

logger = logging.getLogger(__name__)


def create_hierarchical_chunks(
    elements: list[dict], filename: str, source_type: str
) -> tuple[list[dict], list[dict]]:
    """
    Groups consecutive elements into parent chunks by heading/section boundary,
    then splits the concatenated parent text into child chunks.

    Args:
        elements: List of extracted elements from PDF parsing.
        filename: Name of the source file.
        source_type: "base" or "user".

    Returns:
        tuple of (parent_chunks, child_chunks) where each item is a list of dicts
        compatible with ChunkMetadata fields.
    """
    if not elements:
        return [], []

    logger.info(f"Creating hierarchical chunks for {filename}")
    parent_chunks: list[dict] = []
    child_chunks: list[dict] = []

    # §4 step 5 specifies separators ["\n\n", "\n", ". ", " "]. If none of
    # those appear in a stretch of text (e.g. a long unbroken ID/URL/base64
    # blob with no whitespace), RecursiveCharacterTextSplitter has nothing
    # left to split on and returns the whole span as one oversized chunk —
    # this is a real edge case caught by tests/test_chunking.py's size-bound
    # test. Appending "" as the final fallback guarantees a hard character-
    # count split as a last resort, so no child chunk can ever exceed the
    # configured size bound, without changing behavior for normal prose.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHILD_CHUNK_SIZE,
        chunk_overlap=settings.CHILD_CHUNK_OVERLAP,
        separators=[*settings.CHILD_CHUNK_SEPARATORS, ""],
    )

    # Accumulate elements into parent groups
    current_group: list[dict] = []
    current_group_len = 0

    def _flush_parent(group: list[dict]):
        """Process a group of elements into one parent chunk and its child chunks."""
        if not group:
            return

        parent_id = str(uuid.uuid4())

        # Separate tables from non-table elements
        table_elements = [e for e in group if e.get("type") == "Table"]
        non_table_elements = [e for e in group if e.get("type") != "Table"]

        # Build full parent text from ALL elements (tables + non-tables)
        parent_text = "\n\n".join(e["text"] for e in group if e.get("text"))
        first_page = group[0].get("page_number") or 1

        # Track parent chunk metadata
        parent_chunks.append({
            "chunk_id": parent_id,
            "filename": filename,
            "page_number": first_page,
            "source_type": source_type,
            "parent_text": parent_text,
        })

        # --- Child chunks from non-table content ---
        # Concatenate all non-table text, THEN split (spec §4 step 5:
        # "within each parent, split further using RecursiveCharacterTextSplitter")
        non_table_text = "\n\n".join(
            e["text"] for e in non_table_elements if e.get("text")
        )
        if non_table_text.strip():
            splits = splitter.split_text(non_table_text)
            for split_text in splits:
                if not split_text.strip():
                    continue
                # Determine which page this split came from (approximate)
                page = _find_page_for_text(split_text, non_table_elements, first_page)
                child_chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "parent_id": parent_id,
                    "filename": filename,
                    "page_number": page,
                    "source_type": source_type,
                    "parent_text": parent_text,
                    "child_text": split_text,
                })

        # --- Table elements: never split mid-table (§4 step 4) ---
        for table_elem in table_elements:
            child_chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "parent_id": parent_id,
                "filename": filename,
                "page_number": table_elem.get("page_number") or first_page,
                "source_type": source_type,
                "parent_text": parent_text,
                "child_text": table_elem["text"],
            })

    def _find_page_for_text(
        text: str, elements: list[dict], default_page: int
    ) -> int:
        """Best-effort: find which element's page a split came from."""
        for elem in elements:
            if elem.get("text") and text[:50] in elem["text"]:
                return elem.get("page_number") or default_page
        return default_page

    # --- Group elements into parent chunks ---
    for elem in elements:
        elem_type = elem.get("type", "").lower()
        text = elem.get("text", "")
        is_heading = "title" in elem_type or "heading" in elem_type

        # Start a new parent group on heading boundary or size limit
        if (is_heading and current_group_len > 0) or current_group_len > settings.PARENT_CHUNK_TARGET_SIZE:
            _flush_parent(current_group)
            current_group = []
            current_group_len = 0

        current_group.append(elem)
        current_group_len += len(text)

    # Flush remaining
    _flush_parent(current_group)

    logger.info(
        f"  {filename}: {len(parent_chunks)} parents, {len(child_chunks)} children"
    )
    return parent_chunks, child_chunks
