# GWAY LCD And Event Sound

GWAY uses two local operator-feedback surfaces during rebuild and operation:

- a standalone LCD lockfile runner that can keep showing host status even when
  the suite is restarting
- GPIO/audio earcons for USB, bastion, network, thermal, undervoltage, feedback,
  and upgrade events

The live helpers are host-local and intentionally avoid direct database access
for normal LCD/event operation. Runtime lockfiles, history, logs, and current
hardware identifiers are operational state and must not be published as source.

## Repository Files

| Source path | Install target |
| --- | --- |
| `scripts/gway/lcd_lockfile_runner.py` | `/home/arthe/.local/bin/lcd-lockfile-runner` |
| `scripts/gway/lcd_system_info_publisher.py` | `/home/arthe/.local/bin/lcd-system-info-publisher` |
| `scripts/gway/gway_eth0_node_lcd_monitor.py` | `/home/arthe/.local/bin/gway-eth0-node-lcd-monitor` |
| `scripts/gway/arthexis_dense_lcd_summary.py` | `/usr/local/bin/arthexis-dense-lcd-summary` |
| `scripts/gway/gway_event_sound_monitor.py` | `/home/arthe/.local/bin/gway-event-sound-monitor` |
| `scripts/gway/gway-event-sound-hotplug` | `/home/arthe/.local/bin/gway-event-sound-hotplug` |
| `scripts/gway/codex-sound-hook` | `/home/arthe/.local/bin/codex-sound-hook` |
| `scripts/gway/gway-toggle-gpio-sound-mute` | `/home/arthe/.local/bin/gway-toggle-gpio-sound-mute` |
| `scripts/gway/gway-system-notify` | `/home/arthe/.local/bin/gway-system-notify` |
| `scripts/gway/sound.sh` | `/usr/local/libexec/gway-home-tools/sound.sh` plus `/usr/local/bin/sound` symlink |
| `config/systemd/gway/lcd/` | system and user systemd units/drop-ins |
| `config/systemd/gway/event-sound/` | event-sound systemd units |
| `config/udev/rules.d/94-gway-event-sound.rules.template` | `/etc/udev/rules.d/94-gway-event-sound.rules` after local edit |
| `config/templates/gway-lcd.env.template` | optional local LCD systemd drop-in values |
| `config/templates/gway-event-sound.env.template` | optional local event-sound systemd drop-in values |
| `docs/man/man1/lcd-commands.1` | `/usr/local/share/man/man1/lcd-commands.1` |
| `docs/man/man1/sound-commands.1` | `/usr/local/share/man/man1/sound-commands.1` |

## Drift Resolution

The 2026-07-28 rebuild inventory found these live/staging differences:

- `arthexis-llm-lcd-summary.service` no longer depends on Celery.
- `gway-event-sound.service` and `gway-event-sound-hotplug@.service` use the
  live `gway-*` helper names, not the older `arthexis-*` names.
- `94-gway-event-sound.rules` targets the live `gway-*` hotplug unit names, but
  also contains private bastion USB selectors.

For rebuild purposes, the repository follows installed behavior for dependency
ordering and helper names. The dense LCD summary script is promoted from its
staging directory into repository source and installed as
`/usr/local/bin/arthexis-dense-lcd-summary`; the systemd unit uses that stable
target. The udev file is a template so local bastion serials and filesystem UUIDs
stay out of public source.

## Install

From the repository root as the `arthe` user, use the supported
release installer rather than copying Python packages individually:

```bash
bash scripts/deploy/install.sh install
bash scripts/deploy/install.sh verify
# If the current release is not usable:
bash scripts/deploy/install.sh rollback
```

The installer owns host-local LCD and sound entry points, versioned releases,
and the `current` symlink. It does not install system-wide units, udev rules,
the root-owned audio player, man pages or private bastion selectors. These
remain explicit administrator operations. To install those prerequisites:

```bash
sudo install -d -m 0755 /usr/local/bin /usr/local/libexec/gway-home-tools /usr/local/share/man/man1
sudo install -m 0755 scripts/gway/sound.sh /usr/local/libexec/gway-home-tools/sound.sh
sudo ln -sfn /usr/local/libexec/gway-home-tools/sound.sh /usr/local/bin/sound
sudo install -m 0755 scripts/gway/arthexis_dense_lcd_summary.py /usr/local/bin/arthexis-dense-lcd-summary
sudo install -m 0644 docs/man/man1/lcd-commands.1 /usr/local/share/man/man1/lcd-commands.1
sudo install -m 0644 docs/man/man1/sound-commands.1 /usr/local/share/man/man1/sound-commands.1
```

Install system services:

```bash
sudo install -d -m 0755 /etc/systemd/system \
  /etc/systemd/system/lcd-arthexis.service.d \
  /etc/systemd/system/arthexis-llm-lcd-summary.service.d
sudo install -m 0644 config/systemd/gway/lcd/lcd-arthexis.service \
  /etc/systemd/system/lcd-arthexis.service
sudo install -m 0644 config/systemd/gway/lcd/lcd-arthexis.service.d/30-no-pycache.conf \
  /etc/systemd/system/lcd-arthexis.service.d/30-no-pycache.conf
sudo install -m 0644 config/systemd/gway/lcd/arthexis-llm-lcd-summary.service \
  /etc/systemd/system/arthexis-llm-lcd-summary.service
sudo install -m 0644 config/systemd/gway/lcd/arthexis-llm-lcd-summary.service.d/30-no-pycache.conf \
  /etc/systemd/system/arthexis-llm-lcd-summary.service.d/30-no-pycache.conf
sudo install -m 0644 config/systemd/gway/lcd/arthexis-llm-lcd-summary.timer \
  /etc/systemd/system/arthexis-llm-lcd-summary.timer
sudo install -m 0644 config/systemd/gway/lcd/gway-eth0-node-lcd.service \
  /etc/systemd/system/gway-eth0-node-lcd.service
sudo install -m 0644 config/systemd/gway/event-sound/gway-event-sound.service \
  /etc/systemd/system/gway-event-sound.service
sudo install -m 0644 config/systemd/gway/event-sound/gway-event-sound-hotplug@.service \
  /etc/systemd/system/gway-event-sound-hotplug@.service
```

Install user services as the `arthe` user:

```bash
install -d -m 0755 "$HOME/.config/systemd/user" \
  "$HOME/.config/systemd/user/lcd-system-info-publisher.timer.d"
install -m 0644 config/systemd/gway/lcd/user/lcd-lockfile.service \
  "$HOME/.config/systemd/user/lcd-lockfile.service"
install -m 0644 config/systemd/gway/lcd/user/lcd-system-info-publisher.service \
  "$HOME/.config/systemd/user/lcd-system-info-publisher.service"
install -m 0644 config/systemd/gway/lcd/user/lcd-system-info-publisher.timer \
  "$HOME/.config/systemd/user/lcd-system-info-publisher.timer"
install -m 0644 \
  config/systemd/gway/lcd/user/lcd-system-info-publisher.timer.d/98-boot-stagger-30s.conf \
  "$HOME/.config/systemd/user/lcd-system-info-publisher.timer.d/98-boot-stagger-30s.conf"
systemctl --user daemon-reload
systemctl --user enable --now lcd-lockfile.service lcd-system-info-publisher.timer
sudo systemctl daemon-reload
sudo systemctl enable --now lcd-arthexis.service arthexis-llm-lcd-summary.timer \
  gway-eth0-node-lcd.service gway-event-sound.service
```

Install the event hotplug rule only after replacing the bastion placeholders:

```bash
sudo install -m 0644 config/udev/rules.d/94-gway-event-sound.rules.template \
  /etc/udev/rules.d/94-gway-event-sound.rules
sudo editor /etc/udev/rules.d/94-gway-event-sound.rules
sudo udevadm control --reload
```

## Validation

LCD software path:

```bash
lcd-system-info-publisher --dry-run
lcd-lockfile-runner --once --dry-run --no-hardware
systemctl --user status lcd-lockfile.service --no-pager
systemctl --user status lcd-system-info-publisher.timer --no-pager
systemctl status lcd-arthexis.service arthexis-llm-lcd-summary.timer --no-pager
```

LCD hardware path:

```bash
i2cdetect -y 1
journalctl --user -u lcd-lockfile.service -n 50 --no-pager
tail -n 50 /home/arthe/.local/state/lcd-lockfile-runner/lcd-lockfile-runner.log
cat /home/arthe/.local/state/lcd-lockfile-runner/lcd-screen.txt
```

The runner auto-detects common LCD addresses `0x27`, `0x3f`, and `0x3e`. If
those addresses are missing and the log shows `lcd-unavailable` or I/O errors,
check wiring, display power, connector seating, and the I2C bus before changing
application code.

Event sound path:

```bash
sound list
sound ok --dry-run
codex-sound-hook test ok
gway-event-sound-monitor --once --json
gway-event-sound-monitor --once --json --dry-run
systemctl status gway-event-sound.service --no-pager
journalctl -u gway-event-sound.service -n 50 --no-pager
```

Hotplug path:

```bash
systemctl status 'gway-event-sound-hotplug@bastion-add.service' --no-pager
systemctl status 'gway-event-sound-hotplug@wifi-add.service' --no-pager
udevadm test-builtin net_id /sys/class/net/<usb-wlan-iface>
```

## Safety Notes

- Do not commit filled `ID_SERIAL_SHORT`, `ID_FS_UUID`, or other private udev
  selectors.
- Do not publish LCD history or event-sound logs if they include local operator
  messages, device labels, MAC addresses, serials, or paths.
- Do not treat a fresh LCD fallback file as proof the physical LCD works; verify
  I2C detection and runner logs.
- Do not run live sound playback in shared/noisy environments; use `--dry-run`
  when validating command shape only.

## GitHub Actions runner PR display

The standalone `lcd-lockfile-runner` reserves a high-priority LCD frame when
`$HOME/.local/state/lcd-lockfiles/lcd-actions-runner` exists with three lines:
the top row, bottom row, and UTC expiration timestamp. It bypasses rotating
status/event frames for the duration of the job, while retaining the existing
LCD driver and recovery behavior. Expired locks are discarded automatically.

The OCPP-CSMS self-hosted CI workflow updates the sibling checkout on
Gway-001 and calls `scripts/deploy/install.sh install --no-restart`, followed
by `verify --no-restart`. It then smoke-tests the installed LCD and sound
commands before starting the PR status notification.

A trusted PR job in `arthexis/ocpp-csms` with the `simulator` label invokes:

```bash
lcd-actions-runner-status start 142 ci/trusted-pr-ocpp-simulator-e2e
# On job completion (including failure):
lcd-actions-runner-status stop
```

The first LCD line becomes `Run PR #142`; the bottom shows the head branch
name, scrolling if longer than the 16-column display. While the job is running,
this message overrides the normal LCD rotation. It is removed in an always-run
workflow cleanup step, with a 3-hour expiry as a crash/cancellation fallback.

LCD updates are best-effort and do not alter CI success/failure. No physical LCD
writes occur from the GitHub Actions workflow itself; only the installed
host-local LCD runner owns the hardware.
