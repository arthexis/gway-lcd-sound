"""Bounded, identity-preserving operational notices for the LCD1602.

The transport authorizes the *producer*. This module validates only data and
owns the receiver's private lockfiles; it never executes user-controlled text
or plays sound. Audio is emitted once by the durable producer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata

from .model import Payload

SCHEMA = "gway-notification/v1"
MAX_BYTES = 4096
MAX_ACTIVE = 32
MAX_PAGES = 8
PREFIX = "lcd-notice-"
NODE = re.compile(r"(?:gway-[0-9]{3,}|ocpp-abb-1|gelectriic\.com)\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]{1,64}/[A-Za-z0-9_.-]{1,100}\Z")
SERVICE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")
EPISODE = re.compile(r"[A-Za-z0-9:_-]{1,80}\Z")
REASON = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")

STATES = {
    "agentops": {"finished": "important", "codex_failed": "error",
                 "interrupted": "error"},
    "fleet": {"down": "critical", "unreachable": "error",
              "degraded": "error", "recovered": "important"},
    "deploy": {"deploy-started": "info", "deploy-activated": "info",
               "deploy-skipped": "important", "deploy-verified": "important",
               "deploy-failed": "error", "rollback-started": "important",
               "rollback-verified": "important", "rollback-failed": "critical"},
}
LABELS = {
    "finished": "DONE", "codex_failed": "FAILED", "interrupted": "BLOCKED",
    "down": "DOWN", "unreachable": "UNREACHABLE", "degraded": "DEGRADED",
    "recovered": "RECOVERED", "deploy-started": "STARTED",
    "deploy-activated": "ACTIVATED", "deploy-skipped": "SKIPPED",
    "deploy-verified": "VERIFIED", "deploy-failed": "FAILED",
    "rollback-started": "RB START", "rollback-verified": "RB OK",
    "rollback-failed": "RB FAILED",
}
PRIORITY = {"critical": 0, "error": 1, "important": 2, "info": 3}


def valid_notice(doc):
    if (type(doc) is not dict or set(doc) != {
        "schema", "system", "origin_node", "target_node", "subject",
        "state", "severity", "reason_code", "episode_id", "expires_in"
    } or doc["schema"] != SCHEMA):
        raise ValueError("invalid notification schema")
    system = doc["system"]
    if type(system) is not str or system not in STATES:
        raise ValueError("invalid notification system")
    if (type(doc["state"]) is not str or doc["state"] not in STATES[system]
            or doc["severity"] != STATES[system][doc["state"]]):
        raise ValueError("inconsistent notification state/severity")
    if any(type(doc[key]) is not str or not NODE.fullmatch(doc[key])
           for key in ("origin_node", "target_node")):
        raise ValueError("invalid notification node")
    if (type(doc["episode_id"]) is not str or
            not EPISODE.fullmatch(doc["episode_id"])):
        raise ValueError("invalid episode identity")
    if (type(doc["reason_code"]) is not str or
            not REASON.fullmatch(doc["reason_code"])):
        raise ValueError("invalid reason code")
    if type(doc["expires_in"]) is not int or not 5 <= doc["expires_in"] <= 300:
        raise ValueError("invalid notification lifetime")
    subject = doc["subject"]
    if type(subject) is not dict:
        raise ValueError("invalid notification subject")
    if system == "agentops":
        if (set(subject) != {"type", "repository", "number"} or
                subject["type"] != "github_issue" or
                type(subject["repository"]) is not str or
                not REPO.fullmatch(subject["repository"]) or
                type(subject["number"]) is not int or
                not 1 <= subject["number"] <= 999999999):
            raise ValueError("invalid GitHub issue subject")
    elif system == "deploy":
        if (set(subject) != {"type", "repository"} or
                subject["type"] != "repository" or
                type(subject["repository"]) is not str or
                not REPO.fullmatch(subject["repository"])):
            raise ValueError("invalid deployment subject")
    else:
        if (set(subject) != {"type", "name"} or
                subject["type"] != "service" or
                type(subject["name"]) is not str or
                not SERVICE.fullmatch(subject["name"])):
            raise ValueError("invalid service subject")
    if len(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()) > MAX_BYTES:
        raise ValueError("notification over size budget")
    return doc


def parse_notice(raw):
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("notification over size budget")
    return valid_notice(json.loads(raw))


def node_code(node):
    if node.startswith("gway-"):
        return node.split("-")[-1]
    return "ABB1" if node == "ocpp-abb-1" else "WT"


def _ascii(value):
    text = unicodedata.normalize("NFKD", value)
    return "".join(c for c in text if 32 <= ord(c) <= 126)


def render(doc):
    """Grouped pages: identity -> evidence -> full unambiguous repository."""
    valid_notice(doc)
    system, subject, state = doc["system"], doc["subject"], doc["state"]
    prefix = {"agentops": "AGT@", "fleet": "FLT>", "deploy": "DEP>"}[system]
    node = doc["origin_node"] if system == "agentops" else doc["target_node"]
    headline = prefix + node_code(node) + " " + LABELS[state]
    name = (subject["name"] if system == "fleet" else
            subject["repository"].split("/", 1)[1])
    pages = [(headline[:16], _ascii(name)[:16])]
    if system == "agentops":
        second = "ISSUE #" + str(subject["number"])
    elif system == "fleet":
        second = "MONITOR: " + node_code(doc["origin_node"])
    else:
        second = "DEP " + doc["episode_id"][:8]
    reason = _ascii(doc["reason_code"].replace("_", " "))
    pages.append((second[:16], reason[:16]))
    if len(reason) > 16:
        for i in range(16, len(reason), 16):
            pages.append(("REASON CONT", reason[i:i + 16]))
    if system != "fleet":
        repository = _ascii(subject["repository"])
        if len(repository) > 16:
            chunks = [repository[i:i + 16] for i in range(0, len(repository), 16)]
            for i, piece in enumerate(chunks):
                pages.append((f"REPO {i+1}/{len(chunks)}", piece))
    if len(pages) > MAX_PAGES or any(len(a) > 16 or len(b) > 16 for a, b in pages):
        raise ValueError("too many notification display pages")
    return pages


def _identity(doc):
    subject = doc["subject"]
    item = (f"{subject['repository']}#{subject['number']}"
            if doc["system"] == "agentops"
            else subject.get("repository", subject.get("name")))
    return "\n".join([doc["system"], doc["origin_node"], doc["target_node"],
                      item, doc["episode_id"]])


def _datetime(raw):
    if type(raw) is not str:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def store_notice(root, doc, *, now=None):
    now = now or datetime.now(timezone.utc)
    valid_notice(doc)
    render(doc)  # Enforce page count before committing any state.
    root = Path(root)
    if root.is_symlink():
        raise PermissionError("unsafe notification directory")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    key = hashlib.sha256(_identity(doc).encode()).hexdigest()[:32]
    path = root / (PREFIX + key + ".json")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PermissionError("unsafe notification target")
    # Keep at most 32 active episodes and prune expired owned regular files.
    active = 0
    for entry in list(root.glob(PREFIX + "*.json"))[:256]:
        try:
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                continue
            record = json.loads(entry.read_text(encoding="utf-8")[:MAX_BYTES + 1])
            expiry = _datetime(record.get("expires_at"))
            if expiry is None or expiry <= now:
                entry.unlink()
            elif entry != path:
                active += 1
        except (OSError, ValueError, TypeError):
            continue
    if active >= MAX_ACTIVE and not path.exists():
        raise ValueError("notification capacity exceeded")
    record = {"schema": 1, "notice": doc,
              "expires_at": (now + timedelta(seconds=doc["expires_in"])).isoformat()}
    data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("stored notification exceeds budget")
    fd, temporary = tempfile.mkstemp(dir=root, prefix=".lcd-notice-")
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def read_notices(lock_dirs, *, now=None):
    now = now or datetime.now(timezone.utc)
    found = []
    for root in lock_dirs:
        root = Path(root)
        if root.is_symlink():
            continue
        for path in sorted(root.glob(PREFIX + "*.json"))[:MAX_ACTIVE]:
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_size < 1:
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                if (type(record) is not dict or set(record) != {"schema", "notice", "expires_at"}
                        or record["schema"] != 1):
                    continue
                expiry = _datetime(record["expires_at"])
                if expiry is None or not now < expiry <= now + timedelta(seconds=301):
                    continue
                doc = valid_notice(record["notice"])
                found.append((PRIORITY[doc["severity"]], _identity(doc), doc, path))
            except (OSError, ValueError, TypeError):
                continue
    return sorted(found, key=lambda item: (item[0], item[1]))[:MAX_ACTIVE]


def current_payload(lock_dirs, *, now=None, monotonic=0.0):
    notices = read_notices(lock_dirs, now=now)
    if not notices:
        return None
    # All pages from one episode stay together, with fair rotation among
    # notices of the same severity; critical alerts outrank lower levels.
    best = notices[0][0]
    eligible = [item for item in notices if item[0] == best]
    page_sets = [(render(doc), path) for _rank, _key, doc, path in eligible]
    pages = [(page, path) for group, path in page_sets for page in group]
    (line1, line2), path = pages[int(monotonic // 5) % len(pages)]
    return Payload(line1, line2, label="notice-" + eligible[0][2]["severity"], source=path)
