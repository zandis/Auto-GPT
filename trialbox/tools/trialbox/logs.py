"""``trialbox logs``: retention of the service logs and the audit archive on the host (TB-PLAN-04 step 8, D-138).

    sudo python3 -m tools.trialbox logs daily          # cron, 00:20 (install.sh): collect, prune, archive-audit
    sudo python3 -m tools.trialbox logs collect [--day 2026-11-08]
    sudo python3 -m tools.trialbox logs prune
    sudo python3 -m tools.trialbox logs archive-audit

* **collect**: yesterday's log of every compose service (``docker compose logs --timestamps --since --until``, UTC
  day) into ``TB_LOG_DIR/services/<day>/<service>.log.gz`` (0640). The containers keep their own size-capped JSON
  logs (50 MB x 5); the collected days are what the hospital's SIEM or an auditor reads (security review §6 q.25).
* **prune**: collected days older than ``settings.yaml`` ``retention.logs_days`` are deleted.
* **archive-audit**: every closed day file of the audit chain (``TB_AUDIT_HOST_DIR``, default the ``audit-data``
  volume) is copied, gzip-compressed, to ``TB_AUDIT_ARCHIVE_DIR/<year>/<day>.jsonl.gz`` with its sha256 in
  ``MANIFEST.sha256``; the chain is verified before and the archived copy after. Nothing in the audit folder is ever
  deleted or changed: the archive is a second copy, for the ten years and beyond (``retention.audit_years``).

Mail logs, job outputs and attachments are pruned inside the box by the daily RETENTION job
(``services/orchestrator/scenarios/retention.py``). Standard library only (the host's python3).
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AUDIT_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
DEFAULT_AUDIT = "/var/lib/docker/volumes/trialbox_audit-data/_data"
DEFAULT_LOGS_DAYS = 365

Runner = Callable[[Sequence[str]], bytes]


def run_cmd(argv: Sequence[str]) -> bytes:
    r = subprocess.run(list(argv), capture_output=True, check=False, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(
            f"{shlex.join(list(argv)[:6])} ... exit {r.returncode}: {r.stderr.decode(errors='replace')[-300:]}"
        )
    return r.stdout


def env_file(deploy: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    f = deploy / ".env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def retention_days(settings: Path, key: str, default: int) -> int:
    """``retention.<key>`` from settings.yaml without a YAML library: the block form the wizard writes
    (``retention:`` then indented ``key: n``) and the flow form of the example (``retention: {key: n, ...}``)."""
    if not settings.is_file():
        return default
    lines = settings.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("retention:"):
            continue
        flow = line.partition(":")[2].strip()
        if flow.startswith("{"):
            m = re.search(rf"(?:^|[{{,\s]){re.escape(key)}\s*:\s*(\d+)", flow)
            return int(m.group(1)) if m else default
        for sub in lines[i + 1 :]:
            if sub and not sub[0].isspace():
                break
            m = re.match(rf"^\s+{re.escape(key)}\s*:\s*(\d+)\s*(?:#.*)?$", sub)
            if m:
                return int(m.group(1))
        return default
    return default


def compose(deploy: Path) -> list[str]:
    return shlex.split(os.environ.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}")


def collect(deploy: Path, day: date, log_dir: Path, runner: Runner = run_cmd) -> list[Path]:
    """One gzip file per compose service for ``day`` (UTC)."""
    services = runner([*compose(deploy), "ps", "--all", "--services"]).decode().split()
    out_dir = log_dir / "services" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o750)
    since, until = f"{day.isoformat()}T00:00:00Z", f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z"
    written = []
    for svc in sorted(set(services)):
        data = runner([*compose(deploy), "logs", "--no-color", "--timestamps", "--since", since, "--until", until, svc])
        f = out_dir / f"{svc}.log.gz"
        tmp = f.with_suffix(".gz.part")
        with gzip.open(tmp, "wb") as gz:
            gz.write(data)
        os.chmod(tmp, 0o640)
        tmp.replace(f)
        written.append(f)
    return written


def prune(log_dir: Path, days: int, today: date) -> list[str]:
    """Delete collected days older than ``days``; return the days deleted."""
    gone = []
    base = log_dir / "services"
    cutoff = today - timedelta(days=days)
    for d in sorted(base.iterdir()) if base.is_dir() else []:
        if d.is_dir() and DAY.match(d.name) and date.fromisoformat(d.name) < cutoff:
            shutil.rmtree(d)
            gone.append(d.name)
    return gone


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _audit_lib() -> object:
    sys.path.insert(0, str(ROOT / "libs"))
    from tb_common import audit  # standard library only

    return audit


def _verify(
    directory: Path, anchor: dict[str, object] | None = None, require_head: bool = True
) -> tuple[bool, str, object]:
    res = _audit_lib().verify(directory, anchor=anchor, require_head=require_head)  # type: ignore[attr-defined]
    return bool(res.ok), "; ".join(res.errors[:3]), res


def _gunzip(path: Path) -> bytes:
    with gzip.open(path, "rb") as fh:
        return fh.read()


def archive_audit(audit: Path, archive: Path, today: date) -> list[str]:
    """Copy each closed audit day file (before ``today``) not yet in the archive; never touch ``audit``. The chain
    must verify first, against its own head anchor and against the archive's ``HEAD.json`` (where the chain stood at
    the end of the last archived day, D-272), and the archive (decompressed) must verify after. A closed day that
    changed since it was archived is refused, never overwritten: only a day that grew (its archived copy is the start
    of the file, the newest file still being written past midnight) is copied again."""
    import json

    head_file = archive / "HEAD.json"
    anchor = json.loads(head_file.read_text(encoding="utf-8")) if head_file.is_file() else None
    ok, why, _ = _verify(audit, anchor)
    if not ok:
        raise RuntimeError(f"the audit chain in {audit} does not verify ({why}): nothing archived, check it first")
    archive.mkdir(parents=True, exist_ok=True)
    manifest = archive / "MANIFEST.sha256"
    known: dict[str, str] = {}
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            h, _, name = line.partition("  ")
            known[name] = h
    present = {f.name for f in audit.iterdir() if AUDIT_DAY.match(f.name)}
    gone = sorted(set(known) - present)
    if gone:
        raise RuntimeError(f"archived day files are missing from {audit}: {', '.join(gone)}: nothing archived")
    todo: list[tuple[Path, str, Path]] = []
    for f in sorted(audit.iterdir()):
        m = AUDIT_DAY.match(f.name)
        if not m or m.group(1) >= today.isoformat():
            continue
        h = _sha(f)
        if known.get(f.name) == h:
            continue
        dest = archive / m.group(1)[:4] / f"{f.name}.gz"
        if f.name in known:
            old = _gunzip(dest) if dest.is_file() else b""
            if not old or not f.read_bytes().startswith(old):
                raise RuntimeError(
                    f"the closed day {f.name} changed since it was archived (sha256 {known[f.name][:16]}, now "
                    f"{h[:16]}): the archived copy is kept and nothing is archived; compare the two"
                )
        todo.append((f, h, dest))
    done = []
    for f, h, dest in todo:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".gz.part")
        with f.open("rb") as src, gzip.open(tmp, "wb") as gz:
            shutil.copyfileobj(src, gz)
        tmp.replace(dest)
        known[f.name] = h
        done.append(f.name)
    manifest.write_text("".join(f"{h}  {n}\n" for n, h in sorted(known.items())), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="tb-audit-archive-") as tmpd:
        for packed in sorted(archive.rglob("*.jsonl.gz")):
            with gzip.open(packed, "rb") as unpacked, (Path(tmpd) / packed.name[:-3]).open("wb") as out:
                shutil.copyfileobj(unpacked, out)
        for name, h in known.items():
            if _sha(Path(tmpd) / name) != h:
                raise RuntimeError(f"archived {name} differs from its manifest line")
        ok, why, res = _verify(Path(tmpd), anchor, require_head=False)
        if not ok:
            raise RuntimeError(f"the archived chain does not verify ({why})")
    if known:
        last = max(known)
        new = {"file": last, "hash": res.last_hash, "lines": res.lines}  # type: ignore[attr-defined]
        tmp_head = archive / ".HEAD.json.tmp"
        tmp_head.write_text(json.dumps(new, sort_keys=True) + "\n", encoding="utf-8")
        tmp_head.replace(head_file)
    return done


def main_action(action: str, deploy: Path, day: str | None, runner: Runner = run_cmd, today: date | None = None) -> int:
    env = env_file(deploy)
    today = today or datetime.now(UTC).date()
    log_dir = Path(env.get("TB_LOG_DIR") or deploy / "logs")
    days = retention_days(deploy / "settings.yaml", "logs_days", DEFAULT_LOGS_DAYS)
    try:
        if action in ("collect", "daily"):
            d = date.fromisoformat(day) if day else today - timedelta(days=1)
            files = collect(deploy, d, log_dir, runner)
            print(f"collected {len(files)} service logs of {d} into {log_dir / 'services' / d.isoformat()}")
        if action in ("prune", "daily"):
            gone = prune(log_dir, days, today)
            print(f"service logs kept {days} days; deleted: {', '.join(gone) or 'none'}")
        if action in ("archive-audit", "daily"):
            audit = Path(env.get("TB_AUDIT_HOST_DIR") or DEFAULT_AUDIT)
            archive = Path(env.get("TB_AUDIT_ARCHIVE_DIR") or log_dir / "audit-archive")
            done = archive_audit(audit, archive, today)
            print(f"audit archived to {archive}: {len(done)} day files new or changed; the box's copy untouched")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"logs {action}: {exc}", file=sys.stderr)
        return 1
    return 0
