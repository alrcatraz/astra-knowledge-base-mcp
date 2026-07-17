"""Markdown heading-anchored chunking strategy.

Splits text at Markdown heading boundaries (#, ##, ###, etc.),
preserving heading hierarchy in metadata for context reconstruction.
"""

import re
from typing import Any

from .base import Chunker


class HeadingAnchorChunker(Chunker):
    """Split text on Markdown heading boundaries.

    Each heading level (# through ######) starts a new chunk.
    Heading text is included in the chunk content; heading level
    and full heading path are stored in metadata.
    """

    def __init__(
        self,
        min_chunk_chars: int = 100,
        max_chunk_chars: int = 4096,
        merge_under_min: bool = False,
    ):
        self.min_chunk_chars = min_chunk_chars
        self.max_chunk_chars = max_chunk_chars
        self.merge_under_min = merge_under_min

    def chunk(self, text: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        metadata = metadata or {}
        source = metadata.get("source")
        tags = metadata.get("tags", [])
        doc_title = metadata.get("title", "")

        sections = self._split_by_headings(text)
        chunks = []
        heading_stack: list[str] = []

        for section in sections:
            hdr = section["heading"]
            content = section["content"].strip()
            if not content and not hdr:
                continue

            if hdr:
                level = section["level"]
                while heading_stack and len(heading_stack) >= level:
                    heading_stack.pop()
                heading_stack.append(hdr)

            chunk_title = doc_title
            if heading_stack:
                chunk_title = " > ".join(heading_stack)

            chunks.append({
                "title": chunk_title,
                "content": (hdr + "\n\n" + content) if hdr else content,
                "source": source,
                "tags": tags,
                "metadata": {
                    "heading_level": section["level"] if hdr else 0,
                    "heading_path": list(heading_stack),
                    "section_index": section["index"],
                    "chunker": "heading-anchor",
                },
            })

        if self.merge_under_min and len(chunks) > 1:
            chunks = self._merge_small_chunks(chunks)

        chunks = self._split_oversized(chunks, self.max_chunk_chars)

        return chunks

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    @classmethod
    def _split_by_headings(cls, text: str) -> list[dict]:
        matches = list(cls._HEADING_RE.finditer(text))
        sections = []
        prev_end = 0

        for i, m in enumerate(matches):
            preamble = text[prev_end:m.start()].strip()
            if preamble:
                sections.append({
                    "heading": None, "level": 0,
                    "content": preamble, "index": i,
                })

            level = len(m.group(1))
            heading_text = m.group(2).strip()
            start = m.end()
            next_match = matches[i + 1] if i + 1 < len(matches) else None
            end = next_match.start() if next_match else len(text)
            content = text[start:end].strip()

            sections.append({
                "heading": heading_text, "level": level,
                "content": content, "index": i,
            })
            prev_end = end

        trailing = text[prev_end:].strip()
        if trailing:
            sections.append({
                "heading": None, "level": 0,
                "content": trailing, "index": len(matches),
            })

        return sections or [{"heading": None, "level": 0, "content": text.strip(), "index": 0}]
    @staticmethod
    def _merge_small_chunks(chunks: list[dict]) -> list[dict]:
        """Merge consecutive small chunks under a shared parent heading."""
        if len(chunks) <= 1:
            return chunks

        merged = [chunks[0]]
        for ch in chunks[1:]:
            last = merged[-1]
            last_lvl = last["metadata"].get("heading_level", 0)
            curr_lvl = ch["metadata"].get("heading_level", 0)

            # Merge if: (a) both are under small threshold, AND
            # (b) current is a child-level heading (deeper), not a sibling/top-level
            should_merge = (
                len(last["content"]) < 300
                and len(ch["content"]) < 300
                and curr_lvl > last_lvl  # child heading only
            )
            if should_merge:
                last["content"] += "\n\n" + ch["content"]
                # Keep parent heading level
                last["metadata"]["heading_level"] = last_lvl
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
