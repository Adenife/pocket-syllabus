from pathlib import Path
from app.ingestion.parsers import markdown, text, pdf, docx

PARSERS = {'.md': markdown.parse, '.txt': text.parse, '.pdf': pdf.parse, '.docx': docx.parse}


def parse_document(path: Path, filename: str, warnings: list[str]):
    suffix = Path(filename).suffix.lower()
    if suffix not in PARSERS:
        raise ValueError('Supported formats: .md, .txt, .pdf, .docx')
    yield from PARSERS[suffix](path, Path(filename).stem, warnings)
