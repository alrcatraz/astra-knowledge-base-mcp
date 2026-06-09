"""Plain text ingestion — accepts raw text or file paths."""

from .base import Ingestor
from chunking.recursive import RecursiveChunker


class TextIngestor(Ingestor):
    """Ingest plain text (direct string or file path)."""

    def __init__(self, chunker=None):
        self.chunker = chunker or RecursiveChunker()

    def ingest(self, content, **kwargs):
        """Ingest text.

        Args:
            content: Text content to ingest, or a file:///path URL.
            title: Optional title.
            source: Optional source description (URL, file path, etc.).
            tags: Optional list of tags.
        """
        title = kwargs.get("title", "")
        source = kwargs.get("source")
        tags = kwargs.get("tags", [])

        if content.startswith("file://"):
            path = content[7:]
            with open(path, encoding="utf-8") as f:
                text = f.read()
            source = source or path
        else:
            text = content

        chunks = self.chunker.chunk(text, metadata={
            "title": title,
            "source": source,
            "tags": tags,
        })
        return chunks
