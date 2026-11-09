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
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from lake.flatten import DEMOGRAPHIC, SCHEMAS
from tb_common.db import Database

from omop import vocab
from omop.schema import COUNTED

Row = dict[str, Any]
ORDER = "ORDER BY (r.source_kind = 'site'), r.source_row, r.part"
LIVE = "r.status NOT IN ('tombstoned', 'superseded')"
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


def _basis(basis: str | None, status: str) -> str | None:
    """The basis a site fact is listed with: the source's tag, moved on by a person's confirm / sign (D-135)."""
    if basis is None:
        return None
    return status if status in ("proposed", "confirmed", "signed", "derived") else basis


def export_rows(db: Database) -> dict[str, list[Row]]:
    with db.transaction() as tx:
        return _export(tx)


def _export(tx: Any) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {name: [] for name in SCHEMAS}
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
    for r in tx.fetchdicts(
        "SELECT p.person_id, p.birth_datetime, p.gender_source_value, d.death_date FROM person p "
        "LEFT JOIN death d USING (person_id) JOIN LATERAL (SELECT (r.source_kind = 'site') AS s, r.source_row "
        "FROM tb_record r WHERE r.cdm_table = 'person' AND r.record_id = p.person_id AND r.status <> 'tombstoned' "
        "ORDER BY 1, 2 LIMIT 1) o ON true ORDER BY o.s, o.source_row"
    ):
        row = {
            "pid": person[r["person_id"]],
            "birth_date": _day(r["birth_datetime"]),
            "sex": r["gender_source_value"],
            "deceased_date": r["death_date"],
        }
        for item in ("birth_date", "sex", "deceased_date"):
            got = conflicts.get((r["person_id"], item))
            if got:
                row[item] = None if got[0] == "open" else _typed("patient", item, got[1])
        out["patient"].append(row)
    # -- practitioner
    for r in tx.fetchdicts(
        f"SELECT r.record_id, r.extra FROM tb_record r WHERE r.cdm_table = 'provider' AND {LIVE} {ORDER}"
    ):
        out["practitioner"].append(_apply("practitioner", {"practitioner_id": provider[r["record_id"]]}, r["extra"]))
    # -- encounter
    for r in tx.fetchdicts(
        "SELECT r.source_record_id, r.extra, v.person_id, v.visit_start_datetime, v.care_site_id, v.provider_id, "
        f"v.visit_source_value FROM tb_record r JOIN visit_occurrence v ON v.visit_occurrence_id = r.record_id "
        f"WHERE r.cdm_table = 'visit_occurrence' AND {LIVE} {ORDER}"
    ):
        out["encounter"].append(
            _apply(
                "encounter",
                {
                    "eid": r["source_record_id"],
                    "pid": person.get(r["person_id"]),
                    "start": r["visit_start_datetime"],
                    "dept": site.get(r["care_site_id"]),
                    "practitioner_id": provider.get(r["provider_id"]),
                    "class": r["visit_source_value"],
                },
                r["extra"],
            )
        )
    # -- appointment
    for r in tx.fetchdicts(
        "SELECT r.source_record_id, r.extra, a.* FROM tb_record r JOIN tb_appointment a ON a.appointment_id = "
        f"r.record_id WHERE r.cdm_table = 'tb_appointment' AND {LIVE} {ORDER}"
    ):
        out["appointment"].append(
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
            )
        )
    facts: dict[str, list[Row]] = {"Condition": [], "MedicationRequest": [], "Observation": []}
    # -- condition
    for r in tx.fetchdicts(
        "SELECT r.source_record_id, r.extra, r.status, r.basis, c.person_id, c.condition_source_value, "
        "c.condition_source_concept_id, c.condition_start_datetime, c.condition_status_source_value, "
        "c.condition_status_concept_id, vr.source_record_id AS eid FROM tb_record r JOIN condition_occurrence c "
        "ON c.condition_occurrence_id = r.record_id LEFT JOIN tb_record vr ON vr.cdm_table = 'visit_occurrence' "
        f"AND vr.record_id = c.visit_occurrence_id WHERE r.cdm_table = 'condition_occurrence' AND {LIVE} "
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
        }
        if r["condition_status_concept_id"] == vocab.SUSPECTED and b != "proposed":
            facts["Condition"].append({**fact, "basis": "suspected"})  # D-142: listed, never coded
            continue
        if b is not None:
            facts["Condition"].append({**fact, "basis": b})
        if r["status"] in COUNTED:
            out["condition"].append(row)
    # -- observation: measurement rows (components included) and demographic facts (OMOP OBSERVATION)
    obs_rows = tx.fetchdicts(
        "SELECT r.source_record_id, r.part, r.extra, r.status, r.basis, r.source_kind, r.source_row, m.person_id, "
        "m.measurement_source_value AS code, m.measurement_source_concept_id AS src, m.measurement_datetime AS ts, "
        "m.value_as_number, m.unit_source_value, m.value_as_concept_id, m.operator_concept_id, "
        "m.value_source_value, false AS demographic FROM tb_record r JOIN measurement m "
        f"ON m.measurement_id = r.record_id WHERE r.cdm_table = 'measurement' AND {LIVE} AND r.status <> 'rejected' "
        "UNION ALL SELECT r.source_record_id, r.part, r.extra, r.status, r.basis, r.source_kind, r.source_row, "
        "o.person_id, o.observation_source_value, o.observation_source_concept_id, o.observation_datetime, "
        "o.value_as_number, o.unit_source_value, o.value_as_concept_id, NULL, o.value_source_value, true "
        "FROM tb_record r JOIN observation o ON o.observation_id = r.record_id WHERE r.cdm_table = 'observation' "
        f"AND {LIVE} AND r.status <> 'rejected' ORDER BY 6, 7, 2"
    )
    for r in obs_rows:
        r["source_kind"] = r["source_kind"] == "site"
    obs_rows.sort(key=lambda r: (r["source_kind"], r["source_row"], r["part"]))
    for r in obs_rows:
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
                }
            )
        if r["status"] in COUNTED and not demographic:
            out["observation"].append(row)
    # -- medication
    for r in tx.fetchdicts(
        "SELECT r.source_record_id, r.extra, r.status, r.basis, d.person_id, d.drug_source_value, "
        "d.drug_exposure_start_datetime, d.verbatim_end_date, d.sig FROM tb_record r JOIN drug_exposure d "
        f"ON d.drug_exposure_id = r.record_id WHERE r.cdm_table = 'drug_exposure' AND {LIVE} "
        f"AND r.status <> 'rejected' {ORDER}"
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
                }
            )
        if r["status"] in COUNTED:
            out["medication"].append(row)
    # -- procedure
    for r in tx.fetchdicts(
        "SELECT r.source_record_id, r.extra, p.person_id, p.procedure_source_value, p.procedure_source_concept_id, "
        "p.procedure_datetime FROM tb_record r JOIN procedure_occurrence p ON p.procedure_occurrence_id = "
        f"r.record_id WHERE r.cdm_table = 'procedure_occurrence' AND {LIVE} {ORDER}"
    ):
        out["procedure"].append(
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
            )
        )
    # -- report and document: NOTE
    for r in tx.fetchdicts(
        "SELECT r.resource_type, r.source_record_id, r.extra, n.person_id, n.note_datetime, n.note_title, "
        "n.note_text, n.note_source_value, vr.source_record_id AS eid FROM tb_record r JOIN note n "
        "ON n.note_id = r.record_id LEFT JOIN tb_record vr ON vr.cdm_table = 'visit_occurrence' "
        f"AND vr.record_id = n.visit_occurrence_id WHERE r.cdm_table = 'note' AND {LIVE} {ORDER}"
    ):
        pid = person.get(r["person_id"])
        if r["resource_type"] == "DiagnosticReport":
            out["report"].append(
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
                )
            )
        else:
            out["document"].append(
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
                )
            )
    # -- claim, consent (local tables)
    for r in tx.fetchdicts(
        "SELECT r.source_record_id, r.extra, c.* FROM tb_record r JOIN tb_claim c ON c.claim_id = r.record_id "
        f"WHERE r.cdm_table = 'tb_claim' AND {LIVE} {ORDER}"
    ):
        out["claim"].append(
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
            )
        )
    for r in tx.fetchdicts(
        "SELECT r.source_record_id, r.extra, c.* FROM tb_record r JOIN tb_consent c ON c.consent_id = r.record_id "
        f"WHERE r.cdm_table = 'tb_consent' AND {LIVE} {ORDER}"
    ):
        out["consent"].append(
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
            )
        )
    out["site_fact"] = [*facts["Condition"], *facts["MedicationRequest"], *facts["Observation"]]
    return out
