import requests


class JavaApiClient:
    def __init__(self, base_url: str, timeout_seconds: int, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    def update_document_status(self, document_id: int, status: str, error_message: str | None = None) -> None:
        payload = {"status": status}
        if error_message:
            payload["error_message"] = error_message[:1000]
        response = self.session.patch(
            f"{self.base_url}/documents/{document_id}/status",
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
