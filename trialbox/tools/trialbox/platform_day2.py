"""``trialbox platform-day2``: the day-2 jobs of the platform form (T-633, D-416; OPS-050, OPS-068, OPS-069).

On the appliance, backup, logs and the audit archive run from host cron with ``docker compose exec`` (D-187,
D-138); none of that exists in a namespace. ``deploy/platform/base/day2.yaml`` has them as CronJobs, and these are
the commands they run (RUNBOOK §26):

    platform-day2 snapshot-prepare --spool /spool          # backup, init 1: the psql script of each database
    sh pg-snapshot.sh /spool                               # backup, init 2: the database image dumps in a snapshot
    platform-day2 backup --share /backup/trialbox --public <backup.pub>
    platform-day2 restore --share /backup/trialbox --key <backup.key> --public <backup.pub> --keep-to <dir>
    platform-day2 pg <psql|pg_dump|pg_restore> ...          # the restore's database tools, through the spool
    platform-day2 logs --log-dir /logs --audit /vol/audit --archive /logs/audit-archive --settings <settings.yaml>
    platform-day2 update-overlay --site <overlay> --release <new release.json> --out <dir>

**Backup.** The file is the appliance's ``.tbbak`` (``backup.py``, layout 2): a backup of the platform restores on an
appliance and the other way round (the interim cloud's migration, D-211), under the same directory names
(``backup.DEFAULT_DIRS``). The Python image has no PostgreSQL client (D-23), so the dump is the database image's: the
first init container writes ``backup_schedule.snapshot_script`` for each database, naming the connection's variable
(``$TB_DB_URL``, ``$TB_HAPI_DB_URL``) and never its value; the second runs it with ``psql`` (one ``REPEATABLE READ``
snapshot: the dump, the row counts and hashes, the hospital's own reference rows); ``trialbox backup`` then packs the
dump folder (``TB_PG_DUMP_DIR``) and every data claim, encrypts it to the hospital's public key and writes it to the
backup share claim. ``backup-last.json`` beside the files records the result (never a row or a file's content).
The files of the claims are read while the services run: the database is one point in time, the files are read
once each and read again if they change (``backup._add``); the appliance's pause of the writers (D-274) has no
equivalent the job may do in a namespace it does not administer.

**Restore.** The restore container runs ``backup.restore`` with ``TB_PG_DUMP_CMD`` and ``TB_PG_RESTORE_CMD`` set to
``platform-day2 pg``: each call is written to the spool folder the database image's ``pg-spool.sh`` serves (the
tool, its arguments, the connection as the name of its variable, standard input), and its output, errors and exit
code come back the same way. The claims are mount points, which cannot be renamed aside, so the backup is restored
into a staging folder inside each claim and then moved up; a box that holds data is first kept as one more
encrypted backup (``--keep-to``, D-274), after which its old files are removed. The database rows are checked
against the backup's own count before any file is touched (``backup.restore``).

**Logs.** The pod logs of the site's day (``TB_TZ``, D-315) through the API server (the job's service account may
list pods and read their logs, nothing else) into ``<log dir>/services/<day>/<component>.log.gz`` with
``COVERAGE.json`` (a **log gap** when a pod ran before the day began but its oldest kept line is later: the
platform's rotation took the start of the day), pruned after ``retention.logs_days``; then the audit chain archived
(``logs.archive_audit``: verified before and after, never changed).

**Update and rollback.** A digest update writes two overlays next to the site's (``deploy/platform/overlays/update``
is their shape): ``next`` pins the changed images by their new digests and carries the new ``release.json`` as the
ConfigMap ``trialbox-release``; ``previous`` is the overlay applied now. The backup job runs first (``kubectl create
job --from=cronjob/trialbox-backup``); applying ``previous`` is the rollback, and a restore of that backup undoes a
migration the new images made. A new image name or repository is not a digest update and is refused.

Nothing here prints or logs a row, a file's content, a key or a connection string.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
UPDATE_TEMPLATE = ROOT / "deploy" / "platform" / "overlays" / "update" / "kustomization.yaml"
DB_VARS = {"trialbox_wf": "TB_DB_URL", "hapi": "TB_HAPI_DB_URL"}  # the database and the variable of its URL
TOOLS = ("psql", "pg_dump", "pg_restore")
RECORD = "backup-last.json"
SPOOL_TIMEOUT_S = 6 * 3600  # the restore job's activeDeadlineSeconds
STOP = "STOP"


class Day2Error(RuntimeError):
    pass


def _write_json(path: Path, doc: Mapping[str, Any], mode: int = 0o640) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


# ------------------------------------------------------------------------------------------------ backup
def sources(env: Mapping[str, str]) -> list[tuple[Any, str]]:
    """``(backup.DbSource, variable)`` for each database to back up. A platform database has no ``tb_prefix``: one
    database per site (a prefix is the test suite's way to share one server)."""
    from tools.trialbox import backup as bk

    out = []
    for src in bk.db_sources(env):
        if src.prefix:
            raise Day2Error(f"{DB_VARS[src.name]} carries a tb_prefix: a platform database has none")
        out.append((src, DB_VARS[src.name]))
    return out


def snapshot_prepare(spool: Path, env: Mapping[str, str]) -> list[str]:
    """The backup job's first init container: for each database the psql snapshot script and its meta file, and
    the list ``sources`` that ``pg-snapshot.sh`` reads. Returns the databases."""
    from tools.trialbox import backup_schedule as bsch

    spool.mkdir(parents=True, exist_ok=True)
    names, lines = [], []
    for src, var in sources(env):
        script = bsch.snapshot_script(str(spool), src.name, "pg_dump", f'--dbname "${var}"', src.schemas, src.refdata)
        (spool / f"{src.name}.sql").write_text(script, encoding="utf-8")
        (spool / f"{src.name}.dump.json").write_text(
            json.dumps(bsch.snapshot_meta(src.name, src.refdata)), encoding="utf-8"
        )
        names.append(src.name)
        lines.append(f"{src.name} {var}\n")
    (spool / "sources").write_text("".join(lines), encoding="utf-8")
    return names


def run_backup(
    share: Path, public: Path, env: Mapping[str, str], keep: int = 14, now: datetime | None = None
) -> dict[str, Any]:
    """The backup job's main container: one encrypted backup of the dump folder (``TB_PG_DUMP_DIR``) and the claims
    (``TB_BACKUP_DIRS``) into ``share``, and ``backup-last.json`` beside it. Raises on any failure (recorded too)."""
    from tools.trialbox import backup as bk

    when = now or datetime.now(UTC)
    share.mkdir(parents=True, exist_ok=True)
    rec: dict[str, Any] = {"at": when.isoformat(timespec="seconds"), "ok": False, "file": None, "error": None}
    try:
        if not env.get("TB_PG_DUMP_DIR"):
            raise Day2Error("no TB_PG_DUMP_DIR: the dump is taken by the job's snapshot container (day2.yaml)")
        files = bk.backup([share], public, env=env, dirs=bk.layout(env), keep=keep, now=when)
        f = files[0]
        rec.update(ok=True, file={"name": f.name, "bytes": f.stat().st_size, "sha256": bk.read_sidecar(f)})
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {str(e)[-400:]}"
        _write_json(share / RECORD, rec)
        raise
    _write_json(share / RECORD, rec)
    return rec


# ------------------------------------------------------------------------------------------------ the spool
def _dsn_vars(env: Mapping[str, str]) -> dict[str, str]:
    from tb_common.db import split_url

    out = {}
    for var in DB_VARS.values():
        if env.get(var):
            out[env[var]] = var
            out[split_url(env[var])[0]] = var
    return out


def spool_args(tool: str, args: Sequence[str], env: Mapping[str, str]) -> list[str]:
    """The request's lines: the tool, then its arguments with each connection string replaced by ``@<variable>``.
    A connection string that is not one of the job's variables is refused (it would be written to disk)."""
    if tool not in TOOLS:
        raise Day2Error(f"{tool}: only {', '.join(TOOLS)} run in the database image")
    known = _dsn_vars(env)
    out = [tool]
    i = 0
    while i < len(args):
        a = args[i]
        value = None
        if a == "--dbname" and i + 1 < len(args):
            value, i = args[i + 1], i + 2
        elif a.startswith("--dbname="):
            value, i = a.partition("=")[2], i + 1
        else:
            if "\n" in a or a.startswith("@"):
                raise Day2Error("an argument with a line break or a leading @ is refused")
            out.append(a)
            i += 1
            continue
        var = known.get(value)
        if var is None:
            raise Day2Error("a connection that is not TB_DB_URL or TB_HAPI_DB_URL is refused (it would be on disk)")
        out += ["--dbname", f"@{var}"]
    return out


def pg_call(
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    poll: float = 0.2,
    timeout: float = SPOOL_TIMEOUT_S,
) -> int:
    """``platform-day2 pg <tool> ...``: hand one call to ``pg-spool.sh`` and wait for it; its output, errors and exit
    code are this command's."""
    env = os.environ if env is None else env
    stdin = sys.stdin.buffer if stdin is None else stdin
    stdout = sys.stdout.buffer if stdout is None else stdout
    stderr = sys.stderr.buffer if stderr is None else stderr
    if not argv:
        raise Day2Error("platform-day2 pg <psql|pg_dump|pg_restore> [arguments]")
    lines = spool_args(argv[0], list(argv[1:]), env)
    if not env.get("TB_PG_SPOOL"):
        raise Day2Error("TB_PG_SPOOL is not set: the folder pg-spool.sh serves (the restore job sets it)")
    spool = Path(env["TB_PG_SPOOL"])
    if not spool.is_dir():
        raise Day2Error(f"no {spool}: pg-spool.sh is not running beside this container")
    rid = spool / uuid.uuid4().hex
    old = os.umask(0o077)
    try:
        Path(f"{rid}.args").write_text("".join(f"{a}\n" for a in lines), encoding="utf-8")
        if argv[0] == "pg_restore":  # the dump on standard input
            with Path(f"{rid}.in").open("wb") as fh:
                shutil.copyfileobj(stdin, fh, 1 << 20)
        Path(f"{rid}.req").touch()
    finally:
        os.umask(old)
    rc_file = Path(f"{rid}.rc")
    deadline = time.monotonic() + timeout
    try:
        while not rc_file.is_file():
            if (spool / STOP).exists() and not Path(f"{rid}.run").exists() and not rc_file.is_file():
                raise Day2Error(f"{argv[0]}: the database image's container has stopped (pg-spool.sh, {STOP})")
            if time.monotonic() > deadline:
                raise Day2Error(f"{argv[0]}: no answer from the database image in {timeout:.0f} s (pg-spool.sh)")
            time.sleep(poll)
        for part, out in ((".out", stdout), (".err", stderr)):
            f = Path(f"{rid}{part}")
            if f.is_file():
                with f.open("rb") as fh:
                    shutil.copyfileobj(fh, out, 1 << 20)
        out_flush = getattr(stdout, "flush", None)
        if out_flush:
            out_flush()
        return int(rc_file.read_text(encoding="utf-8").strip() or "1")
    finally:
        for part in (".args", ".in", ".req", ".run", ".out", ".err", ".rc"):
            Path(f"{rid}{part}").unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------------ restore
def pick(share: Path, name: str) -> Path:
    """The backup to restore: ``name`` on the share, or with ``newest`` the newest complete one (a ``.sha256``
    sidecar beside it, as ``trialbox backup-status`` counts them)."""
    from tools.trialbox import backup as bk

    if name and name != "newest":
        f = share / Path(name).name
        if not f.is_file():
            raise Day2Error(f"no {f.name} on the backup share")
        return f
    done = sorted(
        (p for p in share.glob(f"*{bk.SUFFIX}") if bk.read_sidecar(p)),
        key=lambda p: (bk.stamp_of(p) or datetime.min.replace(tzinfo=UTC), p.name),
    )
    if not done:
        raise Day2Error(f"no complete backup ({bk.SUFFIX} with its .sha256) on the backup share")
    return done[-1]


def _empty(d: Path, keep: str) -> None:
    for c in d.iterdir():
        if c.name == keep:
            continue
        if c.is_dir() and not c.is_symlink():
            shutil.rmtree(c)
        else:
            c.unlink()


def run_restore(
    file: Path,
    key: Path,
    env: Mapping[str, str],
    public: Path,
    keep_to: Path,
    *,
    now: datetime | None = None,
    other_site: bool = False,
    older_ok: bool = False,
    refdata_dir: Path | None = None,
) -> dict[str, Any]:
    """Restore ``file`` into the claims (``TB_BACKUP_DIRS``) and the databases. A box that holds data is kept first as
    an encrypted backup in ``keep_to``; the backup goes into ``<claim>/.tb-restore-<time>`` and, once the databases
    are restored and their rows checked, replaces the claim's files. A failure before that leaves the claims as they
    were and removes the staging folders."""
    from tools.trialbox import backup as bk

    when = now or datetime.now(UTC)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    dirs = bk.layout(env)
    stage_name = f".tb-restore-{stamp}"
    stage = {n: p / stage_name for n, p in dirs.items()}
    srcs = bk.db_sources(env)
    copy: Path | None = None
    if bk._box_holds_data(srcs, dirs):
        if not public.is_file():
            raise Day2Error(f"the box holds data and {public} is missing: no copy can be kept before the restore")
        copy = bk.keep_copy(env, dirs, public, keep_to, when)
    try:
        out = bk.restore(
            file,
            key,
            env=env,
            dirs=stage,
            now=when,
            refdata_dir=refdata_dir,
            no_copy=True,
            other_site=other_site,
            max_age_days=None if older_ok else bk.RESTORE_MAX_AGE_DAYS,
        )
    except BaseException:
        for s in stage.values():
            shutil.rmtree(s, ignore_errors=True)
        raise
    for n, real in dirs.items():
        st = stage[n]
        if not st.is_dir():
            continue  # the backup has no such folder: the claim stays as it is
        real.mkdir(parents=True, exist_ok=True)
        _empty(real, stage_name)  # the box as it was is in the kept copy (or held nothing)
        for c in st.iterdir():
            c.rename(real / c.name)
        st.rmdir()
    out["kept_copy"] = str(copy) if copy else None
    out["copy"] = f"kept in {copy}" if copy else "the box held no data"
    sha = bk.read_sidecar(file) or ""
    out["audit"] = bk._audit(dirs, env, "backup.restore_copy", sha, {"file": file.name, "kept_copy": out["kept_copy"]})
    return out


# ------------------------------------------------------------------------------------------------ logs
Getter = Callable[[str], bytes]


def api_getter() -> tuple[Getter, str]:
    """A GET on the API server with the pod's service account, and the namespace."""
    from tools.trialbox.platform import KubeApi

    api = KubeApi()

    def get(path: str) -> bytes:
        req = urllib.request.Request(api.base + path, headers={"Authorization": f"Bearer {api.token}"})
        with urllib.request.urlopen(req, context=api.ctx, timeout=60) as r:
            data: bytes = r.read()
        return data

    return get, api.namespace


def _line_time(line: bytes) -> datetime | None:
    return _parse(line.split(b" ", 1)[0].decode(errors="replace"))


def collect_logs(get: Getter, namespace: str, day: date, log_dir: Path, tz: str) -> dict[str, Any]:
    """The pod logs of the site's ``day`` into ``<log_dir>/services/<day>/<component>.log.gz`` (each line
    ``<pod>/<container> <time> <text>``) and ``COVERAGE.json``; returns the coverage report."""
    from tools.trialbox import logs as tb_logs

    since, until = tb_logs.site_day_bounds(day, tz)
    t0 = datetime.fromisoformat(since.replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(until.replace("Z", "+00:00"))
    ns = urllib.parse.quote(namespace)
    pods = json.loads(get(f"/api/v1/namespaces/{ns}/pods")).get("items") or []
    by_comp: dict[str, list[bytes]] = {}
    cover: dict[str, dict[str, Any]] = {}
    for pod in pods:
        meta = pod.get("metadata") or {}
        pname = str(meta.get("name") or "")
        comp = str((meta.get("labels") or {}).get("app.kubernetes.io/component") or pname)
        started = _parse(str((pod.get("status") or {}).get("startTime") or ""))
        spec = pod.get("spec") or {}
        for c in [*(spec.get("initContainers") or []), *(spec.get("containers") or [])]:
            cname = str(c.get("name") or "")
            base = f"/api/v1/namespaces/{ns}/pods/{urllib.parse.quote(pname)}/log?container={urllib.parse.quote(cname)}"
            try:
                head = get(base + "&timestamps=true&limitBytes=4096")
                text = get(base + "&timestamps=true&sinceTime=" + urllib.parse.quote(since))
            except OSError as e:  # a pod that went away, a container not started: noted, not fatal
                cover.setdefault(comp, {"bytes": 0, "lines": 0, "gap": False, "errors": []})["errors"].append(
                    f"{pname}/{cname}: {type(e).__name__}"
                )
                continue
            first = next((t for t in map(_line_time, head.splitlines()) if t), None)
            kept = [ln for ln in text.splitlines() if (t := _line_time(ln)) is not None and t0 <= t < t1]
            by_comp.setdefault(comp, []).extend(f"{pname}/{cname} ".encode() + ln for ln in kept)
            row = cover.setdefault(comp, {"bytes": 0, "lines": 0, "gap": False, "errors": []})
            row["lines"] += len(kept)
            row["bytes"] += sum(len(ln) + 1 for ln in kept)
            if started is not None and started < t0 and first is not None and first > t0:
                row["gap"] = True  # it ran before the day began, but the platform's rotation took the start
    out_dir = log_dir / "services" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    for comp in sorted(cover):
        f = out_dir / f"{comp}.log.gz"
        tmp = f.with_suffix(".gz.part")
        with gzip.open(tmp, "wb") as gz:
            gz.write(b"".join(ln + b"\n" for ln in sorted(by_comp.get(comp, []), key=lambda b: b.split(b" ", 2)[1:2])))
        os.chmod(tmp, 0o640)
        tmp.replace(f)
    report = {"day": day.isoformat(), "since": since, "until": until, "source": "kubernetes", "services": cover}
    _write_json(out_dir / "COVERAGE.json", report)
    return report


def _parse(v: str) -> datetime | None:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def run_logs(
    get: Getter,
    namespace: str,
    log_dir: Path,
    audit: Path,
    archive: Path,
    settings: Path,
    tz: str,
    day: date | None = None,
    today: date | None = None,
) -> tuple[int, list[str]]:
    """The log job: collect the day, prune, archive the audit chain. Returns (exit code, messages)."""
    from tools.trialbox import logs as tb_logs

    if not tz:
        return 1, ["logs: TB_TZ is not set (D-315): the site's day is unknown"]
    today = today or datetime.now(ZoneInfo(tz)).date()
    d = day or today - timedelta(days=1)
    msgs: list[str] = []
    rc = 0
    rep = collect_logs(get, namespace, d, log_dir, tz)
    msgs.append(f"collected the logs of {len(rep['services'])} components of {d} into {log_dir / 'services'}")
    gaps = sorted(c for c, r in rep["services"].items() if r["gap"])
    if gaps:
        msgs.append(
            f"LOG GAP on {d} in {', '.join(gaps)}: the platform rotated the start of the day away (RUNBOOK §26)"
        )
        rc = 1
    days = tb_logs.retention_days(settings, "logs_days", tb_logs.DEFAULT_LOGS_DAYS)
    gone = tb_logs.prune(log_dir, days, today)
    msgs.append(f"logs kept {days} days; deleted: {', '.join(gone) or 'none'}")
    done = tb_logs.archive_audit(audit, archive, today)
    msgs.append(f"audit archived to {archive}: {len(done)} day files new or changed; the chain untouched")
    return rc, msgs


# ------------------------------------------------------------------------------------------------ update
def update_overlay(
    site: Path,
    release: Path,
    out: Path,
    current_release: Path | None = None,
    current: Path | None = None,
) -> dict[str, Any]:
    """Write ``<out>/next`` (the update) and ``<out>/previous`` (the rollback) for a digest update from
    ``current_release`` (default ``deploy/platform/release.json``, what the site overlay renders) to ``release``;
    ``current`` is the overlay applied now (default ``site``). Returns the plan, also in ``<out>/plan.json``."""
    import yaml

    from tools.trialbox import platform as pf

    try:
        cur = pf.load_release(current_release or pf.RELEASE)
        new = pf.load_release(release)
    except pf.PlatformError as e:
        raise Day2Error(str(e)) from e
    if set(cur.images) != set(new.images):
        raise Day2Error(
            f"the images differ ({sorted(set(cur.images) ^ set(new.images))}): not a digest update, apply the new "
            "release's manifests"
        )
    changes = []
    for name in sorted(cur.images):
        c, n = cur.images[name], new.images[name]
        if pf._norm(c.repository) != pf._norm(n.repository):
            raise Day2Error(f"{name}: repository {c.repository} becomes {n.repository}: not a digest update")
        if n.digest == c.digest:
            continue  # unchanged (pinned, or still the unreleased build on both sides)
        if not n.digest:
            raise Day2Error(f"{name}: the new release has no digest for it: a digest update pins every image it moves")
        if n.digest != c.digest:
            changes.append({"image": name, "repository": c.repository, "from": c.digest or c.tag, "to": n.digest})
    if not changes:
        raise Day2Error("the new release changes no digest: nothing to update")
    applied = (current or site).resolve()
    nxt, prev = out / "next", out / "previous"
    for d in (nxt, prev):
        d.mkdir(parents=True, exist_ok=True)
    head = (
        "# Written by `trialbox platform-day2 update-overlay` (T-633, D-416; the shape of deploy/platform/overlays/"
        "update).\n"
    )
    k = yaml.safe_load(UPDATE_TEMPLATE.read_text(encoding="utf-8"))
    k["resources"] = [os.path.relpath(applied, nxt)]
    k["images"] = [{"name": c["repository"], "digest": c["to"]} for c in changes]
    k["configMapGenerator"] = [{"name": "trialbox-release", "behavior": "replace", "files": ["release.json"]}]
    shutil.copyfile(release, nxt / "release.json")
    (nxt / "kustomization.yaml").write_text(
        head + "# The update: " + ", ".join(f"{c['image']} -> {str(c['to'])[:19]}" for c in changes) + "\n"
        + yaml.safe_dump(k, sort_keys=False), encoding="utf-8")  # fmt: skip
    p = {"apiVersion": k["apiVersion"], "kind": k["kind"], "resources": [os.path.relpath(applied, prev)]}
    (prev / "kustomization.yaml").write_text(
        head
        + "# The rollback: the overlay applied before the update, as it was.\n"
        + yaml.safe_dump(p, sort_keys=False),
        encoding="utf-8",
    )
    plan = {
        "from_release": cur.release_id,
        "to_release": new.release_id,
        "changes": changes,
        "next": str(nxt),
        "previous": str(prev),
        "steps": [
            "kubectl -n <ns> create job --from=cronjob/trialbox-backup trialbox-backup-pre-update  (wait: complete)",
            f"kustomize build {nxt} | kubectl apply -f -",
            "kubectl -n <ns> rollout status deployment --timeout=900s; the doctor job again (image_digests)",
            f"rollback: kustomize build {prev} | kubectl apply -f -  (and restore the pre-update backup when the new "
            "images migrated the database)",
        ],
    }
    _write_json(out / "plan.json", plan, 0o644)
    return plan


# ------------------------------------------------------------------------------------------------ command line
def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes")


def main(argv: Sequence[str]) -> int:
    args = list(argv)
    if args[:1] == ["pg"]:
        try:
            return pg_call(args[1:])
        except Day2Error as e:
            print(f"platform-day2 pg: {e}", file=sys.stderr)
            return 2
    ap = argparse.ArgumentParser(prog="trialbox platform-day2", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="action", required=True)
    sp = sub.add_parser("snapshot-prepare", help="the backup job's snapshot scripts (init container 1)")
    sp.add_argument("--spool", type=Path, required=True)
    b = sub.add_parser("backup", help="the backup job: one encrypted backup of the dump and the claims to the share")
    b.add_argument("--share", type=Path, required=True)
    b.add_argument("--public", type=Path, required=True)
    b.add_argument("--keep", type=int, default=int(os.environ.get("TB_BACKUP_KEEP") or 14))
    r = sub.add_parser("restore", help="the restore job (TB_RESTORE_FILE: a file on the share, or newest)")
    r.add_argument("--share", type=Path, required=True)
    r.add_argument("--key", type=Path, required=True)
    r.add_argument("--public", type=Path, required=True)
    r.add_argument("--keep-to", type=Path, required=True)
    r.add_argument("--spool", type=Path, default=None, help="the pg-spool folder: STOP is written there at the end")
    lg = sub.add_parser("logs", help="the log job: the pod logs of yesterday, pruning, the audit archive")
    lg.add_argument("--log-dir", type=Path, required=True)
    lg.add_argument("--audit", type=Path, required=True)
    lg.add_argument("--archive", type=Path, required=True)
    lg.add_argument("--settings", type=Path, required=True)
    lg.add_argument("--day", default=None)
    up = sub.add_parser("update-overlay", help="the update and rollback overlays of a digest update")
    up.add_argument("--site", type=Path, required=True, help="the site overlay")
    up.add_argument("--release", type=Path, required=True, help="the new release.json")
    up.add_argument("--current-release", type=Path, default=None, help="default: deploy/platform/release.json")
    up.add_argument("--current", type=Path, default=None, help="the overlay applied now (default: --site)")
    up.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(args)
    env = dict(os.environ)
    try:
        if a.action == "snapshot-prepare":
            print(f"snapshot scripts for {', '.join(snapshot_prepare(a.spool, env))} in {a.spool}")
            return 0
        if a.action == "backup":
            rec = run_backup(a.share, a.public, env, keep=a.keep)
            print(f"backup {rec['file']['name']} ({rec['file']['bytes']} bytes) on the share")
            return 0
        if a.action == "restore":
            try:
                f = pick(a.share, env.get("TB_RESTORE_FILE") or "newest")
                print(f"restoring {f.name}")
                refdata = Path(env["TB_REFDATA_DIR"]) if env.get("TB_REFDATA_DIR") else None
                out = run_restore(
                    f, a.key, env, a.public, a.keep_to, other_site=_truthy(env.get("TB_RESTORE_OTHER_SITE")),
                    older_ok=_truthy(env.get("TB_RESTORE_OLDER_OK")), refdata_dir=refdata,
                )  # fmt: skip
            finally:
                if a.spool is not None:
                    a.spool.mkdir(parents=True, exist_ok=True)
                    (a.spool / STOP).touch()
            print(json.dumps(out, indent=1, ensure_ascii=False))
            for w in out["warnings"]:
                print(f"restore: warning: {w}", file=sys.stderr)
            if out["refdata"]["missing"]:
                print(f"restore: the reference data is NOT loaded ({', '.join(out['refdata']['missing'])}): load the "
                      "packs (RUNBOOK §26)", file=sys.stderr)  # fmt: skip
                return 3
            return 0
        if a.action == "logs":
            get, ns = api_getter()
            rc, msgs = run_logs(get, ns, a.log_dir, a.audit, a.archive, a.settings, env.get("TB_TZ", "").strip(),
                                day=date.fromisoformat(a.day) if a.day else None)  # fmt: skip
            for m in msgs:
                print(m, file=sys.stderr if "GAP" in m else sys.stdout)
            return rc
        plan = update_overlay(a.site, a.release, a.out, a.current_release, a.current)
        print(json.dumps(plan, indent=1))
        return 0
    except Exception as e:  # every failure is one plain line and exit 1 (the job's log)
        print(f"platform-day2 {a.action}: {type(e).__name__}: {str(e)[-500:]}", file=sys.stderr)
        return 1
