"""``python -m tools.trialbox <command>`` (spec v4 §18). Commands: ``doctor``, ``eval``, ``backup-keygen``,
``backup``, ``backup-verify``, ``restore`` (D-126, ``tools/trialbox/backup.py``)."""

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
    v = sub.add_parser("backup-verify", help="decrypt a backup and check every hash (needs the private key)")
    v.add_argument("file", type=Path)
    v.add_argument("--key", type=Path, required=True)
    r = sub.add_parser("restore", help="restore databases and files from a backup (needs the private key)")
    r.add_argument("file", type=Path)
    r.add_argument("--key", type=Path, required=True)
    r.add_argument("--dir", action="append", default=[])
    r.add_argument("--yes", action="store_true", help="replace the current data (moved aside, not deleted)")
    a = ap.parse_args(argv)
    if a.cmd in ("backup-keygen", "backup", "backup-verify", "restore"):
        return _backup_cmd(a)
    if a.cmd == "doctor":
        from tools.trialbox import doctor

        checks = doctor.run(
            doctor.inputs_from(env_file=a.env_file, settings=a.settings, routing=a.routing, dataplat=a.dataplat_workdir)
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
        if a.cmd == "backup-verify":
            print(json.dumps(bk.verify(a.file, a.key), indent=1, ensure_ascii=False))
            return 0
        if not a.yes:
            print("restore replaces the box's databases and data folders (the old folders are kept aside): add --yes")
            return 2
        print(json.dumps(bk.restore(a.file, a.key, dirs=bk.layout(os.environ, a.dir)), indent=1, ensure_ascii=False))
        return 0
    except bk.BackupError as exc:
        print(f"{a.cmd}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
