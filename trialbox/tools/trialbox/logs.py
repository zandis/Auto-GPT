"""``trialbox logs``: retention of the service logs and the audit archive on the host (TB-PLAN-04 step 8, D-138).

    sudo python3 -m tools.trialbox logs daily          # cron, 00:20 (install.sh): collect, prune, archive-audit
    sudo python3 -m tools.trialbox logs collect [--day 2026-11-08]
    sudo python3 -m tools.trialbox logs prune
    sudo python3 -m tools.trialbox logs archive-audit

* **collect**: yesterday's log of every compose service (``docker compose logs --timestamps --since --until``, the
  site's day: 00:00 to 24:00 in ``TB_TZ``, the zone the audit day files use; D-315, OPS-036) into
  ``TB_LOG_DIR/services/<day>/<service>.log.gz`` (0640). The containers keep their own size-capped JSON logs
  (``TB_LOG_MAX_SIZE`` x ``TB_LOG_MAX_FILE``, provisional 100 MB x 10, D-389); the collected days are what the
  hospital's SIEM or an auditor reads (security review §6 q.25). Each collected day gets ``COVERAGE.json``: per
  service the bytes and lines of the day, the share of the container's cap they used, and whether the container's
  oldest kept line is later than the day's start while the container already ran then: a **log gap** (rotation ate
  the start of the day, OPS-034). A gap makes ``collect`` and ``daily`` exit 1 with what to raise. The numbers are
  the measurement the caps are re-sized from (G1 is parked: the caps are unmeasured until then).
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
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AUDIT_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
DEFAULT_AUDIT = "/var/lib/docker/volumes/trialbox_audit-data/_data"
DEFAULT_LOGS_DAYS = 365
# D-389 (OPS-034): the container log caps. PROVISIONAL and UNMEASURED: G1, the run they were to be sized from, is
# parked. The estimate they rest on is the review's (by reading): a 50,000-patient night, about 20 gateway calls a
# patient and about 300 bytes a request line, so about 300 MB in the busiest service for the night; docker's JSON
# wrapping adds about 64 bytes a line. 100 MB x 10 = 1 GB per container holds that night about 2.8 times, and a whole
# day whose daytime traffic equals the night about 1.4 times, between two collections (24 h 20 min). COVERAGE.json of
# each collected day is the measurement that replaces the estimate.
DEFAULT_LOG_MAX_SIZE = "100m"
DEFAULT_LOG_MAX_FILE = 10
NIGHT_ESTIMATE_BYTES = 50_000 * 20 * 300  # unmeasured (review 09-operations, OPS-034)
JSON_LINE_OVERHEAD = 64  # {"log":"...","stream":"stdout","time":"2026-11-08T00:00:00.000000000Z"}
HEADROOM_WARN = 0.75  # a day that used three quarters of the cap: raise the cap before it becomes a gap

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


def size_bytes(value: str) -> int:
    """A docker log size (``100m``, ``1g``, ``512k``, ``1048576``) in bytes."""
    m = re.fullmatch(r"\s*(\d+)\s*([kmg]?)b?\s*", value.lower())
    if not m:
        raise ValueError(f"not a log size: {value!r} (for example 100m)")
    return int(m.group(1)) * {"": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30}[m.group(2)]


def log_cap(env: dict[str, str]) -> int:
    """Bytes one container keeps: ``TB_LOG_MAX_SIZE`` x ``TB_LOG_MAX_FILE`` (the compose files read the same two)."""
    size = size_bytes((env.get("TB_LOG_MAX_SIZE") or DEFAULT_LOG_MAX_SIZE).strip("\"'"))
    files = int((env.get("TB_LOG_MAX_FILE") or str(DEFAULT_LOG_MAX_FILE)).strip("\"'"))
    return size * max(1, files)


def _instant(text: str) -> datetime | None:
    """Docker's RFC 3339 time (nanoseconds, ``Z``) as an aware datetime; None when it is not one."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$", text.strip())
    if not m:
        return None
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    tz = "+00:00" if m.group(3) == "Z" else m.group(3)
    return datetime.fromisoformat(f"{m.group(1)}.{frac}{tz}")


def oldest_kept(log_path: Path) -> tuple[datetime | None, int]:
    """The time of the oldest line docker still keeps for a container (the first line of its oldest rotated file,
    ``<id>-json.log.N`` with the highest N, gzip when the ``compress`` option is on, else of the live file) and how
    many rotated files there are."""
    rotated = []
    for f in log_path.parent.glob(log_path.name + ".*"):
        m = re.fullmatch(re.escape(log_path.name) + r"\.(\d+)(\.gz)?", f.name)
        if m:
            rotated.append((int(m.group(1)), f))
    for f in [f for _, f in sorted(rotated, reverse=True)] + [log_path]:
        try:
            opener = gzip.open if f.suffix == ".gz" else open
            with opener(f, "rt", encoding="utf-8") as fh:
                first = fh.readline()
        except OSError:
            continue
        if first.strip():
            try:
                return _instant(str(json.loads(first).get("time", ""))), len(rotated)
            except (ValueError, AttributeError):
                break
    return None, len(rotated)


INSPECT = (
    '{{.LogPath}}|{{index .HostConfig.LogConfig.Config "max-size"}}|{{index .HostConfig.LogConfig.Config "max-file"}}'
)


def coverage(deploy: Path, svc: str, since: str, runner: Runner, data: bytes, cap: int) -> dict[str, object]:
    """One service's day: its size, the share of the container's cap it used, and whether rotation already dropped
    lines of the day (a gap: docker deleted its oldest file and the oldest kept line is later than the day's start)."""
    lines = data.count(b"\n")
    used = len(data) + JSON_LINE_OVERHEAD * lines
    start = _instant(since)
    if start is None:
        raise ValueError(f"not an instant: {since}")
    docker = shlex.split(os.environ.get("TB_DOCKER") or "docker")
    gap, notes = False, []
    oldest: str | None = None
    try:
        ids = runner([*compose(deploy), "ps", "--all", "-q", svc]).decode().split()
    except RuntimeError as exc:
        ids, notes = [], [f"containers not listed: {exc}"]
    for cid in ids:
        try:
            info = runner([*docker, "inspect", "--format", INSPECT, cid]).decode().strip().split("|")
        except RuntimeError as exc:
            notes.append(f"{cid[:12]}: not inspected: {exc}")
            continue
        if len(info) != 3 or not info[0]:
            notes.append(f"{cid[:12]}: no json-file log to check")
            continue
        path, size, files = info
        try:
            max_file = int(files)
            cap = size_bytes(size) * max_file
        except ValueError:
            max_file = 1  # docker's default for json-file: one file, so its start is always the oldest kept line
        kept, rotated = oldest_kept(Path(path))
        if kept is None:
            notes.append(f"{cid[:12]}: log file not readable")
            continue
        oldest = kept.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        dropped = max_file > 1 and rotated >= max_file - 1
        if dropped and kept > start:
            gap = True
            notes.append(f"{cid[:12]}: rotation dropped lines; the oldest kept is {oldest}, after the day's start")
    out: dict[str, object] = {
        "bytes": len(data),
        "lines": lines,
        "cap_bytes": cap,
        "share_of_cap": round(used / cap, 3),
        "gap": gap,
    }
    if oldest:
        out["oldest_kept"] = oldest
    if notes:
        out["notes"] = notes
    return out


def compose(deploy: Path) -> list[str]:
    return shlex.split(os.environ.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}")


def site_day_bounds(day: date, tz: str) -> tuple[str, str]:
    """The UTC instants where the site's ``day`` starts and ends (``--since``/``--until`` of docker compose logs)."""
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time(0), zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(0), zone).astimezone(UTC)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(
    deploy: Path, day: date, log_dir: Path, runner: Runner = run_cmd, *, tz: str, cap: int | None = None
) -> list[Path]:
    """One gzip file per compose service for the site's ``day`` in ``tz`` (D-315), and the day's ``COVERAGE.json``
    (D-389): read it with :func:`gaps`."""
    services = runner([*compose(deploy), "ps", "--all", "--services"]).decode().split()
    out_dir = log_dir / "services" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o750)
    since, until = site_day_bounds(day, tz)
    written = []
    sizes: dict[str, bytes] = {}
    for svc in sorted(set(services)):
        data = runner([*compose(deploy), "logs", "--no-color", "--timestamps", "--since", since, "--until", until, svc])
        f = out_dir / f"{svc}.log.gz"
        tmp = f.with_suffix(".gz.part")
        with gzip.open(tmp, "wb") as gz:
            gz.write(data)
        os.chmod(tmp, 0o640)
        tmp.replace(f)
        written.append(f)
        sizes[svc] = data
    limit = cap if cap is not None else log_cap(env_file(deploy))
    report = {
        "day": day.isoformat(),
        "since": since,
        "until": until,
        "cap_bytes": limit,
        "caps_measured": False,  # D-389: provisional until a full night is measured (G1 parked)
        "services": {svc: coverage(deploy, svc, since, runner, data, limit) for svc, data in sizes.items()},
    }
    cov = out_dir / "COVERAGE.json"
    cov.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(cov, 0o640)
    return written


def gaps(log_dir: Path, day: date) -> tuple[list[str], list[str]]:
    """The services of a collected day with a log gap, and those that used over HEADROOM_WARN of their cap."""
    f = log_dir / "services" / day.isoformat() / "COVERAGE.json"
    if not f.is_file():
        return [], []
    svcs = json.loads(f.read_text(encoding="utf-8")).get("services", {})
    gap = sorted(s for s, c in svcs.items() if c.get("gap"))
    thin = sorted(s for s, c in svcs.items() if not c.get("gap") and c.get("share_of_cap", 0) > HEADROOM_WARN)
    return gap, thin


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
    tz = (env.get("TB_TZ") or os.environ.get("TB_TZ") or "").strip().strip("\"'")
    if not tz:  # no default zone (D-315): the day boundaries would be another site's
        print(f"logs {action}: TB_TZ is not set in {deploy / '.env'}: set it to site.tz", file=sys.stderr)
        return 1
    today = today or datetime.now(ZoneInfo(tz)).date()  # the site's day, as the audit day files (OPS-036)
    log_dir = Path(env.get("TB_LOG_DIR") or deploy / "logs")
    days = retention_days(deploy / "settings.yaml", "logs_days", DEFAULT_LOGS_DAYS)
    status = 0
    try:
        if action in ("collect", "daily"):
            d = date.fromisoformat(day) if day else today - timedelta(days=1)
            files = collect(deploy, d, log_dir, runner, tz=tz, cap=log_cap(env))
            print(f"collected {len(files)} service logs of {d} into {log_dir / 'services' / d.isoformat()}")
            gap, thin = gaps(log_dir, d)
            if thin:
                print(f"logs {action}: {', '.join(thin)} used over {HEADROOM_WARN:.0%} of the log cap on {d}: "
                      "raise TB_LOG_MAX_SIZE or TB_LOG_MAX_FILE in deploy/.env (D-389, RUNBOOK §2)",
                      file=sys.stderr)  # fmt: skip
            if gap:
                print(f"logs {action}: LOG GAP on {d} in {', '.join(gap)}: the container rotated away the start of "
                      f"the day before it was collected (COVERAGE.json). Raise TB_LOG_MAX_SIZE or TB_LOG_MAX_FILE in "
                      f"deploy/.env and run `docker compose up -d` (D-389, RUNBOOK §2)", file=sys.stderr)  # fmt: skip
                status = 1
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
    return status
