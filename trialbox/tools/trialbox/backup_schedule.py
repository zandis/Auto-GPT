"""The nightly backup, its off-box rule and the age alert (WS-08.6, D-187). Standard library only at import, so the
host's ``python3`` runs it from the install folder (cron, ``deploy/backup/trialbox-backup.cron``):

    python3 -m tools.trialbox backup-nightly            # 04:45: the .tbbak to every target, then pgBackRest
    python3 -m tools.trialbox backup-status [--json]    # hourly: exit 1 and alert when the newest good one is too old

**Nightly** (:func:`nightly`). The trial and HAPI databases are dumped by the ``db`` container (``pg_dump -Fc -Z0``,
without the rows of ``refdata``) into a 0700 folder under ``deploy/`` that is removed right after; ``trialbox backup``
runs in a one-off container with every volume read-only (the update path's own step, ``update.ComposeBox``) and
writes the encrypted file to every directory of ``TB_BACKUP_TARGETS``. When WAL archiving is on
(``TB_PG_ARCHIVE_MODE=on``), pgBackRest then takes a differential backup, or a full one on ``TB_PGBACKREST_FULL_DAY``
(default Sunday). The result goes to ``deploy/site/backup-last.json`` (0600: time, file name, size, sha256, targets,
error; never a row or a file's content) and to the audit (``backup.done`` / ``backup.failed``).

**Off-box.** A target counts as off-box when it is a network share (NFS, SMB/CIFS, SSHFS ... or a Windows UNC path
mounted in WSL2), a USB disk, or a path that hospital IT declared in ``TB_BACKUP_OFFBOX`` (e.g. an iSCSI volume in
another room). In PRODUCTION a backup is *good* only on an off-box target: a box whose targets are all on its own
disks writes its backup and still fails (exit 1, ``backup.failed``) and stays red.

**Age alert** (:func:`status`, :func:`alert`). The newest good backup is the newest ``trialbox-*.tbbak`` on a counted
target that has its ``.sha256`` sidecar (written only after the file was complete and its copies matched). It is
too old after ``TB_BACKUP_MAX_AGE_HOURS`` (default 36, the admin tile's red, WS-08.5). A failed last nightly run, a
failed pgBackRest run and failing WAL archiving (``pg_stat_archiver``) are alerts too. An alert is audited
(``backup.alert``, again every 24 h while it lasts, ``backup.alert_cleared`` when it ends) and sent to
``TB_BACKUP_ALERT_CMD`` (a command that reads the message on stdin, e.g. the hospital's mail relay), and the command
exits 1 so cron's ``MAILTO`` mails it too. The message names the problem and the box, never patient data.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SUFFIX = ".tbbak"
EXCLUDE_DATA_SCHEMAS = ("refdata",)  # D-187: as tools/trialbox/backup.py, whose dumps leave out the same rows
NETWORK_FS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "sshfs", "glusterfs", "ceph",
                        "fuse.rclone", "davfs", "fuse.s3fs", "afs"})  # fmt: skip
MAX_AGE_HOURS = 36.0
REALERT = timedelta(hours=24)
STANZA = "trialbox"

Audit = Callable[[str, dict[str, Any]], None]


# ------------------------------------------------------------------------------------------------ files
def sidecar(file: Path) -> Path:
    return file.with_name(file.name + ".sha256")


def read_sidecar(file: Path) -> str | None:
    """The sha256 written beside ``file`` when it was complete, or None (no sidecar: not a finished backup)."""
    try:
        sha, _, rest = sidecar(file).read_text(encoding="utf-8").strip().partition("  ")
    except OSError:
        return None
    return sha if rest == file.name and len(sha) == 64 else None


def stamp_of(file: Path) -> datetime | None:
    """The time in a backup's file name (``trialbox-<site>-YYYYmmddTHHMMSSZ.tbbak``), UTC."""
    try:
        return datetime.strptime(file.name[: -len(SUFFIX)].rsplit("-", 1)[-1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def prune(target: Path, keep: int) -> list[Path]:
    """Keep the newest ``keep`` backups in a target; remove older ones (with their sidecar) and stale ``.part``
    files."""
    files = sorted(target.glob(f"trialbox-*{SUFFIX}"), key=lambda p: p.name.rsplit("-", 1)[-1])
    gone = files[:-keep] if keep > 0 else []
    gone += [sidecar(p) for p in gone]
    gone += list(target.glob(f"trialbox-*{SUFFIX}.part")) + list(target.glob(f"trialbox-*{SUFFIX}.sha256.part"))
    for p in gone:
        p.unlink(missing_ok=True)
    return gone


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


# ------------------------------------------------------------------------------------------------ targets
@dataclass(frozen=True)
class Target:
    path: str
    kind: str  # network share | usb disk | declared off-box | this box
    offbox: bool
    fstype: str = ""


def _unescape(s: str) -> str:
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def _mounts(text: str | None) -> list[tuple[str, str, str]]:
    if text is None:
        try:
            text = Path("/proc/mounts").read_text(encoding="utf-8")
        except OSError:
            text = ""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 3:
            out.append((_unescape(f[0]), _unescape(f[1]), f[2]))
    return out


def _resolve(path: Path) -> Path:
    """``path`` with the symlinks of its existing part resolved; a part not made yet is kept as written."""
    p, tail = Path(os.path.normpath(path.absolute())), list[str]()
    while not p.exists() and p != p.parent:
        tail.insert(0, p.name)
        p = p.parent
    return p.resolve().joinpath(*tail)


def _is_usb(device: str, sys_block: Path) -> bool:
    if not device.startswith("/dev/"):
        return False
    name = Path(device).resolve().name if Path(device).exists() else Path(device).name
    node = sys_block / name
    try:
        real = node.resolve()
    except OSError:
        return False
    if "/usb" in str(real):
        return True
    for d in (real, real.parent):
        try:
            if (d / "removable").read_text().strip() == "1":
                return True
        except OSError:
            continue
    return False


def target_kind(
    path: Path,
    mounts_text: str | None = None,
    declared: Sequence[str] = (),
    sys_block: Path = Path("/sys/class/block"),
) -> Target:
    """Where ``path`` lives: on a network share, a USB disk, a declared off-box volume, or this box's own disks."""
    real = _resolve(Path(path))
    for d in declared:
        if d and (real == _resolve(Path(d)) or _resolve(Path(d)) in real.parents):
            return Target(str(path), "declared off-box", True)
    best = ("", "/", "")
    for src, mnt, fstype in _mounts(mounts_text):
        m = Path(mnt)
        if (real == m or m in real.parents) and len(mnt) >= len(best[1]):
            best = (src, mnt, fstype)
    src, _, fstype = best
    if fstype in NETWORK_FS or src.startswith(("//", "\\\\")):  # a UNC source: a Windows share mounted in WSL2
        return Target(str(path), "network share", True, fstype)
    if _is_usb(src, sys_block):
        return Target(str(path), "usb disk", True, fstype)
    return Target(str(path), "this box", False, fstype)


# ------------------------------------------------------------------------------------------------ configuration
@dataclass
class Config:
    deploy: Path
    targets: list[Path]
    public_key: Path
    production: bool = True
    keep: int = 14
    max_age_hours: float = MAX_AGE_HOURS
    archive_on: bool = False
    full_day: int = 6  # Monday 0 ... Sunday 6
    declared_offbox: list[str] = field(default_factory=list)
    alert_cmd: str = ""
    site: str = ""

    @property
    def last_file(self) -> Path:
        return self.deploy / "site" / "backup-last.json"

    @property
    def alert_file(self) -> Path:
        return self.deploy / "site" / "backup-alert.json"


def _split(v: str) -> list[str]:
    return [t for t in v.replace(",", " ").split() if t]


def config(deploy: Path, env: Mapping[str, str]) -> Config:
    """The schedule's settings from ``deploy/.env`` (``env``), with the process environment winning."""
    e = {**env, **{k: v for k, v in os.environ.items() if k.startswith("TB_")}}
    return Config(
        deploy=deploy,
        targets=[Path(t) for t in _split(e.get("TB_BACKUP_TARGETS", ""))],
        public_key=Path(e.get("TB_BACKUP_PUBKEY") or deploy / "secrets" / "backup.pub"),
        production=(e.get("TB_ENV") or "PRODUCTION").upper() == "PRODUCTION",
        keep=int(e.get("TB_BACKUP_KEEP") or 14),
        max_age_hours=float(e.get("TB_BACKUP_MAX_AGE_HOURS") or MAX_AGE_HOURS),
        archive_on=(e.get("TB_PG_ARCHIVE_MODE") or "off").lower() == "on",
        full_day=int(e.get("TB_PGBACKREST_FULL_DAY") or 6),
        declared_offbox=_split(e.get("TB_BACKUP_OFFBOX", "")),
        alert_cmd=e.get("TB_BACKUP_ALERT_CMD", ""),
        site=e.get("TB_SITE_ID", ""),
    )


# ------------------------------------------------------------------------------------------------ nightly
def nightly(
    cfg: Config,
    make_backup: Callable[[list[Path]], Sequence[Path]],
    audit: Audit,
    pgbackrest: Callable[[str], None] | None = None,
    now: datetime | None = None,
    classify: Callable[[Path], Target] | None = None,
) -> dict[str, Any]:
    """One nightly run: the encrypted backup to every target, then pgBackRest; record and audit the result."""
    now = now or datetime.now(UTC)
    kinds = [(classify or (lambda p: target_kind(p, declared=cfg.declared_offbox)))(t) for t in cfg.targets]
    res: dict[str, Any] = {"at": now.isoformat(timespec="seconds"), "ok": False, "targets": [asdict(k) for k in kinds],
                           "file": None, "errors": []}  # fmt: skip
    errors: list[str] = res["errors"]
    if not cfg.targets:
        errors.append("no backup target: set TB_BACKUP_TARGETS in deploy/.env (RUNBOOK §5)")
    elif not cfg.public_key.is_file():
        errors.append(f"no backup key {cfg.public_key}: trialbox backup-keygen with hospital IT (RUNBOOK §5)")
    else:
        if cfg.production and not any(k.offbox for k in kinds):
            errors.append("no off-box target: every TB_BACKUP_TARGETS directory is on this box (RUNBOOK §5)")
        try:
            files = list(make_backup(cfg.targets))
            copies: list[dict[str, Any]] = []
            for f in files:
                prune(f.parent, cfg.keep)
                sha = read_sidecar(f)
                if sha is None:
                    raise RuntimeError(f"{f} has no .sha256 sidecar: the backup did not complete")
                copies.append({"path": str(f), "bytes": f.stat().st_size, "sha256": sha})
            if not copies or len({c["sha256"] for c in copies}) != 1:
                raise RuntimeError("the copies of the backup differ or none was written")
            res["file"] = {"name": Path(copies[0]["path"]).name, "bytes": copies[0]["bytes"],
                           "sha256": copies[0]["sha256"], "copies": copies}  # fmt: skip
        except Exception as e:  # every failure is recorded, audited and alerted (exit 1)
            errors.append(f"backup failed: {type(e).__name__}: {str(e)[-400:]}")
    if cfg.archive_on and pgbackrest is not None:
        kind = "full" if now.weekday() == cfg.full_day else "diff"
        try:
            pgbackrest(kind)
            res["pgbackrest"] = {"type": kind, "ok": True}
        except Exception as e:
            res["pgbackrest"] = {"type": kind, "ok": False}
            errors.append(f"pgBackRest {kind} backup failed: {type(e).__name__}: {str(e)[-300:]}")
    res["ok"] = not errors
    if res["ok"]:
        res["good_at"] = res["at"]
    _write_json(cfg.last_file, res)
    detail = {"file": (res["file"] or {}).get("name"), "bytes": (res["file"] or {}).get("bytes"),
              "sha256": (res["file"] or {}).get("sha256"), "targets": len(kinds),
              "offbox_targets": sum(k.offbox for k in kinds), "pgbackrest": res.get("pgbackrest"),
              "errors": errors}  # fmt: skip
    audit("backup.done" if res["ok"] else "backup.failed", detail)
    return res


# ------------------------------------------------------------------------------------------------ status and alert
def newest_good(dirs: Sequence[Path]) -> dict[str, Any] | None:
    """The newest complete backup (``.tbbak`` with its ``.sha256`` sidecar) in ``dirs``, by the time in its name."""
    best: dict[str, Any] | None = None
    for d in dirs:
        for f in Path(d).glob(f"trialbox-*{SUFFIX}"):
            at, sha = stamp_of(f), read_sidecar(f)
            if at is None or sha is None or f.stat().st_size == 0:
                continue
            if best is None or at > best["at"]:
                best = {"at": at, "path": str(f), "bytes": f.stat().st_size, "sha256": sha}
    return best


def status(
    cfg: Config,
    now: datetime | None = None,
    archiver: Mapping[str, Any] | None = None,
    classify: Callable[[Path], Target] | None = None,
) -> dict[str, Any]:
    """``level`` ok or alert, the newest good backup and its age, and every problem in plain words."""
    now = now or datetime.now(UTC)
    kinds = [(classify or (lambda p: target_kind(p, declared=cfg.declared_offbox)))(t) for t in cfg.targets]
    problems: list[str] = []
    counted = [Path(k.path) for k in kinds if k.offbox or not cfg.production]
    if not cfg.targets:
        problems.append("no backup target (TB_BACKUP_TARGETS)")
    elif cfg.production and not counted:
        problems.append("no off-box backup target: every target is on this box")
    good = newest_good(counted)
    age_h = None
    if good is None:
        if counted:
            problems.append("no complete backup on " + ("an off-box target" if cfg.production else "any target"))
    else:
        age_h = round((now - good["at"]).total_seconds() / 3600, 1)
        if age_h > cfg.max_age_hours:
            problems.append(f"the newest good backup is {age_h:.0f} h old (limit {cfg.max_age_hours:.0f} h)")
    last = _read_json(cfg.last_file)
    if last and not last.get("ok"):
        when = last.get("at", "?")
        if good is None or str(when) > good["at"].isoformat(timespec="seconds"):
            problems.append(f"the last nightly backup at {when} failed (deploy/site/backup-last.json)")
    elif last.get("pgbackrest") and not last["pgbackrest"].get("ok"):
        problems.append("the last pgBackRest backup failed (deploy/site/backup-last.json)")
    if archiver and archiver.get("failing"):
        problems.append("WAL archiving to pgBackRest is failing: PITR is not current and pg_wal grows (RUNBOOK §5)")
    out = {"level": "alert" if problems else "ok", "at": now.isoformat(timespec="seconds"), "problems": problems,
           "age_hours": age_h, "max_age_hours": cfg.max_age_hours, "targets": [asdict(k) for k in kinds],
           "newest_good": None if good is None else {**good, "at": good["at"].isoformat(timespec="seconds")},
           }  # fmt: skip
    if archiver is not None:
        out["archiver"] = dict(archiver)
    return out


def alert(
    cfg: Config,
    st: Mapping[str, Any],
    audit: Audit,
    send: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> str:
    """Audit and send an alert when one starts, changes or has lasted another 24 h; audit its end. Returns what was
    done: ``sent``, ``cleared`` or ``quiet``."""
    now = now or datetime.now(UTC)
    prev = _read_json(cfg.alert_file)
    if st["level"] == "alert":
        sent = prev.get("sent_at")
        kinds = sorted({re.sub(r"[0-9][0-9:.T+-]*", "#", p) for p in st["problems"]})  # the age changes hourly
        due = (prev.get("level") != "alert" or prev.get("kinds") != kinds or not sent
               or now - datetime.fromisoformat(sent) >= REALERT)  # fmt: skip
        if not due:
            return "quiet"
        audit("backup.alert", {"problems": st["problems"], "age_hours": st.get("age_hours")})
        msg = (f"TrialBox {cfg.site or 'box'}: backup alert\n" + "".join(f"- {p}\n" for p in st["problems"])
               + "What to do: docs/RUNBOOK.md §5 (Backup). This message holds no patient data.\n")  # fmt: skip
        if send is not None:
            try:
                send(msg)
            except Exception as e:  # the audit and the exit code still carry the alert
                audit("backup.alert_not_sent", {"error": f"{type(e).__name__}: {str(e)[-200:]}"})
        _write_json(cfg.alert_file, {"level": "alert", "problems": st["problems"], "kinds": kinds,
                                     "sent_at": now.isoformat()})  # fmt: skip
        return "sent"
    if prev.get("level") == "alert":
        audit("backup.alert_cleared", {"newest_good": (st.get("newest_good") or {}).get("at")})
        _write_json(cfg.alert_file, {"level": "ok", "cleared_at": now.isoformat()})
        return "cleared"
    return "quiet"


def send_cmd(cmd: str) -> Callable[[str], None] | None:
    """``TB_BACKUP_ALERT_CMD`` as a sender: the command reads the message on stdin."""
    if not cmd:
        return None

    def send(msg: str) -> None:
        subprocess.run(shlex.split(cmd), input=msg.encode(), check=True, timeout=120, capture_output=True)

    return send


# ------------------------------------------------------------------------------------------------ the compose box
ARCHIVER_SQL = (
    "SELECT current_setting('archive_mode'), COALESCE(failed_count, 0), "
    "COALESCE(last_failed_time > COALESCE(last_archived_time, 'epoch'), false) FROM pg_stat_archiver"
)


class ComposeOps:
    """The nightly run's steps on a site box (``docker compose --project-directory deploy``)."""

    def __init__(self, deploy: Path, run: Callable[..., str] | None = None) -> None:
        from tools.trialbox import update

        self.deploy = deploy
        self.box = update.ComposeBox(deploy, run or update.run_cmd)
        self.env = self.box.env

    def make_backup(self, cfg: Config) -> Callable[[list[Path]], list[Path]]:
        def run(targets: list[Path]) -> list[Path]:
            before = {t: {p.name for p in t.glob(f"trialbox-*{SUFFIX}")} for t in targets}
            work = Path(tempfile.mkdtemp(prefix=".backup-", dir=self.deploy))  # 0700; plaintext dumps: removed below
            try:
                for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi")):
                    excl = list(EXCLUDE_DATA_SCHEMAS) if db == "trialbox_wf" else []
                    self.box.run(self.box._c("exec", "-T", "db", "pg_dump", "-Fc", "-Z0", "--no-owner", "-U", user,
                                             "-d", db, *[f"--exclude-table-data={s}.*" for s in excl]),
                                 stdout_file=work / f"{db}.dump", timeout=7200)  # fmt: skip
                    (work / f"{db}.dump.json").write_text(json.dumps({"exclude_table_data_schemas": excl}))
                self.box._backup_container(work, cfg.public_key, [str(t) for t in targets])
            finally:
                shutil.rmtree(work, ignore_errors=True)
            new = [sorted({p.name for p in t.glob(f"trialbox-*{SUFFIX}")} - before[t]) for t in targets]
            if not all(new):
                raise RuntimeError("the backup container wrote no new file to every target")
            return [t / n[-1] for t, n in zip(targets, new, strict=True)]

        return run

    def pgbackrest(self, kind: str) -> None:
        self.box.run(self.box._c("exec", "-T", "-u", "postgres", "db", "pgbackrest", f"--stanza={STANZA}",
                                 f"--type={kind}", "backup"), timeout=4 * 3600)  # fmt: skip

    def archiver(self) -> dict[str, Any]:
        out = self.box.run(self.box._c("exec", "-T", "db", "psql", "-U", self.env.get("POSTGRES_USER") or "hapi",
                                       "-d", "hapi", "-tAc", ARCHIVER_SQL)).strip()  # fmt: skip
        mode, failed, failing = [*out.split("|"), "", "0", "f"][:3]
        return {"archive_mode": mode, "failed_count": int(failed or 0), "failing": failing == "t" and mode != "off"}

    def audit(self, event: str, detail: dict[str, Any]) -> None:
        code = (
            "import json, sys\nfrom tb_common.audit import AuditLog\ns = json.load(sys.stdin)\n"
            "AuditLog('/data/audit').append(s['event'], actor='backup', input_sha=s['sha'], detail=s['detail'])\n"
        )
        state = self.deploy / "site"
        state.mkdir(parents=True, exist_ok=True)
        f = state / f".audit-{event}.json"
        f.write_text(json.dumps({"event": event, "sha": detail.get("sha256") or "", "detail": detail}))
        try:
            self.box.run(self.box._c("exec", "-T", "orchestrator", "python", "-c", code), stdin_file=f)
            f.unlink(missing_ok=True)
        except Exception:  # the orchestrator is down: keep the event for the admin, never lose it
            with (state / "backup-audit-pending.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(f.read_text() + "\n")
            f.unlink(missing_ok=True)


def main_nightly(deploy: Path) -> int:
    from tools.trialbox import update

    ops = ComposeOps(deploy)
    cfg = config(deploy, update._env_file(deploy / ".env"))
    res = nightly(cfg, ops.make_backup(cfg), ops.audit, ops.pgbackrest if cfg.archive_on else None)
    for e in res["errors"]:
        print(f"backup-nightly: {e}")
    if res["file"]:
        print(f"backup-nightly: wrote {res['file']['name']} ({res['file']['bytes']} bytes) to "
              f"{len(res['file']['copies'])} targets")  # fmt: skip
    st = status(cfg, archiver=_try(ops.archiver) if cfg.archive_on else None)
    alert(cfg, st, ops.audit, send_cmd(cfg.alert_cmd))
    return 0 if res["ok"] else 1


def main_status(deploy: Path, as_json: bool = False, quiet: bool = False) -> int:
    from tools.trialbox import update

    cfg = config(deploy, update._env_file(deploy / ".env"))
    ops = ComposeOps(deploy)
    st = status(cfg, archiver=_try(ops.archiver) if cfg.archive_on else None)
    alert(cfg, st, ops.audit, send_cmd(cfg.alert_cmd))
    if quiet and st["level"] == "ok":
        return 0
    if as_json:
        print(json.dumps(st, indent=1, ensure_ascii=False))
    else:
        good = st["newest_good"]
        print(f"backup {st['level'].upper()}: newest good "
              + (f"{Path(good['path']).name} ({st['age_hours']} h old)" if good else "none"))  # fmt: skip
        for p in st["problems"]:
            print(f"  - {p}")
    return 0 if st["level"] == "ok" else 1


def _try(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as e:  # the db is down: that is an alert too
        return {"failing": True, "error": f"{type(e).__name__}: {str(e)[-200:]}"}
