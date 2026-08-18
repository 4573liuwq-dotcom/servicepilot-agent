import hashlib
import re
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from insightforge.domain import Evidence, SourceType


class KnowledgeBase:
    """Small, dependency-free persistent retrieval store for learning and demos.

    Production migration point: keep this interface and replace the implementation
    with pgvector, Elasticsearch or a managed vector database.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL
                )"""
            )
            connection.commit()

    @staticmethod
    def _chunks(text: str, chunk_size: int = 900, overlap: int = 120) -> Iterable[str]:
        clean = re.sub(r"\n{3,}", "\n\n", text.strip())
        start = 0
        while start < len(clean):
            end = min(len(clean), start + chunk_size)
            if end < len(clean):
                boundary = max(clean.rfind("\n", start, end), clean.rfind("。", start, end))
                if boundary > start + chunk_size // 2:
                    end = boundary + 1
            yield clean[start:end]
            if end == len(clean):
                break
            start = max(start + 1, end - overlap)

    def ingest_text(self, text: str, source: str, title: str | None = None) -> int:
        title = title or Path(source).stem
        rows = []
        for index, chunk in enumerate(self._chunks(text)):
            digest = hashlib.sha256(f"{source}:{index}:{chunk}".encode()).hexdigest()[:16]
            rows.append((digest, source, title, chunk))
        with closing(self._connect()) as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO chunks(id, source, title, content) VALUES (?, ?, ?, ?)",
                rows,
            )
            connection.commit()
        return len(rows)

    @staticmethod
    def _query_tokens(query: str) -> set[str]:
        """Tokenize English words and Chinese character bigrams without heavy NLP deps."""
        tokens = set(re.findall(r"[a-zA-Z0-9_]{2,}", query.lower()))
        for sequence in re.findall(r"[\u4e00-\u9fff]+", query):
            if len(sequence) <= 4:
                tokens.add(sequence)
            tokens.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
        return tokens

    def search(self, query: str, limit: int = 5) -> list[Evidence]:
        tokens = self._query_tokens(query)
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM chunks").fetchall()
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            haystack = f"{row['title']} {row['content']}".lower()
            hits = sum(1 for token in tokens if token in haystack)
            if hits:
                score = min(1.0, hits / max(3, len(tokens)) + 0.35)
                ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            Evidence(
                id=f"KB-{row['id'][:8]}",
                title=row["title"],
                content=row["content"],
                source_type=SourceType.KNOWLEDGE_BASE,
                score=score,
            )
            for score, row in ranked[:limit]
        ]

    def count(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
