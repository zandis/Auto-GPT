"""10K-5 (D-1381, the review of 48b3210c): what a support bundle made from the console's button may hold, by field.

Three reviews each found another free-text source that a leave-out list had missed, so the button's bundle is built
the other way round: every member is made here from an explicit list of allowed fields (:data:`SCHEMAS`), and every
allowed value is of a closed kind:

* a number (not a yes/no), a yes/no, or null;
* a time (:data:`TS`: an ISO date or date and time, nothing else);
* a value from a fixed set (:class:`OneOf`: the update steps and health checks the code writes, the error types known
  when this module is imported, the services of the vendor's compose files, states, levels, labels);
* a string matching a strict pattern declared next to the field (:class:`Like`: a sha256, a mode, a driver version, a
  label such as ``bundle-2`` or ``backup``).

Anything else, a key not on the list or a value not of its kind, is dropped and counted; the count is the MANIFEST's
``"<member>: N field(s) not on its allow-list"``. No free text, no path, no file name a person chose, no command line
and no command output travels: the commands' outputs are parsed here into the fields above and the text is thrown
away. The builder's line scan and last look still run over the result (``tools/support_bundle.py``), as a second
line; they are not the protection.

:func:`check` is the same lists read the other way: every value of a member that is not of its declared kind, used by
the tests on every member of a made bundle.
"""

from __future__ import annotations

import builtins
import functools
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------------ the kinds
@dataclass(frozen=True)
class Like:
    """A string that matches ``pattern`` whole."""

    pattern: re.Pattern[str]

    def ok(self, v: Any) -> bool:
        return isinstance(v, str) and self.pattern.fullmatch(v) is not None


@dataclass(frozen=True)
class OneOf:
    """A string from a fixed set."""

    values: frozenset[str]

    def ok(self, v: Any) -> bool:
        return isinstance(v, str) and v in self.values


class _Num:
    def ok(self, v: Any) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)


class _Bool:
    def ok(self, v: Any) -> bool:
        return isinstance(v, bool)


NUM, BOOL = _Num(), _Bool()
TS = Like(re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?)?", re.A))
SHA256 = Like(re.compile(r"[0-9a-f]{64}", re.A))
LENGTHS = OneOf(frozenset({"0", "1-99", "100-999", "1000+"}))
Kind = Any  # a leaf kind above, a dict of field -> kind (closed), or a one-element list [kind] (each item)


# ------------------------------------------------------------------------------------------------ the fixed sets
def _literals(path: Path, *patterns: str) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    return {m for p in patterns for m in re.findall(p, text)}


@functools.cache
def error_types() -> frozenset[str]:
    """The exception class names known when this module is imported: Python's own, the classes defined in the
    tools and libraries of this tree (by their ``class Name(...)`` lines) and the database driver's, when present."""
    names = {n for n, v in vars(builtins).items() if isinstance(v, type) and issubclass(v, BaseException)}
    for f in [*(ROOT / "tools").rglob("*.py"), *(ROOT / "libs").rglob("*.py")]:
        names |= _literals(f, r"(?m)^\s*class ([A-Z][A-Za-z]{2,60})\((?:[A-Za-z_.]*(?:Error|Exception|Failed|Refused|"
                              r"Exit|Interrupt|Warning))\)")  # fmt: skip
    try:
        import psycopg.errors as pe  # the box's database driver: UniqueViolation and its siblings
    except ImportError:
        pass
    else:
        names |= {n for n, v in vars(pe).items() if isinstance(v, type) and issubclass(v, BaseException)}
    return frozenset(n for n in names if re.fullmatch(r"[A-Z][A-Za-z]{2,60}", n))


class _Error:
    """An error's type: a name of :func:`error_types`, ``other`` or ``none``."""

    def ok(self, v: Any) -> bool:
        return isinstance(v, str) and (v in ("other", "none") or v in error_types())


ERROR = _Error()
_UPDATE = ROOT / "tools" / "trialbox" / "update.py"
#: the update steps ``tools/trialbox/update.py`` writes into the history (its string literals), and two forms of ours
STEPS = OneOf(frozenset(_literals(_UPDATE, r'\bstep\(\s*"([^"{}]+)"', r'_history\(\s*plan,\s*"([^"{}]+)"',
                                  r'\benter\(\s*"([^"{}]+)"')) | {"recover from step", "other"})  # fmt: skip
#: the health checks ``tb_common.metrics`` makes (its literals; ``disk:<path>`` is ``disk``)
CHECKS = OneOf(frozenset(_literals(ROOT / "libs" / "tb_common" / "metrics.py", r'Check\(\s*f?"([a-z_]+)')) | {"other"})
LEVELS = OneOf(frozenset({"ok", "warn", "red", "alert", "unknown"}))
#: every service of the vendor's compose files (their own service keys) and the builder's lists
_COMPOSE_KEY = r"(?m)^  ([a-z][a-z0-9-]{1,40}):\s*$"
SERVICES = OneOf(frozenset(n for f in sorted((ROOT / "deploy").glob("docker-compose*.y*ml"))
                           for n in _literals(f, _COMPOSE_KEY)) | {"other"})  # fmt: skip
STATES = OneOf(frozenset({"created", "running", "paused", "restarting", "removing", "exited", "dead", "other"}))
HEALTH = OneOf(frozenset({"healthy", "unhealthy", "starting", "none", "other"}))
BUNDLE = Like(re.compile(r"bundle-\d{1,3}|installed", re.A))
DISK = Like(re.compile(r"system|data|docker|deploy|backup(?:-\d{1,2})?|other-\d{1,2}", re.A))
#: the backup problems ``tools/trialbox/backup_schedule.status`` writes, as kinds (their words never travel)
PROBLEMS: tuple[tuple[str, str], ...] = (
    ("no backup target", "no_target"), ("no off-box backup target", "no_offbox_target"),
    ("no good backup on", "no_good_backup"), ("the newest good backup is dated in the future", "future_dated"),
    ("the newest good backup's file name", "times_disagree"), ("deploy/site/backup-last.json has no time", "no_time"),
    ("the newest good backup is", "too_old"), ("no alert route", "no_alert_route"),
    ("the last nightly backup at", "nightly_failed"), ("the last pgBackRest backup failed", "pgbackrest_failed"),
    ("the restore drill of", "drill_failed"), ("the database did not answer the WAL", "wal_no_answer"),
    ("WAL archiving is on in deploy/.env but", "wal_mode"), ("WAL archiving to pgBackRest is failing", "wal_failing"),
    ("no WAL archived for more than", "wal_stale"),
)  # fmt: skip
PROBLEM = OneOf(frozenset({k for _, k in PROBLEMS} | {"other"}))

#: the allowed fields of each member
SCHEMAS: dict[str, Kind] = {
    "ops-snapshot.json": {
        "at": TS, "box": OneOf(frozenset({"compose", "local"})),
        "version": {"trialbox": Like(re.compile(r"\d{1,4}(?:\.\d{1,4}){1,3}(?:[-+.][0-9a-z]{1,12}){0,3}", re.A)),
                    "bundle": BUNDLE, "applied_at": TS},
        "updates": [{"bundle": BUNDLE, "first": TS, "last": TS, "step": STEPS, "ok": BOOL, "steps": NUM,
                     "outcome": OneOf(frozenset({"applied", "rolled_back", "rollback_failed", "failed"})),
                     "detail_type": ERROR, "detail_length": LENGTHS}],
        "rollback_points": [{"bundle": BUNDLE, "images": NUM, "dumps_kept": NUM, "at": TS}],
        "incoming": [{"bytes": NUM, "at": TS}],
        "backups": {"targets": [{"label": DISK, "reachable": BOOL, "files": NUM, "newest": TS,
                                 "total": NUM, "used": NUM, "free": NUM}],
                    "newest": TS, "key": BOOL, "stale_hours": NUM},
        "secrets": [{"name": None, "present": BOOL, "age_days": NUM, "registered": BOOL,
                     "mode": Like(re.compile(r"0o[0-7]{3}", re.A))}],
        "logs": {"days": [{"day": TS, "files": NUM, "bytes": NUM}]},
        "disk": [{"label": DISK, "total": NUM, "used": NUM, "free": NUM}],
        "health": {"at": TS, "error": ERROR,
                   "backup": {"level": LEVELS, "age_hours": NUM, "max_age_hours": NUM, "problems": [PROBLEM]},
                   "verified": {"at": TS, "sha256": SHA256, "created_at": TS, "drill_failed_at": TS,
                                "drill_error_type": ERROR, "drill_error_length": LENGTHS, "drill_databases": NUM},
                   "disks": [{"label": DISK, "used_pct": NUM, "free": NUM}],
                   "cert": {"mode": OneOf(frozenset({"internal", "acme", "file", "other"})), "not_after": TS,
                            "error": OneOf(frozenset({"not_set", "not_pem", "other"}))},
                   "gpu": {"used_mib": NUM, "total_mib": NUM, "models_mib": NUM}},
        "error": ERROR,
    },
    "health.json": {"at": TS, "level": LEVELS, "checks": [{"name": CHECKS, "level": LEVELS, "value": NUM}]},
    "release.json": {
        "trialbox": Like(re.compile(r"\d{1,4}(?:\.\d{1,4}){1,3}(?:[-+.][0-9a-z]{1,12}){0,3}|-", re.A)),
        "installed": {"format": OneOf(frozenset({"trialbox-installed/1"})), "release_seq": NUM, "bundle": BUNDLE,
                      "manifest_sha256": SHA256, "key_id": Like(re.compile(r"ed25519:[0-9a-f]{16}", re.A)),
                      "applied_at": TS, "dirty": BOOL,
                      "state": {"vocabulary_release": Like(re.compile(r"[0-9]{1,4}(?:[.-][0-9]{1,4}){0,3}", re.A)),
                                "model_pin": Like(re.compile(r"sha256:[0-9a-f]{64}|[0-9a-f]{12,64}", re.A)),
                                "prompt_registry": Like(re.compile(r"[0-9]{1,6}|sha256:[0-9a-f]{64}", re.A)),
                                "schema": NUM}},
        "release": {"release_seq": NUM, "created_at": TS,
                    "commit": Like(re.compile(r"[0-9a-f]{40}", re.A)), "dirty": BOOL},
        "error": OneOf(frozenset({"not_json"})),
    },
    "history.jsonl": {"at": TS, "bundle": BUNDLE, "box": OneOf(frozenset({"compose", "demo", "in-process", "other"})),
                      "step": STEPS, "ok": BOOL, "detail_type": ERROR, "detail_length": LENGTHS},
    "audit-verify.json": {"ok": BOOL, "files": NUM, "lines": NUM, "errors": NUM, "notes": NUM, "error": ERROR,
                          "state": OneOf(frozenset({"verified", "not_here", "unreadable", "failed"}))},
    "services.json": [{"service": SERVICES, "state": STATES, "health": HEALTH, "restarts": NUM, "since": TS}],
    "disks.json": [{"label": DISK, "total": NUM, "used": NUM, "available": NUM}],
    "gpu.json": [{"memory_used_mib": NUM, "memory_total_mib": NUM, "utilization_pct": NUM, "temperature_c": NUM,
                  "driver": Like(re.compile(r"\d{2,4}(?:\.\d{1,4}){1,3}", re.A))}],
}  # fmt: skip


class _SecretName:
    """A secret's name from ``tools.trialbox.svc_secrets`` (its identities and the model key), never another."""

    def ok(self, v: Any) -> bool:
        from tools.trialbox import svc_secrets

        return isinstance(v, str) and v in {*svc_secrets.IDENTITIES, "model key"}


SCHEMAS["ops-snapshot.json"]["secrets"][0]["name"] = _SecretName()


# ------------------------------------------------------------------------------------------------ keep and check
_DROP = object()


def keep(kind: Kind, v: Any) -> tuple[Any, int]:
    """``v`` reduced to ``kind``: the allowed fields of the allowed kind, and how many were dropped. A value that is
    not of its kind is dropped (``_DROP``), never copied; null is kept anywhere."""
    if v is None:
        return None, 0
    if isinstance(kind, dict):
        if not isinstance(v, Mapping):
            return _DROP, 1
        out: dict[str, Any] = {}
        n = 0
        for k, x in v.items():
            if k not in kind:
                n += 1
                continue
            y, m = keep(kind[k], x)
            n += m
            if y is not _DROP:
                out[k] = y
        return out, n
    if isinstance(kind, list):
        if not isinstance(v, (list, tuple)):
            return _DROP, 1
        items, n = [], 0
        for x in v:
            y, m = keep(kind[0], x)
            n += m
            if y is not _DROP:
                items.append(y)
        return items, n
    return (v, 0) if kind.ok(v) else (_DROP, 1)


def check(kind: Kind, v: Any, where: str = "") -> list[str]:
    """Every place in ``v`` that is not of its declared kind (a key not on the list, a value of another kind)."""
    if v is None:
        return []
    if isinstance(kind, dict):
        if not isinstance(v, Mapping):
            return [f"{where}: not an object"]
        out = []
        for k, x in v.items():
            out += check(kind[k], x, f"{where}.{k}") if k in kind else [f"{where}.{k}: not on the list"]
        return out
    if isinstance(kind, list):
        if not isinstance(v, list):
            return [f"{where}: not a list"]
        return [p for i, x in enumerate(v) for p in check(kind[0], x, f"{where}[{i}]")]
    return [] if kind.ok(v) else [f"{where}: not of its kind"]


def check_member(name: str, text: str) -> list[str]:
    """:func:`check` for a member as it is in the bundle (``history.jsonl``: each line)."""
    if name == "history.jsonl":
        return [p for i, line in enumerate(text.splitlines()) if line
                for p in check(SCHEMAS[name], json.loads(line), f"line {i + 1}")]  # fmt: skip
    return check(SCHEMAS[name], json.loads(text))


# ------------------------------------------------------------------------------------------------ the shapes
def error_type(text: Any) -> str:
    """The error's type when the text starts with a known one (``UpdateFailed: ...``); ``other``; ``none`` when
    empty. Only a name of :func:`error_types` ever travels."""
    s = str(text or "")
    if not s:
        return "none"
    m = re.match(r"([A-Za-z_][A-Za-z0-9_.]{0,80})(?::|$)", s)
    name = m.group(1).rsplit(".", 1)[-1] if m else ""
    return name if name in error_types() else "other"


def length(text: Any) -> str:
    n = len(str(text or ""))
    return "0" if n == 0 else "1-99" if n < 100 else "100-999" if n < 1000 else "1000+"


class Labels:
    """``bundle-1``, ``bundle-2`` ... in the order first seen; the installed bundle is ``installed``. A bundle's id
    never travels: it came from a file name on a stick as often as from a signed release."""

    def __init__(self, installed: str = "") -> None:
        self.installed = installed
        self.seen: dict[str, str] = {}

    def __call__(self, bid: Any) -> str:
        b = str(bid or "")
        if b and b == self.installed:
            return "installed"
        return self.seen.setdefault(b, f"bundle-{len(self.seen) + 1}")


def problem_kind(text: Any) -> str:
    s = str(text or "")
    return next((k for p, k in PROBLEMS if s.startswith(p)), "other")


def step_of(step: Any) -> str:
    s = str(step or "")
    if s in STEPS.values:
        return s
    return "recover from step" if s.startswith("recover from step") else "other"


class Disks:
    """A fixed label for a mount or a path, never the path: ``system`` (/), ``data`` (/data), ``docker`` (Docker's
    root), ``deploy`` (the install folder), ``backup``, ``backup-2`` ... (each backup target's mount), else
    ``other-1``, ``other-2`` ... in the order seen."""

    def __init__(self, deploy: Path, docker: str, targets: Sequence[str]) -> None:
        self.fixed = {"/": "system", "/data": "data", docker.rstrip("/") or "/": "docker", str(deploy): "deploy"}
        self.targets = [t.rstrip("/") for t in targets if t]
        self.others: dict[str, str] = {}

    def target(self, i: int) -> str:
        return "backup" if i == 0 else f"backup-{i + 1}"

    def of_path(self, path: str) -> str:
        p = path.rstrip("/") or "/"
        if p in self.targets:
            return self.target(self.targets.index(p))
        if p in self.fixed:
            return self.fixed[p]
        return self.others.setdefault(p, f"other-{len(self.others) + 1}")

    def of_mount(self, mount: str) -> str:
        m = mount.rstrip("/") or "/"
        if m in self.targets:
            return self.target(self.targets.index(m))
        if m in self.fixed:
            return self.fixed[m]
        for i, t in enumerate(self.targets):
            if m != "/" and t.startswith(m + "/"):
                return self.target(i)
        return self.others.setdefault(m, f"other-{len(self.others) + 1}")


# ------------------------------------------------------------------------------------------------ the members
def snapshot(snap: Mapping[str, Any], labels: Labels, disks: Disks) -> dict[str, Any]:
    """``ops-snapshot.json`` from ``tools.trialbox.ops.snapshot``: no path, file name, detail or problem text."""
    v = snap.get("version") or {}
    h = snap.get("health") if isinstance(snap.get("health"), Mapping) else {}
    hb = (h or {}).get("backup") or {}
    vf = (h or {}).get("verified") or {}
    cert = (h or {}).get("cert") or {}
    cert_err = str(cert.get("error") or "")
    out: dict[str, Any] = {
        "at": snap.get("at"), "box": snap.get("box"),
        "version": {"trialbox": v.get("trialbox"), "bundle": labels(v.get("bundle")) if v.get("bundle") else None,
                    "applied_at": v.get("applied_at") or None},
        "updates": [{**{k: u.get(k) for k in ("first", "last", "ok", "steps", "outcome")},
                     "bundle": labels(u.get("bundle")), "step": step_of(u.get("step")),
                     "detail_type": error_type(u.get("detail")), "detail_length": length(u.get("detail"))}
                    for u in snap.get("updates") or []],
        "rollback_points": [{**{k: r.get(k) for k in ("images", "dumps_kept", "at")}, "bundle": labels(r.get("bundle"))}
                            for r in snap.get("rollback_points") or []],
        "incoming": [{"bytes": r.get("bytes"), "at": r.get("at")} for r in snap.get("incoming") or []],
        "backups": {
            "targets": [{"label": disks.of_path(str(t.get("path") or "")), "reachable": t.get("reachable"),
                         "files": len(t.get("files") or []),
                         "newest": max((str(f.get("at") or "") for f in t.get("files") or []), default="") or None,
                         **{k: (t.get("disk") or {}).get(k) for k in ("total", "used", "free")}}
                        for t in (snap.get("backups") or {}).get("targets") or []],
            **{k: (snap.get("backups") or {}).get(k) for k in ("newest", "key", "stale_hours")},
        },
        "secrets": [{k: r.get(k) for k in ("name", "present", "age_days", "registered", "mode")}
                    for r in snap.get("secrets") or []],
        "logs": snap.get("logs"),
        "disk": [{"label": disks.of_path(str(d.get("path") or "")), **{k: d.get(k) for k in ("total", "used", "free")}}
                 for d in snap.get("disk") or []],
        "health": None if not h else {
            "at": h.get("at"), "error": error_type(h.get("error")) if h.get("error") else None,
            "backup": None if not hb else {**{k: hb.get(k) for k in ("level", "age_hours", "max_age_hours")},
                                           "problems": [problem_kind(p) for p in hb.get("problems") or []]},
            "verified": None if not vf else {
                **{k: vf.get(k) for k in ("at", "sha256", "created_at", "drill_failed_at")},
                "drill_error_type": error_type(vf.get("drill_error")) if "drill_error" in vf else None,
                "drill_error_length": length(vf.get("drill_error")) if "drill_error" in vf else None,
                "drill_databases": len(vf.get("drill") or {}) if "drill" in vf else None},
            "disks": [{"label": disks.of_path(str(d.get("path") or "")), "used_pct": d.get("used_pct"),
                       "free": d.get("free")} for d in h.get("disks") or []],
            "cert": None if not cert else {
                "mode": cert.get("mode") if cert.get("mode") in ("internal", "acme", "file") else "other",
                "not_after": cert.get("not_after"),
                "error": None if not cert_err else "not_set" if "not set" in cert_err else
                         "not_pem" if "PEM" in cert_err else "other"},
            "gpu": h.get("gpu")},
        "error": error_type(snap.get("error")) if snap.get("error") else None,
    }  # fmt: skip
    return out


def health(evaluated: Mapping[str, Any]) -> dict[str, Any]:
    """``health.json``: the levels and measures of ``tb_common.metrics.evaluate``, never a check's text."""
    return {"at": evaluated.get("at"), "level": evaluated.get("level"),
            "checks": [{"name": "disk" if str(c.get("name") or "").startswith("disk:") else
                        c.get("name") if c.get("name") in CHECKS.values else "other",
                        "level": c.get("level"), "value": c.get("value")}
                       for c in evaluated.get("checks") or []]}  # fmt: skip


def release(version: str, installed: Any, rel: Any, labels: Labels) -> dict[str, Any]:
    """``release.json``: the version, and of ``installed.json`` and ``release.json`` the listed fields only."""
    out: dict[str, Any] = {"trialbox": version}
    if isinstance(installed, Mapping):
        bid = installed.get("bundle_id")
        out["installed"] = {**{k: installed.get(k) for k in ("format", "release_seq", "manifest_sha256", "key_id",
                                                              "applied_at", "dirty", "state")},
                            "bundle": labels(bid) if bid else None}  # fmt: skip
    if isinstance(rel, Mapping):
        src: Mapping[str, Any] = rel["source"] if isinstance(rel.get("source"), Mapping) else {}
        out["release"] = {"release_seq": rel.get("release_seq"), "created_at": rel.get("created_at"),
                          "commit": src.get("commit"), "dirty": src.get("dirty")}  # fmt: skip
    return out


def history_line(row: Any, labels: Labels) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    return {"at": row.get("at"), "bundle": labels(row.get("bundle")),
            "box": row.get("box") if row.get("box") in ("compose", "demo", "in-process") else "other",
            "step": step_of(row.get("step")), "ok": row.get("ok"),
            "detail_type": error_type(row.get("detail")), "detail_length": length(row.get("detail"))}  # fmt: skip


def audit_verify(res: Any = None, *, state: str, error: Any = None) -> dict[str, Any]:
    """``audit-verify.json``: whether the chain verified, and counts: never a note, an error's text or an event."""
    out: dict[str, Any] = {"state": state, "error": error_type(error) if error else None}
    if res is not None:
        out.update({"ok": bool(res.ok), "files": int(res.files), "lines": int(res.lines),
                    "errors": len(res.errors), "notes": len(res.notes)})  # fmt: skip
    return out


def services(lines: Iterable[str]) -> list[dict[str, Any]]:
    """``services.json`` from ``docker inspect --format`` lines ``service|restarts|status|health|started``."""
    out = []
    for line in lines:
        parts = line.strip().split("|")
        if len(parts) != 5:
            continue
        svc, restarts, status, hl, started = (p.strip() for p in parts)
        out.append({"service": svc if svc in SERVICES.values else "other",
                    "state": status if status in STATES.values else "other",
                    "health": (hl or "none") if (hl or "none") in HEALTH.values else "other",
                    "restarts": int(restarts) if restarts.isdigit() else None,
                    "since": started[:19] + "Z" if TS.ok(started[:19] + "Z") else None})  # fmt: skip
    return out


_PSEUDO_FS = ("tmpfs", "devtmpfs", "overlay", "shm", "udev", "none", "efivarfs", "squashfs", "proc", "sysfs")


def df(lines: Iterable[str], disks: Disks) -> list[dict[str, Any]]:
    """``disks.json`` from ``df -P -B1`` lines: numbers under a fixed label per mount; never a device or a mount."""
    out = []
    for line in list(lines)[1:]:
        parts = line.split(None, 5)
        if len(parts) != 6 or parts[0] in _PSEUDO_FS or not all(p.isdigit() for p in parts[1:4]):
            continue
        out.append({"label": disks.of_mount(parts[5].strip()), "total": int(parts[1]), "used": int(parts[2]),
                    "available": int(parts[3])})  # fmt: skip
    return out


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def gpu(lines: Iterable[str]) -> list[dict[str, Any]]:
    """``gpu.json`` from ``nvidia-smi --query-gpu=...`` CSV lines: numbers and the driver's version, no process."""
    out = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            continue
        out.append({"memory_used_mib": _num(parts[0]), "memory_total_mib": _num(parts[1]),
                    "utilization_pct": _num(parts[2]), "temperature_c": _num(parts[3]),
                    "driver": parts[4]})  # fmt: skip
    return out


#: the commands a site box runs for the button: none prints a command line, a file name or a process
PS_IDS = ("ps", "--all", "-q")
INSPECT_FORMAT = ('{{index .Config.Labels "com.docker.compose.service"}}|{{.RestartCount}}|{{.State.Status}}|'
                  "{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.StartedAt}}")  # fmt: skip
DF = ("df", "-P", "-B1")
GPU = ("nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu,driver_version",
       "--format=csv,noheader,nounits")  # fmt: skip
Runner = Callable[[Sequence[str], int], tuple[int, str]]
