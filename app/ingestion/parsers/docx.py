from pathlib import Path
from zipfile import ZipFile
from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table
from app.ingestion.parsers.text import Block


def parse(path: Path, title: str, warnings: list[str]):
    with ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError('DOCX expanded size exceeds 100 MB')
    document = Document(path)
    headings = {}
    for element in document.element.body:
        if element.tag.endswith('}p'):
            paragraph = Paragraph(element, document)
            style = paragraph.style.name if paragraph.style else ''
            text = paragraph.text.strip()
            if style.startswith('Heading ') and style.split()[-1].isdigit():
                level = int(style.split()[-1])
                headings = {key: value for key, value in headings.items() if key < level}
                headings[level] = text[:256]
            elif text:
                yield Block(text, title, (' / '.join(headings.values()) or 'Introduction')[:1024])
        elif element.tag.endswith('}tbl'):
            table = Table(element, document)
            text = '\n'.join(' | '.join(cell.text for cell in row.cells) for row in table.rows)
            if text.strip():
                yield Block(text, title, (' / '.join(headings.values()) or 'Tables')[:1024])
    warnings.append('DOCX citations use sections; rendered page numbers are unavailable')
