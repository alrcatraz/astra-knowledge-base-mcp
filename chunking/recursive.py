"""Recursive text chunking — splits on paragraphs, then sentences, then fixed size."""

from .base import Chunker


class RecursiveChunker(Chunker):
    """Recursively split text into chunks with overlap."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text, metadata=None):
        metadata = metadata or {}
        source = metadata.get("source")
        tags = metadata.get("tags", [])
        title = metadata.get("title", "")

        chunks = []
        paragraphs = text.split("\n\n")

        current = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) + 2 <= self.chunk_size:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append(self._make_chunk(current, title, source, tags))
                # If the paragraph itself is too long, split by sentence
                if len(para) > self.chunk_size:
                    for sentence in self._split_sentences(para):
                        chunks.append(self._make_chunk(sentence, title, source, tags))
                else:
                    current = para

        if current:
            chunks.append(self._make_chunk(current, title, source, tags))

        # Apply overlap by carrying tail of each chunk as prefix of next
        if self.chunk_overlap > 0 and len(chunks) > 1:
            merged = [chunks[0]]
            for i in range(1, len(chunks)):
                prev_tail = chunks[i - 1]["content"][-self.chunk_overlap:]
                merged.append(self._make_chunk(
                    prev_tail + "\n" + chunks[i]["content"],
                    title,
                    source,
                    tags,
                ))
            chunks = merged

        return chunks

    @staticmethod
    def _make_chunk(content, title, source, tags):
        return {
            "title": title or content[:80].strip(),
            "content": content,
            "source": source,
            "tags": tags,
        }

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Simple sentence splitting on punctuation."""
        import re
        sentences = re.split(r"(?<=[。.!?！？])\s*", text)
        return [s.strip() for s in sentences if s.strip()]
