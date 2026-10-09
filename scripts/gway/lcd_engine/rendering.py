"""Deterministic LCD sanitization and 16-column window selection."""
from __future__ import annotations
import re

COLUMNS = 16


def clean_line(text: object, *, limit: int = 64) -> str:
    value = "" if text is None else str(text)
    value = value.replace("\\r\\n", "\\n").replace("\\r", "\\n")
    value = re.sub(r"[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F]", " ", value)
    value = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in value)
    return value[:limit]


def scroll_segment(text: str, step: int, *, columns: int = COLUMNS) -> str:
    cleaned = clean_line(text)
    if len(cleaned) <= columns:
        return cleaned.ljust(columns)
    padded = f"{cleaned}   "
    span = max(len(padded) - columns + 1, 1)
    index = step % span
    return padded[index : index + columns].ljust(columns)


def frame_for_payload(payload, step: int, *, columns: int = COLUMNS) -> tuple[str, str]:
    return scroll_segment(payload.line1, step, columns=columns), scroll_segment(payload.line2, step, columns=columns)
