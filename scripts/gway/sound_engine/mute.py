"""Volatile mute state shared by sound playback and CLI; reboot clears it."""
import argparse
import fcntl
import json
import os
from pathlib import Path

def state_path():
    return legacy_paths()[0]

def legacy_paths():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return (
        Path(os.environ.get("NODE_SOUND_GPIO_MUTE_FILE") or os.environ.get("GWAY_SOUND_GPIO_MUTE_FILE") or f"{runtime}/gway-sound/gpio-muted"),
        Path(os.environ.get("CODEX_SOUND_HOOK_STATE_DIR", "/home/arthe/.local/state/codex-sound-hooks")) / "silent",
    )

def status():
    runtime_muted = state_path().exists()
    legacy_codex = legacy_paths()[1].exists()
    return {"muted": runtime_muted,
            "runtime_muted": runtime_muted,
            "legacy_codex_muted": legacy_codex}

def change(action):
    path = state_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise OSError("unsafe mute state path")
    lock = path.with_name("mute.lock")
    if lock.is_symlink():
        raise OSError("unsafe mute lock")
    with open(lock, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        old = status()["muted"]
        desired = not old if action == "toggle" else action == "mute"
        if desired:
            with open(path, "w") as out:
                out.write("muted\n")
            os.chmod(path, 0o600)
        else:
            path.unlink(missing_ok=True)
            # Remove legacy marker, but never let persistent Codex state mute playback.
            for legacy in legacy_paths():
                if legacy.is_symlink():
                    raise OSError("unsafe legacy mute marker")
                legacy.unlink(missing_ok=True)
        return status()

def main(argv=None):
    parser = argparse.ArgumentParser(prog="sound")
    parser.add_argument("action", choices=("status", "mute", "unmute", "toggle"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = status() if args.action == "status" else change(args.action)
    except OSError as exc:
        parser.exit(1, f"sound: {exc}\n")
    print(json.dumps(result, sort_keys=True) if args.json else ("muted" if result["muted"] else "unmuted"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
