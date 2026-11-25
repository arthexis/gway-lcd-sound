#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
revision=${ROOT##*/}
case "$revision" in *[!0-9a-f]*) exit 2;; esac
[ "${#revision}" -eq 40 ] || exit 2
[ "$(git -C "$ROOT" rev-parse --verify HEAD)" = "$revision" ] || exit 2
[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ] || exit 2
[ "$(id -u)" -ne 0 ] || exit 2
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
ansible-playbook "$ROOT/ansible/playbooks/stage-mcp-release.yml" -i localhost, -c local -e "lcd_sound_revision=$revision"
"$ROOT/deploy.sh"
exec sudo -n ansible-playbook "$ROOT/ansible/playbooks/publish-mcp.yml" -i localhost, -c local -e "lcd_sound_revision=$revision" -e "lcd_sound_deployment_revision=$revision" -e "lcd_sound_deployment_checkout=$ROOT"
