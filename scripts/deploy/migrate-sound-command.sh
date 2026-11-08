#!/usr/bin/env bash
# Explicit fail-forward adoption; never changes system-owned sound.
set -euo pipefail
[[ $# == 1 ]] || { echo "Usage: $0 inspect|adopt|verify" >&2; exit 2; }
action="$1"
case "$action" in inspect|adopt|verify) ;; *) exit 2 ;; esac
bin_dir="${GWAY_LCD_SOUND_BIN_DIR:-$HOME/.local/bin}"
prefix="${GWAY_LCD_SOUND_PREFIX:-$HOME/.local/share/gway-lcd-sound}"
link="$bin_dir/sound"
target="$prefix/current/scripts/gway/sound.sh"
original="${GWAY_SOUND_ORIGINAL_COMMAND:-/usr/local/bin/sound}"
state="$HOME/.local/state/gway-lcd-sound"
mkdir -p "$state"
[[ ! -L "$state" && ! -L "$state/sound-adopt.lock" ]] || exit 2
exec 9>"$state/sound-adopt.lock"
flock -x 9
if [[ "$action" == inspect ]]; then
  printf 'current=%s\ntarget=%s\n' "$(readlink "$link" 2>/dev/null || echo '<not a symlink>')" "$target"
elif [[ "$action" == verify ]]; then
  [[ -L "$link" && "$(readlink "$link")" == "$target" && -x "$link" ]]
else
  [[ -f "$target" && -x "$target" ]] || { echo "New sound command unavailable" >&2; exit 1; }
  if [[ -L "$link" && "$(readlink "$link")" == "$target" ]]; then
    echo "already adopted"; exit 0
  fi
  [[ -L "$link" && "$(readlink "$link")" == "$original" && -x "$original" ]] || {
    echo "Unexpected sound owner; refusing adoption" >&2; exit 1;
  }
  temp="$bin_dir/.sound-adopt.$$"
  trap 'rm -f "$temp"' EXIT
  ln -s "$target" "$temp"
  mv -Tf "$temp" "$link"
  echo "adopted; fix forward if later checks fail"
fi
