import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow running this file directly (python app/main.py) during local debugging.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api_client import JavaApiClient
from app.chunker import TextChunker
from app.db import DatabaseClient
from app.embedding import EmbeddingService
from app.processor import DocumentProcessor
from app.storage_client import SupabaseStorageClient
from app.utils import get_settings, logger, setup_logging
from app.worker import DocumentWorker


def main() -> None:
    setup_logging()
    settings = get_settings()

    # Initialize long-lived service clients once per worker process.
    db_client = DatabaseClient(settings.database_url, settings.db_connect_timeout_seconds)
    api_client = JavaApiClient(
        base_url=settings.java_api_base_url,
        timeout_seconds=settings.java_api_timeout_seconds,
        token=settings.java_api_token,
    )
    processor = DocumentProcessor(tesseract_cmd=settings.tesseract_cmd)
    chunker = TextChunker(max_tokens=settings.chunk_max_tokens)
    embedding_service = EmbeddingService(
        model_name=settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
    )
    storage_client = None
    if settings.supabase_url and settings.supabase_api_key and settings.supabase_storage_bucket:
        storage_client = SupabaseStorageClient(
            base_url=settings.supabase_url,
            api_key=settings.supabase_api_key,
            bucket=settings.supabase_storage_bucket,
            timeout_seconds=settings.supabase_storage_timeout_seconds,
        )

    worker = DocumentWorker(
        settings=settings,
        db_client=db_client,
        api_client=api_client,
        processor=processor,
        chunker=chunker,
        embedding_service=embedding_service,
        storage_client=storage_client,
    )

    try:
        # Run as a foreground process so orchestration can manage restarts.
        worker.run_forever()
    except KeyboardInterrupt:
        logger.info("worker_stopped")
    finally:
        db_client.close()


if __name__ == "__main__":
    main()
