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
                sample = int(amplitude * envelope * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
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
        print(f"{name}: {DESCRIPTIONS[name]} - {steps} backend={backend} device={device or 'default'}")
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


def list_sounds():
    for name in PATTERNS:
        print(f"{name:<9} {DESCRIPTIONS[name]}")


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
    parser.add_argument("--pin", type=int, default=DEFAULT_PIN, help="BCM GPIO pin, default 18")
    parser.add_argument("--volume", type=float, default=0.42, help="0.0-1.0, default 0.42")
    parser.add_argument("--pause", type=float, default=0.35, help="pause between sounds for all/test")
    parser.add_argument("--backend", choices=("auto", "audio", "gpio"), default=DEFAULT_BACKEND, help="playback backend; normal earcons use gpio")
    parser.add_argument("--device", default=DEFAULT_AUDIO_DEVICE, help="PulseAudio/PipeWire sink or ALSA device")
    parser.add_argument("--dry-run", action="store_true", help="print patterns without playing")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.volume = clamp(args.volume, 0.0, 1.0)
    args.pause = clamp(args.pause, 0.0, 3.0)
    args.backend = (args.backend or "auto").strip().lower()
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
    if requested not in PATTERNS:
        parser.error(f"unknown sound: {requested}")
    play_pattern(requested, pin=args.pin, volume=args.volume, backend=args.backend, device=args.device, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
PY
status=$?
cleanup_gpio
trap - EXIT
exit "$status"
