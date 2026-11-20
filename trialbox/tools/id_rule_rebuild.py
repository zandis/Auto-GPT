"""D-1253: the one rebuild a box makes when its lake ids change rule (runbook §5, "Lake ids per patient").

Rule 2 (a patient's record id holds the patient) changed every id of a patient's record once. The night refuses to
add rule-2 ids to anything written under rule 1 (``tb_common.id_rule``), so a box that ran an earlier release is
rebuilt once, from its sources, after the update and with the services stopped:

    python -m tools.id_rule_rebuild --lake /data/lake          # the plan: what is kept, moved, cleared; changes nothing
    python -m tools.id_rule_rebuild --lake /data/lake --yes    # does it; the first night after it is a full night

**Before anything.** It refuses, changing nothing, when a later release wrote anything on the box (a snapshot, a store
or an EDC study of a rule above this one, or a snapshot record that cannot be read): "update the box" (:func:`newer`).
It refuses, changing nothing, unless the writers are stopped. It checks this itself and does not trust the runbook:

- it takes the adapter's run lock, so no night runs during it and none can start;
- no lake build runs;
- no service's database role is connected to the trial database (or to the OMOP database the night probes).

It holds the lake lock for the whole lake part.

**What it never deletes**: what cannot be made again or what a person decided.

- The month-end snapshots that retention keeps are **moved aside** to ``<lake>/id_rule_1/``, where no reader looks.
  They are kept, not read, and pruned there by retention as before. Each is chosen from every place a snapshot is
  (:func:`tb_common.id_rule.snapshot_names`) and moved whole, one file or folder at a time (:func:`_parts`).
- Each resolved conflict of the derived store, with the score row it names, is **kept**. It is marked ``id_rule =
  1`` and its row is superseded, so screening never reads it again.
- EDC's trail stays: append-only, D-281.
- The site key, the pid map, the site set-up's facts, the embedding cache and the FHIR ledger stay. The ledger is how
  the next load deletes the old ids from fhir-store.

**What it clears**, in this order. A crash after any step, or between any two moves aside, loses nothing kept and
leaves a box that serves nothing of the old rule, and a second run finishes the work.

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
   - in EDC, the open drafts of each rule-1 study that is not frozen. The plan lists them by count. Such a study is
     then stamped rule 2; a decided value that cites no lake row stays as it is.

   Each store is stamped rule 2 in the same transaction.

A rule-1 EDC study with a decided, signed or sent value that cites a lake row stays **frozen** (EDC's own
definition, ``edc.store.cites_old_rows``). The plan and the rebuild name it, with its
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
OMOP_FEED = "source_kind = 'feed' AND resource_type NOT IN ('Patient', 'Practitioner')"
#: the OMOP feed records of patients' clinical data (``OMOP_FEED``), written out: what the plan counts and the rebuild
#: clears table by table
OMOP_FEED_COUNT = (
    "SELECT count(*) FROM tb_record WHERE source_kind = 'feed' AND resource_type NOT IN ('Patient', 'Practitioner')"
)
OMOP_FEED_TABLES = (
    "SELECT DISTINCT cdm_table FROM tb_record WHERE source_kind = 'feed' AND "
    "resource_type NOT IN ('Patient', 'Practitioner') AND cdm_table IS NOT NULL"
)
#: the derived conflicts a person resolved, and every conflict they were carried from: kept
KEPT_CONFLICTS = (
    "WITH RECURSIVE k(id) AS (SELECT id FROM conflict WHERE resolution IS NOT NULL UNION SELECT c.carried_from FROM "
    "conflict c JOIN k ON c.id = k.id WHERE c.carried_from IS NOT NULL) SELECT id FROM k"
)


def _q(template: str, *names: str) -> str:
    """A statement with each ``{}`` filled by a quoted identifier (psycopg's own quoting), as the text the box's
    database wrapper takes."""
    from psycopg import sql

    return sql.SQL(template).format(*(sql.Identifier(n) for n in names)).as_string(None)


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
    """Every completed month's month-end snapshot (not the nightly ones): moved aside, never deleted. Every month, not
    only those the site's retention keeps: the nightly prune applies the site's own setting to the aside folder
    (``adapter.pipeline._prune_aside``), so nothing the site keeps is lost here.

    Chosen from every place a snapshot is (:func:`snapshot_names`) and from what an earlier run, cut short, moved
    aside already: a month keeps its own month-end, never a second one, and a part already aside never makes the
    parts left behind look like a nightly snapshot to clear (review round 3)."""
    from adapter.pipeline import PASSED, _built_not_served, _current
    from tb_common.retention import snapshots_to_keep

    snaps = id_rule.snapshot_names(lake)
    aside = id_rule.snapshot_names(lake / ASIDE)
    good = {
        s
        for s in snaps
        if (lake / "ndjson" / s / PASSED).exists()
        or ((lake / "db" / f"{s}.duckdb").exists() and not _built_not_served(lake, s))
    }
    if current := _current(lake):
        good.add(current)
    months = 12 * 100  # every completed month on the box
    return sorted(snapshots_to_keep(snaps | aside, today, 0, months, good | aside))


def _parts(lake: Path, s: str) -> list[tuple[Path, Path]]:
    """Every file and folder of the snapshot ``s`` under the lake, each with its place under ``id_rule_1``: the NDJSON
    folder, the Parquet folder, the DuckDB file and its sidecars (``.sha256``, ``.source``, ``.siteonly``), and its
    generations' files and records (``db/gen/<s>.g<n>.*``)."""
    to = lake / ASIDE
    parts = [(lake / "ndjson" / s, to / "ndjson" / s), (lake / "parquet" / f"snapshot={s}",
             to / "parquet" / f"snapshot={s}")]  # fmt: skip
    parts += [(f, to / "db" / f.name) for f in sorted((lake / "db").glob(f"{s}.duckdb*"))]
    parts += [(f, to / "db" / "gen" / f.name) for f in sorted((lake / "db" / "gen").glob(f"{s}.g*"))]
    return parts


def newer(lake: Path, url: str | None) -> list[str]:
    """What a later release wrote (empty: the rebuild may run): a snapshot whose record says a rule above this one's
    or cannot be read (a snapshot of rule 1 has no record), a store or an EDC study stamped by a later release. The
    rebuild never treats them as rule 1: the box is updated instead (review round 3)."""
    found: list[str] = []
    for folder in ("ndjson", "ndjson-rerun", "backfill", f"{ASIDE}/ndjson"):
        root = lake / folder
        if not root.is_dir():
            continue
        for snap in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            rule = id_rule.snapshot_rule(snap)
            if rule > id_rule.RULE:
                found.append(f"the lake snapshot {folder}/{snap.name} is of id rule {rule}")
            elif rule == 0:
                found.append(f"the lake snapshot {folder}/{snap.name} has an id-rule record that cannot be read")
    from lake.store import ID_RULE_SIDECAR

    for root in (lake / "db", lake / ASIDE / "db"):
        for side in sorted(root.glob(f"*.duckdb{ID_RULE_SIDECAR}")):
            try:
                rule = int(side.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                rule = 0
            if rule <= 0 or rule > id_rule.RULE:
                found.append(
                    f"{side.relative_to(lake)}: unsupported id rule / 不支援的 ID 規則 / "
                    f"未対応の ID 規則 ({rule or '?'})"
                )
    if not url:
        return found
    from omop.schema import schema_for
    from tb_common.db import Database, split_url

    present = _schemas(url)
    omop_url = _omop_url(url) or url
    for store in id_rule.STORES:
        where = omop_url if store is id_rule.OMOP else url
        name = schema_for(lake) if store is id_rule.OMOP else store.schema
        if id_rule.probe(where, store, name) == id_rule.NEWER:
            found.append(f"the {store.name} store is stamped by a later release")
    if split_url(url)[1] + "edc" in present:
        with Database.connect(url, "edc") as db:
            if _has(db, "tb_id_rule_study"):
                ahead = db.fetchall("SELECT study, rule FROM tb_id_rule_study WHERE rule > ? ORDER BY study",
                                    (id_rule.RULE,))  # fmt: skip
                found += [f"the EDC study {s} is stamped id rule {r}" for s, r in ahead]
    return found


def _omop_url(url: str | None) -> str | None:
    return os.environ.get("TB_OMOP_DB_URL") or url


def _edc_tables(db: Any) -> tuple[str, ...]:
    """The trail tables (``edc.store.TRAIL_TABLES``) this EDC store has."""
    from edc.store import TRAIL_TABLES

    return tuple(t for t in TRAIL_TABLES if _has(db, t))


def _edc_frozen(db: Any, d: str = "d") -> Any:
    """A draft that freezes its study: EDC's own definition (``edc.store.cites_old_rows``), never a second one; as a
    psycopg ``Composable`` (EDC composes it with psycopg's quoting)."""
    from edc.store import cites_old_rows
    from psycopg import sql

    return sql.SQL(cites_old_rows(d, _edc_tables(db)))


def _edc_open(db: Any, d: str = "d") -> Any:
    """An open draft (no trail): EDC's own definition (``edc.store.has_trail``), negated."""
    from edc.store import has_trail
    from psycopg import sql

    return sql.SQL("NOT {}").format(sql.SQL(has_trail(d, _edc_tables(db))))


def _edc_old(db: Any) -> Any:
    """A draft of a study not of the current rule (a study with no rule row has no draft: the migration stamped every
    study that had one)."""
    from psycopg import sql

    if not _has(db, "tb_id_rule_study"):
        return sql.SQL("TRUE")
    return sql.SQL("d.study IN (SELECT study FROM tb_id_rule_study WHERE rule < {})").format(sql.Literal(id_rule.RULE))


def _edc_q(template: str, *parts: Any) -> str:
    """A statement over EDC's drafts with each ``{}`` filled by a composed clause (:func:`_edc_frozen`,
    :func:`_edc_open`, :func:`_edc_old`), as the text the box's database wrapper takes."""
    from psycopg import sql

    return sql.SQL(template).format(*parts).as_string(None)


def _edc_plan(db: Any) -> dict[str, Any]:
    frozen_q, open_q, old = _edc_frozen(db), _edc_open(db), _edc_old(db)
    per_study = "SELECT d.study, count(*) FROM draft d WHERE {} AND {} GROUP BY d.study ORDER BY d.study"
    frozen = db.fetchall(_edc_q(per_study, frozen_q, old))
    frozen_studies = {str(s): int(n) for s, n in frozen}
    waiting = db.fetchall(_edc_q(per_study, open_q, old))
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
        "newer": newer(lake, url),
        "lake": {
            "dir": str(lake),
            "snapshots": len(snaps),
            "old_snapshots": id_rule.old_snapshots(lake / "ndjson"),
            "moved_aside": aside,
            "cleared": [e for e in LAKE_ENTRIES if (lake / e).exists()],
            "kept": ["site_key.json", "pid map", "site", "embed_cache.duckdb", "fhir_ledger", ASIDE],
        },
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
                row["cleared"] = {"feed_records": int(db.fetchval(OMOP_FEED_COUNT))}
            else:
                row["cleared"] = {t: int(db.fetchval(_q("SELECT count(*) FROM {}", t))) for t in COUNTS.get(name, ())
                                  if _has(db, t)}  # fmt: skip
                if name == "derived" and _has(db, "conflict") and "resolution" in _columns(db, "conflict"):
                    kept = len(db.fetchall(KEPT_CONFLICTS))
                    row["kept"] = {"resolved_conflicts": kept}
                    row["cleared"]["conflict"] = row["cleared"].get("conflict", 0) - kept
        out[store.name] = row
    if prefix + "dataops" in present:
        with Database.connect(url, "dataops") as db:
            out["dataops"] = {"cleared": {t: int(db.fetchval(_q("SELECT count(*) FROM {}", t)))
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


def _move_aside(lake: Path, snaps: list[str], after_move: Callable[[Path], None] | None = None) -> list[str]:
    """Each month-end, every part of it (:func:`_parts`), to ``<lake>/id_rule_1/``, as it is (it says no rule: 1).
    One file or folder at a time; again after a crash between any two moves: what is already there stays, what is
    left is moved (:func:`month_ends` sees both). ``after_move`` (tests) is called after each move."""
    moved = []
    to = lake / ASIDE
    for s in snaps:
        for src, dst in _parts(lake, s):
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dst)
                if after_move is not None:
                    after_move(dst)
        moved.append(s)
    if moved:
        tmp = to / ".README.json.tmp"
        tmp.write_text(json.dumps({
            "rule": 1, "why": "D-1253: month-end snapshots of the earlier id rule, kept under retention, never read",
            "snapshots": _aside(lake)}, indent=1) + "\n", encoding="utf-8")  # fmt: skip
        tmp.replace(to / "README.json")
    return moved


def _aside(lake: Path) -> list[str]:
    return sorted(id_rule.snapshot_names(lake / ASIDE))


def _stamp(tx: Any) -> None:
    tx.execute(id_rule.DDL)
    tx.execute("INSERT INTO tb_id_rule (rule) VALUES (?) ON CONFLICT (rule) DO NOTHING", (id_rule.RULE,))


def _clear_omop(db: Any) -> dict[str, int]:
    from omop.load import ID_COL

    counts: dict[str, int] = {}
    with db.transaction() as tx:
        tables = [str(r[0]) for r in tx.fetchall(
            OMOP_FEED_TABLES)]  # fmt: skip
        for t in sorted(tables):
            col = ID_COL.get(t)
            if col is None:
                raise Refused(f"the OMOP store holds feed records of table {t}, which this rebuild does not know")
            counts[t] = tx.execute(
                _q("DELETE FROM {} WHERE {} IN (SELECT record_id FROM tb_record WHERE source_kind = 'feed' AND "
                   "resource_type NOT IN ('Patient', 'Practitioner') AND cdm_table = ?)", t, col),
                (t,),
            )  # fmt: skip
        counts["tb_record_event"] = tx.execute(
            "DELETE FROM tb_record_event WHERE record_key IN (SELECT record_key FROM tb_record WHERE "
            "source_kind = 'feed' AND resource_type NOT IN ('Patient', 'Practitioner'))"
        )
        counts["tb_record"] = tx.execute(
            "DELETE FROM tb_record WHERE source_kind = 'feed' AND resource_type NOT IN ('Patient', 'Practitioner')"
        )  # the rows OMOP_FEED names
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
                    counts[t] = tx.execute(_q("DELETE FROM {}", t))
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
            done["dataops"] = {t: tx.execute(_q("DELETE FROM {}", t)) for t in ("built", "built_kept")
                               if tx.fetchval("SELECT to_regclass(?)", (f'"{prefix}dataops".{t}',))}  # fmt: skip
    if prefix + "edc" in present:
        with Database.connect(url, "edc") as db:
            if _has(db, "draft"):
                old, frozen_q, open_q = _edc_old(db), _edc_frozen(db, "d2"), _edc_open(db)
                with db.transaction() as tx:
                    # a rule-1 study no draft of which freezes it: its open drafts go (a decided value that cites no
                    # lake row stays, as it is), then the study is rule 2 (review round 3: one definition with EDC)
                    not_frozen = ("SELECT DISTINCT d.study FROM draft d WHERE {} AND NOT EXISTS (SELECT 1 FROM draft "
                                  "d2 WHERE d2.study = d.study AND {})")  # fmt: skip
                    waiting = [str(r[0]) for r in tx.fetchall(_edc_q(not_frozen, old, frozen_q))]
                    clear = "DELETE FROM draft d WHERE d.study = ANY(?) AND {}"
                    n = tx.execute(_edc_q(clear, open_q), (waiting,)) if waiting else 0
                    if waiting and _has(db, "tb_id_rule_study"):
                        tx.execute("UPDATE tb_id_rule_study SET rule = ?, recorded_at = now() WHERE study = ANY(?)",
                                   (id_rule.RULE, waiting))  # fmt: skip
                done["edc"] = {"open_drafts_cleared": n, "studies_now_rule_2": waiting,
                               "frozen_studies": (before.get("edc") or {}).get("frozen_studies") or {}}  # fmt: skip
    return done


def rebuild(lake: Path, url: str | None, today: date | None = None,
            after_step: Callable[[str], None] | None = None,
            after_move: Callable[[Path], None] | None = None) -> dict[str, Any]:  # fmt: skip
    """Check, then the steps in order (module docstring); ``after_step`` (tests) is called after each step and
    ``after_move`` after each file or folder moved aside."""
    lake.mkdir(parents=True, exist_ok=True)
    with _stopped(lake, url):
        before = plan(lake, url, today)
        if before["newer"]:
            said = "; ".join(before["newer"])
            raise Refused(f"{said}: a later release wrote these. Update the box to that release; this rebuild is "
                          f"for a box that ran an earlier one ({id_rule.RUNBOOK})")  # fmt: skip
        done: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "rule": id_rule.RULE}
        for step in STEPS:
            if step == "aside":
                done["moved_aside"] = _move_aside(lake, before["lake"]["moved_aside"], after_move)
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
    if before["newer"]:
        print(f"refused, nothing changed: {'; '.join(before['newer'])}. A later release wrote these: update the box "
              f"to that release ({id_rule.RUNBOOK})", file=sys.stderr)  # fmt: skip
        return 2
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
