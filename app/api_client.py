import requests


class JavaApiClient:
    STATUS_MAP = {
        "UPLOADED": 1,
        "PROCESSING": 2,
        "PROCESSED": 3,
        "FAILED": 4,
    }

    def __init__(self, base_url: str, timeout_seconds: int, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    def update_document_status(self, document_id: int, status: str, error_message: str | None = None) -> None:
        status_key = status.strip().upper()
        if status_key not in self.STATUS_MAP:
            raise ValueError(f"Unsupported status value: {status}")

        payload = {"statusId": self.STATUS_MAP[status_key]}
        response = self.session.put(
            f"{self.base_url}/arquivos/{document_id}/status",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

    def complete_document(self, document_id: int, content_hash: str, chunk_count: int) -> None:
        response = self.session.post(
            f"{self.base_url}/documents/{document_id}/complete",
            json={"content_hash": content_hash, "chunk_count": chunk_count},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
