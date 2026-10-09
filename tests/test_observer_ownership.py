"""6B: observer ownership requires an explicit, non-default cutover."""
import pytest

import gway_app_observer


def test_observer_mode_requires_all_ownership_inputs(tmp_path):
    with pytest.raises(SystemExit) as exc:
        gway_app_observer.main(["--notification-mode", "observer", "--once"])
    assert exc.value.code == 2


def test_shadow_conflicts_with_live_mode():
    with pytest.raises(SystemExit) as exc:
        gway_app_observer.main(["--shadow", "--notification-mode", "observer", "--once"])
    assert exc.value.code == 2


def test_bad_ownership_acknowledgement_rejected(tmp_path):
    token = tmp_path / "ownership"
    token.write_text("legacy-still-owns-notifications\n")
    sound = tmp_path / "sound"
    sound.write_text("#!/bin/sh\nexit 0\n")
    sound.chmod(0o700)
    with pytest.raises(SystemExit) as exc:
        gway_app_observer.main(["--notification-mode", "observer", "--once",
                                "--lcd-dir", str(tmp_path),
                                "--sound-command", str(sound),
                                "--ownership-file", str(token)])
    assert exc.value.code == 2
