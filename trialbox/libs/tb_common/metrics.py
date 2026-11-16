"""Box health, its thresholds and ``/metrics`` (T-209a, D-379; review OPS-027, OPS-030, OPS-031, OPS-032, OPS-047).

Before this module only the backup age raised an alert. Now five checks give one health level (``ok``, ``warn`` or
``red``) that three places show:

* one **health line** at the top of the coordinator's morning mail (N2, ``console.notify``), so a missing or red
  line is seen by the CRC; a red line sends the mail even on a morning with nothing else in it;
* a **daily health mail** (``HEALTH``) to every administrator with a mailbox, every day at ``TB_HEALTH_MAIL_AT``
  (07:00), with one line per check;
* **``/metrics``** (Prometheus text) on the console and the orchestrator, scraped by the optional
  ``deploy/docker-compose.monitoring.yml``.

The checks and their thresholds (each can be moved in ``deploy/.env``):

==================  ==========================================================================================
``canary``          red when the last model self-test failed or a woken model failed its wake check (note
                    reading was off last night, OPS-032); warn when it has not run, is stale or checked one model
``backup``          red when ``backup-status`` alerts (the newest good backup is older than
                    ``TB_BACKUP_MAX_AGE_HOURS``, 36 h, or the last nightly run failed, D-187, D-274)
``backup_verified`` red when no ``backup-verify`` with the private key succeeded for ``TB_HEALTH_VERIFIED_DAYS``
                    (100) days, warn after 90 or when none ever did (OPS-047); ``backup-verify`` writes
                    ``deploy/site/backup-verified.json``, and so does ``restore-drill`` (T-730d, D-892): red
                    when the last drill failed
``disk:<path>``     each disk the box writes to: warn over ``TB_HEALTH_DISK_WARN`` (70 %), red over
                    ``TB_HEALTH_DISK_RED`` (85 %) (OPS-031)
``certificate``     the hospital's certificate (``TB_TLS_CERT_FILE``): red when it ends within
                    ``TB_HEALTH_CERT_RED_DAYS`` (30) days, warn within 45 (OPS-030); Caddy's own certificate
                    (``TB_TLS_MODE=internal``) renews itself and is ok
``optout_worker``   red when the opt-out worker's last tick failed or none completed for three intervals (D-441,
                    from the orchestrator's ``/models``); not shown when the orchestrator does not report it
``desktop_gpu``     a Windows workstation only (WSL2; NEW-WIN-6, D-607): the card memory held by programs outside
                    TrialBox (the desktop's) against the card's spare memory, which is the card less what the
                    serving record measured for the models. Warn over ``TB_HEALTH_DESKTOP_GPU_WARN`` (70) percent,
                    red over ``TB_HEALTH_DESKTOP_GPU_RED`` (85): the model servers would not fit after a restart
``facts``           warn when the host's runner has not written the facts for an hour (the checks above are old)
==================  ==========================================================================================

The host facts (backup, verified, disks, certificate) are gathered on the host by ``trialbox ops run`` every minute
(:func:`host_facts`, written into the operations status the console reads); the canary comes from the
orchestrator's ``/models``. Nothing here reads a patient row, a secret or a key: the certificate file is public.
Standard library only (``cryptography`` when it is there), so the host's ``python3`` runs it.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OK, WARN, RED = "ok", "warn", "red"
RANK = {OK: 0, WARN: 1, RED: 2}
VERIFIED_FILE = "backup-verified.json"  # under deploy/site, next to backup-last.json (T-117b)
FACTS_STALE_H = 1.0
# NEW-OPS-8 (OPS-009, D-561): facts that are missing or older than FACTS_STALE_H are red, not a warning that never
# ends: without the runner a full disk, an old backup and an ending certificate are never reported
RUNNER_HINT = "is trialbox-ops.timer on? systemctl enable --now trialbox-ops.timer"


def _num(env: Mapping[str, str], key: str, default: float) -> float:
    try:
        v = float(str(env.get(key) or default).strip())
    except ValueError:
        return default
    return v if math.isfinite(v) and v >= 0 else default


@dataclass(frozen=True)
class Thresholds:
    disk_warn_pct: float = 70.0
    disk_red_pct: float = 85.0
    cert_warn_days: float = 45.0
    cert_red_days: float = 30.0
    backup_max_age_h: float = 36.0
    verified_warn_days: float = 90.0
    verified_red_days: float = 100.0
    desktop_gpu_warn_pct: float = 70.0
    desktop_gpu_red_pct: float = 85.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Thresholds:
        e = os.environ if env is None else env
        red_days = _num(e, "TB_HEALTH_VERIFIED_DAYS", 100.0)
        return cls(
            disk_warn_pct=_num(e, "TB_HEALTH_DISK_WARN", 70.0),
            disk_red_pct=_num(e, "TB_HEALTH_DISK_RED", 85.0),
            cert_warn_days=_num(e, "TB_HEALTH_CERT_WARN_DAYS", 45.0),
            cert_red_days=_num(e, "TB_HEALTH_CERT_RED_DAYS", 30.0),
            backup_max_age_h=_num(e, "TB_BACKUP_MAX_AGE_HOURS", 36.0),
            verified_warn_days=max(0.0, red_days - 10.0),
            verified_red_days=red_days,
            desktop_gpu_warn_pct=_num(e, "TB_HEALTH_DESKTOP_GPU_WARN", 70.0),
            desktop_gpu_red_pct=_num(e, "TB_HEALTH_DESKTOP_GPU_RED", 85.0),
        )


@dataclass(frozen=True)
class Check:
    name: str  # canary | backup | backup_verified | disk:<path> | certificate | optout_worker | facts
    level: str
    text: str  # one plain sentence, no patient data
    value: float | None = None  # the measure behind it (hours, days, percent), for /metrics


@dataclass(frozen=True)
class Health:
    at: datetime
    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def level(self) -> str:
        return max((c.level for c in self.checks), key=RANK.__getitem__, default=OK)

    def worst(self) -> list[Check]:
        lv = self.level
        return [c for c in self.checks if c.level == lv] if lv != OK else []

    def details(self) -> str:
        """What the line says after its level: the red (else the warn) checks, or a short all-green summary."""
        bad = self.worst()
        if bad:
            return "; ".join(c.text for c in bad)
        return "; ".join(c.text for c in self.checks if not c.name.startswith("disk:")) + (
            f"; fullest disk {self.fullest_disk():.0f} %" if self.fullest_disk() is not None else ""
        )

    def fullest_disk(self) -> float | None:
        vals = [c.value for c in self.checks if c.name.startswith("disk:") and c.value is not None]
        return max(vals) if vals else None

    def line(self) -> str:
        """The one health line (English); ``console.notify`` puts the translated level before :meth:`details`."""
        return f"TrialBox health: {self.level.upper()}: {self.details()}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(timespec="seconds"),
            "level": self.level,
            "checks": [{"name": c.name, "level": c.level, "text": c.text, "value": c.value} for c in self.checks],
        }


# ------------------------------------------------------------------------------------------------ the checks
def _when(v: object) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def check_canary(canary: Mapping[str, Any] | None) -> Check:
    """From the orchestrator's ``/models`` ``canary`` (``orchestrator.canary_gate.status``)."""
    if canary is None:
        return Check("canary", WARN, "model self-test unknown: the orchestrator did not answer")
    code = str(canary.get("code") or "")
    at = str(canary.get("at") or "?")
    if canary.get("ok") is False or code == "failed":
        return Check("canary", RED, f"model self-test failed at {at}: note reading was off last night", 0.0)
    if code == "wake":
        return Check("canary", RED, "a woken model failed its wake check: note reading is off until the next pass", 0.0)
    if code == "off" and canary.get("ok") is None:
        return Check("canary", OK, "model self-test off on this box")
    if code in ("none", "stale", "single"):
        why = {"none": "has not run yet", "stale": f"last passed at {at}, too long ago",
               "single": "checked one model only"}[code]  # fmt: skip
        return Check("canary", WARN, f"model self-test {why}: note answers cannot exclude", 0.0)
    return Check("canary", OK, f"model self-test passed at {at}", 1.0)


def check_optout(worker: Mapping[str, Any], now: datetime) -> Check:
    """From the orchestrator's ``/models`` ``optout_worker`` (``datacore.optout_worker.status``): ``every`` (minutes;
    0 off), ``started``, ``ok_at`` (the last tick that completed), ``failed`` (what the last tick could not do)."""
    every = float(worker.get("every") or 0)
    if every <= 0:
        return Check("optout_worker", RED, "the opt-out worker is off: an opt-out does not reach the stores")
    if worker.get("failed"):
        return Check("optout_worker", RED, f"the opt-out worker's last tick failed ({', '.join(worker['failed'])})")
    ok_at = _when(worker.get("ok_at"))
    since = ok_at or _when(worker.get("started"))
    if since is None:
        return Check("optout_worker", WARN, "the opt-out worker has not reported")
    age = (now - since).total_seconds() / 60
    if age > 3 * every:
        return Check("optout_worker", RED, f"no opt-out worker tick completed for {age:.0f} min", age)
    if ok_at is None:
        return Check("optout_worker", WARN, "the opt-out worker has not completed a tick yet", age)
    return Check("optout_worker", OK, f"opt-out worker ticked {age:.0f} min ago", age)


def check_derive(info: Mapping[str, Any]) -> Check:
    """D-442, from the orchestrator's ``/models`` ``derive_batch`` (``orchestrator.derive.status``): ``flag`` (the
    stored-score read on or off), ``current`` (the snapshot the lake serves), ``last`` (the newest derive batch:
    ``snapshot``, ``finished_at``, ``failed``). Red only while the flag is on: then a snapshot without a finished
    batch sends every score criterion to "needs information"."""
    bad = RED if info.get("flag") == "on" else WARN
    last = info.get("last") or None
    current = info.get("current")
    if last is None:
        return Check("derive_batch", bad, "no derive batch has run: the stored scores are not computed")
    if not last.get("finished_at"):
        return Check("derive_batch", bad, f"the derive batch of {last.get('snapshot')} did not finish")
    if current and last.get("snapshot") != current:
        return Check("derive_batch", bad, f"the served snapshot {current} has no derive batch yet")
    if info.get("lake_unread"):  # D-709: the lake could not be asked; "finished" would claim it is the served one
        return Check("derive_batch", WARN, "the lake could not be asked which snapshot it serves: whether the newest "
                     f"derive batch ({last.get('snapshot')}) is for it is not known")  # fmt: skip
    if int(last.get("failed") or 0):
        return Check("derive_batch", WARN, f"the derive batch of {last.get('snapshot')} failed for {last['failed']} "
                     "patient(s): their scores read as unknown")  # fmt: skip
    return Check("derive_batch", OK, f"derive batch of {last.get('snapshot')} finished")


def check_backup(backup: Mapping[str, Any] | None, th: Thresholds) -> Check:
    """From ``tools.trialbox.backup_schedule.status`` (T-117b): its level, age and first problem."""
    if not backup:
        return Check("backup", WARN, "backup state unknown: the host runner has not reported it")
    age = backup.get("age_hours")
    value = float(age) if isinstance(age, int | float) else None
    probs = [str(p) for p in backup.get("problems") or []]
    if backup.get("level") == "alert" or (value is not None and value > th.backup_max_age_h):
        why = probs[0] if probs else f"the newest good backup is {value:.0f} h old"
        return Check("backup", RED, f"backup: {why}", value)
    if value is None:
        return Check("backup", WARN, "backup: no good backup found", None)
    return Check("backup", OK, f"backup {value:.0f} h old", value)


def check_verified(verified: Mapping[str, Any] | None, now: datetime, th: Thresholds) -> Check:
    failed = _when((verified or {}).get("drill_failed_at"))
    at = _when((verified or {}).get("at"))
    if failed is not None and (at is None or failed >= at):  # D-892: a failed restore drill, until one passes
        why = f"the last restore drill ({failed:%Y-%m-%d}) failed: {(verified or {}).get('drill_error') or '?'}"
        return Check("backup_verified", RED, why[:300], None)
    if at is None:
        return Check("backup_verified", WARN, "no backup has been verified with the private key yet (backup-verify)")
    days = round((now - at).total_seconds() / 86400, 1)
    if days > th.verified_red_days:
        why = f"last key check of a backup {days:.0f} days ago (limit {th.verified_red_days:.0f})"
        return Check("backup_verified", RED, why, days)
    if days > th.verified_warn_days:
        return Check("backup_verified", WARN, f"last key check of a backup {days:.0f} days ago", days)
    what = "restore drill passed" if (verified or {}).get("drill") else "backup verified"
    return Check("backup_verified", OK, f"{what} {days:.0f} days ago", days)


def check_disks(disks: Sequence[Mapping[str, Any]], th: Thresholds) -> list[Check]:
    out = []
    for d in disks:
        pct = d.get("used_pct")
        if not isinstance(pct, int | float):
            continue
        path = str(d.get("path") or "?")
        level = RED if pct > th.disk_red_pct else WARN if pct > th.disk_warn_pct else OK
        out.append(Check(f"disk:{path}", level, f"disk {path} {pct:.0f} % full", float(pct)))
    return out


def check_cert(cert: Mapping[str, Any] | None, now: datetime, th: Thresholds) -> Check:
    c = cert or {}
    mode = str(c.get("mode") or "internal")
    if mode == "internal":
        return Check("certificate", OK, "certificate renewed by the box itself")
    end = _when(c.get("not_after"))
    if end is None:
        return Check("certificate", WARN, f"certificate end unknown ({c.get('error') or 'no TB_TLS_CERT_FILE'})")
    days = round((end - now).total_seconds() / 86400, 1)
    if days <= th.cert_red_days:
        what = "ended" if days < 0 else f"ends in {max(days, 0):.0f} days"
        return Check("certificate", RED, f"certificate {what} ({end:%Y-%m-%d}): ask hospital IT for the next one", days)
    if days <= th.cert_warn_days:
        return Check("certificate", WARN, f"certificate ends in {days:.0f} days ({end:%Y-%m-%d})", days)
    return Check("certificate", OK, f"certificate {days:.0f} days left", days)


def check_desktop_gpu(gpu: Mapping[str, Any], models_up: bool, th: Thresholds) -> Check:
    """NEW-WIN-6 (D-607; plan v7 section 2.3 rule 6): the workstation's card is shared with the desktop.

    ``gpu``: :func:`gpu_facts`. Inside WSL2 the card reports the memory held by every program, Windows' too, but
    not by which. What is outside TrialBox is therefore what is used less what the serving record measured for the
    models, when the models are up (``models_up``: the self-test passed); all of it when they are not. It is set
    against the card's spare memory: the card less the models' measured share."""
    name = "desktop_gpu"
    used, total, models = gpu.get("used_mib"), gpu.get("total_mib"), gpu.get("models_mib")
    if not isinstance(used, (int, float)) or not isinstance(total, (int, float)) or total <= 0:
        return Check(
            name, WARN, "the graphics card's memory could not be read (nvidia-smi): the desktop's use of it is unknown"
        )
    gib = 1024.0
    if not isinstance(models, (int, float)) or models <= 0:
        return Check(name, WARN, f"{used / gib:.1f} of {total / gib:.1f} GiB of the graphics card in use; no serving "
                     "record says what the models need, so the desktop's share was not judged")  # fmt: skip
    spare = total - models
    if spare <= 0:
        return Check(name, RED, f"the models were measured at {models / gib:.1f} GiB and the card has "
                     f"{total / gib:.1f} GiB: nothing is left for the desktop")  # fmt: skip
    outside = max(0.0, used - models) if models_up else float(used)
    pct = 100.0 * outside / spare
    said = (f"programs outside TrialBox hold {outside / gib:.1f} GiB of the graphics card; {spare / gib:.1f} GiB is "
            f"spare beside the models ({pct:.0f} %)")  # fmt: skip
    if pct >= th.desktop_gpu_red_pct:
        return Check(name, RED, f"{said}: the model servers may not fit after a restart. Close the program that "
                     "uses the card (a game, rendering, another model)", pct)  # fmt: skip
    if pct >= th.desktop_gpu_warn_pct:
        return Check(name, WARN, said, pct)
    return Check(name, OK, said, pct)


def evaluate(
    facts: Mapping[str, Any] | None,
    canary: Mapping[str, Any] | None,
    now: datetime,
    th: Thresholds | None = None,
    optout: Mapping[str, Any] | None = None,
    derive: Mapping[str, Any] | None = None,
) -> Health:
    """The health at ``now`` from the host facts (:func:`host_facts`), the orchestrator's canary status and, when it
    reports one, its opt-out worker (:func:`check_optout`)."""
    th = th or Thresholds.from_env()
    f = facts or {}
    checks = [check_canary(canary), check_backup(f.get("backup"), th), check_verified(f.get("verified"), now, th)]
    if optout is not None:
        checks.append(check_optout(optout, now))
    if derive is not None:  # D-442: the derive batch of the served snapshot
        checks.append(check_derive(derive))
    checks += check_disks(f.get("disks") or [], th)
    checks.append(check_cert(f.get("cert"), now, th))
    if isinstance(f.get("gpu"), Mapping):  # a Windows workstation (WSL2) only
        checks.append(check_desktop_gpu(f["gpu"], check_canary(canary).level == OK and canary is not None, th))
    seen = _when(f.get("at"))
    if seen is None:
        checks.append(Check("facts", RED, f"the host runner has not written the health facts ({RUNNER_HINT})"))
    elif abs(age := (now - seen).total_seconds() / 3600) > FACTS_STALE_H:  # dated ahead of the clock: not fresh
        checks.append(Check("facts", RED, f"the host's health facts are {age:.0f} h old ({RUNNER_HINT})", age))
    return Health(now, tuple(checks))


# ------------------------------------------------------------------------------------------------ the host facts
def disk_paths(deploy: Path, env: Mapping[str, str]) -> list[Path]:
    """The box's own disk, Docker's root, the install folder, every backup target and ``TB_HEALTH_DISKS``; one path
    per device."""
    raw = [Path("/"), Path(env.get("TB_DOCKER_ROOT") or "/var/lib/docker"), deploy]
    for key in ("TB_BACKUP_TARGETS", "TB_HEALTH_DISKS"):
        raw += [Path(t) for t in str(env.get(key) or "").replace(",", " ").split() if t]
    out: list[Path] = []
    devs: set[int] = set()
    for p in raw:
        try:
            dev = p.stat().st_dev
        except OSError:
            continue
        if dev not in devs:
            devs.add(dev)
            out.append(p)
    return out


def disk_usage(paths: Iterable[Path]) -> list[dict[str, Any]]:
    out = []
    for p in paths:
        try:
            u = shutil.disk_usage(p)
        except OSError:
            continue
        if u.total:
            out.append({"path": str(p), "used_pct": round(100.0 * u.used / u.total, 1), "free": u.free})
    return out


def cert_not_after(path: Path) -> datetime:
    """The end of the first certificate of a PEM file (public; never a key)."""
    try:
        from cryptography import x509

        return x509.load_pem_x509_certificates(path.read_bytes())[0].not_valid_after_utc
    except ImportError:  # the host's python3 without cryptography: the standard library's own decoder
        import ssl

        decoded = ssl._ssl._test_decode_cert(str(path))  # type: ignore[attr-defined]
        return datetime.fromtimestamp(ssl.cert_time_to_seconds(decoded["notAfter"]), UTC)


def cert_facts(env: Mapping[str, str]) -> dict[str, Any]:
    mode = (env.get("TB_TLS_MODE") or "internal").strip().lower()
    if mode == "internal":
        return {"mode": mode}
    path = (env.get("TB_TLS_CERT_FILE") or "").strip()
    if not path:
        return {"mode": mode, "error": "TB_TLS_CERT_FILE is not set"}
    try:
        return {"mode": mode, "not_after": cert_not_after(Path(path)).isoformat(timespec="seconds")}
    except Exception as exc:  # unreadable or not PEM: reported, never raised
        return {"mode": mode, "error": f"TB_TLS_CERT_FILE is not readable as PEM ({type(exc).__name__})"}


def read_verified(deploy: Path) -> dict[str, Any] | None:
    try:
        d = json.loads((deploy / "site" / VERIFIED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def record_verified(deploy: Path, result: Mapping[str, Any], now: datetime | None = None) -> Path:
    """After a successful ``backup-verify`` (OPS-047): when, which file (name and sha256) and the backup's own date.
    No row and no content; 0600 like ``backup-last.json``."""
    now = now or datetime.now(UTC)
    out = deploy / "site" / VERIFIED_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": now.isoformat(timespec="seconds"), "file": str(result.get("file") or ""),
           "sha256": str(result.get("sha256") or ""), "created_at": str(result.get("created_at") or ""),
           "site": str(result.get("site") or "")}  # fmt: skip
    tmp = out.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
    os.replace(tmp, out)
    return out


def record_drill(deploy: Path, res: Mapping[str, Any], now: datetime | None = None) -> Path:
    """T-730d (D-892): a restore drill's result in the key-check record. A pass is a key check (``at`` and the file,
    as ``record_verified``) with what was compared; a fail keeps the last good check and adds ``drill_failed_at`` and
    ``drill_error``, which ``check_verified`` shows red until a drill passes. Never the key or its path; no rows."""
    if res.get("ok"):
        out = record_verified(deploy, {**res, "file": res.get("file")}, _when(res.get("at")) or now)
        rec = read_verified(deploy) or {}
        rec["drill"] = {db: {"tables": int(d.get("tables", 0)), "rows": int(d.get("rows", 0))}
                        for db, d in (res.get("databases") or {}).items()}  # fmt: skip
    else:
        out = deploy / "site" / VERIFIED_FILE
        out.parent.mkdir(parents=True, exist_ok=True)
        rec = {k: v for k, v in (read_verified(deploy) or {}).items() if not k.startswith("drill")}
        rec["drill_failed_at"] = str(res.get("at") or (now or datetime.now(UTC)).isoformat(timespec="seconds"))
        rec["drill_error"] = str(res.get("error") or "")[:300]
        rec["drill_file"] = str(res.get("file") or "")
    tmp = out.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
    os.replace(tmp, out)
    return out


def _card_memory() -> tuple[int, int] | None:
    """(used, total) MiB of the first card, as nvidia-smi reports them; None when it does not answer."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    line = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2 or not all(p.isascii() and p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def gpu_facts(
    deploy: Path,
    env: Mapping[str, str],
    *,
    proc: Path = Path("/proc"),
    card: Any = None,
) -> dict[str, Any] | None:
    """The card's memory on a Windows workstation, for :func:`check_desktop_gpu`; ``None`` on any other host.

    ``models_mib`` is ``memory_used_mib`` of the box's serving record: the one of ``TB_GPU_PROFILE``, else the only
    record there is; the site's own (``deploy/site``) before the vendor's (``deploy/measured``). ``card``: a
    callable in place of nvidia-smi (tests)."""
    try:
        kernel = (proc / "sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return None
    if "microsoft" not in kernel or "wsl2" not in kernel:
        return None
    got = (card or _card_memory)()
    profile = str(env.get("TB_GPU_PROFILE") or "").strip()
    models: float | None = None
    for folder in (deploy / "site", deploy / "measured"):
        pattern = f"serving_config.{profile}.json" if profile and profile != "auto" else "serving_config.*.json"
        records = sorted(folder.glob(pattern))
        if len(records) != 1:
            if records:
                break  # two records and no profile: never a guess
            continue
        try:
            value = json.loads(records[0].read_text(encoding="utf-8")).get("memory_used_mib")
        except (OSError, ValueError, AttributeError):
            value = None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            models = float(value)
        break
    return {"used_mib": got[0] if got else None, "total_mib": got[1] if got else None, "models_mib": models}


def host_facts(
    deploy: Path,
    env: Mapping[str, str],
    backup: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """What ``trialbox ops run`` writes into the operations status each minute. ``backup``: the T-117b
    ``backup-status`` result (level, age_hours, problems)."""
    now = now or datetime.now(UTC)
    b = dict(backup) if backup else None
    return {
        "at": now.isoformat(timespec="seconds"),
        "backup": None if b is None else {k: b.get(k) for k in ("level", "age_hours", "max_age_hours", "problems")},
        "verified": read_verified(deploy),
        "disks": disk_usage(disk_paths(deploy, env)),
        "cert": cert_facts(env),
        "gpu": gpu_facts(deploy, env),
    }


# ------------------------------------------------------------------------------------------------ /metrics
def _label(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def prometheus(health: Health, service: str) -> str:
    """The Prometheus text format (0.0.4) of one health: the levels (0 ok, 1 warn, 2 red) and each measure."""
    lines = [
        "# HELP tb_health_level Box health: 0 ok, 1 warn, 2 red (T-209a).",
        "# TYPE tb_health_level gauge",
        f'tb_health_level{{service="{_label(service)}"}} {RANK[health.level]}',
        "# HELP tb_health_check_level One check: 0 ok, 1 warn, 2 red.",
        "# TYPE tb_health_check_level gauge",
    ]
    lines += [f'tb_health_check_level{{check="{_label(c.name)}"}} {RANK[c.level]}' for c in health.checks]
    measures = {
        "canary": ("tb_canary_ok", "1 when the last model self-test passed."),
        "backup": ("tb_backup_age_hours", "Age of the newest good backup, hours."),
        "backup_verified": ("tb_backup_verified_age_days", "Days since a backup was verified with the key."),
        "certificate": ("tb_certificate_days_left", "Days until the hospital certificate ends."),
    }
    for c in health.checks:
        if c.value is None:
            continue
        if c.name.startswith("disk:"):
            continue
        if c.name in measures:
            name, help_ = measures[c.name]
            lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge", f"{name} {c.value:g}"]
    disks = [c for c in health.checks if c.name.startswith("disk:") and c.value is not None]
    if disks:
        lines += ["# HELP tb_disk_used_percent Used share of a disk the box writes to.",
                  "# TYPE tb_disk_used_percent gauge"]  # fmt: skip
        lines += [f'tb_disk_used_percent{{path="{_label(c.name[5:])}"}} {c.value:g}' for c in disks]
    lines.append(f"tb_health_evaluated_timestamp_seconds {health.at.timestamp():.0f}")
    return "\n".join(lines) + "\n"
