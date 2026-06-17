"""SQLite FTS5 full-text search engine."""

import json
import sqlite3
from .engine import SearchEngine
from db import get_connection


class FTSEngine(SearchEngine):
    """Search engine using SQLite FTS5 full-text search."""

    def search(self, query, kb_names=None, limit=10):
        """Full-text search across knowledge bases using FTS5."""
        from kb_manager import get_enabled_kb_names

        targets = kb_names or get_enabled_kb_names()
        if not targets or not query.strip():
            return []

        # Build FTS5 query: prefix matching for each word
        fts_query = _build_fts5_query(query)
        if not fts_query:
            return []

        placeholders = ",".join("?" for _ in targets)
        sql = f"""\
            SELECT c.id, c.kb_name, c.title, c.content, c.source, c.tags,
                   rank AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
              AND c.kb_name IN ({placeholders})
            ORDER BY rank
            LIMIT ?
        """

        results = []
        with get_connection() as conn:
            cur = conn.execute(sql, [fts_query, *targets, limit])
            for row in cur.fetchall():
                tags = _parse_tags(row["tags"])
                results.append({
                    "kb": row["kb_name"],
                    "title": row["title"],
                    "content": row["content"],
                    "score": _fts_rank_to_score(row["score"]),
                    "source": row["source"],
                    "tags": tags,
                })

        return results


def _build_fts5_query(query: str) -> str:
    """Convert natural language query to FTS5 query syntax.
    
    FTS5 supports:
      - word: exact match
      - word*: prefix match
      - word1 AND word2: both required
      - "phrase": exact phrase
    """
    tokens = []
    for word in query.strip().lower().split():
        word = word.strip("'\"")
        if len(word) > 1:
            tokens.append(f"{word}*")
        elif word:
            tokens.append(word)

    if not tokens:
        return ""

    return " AND ".join(tokens)


def _fts_rank_to_score(rank: float) -> float:
    """Convert FTS5 rank (negative = better match) to a 0-1 score.
    
    FTS5 rank is typically negative for matches. We invert and
    normalize so higher = better, matching the original API.
    """
    return round(-rank, 4) if rank < 0 else round(1.0 / (1.0 + rank), 4)


def _parse_tags(tags_json: str) -> list[str]:
    """Parse tags from JSON string stored in SQLite."""
    if not tags_json:
        return []
    try:
        return json.loads(tags_json) if isinstance(tags_json, str) else list(tags_json)
    except (json.JSONDecodeError, TypeError):
        return []
