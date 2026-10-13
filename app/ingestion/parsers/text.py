from dataclasses import dataclass
from pathlib import Path

@dataclass
class Block:
    text: str
    title: str
    section: str = 'Introduction'
    page: int | None = None
    line: int | None = None


def parse(path: Path, title: str, warnings: list[str]):
    buffer, start = [], 1
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                if not buffer:
                    start = number
                buffer.append(line.rstrip())
            elif buffer:
                yield Block('\n'.join(buffer), title, line=start)
                buffer = []
        if buffer:
            yield Block('\n'.join(buffer), title, line=start)
