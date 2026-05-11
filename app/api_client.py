import requests


class JavaApiClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: int,
        token: str | None = None,
        status_map: dict[str, int] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.status_map = status_map or {
            "UPLOADED": 1,
            "PROCESSING": 2,
            "PROCESSED": 3,
            "FAILED": 4,
        }
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    def update_document_status(self, document_id: int, status: str, error_message: str | None = None) -> None:
        status_key = status.strip().upper()
        if status_key not in self.status_map:
            raise ValueError(f"Unsupported status value: {status}")

        payload = {"statusId": self.status_map[status_key]}
        response = self.session.put(
            f"{self.base_url}/arquivos/{document_id}/status",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
