#!/usr/bin/env bash
set -euo pipefail

cleanup_gpio() {
  if command -v pinctrl >/dev/null 2>&1; then
    pinctrl set "${NODE_SOUND_GPIO_PIN:-${GWAY_SOUND_GPIO_PIN:-18}}" ip pd >/dev/null 2>&1 || true
  fi
}

trap cleanup_gpio EXIT

python3 /dev/fd/3 "$@" 3<<'PY'
import argparse
import json
import re
import sqlite3
import fcntl
import math
import os
import shutil
import struct
import subprocess
import sys
import time
import tempfile
import wave
from datetime import datetime, timezone


DEFAULT_PIN = int(os.environ.get("NODE_SOUND_GPIO_PIN") or os.environ.get("GWAY_SOUND_GPIO_PIN", "18"))
DEFAULT_BACKEND = "gpio"
DEFAULT_AUDIO_DEVICE = os.environ.get("NODE_SOUND_AUDIO_DEVICE") or os.environ.get("GWAY_SOUND_AUDIO_DEVICE", "")
DEFAULT_ALSA_DEVICE = os.environ.get("NODE_SOUND_ALSA_DEVICE") or os.environ.get("GWAY_SOUND_ALSA_DEVICE", "")
BACKEND_LOG = os.environ.get("GWAY_SOUND_BACKEND_LOG", "/home/arthe/.local/state/codex-sound-hooks/backend.log")
GPIO_MUTE_FILE = (
    os.environ.get("NODE_SOUND_GPIO_MUTE_FILE")
    or os.environ.get("GWAY_SOUND_GPIO_MUTE_FILE")
    or os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "gway-sound", "gpio-muted")
)
MAX_DUTY_CYCLE = 28.0
SAMPLE_RATE = 48000
CHANNELS = 2
AUDIO_GAIN = float(os.environ.get("NODE_SOUND_AUDIO_GAIN") or os.environ.get("GWAY_SOUND_AUDIO_GAIN", "2.0"))
GPIO_WAIT_SECONDS = float(os.environ.get("NODE_SOUND_GPIO_WAIT_SECONDS") or os.environ.get("GWAY_SOUND_GPIO_WAIT_SECONDS", "8.0"))
NOISE_ALARM_SUPPRESS_FILE = (
    os.environ.get("NODE_SOUND_NOISE_ALARM_SUPPRESS_FILE")
    or os.environ.get("GWAY_SOUND_NOISE_ALARM_SUPPRESS_FILE")
    or os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "gway-sound", "noise-alarm-suppress.json")
)
NOISE_ALARM_SUPPRESS_SECONDS = float(
    os.environ.get("NODE_SOUND_NOISE_ALARM_SUPPRESS_SECONDS")
    or os.environ.get("GWAY_SOUND_NOISE_ALARM_SUPPRESS_SECONDS", "15.0")
)

PATTERNS = {
    "ok": (
        (1047, 0.075, 0.0),
    ),
    "notice": (
        (784, 0.065, 0.055),
        (784, 0.065, 0.0),
    ),
    "email": (
        (659, 0.055, 0.025),
        (880, 0.065, 0.025),
        (1175, 0.095, 0.0),
    ),
    "attention": (
        (523, 0.080, 0.050),
        (1047, 0.105, 0.0),
    ),
    "warning": (
        (1047, 0.090, 0.055),
        (523, 0.140, 0.0),
    ),
    "error": (
        (392, 0.085, 0.050),
        (392, 0.085, 0.050),
        (392, 0.110, 0.0),
    ),
    "noise": (
        (147, 0.4995, 0.0),
        (98, 0.1665, 0.0),
    ),
    "busy": (
        (659, 0.035, 0.040),
        (659, 0.035, 0.040),
        (659, 0.035, 0.040),
        (659, 0.035, 0.0),
    ),
    "critical": (
        (880, 0.090, 0.035),
        (440, 0.110, 0.035),
        (880, 0.090, 0.035),
        (440, 0.150, 0.0),
    ),
    "undervoltage": (
        (247, 0.120, 0.045),
        (196, 0.170, 0.045),
        (147, 0.240, 0.0),
    ),
}

DESCRIPTIONS = {
    "ok": "single high chirp",
    "notice": "two even mid chirps",
    "email": "quick rising mail triad",
    "attention": "rising low-high pair",
    "warning": "falling high-low pair",
    "error": "three low buzzes",
    "noise": "long grave buzz with deeper tail",
    "busy": "four fast ticks",
    "critical": "alternating alarm",
    "undervoltage": "low descending power sag",
}


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def log_backend(message):
    try:
        os.makedirs(os.path.dirname(BACKEND_LOG), exist_ok=True)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(BACKEND_LOG, "a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")
    except Exception:
        pass


def pattern_seconds(pattern):
    return sum(max(0.0, duration) + max(0.0, pause) for _frequency, duration, pause in pattern)


def mark_noise_alarm_suppressed(name, backend, pattern):
    if backend != "gpio" or NOISE_ALARM_SUPPRESS_SECONDS <= 0:
        return
    now = time.time()
    suppress_until_epoch = now + pattern_seconds(pattern) + NOISE_ALARM_SUPPRESS_SECONDS
    payload = {
        "sound": name,
        "backend": backend,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "suppress_until": datetime.fromtimestamp(suppress_until_epoch, timezone.utc).isoformat(),
        "suppress_until_epoch": suppress_until_epoch,
    }
    try:
        directory = os.path.dirname(NOISE_ALARM_SUPPRESS_FILE)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        tmp_path = f"{NOISE_ALARM_SUPPRESS_FILE}.tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            import json

            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, NOISE_ALARM_SUPPRESS_FILE)
    except Exception as exc:
        log_backend(f"sound={name} noise_alarm_suppress_marker_failed={exc!r}")


def gpio_muted():
    return os.path.exists(GPIO_MUTE_FILE)


def ensure_gpio_workdir():
    candidates = []
    configured = os.environ.get("NODE_SOUND_GPIO_WORKDIR") or os.environ.get("GWAY_SOUND_GPIO_WORKDIR")
    if configured:
        candidates.append(configured)
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    candidates.append(os.path.join(runtime_dir, "gway-sound"))
    candidates.append(os.path.join(tempfile.gettempdir(), f"gway-sound-{os.getuid()}"))

    last_error = ""
    for candidate in candidates:
        try:
            os.makedirs(candidate, mode=0o700, exist_ok=True)
            os.chmod(candidate, 0o700)
            os.chdir(candidate)
            return candidate
        except Exception as exc:
            last_error = f"{candidate}: {exc}"
    raise RuntimeError(f"no writable GPIO workdir available: {last_error}")


def audio_env():
    env = os.environ.copy()
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if os.path.isdir(runtime_dir):
        env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
        pulse_socket = os.path.join(runtime_dir, "pulse", "native")
        if os.path.exists(pulse_socket):
            env.setdefault("PULSE_SERVER", f"unix:{pulse_socket}")
    return env


def sample_envelope(index, total):
    if total <= 1:
        return 1.0
    attack = min(int(SAMPLE_RATE * 0.012), max(1, total // 4))
    release = min(int(SAMPLE_RATE * 0.018), max(1, total // 4))
    if index < attack:
        return index / attack
    if index >= total - release:
        return max(0.0, (total - index - 1) / release)
    return 1.0


def render_wave(path, pattern, volume):
    amplitude = int(32767 * clamp(volume * AUDIO_GAIN, 0.0, 1.0))
    with wave.open(path, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for frequency, duration, pause in pattern:
            tone_samples = max(1, int(SAMPLE_RATE * duration))
            frames = bytearray()
            for index in range(tone_samples):
                envelope = sample_envelope(index, tone_samples)
                sample = int(amplitude * envelope * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)) if frequency > 0 else 0
                frames.extend(struct.pack("<h", sample) * CHANNELS)
            wav.writeframes(frames)
            pause_samples = int(SAMPLE_RATE * pause)
            if pause_samples > 0:
                wav.writeframes(b"\x00\x00" * CHANNELS * pause_samples)


def audio_commands(path, device):
    if shutil.which("paplay"):
        command = ["paplay"]
        if device:
            command.extend(["--device", device])
        command.append(path)
        yield "paplay", command
    if shutil.which("pw-play"):
        command = ["pw-play"]
        if device:
            command.extend(["--target", device])
        command.append(path)
        yield "pw-play", command
    if shutil.which("aplay"):
        command = ["aplay", "-q"]
        alsa_device = DEFAULT_ALSA_DEVICE or device
        if alsa_device:
            command.extend(["-D", alsa_device])
        command.append(path)
        yield "aplay", command


def play_audio_pattern(name, pattern, *, volume, device):
    if volume <= 0:
        return
    last_error = "no audio player found"
    with tempfile.NamedTemporaryFile(prefix=f"gway-sound-{name}-", suffix=".wav", delete=False) as handle:
        path = handle.name
    try:
        render_wave(path, pattern, volume)
        for backend_name, command in audio_commands(path, device):
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=audio_env(), check=False)
            if result.returncode == 0:
                log_backend(f"sound={name} backend={backend_name} device={device or 'default'} ok")
                return
            stderr = result.stderr.decode("utf-8", "replace").strip()
            last_error = f"{backend_name} exited {result.returncode}: {stderr}"
            log_backend(f"sound={name} backend={backend_name} device={device or 'default'} failed={last_error!r}")
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    raise RuntimeError(last_error)


def load_gpio():
    try:
        import RPi.GPIO as GPIO  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"RPi.GPIO unavailable: {exc}") from exc
    return GPIO


def gpio_ready_error():
    try:
        ensure_gpio_workdir()
    except Exception as exc:
        return f"GPIO workdir unavailable: {exc}"
    if not (os.path.exists("/dev/gpiomem") or os.path.exists("/dev/gpiochip0")):
        return "GPIO device node is missing"
    try:
        import RPi.GPIO  # type: ignore  # noqa: F401
    except Exception as exc:
        return f"RPi.GPIO unavailable: {exc}"
    return ""


def wait_for_gpio_ready(timeout_seconds):
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    last_error = gpio_ready_error()
    while last_error and time.monotonic() < deadline:
        time.sleep(0.15)
        last_error = gpio_ready_error()
    if last_error:
        raise RuntimeError(last_error)


def configure_gpio(GPIO, pin):
    GPIO.setwarnings(False)
    mode = GPIO.getmode()
    if mode is None:
        GPIO.setmode(GPIO.BCM)
    elif mode != GPIO.BCM:
        raise RuntimeError(f"different GPIO mode already active: {mode}")
    GPIO.setup(pin, GPIO.OUT)


def reset_gpio(GPIO, pin):
    try:
        GPIO.cleanup(pin)
    except Exception:
        pass


def play_tone(GPIO, pin, frequency, duration, volume):
    duty = clamp(volume, 0.0, 1.0) * MAX_DUTY_CYCLE
    if duty <= 0 or frequency <= 0 or duration <= 0:
        time.sleep(max(0.0, duration))
        return
    pwm = GPIO.PWM(pin, int(round(frequency)))
    pwm.start(0)
    try:
        attack = min(0.012, duration / 4)
        release = min(0.018, duration / 4)
        sustain = max(0.0, duration - attack - release)
        for step in range(1, 5):
            pwm.ChangeDutyCycle(duty * step / 4)
            time.sleep(attack / 4)
        if sustain > 0:
            time.sleep(sustain)
        for step in range(3, -1, -1):
            pwm.ChangeDutyCycle(duty * step / 4)
            time.sleep(release / 4)
    finally:
        pwm.stop()


def play_gpio_pattern(name, *, pin, volume):
    workdir = ensure_gpio_workdir()
    wait_for_gpio_ready(GPIO_WAIT_SECONDS)
    GPIO = load_gpio()
    try:
        configure_gpio(GPIO, pin)
        for frequency, duration, pause in PATTERNS[name]:
            play_tone(GPIO, pin, frequency, duration, volume)
            if pause > 0:
                time.sleep(pause)
    finally:
        reset_gpio(GPIO, pin)


def play_pattern(name, *, pin, volume, backend, device, dry_run=False):
    if name not in PATTERNS:
        raise RuntimeError(f"unknown sound: {name}")
    pattern = PATTERNS[name]
    if dry_run:
        steps = " ".join(f"{freq}Hz/{duration * 1000:.0f}ms" for freq, duration, _pause in pattern)
        print(f"{name}: {DESCRIPTIONS.get(name, 'source motif')} - {steps} backend={backend} device={device or 'default'}")
        return
    if backend == "auto":
        backend = "gpio"
    if backend == "gpio" and gpio_muted():
        log_backend(f"sound={name} backend=gpio muted flag={GPIO_MUTE_FILE}")
        return
    if backend == "audio":
        try:
            play_audio_pattern(name, pattern, volume=volume, device=device)
            return
        except Exception as exc:
            log_backend(f"sound={name} backend=audio failed={exc!r}")
            raise
    mark_noise_alarm_suppressed(name, backend, pattern)
    play_gpio_pattern(name, pin=pin, volume=volume)
    log_backend(f"sound={name} backend=gpio pin={pin} cwd={os.getcwd()} ok")



DEFAULT_EVENT_DB = os.environ.get(
    "GWAY_SOUND_EVENT_DB",
    os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                 "gway-sound", "events.sqlite3"),
)
# Source owns event names. The engine owns their audio mapping.
DEFAULT_EVENTS = (
    ("codex", "SessionStart", "notice"),
    ("codex", "UserPromptSubmit", "busy"),
    ("codex", "PermissionRequest", "attention"),
    ("codex", "PreCompact", "warning"),
    ("codex", "PostCompact", "notice"),
    ("codex", "SubagentStart", "busy"),
    ("codex", "SubagentStop", "notice"),
    ("codex", "Stop", "ok"),
    ("codex", "Interrupt", "warning"),
    ("ssh", "session-opened", "notice"),
    ("wifi", "connected", "ok"),
    ("gway-monitor", "bastion-ready", "ok"),
    ("gway-monitor", "bastion-failed", "error"),
    ("gway-monitor", "eth-connect", "ok"),
    ("gway-monitor", "eth-disconnect", "warning"),
    ("gway-monitor", "hdmi-connect", "notice"),
    ("gway-monitor", "hdmi-disconnect", "warning"),
    ("gway-monitor", "camera-connect", "notice"),
    ("gway-monitor", "camera-disconnect", "warning"),
    ("gway-monitor", "kindle-connect", "notice"),
    ("gway-monitor", "kindle-disconnect", "warning"),
    ("gway-monitor", "usb-peripheral", "notice"),
    ("gway-monitor", "usb-unknown", "attention"),
    ("gway-monitor", "usb-remove", "warning"),
    ("gway-monitor", "thermal-warm", "warning"),
    ("gway-monitor", "thermal-hot", "error"),
    ("gway-monitor", "thermal-critical", "critical"),
    ("gway-monitor", "repo-upgrade-complete-unknown", "notice"),
    ("gway-monitor", "ap-connect", "notice"),
    ("gway-monitor", "ap-disconnect", "warning"),
    ("gway-monitor", "wifi-connect", "ok"),
    ("gway-monitor", "wifi-disconnect", "warning"),
    ("gway-monitor", "eth0-connected", "ok"),
    ("gway-monitor", "eth0-disconnected", "warning"),
    ("gway-monitor", "hdmi-connected", "notice"),
    ("gway-monitor", "hdmi-disconnected", "warning"),
    ("gway-monitor", "camera-connect", "notice"),
    ("gway-monitor", "camera-disconnect", "warning"),
    ("gway-monitor", "bastion-insert", "ok"),
    ("gway-monitor", "bastion-remove", "warning"),
    ("gway-monitor", "bastion-result", "ok"),
    ("gway-monitor", "kindle-connect", "notice"),
    ("gway-monitor", "kindle-disconnect", "warning"),
    ("gway-monitor", "usb-connect", "attention"),
    ("gway-monitor", "usb-disconnect", "warning"),
    ("gway-monitor", "lcd-important", "attention"),
    ("gway-monitor", "lcd-external-change", "notice"),
    ("gway-monitor", "feedback-lock", "attention"),
    ("gway-monitor", "repo-upgrade-start", "busy"),
    ("gway-monitor", "repo-upgrade-complete", "ok"),
    ("gway-monitor", "repo-upgrade-failed", "error"),
    ("gway-monitor", "thermal", "warning"),
    ("gway-monitor", "undervoltage", "undervoltage"),
    ("hotplug", "bastion-insert", "notice"),
    ("hotplug", "bastion-remove", "warning"),
    ("wifi", "disconnected", "warning"),
    ("hotplug", "unknown", "attention"),
    ("github-actions", "started", "notice"),
    ("github-actions", "stopped", "warning"),
    ("github-actions", "job-started", "notice"),
    ("github-actions", "job-completed", "notice"),
)


def event_database(path=DEFAULT_EVENT_DB):
    """Open private SQLite mapping; seed only on first creation."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if os.stat(directory).st_mode & 0o077:
        raise PermissionError("sound event directory must be private")
    if os.path.islink(path):
        raise ValueError("sound event database must not be symlinked")
    created = not os.path.exists(path)
    connection = sqlite3.connect(path, timeout=5)
    if created:
        os.chmod(path, 0o600)
    connection.execute("CREATE TABLE IF NOT EXISTS events (source TEXT NOT NULL, event TEXT NOT NULL, sound TEXT NOT NULL, PRIMARY KEY(source, event))")
    connection.execute("CREATE TABLE IF NOT EXISTS aliases (source TEXT NOT NULL, alias TEXT NOT NULL, event TEXT NOT NULL, PRIMARY KEY(source, alias))")
    connection.execute("CREATE TABLE IF NOT EXISTS motifs (source TEXT PRIMARY KEY, notes TEXT NOT NULL, cooldown_seconds REAL NOT NULL DEFAULT 45)")
    connection.execute("CREATE TABLE IF NOT EXISTS sounds (name TEXT PRIMARY KEY, notes TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS motif_context (slot INTEGER PRIMARY KEY CHECK(slot=1), source TEXT NOT NULL, played_at REAL NOT NULL)")
    if created:
        connection.executemany("INSERT OR IGNORE INTO events VALUES (?, ?, ?)", DEFAULT_EVENTS)
    # Idempotent seed also applies to databases created by S1.
    connection.executemany("INSERT OR IGNORE INTO events(source,event,sound) VALUES (?,?,?)", DEFAULT_EVENTS)
    connection.executemany(
        "INSERT OR IGNORE INTO motifs(source,notes,cooldown_seconds) VALUES (?,?,?)",
        (
            ("codex", json.dumps([[659, 0.07, 0.04], [988, 0.09, 0.0]]), 45),
            ("gway-monitor", json.dumps([[330, 0.055, 0.025], [494, 0.055, 0.025], [659, 0.085, 0.0]]), 45),
            ("ssh", json.dumps([[440, 0.06, 0.035], [659, 0.08, 0.0]]), 60),
            ("wifi", json.dumps([[523, 0.06, 0.035], [784, 0.06, 0.0]]), 45),
            ("github", json.dumps([[392, 0.06, 0.025], [587, 0.07, 0.025], [784, 0.10, 0.0]]), 45),
        ),
    )
    # Preserve an existing customized Actions motif when upgrading its identity.
    legacy = connection.execute("SELECT notes, cooldown_seconds FROM motifs WHERE source='github-actions'").fetchone()
    if legacy:
        default_github = (json.dumps([[392, 0.06, 0.025], [587, 0.07, 0.025], [784, 0.10, 0.0]]), 45)
        current_github = connection.execute("SELECT notes, cooldown_seconds FROM motifs WHERE source='github'").fetchone()
        if current_github == default_github:
            connection.execute("UPDATE motifs SET notes=?, cooldown_seconds=? WHERE source='github'", legacy)
        connection.execute("DELETE FROM motifs WHERE source='github-actions'")
    connection.commit()
    return connection


def custom_pattern(name, db):
    row = db.execute("SELECT notes FROM sounds WHERE name=?", (name,)).fetchone()
    if not row:
        return None
    try:
        pattern = tuple((float(hz), float(duration), float(pause)) for hz, duration, pause in json.loads(row[0]))
        if not pattern or len(pattern) > 12 or any(
            not math.isfinite(hz) or not math.isfinite(duration) or not math.isfinite(pause)
            or (hz != 0 and not 80 <= hz <= 4000)
            or not 0.01 <= duration <= 0.4 or not 0 <= pause <= 0.4
            for hz,duration,pause in pattern
        ):
            raise ValueError("invalid custom pattern")
        return pattern
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid custom sound") from exc


def play_custom(name, pattern, args):
    private = "__custom_preview__"
    PATTERNS[private] = pattern
    try:
        play_pattern(private, pin=args.pin, volume=args.volume,
                     backend=args.backend, device=args.device, dry_run=args.dry_run)
    finally:
        PATTERNS.pop(private, None)


def resolve_event(source, event, db):
    """Explicit source mapping, then global mapping; aliases are source-scoped."""
    source = (source or "").strip().lower()
    event = event.strip()
    if not event:
        raise ValueError("event cannot be empty")
    if not source:
        source = "*"
    # A per-source alias is looked up first. Global aliases are fallback.
    for owner in (source, "*"):
        row = db.execute("SELECT event FROM aliases WHERE source=? AND alias=?",
                         (owner, event)).fetchone()
        if row:
            event = row[0]
            break
    for owner in (source, "*"):
        row = db.execute("SELECT sound FROM events WHERE source=? AND event=?",
                         (owner, event)).fetchone()
        if row:
            if row[0] not in PATTERNS and custom_pattern(row[0], db) is None:
                raise ValueError("event maps to an unavailable sound")
            return {"source": source, "event": event, "sound": row[0],
                    "matched_source": owner}
    return {"source": source, "event": event, "sound": None,
            "matched_source": None}



def motif_identity(source):
    source = (source or "").strip().lower()
    return "github" if source == "github" or source.startswith("github-") else source


def motif_for(source, db):
    source = motif_identity(source)
    row = db.execute("SELECT notes, cooldown_seconds FROM motifs WHERE source=?", (source,)).fetchone()
    if not row:
        return None
    notes, cooldown = row
    try:
        pattern = validate_motif_notes(json.loads(notes))
        cooldown = validate_cooldown(cooldown)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid motif definition") from exc
    return pattern, cooldown


def play_event(resolved, args):
    """Serialize source motif and event as one unit; commit context after motif playback."""
    if resolved["sound"] is None:
        return
    source = motif_identity(resolved["source"])
    db_path = os.path.abspath(args.event_db)
    lock_path = os.path.join(os.path.dirname(db_path), "motif-play.lock")
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with event_database(db_path) as db:
            motif = motif_for(source, db)
            previous = db.execute("SELECT source, played_at FROM motif_context WHERE slot=1").fetchone()
            now = time.time()
            announce = bool(motif and (
                previous is None or previous[0] != source or
                now - previous[1] >= motif[1] or now < previous[1]
            ))
            if announce and not args.dry_run and not (args.backend in ("gpio", "auto") and gpio_muted()):
                # Reuse the same playback backend; the motif is not part of public earcon vocabulary.
                private_name = "__source_motif__"
                PATTERNS[private_name] = motif[0]
                try:
                    play_pattern(private_name, pin=args.pin, volume=args.volume,
                                 backend=args.backend, device=args.device)
                finally:
                    PATTERNS.pop(private_name, None)
                db.execute(
                    "INSERT INTO motif_context(slot,source,played_at) VALUES (1,?,?) "
                    "ON CONFLICT(slot) DO UPDATE SET source=excluded.source, played_at=excluded.played_at",
                    (source, time.time()),
                )
                db.commit()
            if args.dry_run:
                print(json.dumps({"source": source, "event": resolved["event"],
                                  "motif": announce, "sound": resolved["sound"]}, sort_keys=True))
            else:
                custom = custom_pattern(resolved["sound"], db)
                if custom is not None:
                    play_custom(resolved["sound"], custom, args)
                else:
                    play_pattern(resolved["sound"], pin=args.pin, volume=args.volume,
                                 backend=args.backend, device=args.device)


def list_sounds():
    for name in PATTERNS:
        print(f"{name:<9} {DESCRIPTIONS[name]}")



# All motif operations share the same bounds as ephemeral sound patterns.
BUILTIN_MOTIFS = frozenset({"codex", "gway-monitor", "ssh", "wifi", "github"})


def validate_motif_notes(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise ValueError("notes must be an array of 1 to 12 triples")
    pattern = []
    for note in raw:
        if not isinstance(note, (list, tuple)) or len(note) != 3:
            raise ValueError("each note must contain frequency, duration and pause")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in note):
            raise ValueError("note values must be numbers")
        hz, duration, pause = map(float, note)
        if not all(map(math.isfinite, (hz, duration, pause))):
            raise ValueError("note values must be finite")
        if (hz != 0 and not 80 <= hz <= 4000) or not 0.01 <= duration <= 0.4 or not 0 <= pause <= 0.4:
            raise ValueError("note outside supported frequency/duration/pause bounds")
        pattern.append((hz, duration, pause))
    return tuple(pattern)


def validate_cooldown(value):
    cooldown = float(value)
    if not math.isfinite(cooldown) or not 0 <= cooldown <= 3600:
        raise ValueError("cooldown must be finite and between 0 and 3600 seconds")
    return cooldown


def validate_motif_source(source):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", source or ""):
        raise ValueError("source must be lowercase ASCII letters, digits or hyphens, starting with a letter")
    if motif_identity(source) != source:
        raise ValueError("source is an alias of the shared github motif")
    return source


def motif_command(argv):
    parser = argparse.ArgumentParser(prog="sound motif")
    parser.add_argument("action", choices=("preview", "validate", "show", "list", "set", "remove"))
    parser.add_argument("source", nargs="?")
    parser.add_argument("--notes", help="JSON array of [Hz, seconds, pause] triples")
    parser.add_argument("--cooldown-seconds", type=float)
    parser.add_argument("--event-db", default=DEFAULT_EVENT_DB)
    parser.add_argument("--backend", choices=("auto", "audio", "gpio"), default=DEFAULT_BACKEND)
    parser.add_argument("--volume", type=float, default=0.42)
    parser.add_argument("--device", default=DEFAULT_AUDIO_DEVICE)
    parser.add_argument("--pin", type=int, default=DEFAULT_PIN)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action in ("preview", "validate", "set"):
            if args.notes is None:
                raise ValueError("--notes is required")
            notes = validate_motif_notes(json.loads(args.notes))
        elif args.notes is not None:
            raise ValueError("--notes is not valid for this action")
        if args.action in ("validate", "set"):
            if args.cooldown_seconds is None:
                raise ValueError("--cooldown-seconds is required")
            cooldown = validate_cooldown(args.cooldown_seconds)
        elif args.cooldown_seconds is not None:
            raise ValueError("--cooldown-seconds is only valid for validate/set")
        if args.action in ("set", "show", "remove"):
            validate_motif_source(args.source)
        elif args.source is not None:
            raise ValueError("source is only valid for set/show/remove")
        if args.action != "preview" and (args.dry_run or args.backend != DEFAULT_BACKEND or args.volume != 0.42):
            raise ValueError("playback options are only valid for preview")
        if args.action == "validate":
            print(json.dumps({"valid": True, "notes": [list(n) for n in notes], "cooldown_seconds": cooldown}, sort_keys=True))
            return 0
        if args.action == "preview":
            play_custom("preview", notes, args)
            return 0
        db_path = os.path.abspath(args.event_db)
        # Serialize modifications against motif playback and other motif writers.
        directory = os.path.dirname(db_path)
        if args.action in ("set", "remove"):
            os.makedirs(directory, mode=0o700, exist_ok=True)
            if os.stat(directory).st_mode & 0o077:
                raise PermissionError("sound event directory must be private")
            lock_path = os.path.join(directory, "motif-play.lock")
            if os.path.islink(lock_path):
                raise ValueError("motif lock must not be symlinked")
            with open(lock_path, "a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with event_database(db_path) as db:
                    if args.action == "set":
                        db.execute("INSERT INTO motifs(source,notes,cooldown_seconds) VALUES (?,?,?) "
                                   "ON CONFLICT(source) DO UPDATE SET notes=excluded.notes, cooldown_seconds=excluded.cooldown_seconds",
                                   (args.source, json.dumps(notes), cooldown))
                        result = {"source": args.source, "notes": [list(n) for n in notes], "cooldown_seconds": cooldown}
                    else:
                        if args.source in BUILTIN_MOTIFS:
                            raise ValueError("built-in motifs cannot be removed")
                        deleted = db.execute("DELETE FROM motifs WHERE source=?", (args.source,)).rowcount
                        if not deleted:
                            raise ValueError("motif does not exist")
                        result = {"source": args.source, "removed": True}
                    db.commit()
        else:
            with event_database(db_path) as db:
                if args.action == "list":
                    result = [{"source": row[0], "notes": json.loads(row[1]), "cooldown_seconds": row[2]}
                              for row in db.execute("SELECT source,notes,cooldown_seconds FROM motifs ORDER BY source")]
                else:
                    row = db.execute("SELECT notes,cooldown_seconds FROM motifs WHERE source=?", (args.source,)).fetchone()
                    if row is None:
                        raise ValueError("motif does not exist")
                    result = {"source": args.source, "notes": json.loads(row[0]), "cooldown_seconds": row[1]}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, TypeError, sqlite3.Error, OSError) as exc:
        parser.error(str(exc))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="sound.sh",
        description="GPIO earcon vocabulary for this host.",
    )
    parser.add_argument(
        "sound",
        nargs="?",
        default="list",
        help="sound name, list, all, or test",
    )
    parser.add_argument("--pattern-json", help="Internal: preview a validated JSON pattern without saving")
    parser.add_argument("--motif", help="Explicit motif to play before a sound; bypasses event cooldown")
    parser.add_argument("--list-motifs", action="store_true", help="Print installed motif names as JSON")
    parser.add_argument("--event", help="Producer-owned event name")
    parser.add_argument("--source", help="Producer identity for event lookup")
    parser.add_argument("--resolve", action="store_true", help="Print event resolution as JSON without playback")
    parser.add_argument("--event-db", default=DEFAULT_EVENT_DB, help="SQLite event mapping path")
    parser.add_argument("--pin", type=int, default=DEFAULT_PIN, help="BCM GPIO pin, default 18")
    parser.add_argument("--volume", type=float, default=0.42, help="0.0-1.0, default 0.42")
    parser.add_argument("--pause", type=float, default=0.35, help="pause between sounds for all/test")
    parser.add_argument("--backend", choices=("auto", "audio", "gpio"), default=DEFAULT_BACKEND, help="playback backend; normal earcons use gpio")
    parser.add_argument("--device", default=DEFAULT_AUDIO_DEVICE, help="PulseAudio/PipeWire sink or ALSA device")
    parser.add_argument("--dry-run", action="store_true", help="print patterns without playing")
    return parser


def main(argv):
    parser = build_parser()
    if argv and argv[0] == "motif":
        return motif_command(argv[1:])
    args = parser.parse_args(argv)
    args.volume = clamp(args.volume, 0.0, 1.0)
    args.pause = clamp(args.pause, 0.0, 3.0)
    args.backend = (args.backend or "auto").strip().lower()
    if args.pattern_json:
        if args.event or args.motif or args.resolve:
            parser.error("--pattern-json cannot be combined with event or motif playback")
        try:
            raw = json.loads(args.pattern_json)
            pattern = tuple((float(a),float(b),float(c)) for a,b,c in raw)
            if not pattern or len(pattern)>12 or any(
                not all(math.isfinite(v) for v in note)
                or (note[0]!=0 and not 80<=note[0]<=4000)
                or not 0.01<=note[1]<=0.4 or not 0<=note[2]<=0.4
                for note in pattern
            ):
                raise ValueError("invalid preview notes")
            play_custom("preview", pattern, args)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        return 0
    if args.list_motifs:
        if args.event or args.motif or args.sound != "list":
            parser.error("--list-motifs cannot be combined with playback")
        with event_database(args.event_db) as db:
            print(json.dumps([row[0] for row in db.execute("SELECT source FROM motifs ORDER BY source")]))
        return 0
    if args.motif and args.event:
        parser.error("--motif is only for direct sound playback")
    if args.resolve and not args.event:
        parser.error("--resolve requires --event")
    if args.source and not args.event:
        parser.error("--source requires --event")
    if args.event:
        try:
            with event_database(args.event_db) as db:
                resolved = resolve_event(args.source, args.event, db)
        except (sqlite3.Error, ValueError, OSError) as exc:
            parser.error(f"cannot resolve event: {exc}")
        if args.resolve:
            print(json.dumps(resolved, sort_keys=True))
            return 0
        if resolved["sound"] is None:
            # Unknown events stay silent, not an implicit 'ok' beep.
            return 0
        play_event(resolved, args)
        return 0
    else:
        requested = args.sound.strip().lower().replace("_", "-")

    if requested in {"list", "ls"}:
        list_sounds()
        return 0
    if requested in {"all", "test", "demo"}:
        for name in PATTERNS:
            print(name, flush=True)
            play_pattern(name, pin=args.pin, volume=args.volume, backend=args.backend, device=args.device, dry_run=args.dry_run)
            if not args.dry_run and args.pause > 0:
                time.sleep(args.pause)
        return 0
    with event_database(args.event_db) as db:
        custom = custom_pattern(requested, db)
    if requested not in PATTERNS and custom is None:
        parser.error(f"unknown sound: {requested}")
    if args.motif:
        with event_database(args.event_db) as db:
            motif = motif_for(args.motif, db)
            if motif is None:
                parser.error("unknown motif")
        db_path = os.path.abspath(args.event_db)
        lock_path = os.path.join(os.path.dirname(db_path), "motif-play.lock")
        with open(lock_path, "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            private_name = "__manual_motif__"
            PATTERNS[private_name] = motif[0]
            try:
                play_pattern(private_name, pin=args.pin, volume=args.volume,
                             backend=args.backend, device=args.device, dry_run=args.dry_run)
                (play_custom(requested, custom, args) if custom is not None else
                 play_pattern(requested, pin=args.pin, volume=args.volume,
                              backend=args.backend, device=args.device, dry_run=args.dry_run))
            finally:
                PATTERNS.pop(private_name, None)
    else:
        if custom is not None:
            play_custom(requested, custom, args)
        else:
            play_pattern(requested, pin=args.pin, volume=args.volume, backend=args.backend, device=args.device, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
PY
status=$?
cleanup_gpio
trap - EXIT
exit "$status"
