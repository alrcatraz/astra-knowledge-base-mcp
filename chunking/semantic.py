"""Semantic chunking — uses embedding cosine similarity to detect topic boundaries.

At each candidate split point (paragraph boundary), computes the embedding
of the window before and after. If cosine similarity drops below threshold,
that's a topic boundary.

Reference: embedding-based semantic segmentation
"""

import math
from typing import Any, Callable

from .base import Chunker


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SemanticChunker(Chunker):
    """Split text at topic boundaries detected by embedding similarity.

    At each paragraph boundary, computes the mean embedding of the
    preceding window and the following window. If cosine similarity
    is below `threshold`, a split is placed.

    Requires an embed function: embed_fn(text: str) -> list[float] | None
    """

    def __init__(
        self,
        embed_fn: Callable[[str], list[float] | None],
        window_size: int = 3,
        threshold: float = 0.75,
        max_chunk_chars: int = 4096,
        min_chunk_chars: int = 100,
    ):
        self.embed_fn = embed_fn
        self.window_size = window_size
        self.threshold = threshold
        self.max_chunk_chars = max_chunk_chars
        self.min_chunk_chars = min_chunk_chars

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        metadata = metadata or {}
        source = metadata.get("source")
        tags = metadata.get("tags", [])
        doc_title = metadata.get("title", "")

        # Split into paragraphs first
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            return [self._make_chunk(text, doc_title, source, tags, "semantic")]

        # Detect topic boundaries
        boundaries = self._detect_boundaries(paragraphs)

        # Build chunks from boundary groups
        chunks = []
        start = 0
        for b in boundaries + [len(paragraphs)]:
            group = paragraphs[start:b]
            content = "\n\n".join(group)
            if content.strip():
                chunks.append(self._make_chunk(
                    content, doc_title, source, tags, "semantic",
                    {"para_start": start, "para_end": b},
                ))
            start = b

        # Merge small trailing chunks
        if len(chunks) > 1:
            chunks = self._merge_small(chunks)

        # Enforce max_chunk_chars
        chunks = self._split_oversized(chunks)

        return chunks

    def _detect_boundaries(self, paragraphs: list[str]) -> list[int]:
        """Find paragraph indices that are topic boundaries."""
        if len(paragraphs) < 2:
            return []

        boundaries = []
        half = self.window_size // 2

        for i in range(1, len(paragraphs)):
            # Build left window: paragraphs[max(0,i-window):i]
            left_text = "\n".join(paragraphs[max(0, i - self.window_size):i])
            # Build right window: paragraphs[i:min(len, i+window)]
            right_text = "\n".join(paragraphs[i:min(len(paragraphs), i + self.window_size)])

            if not left_text.strip() or not right_text.strip():
                continue

            left_vec = self.embed_fn(left_text)
            right_vec = self.embed_fn(right_text)

            if left_vec is None or right_vec is None:
                continue

            sim = _cosine_sim(left_vec, right_vec)
            if sim < self.threshold:
                boundaries.append(i)

        return boundaries

    @staticmethod
    def _make_chunk(content, title, source, tags, chunker_name, extra=None):
        chunk = {
            "title": title or content[:80].strip(),
            "content": content,
            "source": source,
            "tags": tags,
            "metadata": {"chunker": chunker_name},
        }
        if extra:
            chunk["metadata"].update(extra)
        return chunk

    @staticmethod
    def _merge_small(chunks: list[dict], min_chars: int = 200) -> list[dict]:
        merged = [chunks[0]]
        for ch in chunks[1:]:
            last = merged[-1]
            if len(last["content"]) < min_chars:
                last["content"] += "\n\n" + ch["content"]
            else:
                merged.append(ch)
        return merged

    @staticmethod
    def _split_oversized(chunks: list[dict], max_chars: int = 4096) -> list[dict]:
        result = []
        for ch in chunks:
            if len(ch["content"]) <= max_chars:
                result.append(ch)
                continue
            paras = ch["content"].split("\n\n")
            buf = ""
            for para in paras:
                if len(buf) + len(para) + 2 <= max_chars:
                    buf = (buf + "\n\n" + para).strip() if buf else para
                else:
                    if buf:
                        result.append({**ch, "content": buf})
                    buf = para
            if buf:
                result.append({**ch, "content": buf})
        return result
