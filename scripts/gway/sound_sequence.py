"""Pure-data one-shot composition validation shared with the piano editor."""
import json
import math

MAX_BYTES = 4096

def validate(notes):
    if not isinstance(notes, list) or not 1 <= len(notes) <= 12:
        raise ValueError("composition requires 1-12 steps")
    normalized = []
    for item in notes:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError("steps need [Hz, seconds, pause_seconds]")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in item):
            raise ValueError("step values must be numeric")
        hz, duration, pause = map(float, item)
        if not all(map(math.isfinite, (hz, duration, pause))):
            raise ValueError("values must be finite")
        if not (hz == 0 or 80 <= hz <= 4000):
            raise ValueError("frequency must be 0 (rest) or 80-4000 Hz")
        if not (0.01 <= duration <= 0.4 and 0 <= pause <= 0.4):
            raise ValueError("duration must be 10-400 ms, pause 0-400 ms")
        normalized.append([hz, duration, pause])
    return normalized

def parse_sequence(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("sequence exceeds size limit")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid sequence JSON") from exc
    if not isinstance(data, dict) or set(data) != {"format", "notes"} or data["format"] != "gway-piano-v1":
        raise ValueError("expected gway-piano-v1 composition")
    return validate(data["notes"])
