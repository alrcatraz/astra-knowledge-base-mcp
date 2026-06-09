"""Abstract search engine interface."""

from abc import ABC, abstractmethod
from typing import Any


class SearchEngine(ABC):
    """Pluggable search engine for knowledge base chunks."""

    @abstractmethod
    def search(
        self,
        query: str,
        kb_names: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search across knowledge bases and return ranked results.
        
        Each result dict should have at minimum:
          - kb: str
          - title: str
          - content: str (snippet)
          - score: float
          - source: str | None
          - tags: list[str]
        """
        ...
