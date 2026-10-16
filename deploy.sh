#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(id -u)" -eq 0 ]; then
  echo "Run deployment as the non-root GWAY user." >&2
  exit 1
fi
command -v ansible-playbook >/dev/null 2>&1 || { echo "ansible-playbook is required" >&2; exit 1; }
export ANSIBLE_ROLES_PATH="$ROOT/ansible/roles"
exec ansible-playbook "$ROOT/ansible/playbooks/install.yml" -i localhost, -c local "$@"
