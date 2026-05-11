from dataclasses import dataclass

from app.db import DatabaseClient, RetrievedChunk, DocumentSearchResult
from app.embedding import EmbeddingService


@dataclass(frozen=True)
class AnswerSource:
    document_id: int
    chunk_index: int
    page_number: int | None
    similarity: float
    chunk_text: str
    arquivo_nome: str | None = None
    arquivo_path: str | None = None


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    sources: list[AnswerSource]


class QASearchService:
    def __init__(
        self,
        db_client: DatabaseClient,
        embedding_service: EmbeddingService,
        default_top_k: int = 5,
        max_top_k: int = 10,
    ) -> None:
        self.db_client = db_client
        self.embedding_service = embedding_service
        self.default_top_k = max(1, default_top_k)
        self.max_top_k = max(1, max_top_k)

    def ask(self, question: str, document_id: int | None = None, top_k: int | None = None) -> AnswerResult:
        clean_question = (question or "").strip()
        if not clean_question:
            raise ValueError("Question cannot be empty")

        requested_top_k = top_k if top_k is not None else self.default_top_k
        bounded_top_k = max(1, min(requested_top_k, self.max_top_k))

        query_embedding = self.embedding_service.embed([clean_question])[0]
        retrieved = self.db_client.search_similar_chunks(
            query_embedding=query_embedding,
            top_k=bounded_top_k,
            document_id=document_id,
        )

        if not retrieved:
            return AnswerResult(
                answer="Nao encontrei trechos relevantes para responder com os documentos processados.",
                sources=[],
            )

        sources = [
            AnswerSource(
                document_id=item.document_id,
                chunk_index=item.chunk_index,
                page_number=item.page_number,
                similarity=item.similarity,
                chunk_text=item.chunk_text,
                arquivo_nome=item.arquivo_nome,
                arquivo_path=item.arquivo_path,
            )
            for item in retrieved
        ]

        answer = self._build_extractive_answer(clean_question, retrieved)
        return AnswerResult(answer=answer, sources=sources)

    def search_documents(self, description: str, limit: int = 10) -> list[DocumentSearchResult]:
        clean_description = (description or "").strip()
        if not clean_description:
            raise ValueError("Description cannot be empty")

        query_embedding = self.embedding_service.embed([clean_description])[0]
        results = self.db_client.search_documents_by_description(
            query_embedding=query_embedding,
            limit=limit,
        )
        return results

    @staticmethod
    def _build_extractive_answer(question: str, chunks: list[RetrievedChunk]) -> str:
        top_chunks = chunks[:3]
        parts: list[str] = ["Resposta baseada nos trechos mais relevantes:"]
        for index, chunk in enumerate(top_chunks, start=1):
            page_suffix = f" (pagina {chunk.page_number})" if chunk.page_number is not None else ""
            parts.append(f"{index}. [doc {chunk.document_id}, chunk {chunk.chunk_index}{page_suffix}] {chunk.chunk_text}")

        parts.append(f"Pergunta original: {question}")
        return "\n".join(parts)
