"""File ingestion via MarkItDown — converts PDF, DOCX, PPTX, HTML, images to Markdown.

Requires: pip install markitdown
"""

import os
from pathlib import Path
from typing import Any

from .base import Ingestor
from chunking.recursive import RecursiveChunker
from chunking.registry import get_chunker


class FileImporter(Ingestor):
    """Import files (PDF, DOCX, PPTX, HTML, images) via MarkItDown conversion.

    Accepts file:// URLs or local file paths.
    Converts to Markdown using Microsoft MarkItDown, then chunks.
    """

    def __init__(self, chunker=None):
        self.chunker = chunker or RecursiveChunker()

    def ingest(self, content: str, **kwargs) -> list[dict[str, Any]]:
        """Import a file via MarkItDown.

        Args:
            content: file:///path/to/file or absolute path.

        Returns list of chunk dicts with metadata.
        """
        title = kwargs.get("title", "")
        source = kwargs.get("source")
        tags = kwargs.get("tags", [])
        chunker_name = kwargs.get("chunker")
        chunker_kwargs = kwargs.get("chunker_kwargs", {})

        # Resolve file path
        file_path = content
        if file_path.startswith("file://"):
            file_path = file_path[7:]

        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        filename = path.name
        source = source or str(path)

        # Convert via MarkItDown
        try:
            from markitdown import MarkItDown
            converter = MarkItDown()
            result = converter.convert(str(path))
            md_text = result.text_content
        except Exception as e:
            raise RuntimeError(f"MarkItDown conversion failed for {filename}: {e}")

        if not md_text or not md_text.strip():
            raise ValueError(f"MarkItDown produced empty output for {filename}")

        # Auto-detect title if not provided
        doc_title = title or result.title or filename

        # Resolve chunker
        chunker = self.chunker
        if chunker_name:
            chunker = get_chunker(chunker_name, **chunker_kwargs)

        # Add original_filename to metadata for tracking
        file_tags = list(tags)
        ext = path.suffix.lower()
        if ext in (".pdf",):
            file_tags.append("pdf")
        elif ext in (".docx", ".doc"):
            file_tags.append("docx")
        elif ext in (".pptx", ".ppt"):
            file_tags.append("pptx")
        elif ext in (".html", ".htm"):
            file_tags.append("html")
        elif ext in (".md",):
            file_tags.append("markdown")
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            file_tags.append("image")

        metadata = {
            "title": doc_title,
            "source": source,
            "tags": list(set(file_tags)),
            "original_filename": filename,
        }

        return chunker.chunk(md_text, metadata=metadata)
