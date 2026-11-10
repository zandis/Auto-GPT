"""``python -m tools.trialbox <command>`` (spec v4 §18). Commands: ``doctor``, ``eval``, ``backup-keygen``,
``backup``, ``backup-check`` (D-178), ``backup-verify``, ``restore`` (D-126, ``tools/trialbox/backup.py``);
``backup-nightly`` and ``backup-status`` (the schedule and the age alert, D-187, ``backup_schedule.py``); ``secrets``
(per-service tokens, D-128 / D-138, ``svc_secrets.py``), ``logs`` (retention, ``logs.py``) and ``update`` (the update
path behind ``tools/apply_update.sh``, ``update.py``); ``exports`` lists the export ledger (D-149,
``tb_common.flowledger``); ``ops`` runs the console's operations requests and writes their status (D-178, ``ops.py``).
``secrets``, ``logs``, ``update`` and ``ops`` need only the standard library, so they run with the host's ``python3``
from the install folder: ``sudo python3 -m tools.trialbox secrets rotate``."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trialbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="v4 deployment checks; exit 1 on any FAIL")
    d.add_argument("--env-file", type=Path, default=None)
    d.add_argument("--settings", type=Path, default=None)
    d.add_argument("--routing", type=Path, default=None)
    d.add_argument("--dataplat-workdir", type=Path, default=None)
    d.add_argument("--json", action="store_true")
    d.add_argument("--live", action="store_true", help="also ask the model servers (served names, key; D-177)")
    d.add_argument("--serving", action="store_true", help="only the live model-server check (install.sh)")
    e = sub.add_parser("eval", help="run a public evaluation suite and archive the result")
    e.add_argument("suite")
    e.add_argument("--archive", type=Path, default=None)
    k = sub.add_parser("backup-keygen", help="make the backup key pair: private for hospital IT, public for the box")
    k.add_argument("--private", type=Path, required=True, help="e.g. a file on a USB stick that goes in the envelope")
    k.add_argument("--public", type=Path, required=True, help="e.g. deploy/secrets/backup.pub")
    b = sub.add_parser("backup", help="one encrypted backup of databases and files to each --to directory")
    b.add_argument("--to", type=Path, action="append", required=True, help="NAS share, USB disk, second disk ...")
    b.add_argument("--public", type=Path, default=Path(os.environ.get("TB_BACKUP_PUBKEY", "deploy/secrets/backup.pub")))
    b.add_argument("--dir", action="append", default=[], help="name=path (default: TB_BACKUP_DIRS or the volumes)")
    b.add_argument("--keep", type=int, default=int(os.environ.get("TB_BACKUP_KEEP", "14")))
    ck = sub.add_parser("backup-check", help="check a backup is whole without the key (D-178; JSON)")
    ck.add_argument("file", type=Path)
    v = sub.add_parser("backup-verify", help="decrypt a backup and check every hash (needs the private key)")
    v.add_argument("file", type=Path)
    v.add_argument("--key", type=Path, required=True)
    r = sub.add_parser("restore", help="restore databases and files from a backup (needs the private key)")
    r.add_argument("file", type=Path)
    r.add_argument("--key", type=Path, required=True)
    r.add_argument("--dir", action="append", default=[])
    r.add_argument("--yes", action="store_true", help="replace the current data (moved aside, not deleted)")
    kept = Path(__file__).resolve().parents[2] / "deploy" / "refdata" / "loaded"
    r.add_argument("--refdata", type=Path, default=Path(os.environ.get("TB_REFDATA_DIR") or kept),
                   help="the kept reference packs (default: TB_REFDATA_DIR or deploy/refdata/loaded)")  # fmt: skip
    deploy = Path(__file__).resolve().parents[2] / "deploy"
    bn = sub.add_parser("backup-nightly", help="the scheduled backup to TB_BACKUP_TARGETS, then pgBackRest (D-187)")
    bn.add_argument("--deploy", type=Path, default=deploy)
    bs = sub.add_parser("backup-status", help="age of the newest good off-box backup; exit 1 and alert when too old")
    bs.add_argument("--deploy", type=Path, default=deploy)
    bs.add_argument("--json", action="store_true")
    bs.add_argument("--quiet", action="store_true", help="print nothing when all is well (cron)")
    s = sub.add_parser("secrets", help="per-service tokens: init, status, rotate (never prints a value)")
    s.add_argument("action", choices=["init", "status", "rotate"])
    s.add_argument("--service", action="append", default=[], help="rotate only these (a service, operator or db)")
    s.add_argument("--deploy", type=Path, default=deploy)
    s.add_argument("--no-restart", action="store_true", help="rotate the files only; restart the services yourself")
    lg = sub.add_parser("logs", help="log retention: collect, prune, archive-audit, daily (all three)")
    lg.add_argument("action", choices=["collect", "prune", "archive-audit", "daily"])
    lg.add_argument("--deploy", type=Path, default=deploy)
    lg.add_argument("--day", default=None, help="collect: the day to collect (default: yesterday)")
    u = sub.add_parser("update", help="apply a verified, staged bundle: backup, apply, migrate, check, roll back")
    u.add_argument("--stage", type=Path, required=True)
    u.add_argument("--summary", type=Path, required=True, help="verify_update.py's JSON summary")
    u.add_argument("--target", choices=["compose", "demo"], default=os.environ.get("TB_UPDATE_TARGET", "compose"))
    u.add_argument("--deploy", type=Path, default=deploy)
    u.add_argument("--no-backup", action="store_true", help="skip the D-126 backup (audited; not for a real box)")
    op = sub.add_parser("ops", help="the console's operations requests: run them, write the status (D-178)")
    op.add_argument("action", choices=["run", "status"])
    op.add_argument("--deploy", type=Path, default=deploy)
    op.add_argument("--ops-dir", type=Path, default=None, help="default: TB_OPS_DIR or deploy/ops")
    op.add_argument("--local", action="store_true", help="a box in this process (no docker compose)")
    op.add_argument("--watch", type=int, default=0, help="run again every N seconds (0: once)")
    fl = sub.add_parser("exports", help="the export ledger: every file that left the box (D-149)")
    fl.add_argument("--audit", type=Path, default=Path(os.environ.get("TB_AUDIT_DIR", "/data/audit")))
    fl.add_argument("--days", type=int, default=30)
    fl.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "exports":
        return _exports_cmd(a)
    if a.cmd == "secrets":
        return _secrets_cmd(a)
    if a.cmd == "ops":
        from tools.trialbox import ops as tb_ops

        return tb_ops.main(a.action, a.deploy, a.ops_dir, a.local, a.watch)
    if a.cmd == "logs":
        from tools.trialbox import logs as tb_logs

        return tb_logs.main_action(a.action, a.deploy, a.day)
    if a.cmd == "update":
        from tools.trialbox import update as tb_update

        return tb_update.main_apply(a.stage, a.summary, a.target, a.deploy, backup=not a.no_backup)
    if a.cmd in ("backup-nightly", "backup-status"):
        from tools.trialbox import backup_schedule as bsch

        if a.cmd == "backup-nightly":
            return bsch.main_nightly(a.deploy)
        return bsch.main_status(a.deploy, a.json, a.quiet)
    if a.cmd in ("backup-keygen", "backup", "backup-check", "backup-verify", "restore"):
        return _backup_cmd(a)
    if a.cmd == "doctor":
        from tools.trialbox import doctor

        which = doctor.LIVE if a.serving else (doctor.CHECKS + doctor.LIVE if a.live else doctor.CHECKS)
        checks = doctor.run(
            doctor.inputs_from(
                env_file=a.env_file, settings=a.settings, routing=a.routing, dataplat=a.dataplat_workdir
            ),
            which,
        )
        if a.json:
            print(json.dumps([c.__dict__ for c in checks], indent=1, ensure_ascii=False))
        else:
            print(doctor.render(checks))
        return 0 if doctor.ok(checks) else 1
    from tools.trialbox import eval as tb_eval

    with tempfile.TemporaryDirectory(prefix=f"eval-{a.suite}-") as tmp:
        try:
            result, path = tb_eval.run_suite(a.suite, Path(tmp), a.archive or tb_eval.ARCHIVE)
        except tb_eval.SuiteRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    print(json.dumps({k: v for k, v in result.items() if k != "datasets"}, indent=1, ensure_ascii=False))
    print(f"archived: {path}")
    return 1 if result.get("passed") is False else 0


def _exports_cmd(a: argparse.Namespace) -> int:
    """What left this box in the last ``--days`` days: when, channel, file, level, approval, recipients, sha256."""
    from dataclasses import asdict
    from datetime import UTC, datetime, timedelta

    from tb_common.flowledger import exports

    rows = exports(a.audit, since=datetime.now(UTC) - timedelta(days=a.days))
    if a.json:
        print(json.dumps([asdict(r) for r in rows], indent=1, ensure_ascii=False))
        return 0
    for r in rows:
        to = ", ".join(r.recipients) or "-"
        print(f"{r.ts[:19]}  {r.channel:<16} {r.identifier_level:<13} {r.filename}  to {to}  [{r.approval}]  "
              f"sha256 {r.sha256[:16]}")  # fmt: skip
    print(f"{len(rows)} exports in the last {a.days} days")
    return 0


def _secrets_cmd(a: argparse.Namespace) -> int:
    from tools.trialbox import svc_secrets as sx

    try:
        if a.action == "status":
            for row in sx.status(a.deploy):
                print("  ".join(f"{k}={v}" for k, v in row.items()))
            return 0
        if a.action == "init":
            res = sx.init(a.deploy)
            print(
                f"tokens made for: {', '.join(res.created) or 'none (all present)'}; "
                f"registry {sx.registry_path(a.deploy)}"
            )
            if res.legacy_kept:
                print("the old shared token still works (with a warning) until: trialbox secrets rotate")
            return 0
        res = sx.rotate(a.deploy, a.service, do_restart=not a.no_restart)
        print(f"rotated: {', '.join(res.rotated)}")
        print(f"restarted: {', '.join(res.restarted) or 'none (restart them yourself)'}")
        print("old shared token: " + ("still accepted (rotate every token to end it)" if res.legacy_kept else "gone"))
        return 0
    except sx.SecretsError as exc:
        print(f"secrets: {exc}", file=sys.stderr)
        return 1


def _backup_cmd(a: argparse.Namespace) -> int:
    from tools.trialbox import backup as bk

    try:
        if a.cmd == "backup-keygen":
            fp = bk.keygen(a.private, a.public)
            print(f"backup key {fp}: give {a.private} to hospital IT in a sealed envelope; the box keeps {a.public}")
            return 0
        if a.cmd == "backup":
            dirs = bk.layout(os.environ, a.dir)
            for f in bk.backup(a.to, a.public, dirs=dirs, keep=a.keep):
                print(f"wrote {f}")
            return 0
        if a.cmd == "backup-check":
            print(json.dumps(bk.check(a.file), indent=1, ensure_ascii=False))
            return 0
        if a.cmd == "backup-verify":
            print(json.dumps(bk.verify(a.file, a.key), indent=1, ensure_ascii=False))
            return 0
        if not a.yes:
            print("restore replaces the box's databases and data folders (the old folders are kept aside): add --yes")
            return 2
        out = bk.restore(a.file, a.key, dirs=bk.layout(os.environ, a.dir), refdata_dir=a.refdata)
        print(json.dumps(out, indent=1, ensure_ascii=False))
        for w in out["warnings"]:
            print(f"restore: warning: {w}", file=sys.stderr)
        if out["refdata"]["missing"]:  # D-187: a backup holds no vendor pack rows; the box is not whole without them
            print(f"restore: the reference data is NOT loaded: put {', '.join(out['refdata']['missing'])}.tar in "
                  f"{a.refdata} (the update bundle or the vendor) and run this restore again, or load it with "
                  "python -m tb_common.refdata load <pack> (RUNBOOK §5)", file=sys.stderr)  # fmt: skip
            return 3
        return 0
    except bk.BackupError as exc:
        print(f"{a.cmd}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
