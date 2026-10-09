"""Pure LCD text normalization and display window selection."""
from __future__ import annotations
import re

COLUMNS = 16

def clean_line(text: object, *, limit: int = 64) -> str:
    value = "" if text is None else str(text)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", value)
    value = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in value)
    return value[:limit]


def scroll_segment(text: str, step: int) -> str:
    clean = clean_line(text)
    if len(clean) <= COLUMNS:
        return clean.ljust(COLUMNS)
    padded = f"{clean}   "
    span = max(len(padded) - COLUMNS + 1, 1)
    index = step % span
    return padded[index : index + COLUMNS].ljust(COLUMNS)

