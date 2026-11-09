"""Offline contract tests for ephemeral compositions."""
import json
import pytest
from sound_sequence import parse_sequence, validate

def test_piano_format_roundtrip():
    notes = [[440, .12, .03], [0, .05, 0], [880, .2, 0]]
    assert parse_sequence(json.dumps({"format": "gway-piano-v1", "notes": notes})) == validate(notes)

@pytest.mark.parametrize("payload", [
    "[]", "{}", '{"format":"other","notes":[[440,0.1,0]]}',
    '{"format":"gway-piano-v1","notes":[]}',
    '{"format":"gway-piano-v1","notes":[[true,0.1,0]]}',
    '{"format":"gway-piano-v1","notes":[[440,0.1,-1]]}',
    '{"format":"gway-piano-v1","notes":[[440,0.1,0]],"command":"rm"}',
    "x" * 4097,
])
def test_reject_invalid_sequences(payload):
    with pytest.raises(ValueError):
        parse_sequence(payload)

def test_reject_non_finite_and_excessive_steps():
    with pytest.raises(ValueError):
        validate([[float("nan"), .1, 0]])
    with pytest.raises(ValueError):
        validate([[440, .1, 0]] * 13)
