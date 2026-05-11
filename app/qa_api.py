from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.db import DatabaseClient
from app.embedding import EmbeddingService
from app.qa_service import QASearchService
from app.utils import get_settings


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    document_id: int | None = None
    top_k: int | None = Field(default=None, ge=1)


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]


class SearchRequest(BaseModel):
    description: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchResponse(BaseModel):
    documents: list[dict]


app = FastAPI(title="BackIa Q&A API", version="1.0.0")

_settings = get_settings()
_db_client = DatabaseClient(_settings.database_url, _settings.db_connect_timeout_seconds)
_embedding_service = EmbeddingService(
    model_name=_settings.embedding_model_name,
    batch_size=_settings.embedding_batch_size,
)
_qa_service = QASearchService(
    db_client=_db_client,
    embedding_service=_embedding_service,
    default_top_k=_settings.qa_default_top_k,
    max_top_k=_settings.qa_max_top_k,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    try:
        result = _qa_service.ask(
            question=request.question,
            document_id=request.document_id,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to process question: {exc}") from exc

    sources_with_download = []
    for source in result.sources:
        source_dict = asdict(source)
        if source.arquivo_path:
            source_dict["download_url"] = f"/download/{source.document_id}"
        sources_with_download.append(source_dict)

    return AskResponse(
        answer=result.answer,
        sources=sources_with_download,
    )


@app.get("/download/{document_id}")
def download(document_id: int) -> FileResponse:
    try:
        sql = "SELECT path FROM arquivo WHERE id = %s"
        with _db_client.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (document_id,))
                result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail=f"Arquivo com ID {document_id} nao encontrado")

        file_path_str = result[0]
        if not file_path_str:
            raise HTTPException(status_code=404, detail="Caminho do arquivo nao disponivel")

        file_path = Path(file_path_str)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Arquivo nao encontrado no sistema: {file_path}")

        return FileResponse(
            path=file_path,
            media_type="application/octet-stream",
            filename=file_path.name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao baixar arquivo: {exc}") from exc


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    try:
        results = _qa_service.search_documents(
            description=request.description,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to search documents: {exc}") from exc

    documents = []
    for result in results:
        doc_dict = asdict(result)
        if result.arquivo_path:
            doc_dict["download_url"] = f"/download/{result.document_id}"
        documents.append(doc_dict)

    return SearchResponse(documents=documents)
