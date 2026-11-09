"""Update drill (TB-PLAN-04 step 8, D-138): the update path on the in-process box, with real bundles.

    python -m tools.update_drill --dir /tmp/tb-update-drill        # exit 0 only when every check passes
    python -m tools.update_drill backup-work --to DIR [--work DIR]  # the demo container's pre-update backup

1. ``e2e_simple``'s chain runs in ``<dir>/box-run`` (the whole path, its own schemas of the trial database).
2. A throwaway vendor key signs three bundles (``tools/sign_bundle.py``); each is verified and staged exactly as
   ``tools/apply_update.sh`` does (``tools/verify_update.py``), and a tampered copy is refused.
3. **Good bundle**: an image, a new and an overwritten model file, and a migration. The update backs up first
   (``trialbox backup`` to the hospital key; the private key opens it), takes the rollback point (``pg_dump``),
   applies, migrates (``tb_common.db``), restarts the stores and checks that every mark, participant, set-up fact and
   code list reads back as before. ``update.applied`` is audited.
4. **Bad migration**: a second migration with an SQL error. The update fails and rolls back: the release, the models
   and the database are as before the update, ``update.rolled_back`` is audited.
5. **Unhealthy release**: a valid second migration whose release fails its check. The migration had run, so the
   rollback restores the database from the dump: the new table is gone, the schema version is back to 1.
6. The audit chain verifies with the three update events in it; then ``e2e_simple`` runs again on a fresh box in the
   same environment and passes.

What it cannot show: ``docker load``, ``docker compose up --wait`` and a real service's migration at start (no
Docker here); those are the compose and demo boxes of ``tools/trialbox/update.py``, exercised on the demo VM.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import secrets
import shutil
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

MIGRATION_1 = (
    "CREATE TABLE release_note (id INTEGER PRIMARY KEY, text TEXT NOT NULL);\n"
    "INSERT INTO release_note (id, text) VALUES (1, 'step 8 drill release')\n"
)
MIGRATION_2_BAD = "CREATE TABLE release_extra (id INTEGER PRIMARY KEY, oops;\n"
MIGRATION_2_OK = "CREATE TABLE release_extra (id INTEGER PRIMARY KEY)\n"


def _image_tar(path: Path, tag: str) -> Path:
    """A minimal ``docker save``-shaped archive (manifest.json with the tag): what the bundle carries."""
    buf = json.dumps([{"Config": "config.json", "RepoTags": [tag], "Layers": []}]).encode()
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(buf)
        tf.addfile(info, io.BytesIO(buf))
    return path


def make_bundle(base: Path, key: Path, bundle_id: str, migrations: list[str], fail_check: bool = False) -> Path:
    from tools.sign_bundle import build

    src = base / "payload" / bundle_id
    src.mkdir(parents=True, exist_ok=True)
    items = [("image", _image_tar(src / "trialbox-py.tar", "trialbox-py:1.0.0"), "trialbox-py_1.0.0.tar")]
    (src / "config.json").write_text(json.dumps({"bundle": bundle_id}), encoding="utf-8")
    (src / "tokenizer.bin").write_bytes(secrets.token_bytes(256))
    items += [("model", src / "config.json", "judge/config.json"), ("model", src / "tokenizer.bin", "judge/new.bin")]
    for i, sql in enumerate(migrations, start=1):
        f = src / f"{i:03d}.sql"
        f.write_text(sql, encoding="utf-8")
        items.append(("other", f, f"migrations/{i:03d}_release.sql"))
    if fail_check:
        (src / "FAIL_CHECK").write_text("the new release does not start\n", encoding="utf-8")
        items.append(("other", src / "FAIL_CHECK", "FAIL_CHECK"))
    out = base / "bundles" / f"{bundle_id}.tar"
    out.parent.mkdir(parents=True, exist_ok=True)
    build(key, bundle_id, items, out)
    return out


def _stage(bundle: Path, pub: Path, stage: Path) -> Any:
    from tools.trialbox.update import Plan
    from tools.verify_update import verify

    summary = verify(bundle, pub, stage)
    return Plan.load(stage, summary)


def _tables(url: str) -> list[str]:
    from tb_common.db import Database

    with Database.connect(url, "release") as db:
        return sorted(
            str(r[0])
            for r in db.fetchall(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?", (db.schema,)
            )
        )


def run(base: Path) -> dict[str, Any]:
    from tb_common.audit import verify as audit_verify

    from tools import e2e_simple, pglocal
    from tools.sign_bundle import keygen
    from tools.trialbox.update import InProcessBox, UpdateFailed, Updater
    from tools.verify_update import Rejected

    t0 = time.perf_counter()
    external_db = bool(os.environ.get("TB_DB_URL"))
    work = base / "box-run"
    url = pglocal.for_work(work)
    password = secrets.token_urlsafe(12)
    res = e2e_simple.run(work, password, "ja")
    checks: list[tuple[str, bool, str]] = [("the box ran the whole path (e2e_simple)", bool(res["ok"]), "")]
    models = work / "models" / "judge"
    models.mkdir(parents=True, exist_ok=True)
    (models / "config.json").write_text('{"bundle": "factory"}', encoding="utf-8")
    (work / "RELEASE").write_text("factory\n", encoding="utf-8")

    priv, pub = keygen(base / "vendor")
    good = make_bundle(base, priv, "2026.11-step8-a", [MIGRATION_1])
    bad_sql = make_bundle(base, priv, "2026.11-step8-b", [MIGRATION_1, MIGRATION_2_BAD])
    bad_run = make_bundle(base, priv, "2026.11-step8-c", [MIGRATION_1, MIGRATION_2_OK], fail_check=True)

    tampered = base / "bundles" / "tampered.tar"
    with tarfile.open(good) as src, tarfile.open(tampered, "w") as dst:  # one model payload changed, same size
        for m in src.getmembers():
            fh = src.extractfile(m) if m.isfile() else None
            body = fh.read() if fh else b""
            if m.name.endswith("judge/new.bin"):
                body = bytes([body[0] ^ 0xFF]) + body[1:]
            dst.addfile(m, io.BytesIO(body) if fh else None)
    try:
        _stage(tampered, pub, base / "stage-tampered")
        refused = False
    except Rejected:
        refused = True
    checks.append(("a tampered bundle is refused before anything changes", refused, ""))

    box = InProcessBox(work, url, base / "backups")
    lines: list[str] = []
    up = Updater(box, base / "updates", say=lines.append)

    plan = _stage(good, pub, base / "stage-a")
    out = up.run(plan)
    backups = sorted((base / "backups" / "nas").glob("*.tbbak"))
    checks.append(
        (
            "good bundle: backed up first (D-126), the hospital key opens it",
            len(backups) == 1,
            backups[0].name if backups else "",
        )
    )
    checks.append(("good bundle: applied, migrated, data unchanged, audited", bool(out["ok"]), "; ".join(lines[-6:])))
    checks.append(("good bundle: release, new model and migration in place",
                   (work / "RELEASE").read_text(encoding="utf-8").startswith("2026.11-step8-a")
                   and (models / "new.bin").exists() and _tables(url) == ["_schema_version", "release_note"]
                   and box.schema_version() == 1, (work / "RELEASE").read_text(encoding="utf-8").strip()))  # fmt: skip
    after_good = (work / "RELEASE").read_text(encoding="utf-8"), (models / "config.json").read_text(encoding="utf-8")

    for label, bundle, stage in (("bad migration", bad_sql, "stage-b"), ("unhealthy release", bad_run, "stage-c")):
        plan = _stage(bundle, pub, base / stage)
        lines.clear()
        try:
            up.run(plan)
            failed = False
        except UpdateFailed:
            failed = True
        same = ((work / "RELEASE").read_text(encoding="utf-8"), (models / "config.json").read_text(encoding="utf-8"))
        checks.append((f"{label}: the update fails and rolls back", failed and any("rollback" in x for x in lines),
                       "; ".join(x for x in lines if "FAIL" in x or "rollback" in x)[:300]))  # fmt: skip
        checks.append((f"{label}: release, models, database and data as before the update",
                       same == after_good and _tables(url) == ["_schema_version", "release_note"]
                       and box.schema_version() == 1 and box.state() == box.before,
                       f"schema version {box.schema_version()}"))  # fmt: skip

    audit_dir = work / "box" / "audit"
    events = []
    for f in sorted(audit_dir.glob("*.jsonl")):
        events += [json.loads(x)["event"] for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    upd = [e for e in events if e.startswith("update.")]
    checks.append(("the audit chain verifies, with update.applied and two update.rolled_back",
                   audit_verify(audit_dir).ok and upd == ["update.applied", "update.rolled_back", "update.rolled_back"],
                   ", ".join(upd)))  # fmt: skip
    history = (base / "updates" / "history.jsonl").read_text(encoding="utf-8")
    checks.append(("the update history holds no secret", password not in history and "PRIVATE" not in history,
                   f"{len(history.splitlines())} lines"))  # fmt: skip

    if not external_db:
        os.environ.pop("TB_DB_URL", None)
        res2 = e2e_simple.run(base / "box-after", secrets.token_urlsafe(12), "ja")
        checks.append(("after the updates, e2e_simple passes on a fresh box", bool(res2["ok"]), ""))
    return {"ok": all(c[1] for c in checks), "checks": checks, "seconds": round(time.perf_counter() - t0, 1)}


def backup_work(work: Path, to: Path) -> Path:
    """The pre-update backup of an in-process box (the demo container): a throwaway key pair next to it (synthetic
    data only), the box's files and schemas, verified with the private key. Returns the backup file."""
    from tools import pglocal
    from tools.trialbox import backup as bk

    url = pglocal.for_work(work)
    keys = to / "keys"
    priv, pub = keys / "demo-backup.key", keys / "demo-backup.pub"
    if not pub.is_file():
        bk.keygen(priv, pub)
    dirs = {n: work / n for n in ("box", "console", "lake", "sec") if (work / n).exists()}
    files = bk.backup([to], pub, env={**os.environ, "TB_DB_URL": url}, dirs=dirs)
    bk.verify(files[0], priv)
    return files[0]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["backup-work"]:
        ap = argparse.ArgumentParser(prog="update_drill backup-work")
        ap.add_argument("--to", type=Path, required=True)
        ap.add_argument("--work", type=Path, default=Path(os.environ.get("TB_DEMO_DIR", "/tmp/tb-demo")))
        b = ap.parse_args(argv[1:])
        print(backup_work(b.work, b.to))
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_UPDATE_DRILL_DIR", "/tmp/tb-update-drill")))
    a = ap.parse_args(argv)
    import logging

    logging.disable(logging.INFO)
    if a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True)
    out = run(a.dir)
    for name, ok, detail in out["checks"]:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"update drill {'PASSED' if out['ok'] else 'FAILED'} in {out['seconds']} s")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
