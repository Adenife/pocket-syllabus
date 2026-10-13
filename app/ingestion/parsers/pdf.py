from pathlib import Path
from pypdf import PdfReader
from app.ingestion.parsers.text import Block


def parse(path: Path, title: str, warnings: list[str]):
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError('Password-protected PDFs are not supported; upload an unlocked copy')
    if len(reader.pages) > 10000:
        raise ValueError('PDF exceeds the 10,000-page processing limit')
    for page_number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ''
        if not text.strip():
            warnings.append(f'Page {page_number} has no extractable text; scanned pages need OCR')
        for paragraph in text.split('\n\n'):
            if paragraph.strip():
                yield Block(paragraph.strip(), title, f'Page {page_number}', page=page_number)
