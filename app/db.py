from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from psycopg2 import pool
from psycopg2.extras import execute_values

try:
    from app.chunker import DocumentChunk
except ModuleNotFoundError:
    from chunker import DocumentChunk


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: int
    chunk_index: int
    page_number: int | None
    chunk_text: str
    similarity: float
    arquivo_nome: str | None = None
    arquivo_path: str | None = None


@dataclass(frozen=True)
class DocumentSearchResult:
    document_id: int
    arquivo_nome: str | None
    arquivo_path: str | None
    max_similarity: float
    avg_similarity: float
    chunk_count: int


class DatabaseClient:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 10) -> None:
        normalized_dsn = self._normalize_dsn(dsn, connect_timeout_seconds)
        self.connection_pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=4,
            dsn=normalized_dsn,
        )

    @staticmethod
    def _normalize_dsn(dsn: str, connect_timeout_seconds: int) -> str:
        parsed = urlsplit(dsn)
        if parsed.scheme not in {"postgresql", "postgres"}:
            return dsn

        params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "pgbouncer"]

        params = [(key, value) for key, value in params if key.lower() != "connect_timeout"]
        params.append(("connect_timeout", str(connect_timeout_seconds)))

        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment))

    @contextmanager
    def connection(self) -> Iterator:
        connection = self.connection_pool.getconn()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self.connection_pool.putconn(connection)

    def replace_document_chunks(
        self,
        document_id: int,
        chunks: list[DocumentChunk],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts must match")

        values = [
            (
                document_id,
                chunk.chunk_index,
                chunk.chunk_text,
                chunk.page_number,
                self._vector_literal(embedding),
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]

        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
                if values:
                    # pgvector accepts textual literals like [0.1, 0.2, ...] when cast to vector.
                    execute_values(
                        cursor,
                        """
                        INSERT INTO document_chunks (
                            document_id,
                            chunk_index,
                            chunk_text,
                            page_number,
                            embedding,
                            created_at,
                            updated_at
                        ) VALUES %s
                        """,
                        values,
                        template="(%s, %s, %s, %s, %s::vector, %s, %s)",
                    )

    def close(self) -> None:
        self.connection_pool.closeall()

    def search_similar_chunks(
        self,
        query_embedding: list[float],
        top_k: int,
        document_id: int | None = None,
    ) -> list[RetrievedChunk]:
        vector = self._vector_literal(query_embedding)
        sql = """
            SELECT
                dc.document_id,
                dc.chunk_index,
                dc.page_number,
                dc.chunk_text,
                (1 - (dc.embedding <=> %s::vector))::float AS similarity,
                a.nome,
                a.path
            FROM document_chunks dc
            LEFT JOIN arquivo a ON dc.document_id = a.id
            WHERE (%s IS NULL OR dc.document_id = %s)
            ORDER BY dc.embedding <=> %s::vector
            LIMIT %s
        """
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (vector, document_id, document_id, vector, top_k))
                rows = cursor.fetchall()

        return [
            RetrievedChunk(
                document_id=row[0],
                chunk_index=row[1],
                page_number=row[2],
                chunk_text=row[3],
                similarity=float(row[4]),
                arquivo_nome=row[5],
                arquivo_path=row[6],
            )
            for row in rows
        ]

    def search_documents_by_description(
        self,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[DocumentSearchResult]:
        vector = self._vector_literal(query_embedding)
        sql = """
            SELECT
                dc.document_id,
                a.nome,
                a.path,
                MAX((1 - (dc.embedding <=> %s::vector))::float) AS max_similarity,
                AVG((1 - (dc.embedding <=> %s::vector))::float) AS avg_similarity,
                COUNT(*) AS chunk_count
            FROM document_chunks dc
            LEFT JOIN arquivo a ON dc.document_id = a.id
            GROUP BY dc.document_id, a.nome, a.path
            ORDER BY max_similarity DESC, avg_similarity DESC
            LIMIT %s
        """
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (vector, vector, limit))
                rows = cursor.fetchall()

        return [
            DocumentSearchResult(
                document_id=row[0],
                arquivo_nome=row[1],
                arquivo_path=row[2],
                max_similarity=float(row[3]),
                avg_similarity=float(row[4]),
                chunk_count=int(row[5]),
            )
            for row in rows
        ]

    @staticmethod
    def _vector_literal(embedding: list[float]) -> str:
        return "[" + ", ".join(f"{value:.8f}" for value in embedding) + "]"
