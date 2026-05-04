import mimetypes
from pathlib import Path

import pandas as pd
import pdfplumber
import pytesseract
from docx import Document
from PIL import Image

from app.chunker import TextSegment


class UnsupportedFileTypeError(ValueError):
    pass


class DocumentProcessor:
    def __init__(self, tesseract_cmd: str | None = None) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def extract_segments(self, file_path: Path) -> list[TextSegment]:
        file_type = self._detect_file_type(file_path)
        if file_type == "pdf":
            return self._extract_pdf(file_path)
        if file_type == "image":
            return self._extract_image(file_path)
        if file_type == "excel":
            return self._extract_excel(file_path)
        if file_type == "word":
            return self._extract_word(file_path)
        raise UnsupportedFileTypeError(f"Unsupported file type for {file_path}")

    def extract_text(self, file_path: Path) -> str:
        segments = self.extract_segments(file_path)
        return "\n\n".join(segment.text for segment in segments if segment.text.strip())

    def _detect_file_type(self, file_path: Path) -> str:
        content_type, _ = mimetypes.guess_type(file_path.name)
        suffix = file_path.suffix.lower()

        if suffix == ".pdf" or content_type == "application/pdf":
            return "pdf"
        if suffix in {".png", ".jpg", ".jpeg"} or (content_type and content_type.startswith("image/")):
            return "image"
        if suffix in {".xls", ".xlsx", ".xlsm"}:
            return "excel"
        if suffix in {".doc", ".docx"}:
            return "word"
        raise UnsupportedFileTypeError(f"Unsupported file extension: {suffix}")

    def _extract_pdf(self, file_path: Path) -> list[TextSegment]:
        segments: list[TextSegment] = []
        with pdfplumber.open(file_path) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                # Keep page boundaries so chunk metadata can preserve page_number.
                text = page.extract_text() or ""
                paragraphs = [block.strip() for block in text.split("\n\n") if block.strip()]
                if not paragraphs and text.strip():
                    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
                segments.extend(TextSegment(text=paragraph, page_number=page_index) for paragraph in paragraphs)
        return segments

    def _extract_image(self, file_path: Path) -> list[TextSegment]:
        with Image.open(file_path) as image:
            text = pytesseract.image_to_string(image)
        return [TextSegment(text=text.strip(), page_number=1)] if text.strip() else []

    def _extract_excel(self, file_path: Path) -> list[TextSegment]:
        sheets = pd.read_excel(file_path, sheet_name=None)
        segments: list[TextSegment] = []
        for sheet_name, data_frame in sheets.items():
            if data_frame.empty:
                continue
            # CSV preserves table semantics well enough for embedding in the MVP pipeline.
            csv_text = data_frame.fillna("").to_csv(index=False)
            segments.append(TextSegment(text=f"Sheet: {sheet_name}\n{csv_text}", page_number=None))
        return segments

    def _extract_word(self, file_path: Path) -> list[TextSegment]:
        if file_path.suffix.lower() == ".doc":
            raise UnsupportedFileTypeError("Legacy .doc files are not supported. Convert to .docx first.")

        document = Document(file_path)
        return [
            TextSegment(text=paragraph.text.strip(), page_number=None)
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]
