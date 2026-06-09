"""Abstract chunking strategy interface."""

from abc import ABC, abstractmethod
from typing import Any


class Chunker(ABC):
    """Pluggable document chunking strategy."""

    @abstractmethod
    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Split text into chunks.
        
        Each chunk dict should have:
          - title: str
          - content: str
          - source: str | None
          - tags: list[str]
        """
        ...
