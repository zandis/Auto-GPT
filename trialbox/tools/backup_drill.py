"""Backup and restore drill (TB-PLAN-04 step 2 done-check, D-126): a box that has run the whole path is backed up,
wiped, restored from the backup with the hospital's key, and must then be the same box.

    python -m tools.backup_drill --dir /tmp/tb-drill        # exit 0 only when every check passes

1. ``e2e_simple``'s chain runs in ``<dir>/box-run`` (criteria -> report -> approval -> list -> marks -> mail ->
   REDCap -> log), on its own schemas of the trial database (``TB_DB_URL`` or the local throwaway cluster).
2. A backup key pair is made; ``trialbox backup`` writes the box to two targets (``nas``, ``usb``).
3. The box is wiped: its schemas dropped, its data folders moved away.
4. ``trialbox restore`` (private key) puts it back. Checks: every table's rows equal the backup's manifest (count and
   content hash), every file equal, the audit hash chain verifies, the administrator signs in with the same password,
   and the investigator's marks read back through the site store as before.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

DATA_DIRS = ("box", "console", "lake", "sec")  # the work-dir folders that hold the box's files


def run(base: Path) -> dict[str, Any]:
    from tb_common.audit import verify

    from tools import e2e_simple, pglocal
    from tools.trialbox import backup as bk

    work = base / "box-run"
    url = pglocal.for_work(work)
    password = secrets.token_urlsafe(12)
    t0 = time.perf_counter()
    res = e2e_simple.run(work, password, "ja")
    checks: list[tuple[str, bool, str]] = [("the box ran the whole path (e2e_simple)", bool(res["ok"]), "")]
    dirs = {name: work / name for name in DATA_DIRS if (work / name).exists()}
    before_files = {n: bk.tree_hashes(p) for n, p in dirs.items()}
    marks_before = _marks(work)

    keys = base / "keys"
    priv, pub = keys / "hospital-it.key", keys / "box.pub"
    for f in (priv, pub):
        f.unlink(missing_ok=True)
    bk.keygen(priv, pub)
    env = {**os.environ, "TB_DB_URL": url, "TB_SITE_ID": "DRILL"}
    files = bk.backup([base / "nas", base / "usb"], pub, env=env, dirs=dirs)
    checks.append(("backup written to both targets", len(files) == 2 and files[0].stat().st_size > 0, files[0].name))

    # wipe: drop the run's schemas, move its folders away (a dead box)
    from tb_common.db import split_url

    _, prefix = split_url(url)
    pglocal.drop_prefix(url, prefix)
    gone = base / "wiped"
    shutil.rmtree(gone, ignore_errors=True)
    gone.mkdir()
    for n, p in dirs.items():
        p.rename(gone / n)
    checks.append(("box wiped", not any(p.exists() for p in dirs.values()), ""))

    out = bk.restore(files[1], priv, env=env, dirs=dirs)
    checks.append(("restore: every table equal to the backup (rows and content hash)", bool(out["ok"]),
                   json.dumps(out["rows"])))  # fmt: skip
    after_files = {n: bk.tree_hashes(p) for n, p in dirs.items()}
    checks.append(("restore: every file equal", after_files == before_files,
                   f"{sum(len(v) for v in after_files.values())} files"))  # fmt: skip
    audit_dirs = [p for p in (work / "box" / "audit", work / "lake" / "audit") if p.exists()]
    ok_chain = all(verify(p)[0] for p in audit_dirs) if audit_dirs else False
    checks.append(
        ("restore: audit hash chain verifies", ok_chain, ", ".join(str(p.relative_to(base)) for p in audit_dirs))
    )
    checks.append(("restore: the administrator signs in with the same password", _admin_signs_in(work, password), ""))
    checks.append(("restore: the investigator's marks read back the same", _marks(work) == marks_before,
                   f"{len(marks_before)} marks"))  # fmt: skip
    return {"ok": all(c[1] for c in checks), "checks": checks, "seconds": round(time.perf_counter() - t0, 1)}


def _marks(work: Path) -> list[tuple[Any, ...]]:
    """Every investigator mark, read through the site store's own API (a fresh store: a fresh process)."""
    from console.sitestore import SiteStore
    from tb_common.db import Database

    db = Database.connect(os.environ["TB_DB_URL"], "site")
    tables = [r[0] for r in db.fetchall(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = ? AND column_name = 'ruleset'",
        (db.schema,))]  # fmt: skip
    rulesets = sorted({r[0] for t in tables for r in db.fetchall(f'SELECT DISTINCT ruleset FROM "{t}"')})
    store = SiteStore()
    return sorted(((r, m.pid, m.mark, m.by, m.at) for r in rulesets for m in store.all_marks(r)), key=repr)


def _admin_signs_in(work: Path, password: str) -> bool:
    from console.auth import UserStore

    users = UserStore()
    try:
        return bool(users.authenticate("admin", password))
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DRILL_DIR", "/tmp/tb-backup-drill")))
    a = ap.parse_args(argv)
    import logging

    logging.disable(logging.INFO)
    if a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True)
    out = run(a.dir)
    for name, ok, detail in out["checks"]:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"backup drill {'PASSED' if out['ok'] else 'FAILED'} in {out['seconds']} s")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
