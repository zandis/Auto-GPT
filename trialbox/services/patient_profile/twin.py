"""The patient twin, ``tb_patient_profile`` v1 (T-204, D-440).

One JSON document per patient (``schemas/profile.schema.json``), assembled with no model from one lake snapshot and
the stored derived rows, and kept with every version in schema ``profile`` of the trial database.

* **Layers.** ``record``, ``timeline``, ``phenotype``, ``derived``, ``eligibility``, ``setpoint``, ``gap`` and
  ``similarity``. A layer is ``null`` until the card that builds it lands (never left out), else
  ``{"version": "<layer>@<n>", "items": [...]}``.
* **Sources.** Every item carries ``source``: the source table and row hash the adapter stamped on the lake row
  (T-106b) or, for a row no mapping made, the lake table; the lake row id; the item's date. T-311a cites from it.
* **Basis.** The document names the lake snapshot and the mapping versions of its rows; the stored row also says the
  newest snapshot that gave the same content (``checked_snapshot``).
* **Deterministic.** Only the given snapshot is read, every list is sorted by a total key, and the document is
  canonical JSON with no build time in it: two builds of one snapshot give the same bytes.
* **Opt-out.** :func:`build` reads the register (:func:`tb_common.optout.opted_out`): an opted-out patient is never
  assembled and their rows are erased. The opt-out worker (T-206a) calls :meth:`ProfileStore.erase`.

    store = ProfileStore()                      # TB_DB_URL
    build(store, lake, pids, snapshot=snap, derived=DerivedStore(), now=clock())
    store.current(pid)                          # Twin | None
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from tb_common.db import ENV, Database
from tb_common.optout import opted_out

log = logging.getLogger("patient_profile")

PROFILE = "tb_patient_profile/1"
SCHEMA_NAME = "profile"  # schemas/profile.schema.json
STORE = "profile"  # schema of the trial database
LAYERS: tuple[str, ...] = ("record", "timeline", "phenotype", "derived", "eligibility", "setpoint", "gap", "similarity")
#: the layers v1 builds, with the version of the code that builds each
BUILT: dict[str, str] = {"record": "record@1", "timeline": "timeline@1", "phenotype": "phenotype@1",
                         "derived": "derived@1"}  # fmt: skip
#: the layers only a role holding ``profile.research_layers`` is shown (T-313 fills them)
RESEARCH_LAYERS: tuple[str, ...] = ("setpoint", "gap")

# the lake tables of the timeline: (id column, columns read). Free text (note text, report conclusions, names) is
# never read: the twin holds codes, values, dates and sources only.
_TIMELINE: dict[str, tuple[str, tuple[str, ...]]] = {
    "encounter": ("eid", ("start", "class", "dept", "status")),
    "condition": ("cid", ("onset", "recorded", "code", "system", "status")),
    "observation": ("oid", ("effective", "code", "system", "value_num", "value_code", "unit", "value_cmp")),
    "medication": ("mid", ("start", "authored", "atc", "nhi_code", "name", "status")),
    "procedure": ("prid", ("performed", "code", "system")),
    "report": ("rid", ("effective", "code", "system")),
    "document": ("did", ("date", "type")),
}
_PROV = ("src_table", "src_row_hash", "mapping_version")
#: NEW-B-40 (D-741): the oldest lake schema a twin is read from: the encounter's status and each row's provenance
#: (T-106b) came with schema 3. The lake still serves schemas 1 and 2 (``lake.store.MIN_READABLE_SCHEMA``)
TWIN_MIN_SCHEMA = 3

MIGRATIONS: tuple[str, ...] = (
    """
CREATE TABLE tb_patient_profile (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pid TEXT NOT NULL,
  version INTEGER NOT NULL,
  snapshot TEXT NOT NULL,
  doc TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  built_at TEXT COLLATE "C" NOT NULL,
  checked_snapshot TEXT NOT NULL,
  checked_at TEXT COLLATE "C" NOT NULL,
  superseded_at TEXT,
  UNIQUE (pid, version)
);
CREATE UNIQUE INDEX tb_patient_profile_current ON tb_patient_profile (pid) WHERE superseded_at IS NULL
""",
)


class LakeReader(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


class TwinError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- canonical form
def _j(v: Any) -> Any:
    """A JSON value of a lake cell: dates as ISO text, non-finite numbers as null, whole floats kept as floats."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def canonical(doc: Mapping[str, Any]) -> bytes:
    """The stored bytes: sorted keys, no spaces, UTF-8. Equal documents give equal bytes."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_sha(doc: Mapping[str, Any]) -> str:
    """sha256 of the layers alone: a new snapshot that changes nothing for the patient writes no new version."""
    return hashlib.sha256(canonical({"profile": doc["profile"], "layers": doc["layers"]})).hexdigest()


# ---------------------------------------------------------------------------------------------- the lake read
#: has the snapshot's ``lake_meta`` a version column: one row, one number (a snapshot of schema 1 has none)
VERSION_COLUMN_SQL = (
    "SELECT count(*) AS n FROM duckdb_columns() "
    "WHERE lower(table_name) = 'lake_meta' AND lower(column_name) = 'schema_version'"
)


def lake_schema(lake: LakeReader, snapshot: str) -> int:
    """The layout version of ``snapshot``; 1 for a snapshot built before the version was recorded.

    NEW-B-35 (D-676): whether the version column is there is asked of the lake, not read from an error. Before,
    every error of the version question was read as "schema 1": a lake that failed on that one question was taken
    for an older snapshot and the twins were built without the provenance of their rows. There is no handler
    here: a failure of the lake (D-675: a 5xx) or a fault of the question stops the build."""
    rows = lake.query(VERSION_COLUMN_SQL, [], snapshot).to_pylist()
    n = rows[0].get("n") if len(rows) == 1 else None
    if type(n) is not int:
        raise TwinError(f"the lake did not say whether snapshot {snapshot} records its layout version")
    if n == 0:
        return 1
    rows = lake.query("SELECT schema_version FROM lake_meta", [], snapshot).to_pylist()
    v = rows[0].get("schema_version") if rows else None
    return int(v) if v is not None else 1


def read_lake(lake: LakeReader, pids: Sequence[str], snapshot: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """``{pid: {table: [row, ...]}}`` for ``pids`` from ``snapshot`` (never "current": the caller pins it)."""
    out: dict[str, dict[str, list[dict[str, Any]]]] = {p: {} for p in pids}
    if not pids:
        return out
    version = lake_schema(lake, snapshot)
    if version < TWIN_MIN_SCHEMA:
        raise TwinError(
            f"lake snapshot {snapshot} has lake schema {version}; a twin needs schema {TWIN_MIN_SCHEMA} or later (the "
            "encounter's status and each row's provenance came with it): rebuild the snapshot from its NDJSON (the "
            "lake's rebuild) before twins are built from it"
        )
    pcols = ", ".join(_PROV)
    plist = [sorted(pids)]
    tables: dict[str, tuple[str, tuple[str, ...]]] = {
        "patient": ("pid", ("birth_date", "sex", "deceased_date", "deceased")),
        **_TIMELINE,
    }
    for table, (idc, cols) in tables.items():
        quoted = ", ".join(f'"{c}"' for c in (idc, *cols) if c != "pid")
        sql = (f'SELECT pid, {quoted}, {pcols} FROM "{table}" '  # constants only, never user input
               "WHERE pid IN (SELECT unnest(CAST($1 AS VARCHAR[])))")  # fmt: skip
        for r in lake.query(sql, plist, snapshot).to_pylist():
            if r["pid"] in out:
                out[r["pid"]].setdefault(table, []).append(r)
    return out


# ---------------------------------------------------------------------------------------------- the assembler
def _source(table: str, row: Mapping[str, Any], idc: str, when: Any) -> dict[str, Any]:
    return {
        "table": row.get("src_table") or table,
        "row_hash": row.get("src_row_hash"),
        "lake_table": table,
        "row": str(row.get(idc)),
        "date": _j(when),
    }


def _item(kind: str, row: Mapping[str, Any]) -> dict[str, Any]:
    idc = _TIMELINE[kind][0]
    when: Any = None
    code = system = value = unit = status = cmp = None
    if kind == "encounter":
        when, code, value, status = row.get("start"), row.get("class"), row.get("dept"), row.get("status")
    elif kind == "condition":
        when = row.get("onset") or row.get("recorded")
        code, system, status = row.get("code"), row.get("system"), row.get("status")
    elif kind == "observation":
        when, code, system, unit = row.get("effective"), row.get("code"), row.get("system"), row.get("unit")
        value = row.get("value_num") if row.get("value_num") is not None else row.get("value_code")
        cmp = row.get("value_cmp")
    elif kind == "medication":
        when = row.get("start") or row.get("authored")
        code, system = (row.get("atc"), "atc") if row.get("atc") else (row.get("nhi_code"), "nhi")
        value, status = row.get("name"), row.get("status")
    elif kind == "procedure":
        when, code, system = row.get("performed"), row.get("code"), row.get("system")
    elif kind == "report":
        when, code, system = row.get("effective"), row.get("code"), row.get("system")
    elif kind == "document":
        when, code = row.get("date"), row.get("type")
    return {
        "kind": kind,
        "date": _j(when),
        "code": code,
        "system": system if code is not None else None,
        "value": _j(value),
        "unit": unit,
        "comparator": cmp,
        "status": status,
        "source": _source(kind, row, idc, when),
    }


def _order(it: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (it["date"] or "", it["kind"], it["source"]["row"], it["source"]["row_hash"] or "")


def _record(patient: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if patient is None:
        return []
    src = _source("patient", patient, "pid", None)
    out = []
    for f in ("birth_date", "sex", "deceased", "deceased_date"):
        out.append({"field": f, "value": _j(patient.get(f)), "source": src})
    return out


def _phenotype(timeline: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The coded problems: each condition code once, with its first and last date, how often it was recorded, the
    status of its latest record and every source row."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for it in timeline:
        if it["kind"] == "condition" and it["code"]:
            groups.setdefault((it["system"] or "", it["code"]), []).append(it)
    out = []
    for (system, code), its in sorted(groups.items()):
        dated = [i["date"] for i in its if i["date"]]
        out.append({
            "system": system or None,
            "code": code,
            "first": min(dated) if dated else None,
            "last": max(dated) if dated else None,
            "count": len(its),
            "status": its[-1]["status"],
            "sources": [i["source"] for i in its],
        })  # fmt: skip
    return out


def _derived(rows: Iterable[Mapping[str, Any]], hashes: Mapping[tuple[str, str], str | None]) -> list[dict[str, Any]]:
    """The stored derived rows (``tb_common.derived_store``, D-190): the value or the reason it has none, the
    definition version, and each input row as a source."""
    out = []
    for r in rows:
        inputs = []
        for i in r.get("inputs") or []:
            table, rid = str(i.get("table") or ""), str(i.get("id") or "")
            inputs.append({"component": i.get("component"), "table": table, "row": rid,
                           "row_hash": hashes.get((table, rid)), "date": i.get("date")})  # fmt: skip
        when = _j(r.get("anchor_date"))
        out.append({
            "score": r["score"],
            "value": _j(r.get("value")),
            "reason": r.get("reason"),
            "unit": r.get("unit"),
            "date": when,
            "def_version": r.get("def_version"),
            "source": {"table": "derived.score_row", "row_hash": r.get("fingerprint"), "lake_table": None,
                       "row": str(r.get("id")), "date": when},
            "inputs": sorted(inputs, key=lambda x: (str(x["component"]), x["table"], x["row"])),
        })  # fmt: skip
    return sorted(out, key=lambda x: (x["score"], x["date"] or "", x["source"]["row"]))


def assemble(
    pid: str,
    snapshot: str,
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    derived_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The twin of one patient from their lake rows (``read_lake``) and, when given, their current derived rows
    (``DerivedStore.rows``; None leaves the layer ``null``). Pure: same input, same document."""
    patients = list(tables.get("patient") or [])
    timeline = sorted((_item(k, r) for k in _TIMELINE for r in tables.get(k) or []), key=_order)
    hashes = {(i["kind"], i["source"]["row"]): i["source"]["row_hash"] for i in timeline}
    mappings = sorted({str(r["mapping_version"]) for rows in tables.values() for r in rows
                       if r.get("mapping_version")})  # fmt: skip
    layers: dict[str, Any] = dict.fromkeys(LAYERS)
    layers["record"] = {"version": BUILT["record"], "items": _record(patients[0] if patients else None)}
    layers["timeline"] = {"version": BUILT["timeline"], "items": timeline}
    layers["phenotype"] = {"version": BUILT["phenotype"], "items": _phenotype(timeline)}
    if derived_rows is not None:
        layers["derived"] = {"version": BUILT["derived"], "items": _derived(derived_rows, hashes)}
    return {
        "profile": PROFILE,
        "pid": pid,
        "basis": {"snapshot": snapshot, "mapping_versions": mappings},
        "layers": layers,
    }


def for_role(doc: Mapping[str, Any], research: bool) -> dict[str, Any]:
    """The document a reader is shown: the research layers (``setpoint``, ``gap``) only with ``research``; for every
    other reader they are absent (D-440 item 7), while a layer not built yet stays ``null``."""
    out = dict(doc)
    out["layers"] = {k: v for k, v in doc["layers"].items() if research or k not in RESEARCH_LAYERS}
    return out


# ---------------------------------------------------------------------------------------------- the store
@dataclass(frozen=True)
class Twin:
    pid: str
    version: int
    snapshot: str
    checked_snapshot: str
    sha256: str
    built_at: str
    doc: dict[str, Any]


class ProfileStore:
    """Schema ``profile`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = Database.connect(url if url is not None else os.environ.get(ENV), STORE)
        self.db.migrate(MIGRATIONS)
        self.url = self.db.url

    def close(self) -> None:
        self.db.close()

    def put(self, doc: Mapping[str, Any], now: str) -> str:
        """Keep ``doc``: ``inserted`` (a new version; the old one superseded) or ``unchanged`` (same layers as the
        current version: only its ``checked_snapshot`` moves on)."""
        pid, snap = str(doc["pid"]), str(doc["basis"]["snapshot"])
        sha = content_sha(doc)
        with self.db.transaction() as tx:
            cur = tx.fetchone(
                "SELECT id, version, sha256 FROM tb_patient_profile WHERE pid = ? AND superseded_at IS NULL FOR UPDATE",
                (pid,),
            )
            if cur is not None and cur[2] == sha:
                tx.execute("UPDATE tb_patient_profile SET checked_snapshot = ?, checked_at = ? WHERE id = ?",
                           (snap, now, cur[0]))  # fmt: skip
                return "unchanged"
            version = int(cur[1]) + 1 if cur is not None else 1
            if cur is not None:
                tx.execute("UPDATE tb_patient_profile SET superseded_at = ? WHERE id = ?", (now, cur[0]))
            tx.execute(
                "INSERT INTO tb_patient_profile (pid, version, snapshot, doc, sha256, built_at, checked_snapshot, "
                "checked_at) VALUES (?,?,?,?,?,?,?,?)",
                (pid, version, snap, canonical(doc).decode("utf-8"), sha, now, snap, now),
            )
        return "inserted"

    def current(self, pid: str) -> Twin | None:
        r = self.db.fetchone(
            "SELECT pid, version, snapshot, checked_snapshot, sha256, built_at, doc FROM tb_patient_profile "
            "WHERE pid = ? AND superseded_at IS NULL",
            (pid,),
        )
        if r is None:
            return None
        return Twin(str(r[0]), int(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), json.loads(r[6]))

    def history(self, pid: str) -> list[dict[str, Any]]:
        """Every version of one patient's twin, oldest first (no document bodies)."""
        return self.db.fetchdicts(
            "SELECT version, snapshot, checked_snapshot, sha256, built_at, superseded_at FROM tb_patient_profile "
            "WHERE pid = ? ORDER BY version",
            (pid,),
        )

    def pids(self) -> list[str]:
        return [str(r[0]) for r in self.db.fetchall("SELECT DISTINCT pid FROM tb_patient_profile ORDER BY 1")]

    def erase(self, pid: str) -> int:
        """Delete every version of one patient's twin (the opt-out: T-206a's worker and :func:`build`). Returns the
        rows deleted."""
        return self.db.execute("DELETE FROM tb_patient_profile WHERE pid = ?", (pid,))


# ---------------------------------------------------------------------------------------------- the build step
@dataclass
class BuildReport:
    snapshot: str
    inserted: int = 0
    unchanged: int = 0
    erased: int = 0  # rows of patients on the opt-out register
    opted_out: int = 0  # asked for and not assembled
    missing: int = 0  # not in the snapshot
    failed: list[str] = field(default_factory=list)


def build(
    store: ProfileStore,
    lake: LakeReader,
    pids: Iterable[str],
    *,
    snapshot: str,
    now: str,
    derived: Any = None,
    optout_url: str | None = None,
) -> BuildReport:
    """Assemble and keep the twins of ``pids`` from ``snapshot``. The opt-out register is read first: an opted-out
    patient is never assembled, and every stored twin of a patient on it is erased. ``derived`` is a
    :class:`tb_common.derived_store.DerivedStore` (None: the derived layer stays ``null``). A patient whose
    assembly fails is listed in ``failed`` and the build goes on; nothing of theirs is changed."""
    from tb_contracts.schema import schema_errors

    if not snapshot:
        raise TwinError("a twin is built from a named snapshot")
    rep = BuildReport(snapshot)
    gone = opted_out(optout_url if optout_url is not None else store.url)
    asked = set(pids)
    for pid in sorted(gone & (asked | set(store.pids()))):
        rep.erased += store.erase(pid)
    rep.opted_out = len(asked & gone)
    todo = sorted(asked - gone)
    rows = read_lake(lake, todo, snapshot)
    for pid in todo:
        tables = rows.get(pid) or {}
        if not tables.get("patient"):
            rep.missing += 1
            continue
        try:
            doc = assemble(pid, snapshot, tables, derived.rows(pid) if derived is not None else None)
            errs = schema_errors(SCHEMA_NAME, doc)
            if errs:
                raise TwinError("; ".join(e.split(":")[0] for e in errs[:5]))  # paths only: no values in the log
            if store.put(doc, now) == "inserted":
                rep.inserted += 1
            else:
                rep.unchanged += 1
        except Exception as e:  # one bad patient never stops the build
            log.warning("twin: build failed for %s (%s)", pid, type(e).__name__)
            rep.failed.append(pid)
    return rep


def study_pids(orch_db: Any) -> list[str]:
    """The study patients: every pseudonym in a study's candidate pool or candidate registry (D-440 item 6)."""
    out: set[str] = set()
    rulesets = set(orch_db.pool_rulesets()) | {str(s["ruleset"]) for s in orch_db.candidate_summaries()}
    for rid in sorted(rulesets):
        out |= {str(r["pid"]) for r in orch_db.pool(rid)}
        out |= {str(r["pid"]) for r in orch_db.candidates(rid)}
    return sorted(out)


def after_ingest(orch_db: Any, lake: LakeReader, snapshot: str, now: str, url: str | None = None) -> BuildReport | None:
    """The build step of the night (D-440 item 6): after an ingest that passed, the study patients' twins from the
    snapshot it published. Never raises (the ingest itself has passed); None when it could not run."""
    try:
        from tb_common.derived_store import DerivedStore

        store = ProfileStore(url)
        derived = DerivedStore(url)
        try:
            rep = build(store, lake, study_pids(orch_db), snapshot=snapshot, now=now, derived=derived)
        finally:
            derived.close()
            store.close()
        log.info("twin: snapshot %s: %d new, %d unchanged, %d erased, %d failed", snapshot, rep.inserted,
                 rep.unchanged, rep.erased, len(rep.failed))  # fmt: skip
        return rep
    except Exception as exc:  # the follow-up must not turn a passed ingest into a failed one
        # a TwinError is this module's own sentence (a snapshot's name and a layout, never a patient): said whole
        log.error(
            "twin build after the ingest did not run: %s", exc if isinstance(exc, TwinError) else type(exc).__name__
        )
        return None


__all__ = [
    "BUILT",
    "LAYERS",
    "MIGRATIONS",
    "PROFILE",
    "RESEARCH_LAYERS",
    "BuildReport",
    "ProfileStore",
    "Twin",
    "TwinError",
    "after_ingest",
    "assemble",
    "build",
    "canonical",
    "content_sha",
    "for_role",
    "read_lake",
    "study_pids",
]
