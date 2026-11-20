"""Update drill (TB-PLAN-04 step 8, D-138, D-210): the update path on the in-process box, with real bundles.

    python -m tools.update_drill --dir /tmp/tb-update-drill        # exit 0 only when every check passes
    python -m tools.update_drill backup-work --to DIR [--work DIR]  # the demo container's pre-update backup
    python -m tools.update_drill stick [--dir DIR]                  # 10K-7: insert, verify, quiet hour, roll back

``--dir`` is a folder that does not exist yet (made, with the mark ``.tb-update-drill``) or one an earlier run made
(emptied); any other folder, a link or a file is refused before anything is removed (H4 of the review, D-1363).

1. ``e2e_simple``'s chain runs in ``<dir>/box-run`` (the whole path, its own schemas of the trial database).
2. A throwaway vendor key signs the bundles (``tools/sign_bundle.py``, manifest 1.2.0: ``release_seq``, ``key_id``,
   ``not_after``, ``compat.json``, ``release.json`` and ``images.lock`` for the image); each is verified and staged
   exactly as ``tools/apply_update.sh`` does (``tools/verify_update.py``), and a tampered copy is refused.
3. **Good bundle** (``release_seq`` 2): an image, a new and an overwritten model file, and a migration. Backed up
   first (the hospital key opens it), the rollback point (``pg_dump``, sealed), applied, migrated
   (``Database.migrate_dir``), the stores restarted, every mark, participant, set-up fact and code list as before;
   ``update.applied`` audited, ``installed.json`` at 2, no plaintext dump left (``*.sql``, ``*.dump``).
4. **Older release**: a bundle at ``release_seq`` 1 is refused; with ``--allow-downgrade REASON`` it applies and
   ``update.downgrade`` is audited. **Compatibility**: a bundle whose table does not accept the box's schema version
   is refused by the verifier and by the preflight, nothing changed.
5. **Bad migration** and **unhealthy release**: the update fails and rolls back (release, models, database as before).
6. **Disk full**: the preflight refuses with the bytes needed and free; no marker, no rollback point, nothing changed.
7. **kill -9 at each step** (a child process killed by SIGKILL as it enters each of the eight steps): ``update status``
   names the step and the bundle, a second update is refused while the marker exists, ``update rollback <bundle>``
   puts the box back (release, models, database, data), removes the marker, and the box's stores start.
8. **The db image** (``deploy/images.lock`` ``db``, when Docker and the image are here): a ``trialbox_wf`` dump taken
   and restored with exactly the compose box's ``pg_dump`` / ``pg_restore`` commands on the box's database image,
   with the extensions of ``db-init``; the database starts again with its data and extensions. Without Docker or
   the image this case is reported ``SKIP`` (not passed).
9. The audit chain verifies; ``e2e_simple`` runs again on a fresh box and passes.

``stick`` (10K-7, D-1363; no database): an update from a stick inserted at the box, through the operations runner
the console's requests reach, on a frozen clock: insert, verify (the Japanese release note and the change-impact
sheet shown), apply in the quiet hour, return to the previous release (:func:`stick_drill`).

What it cannot show: ``docker load`` and ``docker compose up --wait`` with real service images (case 8 runs only the
database); those are the compose and demo boxes of ``tools/trialbox/update.py``, exercised on the demo VM.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import io
import json
import os
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
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
IMAGE_TAG = "trialbox-py:1.0.0"


def _image_tar(path: Path, tag: str) -> Path:
    """A minimal ``docker save``-shaped archive (manifest.json with the tag): what the bundle carries."""
    buf = json.dumps([{"Config": "config.json", "RepoTags": [tag], "Layers": []}]).encode()
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(buf)
        tf.addfile(info, io.BytesIO(buf))
    return path


def compat_table(bundle_id: str, schema_max: int = 1, provides: int | None = None) -> dict[str, Any]:
    """The drill's compatibility table: the schema ``release`` at 0..``schema_max``, any vocabulary/model/prompts."""
    t: dict[str, Any] = {
        "format": "trialbox-update-compat/1",
        "bundle_id": bundle_id,
        "rows": [
            {
                "schema": {"release": {"min": 0, "max": schema_max}},
                "vocabulary_release": "*",
                "model_pin": "*",
                "prompt_registry": "*",
            }
        ],
    }
    if provides is not None:
        t["provides"] = {"schema": {"release": provides}, "model_pin": "drill-judge@1", "vocabulary_release": None,
                         "prompt_registry": None}  # fmt: skip
    return t


def release_and_lock(image_tar: Path, seq: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Provisional ``release.json`` (T-110) and the release's ``images.lock`` (T-104) agreeing on the image digest."""
    digest = "sha256:" + hashlib.sha256(image_tar.read_bytes()).hexdigest()
    release = {"format": "trialbox-release/0-provisional", "release_seq": seq,
               "images": {"py": {"image": IMAGE_TAG, "digest": digest}}}  # fmt: skip
    lock = {"format": "trialbox-images-lock/1", "images": {"py": {"image": IMAGE_TAG, "digest": digest}}}
    return release, lock


def make_bundle(
    base: Path,
    key: Path,
    bundle_id: str,
    migrations: list[str],
    fail_check: bool = False,
    release_seq: int = 1,
    schema_max: int | None = None,
) -> Path:
    from tools.sign_bundle import build

    src = base / "payload" / bundle_id
    src.mkdir(parents=True, exist_ok=True)
    image = _image_tar(src / "trialbox-py.tar", IMAGE_TAG)
    items = [("image", image, "trialbox-py_1.0.0.tar")]
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
    release, lock = release_and_lock(image, release_seq)
    smax = len(migrations) if schema_max is None else schema_max
    build(key, bundle_id, items, out, release_seq=release_seq, release=release, images_lock=lock,
          compat=compat_table(bundle_id, smax, len(migrations)))  # fmt: skip
    return out


def _stage(bundle: Path, pub: Path, stage: Path, updates: Path | None = None, downgrade: str | None = None,
           trust_only: Path | None = None) -> Any:  # fmt: skip
    from tools.trialbox.update import Plan
    from tools.verify_update import summary, verify

    kw: dict[str, Any] = {}
    if updates is not None:
        kw = {"trust_file": updates / "trust.json", "installed_file": updates / "installed.json"}
    elif trust_only is not None:  # the box's trust but not its installed state
        kw = {"trust_file": trust_only / "trust.json"}
    m = verify(bundle, pub, stage, allow_downgrade=downgrade, **kw)
    s = summary(m)
    (stage.parent / f"{stage.name}.summary.json").write_text(json.dumps(s), encoding="utf-8")
    return Plan.load(stage, s)


def _tables(url: str) -> list[str]:
    from tb_common.db import Database

    with Database.connect(url, "release") as db:
        return sorted(
            str(r[0])
            for r in db.fetchall(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?", (db.schema,)
            )
        )


def plaintext_dumps(roots: list[Path], since: float) -> list[str]:
    """``find <roots> -name '*.sql' -o -name '*.dump' -newer <start>``: plaintext dumps written since ``since``."""
    out = []
    for r in roots:
        for f in r.rglob("*") if r.is_dir() else []:
            if r.name == "box-run" and f.relative_to(r).parts[0] == "updates":
                continue  # the bundles' own files (their migration scripts), copied by apply: not dumps
            if f.is_file() and (f.suffix in (".sql", ".dump", ".restore")) and f.stat().st_mtime >= since:
                out.append(str(f))
    return sorted(out)


# ------------------------------------------------------------------------------------------------ kill -9 child
def child(args: argparse.Namespace) -> int:
    """One update in its own process, SIGKILLed as it enters ``--kill-at`` (``update_drill child``)."""
    import logging

    from tools.trialbox.update import InProcessBox, Plan, Updater

    logging.disable(logging.INFO)
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    plan = Plan.load(Path(args.stage), summary)
    box = InProcessBox(Path(args.work), os.environ["TB_DB_URL"], Path(args.backups))

    def kill(step: str) -> None:
        if step == args.kill_at:
            os.kill(os.getpid(), signal.SIGKILL)

    Updater(box, Path(args.updates), say=lambda _m: None, on_step=kill).run(plan)
    return 0


def kill_case(
    base: Path, work: Path, url: str, pub: Path, priv: Path, step: str, seq: int
) -> list[tuple[str, bool, str]]:
    from tools import update_status as us
    from tools.trialbox.update import STEPS, InProcessBox, UpdateFailed, Updater

    updates = base / "updates"
    bid = f"2026.11-kill-{STEPS.index(step)}"
    bundle = make_bundle(base, priv, bid, [MIGRATION_1, MIGRATION_2_OK], release_seq=seq)
    stage = base / f"stage-{bid}"
    _stage(bundle, pub, stage, updates)
    box = InProcessBox(work, url, base / "backups")
    before = (box.state(), (work / "RELEASE").read_text(encoding="utf-8"), _tables(url), box.schema_version())
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "tools.update_drill", "child", "--work", str(work), "--updates",
                        str(updates), "--backups", str(base / "backups"), "--stage", str(stage), "--summary",
                        str(base / f"{stage.name}.summary.json"), "--kill-at", step],
                       cwd=ROOT, capture_output=True, text=True, check=False)  # fmt: skip
    out: list[tuple[str, bool, str]] = []
    st = us.status(updates)
    u = st.get("update") or {}
    out.append((f"kill -9 at '{step}': status names the step and the bundle",
                r.returncode == -signal.SIGKILL and st["in_progress"] and u.get("step") == step
                and u.get("bundle_id") == bid and u.get("state") == "interrupted",
                f"exit {r.returncode}; {u.get('bundle_id')} step {u.get('step')!r} {u.get('state')}"
                + (f"; {r.stderr.strip()[-200:]}" if r.returncode != -signal.SIGKILL else "")))  # fmt: skip
    try:
        Updater(InProcessBox(work, url, base / "backups"), updates, say=lambda _m: None).run(
            _stage(bundle, pub, base / f"stage-{bid}-again", updates)
        )
        refused = False
    except UpdateFailed as exc:
        refused = "unfinished" in str(exc)
    out.append((f"kill -9 at '{step}': another update is refused while the marker exists", refused, ""))
    lines: list[str] = []
    try:
        Updater(InProcessBox(work, url, base / "backups"), updates, say=lines.append).recover(bid)
        recovered = True
    except UpdateFailed as exc:
        recovered, lines = False, [*lines, str(exc)]
    box2 = InProcessBox(work, url, base / "backups")
    box2._open_stores()  # the box starts: every store opens and runs its own migrations
    after = (box2.state(), (work / "RELEASE").read_text(encoding="utf-8"), _tables(url), box2.schema_version())
    out.append((f"kill -9 at '{step}': rollback <bundle> puts the box back, the marker is gone, the box starts",
                recovered and us.marker(updates) is None and after == before
                and not (updates / bid / "rollback").exists() and not plaintext_dumps([updates, work], t0),
                "; ".join(lines[-3:])[:300]))  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ the db image
def db_image_case(base: Path) -> tuple[str, str]:
    """The compose box's dump and restore of ``trialbox_wf`` on the box's database image. ``(PASS|FAIL|SKIP, why)``."""
    from tools.trialbox import update as up

    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    image = lock["images"]["db"]["image"]
    if not shutil.which("docker"):
        return "SKIP", "no docker here"
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False).returncode != 0:
        return "SKIP", f"image {image} is not built here (docker build -f deploy/docker/db.Dockerfile)"
    name = f"tb-update-drill-db-{uuid.uuid4().hex[:8]}"
    init = ROOT / "deploy" / "docker" / "db-init"
    run = up.run_cmd

    def translated(argv: Any, stdin_file: Path | None = None, stdout_file: Path | None = None,
                   env: dict[str, str] | None = None, timeout: float | None = None) -> str:  # fmt: skip
        a = list(argv)
        assert a[:4] == ["compose", "exec", "-T", "db"], a
        return run(["docker", "exec", "-i", name, *a[4:]], stdin_file, stdout_file, env, timeout)

    def psql(sql: str) -> str:
        return run(["docker", "exec", "-i", name, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-U", "trialbox",
                    "-d", "trialbox_wf", "-c", sql])  # fmt: skip

    def ready() -> bool:
        deadline = time.time() + 180
        while time.time() < deadline:
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, check=False)
            if "init process complete" in logs.stdout + logs.stderr or "Skipping initialization" in logs.stdout:
                with contextlib.suppress(up.UpdateFailed):
                    if psql("SELECT 1").strip() == "1":
                        return True
            time.sleep(1)
        return False

    try:
        run(["docker", "run", "-d", "--name", name, "-e", "POSTGRES_DB=hapi", "-e", "POSTGRES_USER=hapi",
             "-e", "POSTGRES_PASSWORD=drill", "-e", "POSTGRES_WF_PASSWORD=drill", "-v",
             f"{init}:/docker-entrypoint-initdb.d:ro", image])  # fmt: skip
        if not ready():
            return "FAIL", "the database did not start"
        psql("CREATE SCHEMA site; CREATE TABLE site.marks (id INT PRIMARY KEY, mark TEXT); "
             "INSERT INTO site.marks VALUES (1, 'approach'); "
             "CREATE TABLE site.vec (id INT PRIMARY KEY, e vector(3)); "
             "INSERT INTO site.vec VALUES (1, '[1,2,3]')")  # fmt: skip
        rb = base / "dbimage" / "rollback"
        rb.mkdir(parents=True)
        box = up.ComposeBox(base / "dbimage", run=translated)
        box.compose = ["compose"]
        f = rb / "trialbox_wf.dump"
        box._dump("trialbox_wf", "trialbox", f)  # exactly the compose box's rollback-point dump
        point = up.Point(dumps={"trialbox_wf": str(up.seal(f, rb))})
        psql(
            "CREATE TABLE site.extra (id INT); UPDATE site.marks SET mark = 'changed'; CREATE SCHEMA later; "
            "CREATE TABLE later.t (id INT); CREATE TABLE public.extra (id INT)"
        )  # the new release's work
        try:
            box.restore_databases(rb, point)  # exactly the compose box's rollback restore
        except up.UpdateFailed as exc:
            return "FAIL", f"the compose box's pg_restore of trialbox_wf failed on the db image: {str(exc)[-300:]}"
        run(["docker", "restart", name])
        if not ready():
            return "FAIL", "the database did not start again after the restore"
        got = psql("SELECT (SELECT mark FROM site.marks WHERE id = 1), (SELECT count(*) FROM information_schema.tables "
                   "WHERE (table_schema, table_name) IN (('site', 'extra'), ('later', 't'), ('public', 'extra'))), "
                   "(SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension "
                   "WHERE extname IN ('vector', 'pgroonga')), "
                   "(SELECT e::text FROM site.vec WHERE id = 1)").strip()  # fmt: skip
        want = "approach|0|pgroonga,vector|[1,2,3]"
        return ("PASS" if got == want else "FAIL"), f"after restore and restart: {got} (want {want})"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


# ------------------------------------------------------------------------------------------------ the drill
def run(base: Path) -> dict[str, Any]:
    from tb_common.audit import verify as audit_verify

    from tools import e2e_simple, pglocal
    from tools import update_status as us
    from tools.sign_bundle import keygen
    from tools.trialbox.update import STEPS, InProcessBox, UpdateFailed, Updater, UpdateRefused
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
    updates = base / "updates"

    priv, pub = keygen(base / "vendor")
    good = make_bundle(base, priv, "2026.11-step8-a", [MIGRATION_1], release_seq=2)
    old = make_bundle(base, priv, "2026.11-step8-old", [MIGRATION_1], release_seq=1)
    bad_sql = make_bundle(base, priv, "2026.11-step8-b", [MIGRATION_1, MIGRATION_2_BAD], release_seq=3)
    bad_run = make_bundle(base, priv, "2026.11-step8-c", [MIGRATION_1, MIGRATION_2_OK], fail_check=True,
                          release_seq=4)  # fmt: skip
    too_new = make_bundle(base, priv, "2026.11-step8-z", [], release_seq=5, schema_max=0)
    full = make_bundle(base, priv, "2026.11-step8-full", [MIGRATION_1, MIGRATION_2_OK], release_seq=6)

    tampered = base / "bundles" / "tampered.tar"
    with tarfile.open(good) as src, tarfile.open(tampered, "w") as dst:  # one model payload changed, same size
        for m in src.getmembers():
            fh = src.extractfile(m) if m.isfile() else None
            body = fh.read() if fh else b""
            if m.name.endswith("judge/new.bin"):
                body = bytes([body[0] ^ 0xFF]) + body[1:]
            dst.addfile(m, io.BytesIO(body) if fh else None)
    try:
        _stage(tampered, pub, base / "stage-tampered", updates)
        refused = False
    except Rejected:
        refused = True
    checks.append(("a tampered bundle is refused before anything changes", refused, ""))

    box = InProcessBox(work, url, base / "backups")
    lines: list[str] = []
    up = Updater(box, updates, say=lines.append)
    start = time.time()
    plan = _stage(good, pub, base / "stage-a", updates)
    out = up.run(plan)
    backups = sorted((base / "backups" / "nas").glob("*.tbbak"))
    checks.append(("good bundle: backed up first (D-126), the hospital key opens it", len(backups) == 1,
                   backups[0].name if backups else ""))  # fmt: skip
    checks.append(("good bundle: applied, migrated, data unchanged, audited", bool(out["ok"]), "; ".join(lines[-6:])))
    checks.append(("good bundle: release, new model and migration in place",
                   (work / "RELEASE").read_text(encoding="utf-8").startswith("2026.11-step8-a")
                   and (models / "new.bin").exists() and _tables(url) == ["_schema_version", "release_note"]
                   and box.schema_version() == 1, (work / "RELEASE").read_text(encoding="utf-8").strip()))  # fmt: skip
    inst = us.installed(updates)
    left = plaintext_dumps([updates, work, base / "backups"], start)
    checks.append(("good bundle: installed.json at release_seq 2, trust.json written, marker and rollback point gone, "
                   "no plaintext dump (find -name '*.sql' -newer start)",
                   inst["release_seq"] == 2 and inst["state"]["schema"].get("release") == 1
                   and (updates / "trust.json").is_file() and us.marker(updates) is None
                   and not (updates / "2026.11-step8-a" / "rollback").exists() and not left,
                   f"installed {inst['release_seq']}, state {inst['state']}; plaintext {left[:3]}"))  # fmt: skip

    try:
        _stage(old, pub, base / "stage-old", updates)
        older = False
    except Rejected as exc:
        older = "release_seq 1 is not above the installed 2" in str(exc)
    checks.append(("an older release_seq is refused", older, ""))
    lines.clear()
    out = up.run(_stage(old, pub, base / "stage-old2", updates, downgrade="drill: vendor asked to go back"))
    checks.append(("--allow-downgrade applies it and audits update.downgrade",
                   bool(out["ok"]) and us.installed(updates)["release_seq"] == 1, "; ".join(lines[:2])))  # fmt: skip
    after_good = (work / "RELEASE").read_text(encoding="utf-8"), (models / "config.json").read_text(encoding="utf-8")

    try:
        _stage(too_new, pub, base / "stage-z", updates)
        compat_v = False
    except Rejected as exc:
        compat_v = "compatibility table" in str(exc) and "newer than this bundle knows" in str(exc)
    plan_z = _stage(too_new, pub, base / "stage-z2", trust_only=updates)  # no installed state: the preflight's
    try:
        up.run(plan_z)
        compat_u = False
    except UpdateRefused as exc:
        compat_u = "compatibility table" in str(exc)
    checks.append(("compat.json: a bundle that does not know the box's schema version is refused by the verifier "
                   "and by the preflight, nothing changed", compat_v and compat_u and us.marker(updates) is None,
                   ""))  # fmt: skip

    for label, bundle, stage in (("bad migration", bad_sql, "stage-b"), ("unhealthy release", bad_run, "stage-c")):
        plan = _stage(bundle, pub, base / stage, updates)
        lines.clear()
        try:
            up.run(plan)
            failed = False
        except UpdateFailed:
            failed = True
        same = ((work / "RELEASE").read_text(encoding="utf-8"), (models / "config.json").read_text(encoding="utf-8"))
        checks.append((f"{label}: the update fails and rolls back", failed and any("rollback" in x for x in lines),
                       "; ".join(x for x in lines if "FAIL" in x or "rollback" in x)[:300]))  # fmt: skip
        checks.append((f"{label}: release, models, database and data as before; marker gone",
                       same == after_good and _tables(url) == ["_schema_version", "release_note"]
                       and box.schema_version() == 1 and box.state() == box.before and us.marker(updates) is None,
                       f"schema version {box.schema_version()}"))  # fmt: skip

    plan = _stage(full, pub, base / "stage-full", updates)
    hist = (updates / "history.jsonl").read_text(encoding="utf-8")
    full_up = Updater(box, updates, say=lambda _m: None, disk_free=lambda _p: 1024)
    try:
        full_up.run(plan)
        disk = ""
    except UpdateRefused as exc:
        disk = str(exc)
    nothing = (us.marker(updates) is None and not (updates / "2026.11-step8-full").exists()
               and (updates / "history.jsonl").read_text(encoding="utf-8") == hist)  # fmt: skip
    checks.append(("disk full: the preflight refuses with the numbers needed and free; nothing changed",
                   "not enough disk space" in disk and "needs" in disk and "free 0.00 GB" in disk and nothing,
                   disk[:300]))  # fmt: skip

    for i, step in enumerate(STEPS):
        checks += kill_case(base, work, url, pub, priv, step, 10 + i)

    verdict, why = db_image_case(base)
    db_check = (f"db image: the compose box's rollback restore of trialbox_wf, and the database starts [{verdict}]",
                verdict == "PASS", why)  # fmt: skip

    audit_dir = work / "box" / "audit"
    events = []
    for f in sorted(audit_dir.glob("*.jsonl")):
        events += [json.loads(x)["event"] for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    upd = [e for e in events if e.startswith("update.")]
    want = ["update.applied", "update.downgrade", "update.applied", "update.rolled_back", "update.rolled_back",
            *["update.rolled_back"] * len(STEPS)]  # fmt: skip
    checks.append(("the audit chain verifies, with every update event in order",
                   audit_verify(audit_dir).ok and upd == want, ", ".join(upd)))  # fmt: skip
    history = (updates / "history.jsonl").read_text(encoding="utf-8")
    checks.append(("the update history holds no secret", password not in history and "PRIVATE" not in history,
                   f"{len(history.splitlines())} lines"))  # fmt: skip

    if not external_db:
        os.environ.pop("TB_DB_URL", None)
        res2 = e2e_simple.run(base / "box-after", secrets.token_urlsafe(12), "ja")
        checks.append(("after the updates, e2e_simple passes on a fresh box", bool(res2["ok"]), ""))
    skipped = [db_check] if verdict == "SKIP" else []
    if not skipped:
        checks.append(db_check)
    return {"ok": all(c[1] for c in checks), "checks": checks, "skipped": skipped,
            "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip


# ------------------------------------------------------------------------------------- 10K-7: update from a stick
#: the drill's site: Tokyo's clock, the quiet hour from 05:00 for 2 hours (D-731's defaults)
STICK_ENV = {"TB_TZ": "Asia/Tokyo", "TB_UPDATE_QUIET_AT": "05:00", "TB_UPDATE_QUIET_HOURS": "2"}
STICK_DAY = "2026-11-19T06:00:00+00:00"  # 15:00 in Tokyo: the administrator asks; not the quiet hour
STICK_QUIET = "2026-11-19T20:30:00+00:00"  # 05:30 the next morning in Tokyo: the quiet hour
STICK_SOURCE: dict[str, Any] = {
    "format": "trialbox-release-note/1",
    "title_ja": "ドリル用リリース（合成）",
    "summary_ja": "更新用USBメモリからの更新ドリルのための合成リリースです。",
    "changes": {
        "CC1": {"changed": False},
        "CC2": {"changed": False, "what_ja": ""},
        "CC3": {"changed": False},
        "CC4": {"changed": True, "what_ja": "画面の文言を変更しました。"},
        "CC5": {"changed": False},
        "CC6": {"changed": False},
    },
    "impact": {
        "downtime_minutes": 20,
        "database_migration": False,
        "ruleset_reapproval": False,
        "site_actions_ja": ["適用の翌朝、運用画面で結果を確認してください。"],
    },
}


class StickBox:
    """The update path's box in memory for the stick drill: which release runs, and each update event it audits. The
    stores, images and databases of a real update are the main drill's (``run``); this one needs no database."""

    name = "stick-drill"

    def __init__(self) -> None:
        self.release = "factory"
        self.audits: list[str] = []

    def running(self) -> bool:
        return True

    def backup(self, plan: Any, rb: Path) -> str:
        return "nas (drill)"

    def resume(self, plan: Any) -> None:
        return None

    def snapshot(self, plan: Any, rb: Path, point: Any) -> None:
        (rb / "release.before").write_text(self.release, encoding="utf-8")

    def apply(self, plan: Any, rb: Path, point: Any) -> list[str]:
        self.release = plan.bundle_id
        return [f"release {plan.bundle_id}"]

    def restart(self, plan: Any) -> None:
        return None

    def post_apply(self, plan: Any) -> list[str]:
        return []

    def check(self, plan: Any) -> str:
        return "healthy"

    def rollback(self, plan: Any, rb: Path, point: Any) -> None:
        self.release = (rb / "release.before").read_text(encoding="utf-8")

    def audit(self, event: str, plan: Any, detail: dict[str, Any]) -> None:
        self.audits.append(event)


def stick_bundle(base: Path, key: Path, bundle_id: str, release_seq: int, note: bool = True) -> Path:
    """A synthetic signed bundle as ``tools/make_bundle.sh`` lays one out for this card: a payload, the compat table,
    and (``note``) the Japanese release note and change-impact sheet built by ``tools/release_note.py``."""
    from tools import release_note
    from tools.sign_bundle import build

    src = base / "payload" / bundle_id
    src.mkdir(parents=True, exist_ok=True)
    (src / "config.json").write_text(json.dumps({"bundle": bundle_id}), encoding="utf-8")
    items = [("other", src / "config.json", "config.json")]
    if note:
        source = src / "release-note.ja.yaml"
        source.write_text(json.dumps(STICK_SOURCE, ensure_ascii=False), encoding="utf-8")  # JSON is YAML
        n, i = release_note.build(source, bundle_id, release_seq, src / "note")
        items += [("other", n, release_note.NOTE), ("other", i, release_note.IMPACT)]
    out = base / "bundles" / f"trialbox-{bundle_id}.tar"
    out.parent.mkdir(parents=True, exist_ok=True)
    build(key, bundle_id, items, out, release_seq=release_seq, compat=compat_table(bundle_id, 0))
    return out


def stick_drill(base: Path) -> dict[str, Any]:
    """10K-7 (D-1363): insert, verify, apply in the quiet hour, roll back, with the operations runner the console's
    requests reach (``tools/trialbox/ops.py``) on a frozen clock. The runner's call of ``tools/apply_update.sh`` runs
    the same verifier and update path in this process (``verify_update.verify``, ``Updater``); the console's own
    pages are ``tests/console/test_ops_pages.py``.

    1. The box runs release 1 (``release_seq`` 1, applied as any update).
    2. **Insert**: release 2's bundle on a "stick" folder (``TB_UPDATE_STICK``) is listed in the status when a
       listing is asked for (``update_stick_list``).
    3. **Verify**: ``update_check`` with ``from: stick`` copies it into the incoming folder and verifies it; the status
       carries its Japanese release note and the change-impact sheet listing CC1 to CC6. A tampered bundle on the
       stick is refused and shows no note; a link on the stick is not listed and not copied.
    4. **Apply in the quiet hour**: ``update_apply`` with ``when: quiet`` asked at 15:00 waits (the status says why);
       at 05:30 the next morning, no job running, it runs: release 2, ``installed.json`` at 2, the status names
       release 1 as the previous release.
    5. **Roll back**: release 1's bundle with ``--allow-downgrade REASON`` (the older-release path of RUNBOOK §5; the
       console shows it, D-1363) returns the box to release 1, ``update.downgrade`` audited.
    """
    from datetime import datetime

    from tools import update_status as us
    from tools.sign_bundle import keygen
    from tools.trialbox import ops as tb_ops
    from tools.trialbox.update import Plan, Updater
    from tools.verify_update import Rejected, summary, verify

    t0 = time.perf_counter()
    checks: list[tuple[str, bool, str]] = []
    priv, pub = keygen(base / "vendor")
    deploy, stick = base / "deploy", base / "stick"
    updates = deploy / "updates"
    box = StickBox()
    said: list[str] = []
    updater = Updater(box, updates, say=said.append)
    clock = [datetime.fromisoformat(STICK_DAY)]

    def plan_of(bundle: Path, downgrade: str | None = None) -> tuple[Any, list[str]]:
        stage = Path(tempfile.mkdtemp(prefix="stage-", dir=base))
        m = verify(bundle, pub, stage, trust_file=updates / "trust.json", installed_file=updates / "installed.json",
                   allow_downgrade=downgrade)  # fmt: skip
        return Plan.load(stage, summary(m)), list((m.get("release_note") or {}).get("warnings") or [])

    def apply_update(argv: Any, timeout: int | None) -> str:
        """``sh tools/apply_update.sh <bundle> [--dry-run]`` as the runner calls it: verify, then the update path."""
        bundle = Path(argv[2])
        try:
            plan, warns = plan_of(bundle)
        except Rejected as exc:
            raise tb_ops.OpsFailed(f"exit 1: REJECTED: {exc}") from exc
        lines = [f"verified: {plan.bundle_id} release_seq {plan.release_seq}", *(f"WARNING: {w}" for w in warns)]
        if "--dry-run" in argv:
            return "\n".join([*lines, "dry run: nothing applied"])
        out = updater.run(plan)
        return "\n".join([*lines, f"applied: {bool(out.get('ok'))}"])

    class Runner(tb_ops.OpsRunner):
        def now(self) -> datetime:
            return clock[0]

        def jobs_running(self) -> int | None:
            return 0

        def apply_limit(self) -> int | None:
            return None

        def audit(self, res: Any) -> None:  # the compose box's audit chain; the update path audits on StickBox
            return None

    env = {**STICK_ENV, "TB_UPDATE_STICK": str(stick), "TB_UPDATE_INCOMING": str(updates / "incoming")}
    runner = Runner(tb_ops.Box("compose", deploy, env, apply_update), tb_ops.OpsDir(base / "ops"))
    ops = runner.ops

    def ask(action: str, **args: str) -> str:
        return ops.submit(action, "console:admin", args)

    # 1. the box at release 1
    r1 = stick_bundle(base, priv, "2026.11-stick-1", 1)
    plan1, _ = plan_of(r1)
    updater.run(plan1)
    checks.append(("the box runs release 1", box.release == "2026.11-stick-1" and us.installed(updates)["release_seq"]
                   == 1, box.release))  # fmt: skip

    # 2. insert
    r2 = stick_bundle(base, priv, "2026.11-stick-2", 2)
    stick.mkdir(parents=True)
    shutil.copy2(r2, stick / r2.name)
    bad = stick / "trialbox-2026.11-stick-2-tampered.tar"
    with tarfile.open(r2) as src, tarfile.open(bad, "w") as dst:  # the release note changed, same size: tampering
        for m in src.getmembers():
            fh = src.extractfile(m) if m.isfile() else None
            body = fh.read() if fh else b""
            if m.name.endswith("RELEASE-NOTE.ja.md"):
                body = body.replace("合成".encode(), "本番".encode())
            dst.addfile(m, io.BytesIO(body) if fh else None)
    (stick / "trialbox-link.tar").symlink_to(r2)
    ask("update_stick_list")  # the third review, M2: the stick is read when a listing is asked for, not on a pass
    runner.run_pending()
    st = json.loads((base / "ops" / "status.json").read_text(encoding="utf-8"))
    sk = st.get("stick") or {}
    listed = [b["name"] for b in sk.get("bundles") or []]
    checks.append(("insert: the stick's bundles are listed (a link is not)", bool(sk.get("mounted"))
                   and listed == sorted([r2.name, bad.name]), ", ".join(listed)))  # fmt: skip

    # 3. verify from the stick
    rid = ask("update_check", bundle=r2.name, **{"from": "stick"})
    rbad = ask("update_check", bundle=bad.name, **{"from": "stick"})
    rlink = ask("update_check", bundle="trialbox-link.tar", **{"from": "stick"})
    runner.run_pending()
    res, resbad, reslink = ops.result(rid) or {}, ops.result(rbad) or {}, ops.result(rlink) or {}
    # as the console reads them: the status file, then the note record of the verified sha256 (D-1363)
    st = json.loads((base / "ops" / "status.json").read_text(encoding="utf-8"))
    vf = (st.get("verified") or {}).get(r2.name) or {}
    sha = hashlib.sha256((updates / "incoming" / r2.name).read_bytes()).hexdigest()
    _state, rec = ops.note_record(r2.name, str(vf.get("sha256") or ""))
    note = rec or {}
    sheet = note.get("impact") or {}
    checks.append(("verify: copied from the stick into the incoming folder and verified, nothing applied",
                   bool(res.get("ok")) and (updates / "incoming" / r2.name).is_file()
                   and box.release == "2026.11-stick-1", str(res.get("summary"))))  # fmt: skip
    checks.append(("verify: the verified record is that file's sha256, the status is small and holds no note",
                   vf.get("sha256") == sha and "note_ja" not in json.dumps(st) and "notes" not in st
                   and (base / "ops" / "status.json").stat().st_size < tb_ops.MAX_JSON, sha[:12]))  # fmt: skip
    checks.append(("verify: the Japanese release note is shown with the verification",
                   "ドリル用リリース" in str(note.get("note_ja")) and note.get("bundle_id") == "2026.11-stick-2",
                   str(note.get("warnings"))))  # fmt: skip
    checks.append(("verify: the change-impact sheet lists the change classes CC1 to CC6",
                   [c.get("class") for c in sheet.get("classes") or []] == ["CC1", "CC2", "CC3", "CC4", "CC5", "CC6"]
                   and [c["class"] for c in sheet["classes"] if c.get("changed")] == ["CC4"],
                   str(sheet.get("downtime_minutes"))))  # fmt: skip
    checks.append(("verify: a tampered bundle on the stick is refused, shows no note and is not left on the box",
                   resbad.get("ok") is False and "REJECTED" in str(resbad.get("summary")) and bad.name not in
                   (st.get("verified") or {}) and not (base / "ops" / "notes" / f"{bad.name}.json").exists()
                   and not (updates / "incoming" / bad.name).exists(),
                   str(resbad.get("summary"))[:120]))  # fmt: skip
    checks.append(("verify: a link on the stick is not followed", reslink.get("ok") is False
                   and not (updates / "incoming" / "trialbox-link.tar").exists(),
                   str(reslink.get("summary"))[:120]))  # fmt: skip

    # 4. apply in the quiet hour
    rq = ask("update_apply", bundle=r2.name, when="quiet", sha256=sha)  # as the console asks: the verified file
    asked_at = clock[0].timestamp()  # the request file's time as the frozen clock's: it was asked at 15:00
    os.utime(base / "ops" / "requests" / f"{rq}.json", (asked_at, asked_at))
    runner.run_pending()
    waiting = runner.write_status().get("waiting") or []
    checks.append(("asked at 15:00 for the quiet hour: it waits and says why, nothing applied",
                   ops.result(rq) is None and box.release == "2026.11-stick-1" and len(waiting) == 1
                   and "waits for the quiet hour" in str(waiting[0].get("why")), str(waiting[:1])))  # fmt: skip
    clock[0] = datetime.fromisoformat(STICK_QUIET)
    runner.run_pending()
    done = ops.result(rq) or {}
    st = runner.write_status()
    checks.append(("at 05:30 in the quiet hour, no job running: applied (backup first, release 2, installed at 2)",
                   bool(done.get("ok")) and box.release == "2026.11-stick-2" and us.installed(updates)["release_seq"]
                   == 2 and not st.get("waiting"), str(done.get("summary"))))  # fmt: skip
    checks.append(("the status names release 1 as the previous release",
                   (st.get("version") or {}).get("previous") == "2026.11-stick-1", str(st.get("version"))))  # fmt: skip

    # 5. return to the previous release
    try:
        plan_of(r1)
        older = False
    except Rejected as exc:
        older = "not above the installed 2" in str(exc)
    plan_back, _ = plan_of(r1, downgrade="drill: return to the previous release")
    back = updater.run(plan_back)
    checks.append(("roll back: release 1's bundle is refused as it is, and applied as an older release with a reason",
                   older and bool(back.get("ok")) and box.release == "2026.11-stick-1"
                   and us.installed(updates)["release_seq"] == 1, box.release))  # fmt: skip
    checks.append(("the update events in order: applied, applied, downgrade, applied",
                   box.audits == ["update.applied", "update.applied", "update.downgrade", "update.applied"],
                   ", ".join(box.audits)))  # fmt: skip
    return {"ok": all(c[1] for c in checks), "checks": checks, "skipped": [],
            "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip


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
    from tb_common.config import adopt_site_tz

    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    adopt_site_tz()  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["backup-work"]:
        ap = argparse.ArgumentParser(prog="update_drill backup-work")
        ap.add_argument("--to", type=Path, required=True)
        ap.add_argument("--work", type=Path, default=Path(os.environ.get("TB_DEMO_DIR") or scratch_root() / "tb-demo"))
        b = ap.parse_args(argv[1:])
        print(backup_work(b.work, b.to))
        return 0
    if argv[:1] == ["stick"]:  # 10K-7 (D-1363)
        ap = argparse.ArgumentParser(prog="update_drill stick")
        ap.add_argument("--dir", type=Path, default=scratch_root() / "tb-update-stick-drill")
        d = ap.parse_args(argv[1:]).dir
        if (why := drill_dir(d)) is not None:
            print(f"refused: {why}", file=sys.stderr)
            return 2
        return _report(stick_drill(d), "update-from-a-stick drill")
    if argv[:1] == ["child"]:
        ap = argparse.ArgumentParser(prog="update_drill child")
        for name in ("--work", "--updates", "--backups", "--stage", "--summary", "--kill-at"):
            ap.add_argument(name, required=True)
        return child(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--dir", type=Path, default=Path(os.environ.get("TB_UPDATE_DRILL_DIR") or scratch_root() / "tb-update-drill")
    )
    a = ap.parse_args(argv)
    import logging

    logging.disable(logging.INFO)
    if (why := drill_dir(a.dir)) is not None:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    return _report(run(a.dir), "update drill")


#: H4 of the review of d314d016 (D-1363): the file a drill writes into the folder it makes; ``--dir`` names a folder
#: that holds it, or one that does not exist yet
DRILL_MARK = ".tb-update-drill"


def _parent_ok(st: os.stat_result) -> bool:
    """M1 of the third review (D-1363): a folder no other account can change entries in: the caller's own or root's,
    and not writable by group or others unless sticky (``/var/tmp`` itself: only an entry's owner moves it)."""
    mine = st.st_uid in (os.geteuid(), 0)
    return mine and (not st.st_mode & 0o022 or bool(st.st_mode & stat.S_ISVTX))


def drill_dir(d: Path) -> str | None:
    """The drill's working folder, emptied for this run: made new (with :data:`DRILL_MARK`) when ``d`` does not exist;
    emptied when it is a real folder holding the mark, a regular file the drill wrote. Anything else (a folder without
    the mark, such as a backup folder; a link, even to a drill's folder; a file) is refused BEFORE anything is
    removed: the reason, else None.

    M1 of the third review (D-1363): every folder from ``/`` down to ``d``'s parent must be one no other account can
    change (:func:`_parent_ok`: the default ``/var/tmp/trialbox-<uid>`` can be made first by any local account), and
    ``d`` must be the caller's own. ``d`` is then opened ONCE through its parent's descriptor without following a link
    and emptied through its own descriptor (``unlink``/``rmtree`` with ``dir_fd``): a folder swapped for a link
    after the check changes nothing outside the folder that was checked."""
    d = Path(os.path.abspath(d))
    parent = Path(os.path.realpath(d.parent))
    walk = [parent, *parent.parents]
    for anc in reversed(walk):  # from / down: an ancestor that does not exist yet is made below, the caller's own
        try:
            st = os.lstat(anc)
        except FileNotFoundError:
            break
        if not _parent_ok(st):
            who = "owned by another account" if st.st_uid not in (os.geteuid(), 0) else "writable by others"
            return (f"--dir {d}: the folder {anc} is {who}; nothing was removed. Give a folder whose parents only "
                    "you (or root) can change")  # fmt: skip
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        pfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        return f"--dir {d}: its parent {parent} cannot be opened as a folder ({exc.strerror})"
    try:
        if not _parent_ok(os.fstat(pfd)):
            return f"--dir {d}: the folder {parent} changed while it was checked; nothing was removed"
        made = False
        try:
            os.mkdir(d.name, 0o700, dir_fd=pfd)
            made = True
        except FileExistsError:
            pass
        try:
            dfd = os.open(d.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=pfd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                return f"--dir {d} is a link; give the folder itself (the drill never follows a link)"
            return f"--dir {d} exists and is not a folder"
    finally:
        os.close(pfd)
    try:
        st = os.fstat(dfd)
        if st.st_uid != os.geteuid():
            return f"--dir {d} is owned by another account; nothing was removed"
        if made:
            fd = os.open(DRILL_MARK, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dfd)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("made by tools/update_drill.py; emptied by its next run\n")
            return None
        try:
            mark = os.stat(DRILL_MARK, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            mark = None
        if mark is None or not stat.S_ISREG(mark.st_mode):
            return (f"--dir {d} exists and was not made by this drill (no {DRILL_MARK} in it); nothing was removed. "
                    "Give a folder that does not exist yet")  # fmt: skip
        with os.scandir(dfd) as it:  # the folder itself stays: emptied, never replaced
            children = [(c.name, c.is_dir(follow_symlinks=False)) for c in it]
        for name, is_dir in children:
            if is_dir:
                shutil.rmtree(name, dir_fd=dfd)
            elif name != DRILL_MARK:
                os.unlink(name, dir_fd=dfd)
        return None
    finally:
        os.close(dfd)


def _report(out: dict[str, Any], what: str) -> int:
    for name, ok, detail in out["checks"]:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    for name, _ok, detail in out["skipped"]:
        print(f"SKIP  {name}  ({detail})")
    print(f"{what} {'PASSED' if out['ok'] else 'FAILED'} in {out['seconds']} s"
          + (f" ({len(out['skipped'])} case skipped)" if out["skipped"] else ""))  # fmt: skip
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
