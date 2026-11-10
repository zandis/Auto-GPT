"""The update path's state on the box and the commands that read it (T-111, D-210).

    tools/apply_update.sh status              # = python3 -m tools.update_status status [--json]
    tools/apply_update.sh rollback <bundle>   # finish an interrupted update by rolling it back
    tools/apply_update.sh clean               # remove left-over rollback points of finished updates
    python3 -m tools.update_status check      # exit 3 while an update is unfinished (for a start guard)

Everything lives in ``deploy/updates/`` (one directory, the same file system as the box's data):

* ``IN_PROGRESS.json`` — **the marker**. Written (atomically) before the update changes anything and rewritten at
  every step: bundle, manifest sha256, ``release_seq``, the step running, the rollback point's folder, the process.
  It is removed only by a completed apply or a completed rollback. While it exists no other update starts, and
  ``status`` reports it (after a power cut or a ``kill -9`` it is the only record of what was half done).
* ``installed.json`` — what the last completed update installed: ``release_seq``, bundle, manifest sha256, and the
  compatibility state (schema versions, vocabulary release, model pin, prompt registry) the next bundle is checked
  against. Absent on a box never updated under D-210 (``release_seq`` 0).
* ``trust.json`` — the vendor keys the box trusts (at most two, by ``key_id``), the retired ones (never trusted
  again) and the rotation bundles already applied. Absent until the first completed update: then the key(s) given to
  ``verify_update.py`` (``deploy/keys/vendor_ed25519.pub``) are the trust and are written here; from then on this file
  alone is the trust (``TB_VENDOR_PUBKEY`` no longer matters).
* ``history.jsonl`` — one line per step (no secret in it); ``<bundle>/rollback/`` — the rollback point while an
  update runs (``point.json``, the encrypted database dumps and their key, the model files it overwrote), deleted by
  the completed apply or rollback.
* ``.lock`` — ``flock`` held by the process that runs an update or a rollback; a ``kill -9`` releases it, so
  ``status`` can tell a running update from an interrupted one.

Standard library only (the host's ``python3`` runs it, like ``tools/trialbox/update.py``).
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MARKER = "IN_PROGRESS.json"
INSTALLED = "installed.json"
TRUST = "trust.json"
HISTORY = "history.jsonl"
LOCK = ".lock"
COMPAT_FORMAT = "trialbox-update-compat/1"
TRUST_FORMAT = "trialbox-update-trust/1"
INSTALLED_FORMAT = "trialbox-installed/1"
MARKER_FORMAT = "trialbox-update-in-progress/1"
MAX_TRUSTED_KEYS = 2
DIMENSIONS = ("vocabulary_release", "model_pin", "prompt_registry")
EXIT_IN_PROGRESS = 3
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ROOT = Path(__file__).resolve().parents[1]


class Busy(RuntimeError):
    """Another process holds the update lock (an update or a rollback is running)."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_atomic(path: Path, data: Mapping[str, Any] | str, mode: int = 0o600) -> None:
    """Write ``path`` so a crash leaves the old or the new file, never half of one (temp file, fsync, rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    with contextlib.suppress(OSError):  # the rename itself survives a power cut
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


@contextlib.contextmanager
def locked(updates: Path, wait: bool = False) -> Iterator[None]:
    """Hold the update lock (``flock`` on ``updates/.lock``). Raises :class:`Busy` when another process holds it."""
    updates.mkdir(parents=True, exist_ok=True)
    fd = os.open(updates / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise Busy("another update or rollback is running on this box (deploy/updates/.lock)") from exc
            raise
        yield
    finally:
        os.close(fd)


def lock_held(updates: Path) -> bool:
    """True when a live process holds the update lock (an update is running, not interrupted)."""
    if not (updates / LOCK).exists():
        return False
    try:
        with locked(updates):
            return False
    except Busy:
        return True


# ------------------------------------------------------------------------------------------------ marker
def marker(updates: Path) -> dict[str, Any] | None:
    """The marker, or None. An unreadable marker still means "unfinished" (never None)."""
    try:
        return read_json(updates / MARKER)
    except ValueError:
        return {"bundle_id": None, "step": "unknown (the marker is unreadable)", "steps_done": []}


def create_marker(updates: Path, fields: Mapping[str, Any]) -> dict[str, Any]:
    """The marker, created exclusively (two updates can never both own it). Call under :func:`locked`."""
    m = {"format": MARKER_FORMAT, "started_at": now(), "updated_at": now(), "pid": os.getpid(), "boot_id": boot_id(),
         "steps_done": [], **fields}  # fmt: skip
    path = updates / MARKER
    tmp = updates / f".{MARKER}.{os.getpid()}.new"
    write_atomic(tmp, m)
    try:
        os.link(tmp, path)  # exclusive and complete at once: FileExistsError when an update is unfinished
    finally:
        tmp.unlink(missing_ok=True)
    return m


def set_step(updates: Path, m: dict[str, Any], step: str, **extra: Any) -> None:
    if m.get("step") and m["step"] != step:
        m["steps_done"] = [*m.get("steps_done", []), m["step"]]
    m.update(step=step, updated_at=now(), pid=os.getpid(), **extra)
    write_atomic(updates / MARKER, m)


def remove_marker(updates: Path) -> None:
    (updates / MARKER).unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------------ installed, trust
def load_installed(path: Path | None) -> dict[str, Any]:
    """The installed record; ``release_seq`` 0 and an unknown state on a box never updated under D-210."""
    rec = read_json(path) if path is not None else None
    if rec is None:
        return {"format": INSTALLED_FORMAT, "release_seq": 0, "bundle_id": None, "state": {}}
    if not isinstance(rec.get("release_seq"), int) or isinstance(rec.get("release_seq"), bool):
        raise ValueError(f"{path} has no integer release_seq")
    return rec


def installed(updates: Path) -> dict[str, Any]:
    return load_installed(updates / INSTALLED)


def load_trust(path: Path | None) -> dict[str, Any] | None:
    t = read_json(path) if path is not None else None
    if t is not None and (t.get("format") != TRUST_FORMAT or not isinstance(t.get("keys"), dict) or not t["keys"]):
        raise ValueError(f"{path} is not a {TRUST_FORMAT} file with at least one key")
    return t


def trust(updates: Path) -> dict[str, Any] | None:
    return load_trust(updates / TRUST)


def file_sha256(path: Path) -> str | None:
    """sha256 of a file's bytes, None when it does not exist (trust.json's identity between verify and the update)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def load_trust_with_sha(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    """:func:`load_trust` and the sha256 of exactly the bytes it parsed (one read), or ``(None, None)``."""
    if path is None:
        return None, None
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, None
    t = json.loads(raw)
    if not isinstance(t, dict) or t.get("format") != TRUST_FORMAT or not isinstance(t.get("keys"), dict) \
            or not t["keys"]:  # fmt: skip
        raise ValueError(f"{path} is not a {TRUST_FORMAT} file with at least one key")
    return t, hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------------------------------------------ compatibility
def compat_problems(table: Mapping[str, Any], bundle_id: str) -> list[str]:
    """The table's own shape (the schema of compat.json, kept here so the host's python3 needs nothing)."""
    out = []
    if table.get("format") != COMPAT_FORMAT:
        out.append(f"compat.json format is not {COMPAT_FORMAT}")
    if table.get("bundle_id") != bundle_id:
        out.append(f"compat.json is for bundle {table.get('bundle_id')!r}, not {bundle_id!r}")
    rows = table.get("rows")
    if not isinstance(rows, list) or not rows:
        out.append("compat.json has no rows")
        return out
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            out.append(f"compat.json row {i} is not an object")
            continue
        for store, rng in (row.get("schema") or {}).items():
            if not (isinstance(rng, dict) and isinstance(rng.get("min", 0), int) and isinstance(rng.get("max"), int)):
                out.append(f"compat.json row {i}: schema {store} needs integer max (and min)")
        for dim in DIMENSIONS:
            v = row.get(dim, "*")
            if v != "*" and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                out.append(f'compat.json row {i}: {dim} must be "*" or a list of strings')
        extra = set(row) - {"schema", *DIMENSIONS}
        if extra:
            out.append(f"compat.json row {i}: unknown columns {sorted(extra)}")
    return out


def compat_check(table: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[bool, str, list[str]]:
    """Does the box's ``state`` match a row of the bundle's compatibility table?

    ``state``: ``schema`` ({store: applied version}, or absent when not known here), ``vocabulary_release``,
    ``model_pin``, ``prompt_registry`` (each a string, or absent/None when the box does not record it). A row matches
    when every store it names is within ``min..max`` (a store the box lacks is version 0) and every other column is
    ``"*"`` or lists the box's value. A column the box does not record is not compared (the prompt registry of T-101
    is not on master yet); the notes say so. Returns ``(ok, reason, notes)``."""
    notes: list[str] = []
    schema = state.get("schema")
    if schema is None:
        notes.append("schema versions not compared here (read from the database by the update itself)")
    for dim in DIMENSIONS:
        if state.get(dim) in (None, ""):
            notes.append(f"{dim}: the box records none, not compared")
    reasons = []
    for i, row in enumerate(table.get("rows") or []):
        why = []
        for store, rng in (row.get("schema") or {}).items():
            if schema is None:
                continue
            v = int(schema.get(store, 0))
            lo, hi = int(rng.get("min", 0)), int(rng["max"])
            if v > hi:
                why.append(f"schema {store} is at version {v}, newer than this bundle knows ({hi}): a downgrade")
            elif v < lo:
                why.append(f"schema {store} is at version {v}, older than this bundle needs ({lo})")
        for dim in DIMENSIONS:
            allowed = row.get(dim, "*")
            have = state.get(dim)
            if allowed != "*" and have not in (None, "") and have not in allowed:
                why.append(f"{dim} {have!r} is not one of {allowed}")
        if not why:
            return True, f"matches compatibility row {i}", notes
        reasons.append(f"row {i}: " + "; ".join(why))
    return False, "no compatibility row matches the box: " + " | ".join(reasons), notes


def images_problems(release: Mapping[str, Any] | None, lock: Mapping[str, Any] | None) -> list[str]:
    """``release.json`` (provisional, T-110: ``images`` = {name: {image, digest}}) against ``images.lock`` (T-104).

    Every image either file names must be in both, with the same reference and the same ``sha256:`` digest. A null,
    missing or malformed digest is refused: null never means "nothing to compare"."""
    out: list[str] = []
    if release is None:
        return ["the bundle carries images but no release.json (T-110): the image digests cannot be checked"]
    if lock is None:
        return ["no images.lock to check release.json's image digests against"]
    rel = release.get("images")
    lk = lock.get("images")
    if not isinstance(rel, dict) or not rel:
        return ["release.json lists no images"]
    if not isinstance(lk, dict) or not lk:
        return ["images.lock lists no images"]
    for name in sorted(set(rel) | set(lk)):
        r, k = rel.get(name), lk.get(name)
        if not isinstance(k, dict):
            out.append(f"image {name}: in release.json but not in images.lock")
            continue
        if not isinstance(r, dict):
            out.append(f"image {name}: pinned in images.lock but not in release.json")
            continue
        kd, rd = k.get("digest"), r.get("digest")
        if not isinstance(kd, str) or not _DIGEST.match(kd):
            out.append(f"image {name}: images.lock has no digest ({kd!r}); refused until the release build pins it")
            continue
        if not isinstance(rd, str) or not _DIGEST.match(rd):
            out.append(f"image {name}: release.json has no digest ({rd!r})")
            continue
        if rd != kd:
            out.append(f"image {name}: release.json digest {rd} differs from images.lock {kd}")
        if r.get("image") != k.get("image"):
            out.append(f"image {name}: release.json names {r.get('image')!r}, images.lock {k.get('image')!r}")
    return out


# ------------------------------------------------------------------------------------------------ clean
def stale_rollback_dirs(updates: Path) -> list[Path]:
    """Rollback points not owned by an unfinished update (the marker's), oldest first."""
    m = marker(updates)
    keep = Path(m["rollback_dir"]).resolve() if m and m.get("rollback_dir") else None
    out = []
    for rb in sorted(updates.glob("*/rollback")):
        if rb.is_dir() and rb.resolve() != keep:
            out.append(rb)
    return out


def clean(updates: Path) -> list[str]:
    """Remove left-over rollback points (dumps, their key, kept model files) of finished updates."""
    removed = []
    for rb in stale_rollback_dirs(updates):
        shutil.rmtree(rb)
        removed.append(str(rb))
    for st in sorted(updates.glob("stage.*")):
        if st.is_dir():
            shutil.rmtree(st)
            removed.append(str(st))
    return removed


# ------------------------------------------------------------------------------------------------ status
def status(updates: Path) -> dict[str, Any]:
    m = marker(updates)
    out: dict[str, Any] = {"in_progress": m is not None, "installed": installed(updates)}
    if m is not None:
        running = lock_held(updates)
        out["update"] = {k: m.get(k) for k in ("bundle_id", "release_seq", "step", "steps_done", "started_at",
                                                "updated_at", "pid", "target", "rollback_dir")}  # fmt: skip
        out["update"]["state"] = "running" if running else "interrupted"
        out["update"]["rebooted_since"] = bool(m.get("boot_id") and boot_id() and m["boot_id"] != boot_id())
        out["next"] = (
            "an update is running; wait for it"
            if running
            else f"tools/apply_update.sh rollback {m.get('bundle_id')}  (puts the box back as before the update)"
        )
    t = trust(updates)
    out["trusted_keys"] = sorted(t["keys"]) if t else []
    out["retired_keys"] = sorted((t or {}).get("retired") or {})
    hist = updates / HISTORY
    lines = hist.read_text(encoding="utf-8").splitlines()[-5:] if hist.is_file() else []
    out["history"] = [json.loads(x) for x in lines if x.strip()]
    out["left_over_rollback_points"] = [str(p) for p in stale_rollback_dirs(updates)]
    return out


def _print_status(s: Mapping[str, Any]) -> None:
    inst = s["installed"]
    print(f"installed: release_seq {inst.get('release_seq')}, bundle {inst.get('bundle_id') or '(none recorded)'}")
    if s["in_progress"]:
        u = s["update"]
        print(f"UPDATE IN PROGRESS ({u['state']}): bundle {u['bundle_id']}, release_seq {u['release_seq']}, "
              f"step {u['step']!r} since {u['updated_at']} (started {u['started_at']}, pid {u['pid']}"
              f"{', the host rebooted since' if u['rebooted_since'] else ''})")  # fmt: skip
        print(f"  steps done: {', '.join(u['steps_done'] or []) or '(none)'}")
        print(f"  next: {s['next']}")
    else:
        print("no update in progress")
    print(f"trusted vendor keys: {', '.join(s['trusted_keys']) or '(trust.json not written yet: deploy/keys)'}")
    if s["left_over_rollback_points"]:
        print(f"left-over rollback points (tools/apply_update.sh clean): {', '.join(s['left_over_rollback_points'])}")
    for h in s["history"]:
        print(f"  {h.get('at')}  {h.get('bundle')}  {'ok  ' if h.get('ok') else 'FAIL'}  {h.get('step')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="update_status", description=__doc__.split("\n\n")[0])
    ap.add_argument("--deploy", type=Path, default=ROOT / "deploy", help="the install's deploy folder")
    sub = ap.add_subparsers(dest="cmd")
    st = sub.add_parser("status", help="the marker, the installed release, the trusted keys, the last steps")
    st.add_argument("--json", action="store_true")
    sub.add_parser("check", help=f"exit {EXIT_IN_PROGRESS} while an update is unfinished (a start guard)")
    rb = sub.add_parser("rollback", help="roll back an interrupted update (its marker names the bundle)")
    rb.add_argument("bundle")
    rb.add_argument("--target", choices=("compose", "demo"), help="default: the one the marker records")
    sub.add_parser("clean", help="remove left-over rollback points of finished updates")
    a = ap.parse_args(argv)
    updates = a.deploy / "updates"
    cmd = a.cmd or "status"
    if cmd == "status":
        s = status(updates)
        if getattr(a, "json", False):
            print(json.dumps(s, ensure_ascii=False, indent=1))
        else:
            _print_status(s)
        return EXIT_IN_PROGRESS if s["in_progress"] else 0
    if cmd == "check":
        m = marker(updates)
        if m is None:
            return 0
        print(f"update {m.get('bundle_id')} is unfinished (step {m.get('step')!r}): tools/apply_update.sh status",
              file=sys.stderr)  # fmt: skip
        return EXIT_IN_PROGRESS
    if cmd == "clean":
        try:
            with locked(updates):
                for p in clean(updates):
                    print(f"removed {p}")
        except Busy as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    from tools.trialbox import update as up

    m = marker(updates)
    target = a.target or (m or {}).get("target") or "compose"
    box: up.ComposeBox | up.DemoBox = up.DemoBox(a.deploy) if target == "demo" else up.ComposeBox(a.deploy)
    try:
        up.Updater(box, updates).recover(a.bundle)
    except (up.UpdateFailed, Busy) as exc:
        print(f"rollback FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"update {a.bundle} rolled back; the marker is removed")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
