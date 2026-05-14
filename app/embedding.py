import logging

import torch
from sentence_transformers import SentenceTransformer


class EmbeddingService:
    def __init__(self, model_name: str, batch_size: int = 16, device: str = "auto") -> None:
        self.batch_size = batch_size
        self.device = self._resolve_device(device)
        self.model = SentenceTransformer(model_name, device=self.device)

    @staticmethod
    def _resolve_device(requested_device: str) -> str:
        normalized = (requested_device or "auto").strip().lower()

        if normalized in {"", "auto"}:
            return "cuda" if torch.cuda.is_available() else "cpu"

        if normalized == "cuda":
            if torch.cuda.is_available():
                return "cuda"
            logging.getLogger("document_worker").warning(
                "cuda_requested_but_unavailable_falling_back_to_cpu"
            )
            return "cpu"

        if normalized.startswith("cuda:"):
            if torch.cuda.is_available():
                return normalized
            logging.getLogger("document_worker").warning(
                "cuda_device_requested_but_unavailable_falling_back_to_cpu"
            )
            return "cpu"

        return "cpu"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        return vectors.tolist()
