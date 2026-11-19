"""D-1253: the one rebuild a box makes when its lake ids change rule (runbook §5, "Lake ids per patient").

Rule 2 (a patient's record id holds the patient) changed every id of a patient's record once. The night refuses to
add rule-2 ids to anything written under rule 1 (``tb_common.id_rule``), so a box that ran an earlier release is
rebuilt once, from its sources, after the update and with the services stopped:

    python -m tools.id_rule_rebuild --lake /data/lake          # the plan: what is kept, moved, cleared; changes nothing
    python -m tools.id_rule_rebuild --lake /data/lake --yes    # does it; the first night after it is a full night

**Before anything.** It refuses, changing nothing, unless the writers are stopped. It checks this itself and does
not trust the runbook:

- it takes the adapter's run lock, so no night runs during it and none can start;
- no lake build runs;
- no service's database role is connected to the trial database (or to the OMOP database the night probes).

It holds the lake lock for the whole lake part.

**What it never deletes**: what cannot be made again or what a person decided.

- The month-end snapshots that retention keeps are **moved aside** to ``<lake>/id_rule_1/``, where no reader looks.
  They are kept, not read, and pruned there by retention as before.
- Each resolved conflict of the derived store, with the score row it names, is **kept**. It is marked ``id_rule =
  1`` and its row is superseded, so screening never reads it again.
- EDC's trail stays: append-only, D-281.
- The site key, the pid map, the site set-up's facts, the embedding cache and the FHIR ledger stay. The ledger is how
  the next load deletes the old ids from fhir-store.

**What it clears**, in this order. A crash after any step leaves a box that serves nothing of the old rule, and a
second run finishes the work.

1. **Moved aside**: the month-end snapshots (above).
2. **What is served**: ``CURRENT``, the DuckDB and Parquet copies, the job holds. From here no reader serves an old
   id.
3. **The rest of the lake**: the NDJSON snapshots, their re-runs, the back-fill's copy, the scratch and the last
   feed's date.
4. **The stores**:
   - the OMOP store of record (``TB_OMOP_DB_URL`` when set, else the trial database: the store the night probes).
     Its feed records of patients' clinical data go. Persons, site records, vocabulary, conflicts, loads and ruleset
     releases stay.
   - the derived store: scores, inputs, open conflicts and batch runs. The definitions and the resolved conflicts
     (above) stay.
   - the note chunks, the twin's documents and the pool.
   - the data-ops records of what each artefact was built from (``built``, ``built_kept``).
   - in EDC, the open drafts of each rule-1 study that has no trail. The plan lists them by count. Such a study is
     then stamped rule 2.

   Each store is stamped rule 2 in the same transaction.

A rule-1 EDC study with a decided, signed or sent value stays **frozen**. The plan and the rebuild name it, with its
count and its ODM export. No removal is offered.

Published job outputs and the audit chain are not touched. The rebuild writes one audit event of a kind the box
already has, ``lake.rebuild.source`` (``source: id_rule``), with counts only, and the same counts to
``<lake>/id_rule_rebuild.json``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tb_common import id_rule  # noqa: E402

RECORD = "id_rule_rebuild.json"
ASIDE = "id_rule_1"  # <lake>/id_rule_1/{ndjson,db,parquet}/...: rule-1 month-ends kept under retention, never read
#                      (adapter.pipeline.ID_RULE_ASIDE: the nightly prune lets each go when retention does)
#: step 2: what is served; step 3: the rest of the lake made from the snapshots (``tb_common.erasure``'s lake entries)
SERVED = ("CURRENT", "CURRENT.tmp", "db", "parquet", "holds")
REST = ("ndjson", "ndjson-rerun", "backfill", "tmp", "FEED")
LAKE_ENTRIES = SERVED + REST
STEPS = ("aside", "served", "lake", "stores")
#: per store: what is cleared (each a statement of the store's own schema)
CLEARS: dict[str, tuple[str, ...]] = {
    "vec": ("DELETE FROM note_chunk",),
    "profile": ("DELETE FROM tb_patient_profile",),
    "orch": ("DELETE FROM pool",),
}
COUNTS: dict[str, tuple[str, ...]] = {
    "derived": ("score_row", "input_link", "conflict", "batch_run"),
    "vec": ("note_chunk",),
    "profile": ("tb_patient_profile",),
    "orch": ("pool",),
}
OMOP_FEED = "source_kind = 'feed' AND resource_type <> 'Patient'"
#: EDC: a draft's trail is every append-only table with a ``draft_id`` (read from the schema, so a trail table added
#: later is never missed) and the draft's own decided, signed or sent marks
EDC_TRAIL_TABLES = (
    "SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema = current_schema() AND "
    "column_name = 'draft_id' AND table_name <> 'draft' ORDER BY table_name"
)
#: the derived conflicts a person resolved, and every conflict they were carried from: kept
KEPT_CONFLICTS = (
    "WITH RECURSIVE k(id) AS (SELECT id FROM conflict WHERE resolution IS NOT NULL UNION SELECT c.carried_from FROM "
    "conflict c JOIN k ON c.id = k.id WHERE c.carried_from IS NOT NULL) SELECT id FROM k"
)


class Refused(RuntimeError):
    """The rebuild does not start: nothing was changed."""


def _schemas(url: str) -> set[str]:
    import psycopg
    from tb_common.db import split_url

    dsn, _ = split_url(url)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as con:
        return {str(r[0]) for r in con.execute("SELECT nspname FROM pg_namespace").fetchall()}


def _has(db: Any, table: str) -> bool:
    return db.fetchval("SELECT to_regclass(?)", (f'"{db.schema}".{table}',)) is not None


def _columns(db: Any, table: str) -> set[str]:
    return {
        str(r[0])
        for r in db.fetchall(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND "
            "table_name = ?",
            (table,),
        )
    }


def _snapshots(lake: Path) -> list[str]:
    nd = lake / "ndjson"
    return sorted(p.name for p in nd.iterdir() if p.is_dir() and not p.name.startswith(".")) if nd.is_dir() else []


def month_ends(lake: Path, today: date) -> list[str]:
    """The snapshots retention keeps as month-ends (not the nightly ones): moved aside, never deleted."""
    from tb_common.retention import snapshots_to_keep

    snaps = _snapshots(lake)
    months = int(os.environ.get("TB_KEEP_MONTH_END_MONTHS") or 36)
    # with what an earlier run (cut short) moved already: a month keeps its own month-end, never a second one
    return sorted(snapshots_to_keep(set(snaps) | set(_aside(lake)), today, 0, months) & set(snaps))


def _omop_url(url: str | None) -> str | None:
    return os.environ.get("TB_OMOP_DB_URL") or url


def _edc_clauses(db: Any) -> str:
    """The trail of ``draft d``, as SQL."""
    trail = " OR ".join(
        f"EXISTS (SELECT 1 FROM {t} x WHERE x.draft_id = d.id)" for (t,) in db.fetchall(EDC_TRAIL_TABLES)
    )
    return "(d.fate IN ('confirmed', 'edited') OR d.signature_id IS NOT NULL OR d.sent_at IS NOT NULL" + (
        f" OR {trail})" if trail else ")"
    )


def _edc_old(db: Any) -> str:
    """A draft of a study not of the current rule (a study with no rule row has no draft: the migration stamped every
    study that had one)."""
    if not _has(db, "tb_id_rule_study"):
        return "TRUE"
    return f"d.study IN (SELECT study FROM tb_id_rule_study WHERE rule < {id_rule.RULE})"


def _edc_plan(db: Any) -> dict[str, Any]:
    trail, old = _edc_clauses(db), _edc_old(db)
    frozen = db.fetchall(f"SELECT d.study, count(*) FROM draft d WHERE {trail} AND {old} GROUP BY d.study "
                         "ORDER BY d.study")  # fmt: skip
    frozen_studies = {str(s): int(n) for s, n in frozen}
    waiting = db.fetchall(f"SELECT d.study, count(*) FROM draft d WHERE NOT {trail} AND {old} GROUP BY d.study "
                          "ORDER BY d.study")  # fmt: skip
    return {
        "frozen_studies": frozen_studies,
        "open_drafts": {str(s): int(n) for s, n in waiting if str(s) not in frozen_studies},
        "open_drafts_of_frozen_studies_kept": {str(s): int(n) for s, n in waiting if str(s) in frozen_studies},
        "export": "GET /api/v1/studies/<study>/edc/export/odm",
    }


def plan(lake: Path, url: str | None, today: date | None = None) -> dict[str, Any]:
    """What the rebuild keeps, moves aside and clears, with counts; each store's rule state. Changes nothing."""
    from omop.schema import schema_for
    from tb_common.db import Database, split_url

    snaps = _snapshots(lake)
    aside = month_ends(lake, today or date.today())
    out: dict[str, Any] = {
        "lake": {
            "dir": str(lake),
            "snapshots": len(snaps),
            "old_snapshots": id_rule.old_snapshots(lake / "ndjson"),
            "moved_aside": aside,
            "cleared": [e for e in LAKE_ENTRIES if (lake / e).exists()],
            "kept": ["site_key.json", "pid map", "site", "embed_cache.duckdb", "fhir_ledger", ASIDE],
        }
    }
    if not url:
        out["database"] = "no TB_DB_URL: the stores of the trial database were not read"
        return out
    prefix = split_url(url)[1]
    present = _schemas(url)
    omop = schema_for(lake)
    omop_url = _omop_url(url) or url
    omop_present = _schemas(omop_url) if omop_url != url else present
    for store in id_rule.STORES:
        name = omop if store is id_rule.OMOP else store.schema
        where = omop_url if store is id_rule.OMOP else url
        full = (split_url(omop_url)[1] if store is id_rule.OMOP else prefix) + name
        if full not in (omop_present if store is id_rule.OMOP else present):
            out[store.name] = {"schema": full, "present": False}
            continue
        row: dict[str, Any] = {"schema": full, "present": True, "rule": id_rule.probe(where, store, name)}
        with Database.connect(where, name) as db:
            if store is id_rule.OMOP and _has(db, "tb_record"):
                row["cleared"] = {"feed_records": int(db.fetchval(f"SELECT count(*) FROM tb_record WHERE {OMOP_FEED}"))}
            else:
                row["cleared"] = {t: int(db.fetchval(f"SELECT count(*) FROM {t}")) for t in COUNTS.get(name, ())
                                  if _has(db, t)}  # fmt: skip
                if name == "derived" and _has(db, "conflict") and "resolution" in _columns(db, "conflict"):
                    kept = len(db.fetchall(KEPT_CONFLICTS))
                    row["kept"] = {"resolved_conflicts": kept}
                    row["cleared"]["conflict"] = row["cleared"].get("conflict", 0) - kept
        out[store.name] = row
    if prefix + "dataops" in present:
        with Database.connect(url, "dataops") as db:
            out["dataops"] = {"cleared": {t: int(db.fetchval(f"SELECT count(*) FROM {t}"))
                                          for t in ("built", "built_kept") if _has(db, t)}}  # fmt: skip
    if prefix + "edc" in present:
        with Database.connect(url, "edc") as db:
            if _has(db, "draft"):
                out["edc"] = _edc_plan(db)
    return out


# ------------------------------------------------------------------------------------------------ the checks
def writers(lake: Path, url: str | None) -> list[str]:
    """What still writes (empty: the rebuild may start): a lake build, a service connected to the database. The
    night itself is kept out by the run lock the rebuild holds (:func:`rebuild`)."""
    from lake.store import build_running

    found: list[str] = []
    names = set(_snapshots(lake)) | {p.stem for p in (lake / "db").glob("*.duckdb")}
    found += [f"a lake build of {s} runs" for s in sorted(names) if build_running(lake, s)]
    for where in {u for u in (url, _omop_url(url)) if u}:
        import psycopg
        from tb_common.db import split_url

        dsn, _ = split_url(where)
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as con:
            others = con.execute(
                "SELECT usename, count(*) FROM pg_stat_activity WHERE datname = current_database() AND "
                "pid <> pg_backend_pid() AND backend_type = 'client backend' AND usename <> current_user "
                "GROUP BY usename ORDER BY usename"
            ).fetchall()
        found += [f"{n} connection(s) of the database role {u}" for u, n in others]
    return found


@contextlib.contextmanager
def _stopped(lake: Path, url: str | None) -> Iterator[None]:
    """The run lock (no night starts) and the lake lock, held while the writers are seen stopped."""
    from adapter.runs import RunLock, RunLockHeld
    from lake.store import lake_lock

    try:
        run = RunLock(lake)
    except RunLockHeld as exc:
        raise Refused(f"a night runs ({exc}): stop the services first (runbook step 0)") from exc
    try:
        busy = writers(lake, url)
        if busy:
            raise Refused(f"the services still write ({'; '.join(busy)}): stop them first (runbook step 0)")
        with lake_lock(lake):
            yield
    finally:
        run.release()


# ------------------------------------------------------------------------------------------------ the steps
def _remove(lake: Path, entries: tuple[str, ...]) -> list[str]:
    gone = []
    for entry in entries:
        path = lake / entry
        if path.is_dir():
            shutil.rmtree(path)
            gone.append(entry)
        elif path.exists():
            path.unlink()
            gone.append(entry)
    return gone


def _move_aside(lake: Path, snaps: list[str]) -> list[str]:
    """Each month-end's NDJSON, DuckDB and Parquet to ``<lake>/id_rule_1/``, as they are (they say no rule: 1).
    Again after a crash: what is already there stays, what is left is moved."""
    moved = []
    to = lake / ASIDE
    for s in snaps:
        parts = [(lake / "ndjson" / s, to / "ndjson" / s), (lake / "parquet" / f"snapshot={s}",
                 to / "parquet" / f"snapshot={s}")]  # fmt: skip
        parts += [(f, to / "db" / f.name) for f in sorted((lake / "db").glob(f"{s}.duckdb*"))]
        for src, dst in parts:
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dst)
        moved.append(s)
    if moved:
        (to / "README.json").write_text(json.dumps({
            "rule": 1, "why": "D-1253: month-end snapshots of the earlier id rule, kept under retention, never read",
            "snapshots": sorted(set(moved) | set(_aside(lake)))}, indent=1) + "\n", encoding="utf-8")  # fmt: skip
    return moved


def _aside(lake: Path) -> list[str]:
    nd = lake / ASIDE / "ndjson"
    return sorted(p.name for p in nd.iterdir() if p.is_dir()) if nd.is_dir() else []


def _stamp(tx: Any) -> None:
    tx.execute(id_rule.DDL)
    tx.execute("INSERT INTO tb_id_rule (rule) VALUES (?) ON CONFLICT (rule) DO NOTHING", (id_rule.RULE,))


def _clear_omop(db: Any) -> dict[str, int]:
    from omop.load import ID_COL

    counts: dict[str, int] = {}
    with db.transaction() as tx:
        tables = [str(r[0]) for r in tx.fetchall(
            f"SELECT DISTINCT cdm_table FROM tb_record WHERE {OMOP_FEED} AND cdm_table IS NOT NULL")]  # fmt: skip
        for t in sorted(tables):
            col = ID_COL.get(t)
            if col is None:
                raise Refused(f"the OMOP store holds feed records of table {t}, which this rebuild does not know")
            counts[t] = tx.execute(
                f"DELETE FROM {t} WHERE {col} IN (SELECT record_id FROM tb_record WHERE {OMOP_FEED} AND cdm_table = ?)",
                (t,),
            )  # fmt: skip
        counts["tb_record_event"] = tx.execute(
            f"DELETE FROM tb_record_event WHERE record_key IN (SELECT record_key FROM tb_record WHERE {OMOP_FEED})"
        )
        counts["tb_record"] = tx.execute(f"DELETE FROM tb_record WHERE {OMOP_FEED}")
        _stamp(tx)
    return counts


def _clear_derived(db: Any) -> dict[str, Any]:
    """Scores, inputs, open conflicts and batch runs go; a resolved conflict (a person's decision) and the score row
    it names stay, marked rule 1 and superseded (never read again)."""
    counts: dict[str, Any] = {}

    def has(t: str) -> bool:
        return tx.fetchval("SELECT to_regclass(?)", (f'"{db.schema}".{t}',)) is not None

    with db.transaction() as tx:
        kept: list[int] = []
        if has("conflict"):
            cols = _columns(tx, "conflict")
            if "resolution" in cols:
                kept = [int(r[0]) for r in tx.fetchall(KEPT_CONFLICTS)]
                if kept and "id_rule" not in cols:
                    raise Refused("the derived store is not migrated to this release: start the services once after "
                                  "the update, stop them, then run the rebuild")  # fmt: skip
        if kept:
            rows = [int(r[0]) for r in tx.fetchall("SELECT DISTINCT row_id FROM conflict WHERE id = ANY(?)", (kept,))]
            tx.execute("UPDATE conflict SET id_rule = 1 WHERE id = ANY(?)", (kept,))
            tx.execute("UPDATE score_row SET id_rule = 1, superseded_at = COALESCE(superseded_at, ?) WHERE id = ANY(?)",
                       (datetime.now(UTC).isoformat(timespec="seconds"), rows))  # fmt: skip
            counts["kept"] = {"resolved_conflicts": len(kept), "their_score_rows": len(rows)}
            counts["conflict"] = tx.execute("DELETE FROM conflict WHERE NOT (id = ANY(?))", (kept,))
            counts["input_link"] = tx.execute("DELETE FROM input_link WHERE NOT (row_id = ANY(?))", (rows,))
            counts["score_row"] = tx.execute("DELETE FROM score_row WHERE NOT (id = ANY(?))", (rows,))
        else:
            for t in ("conflict", "input_link", "score_row"):
                if has(t):
                    counts[t] = tx.execute(f"DELETE FROM {t}")
        if has("batch_run"):
            counts["batch_run"] = tx.execute("DELETE FROM batch_run")
        _stamp(tx)
    return counts


def _stores(lake: Path, url: str, before: dict[str, Any]) -> dict[str, Any]:
    from omop.schema import schema_for
    from tb_common.db import Database, split_url

    done: dict[str, Any] = {}
    prefix = split_url(url)[1]
    present = _schemas(url)
    omop = schema_for(lake)
    omop_url = _omop_url(url) or url
    if split_url(omop_url)[1] + omop in (_schemas(omop_url) if omop_url != url else present):
        with Database.connect(omop_url, omop) as db:
            if _has(db, "tb_record"):
                done["omop"] = _clear_omop(db)
    if prefix + "derived" in present:
        with Database.connect(url, "derived") as db:
            done["derived"] = _clear_derived(db)
    for name, statements in CLEARS.items():
        if prefix + name not in present:
            continue
        with Database.connect(url, name) as db, db.transaction() as tx:
            done[name] = {
                st.split()[-1]: tx.execute(st)
                for st in statements
                if tx.fetchval("SELECT to_regclass(?)", (f'"{prefix}{name}".{st.split()[-1]}',))
            }
            _stamp(tx)
    if prefix + "dataops" in present:
        with Database.connect(url, "dataops") as db, db.transaction() as tx:
            done["dataops"] = {t: tx.execute(f"DELETE FROM {t}") for t in ("built", "built_kept")
                               if tx.fetchval("SELECT to_regclass(?)", (f'"{prefix}dataops".{t}',))}  # fmt: skip
    if prefix + "edc" in present:
        with Database.connect(url, "edc") as db:
            if _has(db, "draft"):
                trail, old = _edc_clauses(db), _edc_old(db)
                with db.transaction() as tx:  # open drafts of a rule-1 study with no trail; then the study is rule 2
                    waiting = [str(r[0]) for r in tx.fetchall(
                        f"SELECT DISTINCT d.study FROM draft d WHERE {old} AND NOT EXISTS (SELECT 1 FROM draft d2 "
                        f"WHERE d2.study = d.study AND {trail.replace('d.', 'd2.')})")]  # fmt: skip
                    n = tx.execute("DELETE FROM draft d WHERE d.study = ANY(?)", (waiting,)) if waiting else 0
                    if waiting and _has(db, "tb_id_rule_study"):
                        tx.execute("UPDATE tb_id_rule_study SET rule = ?, recorded_at = now() WHERE study = ANY(?)",
                                   (id_rule.RULE, waiting))  # fmt: skip
                done["edc"] = {"open_drafts_cleared": n, "studies_now_rule_2": waiting,
                               "frozen_studies": (before.get("edc") or {}).get("frozen_studies") or {}}  # fmt: skip
    return done


def rebuild(lake: Path, url: str | None, today: date | None = None,
            after_step: Callable[[str], None] | None = None) -> dict[str, Any]:  # fmt: skip
    """Check, then the steps in order (module docstring); ``after_step`` (tests) is called after each step."""
    lake.mkdir(parents=True, exist_ok=True)
    with _stopped(lake, url):
        before = plan(lake, url, today)
        done: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "rule": id_rule.RULE}
        for step in STEPS:
            if step == "aside":
                done["moved_aside"] = _move_aside(lake, before["lake"]["moved_aside"])
            elif step == "served":
                done["served_cleared"] = _remove(lake, SERVED)
            elif step == "lake":
                done["lake_cleared"] = _remove(lake, REST)
            elif step == "stores" and url:
                done.update(_stores(lake, url, before))
            if after_step is not None:
                after_step(step)
        done["lake"] = {"snapshots": before["lake"]["snapshots"], "kept_aside": _aside(lake)}
        (lake / RECORD).write_text(json.dumps(done, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    _audit(done)
    return done


def _audit(done: dict[str, Any]) -> None:
    """One event of a kind the box already has (no audit schema change): the lake rebuilt from a source."""
    where = os.environ.get("TB_AUDIT_DIR")
    if not where:
        return
    from tb_common.audit_writer import open_audit

    open_audit(Path(where), os.environ.get("TB_TZ") or "UTC").append(
        "lake.rebuild.source", actor="id-rule-rebuild",
        detail={"source": "id_rule", "rule": id_rule.RULE, "counts": done},
    )  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.id_rule_rebuild", description=__doc__.split("\n\n")[0])
    ap.add_argument("--lake", type=Path, default=Path(os.environ.get("TB_LAKE_DIR") or "/data/lake"))
    ap.add_argument("--db-url", default=os.environ.get("TB_DB_URL"), help="the trial database (default TB_DB_URL)")
    ap.add_argument("--yes", action="store_true", help="do what the plan lists")
    a = ap.parse_args(argv)
    before = plan(a.lake, a.db_url)
    print(json.dumps({"plan": before}, indent=1, sort_keys=True))
    for study, n in sorted(((before.get("edc") or {}).get("open_drafts") or {}).items()):
        print(f"EDC study {study}: {n} open drafts (nothing decided, signed or sent) are cleared; the study goes on")
    if not a.yes:
        print(f"nothing changed. To do what is listed: add --yes ({id_rule.RUNBOOK})")
        return 0
    try:
        done = rebuild(a.lake, a.db_url)
    except Refused as exc:
        print(f"refused, nothing changed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"done": done}, indent=1, sort_keys=True))
    print("the next night reads every table whole (a full night); then the lake is rebuilt from it")
    for study, n in sorted(((done.get("edc") or {}).get("frozen_studies") or {}).items()):
        print(f"EDC study {study}: frozen for prefill ({n} decided, signed or sent values cite the earlier rule's "
              f"rows); export it: GET /api/v1/studies/{study}/edc/export/odm ({id_rule.RUNBOOK}, step 2)")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
