"""Abstract ingestion interface."""

from abc import ABC, abstractmethod
from typing import Any


class Ingestor(ABC):
    """Pluggable document import strategy."""

    @abstractmethod
    def ingest(self, content: str, **kwargs) -> list[dict[str, Any]]:
        """Import a document and return chunks ready for storage.
        
        Args:
            content: Text content or file:///path URL to import.
            title: Optional title.
            source: Optional source description.
            tags: Optional list of tags.
        """
        ...
