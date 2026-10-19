# M3: Gway-001 LCD/Sound field cutover

The release installer manages user commands, **not** root-owned systemd/udev configuration.
PR #33 already changed both tracked unit templates. This procedure is an explicit,
operator-approved host operation. It is not run by CI, `deploy.sh`, or an unattended
installer. Do not modify the Codex/Actions hooks during this cutover.

## 1. Inspect (read-only)

Run as the host operator, using the intended `arthe` account for user commands:

```bash
set -euo pipefail
bash scripts/deploy/install.sh verify
/home/arthe/.local/bin/gway-lcd-sound --help
systemctl cat gway-eth0-node-lcd.service
systemctl cat 'gway-event-sound-hotplug@.service'
systemctl show -p FragmentPath -p DropInPaths -p ActiveState -p UnitFileState gway-eth0-node-lcd.service
systemctl show -p FragmentPath -p DropInPaths -p UnitFileState 'gway-event-sound-hotplug@.service'
sudo grep -R -nE 'gway-(eth0-node-lcd-monitor|event-sound-hotplug|toggle-gpio-sound-mute|system-notify)' \
  /etc/systemd/system /etc/udev/rules.d /usr/local/bin /home/arthe/.config/systemd \
  2>/dev/null || true
```

Review the output and identify **all** live consumers, including drop-ins and
operator scripts. Do not infer host state from repository templates.

## 2. Capture rollback evidence before edits

Create an operator-owned backup directory outside the release tree. Record
`stat` and `sha256sum` for each existing legacy helper and each effective
unit file, then copy with permissions preserved (`cp -a`). Include any
drop-ins or udev rules you intend to modify. Keep backups until after field
acceptance. Do not overwrite an existing backup directory.

## 3. Stage and validate the tracked unit templates

The templates are:

- `config/systemd/gway/lcd/gway-eth0-node-lcd.service`
- `config/systemd/gway/event-sound/gway-event-sound-hotplug@.service`

Compare their `User`, `Group`, `Environment`, `WorkingDirectory`,
`Restart`, dependencies and hardening to the installed units. Preserve
host-specific settings and drop-ins; only change the effective `ExecStart`
when appropriate:

```ini
ExecStart=/home/arthe/.local/bin/gway-lcd-sound monitor eth0 --interval 15
```

```ini
ExecStart=/home/arthe/.local/bin/gway-lcd-sound hotplug %i
```

When using a systemd drop-in to override `ExecStart`, first clear the
existing command with an empty `ExecStart=` line. For a complete replacement
unit, retain the current permissions and service configuration. Verify the
staged files with `systemd-analyze verify` before installation.

## 4. Authorized activation only

After explicit field approval, install the reviewed units, run
`sudo systemctl daemon-reload`, and restart **only**
`gway-eth0-node-lcd.service` if it was already active. Do not enable
previously disabled services. Do not trigger udev events, mute GPIO, send
notifications, or play sound as part of the automated verification.

Confirm `systemctl show -p ExecStart -p ActiveState -p SubState`,
`systemctl status`, and relevant journal output. The hotplug template is a
oneshot activated on demand; verify its effective command without synthesizing
a physical event. Run `gway-lcd-sound mute toggle --status` only as a
read-only status check.

## 5. Acceptance and retirement

- The monitor is healthy and the effective `ExecStart` uses the dispatcher.
- The hotplug template's effective `ExecStart` uses the dispatcher.
- All other audited consumers use the new commands, or have an explicitly
  documented transitional compatibility requirement.
- Event and notification contracts have been checked without unauthorized
  external side effects.
- A physical LCD and hotplug/audio field test is recorded separately.

Only then retire legacy standalone files that have no remaining consumers;
retain backups until the operator accepts the field result. If activation
fails, restore the saved unit/drop-in files, reload systemd, and restart only
the previously active monitor. Do not roll back the entire release or change
unrelated services merely to undo a unit-file change.
