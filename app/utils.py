import hashlib
import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    worker_mode: str
    redis_url: str
    redis_queue_name: str
    polling_job_file: str
    polling_interval_seconds: int
    max_retries: int
    files_base_path: str | None
    java_api_base_url: str
    java_api_timeout_seconds: int
    java_api_token: str | None
    supabase_url: str | None
    supabase_api_key: str | None
    supabase_storage_bucket: str | None
    supabase_storage_timeout_seconds: int
    database_url: str
    db_connect_timeout_seconds: int
    embedding_model_name: str
    embedding_batch_size: int
    chunk_max_tokens: int
    tesseract_cmd: str | None
    log_level: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        worker_mode=os.getenv("WORKER_MODE", "redis").strip().lower(),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        redis_queue_name=os.getenv("REDIS_QUEUE_NAME", "document_jobs"),
        polling_job_file=os.getenv("POLLING_JOB_FILE", "jobs.jsonl"),
        polling_interval_seconds=int(os.getenv("POLLING_INTERVAL_SECONDS", "5")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        files_base_path=os.getenv("FILES_BASE_PATH") or None,
        java_api_base_url=os.getenv("JAVA_API_BASE_URL", "http://localhost:8080").rstrip("/"),
        java_api_timeout_seconds=int(os.getenv("JAVA_API_TIMEOUT_SECONDS", "30")),
        java_api_token=os.getenv("JAVA_API_TOKEN") or None,
        supabase_url=(os.getenv("SUPABASE_URL") or "").rstrip("/") or None,
        supabase_api_key=os.getenv("SUPABASE_API_KEY") or None,
        supabase_storage_bucket=os.getenv("SUPABASE_STORAGE_BUCKET") or None,
        supabase_storage_timeout_seconds=int(os.getenv("SUPABASE_STORAGE_TIMEOUT_SECONDS", "60")),
        database_url=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"),
        db_connect_timeout_seconds=int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "10")),
        embedding_model_name=os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2"),
        embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
        chunk_max_tokens=int(os.getenv("CHUNK_MAX_TOKENS", "500")),
        tesseract_cmd=os.getenv("TESSERACT_CMD") or None,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


def setup_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


logger = logging.getLogger("document_worker")


def compute_text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def resolve_file_path(file_path: str, files_base_path: str | None) -> Path:
    path = Path(file_path)
    if path.is_absolute() or not files_base_path:
        return path
    return Path(files_base_path) / path


def read_json_line(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()

    if not lines:
        return None

    first = lines[0]
    remaining = lines[1:]

    with path.open("w", encoding="utf-8") as handle:
        handle.writelines(remaining)

    return json.loads(first)
