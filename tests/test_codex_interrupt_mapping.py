from pathlib import Path


def test_codex_interrupt_maps_to_warning():
    script = (Path(__file__).resolve().parents[1] / 'scripts/gway/sound.sh').read_text()
    assert '("codex", "Interrupt", "warning")' in script
    assert '("codex", "Stop", "ok")' in script
