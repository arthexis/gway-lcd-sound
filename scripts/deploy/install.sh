#!/usr/bin/env bash
# Install host-local LCD Sound without root privileges.
# A versioned release is activated by an atomic current-symlink replacement.
set -euo pipefail

usage() {
  echo "Usage: $0 install|verify|rollback [--no-restart]" >&2
  exit 2
}

action="${1:-}"
[[ "$action" == install || "$action" == verify || "$action" == rollback ]] || usage
restart=1
[[ "${2:-}" == --no-restart ]] && restart=0
[[ -z "${2:-}" || "${2:-}" == --no-restart ]] || usage

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
prefix="${GWAY_LCD_SOUND_PREFIX:-$HOME/.local/share/gway-lcd-sound}"
bin_dir="${GWAY_LCD_SOUND_BIN_DIR:-$HOME/.local/bin}"
current="$prefix/current"
previous="$prefix/previous"
releases="$prefix/releases"
unit_dir="${GWAY_LCD_SOUND_UNIT_DIR:-$HOME/.config/systemd/user}"
man_dir="${GWAY_LCD_SOUND_MAN_DIR:-$HOME/.local/share/man/man1}"
observer_unit="gway-app-observer.service"

# Entry-point symlinks stay fixed, while their resolved targets switch releases.
commands=(
  lcd-lockfile-runner:lcd_lockfile_runner.py
  lcd-system-info-publisher:lcd_system_info_publisher.py
  lcd-actions-runner-status:lcd-actions-runner-status
  gway-event-sound-monitor:gway_event_sound_monitor.py
  codex-sound-hook:codex-sound-hook
  github-actions-sound-hook:github-actions-sound-hook
  github-actions-job-started:github-actions-job-started
  github-actions-job-completed:github-actions-job-completed
  gway-app-observer:gway_app_observer.py
  gway-lcd-sound:gway-lcd-sound
)
manpages=(gway-lcd-sound.1)
legacy_helpers=(
  gway-eth0-node-lcd-monitor
  gway-event-sound-hotplug
  gway-toggle-gpio-sound-mute
  gway-system-notify
)
resolve_current() {
  [[ -L "$current" && -d "$current/scripts/gway" ]]
}
report_stale_legacy_helpers() {
  local command
  for command in "${legacy_helpers[@]}"; do
    if [[ -f "$bin_dir/$command" && ! -L "$bin_dir/$command" ]]; then
      echo "Warning: stale independent legacy helper retained: $bin_dir/$command" >&2
    fi
  done
}
verify() {
  resolve_current || { echo "No active LCD Sound release" >&2; return 1; }
  for pair in "${commands[@]}"; do
    local cmd="${pair%%:*}" file="${pair#*:}"
    [[ -L "$bin_dir/$cmd" && "$(readlink "$bin_dir/$cmd")" == "$current/scripts/gway/$file" && -x "$bin_dir/$cmd" && -f "$current/scripts/gway/$file" ]] || {
      echo "Missing installed command: $cmd" >&2; return 1;
    }
  done
  for page in "${manpages[@]}"; do
    if [[ -f "$current/docs/man/man1/$page" ]]; then
      [[ -L "$man_dir/$page" && "$(readlink "$man_dir/$page")" == "$current/docs/man/man1/$page" ]] || {
        echo "Missing installed manual page: $page" >&2; return 1;
      }
    fi
  done
  "$bin_dir/lcd-lockfile-runner" --help >/dev/null
  "$bin_dir/lcd-system-info-publisher" --help >/dev/null
  "$bin_dir/gway-event-sound-monitor" --help >/dev/null
  "$bin_dir/gway-app-observer" --help >/dev/null
  if [[ -f "$current/scripts/deploy/systemd/user/$observer_unit" ]]; then
    [[ -L "$unit_dir/$observer_unit" && "$(readlink "$unit_dir/$observer_unit")" == "$current/scripts/deploy/systemd/user/$observer_unit" ]] || {
      echo "Missing or unexpected observer user unit: $unit_dir/$observer_unit" >&2; return 1;
    }
    grep -q -- "--notification-mode shadow" "$unit_dir/$observer_unit" || {
      echo "Observer unit must remain in shadow mode" >&2; return 1;
    }
  fi
  PYTHONDONTWRITEBYTECODE=1 python3 - "$current/scripts/gway" <<'PY'
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).resolve()))
import lcd_engine.hardware.discovery
import lcd_engine.system_info.collectors
import sound_engine.events
import event_engine.app_observer
import event_engine.observer_lock
import event_engine.notification_journal
PY
  report_stale_legacy_helpers
  echo "LCD Sound installation verified: $(readlink -f "$current")"
}
activate() {
  local target="$1" temp
  [[ -d "$target/scripts/gway" ]] || { echo "Invalid release: $target" >&2; return 1; }
  mkdir -p "$prefix" "$bin_dir" "$man_dir"
  temp="$prefix/.current.$$"
  ln -s "$target" "$temp"
  # Publish the release pointer last: a failed link update must not switch code.
  for pair in "${commands[@]}"; do
    local cmd="${pair%%:*}" file="${pair#*:}" link
    link="$bin_dir/.$cmd.$$"
    ln -s "$current/scripts/gway/$file" "$link"
    mv -Tf "$link" "$bin_dir/$cmd" || { rm -f "$link" "$temp"; return 1; }
  done
  for page in "${manpages[@]}"; do
    if [[ -f "$target/docs/man/man1/$page" ]]; then
      link="$man_dir/.$page.$$"
      ln -s "$current/docs/man/man1/$page" "$link"
      mv -Tf "$link" "$man_dir/$page" || { rm -f "$link" "$temp"; return 1; }
    elif [[ -L "$man_dir/$page" && "$(readlink "$man_dir/$page")" == "$current/docs/man/man1/$page" ]]; then
      rm "$man_dir/$page"
    fi
  done
  # Install the definition only; never enable, start, or restart this service.
  if [[ -f "$target/scripts/deploy/systemd/user/$observer_unit" ]]; then
    mkdir -p "$unit_dir"
    link="$unit_dir/.$observer_unit.$$"
    ln -s "$current/scripts/deploy/systemd/user/$observer_unit" "$link"
    mv -Tf "$link" "$unit_dir/$observer_unit" || { rm -f "$link" "$temp"; return 1; }
    if command -v systemctl >/dev/null; then
      systemctl --user daemon-reload || echo "Warning: user daemon-reload unavailable; run it after login" >&2
    fi
  elif [[ -L "$unit_dir/$observer_unit" && "$(readlink "$unit_dir/$observer_unit")" == "$current/scripts/deploy/systemd/user/$observer_unit" ]]; then
    rm "$unit_dir/$observer_unit"
    if command -v systemctl >/dev/null; then
      systemctl --user daemon-reload || echo "Warning: user daemon-reload unavailable" >&2
    fi
  fi
  mv -Tf "$temp" "$current"
}
maybe_restart() {
  if [[ "$restart" == 1 ]] && command -v systemctl >/dev/null; then
    # Services may not be installed. Their absence is not an installation failure.
    systemctl --user try-restart lcd-lockfile.service 2>/dev/null || true
  fi
}

case "$action" in
  install)
    mkdir -p "$releases"
    version="$(git -C "$source_dir" rev-parse --short=12 HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
    target="$releases/$version"
    if [[ ! -d "$target" ]]; then
      staging="$(mktemp -d "$releases/.staging.XXXXXXXX")"
      trap 'rm -rf "$staging"' EXIT
      mkdir -p "$staging/scripts"
      cp -a "$source_dir/scripts/gway" "$staging/scripts/gway"
      mkdir -p "$staging/docs/man/man1"
      cp "$source_dir/docs/man/man1/gway-lcd-sound.1" "$staging/docs/man/man1/gway-lcd-sound.1"
      if [[ -f "$source_dir/scripts/deploy/systemd/user/$observer_unit" ]]; then
        mkdir -p "$staging/scripts/deploy/systemd/user"
        cp "$source_dir/scripts/deploy/systemd/user/$observer_unit" "$staging/scripts/deploy/systemd/user/$observer_unit"
      fi
      chmod 0755 "$staging/scripts/gway/lcd-actions-runner-status" "$staging/scripts/gway/gway_app_observer.py" "$staging/scripts/gway/github-actions-sound-hook" "$staging/scripts/gway/github-actions-job-started" "$staging/scripts/gway/github-actions-job-completed" "$staging/scripts/gway/gway-lcd-sound"
      PYTHONDONTWRITEBYTECODE=1 python3 - "$staging/scripts/gway" <<'PY'
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).resolve()))
import lcd_engine.hardware.discovery
import lcd_engine.system_info.collectors
import sound_engine.events
PY
      mv "$staging" "$target"
      trap - EXIT
    fi
    old=""
    if resolve_current; then old="$(readlink -f "$current")"; fi
    if [[ -n "$old" && "$old" != "$target" ]]; then
      ln -s "$old" "$prefix/.previous.$$"
      mv -Tf "$prefix/.previous.$$" "$previous"
    fi
    if ! activate "$target" || ! verify; then
      if [[ -n "$old" ]]; then activate "$old"; fi
      echo "Verification failed; restored previous release where available" >&2
      exit 1
    fi
    maybe_restart
    ;;
  verify)
    verify
    ;;
  rollback)
    [[ -L "$previous" ]] || { echo "No previous release available" >&2; exit 1; }
    prior="$(readlink -f "$previous")"
    old=""
    if resolve_current; then old="$(readlink -f "$current")"; fi
    if ! activate "$prior" || ! verify; then
      [[ -z "$old" ]] || activate "$old"
      exit 1
    fi
    if [[ -n "$old" ]]; then
      ln -s "$old" "$prefix/.previous.$$"
      mv -Tf "$prefix/.previous.$$" "$previous"
    fi
    maybe_restart
    ;;
esac
