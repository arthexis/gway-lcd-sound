#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(id -u)" -eq 0 ]; then
  echo "Run deployment as the non-root GWAY user." >&2
  exit 1
fi
command -v ansible-playbook >/dev/null 2>&1 || { echo "ansible-playbook is required" >&2; exit 1; }
# Skip only when the active release and all installed command links are verified.
if [ "$#" -eq 0 ]; then
  revision=$(git -C "$ROOT" rev-parse --short=12 HEAD)
  prefix="$HOME/.local/share/gway-lcd-sound"
  release="$prefix/releases/$revision"
  bin="$HOME/.local/bin"
  if [ "$(readlink "$prefix/current" 2>/dev/null || true)" = "$release" ] &&
     [ -d "$release/scripts/gway" ] &&
     [ "$(readlink "$bin/lcd-lockfile-runner" 2>/dev/null || true)" = "$prefix/current/scripts/gway/lcd_lockfile_runner.py" ] &&
     [ "$(readlink "$bin/gway-event-sound-monitor" 2>/dev/null || true)" = "$prefix/current/scripts/gway/gway_event_sound_monitor.py" ] &&
     [ "$(readlink "$bin/lcd-system-info-publisher" 2>/dev/null || true)" = "$prefix/current/scripts/gway/lcd_system_info_publisher.py" ] &&
     [ "$(readlink "$bin/gway-app-observer" 2>/dev/null || true)" = "$prefix/current/scripts/gway/gway_app_observer.py" ] &&
     "$bin/lcd-system-info-publisher" --help >/dev/null 2>&1 &&
     "$bin/gway-app-observer" --help >/dev/null 2>&1 &&
     "$bin/lcd-lockfile-runner" --help >/dev/null 2>&1 &&
     "$bin/gway-event-sound-monitor" --help >/dev/null 2>&1; then
    printf 'LCD Sound revision %s already installed and healthy; skipped Ansible.\n' "$revision"
    exit 0
  fi
fi
export ANSIBLE_ROLES_PATH="$ROOT/ansible/roles"
exec ansible-playbook "$ROOT/ansible/playbooks/install.yml" -i localhost, -c local "$@"
