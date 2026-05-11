import json
import time
from dataclasses import dataclass
from pathlib import Path

import redis
from requests import HTTPError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.api_client import JavaApiClient
from app.chunker import TextChunker
from app.db import DatabaseClient
from app.embedding import EmbeddingService
from app.processor import DocumentProcessor
from app.storage_client import SupabaseStorageClient
from app.utils import Settings, logger, read_json_line, resolve_file_path


@dataclass(frozen=True)
class JobPayload:
    document_id: int
    file_path: str


class DocumentWorker:
    def __init__(
        self,
        settings: Settings,
        db_client: DatabaseClient,
        api_client: JavaApiClient,
        processor: DocumentProcessor,
        chunker: TextChunker,
        embedding_service: EmbeddingService,
        storage_client: SupabaseStorageClient | None = None,
    ) -> None:
        self.settings = settings
        self.db_client = db_client
        self.api_client = api_client
        self.processor = processor
        self.chunker = chunker
        self.embedding_service = embedding_service
        self.storage_client = storage_client
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True) if settings.worker_mode == "redis" else None
        self.polling_path = Path(settings.polling_job_file)
        self._redis_unavailable_logged = False

    def run_forever(self) -> None:
        logger.info("worker_started mode=%s queue=%s", self.settings.worker_mode, self.settings.redis_queue_name)
        while True:
            job = self._get_next_job()
            if not job:
                continue
            self._process_with_retries(job)

    def _get_next_job(self) -> JobPayload | None:
        if self.settings.worker_mode == "redis":
            try:
                result = self.redis_client.brpop(self.settings.redis_queue_name, timeout=5) if self.redis_client else None
            except (RedisConnectionError, RedisTimeoutError):
                if not self._redis_unavailable_logged:
                    logger.warning(
                        "redis_unavailable redis_url=%s queue=%s fallback=polling",
                        self.settings.redis_url,
                        self.settings.redis_queue_name,
                    )
                    self._redis_unavailable_logged = True

                payload = read_json_line(self.polling_path)
                if payload:
                    return self._parse_job(payload)

                time.sleep(self.settings.polling_interval_seconds)
                return None

            if self._redis_unavailable_logged:
                logger.info("redis_recovered redis_url=%s", self.settings.redis_url)
                self._redis_unavailable_logged = False

            if not result:
                # Optional local fallback for ad-hoc jobs while keeping Redis as primary queue.
                payload = read_json_line(self.polling_path)
                if payload:
                    return self._parse_job(payload)
                return None

            _, payload = result
            return self._parse_job(payload)

        payload = read_json_line(self.polling_path)
        if not payload:
            time.sleep(self.settings.polling_interval_seconds)
            return None
        return self._parse_job(payload)

    def _parse_job(self, payload: str | dict) -> JobPayload:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return JobPayload(document_id=int(data["document_id"]), file_path=str(data["file_path"]))

    def _process_with_retries(self, job: JobPayload) -> None:
        # Retries stay within the worker so the Java side can keep its queue contract simple.
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                self._process(job)
                return
            except HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                    logger.error(
                        "job_processing_failed_non_retriable document_id=%s status_code=%s response=%s",
                        job.document_id,
                        status_code,
                        (exc.response.text or "")[:500] if exc.response is not None else "",
                    )
                    self._mark_failed(job.document_id, f"HTTP {status_code}: client error from Java API")
                    return

                logger.exception(
                    "job_processing_failed document_id=%s attempt=%s/%s",
                    job.document_id,
                    attempt,
                    self.settings.max_retries,
                )
                if attempt >= self.settings.max_retries:
                    self._mark_failed(job.document_id, str(exc))
                    return
                time.sleep(min(attempt * 2, 10))
            except Exception as exc:
                logger.exception(
                    "job_processing_failed document_id=%s attempt=%s/%s",
                    job.document_id,
                    attempt,
                    self.settings.max_retries,
                )
                if attempt >= self.settings.max_retries:
                    self._mark_failed(job.document_id, str(exc))
                    return
                time.sleep(min(attempt * 2, 10))

    def _process(self, job: JobPayload) -> None:
        file_path = resolve_file_path(job.file_path, self.settings.files_base_path)
        temp_file_path: Path | None = None
        if not file_path.exists():
            if not self.storage_client:
                raise FileNotFoundError(f"File not found locally and storage client is disabled: {file_path}")
            logger.info("document_download_started document_id=%s object_path=%s", job.document_id, job.file_path)
            temp_file_path = self.storage_client.download_to_temp(job.file_path)
            file_path = temp_file_path
            logger.info("document_download_completed document_id=%s temp_file=%s", job.document_id, temp_file_path)

        try:
            self.api_client.update_document_status(job.document_id, "PROCESSING")
            logger.info("document_processing_started document_id=%s file_path=%s", job.document_id, file_path)

            # Extract first, then derive the content hash from the normalized text that will be embedded.
            segments = self.processor.extract_segments(file_path)
            extracted_text = "\n\n".join(segment.text for segment in segments if segment.text.strip())
            if not extracted_text.strip():
                raise ValueError("No text could be extracted from the document")

            chunks = self.chunker.chunk(segments)
            embeddings = self.embedding_service.embed([chunk.chunk_text for chunk in chunks])

            # Replace previous chunks atomically so reprocessing does not create duplicates.
            self.db_client.replace_document_chunks(job.document_id, chunks, embeddings)
            self.api_client.update_document_status(job.document_id, "PROCESSED")
            logger.info(
                "document_processing_completed document_id=%s chunks=%s",
                job.document_id,
                len(chunks),
            )
        finally:
            if temp_file_path and temp_file_path.exists():
                temp_file_path.unlink(missing_ok=True)

    def _mark_failed(self, document_id: int, error_message: str) -> None:
        try:
            self.api_client.update_document_status(document_id, "FAILED", error_message=error_message)
        except Exception:
            logger.exception("document_status_update_failed document_id=%s", document_id)
