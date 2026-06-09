"""PostgreSQL full-text search engine."""

from db import _sanitize, get_connection
from .engine import SearchEngine


class FTSEngine(SearchEngine):
    """Search engine using PostgreSQL to_tsvector / to_tsquery FTS."""

    def search(self, query, kb_names=None, limit=10):
        """Full-text search across enabled knowledge bases."""
        from kb_manager import get_enabled_kb_names

        targets = kb_names or get_enabled_kb_names()
        if not targets:
            return []

        tsquery_str = _build_tsquery(query)
        if not tsquery_str:
            return []

        parts = []
        params = []
        for kb in targets:
            safe = _sanitize(kb)
            parts.append(
                f"""(
                    SELECT {self._rank_expr(safe, tsquery_str)} AS score,
                           {self._headline_expr(safe, tsquery_str)} AS headline,
                           id, title, content, source, tags, %s AS kb
                    FROM kb_{safe}.chunks
                    WHERE search_vec @@ to_tsquery('simple', %s)
                    ORDER BY score DESC
                    LIMIT %s
                )"""
            )
            params.extend([kb, tsquery_str, limit])

        if not parts:
            return []

        if len(parts) > 1:
            sql = " UNION ALL ".join(parts) + " ORDER BY score DESC LIMIT %s"
            params.append(limit)
        else:
            sql = parts[0]

        results = []
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                for row in cur.fetchall():
                    results.append({
                        "kb": row[7],
                        "title": row[3],
                        "content": row[5] or row[4][:500],
                        "score": round(float(row[0]), 4),
                        "source": row[5],
                        "tags": row[6] if isinstance(row[6], list) else [],
                        "headline": row[1],
                    })

        return results

    @staticmethod
    def _rank_expr(schema: str, tsquery: str) -> str:
        return (
            f"ts_rank(kb_{schema}.chunks.search_vec, "
            f"to_tsquery('simple', '{tsquery}'), 32)"
        )

    @staticmethod
    def _headline_expr(schema: str, tsquery: str) -> str:
        return (
            f"ts_headline('simple', kb_{schema}.chunks.content, "
            f"to_tsquery('simple', '{tsquery}'), 'MaxWords=50, MinWords=20')"
        )


def _build_tsquery(query: str) -> str:
    """Build a tsquery string from a natural language query."""
    tokens = []
    for word in query.replace("'", "''").split():
        word = word.strip().lower()
        if len(word) > 1:
            tokens.append(f"{word}:*")
    return " & ".join(tokens) if tokens else "%"
