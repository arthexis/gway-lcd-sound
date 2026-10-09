"""Static safety contract for the autonomous observer user unit."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "scripts/deploy/systemd/user/gway-app-observer.service"
INSTALLER = ROOT / "scripts/deploy/install.sh"


def test_unit_is_unprivileged_shadow_only():
    text = UNIT.read_text()
    assert "ExecStart=%h/.local/bin/gway-app-observer --notification-mode shadow --no-processes" in text
    assert "NoNewPrivileges=true" in text
    assert "Restart=on-failure" in text
    assert "UMask=0077" in text
    assert "User=root" not in text
    assert "--csms-data %h/ocpp-csms-data" in text
    assert "ExecStartPre=" not in text
    assert "ExecStartPost=" not in text


def test_installer_never_starts_observer():
    text = INSTALLER.read_text()
    assert "systemctl --user enable --now gway-app-observer" not in text
    assert "systemctl --user start gway-app-observer" not in text
    assert 'link="$unit_dir/.$observer_unit.$$"' in text
    assert 'ln -s "$current/scripts/deploy/systemd/user/$observer_unit" "$link"' in text
    assert 'mv -Tf "$link" "$unit_dir/$observer_unit"' in text
