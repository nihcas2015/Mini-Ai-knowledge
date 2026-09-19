import logging
import tempfile
import os
from unstructured.partition.pdf import partition_pdf
from unstructured.documents.elements import Table

logger = logging.getLogger(__name__)


def _html_table_to_markdown(html: str) -> str:
    """Convert a simple HTML table to Markdown table syntax."""
    import re
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    md_rows = []
    for i, row in enumerate(rows):
        cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)
        cells = [c.strip().replace('\n', ' ') for c in cells]
        md_rows.append('| ' + ' | '.join(cells) + ' |')
        if i == 0:
            md_rows.append('| ' + ' | '.join(['---'] * len(cells)) + ' |')
    return '\n'.join(md_rows) if md_rows else html

def extract_pdf(file_bytes: bytes, filename: str) -> list[dict]:
    """
    Extracts text, tables, and structural elements from a PDF file.
    
    Args:
        file_bytes: The bytes of the PDF file.
        filename: The original filename.
        
    Returns:
        List of dictionaries containing extracted elements with keys:
        type, text, page_number, metadata.
    """
    logger.info(f"Extracting PDF: {filename}")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmpfile:
        tmpfile.write(file_bytes)
        tmp_path = tmpfile.name
        
    try:
        elements = partition_pdf(filename=tmp_path, strategy="hi_res")
        
        extracted_data = []
        total_text_length = 0
        
        for element in elements:
            element_type = type(element).__name__
            text = element.text
            page_number = element.metadata.page_number if hasattr(element.metadata, 'page_number') else None
            
            if isinstance(element, Table):
                # Convert table to Markdown format (§4 step 4)
                # If text_as_html is available, try to convert; otherwise keep text as-is
                if hasattr(element.metadata, "text_as_html") and element.metadata.text_as_html:
                    try:
                        text = _html_table_to_markdown(element.metadata.text_as_html)
                    except Exception:
                        pass  # Fall back to plain text representation
            
            metadata = element.metadata.to_dict() if hasattr(element.metadata, "to_dict") else {}
            
            extracted_data.append({
                "type": element_type,
                "text": text,
                "page_number": page_number,
                "metadata": metadata
            })
            total_text_length += len(text)
            
        if total_text_length < 200:
            logger.warning(f"Extracted only {total_text_length} characters from {filename}")
            raise ValueError("No extractable text found — this PDF may be a scanned image.")
            
        return extracted_data
        
    except Exception as e:
        logger.error(f"Error extracting PDF {filename}: {str(e)}")
        raise
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
