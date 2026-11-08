"""Offline release and manifest safety contracts; no root, node or hardware needed."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/publish-mcp.yml"
ROLE = ROOT / "ansible/roles/gway_lcd_sound/tasks/main.yml"
DEFAULTS = ROOT / "ansible/roles/gway_lcd_sound/defaults/main.yml"


def test_mcp_publication_is_opt_in():
    assert PLAYBOOK.is_file()
    assert "publish-mcp.yml" not in (ROOT / "ansible/playbooks/install.yml").read_text()
    assert "publish-mcp.yml" not in (ROOT / "deploy.sh").read_text()
    assert "lcd_sound" not in DEFAULTS.read_text().split("gway_lcd_sound_commands:", 1)[-1]


def test_pinned_manifest_and_root_owned_atomic_copy():
    source = PLAYBOOK.read_text()
    assert "^[a-f0-9]{40}$" in source
    assert "lcd_sound_revision" in source
    assert "follow: false" in source
    assert "owner: root" in source and "group: root" in source
    assert "mode: '0644'" in source
    assert "ansible.builtin.copy:" in source
    assert "lcd_sound_manifest_path" in source
    assert "/current/" not in source
    assert "force: true" not in source


def test_historical_sound_is_not_replaced():
    source = ROLE.read_text()
    defaults = DEFAULTS.read_text()
    assert re.search(r"^  sound:", defaults, re.M) is None
    assert "migrate-sound-command.sh" not in source


def test_two_tools_are_execute_only():
    import importlib.util
    path = ROOT / "scripts/gway/lcd_sound_mcp.py"
    spec = importlib.util.spec_from_file_location("lcd_sound_mcp_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {tool["name"] for tool in module.TOOLS} == {"lcd", "sound"}
    assert all(tool["annotations"]["readOnlyHint"] is False for tool in module.TOOLS)

def test_manifest_publication_has_verified_rollback():
    source = PLAYBOOK.read_text()
    assert "block:" in source and "rescue:" in source
    assert "previous_manifest" in source
    assert "published_manifest" in source
    assert "Restore previous manifest atomically" in source
    assert "Remove new manifest if no previous state existed" in source
    assert "Fail closed after rollback" in source


def test_staging_playbook_is_opt_in_and_full_sha():
    source = (ROOT / "ansible/playbooks/stage-mcp-release.yml").read_text()
    assert "install-mcp-release.py" in source
    assert "^[a-f0-9]{40}$" in source
    assert "ansible_user_uid | int != 0" in source
    assert "stage-mcp-release.yml" not in (ROOT / "deploy.sh").read_text()

def test_fault_injection_is_exercised_by_ci_without_production_paths():
    playbook = PLAYBOOK.read_text()
    ci = (ROOT / ".github/workflows/ansible-deployment.yml").read_text()
    assert "lcd_sound_test_inject_verify_failure" in playbook
    assert "lcd_sound_test_inject_verify_failure=true" in ci
    assert "mcp-registry-test" in ci
    assert "previous-manifest.json" in ci
    assert "published-manifest.json" in ci
    assert "cmp " in ci
    assert "sudo -n ansible-playbook" in ci
