from pathlib import Path
from markdown_it import MarkdownIt
from app.ingestion.parsers.text import Block


def parse(path: Path, title: str, warnings: list[str]):
    tokens = MarkdownIt('commonmark').parse(path.read_text(encoding='utf-8'))
    headings = {}
    for position, token in enumerate(tokens):
        if token.type == 'heading_open':
            depth = int(token.tag[1:])
            name = tokens[position + 1].content[:256]
            if depth == 1:
                title = name
            headings = {key: value for key, value in headings.items() if key < depth}
            headings[depth] = name
        elif token.type in {'inline', 'fence', 'code_block'}:
            if token.type == 'inline' and position and tokens[position - 1].type == 'heading_open':
                continue
            if token.content.strip():
                yield Block(token.content, title, (' / '.join(headings.values()) or 'Introduction')[:1024],
                            line=token.map[0] + 1 if token.map else None)
