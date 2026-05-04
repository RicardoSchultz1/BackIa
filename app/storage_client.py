from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

import requests


class SupabaseStorageClient:
    def __init__(self, base_url: str, api_key: str, bucket: str, timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.bucket = bucket
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
            }
        )

    def download_to_temp(self, object_path: str) -> Path:
        normalized_path = object_path.lstrip("/")
        encoded_bucket = quote(self.bucket, safe="")
        encoded_path = "/".join(quote(part, safe="") for part in normalized_path.split("/"))
        url = f"{self.base_url}/storage/v1/object/{encoded_bucket}/{encoded_path}"

        suffix = Path(normalized_path).suffix or ".bin"
        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            with self.session.get(url, timeout=self.timeout_seconds, stream=True) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        temp_file.write(chunk)
            return Path(temp_file.name)
