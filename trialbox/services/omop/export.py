"""The lake exported from OMOP (D-151): the same 13 tables, the same columns, the same rows as the flattener's.

    rows = export_rows(db)          # {"patient": [...], "condition": [...], ...}  in ``lake.flatten.SCHEMAS`` shape

The screening engine, FEAS, the cascade and every approved ruleset read the lake by these table and column names,
so nothing downstream changes (D-144: "the same table names, so the counts stay identical"). What the export reads:

* the standard tables for every value OMOP has a column for (source values, dates, numbers, the visit, provider
  and care site behind a fact); the code system comes back from the source concept's vocabulary;
* ``tb_record`` for the source id, the record status and the FHIR fields OMOP has no column for (``extra``);
* ``tb_conflict``: a patient item two sources disagree on reads as unknown while the conflict is open, and as the
  resolved value once a person has settled it (D-144: conflicts are recorded, unknown never excludes).

Which rows reach which table is the flattener's rule, written on the record status: a coded table admits
``coded``, ``confirmed``, ``signed`` and ``derived`` records; ``site_fact`` lists the site's facts with their basis
and the suspected diagnoses (D-135, D-142); a proposed fact never reaches a coded table; a ``rejected``,
``superseded`` or ``tombstoned`` record reaches none. Rows come out in the order the flattener gives (the hospital
feed first, then the site's inputs, each in file order), so even order-sensitive readers see the same lake.

A record's lake table is its resource type's, wherever OMOP put it: a condition, lab or procedure the loader routed
to OBSERVATION by its concept's domain (T-106b, STD-031) is read back from there. The row provenance columns
(DATA-010) come from the record's ``extra``, as the other FHIR fields OMOP has no column for.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from lake.flatten import DEMOGRAPHIC, PROVENANCE_COLS, SCHEMAS, sex_of
from tb_common.db import Database

from omop import vocab
from omop.schema import COUNTED

Row = dict[str, Any]
ORDER = "ORDER BY (r.source_kind = 'site'), r.source_row, r.part"
LIVE = "r.status NOT IN ('tombstoned', 'superseded') AND NOT (r.extra @> '{\"id_rule_review\": true}'::jsonb)"
_TYPES = {name: dict(cols) for name, cols in SCHEMAS.items()}


def _typed(table: str, col: str, v: Any) -> Any:
    if v is None:
        return None
    t = _TYPES[table][col]
    if t == "DATE":
        return date.fromisoformat(v) if isinstance(v, str) else v
    if t == "TIMESTAMP":
        return datetime.fromisoformat(v) if isinstance(v, str) else v
    if t == "DOUBLE":
        return float(v)
    if t == "BOOLEAN":
        return bool(v)
    return str(v)


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, Decimal | int | float) else None


def _day(v: datetime | None) -> date | None:
    return v.date() if isinstance(v, datetime) else v


def _apply(table: str, row: Row, extra: dict[str, Any]) -> Row:
    """The FHIR fields kept in ``extra`` (named by the lake column they restore) override the OMOP reading."""
    for k, v in extra.items():
        if k in _TYPES[table]:
            row[k] = _typed(table, k, v)
    return {c: row.get(c) for c in _TYPES[table]}


def _prov(extra: dict[str, Any]) -> Row:
    """The provenance columns a record keeps in ``extra`` (none: all None)."""
    return {c: _typed("site_fact", c, extra.get(c)) for c in PROVENANCE_COLS}


def _basis(basis: str | None, status: str) -> str | None:
    """The basis a site fact is listed with: the source's tag, moved on by a person's confirm / sign (D-135)."""
    if basis is None:
        return None
    return status if status in ("proposed", "confirmed", "signed", "derived") else basis


class _Discard(Exception):
    """Ends the transaction of an export "as of": everything it changed is rolled back."""


def export_rows(db: Database, as_of: datetime | None = None) -> dict[str, list[Row]]:
    """The lake rows the store holds now, or as it held them at ``as_of`` (T-202, D-384; an aware instant).

    An export "as of" winds the store back inside one transaction that is always rolled back, under the loader's
    lock (a load waits for it, never the other way round): every record changed after ``as_of`` gets its before-image
    back (``tb_record_event.record_before`` and ``before``), a record first loaded after it is set aside, conflicts
    opened, resolved or withdrawn after it read as they did then, and the merged person rows are derived again from
    the records of that time. A patient who is opted out now is never brought back: after the wind-back their
    records are tombstoned again, the consent statements excepted (T-728, D-493). Nothing is written. The clinical
    content (which records, their values, status, basis
    and conflicts) is the content of that time; an unchanged record's row provenance and file position are those of
    the last load that carried it (a new night alone is no event, D-384). An instant before a change whose record
    before-image was never kept (an event written before migration 6) is refused, never guessed."""
    if as_of is None:
        with db.transaction() as tx:
            return _export(tx)
    if as_of.tzinfo is None:
        raise ValueError("an export as of a time needs an aware instant (the zone is never guessed, D-315)")
    out: dict[str, list[Row]] = {}
    try:
        with db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext('trialbox-omop-load'))")
            _wind_back(tx, as_of)
            _keep_withheld_out(tx)
            out = _export(tx)
            raise _Discard
    except _Discard:
        pass
    return out


class Spooled:
    """One table of a spooled export, its rows read back line by line each time it is iterated (T-702, D-754)."""

    def __init__(self, path: Path, keep: object = None) -> None:
        self.path = path
        self._keep = keep  # the spool folder's owner: the folder goes when its last table is dropped

    def __iter__(self) -> Iterator[Row]:
        from omop.load import _decoded

        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line, object_hook=_decoded)


class _Folder:
    """A spool folder removed once nothing holds it (every :class:`Spooled` of it garbage)."""

    def __init__(self, path: Path) -> None:
        import shutil
        import weakref

        weakref.finalize(self, shutil.rmtree, path, True)


def export_spool(db: Database, folder: Path, remove_when_done: bool = False) -> dict[str, Spooled]:
    """:func:`export_rows` (the store now) written table by table into ``folder`` as it is read, one line a row with
    each value's type (a date, a datetime, a decimal), and given back as re-readable streams: the export is never
    held whole (T-702, D-754; scale review F-17). The lake writes its Parquet from the streams; ``folder`` is the
    caller's to delete, or with ``remove_when_done`` removed once the streams are dropped."""
    from omop.load import _encoded

    folder.mkdir(parents=True, exist_ok=True)
    files = {name: (folder / f"{name}.jsonl").open("w", encoding="utf-8") for name in SCHEMAS}
    try:
        with db.transaction() as tx:
            _emit_all(tx, lambda t, row: files[t].write(json.dumps(row, default=_encoded, ensure_ascii=False) + "\n"))
    finally:
        for fh in files.values():
            fh.close()
    keep = _Folder(folder) if remove_when_done else None
    return {name: Spooled(folder / f"{name}.jsonl", keep) for name in SCHEMAS}


def _keep_withheld_out(tx: Any) -> None:
    """T-728 (D-493; lifecycle review F-9): the wind-back gave a patient who opted out after ``as_of`` their records
    back (the opt-out is a tombstone with its before-images kept). Every patient withheld now (``tb_withheld`` and
    the opt-out register) is
    tombstoned again in the wound-back store, by the opt-out worker's own code, whatever the order of the later
    events was; the consent statements stay. Inside the caller's transaction, which is rolled back."""
    from tb_common.optout import register_now  # the one door outside a job (T-708, D-477)

    from omop.load import withhold_persons

    # review L1: ``tb_withheld`` is the opt-out worker's copy and lags the register by a tick; the register itself
    # is read too (empty when no trial database is configured; a register that does not answer raises)
    pids = sorted({str(r[0]) for r in tx.fetchall("SELECT pid FROM tb_withheld")} | set(register_now()))
    if pids:
        withhold_persons(tx, pids, "as-of export")


def _wind_back(tx: Any, at: datetime) -> None:
    """The store as it was at ``at``, inside the caller's transaction (which is rolled back)."""
    from omop.load import ID_COL, LoadReport, _derive
    from omop.schema import OmopError

    lost = tx.fetchval(
        "SELECT count(*) FROM tb_record_event WHERE at > ? AND record_before IS NULL AND event <> 'insert'", (at,)
    )
    # the review of D-1031: an image blanked at retention can no longer bring its row back. A patient withheld now
    # is kept out anyway; for one released since (a lift), an instant before a blanked image is refused, never
    # guessed (the record's history would be dropped without a word)
    from tb_common.optout import register_now

    withheld = sorted({str(r[0]) for r in tx.fetchall("SELECT pid FROM tb_withheld")} | set(register_now()))
    held = [int(r[0]) for r in tx.fetchall(
        "SELECT omop_id FROM tb_id_map WHERE id_kind = 'person' AND source_id = ANY(?)", (withheld,))]  # fmt: skip
    blanked = tx.fetchval(
        "SELECT count(*) FROM tb_record_event e JOIN tb_record r USING (record_key) WHERE e.at > ? AND "
        "(e.record_before ->> 'blanked') IS NOT NULL AND NOT (coalesce(r.person_id = ANY(?), false) OR "
        "(r.cdm_table = 'person' AND r.record_id = ANY(?)))",
        (at, held, held),
    )
    if blanked:
        raise OmopError(
            f"the store cannot be exported as of {at.isoformat()}: {blanked} later changes of a patient released "
            "since had their before-images blanked at retention (D-1031)"
        )
    if lost:
        raise OmopError(
            f"the store cannot be exported as of {at.isoformat()}: {lost} later changes have no record before-image "
            "(written before migration 6, T-202)"
        )
    first = tx.fetchall(
        "SELECT DISTINCT ON (e.record_key) e.record_key, e.event, e.record_before::text, r.cdm_table, r.record_id, "
        "r.status FROM tb_record_event e JOIN tb_record r USING (record_key) WHERE e.at > ? "
        "ORDER BY e.record_key, e.event_id",
        (at,),
    )
    if not first:
        return
    cdm_first = {
        int(k): (str(ev), b)
        for k, ev, b in tx.fetchall(
            "SELECT DISTINCT ON (record_key) record_key, event, before::text FROM tb_record_event WHERE at > ? "
            "AND event <> 'status' ORDER BY record_key, event_id",
            (at,),
        )
    }
    deletes: dict[str, list[int]] = defaultdict(list)
    inserts: dict[str, list[str]] = defaultdict(list)
    gone: list[int] = []
    olds: list[tuple[int, str]] = []
    persons: set[int] = set()
    for key, event, rec_before, table, rid, status in first:
        old = json.loads(rec_before) if rec_before else None
        if table == "person" and rid is not None:
            persons.add(int(rid))
        if old and old.get("cdm_table") == "person" and old.get("record_id") is not None:
            persons.add(int(old["record_id"]))
        cdm = cdm_first.get(int(key))
        if cdm is not None:  # the record's OMOP row changed after ``at``: its row of then comes back
            if table in ID_COL and rid is not None and status != "tombstoned":
                deletes[str(table)].append(int(rid))
            if cdm[0] != "insert" and cdm[1] and old and old.get("cdm_table") in ID_COL:
                inserts[str(old["cdm_table"])].append(cdm[1])
        if event == "insert":
            gone.append(int(key))  # not loaded yet at ``at``: set aside (events keep the row, so it stays)
        elif old is not None:
            olds.append((int(key), rec_before))
    for table, ids in deletes.items():
        tx.execute(f"DELETE FROM {table} WHERE {ID_COL[table]} = ANY(?)", (ids,))
    for table, rows in inserts.items():
        tx.execute(
            f"INSERT INTO {table} SELECT * FROM jsonb_populate_recordset(NULL::{table}, ?::jsonb)",
            ("[" + ",".join(rows) + "]",),
        )
    if gone:
        tx.execute("UPDATE tb_record SET status = 'tombstoned' WHERE record_key = ANY(?)", (gone,))
    if olds:
        cols = [
            str(c)
            for (c,) in tx.fetchall(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = 'tb_record' AND column_name <> 'record_key' ORDER BY ordinal_position"
            )
        ]
        tx.execute("CREATE TEMP TABLE tb_asof_tmp (record_key BIGINT, before JSONB) ON COMMIT DROP")
        tx.copy_rows("tb_asof_tmp", ["record_key", "before"], olds)
        sets = ", ".join(f"{c} = b.{c}" for c in cols)
        tx.execute(
            f"UPDATE tb_record r SET {sets} FROM tb_asof_tmp t, jsonb_populate_record(NULL::tb_record, t.before) b "
            "WHERE r.record_key = t.record_key"
        )
    # conflicts as they stood: opened after ``at`` not yet there; resolved or withdrawn after it still open
    later = "SELECT batch FROM tb_load WHERE started_at > ?"
    tx.execute("DELETE FROM tb_conflict WHERE detected_at > ?", (at,))
    tx.execute(
        "UPDATE tb_conflict SET state = CASE WHEN resolved_at IS NOT NULL AND resolved_at <= ? THEN 'resolved' "
        f"ELSE 'open' END, closed_batch = NULL WHERE state = 'withdrawn' AND closed_batch IN ({later})",
        (at, at),
    )
    tx.execute(
        "UPDATE tb_conflict SET state = 'open', resolved_value = NULL, resolution = NULL, reason = NULL, "
        "authority = NULL, resolved_by = NULL, resolved_at = NULL WHERE state = 'resolved' AND resolved_at > ?",
        (at,),
    )
    if persons:  # the merged person and death rows of then (they are derived, not evented)
        batch = tx.fetchval(
            "SELECT batch FROM tb_load WHERE source_kind = 'feed' AND started_at <= ? ORDER BY started_at DESC LIMIT 1",
            (at,),
        )
        _derive(tx, persons, set(), str(batch or at.date().isoformat()), LoadReport("feed", "as-of"), "")


def _export(tx: Any) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {name: [] for name in SCHEMAS}
    _emit_all(tx, lambda table, row: out[table].append(row))
    return out


def _emit_all(tx: Any, emit: Callable[[str, Row], object]) -> None:
    """Every lake row of the store, table by table, each passed to ``emit`` as it is read (T-702, D-754): the
    store's rows come through a server-side cursor a batch at a time, never a table whole."""
    ids: dict[str, dict[int, str]] = defaultdict(dict)
    for kind, oid, sid in tx.fetchall("SELECT id_kind, omop_id, source_id FROM tb_id_map"):
        ids[str(kind)][int(oid)] = str(sid)
    person, provider, site = ids["person"], ids["provider"], ids["care_site"]
    conflicts: dict[tuple[int, str], tuple[str, str | None]] = {}
    for pid, item, state, value in tx.fetchall(
        "SELECT person_id, item, state, resolved_value FROM tb_conflict WHERE state <> 'withdrawn' ORDER BY conflict_id"
    ):
        conflicts[(int(pid), str(item))] = (str(state), value)
    systems = dict(
        tx.fetchall(
            "SELECT c.concept_id, v.vocabulary_reference FROM concept c JOIN vocabulary v USING (vocabulary_id) "
            "WHERE c.concept_id >= 2000000000"
        )
    )
    codes = dict(tx.fetchall("SELECT concept_id, concept_code FROM concept WHERE concept_id >= 2000000000"))

    def system(cid: int | None) -> str | None:
        return systems.get(cid) if cid else None

    # -- patient: the merged sources, an item in open conflict unknown
    for r in tx.iterdicts(
        "SELECT p.person_id, p.birth_datetime, p.gender_source_value, d.death_date, d.death_type_concept_id, "
        "o.extra FROM person p "
        "LEFT JOIN death d USING (person_id) JOIN LATERAL (SELECT (r.source_kind = 'site') AS s, r.source_row, "
        "r.extra FROM tb_record r WHERE r.cdm_table = 'person' AND r.record_id = p.person_id "
        # the text of LIVE written out, so that this statement stays a constant (the SQL-from-strings ratchet)
        "AND r.status NOT IN ('tombstoned', 'superseded') "
        "AND NOT (r.extra @> '{\"id_rule_review\": true}'::jsonb) "
        "ORDER BY 1, 2 LIMIT 1) o ON true ORDER BY o.s, o.source_row"
    ):
        row = {
            "pid": person[r["person_id"]],
            "birth_date": _day(r["birth_datetime"]),
            "sex": sex_of(r["gender_source_value"]),
            # T-616 (STD-013, D-400): a death recorded without a date is deceased with no date (the imputed night
            # stays in OMOP only)
            "deceased_date": None if r["death_type_concept_id"] == vocab.DEATH_DATE_IMPUTED else r["death_date"],
            "deceased": True if r["death_date"] is not None else None,
            **_prov(r["extra"]),  # the first record's (the hospital's), as the flattener's merge keeps
        }
        for item in ("birth_date", "sex", "deceased_date"):
            got = conflicts.get((r["person_id"], item))
            if got:
                row[item] = None if got[0] == "open" else _typed("patient", item, got[1])
        emit("patient", row)
    # -- practitioner
    for r in tx.iterdicts(
        f"SELECT r.record_id, r.extra FROM tb_record r WHERE r.cdm_table = 'provider' AND {LIVE} {ORDER}"
    ):
        emit("practitioner", _apply("practitioner", {"practitioner_id": provider[r["record_id"]]}, r["extra"]))
    # -- encounter
    for r in tx.iterdicts(
        "SELECT r.source_record_id, r.extra, v.person_id, v.visit_start_datetime, v.care_site_id, v.provider_id, "
        "v.visit_source_value, v.visit_end_datetime FROM tb_record r JOIN visit_occurrence v "
        "ON v.visit_occurrence_id = r.record_id "
        f"WHERE r.cdm_table = 'visit_occurrence' AND {LIVE} AND r.status <> 'rejected' {ORDER}"
    ):
        emit(
            "encounter",
            _apply(
                "encounter",
                {
                    "eid": r["source_record_id"],
                    "pid": person.get(r["person_id"]),
                    "start": r["visit_start_datetime"],
                    "dept": site.get(r["care_site_id"]),
                    "practitioner_id": provider.get(r["provider_id"]),
                    "class": r["visit_source_value"],
                    "end": r["visit_end_datetime"],
                },
                r["extra"],
            ),
        )
    # -- appointment
    for r in tx.iterdicts(
        "SELECT r.source_record_id, r.extra, a.* FROM tb_record r JOIN tb_appointment a ON a.appointment_id = "
        f"r.record_id WHERE r.cdm_table = 'tb_appointment' AND {LIVE} {ORDER}"
    ):
        emit(
            "appointment",
            _apply(
                "appointment",
                {
                    "aid": r["source_record_id"],
                    "pid": person.get(r["person_id"]),
                    "start": r["appointment_datetime"],
                    "practitioner_id": provider.get(r["provider_id"]),
                    "dept": site.get(r["care_site_id"]),
                    "status": r["status"],
                },
                r["extra"],
            ),
        )
    facts: dict[str, list[Row]] = {"Condition": [], "MedicationRequest": [], "Observation": []}
    # -- condition
    for r in tx.iterdicts(
        "SELECT r.source_record_id, r.extra, r.status, r.basis, c.person_id, c.condition_source_value, "
        "c.condition_source_concept_id, c.condition_start_datetime, c.condition_status_source_value, "
        "c.condition_status_concept_id, vr.source_record_id AS eid FROM tb_record r JOIN (SELECT "
        "condition_occurrence_id AS rid, person_id, condition_source_value, condition_source_concept_id, "
        "condition_start_datetime, condition_status_source_value, condition_status_concept_id, visit_occurrence_id "
        "FROM condition_occurrence UNION ALL SELECT observation_id, person_id, observation_source_value, "
        "observation_source_concept_id, observation_datetime, qualifier_source_value, qualifier_concept_id, "
        "visit_occurrence_id FROM observation) c ON c.rid = r.record_id LEFT JOIN tb_record vr "
        "ON vr.cdm_table = 'visit_occurrence' AND vr.record_id = c.visit_occurrence_id WHERE r.resource_type = "
        f"'Condition' AND r.cdm_table IN ('condition_occurrence', 'observation') AND {LIVE} "
        f"AND r.status <> 'rejected' {ORDER}"
    ):
        onset = _day(r["condition_start_datetime"])
        row = _apply(
            "condition",
            {
                "cid": r["source_record_id"],
                "pid": person.get(r["person_id"]),
                "code": r["condition_source_value"],
                "system": system(r["condition_source_concept_id"]),
                "onset": onset,
                "recorded": onset,
                "status": r["condition_status_source_value"],
                "eid": r["eid"],
            },
            r["extra"],
        )
        b = _basis(r["basis"], r["status"])
        fact = {
            "fid": row["cid"],
            "pid": row["pid"],
            "domain": "condition",
            "code": row["code"],
            "system": row["system"],
            "d": row["onset"] or row["recorded"],
            "value_num": None,
            "unit": None,
            "value_text": None,
            **_prov(r["extra"]),
        }
        if r["condition_status_concept_id"] == vocab.SUSPECTED and b != "proposed":
            facts["Condition"].append({**fact, "basis": "suspected"})  # D-142: listed, never coded
            continue
        if b is not None:
            facts["Condition"].append({**fact, "basis": b})
        if r["status"] in COUNTED:
            emit("condition", row)
    # -- observation: measurement rows (components included) and demographic facts (OMOP OBSERVATION)
    obs_rows = tx.iterdicts(
        "SELECT * FROM (SELECT r.source_record_id, r.part, r.extra, r.status, r.basis, r.source_kind, r.source_row, "
        "m.person_id, "
        "m.measurement_source_value AS code, m.measurement_source_concept_id AS src, m.measurement_datetime AS ts, "
        "m.value_as_number, m.unit_source_value, m.value_as_concept_id, m.operator_concept_id, "
        "m.value_source_value, false AS demographic FROM tb_record r JOIN measurement m "
        f"ON m.measurement_id = r.record_id WHERE r.cdm_table = 'measurement' AND {LIVE} AND r.status <> 'rejected' "
        "UNION ALL SELECT r.source_record_id, r.part, r.extra, r.status, r.basis, r.source_kind, r.source_row, "
        "o.person_id, o.observation_source_value, o.observation_source_concept_id, o.observation_datetime, "
        "o.value_as_number, o.unit_source_value, o.value_as_concept_id, NULL, o.value_source_value, "
        "coalesce((r.extra->>'demographic')::boolean, false) FROM tb_record r JOIN observation o "
        "ON o.observation_id = r.record_id WHERE r.cdm_table = 'observation' AND r.resource_type = 'Observation' "
        # the hospital's rows, then the site's (D-135), by file position and part: in SQL, so the rows stream
        f"AND {LIVE} AND r.status <> 'rejected') u ORDER BY (u.source_kind = 'site'), u.source_row, u.part"
    )
    for r in obs_rows:
        r["source_kind"] = r["source_kind"] == "site"
        vcode = codes.get(r["value_as_concept_id"]) if r["value_as_concept_id"] else None
        code = r["code"]
        row = _apply(
            "observation",
            {
                "oid": r["source_record_id"],
                "pid": person.get(r["person_id"]),
                "code": code,
                "system": system(r["src"]),
                "effective": r["ts"],
                "value_num": _num(r["value_as_number"]),
                "unit": r["unit_source_value"],
                "value_code": vcode,
                "value_cmp": vocab.OPERATOR_CODE.get(r["operator_concept_id"] or 0),
                "category": None,
                "local_code": None,
            },
            r["extra"],
        )
        if r["part"]:
            row["oid"] = f"{r['source_record_id']}.{row['code']}"  # the flattener's component id
        b = _basis(r["basis"], r["status"])
        demographic = bool(r["demographic"])
        if r["part"] == 0 and (b is not None or demographic):
            text = r["extra"].get("value_text", r["value_source_value"])
            facts["Observation"].append(
                {
                    "fid": r["source_record_id"],
                    "pid": row["pid"],
                    "domain": "demographic" if row["system"] == DEMOGRAPHIC else "observation",
                    "code": row["code"],
                    "system": row["system"],
                    "d": None if row["system"] == DEMOGRAPHIC else row["effective"],
                    "value_num": row["value_num"],
                    "unit": row["unit"],
                    "value_text": text,
                    "basis": b or "coded",
                    **_prov(r["extra"]),
                }
            )
        if r["status"] in COUNTED and not demographic:
            emit("observation", row)
    # -- medication
    for r in tx.iterdicts(
        "SELECT r.source_record_id, r.extra, r.status, r.basis, d.person_id, d.drug_source_value, "
        "d.drug_exposure_start_datetime, d.verbatim_end_date, d.sig FROM tb_record r JOIN drug_exposure d "
        f"ON d.drug_exposure_id = r.record_id WHERE r.cdm_table = 'drug_exposure' AND {LIVE} "
        # T-616: orders, then statements (the flattener's order), each in file order
        f"AND r.status <> 'rejected' {ORDER.replace('ORDER BY ', 'ORDER BY r.resource_type, ', 1)}"
    ):
        x = r["extra"]
        start = _day(r["drug_exposure_start_datetime"])
        atc = r["drug_source_value"] if x.get("atc_src") else None
        nhi = None if x.get("atc_src") else r["drug_source_value"]
        row = _apply(
            "medication",
            {
                "mid": r["source_record_id"],
                "pid": person.get(r["person_id"]),
                "nhi_code": nhi,
                "atc": atc,
                "authored": start,
                "start": start,
                "end": r["verbatim_end_date"],
                "status": None,
                "name": None,
                "dose": r["sig"],
            },
            x,
        )
        b = _basis(r["basis"], r["status"])
        if b is not None:
            facts["MedicationRequest"].append(
                {
                    "fid": row["mid"],
                    "pid": row["pid"],
                    "domain": "medication",
                    "code": row["atc"] or row["nhi_code"],
                    "system": "atc" if row["atc"] else None,
                    "d": row["authored"],
                    "value_num": None,
                    "unit": None,
                    "value_text": row["name"],
                    "basis": b,
                    **_prov(x),
                }
            )
        if r["status"] in COUNTED:
            emit("medication", row)
    # -- procedure
    for r in tx.iterdicts(
        "SELECT r.source_record_id, r.extra, p.person_id, p.procedure_source_value, p.procedure_source_concept_id, "
        "p.procedure_datetime FROM tb_record r JOIN (SELECT procedure_occurrence_id AS rid, person_id, "
        "procedure_source_value, procedure_source_concept_id, procedure_datetime FROM procedure_occurrence UNION ALL "
        "SELECT observation_id, person_id, observation_source_value, observation_source_concept_id, "
        "observation_datetime FROM observation) p ON p.rid = r.record_id WHERE r.resource_type = 'Procedure' "
        f"AND r.cdm_table IN ('procedure_occurrence', 'observation') AND {LIVE} AND r.status <> 'rejected' {ORDER}"
    ):
        emit(
            "procedure",
            _apply(
                "procedure",
                {
                    "prid": r["source_record_id"],
                    "pid": person.get(r["person_id"]),
                    "code": r["procedure_source_value"],
                    "system": system(r["procedure_source_concept_id"]),
                    "performed": _day(r["procedure_datetime"]),
                },
                r["extra"],
            ),
        )
    # -- report and document: NOTE
    for r in tx.iterdicts(
        "SELECT r.resource_type, r.source_record_id, r.extra, n.person_id, n.note_datetime, n.note_title, "
        "n.note_text, n.note_source_value, vr.source_record_id AS eid FROM tb_record r JOIN note n "
        "ON n.note_id = r.record_id LEFT JOIN tb_record vr ON vr.cdm_table = 'visit_occurrence' "
        f"AND vr.record_id = n.visit_occurrence_id WHERE r.cdm_table = 'note' AND {LIVE} "
        f"AND r.status <> 'rejected' {ORDER}"
    ):
        pid = person.get(r["person_id"])
        if r["resource_type"] == "DiagnosticReport":
            emit(
                "report",
                _apply(
                    "report",
                    {
                        "rid": r["source_record_id"],
                        "pid": pid,
                        "code": r["note_source_value"],
                        "system": None,
                        "effective": _day(r["note_datetime"]),
                        "conclusion": r["note_text"],
                    },
                    r["extra"],
                ),
            )
        else:
            emit(
                "document",
                _apply(
                    "document",
                    {
                        "did": r["source_record_id"],
                        "pid": pid,
                        "date": r["note_datetime"],
                        "type": r["note_title"],
                        "eid": r["eid"],
                        "text": r["note_text"],
                    },
                    r["extra"],
                ),
            )
    # -- claim, consent (local tables)
    for r in tx.iterdicts(
        "SELECT r.source_record_id, r.extra, c.* FROM tb_record r JOIN tb_claim c ON c.claim_id = r.record_id "
        f"WHERE r.cdm_table = 'tb_claim' AND {LIVE} {ORDER}"
    ):
        emit(
            "claim",
            _apply(
                "claim",
                {
                    "kid": r["source_record_id"],
                    "pid": person.get(r["person_id"]),
                    "created": r["created"],
                    "product": r["product"],
                    "outcome": r["outcome"],
                    "approval_start": r["approval_start"],
                    "approval_end": r["approval_end"],
                },
                r["extra"],
            ),
        )
    for r in tx.iterdicts(
        "SELECT r.source_record_id, r.extra, c.* FROM tb_record r JOIN tb_consent c ON c.consent_id = r.record_id "
        f"WHERE r.cdm_table = 'tb_consent' AND {LIVE} {ORDER}"
    ):
        emit(
            "consent",
            _apply(
                "consent",
                {
                    "consid": r["source_record_id"],
                    "pid": person.get(r["person_id"]),
                    "status": r["status"],
                    "contact_ok": r["contact_ok"],
                    "date": r["consent_date"],
                },
                r["extra"],
            ),
        )
    for fact in [*facts["Condition"], *facts["MedicationRequest"], *facts["Observation"]]:
        emit("site_fact", fact)
