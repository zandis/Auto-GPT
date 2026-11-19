"""D-1253: the one rebuild a box makes when its lake ids change rule (runbook §5, "Lake ids per patient").

Rule 2 (a patient's record id holds the patient) changed every id of a patient's record once. The night refuses to
add rule-2 ids to anything written under rule 1 (``tb_common.id_rule``), so a box that ran an earlier release is
rebuilt once, from its sources:

    python -m tools.id_rule_rebuild --lake /data/lake          # the plan: what is there, what goes; changes nothing
    python -m tools.id_rule_rebuild --lake /data/lake --yes    # clears it; the first night after it is a full night

**For a box that holds synthetic data only.** What it clears, in this order:

1. the lake: the NDJSON snapshots and their re-runs, the DuckDB and Parquet copies, the back-fill's working copy,
   the served snapshot's name and the last feed's date (``lake:ndjson``, ``lake:db``, ...). The site key, the pid map,
   the site set-up's facts, the embedding cache (keyed by text, not by record) and the FHIR ledger stay: the ledger
   is how the next load deletes the old ids from fhir-store;
2. the OMOP store of record behind the lake: every feed record of a patient's clinical data (its CDM row, its
   ``tb_record`` row and that row's events). The persons stay (a patient's pseudonym is the same under both rules),
   and so do the site set-up's records, the vocabulary, the conflicts, the loads' history and the ruleset releases;
3. the derived store: the scores, their inputs and conflicts and the batch runs (the definitions stay);
4. the vector store: the note chunks (the embeddings are keyed by the text's hash and stay);
5. the patient twin: every document and version;
6. the candidate pool: every row (MICROBATCH fills it again);
7. the EDC drafts that are open and have no decision, signature or send.

Then each store is stamped with rule 2. **EDC decided or signed values are never cleared**: their trail is
append-only (D-281). While any EDC draft with a citation has a decision, a signature or a send, the command stops
before it changes anything and names each study with its counts; the runbook says what a person decides then.

Published job outputs and the audit chain are not touched: an output made before the rebuild cites the old ids and
cannot be traced into the rebuilt lake; the chain is unaffected. What was cleared is written to
``<lake>/id_rule_rebuild.json`` (counts only).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tb_common import id_rule  # noqa: E402

#: the lake entries made from the snapshots (``tb_common.erasure``'s ``lake:<name>``), cleared by the rebuild
LAKE_ENTRIES = ("ndjson", "ndjson-rerun", "db", "parquet", "backfill", "tmp", "holds", "CURRENT", "CURRENT.tmp", "FEED")
RECORD = "id_rule_rebuild.json"
#: per store: what is cleared (each a statement of the store's own schema), and what it counts first
CLEARS: dict[str, tuple[str, ...]] = {
    "derived": ("DELETE FROM conflict", "DELETE FROM input_link", "DELETE FROM score_row", "DELETE FROM batch_run"),
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
EDC_DECIDED = (
    "SELECT d.study, count(*) FROM draft d WHERE (d.citation IS NOT NULL OR d.final_citation IS NOT NULL) AND "
    "(d.fate IN ('confirmed', 'edited') OR d.signature_id IS NOT NULL OR d.sent_at IS NOT NULL OR EXISTS "
    "(SELECT 1 FROM decision x WHERE x.draft_id = d.id)) GROUP BY d.study ORDER BY d.study"
)
EDC_OPEN = (
    "FROM draft d WHERE NOT EXISTS (SELECT 1 FROM decision x WHERE x.draft_id = d.id) AND d.signature_id IS NULL "
    "AND d.sent_at IS NULL AND d.fate NOT IN ('confirmed', 'edited')"
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


def plan(lake: Path, url: str | None) -> dict[str, Any]:
    """What is there: per store, its rule state and the rows the rebuild clears; EDC's decided values per study."""
    from omop.schema import schema_for
    from tb_common.db import Database, split_url

    out: dict[str, Any] = {"lake": {"dir": str(lake), "snapshots": len(_snapshots(lake)),
                                    "old_snapshots": id_rule.old_snapshots(lake / "ndjson"),
                                    "entries": [e for e in LAKE_ENTRIES if (lake / e).exists()]}}  # fmt: skip
    if not url:
        out["database"] = "no TB_DB_URL: the stores of the trial database were not read"
        return out
    prefix = split_url(url)[1]
    present = _schemas(url)
    omop = schema_for(lake)
    for store in id_rule.STORES:
        name = omop if store is id_rule.OMOP else store.schema
        if prefix + name not in present:
            out[store.name] = {"schema": prefix + name, "present": False}
            continue
        row: dict[str, Any] = {"schema": prefix + name, "present": True, "rule": id_rule.probe(url, store, name)}
        with Database.connect(url, name) as db:
            if store is id_rule.OMOP and _has(db, "tb_record"):
                row["feed_records"] = int(db.fetchval(f"SELECT count(*) FROM tb_record WHERE {OMOP_FEED}"))
            elif store is id_rule.EDC and _has(db, "draft"):
                row["decided_by_study"] = {str(s): int(n) for s, n in db.fetchall(EDC_DECIDED)}
                row["open_drafts"] = int(db.fetchval(f"SELECT count(*) {EDC_OPEN}"))
            else:
                row["rows"] = {t: int(db.fetchval(f"SELECT count(*) FROM {t}")) for t in COUNTS.get(name, ())
                               if _has(db, t)}  # fmt: skip
        out[store.name] = row
    return out


def _snapshots(lake: Path) -> list[str]:
    nd = lake / "ndjson"
    return sorted(p.name for p in nd.iterdir() if p.is_dir()) if nd.is_dir() else []


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
        tx.execute(id_rule.DDL)
        tx.execute("INSERT INTO tb_id_rule (rule) VALUES (?) ON CONFLICT (rule) DO NOTHING", (id_rule.RULE,))
    return counts


def rebuild(lake: Path, url: str | None) -> dict[str, Any]:
    """Clear and stamp (module docstring); raises :class:`Refused`, before any change, on EDC decided values."""
    from omop.schema import schema_for
    from tb_common.db import Database, split_url

    before = plan(lake, url)
    decided = (before.get("edc") or {}).get("decided_by_study") or {}
    if decided:
        raise Refused(
            "EDC values a person decided, signed or sent cite lake rows of the earlier rule: "
            + ", ".join(f"study {s}: {n}" for s, n in sorted(decided.items()))
            + f". They are records and are never cleared here. See {id_rule.RUNBOOK}, step 2"
        )
    done: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "rule": id_rule.RULE}
    if url:
        prefix = split_url(url)[1]
        present = _schemas(url)
        omop = schema_for(lake)
        if prefix + omop in present:
            with Database.connect(url, omop) as db:
                done["omop"] = _clear_omop(db) if _has(db, "tb_record") else {}
        for name, statements in CLEARS.items():
            if prefix + name not in present:
                continue
            with Database.connect(url, name) as db, db.transaction() as tx:
                done[name] = {
                    st.split()[-1]: tx.execute(st)
                    for st in statements
                    if tx.fetchval("SELECT to_regclass(?)", (f'"{prefix}{name}".{st.split()[-1]}',))
                }
                tx.execute(id_rule.DDL)
                tx.execute("INSERT INTO tb_id_rule (rule) VALUES (?) ON CONFLICT (rule) DO NOTHING", (id_rule.RULE,))
        if prefix + "edc" in present:
            with Database.connect(url, "edc") as db, db.transaction() as tx:
                done["edc"] = {"open_drafts": tx.execute(f"DELETE {EDC_OPEN}")}
                tx.execute(id_rule.DDL)
                tx.execute("INSERT INTO tb_id_rule (rule) VALUES (?) ON CONFLICT (rule) DO NOTHING", (id_rule.RULE,))
    gone = []
    for entry in LAKE_ENTRIES:
        path = lake / entry
        if path.is_dir():
            shutil.rmtree(path)
            gone.append(entry)
        elif path.exists():
            path.unlink()
            gone.append(entry)
    done["lake"] = {"cleared": gone, "snapshots": before["lake"]["snapshots"]}
    lake.mkdir(parents=True, exist_ok=True)
    (lake / RECORD).write_text(json.dumps(done, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.id_rule_rebuild", description=__doc__.split("\n\n")[0])
    ap.add_argument("--lake", type=Path, default=Path(os.environ.get("TB_LAKE_DIR") or "/data/lake"))
    ap.add_argument("--db-url", default=os.environ.get("TB_DB_URL"), help="the trial database (default TB_DB_URL)")
    ap.add_argument("--yes", action="store_true", help="clear what the plan lists (synthetic data only)")
    a = ap.parse_args(argv)
    before = plan(a.lake, a.db_url)
    print(json.dumps({"plan": before}, indent=1, sort_keys=True))
    if not a.yes:
        print(
            f"nothing changed. To clear what is listed (a box with synthetic data only): add --yes ({id_rule.RUNBOOK})"
        )
        return 0
    try:
        done = rebuild(a.lake, a.db_url)
    except Refused as exc:
        print(f"refused, nothing changed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"cleared": done}, indent=1, sort_keys=True))
    print("the next night reads every table whole (a full night); then the lake is rebuilt from it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
