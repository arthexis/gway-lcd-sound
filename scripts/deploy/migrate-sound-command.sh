#!/usr/bin/env bash
# Explicit, reversible user-level adoption of the LCD Sound CLI.
# Does not touch /usr/local/bin/sound or its gway-home-tools target.
set -euo pipefail
usage() { echo "Usage: $0 inspect|adopt|verify|rollback" >&2; exit 2; }
action="${1:-}"; [[ $# == 1 ]] || usage
case "$action" in inspect|adopt|verify|rollback) ;; *) usage ;; esac
bin_dir="${GWAY_LCD_SOUND_BIN_DIR:-$HOME/.local/bin}"
prefix="${GWAY_LCD_SOUND_PREFIX:-$HOME/.local/share/gway-lcd-sound}"
link="$bin_dir/sound"
target="$prefix/current/scripts/gway/sound.sh"
state="$HOME/.local/state/gway-lcd-sound"
manifest="$state/sound-original-link"
mkdir -p "$state"
[[ ! -L "$state" && ! -L "$manifest" ]] || { echo "Unsafe migration state" >&2; exit 2; }
exec 9>"$state/sound-migration.lock"
flock -x 9
original="${GWAY_SOUND_ORIGINAL_COMMAND:-/usr/local/bin/sound}"
if [[ "$action" == inspect ]]; then
  printf 'current=%s\ntarget=%s\n' "$(readlink "$link" 2>/dev/null || echo '<not a symlink>')" "$target"
  exit 0
fi
if [[ "$action" == adopt ]]; then
  [[ -f "$target" && -x "$target" ]] || { echo "LCD Sound release not installed" >&2; exit 1; }
  if [[ -L "$link" && "$(readlink "$link")" == "$target" && -f "$manifest" ]]; then
    echo "already adopted"; exit 0
  fi
  [[ -L "$link" && "$(readlink "$link")" == "$original" && ! -e "$manifest" ]] || {
    echo "Refusing to replace unexpected sound link or existing migration state" >&2; exit 1;
  }
  [[ -f "$original" || -L "$original" ]] || { echo "Original command missing" >&2; exit 1; }
  (umask 077; printf '%s\n' "$original" > "$manifest")
  temp="$bin_dir/.sound-adopt.$$"
  trap 'rm -f "$temp"' EXIT
  ln -s "$target" "$temp"
  mv -Tf "$temp" "$link"
  echo "adopted user link; system sound untouched"
elif [[ "$action" == verify ]]; then
  [[ -L "$link" && "$(readlink "$link")" == "$target" && -f "$manifest" &&
     "$(cat "$manifest")" == "$original" && -x "$link" ]] || exit 1
  echo "adoption verified"
else
  [[ -f "$manifest" && "$(cat "$manifest")" == "$original" ]] || {
    echo "No recognized migration to rollback" >&2; exit 1;
  }
  [[ -L "$link" && "$(readlink "$link")" == "$target" ]] || {
    echo "Sound link changed since adoption; refusing rollback" >&2; exit 1;
  }
  temp="$bin_dir/.sound-rollback.$$"
  trap 'rm -f "$temp"' EXIT
  ln -s "$original" "$temp"
  mv -Tf "$temp" "$link"
  rm "$manifest"
  echo "original user link restored"
fi
