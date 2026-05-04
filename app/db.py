from contextlib import contextmanager
from typing import Iterator

from psycopg2 import pool
from psycopg2.extras import execute_values

from app.chunker import DocumentChunk


class DatabaseClient:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 10) -> None:
        self.connection_pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=4,
            dsn=f"{dsn}?connect_timeout={connect_timeout_seconds}" if "?" not in dsn else f"{dsn}&connect_timeout={connect_timeout_seconds}",
        )

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
                            embedding
                        ) VALUES %s
                        """,
                        values,
                        template="(%s, %s, %s, %s, %s::vector)",
                    )

    def close(self) -> None:
        self.connection_pool.closeall()

    @staticmethod
    def _vector_literal(embedding: list[float]) -> str:
        return "[" + ", ".join(f"{value:.8f}" for value in embedding) + "]"
