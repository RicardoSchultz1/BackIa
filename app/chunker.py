from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TextSegment:
    text: str
    page_number: int | None = None


@dataclass(frozen=True)
class DocumentChunk:
    chunk_index: int
    chunk_text: str
    page_number: int | None = None


class TextChunker:
    def __init__(self, max_tokens: int = 500) -> None:
        self.max_tokens = max_tokens

    def chunk(self, segments: Iterable[TextSegment]) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        current_tokens: list[str] = []
        current_page: int | None = None

        def flush() -> None:
            nonlocal current_tokens, current_page
            if not current_tokens:
                return
            chunks.append(
                DocumentChunk(
                    chunk_index=len(chunks),
                    chunk_text=" ".join(current_tokens).strip(),
                    page_number=current_page,
                )
            )
            current_tokens = []
            current_page = None

        for segment in segments:
            text = " ".join(segment.text.split())
            if not text:
                continue

            words = text.split()
            start = 0
            while start < len(words):
                if current_tokens and segment.page_number != current_page:
                    flush()

                remaining_capacity = self.max_tokens - len(current_tokens)
                if remaining_capacity <= 0:
                    flush()
                    remaining_capacity = self.max_tokens

                window = words[start : start + remaining_capacity]
                if not current_tokens:
                    current_page = segment.page_number
                current_tokens.extend(window)
                start += len(window)

                if len(current_tokens) >= self.max_tokens:
                    flush()

        flush()
        return chunks
