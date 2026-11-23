"""Backup and restore drill (TB-PLAN-04 step 2 done-check, D-126; extended for WS-08.6, D-187): a box that has run
the whole path is backed up by the nightly schedule, wiped, restored from the backup with the hospital's key, and must
then be the same box.

    python -m tools.backup_drill --dir /tmp/tb-drill        # exit 0 only when every check passes

1. ``e2e_simple``'s chain runs in ``<dir>/box-run`` (criteria -> report -> approval -> list -> marks -> mail ->
   REDCap -> log), on its own schemas of the trial database (``TB_DB_URL`` or the local throwaway cluster). An older
   snapshot's NDJSON and a spill file are put in its lake, so the layout rules have something to leave out.
2. A backup key pair is made; the nightly run (``backup_schedule.nightly``) writes the box to two targets (``nas``,
   declared off-box, and ``usb``) and records it. Checks: layout 2, every member hashed from the stream and the
   file's sha256 equal to its ``.sha256`` sidecar, the old NDJSON, the spill and the ``refdata`` rows left out and
   listed, the status green, and red with an alert (no patient data in it) once the backup is 37 hours old.
3. The box is wiped: its schemas dropped, its data folders moved away.
4. ``trialbox restore`` (private key) puts it back. Checks: every table's rows equal the backup's manifest (count and
   content hash), every file the layout takes equal, the audit hash chain verifies, the administrator signs in with
   the same password, and the investigator's marks read back through the site store as before; the trial lifecycle
   (participants, their steps and the visit schedule, D-134) reads back through the data core as before; the site
   set-up (D-135: inputs, facts with their status, the hospital codes' mapping, the "please check" answers) reads
   back through its store as before, and every uploaded chart file is back in the orchestrator's data folder; the
   licensed code lists (D-137: each release with its version, source and codes) read back through the terminology
   store as before; the OMOP store (D-151: the ``omop`` schema, loaded from the box's lake before the backup) has the
   same rows, the same provenance and conflicts, and exports the same lake; the reference data reads back as before.
5. A backup in the previous format (layout 1, gzip, as every backup before D-149) restores to the same box.
6. Postgres: the compose ``db`` service sets ``wal_compression=zstd``, ``default_toast_compression=lz4`` and archives
   WAL with pgBackRest (``compress-type=zst``); a throwaway cluster with these settings archives WAL, takes a base
   backup and is recovered to a point in time between two commits (PITR), with the TOAST column in lz4. pgBackRest
   itself needs its binary in the db image and runs on the box (RUNBOOK §5), not here.
7. The database extensions of the box's ``db`` image (``vector``, ``pgroonga``, D-204): on a server that offers them
   (``pg_available_extensions``), they exist after the restore with the versions they had before it, and a scratch
   database holding both, with a table that uses both, is dumped and restored over itself with the backup's own
   ``pg_dump`` / ``pg_restore --clean --if-exists --single-transaction`` (``tools.trialbox.backup``) as the drill's
   role, the extensions included. On a server without them (the local throwaway cluster) both checks say so and pass,
   unless ``--require-extensions``.
8. The vector store (schema ``vec``, D-439): where the database has ``vector``, synthetic notes are indexed before the
   backup (hash embedder) and, after the restore, every chunk, every vector, the model's HNSW index and a search read
   back the same. Without the extension the check says so and passes, unless ``--require-extensions``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import secrets
import shlex
import shutil
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

DATA_DIRS = ("box", "console", "lake", "sec")  # the work-dir folders that hold the box's files
DEPLOY = ROOT / "deploy"


def run(base: Path, require_extensions: bool = False) -> dict[str, Any]:
    from tb_common import refdata as rd
    from tb_common.audit import verify

    from tools import e2e_simple, pglocal
    from tools.trialbox import backup as bk
    from tools.trialbox import backup_schedule as bs

    work = base / "box-run"
    url = pglocal.for_work(work)
    password = secrets.token_urlsafe(12)
    t0 = time.perf_counter()
    res = e2e_simple.run(work, password, "ja")
    checks: list[tuple[str, bool, str]] = [("the box ran the whole path (e2e_simple)", bool(res["ok"]), "")]
    if not res["ok"]:
        # the failing checks of e2e_simple, whole, and the folder as the run left it: what follows (backup, wipe,
        # restore) proves nothing on a run that did not finish, and the wipe would take the evidence
        for st in res.get("stages") or []:
            checks += [(f"e2e_simple: {st.name}: {what}", False, detail) for what, ok, detail in st.checks if not ok]
        seconds = round(time.perf_counter() - t0, 1)
        return {"ok": False, "checks": checks, "seconds": seconds, "kept": str(work)}
    lake = work / "lake"
    for day in ("2000-01-30", "2000-01-31"):  # older snapshots' NDJSON (synthetic) and a DuckDB spill file
        old = lake / "ndjson" / day
        old.mkdir(parents=True, exist_ok=True)
        (old / "Patient.ndjson").write_text('{"resourceType":"Patient","id":"drill-old"}\n', encoding="utf-8")
    (lake / "tmp").mkdir(exist_ok=True)
    (lake / "tmp" / "spill.bin").write_bytes(b"\0" * 1024)
    dirs = {name: work / name for name in DATA_DIRS if (work / name).exists()}
    taken = {n: set(bk.select_files(n, p)[0]) for n, p in dirs.items()}
    before_files = {n: {k: v for k, v in bk.tree_hashes(p).items() if k in taken[n]} for n, p in dirs.items()}
    marks_before = _marks(work)
    life_before = _lifecycle()
    site_before = _sitesetup()
    terms_before = _terminology()
    with rd.RefStore() as st:
        packs_before = st.status()
    refrows_before = _refdata_rows()
    omop_before = _omop(work, load=True)
    ext_before = _extensions()
    vec_before = _vec(fill=True)
    charts_before = sorted(str(p.relative_to(work)) for p in (work / "box").rglob("sitesetup/*/inputs/*"))

    # 2. the nightly run, as the schedule runs it, with the in-process backup in place of the compose container
    keys = base / "keys"
    priv, pub = keys / "hospital-it.key", keys / "box.pub"
    for f in (priv, pub):
        f.unlink(missing_ok=True)
    bk.keygen(priv, pub)
    env = {**os.environ, "TB_DB_URL": url, "TB_SITE_ID": "DRILL"}
    nas, usb = base / "nas", base / "usb"
    nas.mkdir(parents=True, exist_ok=True)
    (nas / bs.OFFBOX_MARKER).write_text("drill: stands for the hospital share\n")  # same disk here, so marked
    cfg = bs.Config(deploy=base / "deploy", targets=[nas, usb], public_key=pub, production=True,
                    declared_offbox=[str(nas)], site="DRILL", mailto="it@hospital.example")  # fmt: skip
    events: list[tuple[str, dict[str, Any]]] = []
    when = datetime.now(UTC)
    night = bs.nightly(cfg, lambda ts: bk.backup(ts, pub, env=env, dirs=dirs, now=when),
                       lambda e, d: events.append((e, d)), now=when)  # fmt: skip
    files = [Path(c["path"]) for c in (night["file"] or {}).get("copies", [])]
    checks.append(("nightly backup written to both targets, recorded and audited",
                   night["ok"] and len(files) == 2 and events[-1][0] == "backup.done"
                   and oct(cfg.last_file.stat().st_mode)[-3:] == "600",
                   files[0].name if files else "; ".join(night["errors"])))  # fmt: skip
    info = bk.verify(files[0], priv)
    lake_left = info["excluded"].get("lake", {})
    checks.append(("layout 2: hashes from the stream, the file's sha256 equal to its sidecar",
                   info["layout"] == 2 and info["sha256"] == bk.read_sidecar(files[0]) == night["file"]["sha256"],
                   f"sha256 {info['sha256'][:16]}"))  # fmt: skip
    checks.append(("layout 2: older NDJSON and the spill left out and listed; refdata rows left out, packs listed",
                   any("older snapshots" in k for k in lake_left) and any("tmp" in k for k in lake_left)
                   and [p["pack_id"] for p in info["refdata_packs"]] == [packs_before["pack_id"]]
                   if packs_before else False, json.dumps(lake_left)))  # fmt: skip
    st_now = bs.status(cfg, now=when + timedelta(minutes=5))
    sent: list[str] = []
    st_late = bs.status(cfg, now=when + timedelta(hours=37))
    done = bs.alert(cfg, st_late, lambda e, d: events.append((e, d)), sent.append, now=when + timedelta(hours=37))
    secret_words = [str(m[1]) for m in marks_before] + [password]
    checks.append(("status green now; at 37 h red, alerted and audited, with no patient data in the message",
                   st_now["level"] == "ok" and st_late["level"] == "alert" and done == "sent" and len(sent) == 1
                   and events[-1][0] == "backup.alert" and not any(w and w in sent[0] for w in secret_words),
                   "; ".join(st_late["problems"])))  # fmt: skip

    # 3. wipe: drop the run's schemas, move its folders away (a dead box)
    from tb_common.db import split_url

    _, prefix = split_url(url)
    pglocal.drop_prefix(url, prefix)
    gone = base / "wiped"
    shutil.rmtree(gone, ignore_errors=True)
    gone.mkdir()
    for n, p in dirs.items():
        p.rename(gone / n)
    checks.append(("box wiped", not any(p.exists() for p in dirs.values()), ""))

    # 4. restore
    out = bk.restore(
        files[1],
        priv,
        env={**env, "TB_AUDIT_DIR": str(work / "box" / "audit")},
        dirs=dirs,
        refdata_dir=work / "refdata",
    )  # the kept pack (install.sh)
    checks.append(("restore: every table equal to the backup (rows and content hash)", bool(out["ok"]),
                   json.dumps(out["rows"])))  # fmt: skip
    after_files = {n: bk.tree_hashes(p) for n, p in dirs.items()}
    # D-274 (DI-10): the restore appends one backup.restored event to the restored audit log; every other file equal
    grown = {n: sorted(k for k in after_files[n] if before_files.get(n, {}).get(k) != after_files[n][k])
             for n in after_files}  # fmt: skip
    audit_grown = [k for n, ks in grown.items() for k in ks if "audit" in n or "audit" in k]
    checks.append(("restore: every file the layout takes equal, but the audit log the restore appended to",
                   all(not ks or all(("audit" in n or "audit" in k) for k in ks) for n, ks in grown.items())
                   and set().union(*[set(v) for v in before_files.values()]) <= set().union(
                       *[set(v) for v in after_files.values()]),
                   f"{sum(len(v) for v in after_files.values())} files; audit grew in {audit_grown}"))  # fmt: skip
    audit_at = Path(out["audit"]) if Path(out["audit"]).is_dir() else None
    restored_events = sum(f.read_text(errors="replace").count('"backup.restored"')
                          for f in (audit_at.rglob("*") if audit_at else []) if f.is_file())  # fmt: skip
    checks.append(("restore: audited (one backup.restored event in the restored audit log)", restored_events == 1,
                   out["audit"]))  # fmt: skip
    audit_dirs = [p for p in (work / "box" / "audit", work / "lake" / "audit") if p.exists()]
    ok_chain = all(verify(p).ok for p in audit_dirs) if audit_dirs else False
    checks.append(
        ("restore: audit hash chain verifies", ok_chain, ", ".join(str(p.relative_to(base)) for p in audit_dirs))
    )
    checks.append(("restore: the administrator signs in with the same password", _admin_signs_in(work, password), ""))
    checks.append(("restore: the investigator's marks read back the same", _marks(work) == marks_before,
                   f"{len(marks_before)} marks"))  # fmt: skip
    life_after = _lifecycle()
    checks.append(("restore: participants, their steps and the visit schedule read back the same (D-134)",
                   all(life_before.values()) and life_after == life_before,
                   ", ".join(f"{len(v)} {k}" for k, v in life_before.items())))  # fmt: skip
    site_after = _sitesetup()
    charts_after = sorted(str(p.relative_to(work)) for p in (work / "box").rglob("sitesetup/*/inputs/*"))
    checks.append(("restore: the site set-up reads back the same, chart files included (D-135)",
                   all(site_before.values()) and site_after == site_before and charts_before == charts_after
                   and len(charts_before) >= 2,
                   ", ".join(f"{len(v)} {k}" for k, v in site_before.items())
                   + f", {len(charts_before)} files"))  # fmt: skip
    terms_after = _terminology()
    checks.append(("restore: the licensed code lists read back the same, with version and source (D-137)",
                   len(terms_before["releases"]) >= 3 and terms_after == terms_before,
                   f"{len(terms_before['releases'])} releases, {len(terms_before['codes'])} codes"))  # fmt: skip
    omop_after = _omop(work, load=False)
    checks.append(("restore: the OMOP store reads back the same: rows, provenance, conflicts, the year partitions "
                   "(T-106) and the lake it exports (D-151)",
                   omop_before["rows"]["person"] > 0 and omop_after == omop_before,
                   ", ".join(f"{v} {k}" for k, v in omop_before["rows"].items())))  # fmt: skip
    with rd.RefStore() as st:
        packs_after = st.status()
    checks.append(("restore: the reference pack, left out of the backup, is loaded again from the kept pack file and "
                   "every reference row reads back the same",
                   out["refdata"]["missing"] == [] and bool(out["refdata"]["reloaded"])
                   and _same_pack(packs_after, packs_before) and _refdata_rows() == refrows_before,
                   ", ".join(out["refdata"]["reloaded"])))  # fmt: skip

    checks.append(_extensions_check(ext_before, _extensions(), require_extensions))
    checks.append(_extensions_roundtrip(url, require_extensions))
    checks.append(roles_after_restore(base / "roles-cluster"))
    from tools import role_paths  # D-720: and each service's real write paths, as its own role

    checks.append(role_paths.check(base / "paths-cluster"))
    checks.append(_vec_check(vec_before, _vec(fill=False), require_extensions))

    # 5. a backup in the previous format restores
    rows_now = bk.row_counts(bk.db_sources(env)[0])
    legacy = write_legacy(base / "legacy", pub, env, dirs, "gzip", datetime.now(UTC))
    # D-274 (CR-056): this restore goes over a box that holds data, so the box is kept first as an encrypted copy
    old_out = bk.restore(legacy, priv, env=env, dirs=dirs, public_key=pub, keep_to=base / "kept")
    checks.append(("restore: a backup in the previous format (layout 1, gzip) restores the same rows",
                   old_out["ok"] and old_out["layout"] == 1 and bk.row_counts(bk.db_sources(env)[0]) == rows_now,
                   legacy.name))  # fmt: skip
    kept = Path(old_out["kept_copy"]) if old_out.get("kept_copy") else None
    checks.append(("restore over a box with data: the box is kept first as an encrypted backup that verifies",
                   kept is not None and bk.verify(kept, priv)["ok"], str(kept)))  # fmt: skip

    # 6. Postgres settings and PITR
    pg = compose_pg_settings()
    checks.append(("compose db: wal_compression=zstd, default_toast_compression=lz4, WAL archived by pgBackRest zst",
                   pg["wal_compression"] == "zstd" and pg["default_toast_compression"] == "lz4"
                   and "pgbackrest" in pg["archive_command"] and pg["pgbackrest"].get("compress-type") == "zst"
                   and pg["pgbackrest"].get("repo1-cipher-type") == "aes-256-cbc",
                   ", ".join(f"{k}={v}" for k, v in pg.items() if k != "pgbackrest")))  # fmt: skip
    # in the system temp folder: the cluster runs as the postgres user, who may not reach into the drill's folder
    ok_pitr, detail = pitr_drill(Path(tempfile.mkdtemp(prefix="tb-pitr-")))
    checks.append(("PITR: WAL archived (zstd), base backup, recovered to a time between two commits", ok_pitr, detail))
    return {"ok": all(c[1] for c in checks), "checks": checks, "seconds": round(time.perf_counter() - t0, 1)}


def _extensions() -> dict[str, str | None]:
    """The ``db`` image's extensions (D-204) in the trial database: ``{name: version or None}``."""
    from tb_common.db import Database, extensions

    with Database.connect(os.environ["TB_DB_URL"], "site") as db:
        return extensions(db)


def _available(url: str) -> bool:
    """The server offers both of the image's extensions (the box's db image does; the local cluster does not)."""
    from tb_common.db import IMAGE_EXTENSIONS, Database

    with Database.connect(url, "site") as db:
        n = db.fetchval("SELECT count(*) FROM pg_available_extensions WHERE name = ANY(?)", (list(IMAGE_EXTENSIONS),))
        return int(n) == len(IMAGE_EXTENSIONS)


def _extensions_check(
    before: dict[str, str | None], after: dict[str, str | None], require: bool
) -> tuple[str, bool, str]:
    """On a server that offers them (or with ``require``), both extensions exist before the backup and after the
    restore, at the same version."""
    name = "restore: the database extensions exist, same versions (D-204)"
    url = os.environ["TB_DB_URL"]
    wanted = list(before) if require or _available(url) else []
    if not wanted:
        return (name, True, "not offered by this server (no db image); --require-extensions makes this a failure")
    ok = all(after.get(n) and after.get(n) == before.get(n) for n in wanted)
    return (name, ok, ", ".join(f"{n} {before.get(n) or 'missing'} -> {after.get(n) or 'missing'}" for n in wanted))


def _extensions_roundtrip(url: str, require: bool) -> tuple[str, bool, str]:
    """A scratch database with both extensions and a table using both, dumped and restored over itself with the
    backup's own commands as the drill's role (the restore drops and re-creates the extensions: D-204)."""
    import secrets as _secrets
    from urllib.parse import urlsplit, urlunsplit

    import psycopg
    from tb_common.db import Database, extensions, split_url

    from tools.trialbox import backup as bk

    name = "restore: a database with vector and pgroonga restores over itself as the box's role (D-204)"
    if not _available(url):
        ok = not require
        return (name, ok, "not offered by this server (no db image); --require-extensions makes this a failure")
    dsn, _ = split_url(url)
    scratch = f"tbdrill_ext_{_secrets.token_hex(4)}"
    parts = urlsplit(dsn)
    sdsn = urlunsplit((parts.scheme, parts.netloc, f"/{scratch}", parts.query, parts.fragment))
    with psycopg.connect(dsn, autocommit=True) as con:
        con.execute(f'CREATE DATABASE "{scratch}"')
    try:
        with Database.connect(sdsn, "drill") as db:
            db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            db.execute("CREATE EXTENSION IF NOT EXISTS pgroonga WITH SCHEMA public")
            db.migrate(["CREATE TABLE doc (id INT PRIMARY KEY, body TEXT, emb public.vector(3)); "
                        "CREATE INDEX doc_body ON doc USING pgroonga (body)"])  # fmt: skip
            db.execute("INSERT INTO doc VALUES (1, '肺がん', '[1,0,0]')")
            before = extensions(db)
        src = bk.DbSource("trialbox_wf", sdsn, ())
        dump = Path(tempfile.gettempdir()) / f"{scratch}.dump"  # TMPDIR, under TB_TEST_ROOT from make
        try:
            bk.dump(src, dump, os.environ)
            bk.restore_db(src, dump, os.environ)
        finally:
            dump.unlink(missing_ok=True)
        with Database.connect(sdsn, "drill") as db:
            after = extensions(db)
            hit = db.fetchall("SELECT id FROM doc WHERE body OPERATOR(public.&@~) 'がん'")
        ok = after == before and all(after.values()) and hit == [(1,)]
        return (name, ok, ", ".join(f"{n} {v}" for n, v in after.items()))
    except Exception as e:  # the restore refused (e.g. "must be owner of extension"): the check fails, with why
        return (name, False, f"{type(e).__name__}: {str(e)[-300:]}")
    finally:
        with psycopg.connect(dsn, autocommit=True) as con:
            con.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')


ROLES_SCRIPT = ROOT / "deploy" / "docker" / "db-init" / "30-service-roles.sh"


def service_access(script: Path = ROLES_SCRIPT) -> dict[str, list[str]]:
    """The roles script's own list: service role -> the store schemas it reaches (D-378)."""
    text = script.read_text(encoding="utf-8")
    block = text.split("-- BEGIN SERVICE SCHEMAS (D-378)", 1)[1].split("-- END SERVICE SCHEMAS", 1)[0]
    data: dict[str, list[str]] = json.loads(block.split(":= '", 1)[1].rsplit("';", 1)[0])
    return data


def owned_schemas(script: Path = ROLES_SCRIPT) -> list[str]:
    """The roles script's list of schemas with an owner, a writer and a reader role (D-486); empty before it."""
    text = script.read_text(encoding="utf-8")
    if "-- BEGIN OWNED SCHEMAS (D-486)" not in text:
        return []
    block = text.split("-- BEGIN OWNED SCHEMAS (D-486)", 1)[1].split("-- END OWNED SCHEMAS", 1)[0]
    return re.findall(r"'(\w+)'", block.split("ARRAY[", 1)[1])


def roles_after_restore(root: Path, script: Path = ROLES_SCRIPT) -> tuple[str, bool, str]:
    """D-573: on a throwaway cluster of its own, with the real roles script: every store gets a table and a
    function, the trial database is dumped and restored as the box does it, the restore's own step puts the roles
    back, and then every service role opens each store on its list as the store's group (alters the table,
    replaces the function) and reads no store off its list. D-486: in a schema with an owner role the service is a
    writer: it writes a row, and can neither alter the table nor replace the function."""
    import psycopg
    from psycopg import errors, sql
    from tb_common.db import Database

    from tools import pglocal
    from tools.trialbox import backup as bk

    name = "restore: every service opens its stores as its own role afterwards (D-573)"
    access = service_access(script)
    owned = owned_schemas(script)
    schemas = sorted({s for v in access.values() for s in v})
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o755)
    try:
        url = pglocal.ensure(root)
    except Exception as e:
        return (name, False, f"no throwaway cluster: {type(e).__name__}: {str(e)[-200:]}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(
        PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}",
        PGHOST=str((root / "run").resolve()),
        POSTGRES_USER="postgres",
        TB_WF_DB=pglocal.DB,
        TB_DB_ROLES_CMD=f"sh {shlex.quote(str(script))}",
    )
    try:
        # this round is about roles. Where the server has pgvector, the throwaway cluster's database holds the
        # extension, made by the superuser (pglocal.ensure), and the restore runs as `trialbox`, which is not one
        # here: it could not put the extension back ("must be superuser"). Extensions have their own check (D-204).
        with psycopg.connect(
            url.replace("postgresql://trialbox@", "postgresql://postgres@", 1), autocommit=True
        ) as con:
            con.execute("DROP EXTENSION IF EXISTS vector CASCADE")
        bk.reapply_service_roles(env)  # the box before the restore: the roles are there, as install.sh leaves them
        for schema in schemas:
            with Database.connect(url, schema) as db:  # as the store's group, as a migration makes them
                db.execute("CREATE TABLE drill_probe (k INT)")
                db.execute("INSERT INTO drill_probe VALUES (1)")
                db.execute("CREATE FUNCTION drill_fn() RETURNS INT LANGUAGE sql AS 'SELECT 1'")
        src = bk.DbSource("trialbox_wf", url, ())
        dump = root / "wf.dump"
        bk.dump(src, dump, env)
        bk.restore_db(src, dump, env)
        with psycopg.connect(url, autocommit=True) as con:
            owners = {r[0] for r in con.execute(
                "SELECT pg_get_userbyid(c.relowner) FROM pg_class c WHERE c.relname = 'drill_probe'")}  # fmt: skip
        if owners != {"trialbox"}:
            return (
                name,
                False,
                f"the restored tables are owned by {sorted(owners)}, not trialbox: the premise is gone",
            )
        state = bk.reapply_service_roles(env)["state"]
        # D-486: in a schema with an owner role the service is a writer and can replace no function whoever owns
        # it, so the round below cannot tell: ask who owns what the restore put back
        with psycopg.connect(url, autocommit=True) as con:
            for schema in owned:
                for what, query in (
                    ("function", "SELECT pg_get_userbyid(p.proowner) FROM pg_proc p WHERE p.proname = 'drill_fn' "
                                 "AND p.pronamespace = %s::regnamespace"),
                    ("table", "SELECT pg_get_userbyid(c.relowner) FROM pg_class c WHERE c.relname = 'drill_probe' "
                              "AND c.relnamespace = %s::regnamespace"),
                ):  # fmt: skip
                    got = {r[0] for r in con.execute(query, (schema,))}
                    if got != {f"tbo_{schema}"}:
                        return (name, False, f"the restored {what} is still trialbox's in {schema}: owned by "
                                             f"{sorted(got)}, not tbo_{schema}")  # fmt: skip
        opened = 0
        for role, own in sorted(access.items()):
            dsn = url.replace("postgresql://trialbox@", f"postgresql://{role}@", 1)
            with psycopg.connect(dsn, autocommit=True) as con:
                for schema in schemas:
                    if schema in own and schema in owned:  # D-486: a writer, never the owner
                        try:
                            con.execute(sql.SQL("INSERT INTO {}.drill_probe VALUES (2)").format(sql.Identifier(schema)))
                        except errors.InsufficientPrivilege as e:
                            return (name, False, f"{role} cannot write its table in {schema}: {str(e).strip()[:160]}")
                        for ddl in (f'ALTER TABLE "{schema}".drill_probe ADD COLUMN IF NOT EXISTS seen INT',
                                    f'CREATE OR REPLACE FUNCTION "{schema}".drill_fn() RETURNS INT LANGUAGE sql '
                                    "AS 'SELECT 2'"):  # fmt: skip
                            try:
                                con.execute(ddl)
                            except errors.InsufficientPrivilege:
                                continue
                            return (name, False, f"{role} changed what the owner of {schema} made: {ddl[:40]}")
                        opened += 1
                    elif schema in own:
                        try:
                            con.execute(f'SET ROLE "tbs_{schema}"')
                            con.execute(f'ALTER TABLE "{schema}".drill_probe ADD COLUMN IF NOT EXISTS seen INT')
                            con.execute(f'CREATE OR REPLACE FUNCTION "{schema}".drill_fn() RETURNS INT LANGUAGE sql '
                                        "AS 'SELECT 2'")  # fmt: skip
                            con.execute("RESET ROLE")
                        except errors.InsufficientPrivilege as e:
                            what = "function" if "function" in str(e) else "table"
                            return (name, False, f"{role} cannot change its {what} in {schema}: {str(e).strip()[:160]}")
                        opened += 1
                    else:
                        try:
                            con.execute(sql.SQL("SELECT count(*) FROM {}.drill_probe").format(sql.Identifier(schema)))
                        except errors.InsufficientPrivilege:
                            continue
                        return (name, False, f"{role} reads {schema}, which is not on its list")
        return (name, state == "applied",
                f"{len(access)} service roles, {opened} stores opened as their groups: a table altered and a function "
                "replaced in each; no store off a list is read")  # fmt: skip
    except Exception as e:
        return (name, False, f"{type(e).__name__}: {str(e)[-300:]}")
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


VEC_NOTES = (  # synthetic notes for the vector store's check (D-439)
    ("drill-p1", "drill-d1", "Gout flare. Allopurinol continued. Uric acid 9.2."),
    ("drill-p2", "drill-d2", "痛風發作，尿酸9.2。持續服藥。"),
    ("drill-p2", "drill-d3", "Gout flare. Allopurinol continued. Uric acid 9.2."),
)


def _vec(fill: bool) -> dict[str, Any] | None:
    """The vector store of the run's schemas (``vec``, D-439): its chunks, vectors, HNSW index and one search; with
    ``fill`` the drill's synthetic notes are indexed first. None when the database has no ``vector`` extension."""
    from embed_service.embedder import HashEmbedder
    from tb_common.db import Database, extensions
    from vec.index import Note, index_notes
    from vec.store import VecStore, index_name

    url = os.environ["TB_DB_URL"]
    with Database.connect(url, "site") as db:
        if not extensions(db, ("vector",))["vector"]:
            return None
    e = HashEmbedder()
    with VecStore(url, model=e.model, dim=e.dim) as st:
        if fill:
            index_notes(st, [Note(p, d, t, "2026-01-01", "progress") for p, d, t in VEC_NOTES], e)
        q = e.embed([VEC_NOTES[0][2]])[0]
        return {
            "chunks": st.db.fetchall("SELECT pid, did, chunk_no, start_char, end_char, text, sha FROM note_chunk "
                                     "ORDER BY did, chunk_no"),
            "vectors": st.db.fetchall("SELECT sha, model, dim, emb::text FROM embedding ORDER BY sha, model"),
            "index": index_name(e.model) in st.indexes(),
            "search": [(h["did"], h["chunk_no"]) for h in st.search(q, e.model, k=3)],
        }  # fmt: skip


def _vec_check(before: dict[str, Any] | None, after: dict[str, Any] | None, require: bool) -> tuple[str, bool, str]:
    name = "restore: the vector store reads back the same: chunks, vectors, the HNSW index, a search (D-439)"
    if before is None:
        return (name, not require, "no vector extension in this database (no db image); --require-extensions fails")
    ok = bool(before["chunks"]) and before["index"] and after == before
    return (name, ok, f"{len(before['chunks'])} chunks, {len(before['vectors'])} vectors")


def _refdata_rows() -> dict[str, list[tuple[Any, ...]]]:
    """Every reference row (the pack's and the hospital's own) and the sources, read through the store's database."""
    from tb_common.refdata import RefStore

    with RefStore() as st:
        out = {t: st.db.fetchall(f"SELECT * FROM {t} ORDER BY 1, 2") for t in ("ctgov_study", "trial", "term")}
        out["source"] = st.db.fetchall("SELECT source_id, pack_id, distribution, records FROM source ORDER BY 1")
        return out


def _same_pack(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if not a or not b:
        return False
    keys = ("pack_id", "data_as_of")
    return all(a.get(k) == b.get(k) for k in keys)


# ------------------------------------------------------------------------------------------------ previous format
def write_legacy(target: Path, public_key: Path, env: dict[str, str], dirs: dict[str, Path], compression: str,
                 now: datetime) -> Path:  # fmt: skip
    """Write a backup exactly as TrialBox did before D-187 (layout 1): a full dump with pg_dump's own compression,
    the files hashed by reading them before they go into the tar, no ``layout``/``sizes``/``excluded`` in the
    manifest, the header without ``layout`` (and without ``compression`` for gzip, as before D-149), no sidecar.
    Kept here so the drill and the tests restore a real old-format file."""
    from tools.trialbox import backup as bk

    target.mkdir(parents=True, exist_ok=True)
    site = env.get("TB_SITE_ID") or "box"
    name = f"trialbox-{bk._safe(site)}-{now.strftime('%Y%m%dT%H%M%SZ')}{bk.SUFFIX}"
    srcs = bk.db_sources(env)
    manifest: dict[str, Any] = {"created_at": now.isoformat(timespec="seconds"), "site": site, "databases": {},
                                "dirs": {}, "files": {}}  # fmt: skip
    meta: dict[str, Any] = {"site": site, "created_at": manifest["created_at"]}
    if compression != "gzip":
        meta["compression"] = compression
        manifest["compression"] = f"{compression}-{bk.ZSTD_LEVEL}"
    with tempfile.TemporaryDirectory(prefix="tb-legacy-") as tmp:
        work = Path(tmp)
        for src in srcs:
            args, _ = bk._libpq(src.dsn)
            cmd = [*bk._cmd(env, "TB_PG_DUMP_CMD", "pg_dump"), "--format=custom", "--no-owner", "--no-privileges",
                   *args, *[x for s in src.schemas for x in ("--schema", s)]]  # fmt: skip
            import subprocess

            with (work / f"{src.name}.dump").open("wb") as fh:
                subprocess.run(cmd, stdout=fh, check=True)
            manifest["databases"][src.name] = {"schemas": list(src.schemas), "rows": bk.row_counts(src, scheme="md5")}
        with (target / name).open("wb") as raw:
            enc = bk._Encryptor(raw, bk.load_public(public_key), meta)
            with bk._tar_writer(enc, compression) as tar:
                for src in srcs:
                    f = work / f"{src.name}.dump"
                    manifest["files"][f"db/{src.name}.dump"] = bk._sha_file(f)
                    tar.add(f, arcname=f"db/{src.name}.dump")
                for dname, root in sorted(dirs.items()):
                    hashes_ = bk.tree_hashes(root)
                    manifest["dirs"][dname] = {"path": str(root), "files": len(hashes_)}
                    for rel, sha in hashes_.items():
                        manifest["files"][f"dirs/{dname}/{rel}"] = sha
                        tar.add(root / rel, arcname=f"dirs/{dname}/{rel}", recursive=False)
                data = json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(data)
                info.mtime = int(now.timestamp())
                tar.addfile(info, io.BytesIO(data))
            enc.finish()
    return target / name


# ------------------------------------------------------------------------------------------------ Postgres settings
def compose_pg_settings(deploy: Path = DEPLOY) -> dict[str, Any]:
    """The ``db`` service's ``-c`` settings in ``deploy/docker-compose.yml`` with their defaults filled in, and
    ``deploy/pgbackrest/pgbackrest.conf`` as ``key -> value``."""
    import yaml

    svc = yaml.safe_load((deploy / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["db"]
    cmd = [str(x) for x in svc.get("command") or []]
    out: dict[str, Any] = {}
    for i, x in enumerate(cmd[:-1]):
        if x == "-c":
            k, _, v = cmd[i + 1].partition("=")
            out[k] = re.sub(r"\$\{[A-Z0-9_]+:-([^}]*)\}", r"\1", v)
    conf: dict[str, str] = {}
    for line in (deploy / "pgbackrest" / "pgbackrest.conf").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith(("#", "[")):
            k, _, v = line.partition("=")
            conf[k.strip()] = v.strip()
    out["pgbackrest"] = conf
    return out


def pitr_drill(root: Path) -> tuple[bool, str]:
    """A throwaway cluster with the box's settings: WAL archived, a base backup, three commits, then recovery to a
    time between the second and the third. Plain Postgres archiving (``cp``) stands in for pgBackRest here."""
    from tools import pglocal

    b = pglocal.bindir()
    pre = pglocal._as_postgres_user()
    shutil.rmtree(root, ignore_errors=True)
    data, arch, base_bk, restored = (root / n for n in ("data", "wal-archive", "base", "restored"))
    for d in (root, arch):
        d.mkdir(parents=True, exist_ok=True)
        if pre:
            shutil.chown(d, pre[2])
    # as pglocal.ensure does: a short socket folder when root/run is too long for a Unix socket (a scratch root under
    # TB_TEST_ROOT, D-201), and as root the search bit on a private parent so that the server's owner reaches root
    sock = pglocal._socket_dir(root)
    if pre:
        pglocal._grant_traverse(root, pre[2])
        shutil.chown(sock, pre[2])

    def run(*cmd: str) -> str:
        r = pglocal._run([*pre, *cmd])
        if r.returncode != 0:
            raise RuntimeError(f"{Path(cmd[0]).name}: {r.stderr.strip()[-300:]}")
        return str(r.stdout)

    common = f"-c listen_addresses='' -c unix_socket_directories='{sock}' -c wal_compression=zstd " \
             "-c default_toast_compression=lz4"  # fmt: skip
    psql = [str(b / "psql"), "-h", str(sock), "-U", "postgres", "-d", "postgres", "-tAqc"]
    try:
        run(str(b / "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C",
            "--data-checksums", "--no-instructions")  # fmt: skip
        run(str(b / "pg_ctl"), "-D", str(data), "-l", str(root / "server.log"), "-w", "start", "-o",
            f"{common} -c wal_level=replica -c archive_mode=on -c archive_command='cp %p {arch}/%f'")  # fmt: skip
        try:
            run(*psql, "CREATE TABLE drill (id int PRIMARY KEY, note text)")
            run(*psql, "INSERT INTO drill VALUES (1, repeat('synthetic note ', 4000))")  # TOASTed and compressed
            run(str(b / "pg_basebackup"), "-h", str(sock), "-U", "postgres", "-D", str(base_bk), "--checkpoint=fast")
            run(*psql, "INSERT INTO drill VALUES (2, 'kept')")
            target = run(*psql, "SELECT now()").strip()
            time.sleep(1.2)
            run(*psql, "INSERT INTO drill VALUES (3, 'after the target')")
            wal = run(*psql, "SELECT pg_walfile_name(pg_switch_wal())").strip()
            for _ in range(300):
                if (arch / wal).exists():
                    break
                time.sleep(0.1)
            toast = run(*psql, "SELECT pg_column_compression(note) FROM drill WHERE id = 1").strip()
            walc = run(*psql, "SHOW wal_compression").strip()
        finally:
            pglocal._run([*pre, str(b / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"])
        run("cp", "-a", str(base_bk), str(restored))
        with (restored / "postgresql.auto.conf").open("a", encoding="utf-8") as fh:
            fh.write(f"restore_command = 'cp {arch}/%f %p'\nrecovery_target_time = '{target}'\n"
                     "recovery_target_action = 'promote'\n")  # fmt: skip
        (restored / "recovery.signal").touch()
        run(str(b / "pg_ctl"), "-D", str(restored), "-l", str(root / "restored.log"), "-w", "start", "-o", common)
        try:
            for _ in range(300):
                if run(*psql, "SELECT pg_is_in_recovery()").strip() == "f":
                    break
                time.sleep(0.1)
            ids = run(*psql, "SELECT string_agg(id::text, ',' ORDER BY id) FROM drill").strip()
        finally:
            pglocal._run([*pre, str(b / "pg_ctl"), "-D", str(restored), "-m", "fast", "-w", "stop"])
    except (RuntimeError, OSError) as e:
        return False, str(e)[-300:]
    finally:
        if sock != root / "run":
            shutil.rmtree(sock, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)
    ok = ids == "1,2" and toast == "lz4" and walc == "zstd"
    return ok, f"rows {ids} after recovery to the target time; TOAST {toast}; WAL {walc}"


# ------------------------------------------------------------------------------------------------ read-backs
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


def _lifecycle() -> dict[str, list[tuple[Any, ...]]]:
    """The lifecycle tables of every study, read through the data core (a fresh connection: a fresh process)."""
    from datacore.lifecycle import Lifecycle
    from datacore.store import DataCore

    dc = DataCore()
    try:
        life = Lifecycle(dc)
        studies = sorted({str(r[0]) for r in dc.db.fetchall("SELECT DISTINCT study FROM subject")})
        out: dict[str, list[tuple[Any, ...]]] = {"participants": [], "steps": [], "visits": []}
        for st in studies:
            out["participants"] += [(st, s["record"], s["state"], s["since"]) for s in life.subjects(st)]
            out["steps"] += [(st, s["record"], s["old"], s["new"], s["on_day"], s["who"]) for s in life.steps(st)]
            out["visits"] += [(st, v.name, v.day, v.before, v.after) for v in life.schedule(st)]
        return out
    finally:
        dc.close()


def _sitesetup() -> dict[str, list[tuple[Any, ...]]]:
    """The site set-up of every site space, read through its store (a fresh connection: a fresh process)."""
    from sitesetup.store import SetupStore

    st = SetupStore()
    try:
        out: dict[str, list[tuple[Any, ...]]] = {"inputs": [], "facts": [], "codes": [], "checks": []}
        for ws in st.workspaces():
            out["inputs"] += [(ws, i["kind"], i["sha256"], i["pid"]) for i in st.inputs(ws)]
            out["facts"] += [(ws, f["pid"], f["domain"], f["code"], f["value"], f["status"], f["decided_by"])
                             for f in st.facts(ws)]  # fmt: skip
            out["codes"] += [(ws, c["system"], c["code"], c["mapped_code"], c["mapped_by"]) for c in st.locals(ws)]
            out["checks"] += [(ws, c["key"], c["answer"]) for c in st.checks(ws)]
        return out
    finally:
        st.close()


def _terminology() -> dict[str, list[tuple[Any, ...]]]:
    """The licensed code lists (D-137), read through their store (a fresh connection: a fresh process)."""
    from adapter.licensed import KINDS, TermStore

    st = TermStore()
    try:
        rel = [(r["kind"], r["version"], r["source"], r["sha256"], r["rows"], r["active"]) for r in st.releases()]
        codes = [(k, c, v["target_code"]) for k in KINDS for c, v in sorted(st.concepts(k).items())]
        return {"releases": rel, "codes": codes}
    finally:
        st.close()


def _omop(work: Path, load: bool) -> dict[str, Any]:
    """The OMOP store (D-151) of the run's schemas: loaded from the box's current lake snapshot and site inputs
    (``load``), then its row counts, its open conflicts and a digest of the lake it exports."""
    import hashlib

    from lake.store import Lake
    from omop import schema
    from omop.__main__ import _read
    from omop.export import export_rows
    from omop.load import load_batch
    from omop.partitions import layout

    db = schema.connect()
    try:
        if load:
            lake = Lake(work / "lake")
            snap = str(lake.current())
            load_batch(db, "feed", snap, _read(work / "lake" / "ndjson" / snap))
            load_batch(db, "site", f"site@{snap}", _read(work / "lake" / "site"))
        tables = ("person", "visit_occurrence", "condition_occurrence", "drug_exposure", "measurement", "note",
                  "concept", "tb_record", "tb_record_event", "tb_conflict")  # fmt: skip
        rows = {t: int(db.fetchval(f"SELECT count(*) FROM {t}")) for t in tables}
        blob = json.dumps(export_rows(db), sort_keys=True, default=str).encode()
        seq = int(db.fetchval("SELECT last_value FROM tb_row_seq"))
        with db.transaction() as tx:  # T-106: the year partitions come back with their rows
            parts = layout(tx)
        return {"rows": rows, "export_sha256": hashlib.sha256(blob).hexdigest(), "row_seq": seq, "partitions": parts}
    finally:
        db.close()


def _admin_signs_in(work: Path, password: str) -> bool:
    from console.auth import UserStore

    users = UserStore()
    try:
        return bool(users.authenticate("admin", password))
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import adopt_site_tz

    adopt_site_tz()  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--dir", type=Path, default=Path(os.environ.get("TB_DRILL_DIR") or scratch_root() / "tb-backup-drill")
    )
    ap.add_argument(
        "--require-extensions",
        action="store_true",
        help="fail unless vector and pgroonga exist before and after (a run against the box's db image, D-204)",
    )
    a = ap.parse_args(argv)
    import logging

    was = logging.root.manager.disable  # 9i-1: the level found, given back however this ends
    logging.disable(logging.INFO)
    try:
        if a.dir.exists():
            shutil.rmtree(a.dir)
        a.dir.mkdir(parents=True)
        out = run(a.dir, require_extensions=a.require_extensions)
        for name, ok, detail in out["checks"]:
            print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        if out.get("kept"):
            print(f"the work folder is kept: {out['kept']}")
        print(f"backup drill {'PASSED' if out['ok'] else 'FAILED'} in {out['seconds']} s")
        return 0 if out["ok"] else 1
    finally:
        logging.disable(was)


if __name__ == "__main__":
    sys.exit(main())
