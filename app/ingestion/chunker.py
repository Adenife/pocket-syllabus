"""Tokenizer-aware windows with overlap and sentence boundaries."""
from dataclasses import dataclass
import re
from app.ingestion.parsers.text import Block

@dataclass
class Chunk:
    text: str
    title: str
    section: str
    page: int | None
    line: int | None


def chunk_blocks(blocks, tokenizer, model_limit: int, budget=220, overlap=32):
    special = tokenizer.num_special_tokens_to_add(pair=False)
    budget = min(budget, model_limit - special)
    if budget < 1:
        raise ValueError('Model token window is too small')
    overlap = min(overlap, max(0, budget // 4))
    for block in blocks:
        # Fast-tokenizer offsets retain original whitespace and code formatting.
        encoded = tokenizer(block.text, add_special_tokens=False, return_offsets_mapping=True,
                            truncation=False, verbose=False)
        offsets = encoded['offset_mapping']
        start = 0
        while start < len(offsets):
            end = min(start + budget, len(offsets))
            if end < len(offsets):
                lower = start + budget // 2
                for candidate in range(end, lower, -1):
                    segment = block.text[offsets[start][0]:offsets[candidate - 1][1]]
                    if re.search(r'[.!?]["\']?\s*$', segment):
                        end = candidate
                        break
            value = block.text[offsets[start][0]:offsets[end - 1][1]].strip()
            if value:
                # Assert the real encoded length, accounting for tokenizer edge cases.
                if len(tokenizer.encode(value, add_special_tokens=True)) > model_limit:
                    raise ValueError('Chunk exceeds model input limit')
                yield Chunk(value, block.title, block.section, block.page, block.line)
            if end == len(offsets):
                break
            start = max(start + 1, end - overlap)
