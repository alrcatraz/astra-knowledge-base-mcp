"""Semantic chunking — uses embedding cosine similarity to detect topic boundaries.

两步模式：
  1. 先把所有段落批量嵌入（1 次 API 调用）
  2. 本地计算 cosine similarity，确定分块边界

每段落只嵌入 1 次，没有冗余调用。
"""

import math
from typing import Any, Callable

from .base import Chunker


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SemanticChunker(Chunker):
    """Split text at topic boundaries detected by embedding similarity.

    Uses the 'batch-first' approach: caller pre-embeds all paragraphs in bulk,
    then calls `chunk_with_vectors()` to detect boundaries locally.

    For single-document use, `chunk()` still calls embed_fn per boundary pair
    (slower but self-contained).
    """

    def __init__(
        self,
        embed_fn: Callable[[str], list[float] | None] | None = None,
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
        """Single-document chunking with per-boundary API calls (slower)."""
        metadata = metadata or {}
        source = metadata.get("source")
        tags = metadata.get("tags", [])
        doc_title = metadata.get("title", "")

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            return [self._make_chunk(text, doc_title, source, tags, "semantic")]

        boundaries = self._detect_boundaries(paragraphs)
        return self._build_chunks(paragraphs, boundaries, doc_title, source, tags)

    def chunk_with_vectors(
        self,
        text: str,
        vectors: list[list[float]],
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Chunk using pre-computed paragraph vectors (faster — no API calls).

        Args:
            text: Full document text.
            vectors: One embedding vector per paragraph (len = num paragraphs).
            metadata: Standard chunk metadata.
        """
        metadata = metadata or {}
        source = metadata.get("source")
        tags = metadata.get("tags", [])
        doc_title = metadata.get("title", "")

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            return [self._make_chunk(text, doc_title, source, tags, "semantic")]

        boundaries = self._detect_boundaries_with_vectors(paragraphs, vectors)
        return self._build_chunks(paragraphs, boundaries, doc_title, source, tags)

    def _detect_boundaries(self, paragraphs: list[str]) -> list[int]:
        """Per-boundary embedding calls (original approach)."""
        if len(paragraphs) < 2 or self.embed_fn is None:
            return []
        boundaries = []
        for i in range(1, len(paragraphs)):
            left_text = "\n".join(paragraphs[max(0, i - self.window_size):i])
            right_text = "\n".join(paragraphs[i:min(len(paragraphs), i + self.window_size)])
            if not left_text.strip() or not right_text.strip():
                continue
            left_vec = self.embed_fn(left_text)
            right_vec = self.embed_fn(right_text)
            if left_vec is None or right_vec is None:
                continue
            if _cosine_sim(left_vec, right_vec) < self.threshold:
                boundaries.append(i)
        return boundaries

    def _detect_boundaries_with_vectors(
        self, paragraphs: list[str], vectors: list[list[float]]
    ) -> list[int]:
        """Local boundary detection using pre-computed vectors."""
        if len(paragraphs) < 2 or len(vectors) < len(paragraphs):
            return []
        boundaries = []
        for i in range(1, len(paragraphs)):
            # Mean vector of left window
            left_vecs = vectors[max(0, i - self.window_size):i]
            right_vecs = vectors[i:min(len(vectors), i + self.window_size)]
            if not left_vecs or not right_vecs:
                continue
            left_mean = [sum(v[j] for v in left_vecs) / len(left_vecs)
                         for j in range(len(left_vecs[0]))]
            right_mean = [sum(v[j] for v in right_vecs) / len(right_vecs)
                          for j in range(len(right_vecs[0]))]
            sim = _cosine_sim(left_mean, right_mean)
            if sim < self.threshold:
                boundaries.append(i)
        return boundaries

    def _build_chunks(self, paragraphs, boundaries, title, source, tags):
        chunks = []
        start = 0
        for b in boundaries + [len(paragraphs)]:
            group = paragraphs[start:b]
            content = "\n\n".join(group)
            if content.strip():
                chunks.append(self._make_chunk(
                    content, title, source, tags, "semantic",
                    {"para_start": start, "para_end": b},
                ))
            start = b
        if len(chunks) > 1:
            chunks = self._merge_small(chunks)
        chunks = self._split_oversized(chunks)
        return chunks

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
        if len(chunks) <= 1:
            return chunks
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
