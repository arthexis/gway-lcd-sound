"""Optional, per-user, authenticated server-to-Watchtower LCD/Sound route.

No Watchtower SSH credentials, custom endpoint, redirects, proxy, or fallback.
The source identity is claimed only for per-source policy matching: Watchtower's
bearer verifier independently binds it to a privileged operator grant.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import urllib.request
import urllib.error

URL = "https://remote.arthexis.com/v1/lcd-sound/event"
SOURCE_CONFIG = Path.home() / ".config/gway-lcd-sound/server-source.json"
MAX_BYTES = 2048
ORIGINS = frozenset(("ocpp-abb-1", "gelectriic.com"))


def _private_file(path):
    path = Path(path)
    parent = path.parent
    if not path.is_absolute() or ".." in path.parts or parent.is_symlink():
        raise PermissionError("untrusted source credential location")
    directory = parent.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077):
        raise PermissionError("source configuration directory not private")
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > MAX_BYTES):
        raise PermissionError("unsafe source configuration or token")
    return path.read_text(encoding="utf-8")


def load(path=SOURCE_CONFIG):
    """None means incumbent pinned route; malformed opt-in MUST fail closed."""
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    data = json.loads(_private_file(path))
    if type(data) is not dict or set(data) != {"schema", "origin", "url", "token_file"}:
        raise ValueError("invalid server source configuration")
    if (type(data["schema"]) is not int or data["schema"] != 1
            or data["origin"] not in ORIGINS or data["url"] != URL
            or type(data["token_file"]) is not str):
        raise ValueError("unapproved server source route")
    expected = path.parent / "server-source.token"
    if Path(data["token_file"]) != expected:
        raise PermissionError("unapproved source credential path")
    token = _private_file(expected).strip()
    if not re.fullmatch(r"gwr_[0-9a-f]{24}_[A-Za-z0-9_-]{20,128}", token):
        raise PermissionError("invalid source credential")
    return {"origin": data["origin"], "url": URL, "token": token}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def dispatch(event, *, config=None, opener=None):
    """Single bounded HTTPS call; never retry an uncertain hardware effect."""
    config = load() if config is None else config
    if type(config) is not dict or config.get("url") != URL:
        raise PermissionError("server source forwarding not configured")
    if event.get("origin") != config.get("origin"):
        raise PermissionError("source identity mismatch")
    raw = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > 8192:
        raise ValueError("event too large")
    request = urllib.request.Request(
        URL, raw, method="POST",
        headers={"Authorization": "Bearer " + config["token"],
                 "Content-Type": "application/json"})
    # No environment-specified HTTP proxy, no redirect, system-trusted TLS CA.
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=16) as response:
            code = response.status
            body = response.read(8193)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RuntimeError("authenticated source forwarding refused") from None
    except (OSError, urllib.error.URLError):
        raise RuntimeError("remote source outcome unverified") from None
    if len(body) > 8192 or code not in (200, 202, 502):
        raise RuntimeError("invalid source forwarding acknowledgment")
    result = json.loads(body)
    if (type(result) is not dict or result.get("node") != event["node"]
            or result.get("request_id") != event["request_id"]
            or result.get("source") != config["origin"]):
        raise RuntimeError("incorrect source forwarding acknowledgment")
    if code != 200 or result.get("status") != "succeeded":
        raise RuntimeError("remote source delivery failed or uncertain")
    return result
