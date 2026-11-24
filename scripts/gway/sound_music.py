"""Bounded local RTTTL and SMF 0/1 parsing. No hardware or dependencies."""
import math
import os
import re
import stat
import struct
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 1024 * 1024
MAX_EVENTS = 20000
MAX_SECONDS = 300
MAX_TRACKS = 64


@dataclass(frozen=True)
class Music:
    kind: str
    pattern: tuple
    seconds: float
    tracks: int = 1
    midi_bytes: bytes = field(default=b"", repr=False)


def _tempo(value):
    if not math.isfinite(value) or not 0.25 <= value <= 4:
        raise ValueError("tempo multiplier must be between 0.25 and 4")
    return value


def _hz(note):
    return round(440 * 2 ** ((note - 69) / 12), 3)


def _finish(kind, pattern, tracks=1):
    seconds = sum(duration + pause for _, duration, pause in pattern)
    if not pattern or not 0 < seconds <= MAX_SECONDS or len(pattern) > MAX_EVENTS:
        raise ValueError("music duration or event count outside limits")
    return Music(kind, tuple(pattern), seconds, tracks)


def parse_rtttl(data, tempo=1.0):
    tempo = _tempo(tempo)
    try:
        name, defaults, notes = data.decode("ascii").strip().split(":")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("expected RTTTL name:defaults:notes") from exc
    if not name or len(name) > 64:
        raise ValueError("invalid RTTTL name")
    settings = dict(d=4, o=6, b=63)
    seen = set()
    if defaults.strip():
        for part in defaults.lower().split(","):
            match = re.fullmatch(r"\s*([dob])\s*=\s*(\d{1,3})\s*", part)
            if not match or match[1] in seen:
                raise ValueError("invalid RTTTL default")
            seen.add(match[1])
            settings[match[1]] = int(match[2])
    durations = (1, 2, 4, 8, 16, 32)
    if settings["d"] not in durations or not 4 <= settings["o"] <= 7 or not 25 <= settings["b"] <= 900:
        raise ValueError("invalid RTTTL duration, octave or tempo")
    pattern = []
    elapsed = 0
    for item in notes.lower().split(","):
        if len(pattern) >= MAX_EVENTS:
            raise ValueError("too many RTTTL notes")
        m = re.fullmatch(r"\s*(\d{1,2})?([a-gp])(#)?(\.)?([4-7])?(\.)?\s*", item)
        if not m or (m[4] and m[6]):
            raise ValueError("invalid RTTTL note")
        divisor = int(m[1] or settings["d"])
        if divisor not in durations or (m[2] == "p" and m[3]) or (m[3] and m[2] in "be"):
            raise ValueError("invalid RTTTL note")
        duration = 240 / settings["b"] / divisor / tempo * (1.5 if m[4] or m[6] else 1)
        octave = int(m[5] or settings["o"])
        freq = 0 if m[2] == "p" else _hz(12 * (octave + 1) + dict(c=0,d=2,e=4,f=5,g=7,a=9,b=11)[m[2]] + bool(m[3]))
        elapsed += duration
        if elapsed > MAX_SECONDS:
            raise ValueError("music exceeds duration limit")
        pattern.append((freq, duration, 0))
    return _finish("rtttl", pattern)


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError("truncated MIDI")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def byte(self):
        return self.take(1)[0]

    def vlq(self):
        value = 0
        for _ in range(4):
            byte = self.byte()
            value = (value << 7) | (byte & 127)
            if byte < 128:
                return value
        raise ValueError("invalid MIDI variable-length integer")


def parse_midi(data, track=None, tempo=1.0):
    tempo = _tempo(tempo)
    reader = Reader(data)
    if reader.take(4) != b"MThd":
        raise ValueError("missing MIDI header")
    size = int.from_bytes(reader.take(4), "big")
    if size != 6:
        raise ValueError("unsupported MIDI header")
    fmt, count, division = struct.unpack(">HHH", reader.take(size))
    if fmt not in (0, 1) or not 1 <= count <= MAX_TRACKS or (fmt == 0 and count != 1) or not 1 <= division < 32768:
        raise ValueError("unsupported MIDI format, track count or SMPTE timing")
    if track is not None and not 0 <= track < count:
        raise ValueError("MIDI track index out of range (zero-based)")
    events = []
    end_ticks = []
    total = 0
    for index in range(count):
        if reader.take(4) != b"MTrk":
            raise ValueError("missing MIDI track")
        tr = Reader(reader.take(int.from_bytes(reader.take(4), "big")))
        tick, running, ended = 0, None, False
        while tr.pos < len(tr.data):
            total += 1
            if total > MAX_EVENTS:
                raise ValueError("too many MIDI events")
            tick += tr.vlq()
            byte = tr.byte()
            first = None
            if byte < 128:
                if running is None:
                    raise ValueError("invalid MIDI running status")
                first, byte = byte, running
            if byte == 255:
                running = None
                kind = tr.byte()
                payload = tr.take(tr.vlq())
                if kind == 47:
                    if payload or tr.pos != len(tr.data):
                        raise ValueError("invalid MIDI end of track")
                    ended = True
                    break
                if kind == 81:
                    if len(payload) != 3 or not int.from_bytes(payload, "big"):
                        raise ValueError("invalid MIDI tempo")
                    events.append((tick, index, total, "tempo", int.from_bytes(payload, "big"), 0))
            elif byte in (240, 247):
                running = None
                tr.take(tr.vlq())
            elif 128 <= byte < 240:
                running = byte
                cmd, channel = byte >> 4, byte & 15
                values = ([] if first is None else [first])
                values.extend(tr.take((1 if cmd in (12, 13) else 2) - len(values)))
                if any(v >= 128 for v in values):
                    raise ValueError("invalid MIDI data byte")
                if cmd in (8, 9) and channel != 9 and (track is None or index == track):
                    events.append((tick, index, total, "on" if cmd == 9 and values[1] else "off", channel, values[0]))
            else:
                raise ValueError("unsupported MIDI event")
        if not ended:
            raise ValueError("missing MIDI end of track")
        end_ticks.append(tick)
    if reader.pos != len(data):
        raise ValueError("trailing MIDI data")
    end = max(end_ticks) if track is None else end_ticks[track]
    events.sort()
    active = defaultdict(int)
    pitch_counts = [0] * 128
    pattern = []
    prev, rate, elapsed = 0, 500000, 0.0
    def advance(tick):
        nonlocal prev, elapsed
        duration = (tick - prev) * rate / division / 1e6 / tempo
        elapsed += duration
        if elapsed > MAX_SECONDS:
            raise ValueError("music exceeds duration limit")
        if duration > 0:
            highest = next((pitch for pitch in range(127, -1, -1) if pitch_counts[pitch]), None)
            freq = 0 if highest is None else _hz(highest)
            if pattern and pattern[-1][0] == freq:
                pattern[-1] = (freq, pattern[-1][1] + duration, 0)
            else:
                pattern.append((freq, duration, 0))
        prev = tick
    for tick, index, _, kind, a, b in events:
        if tick > end:
            break
        advance(tick)
        if kind == "tempo":
            rate = a
        else:
            key = (index, a, b)
            if kind == "on":
                active[key] += 1
                pitch_counts[b] += 1
            elif active.get(key):
                active[key] -= 1
                pitch_counts[b] -= 1
                if not active[key]:
                    del active[key]
    advance(end)
    result = _finish("midi", pattern, count)
    return Music(result.kind, result.pattern, result.seconds, result.tracks, data)


def load_music(path, track=None, tempo=1.0):
    suffix = Path(path).suffix.lower()
    if suffix not in (".mid", ".midi", ".rtttl"):
        raise ValueError("expected .mid, .midi or .rtttl")
    # Nonblocking open plus fstat rejects pipes/devices before reading.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("music must be a regular file of at most 1 MiB")
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("music exceeds size limit")
    if suffix == ".rtttl":
        if track is not None:
            raise ValueError("--track requires MIDI")
        return parse_rtttl(data, tempo)
    return parse_midi(data, track, tempo)



def run_music_process(command, muted, timeout, *, env=None, output_path=None):
    """Bound external render/playback and stop promptly on mute.

    Return None for a muted/cancelled operation, otherwise the process exit
    code. The PCM cap leaves room for the synthesizer's release tail.
    """
    if muted():
        return None
    with subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
        deadline = time.monotonic() + timeout
        try:
            while True:
                if muted():
                    return None
                if output_path is not None:
                    try:
                        if os.stat(output_path).st_size > 80 * 1024 * 1024:
                            raise RuntimeError("rendered MIDI exceeds PCM size limit")
                    except FileNotFoundError:
                        pass
                if child.poll() is not None:
                    return child.returncode
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command[0], timeout)
                time.sleep(.05)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
