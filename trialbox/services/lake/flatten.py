"""Flatten FHIR NDJSON into the lake tables of SPEC §3.2 (local-time dates/timestamps in the hospital zone)."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from tb_common import labvalue

Resource = dict[str, Any]
Row = dict[str, Any]

LOINC = "http://loinc.org"
# D-135 (step 5b): facts from the site's own inputs carry their basis as a meta tag. A *proposed* fact (read by the
# model from a chart, not yet checked by a person) never reaches the coded tables: it goes to ``site_fact`` only, so
# no compiled criterion can count it as met or let it exclude. A *confirmed* fact goes to the coded table like any
# coded record and is also listed in ``site_fact`` (how much of a count rests on confirmed facts). Demographic facts
# from a chart are observations in DEMOGRAPHIC, listed in ``site_fact`` only (the patient row carries the value once
# it is confirmed). A suspected diagnosis (D-142) is listed the same way, with basis ``suspected``.
BASIS = "urn:trialbox:basis"
DEMOGRAPHIC = "urn:trialbox:demographic"
# T-106b (DATA-010): row provenance. The adapter's mapper stamps every resource it makes from a source row with
# ``meta.source`` (``<site>/<source table>#<row hash>``, the hash keyed with the site key), ``meta.lastUpdated`` (the
# night it was ingested) and a ``meta.tag`` of this system naming the mapping version; every lake row carries them
# as the four :data:`PROVENANCE` columns (none for a resource no mapping made: a FHIR bulk feed, a site input).
MAPPING_VERSION = "urn:trialbox:mapping-version"
PROVENANCE: list[tuple[str, str]] = [
    ("src_table", "VARCHAR"),
    ("src_row_hash", "VARCHAR"),
    ("ingested_at", "TIMESTAMP"),
    ("mapping_version", "VARCHAR"),
]
PROVENANCE_COLS = tuple(c for c, _ in PROVENANCE)

# T-600 (FR-DEID-01, D-337): the columns that hold free text as the hospital wrote it, names, phone numbers and chart
# numbers included. They stay in the lake under the ``phi`` label only: the chunker, the full-text index and the
# embedder read them through ``tb_common.phi_guard.mask_note`` (``lake.store.Lake.rebuild``), never as they are.
PHI_COLUMNS: dict[str, tuple[str, ...]] = {"document": ("text",)}

SCHEMAS: dict[str, list[tuple[str, str]]] = {
    # T-616 (STD-013, D-400): ``deceased`` is true when the record says the patient died, with a date or without
    # one (``deceasedBoolean``, SS-MIX2 PID-30); the base cohort leaves out a deceased patient with no date at every
    # index date. Never false: a record that says "not deceased" is no evidence, read as unknown (None)
    "patient": [
        ("pid", "VARCHAR"),
        ("birth_date", "DATE"),
        ("sex", "VARCHAR"),
        ("deceased_date", "DATE"),
        ("deceased", "BOOLEAN"),
    ],
    "practitioner": [("practitioner_id", "VARCHAR"), ("staff_id", "VARCHAR"), ("name", "VARCHAR")],
    "encounter": [
        ("eid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("start", "TIMESTAMP"),
        ("dept", "VARCHAR"),
        ("practitioner_id", "VARCHAR"),
        ("class", "VARCHAR"),
        # T-106b (STD-018): the visit's end (``period.end``; none while the patient is still in) and FHIR status
        ("end", "TIMESTAMP"),
        ("status", "VARCHAR"),
    ],
    "appointment": [
        ("aid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("start", "TIMESTAMP"),
        ("practitioner_id", "VARCHAR"),
        ("dept", "VARCHAR"),
        ("status", "VARCHAR"),
    ],
    "condition": [
        ("cid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("code", "VARCHAR"),
        ("system", "VARCHAR"),
        ("onset", "DATE"),
        ("recorded", "DATE"),
        ("status", "VARCHAR"),
        ("eid", "VARCHAR"),
    ],
    "observation": [
        ("oid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("code", "VARCHAR"),
        ("system", "VARCHAR"),
        ("effective", "TIMESTAMP"),
        ("value_num", "DOUBLE"),
        ("unit", "VARCHAR"),
        ("value_code", "VARCHAR"),
        ("category", "VARCHAR"),
        ("local_code", "VARCHAR"),
        # D-142: a censored result ("<0.3", Quantity.comparator): value_num is the bound, value_cmp says which side
        ("value_cmp", "VARCHAR"),
    ],
    "medication": [
        ("mid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("nhi_code", "VARCHAR"),
        ("atc", "VARCHAR"),
        ("authored", "DATE"),
        ("start", "DATE"),
        ("end", "DATE"),
        ("status", "VARCHAR"),
        ("name", "VARCHAR"),
        ("dose", "VARCHAR"),
    ],
    "procedure": [
        ("prid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("code", "VARCHAR"),
        ("system", "VARCHAR"),
        ("performed", "DATE"),
    ],
    "report": [
        ("rid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("code", "VARCHAR"),
        ("system", "VARCHAR"),
        ("effective", "DATE"),
        ("conclusion", "VARCHAR"),
    ],
    "document": [
        ("did", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("date", "TIMESTAMP"),
        ("type", "VARCHAR"),
        ("eid", "VARCHAR"),
        ("text", "VARCHAR"),
    ],
    "claim": [
        ("kid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("created", "DATE"),
        ("product", "VARCHAR"),
        ("outcome", "VARCHAR"),
        ("approval_start", "DATE"),
        ("approval_end", "DATE"),
    ],
    # D-135: the site's own facts with their basis (proposed: listed here only; confirmed: also in the coded table)
    "site_fact": [
        ("fid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("domain", "VARCHAR"),
        ("code", "VARCHAR"),
        ("system", "VARCHAR"),
        ("d", "DATE"),
        ("value_num", "DOUBLE"),
        ("unit", "VARCHAR"),
        ("value_text", "VARCHAR"),
        ("basis", "VARCHAR"),
    ],
    # research-contact consent from the site registry (FHIR Consent, scope research; COHORT n_contactable, D-72)
    "consent": [
        ("consid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("status", "VARCHAR"),
        ("contact_ok", "BOOLEAN"),
        ("date", "DATE"),
    ],
}
for _cols in SCHEMAS.values():  # every lake row says where it came from (DATA-010)
    _cols.extend(PROVENANCE)


# FHIR Condition.verificationStatus: a suspected diagnosis (SS-MIX2 PRB-13 疑い, a provisional or differential
# diagnosis from any FHIR source) goes to ``site_fact`` with basis ``suspected``, never to ``condition`` (D-142)
SUSPECTED = frozenset({"provisional", "differential", "unconfirmed"})
NOT_PRESENT = frozenset({"refuted", "entered-in-error"})


# D-275 (review S-4): a record in one of these states is not a fact. It was written in error, called off, never
# carried out or not yet real, so it reaches no lake table (and no ``site_fact``): it can neither meet a criterion
# nor exclude a patient. A stopped or completed order, a preliminary or amended result still count. The list for
# orders is the one the eCRF pre-fill uses (``edc.prefill.VOID_STATUS``, D-162).
VOID: dict[str, frozenset[str]] = {
    "Observation": frozenset({"entered-in-error", "cancelled", "registered"}),
    "MedicationRequest": frozenset({"entered-in-error", "cancelled", "draft", "not-taken"}),
    "MedicationStatement": frozenset({"entered-in-error", "not-taken", "intended"}),
    "Procedure": frozenset({"entered-in-error", "not-done", "preparation"}),
    "DiagnosticReport": frozenset({"entered-in-error", "cancelled"}),
    "DocumentReference": frozenset({"entered-in-error"}),
    "Encounter": frozenset({"entered-in-error", "cancelled"}),
}
# D-275 (review F1, F3): a status that is a fact of unknown standing. A result not yet final (``preliminary``) or of
# a status nobody can read (``unknown``), an order of an unknown status: the record is kept, but it decides nothing.
# A result keeps no usable value (unknown, as a text result, D-142); an order keeps no date (it cannot be placed in
# a window: unknown, as an undated order). A source that records no status at all is not this: its mapping tags the
# resource ``not-recorded`` and the record counts as it always did.
UNCERTAIN: dict[str, frozenset[str]] = {
    "Observation": frozenset({"preliminary", "unknown"}),
    "MedicationRequest": frozenset({"unknown"}),
    "MedicationStatement": frozenset({"unknown"}),
}
STATUS_SOURCE = "urn:trialbox:status-source"
NOT_RECORDED = "not-recorded"
# D-275 (review S-5): the two values a sex criterion and a sex-dependent formula can use. ``other`` and ``unknown``
# (FHIR administrative gender) are kept as no value: unknown, never "not female"
SEXES = ("male", "female")


def void(rtype: str, r: Resource) -> bool:
    """The record's own status says it is not a fact (:data:`VOID`)."""
    states = VOID.get(rtype)
    if not states:
        return False
    if str(r.get("status") or "").strip().lower() in states:
        return True
    return rtype == "DocumentReference" and str(r.get("docStatus") or "").strip().lower() in states


def uncertain(rtype: str, r: Resource) -> bool:
    """The record's status says neither "a fact" nor "not a fact" (:data:`UNCERTAIN`), and the source did record one."""
    if str(r.get("status") or "").strip().lower() not in UNCERTAIN.get(rtype, frozenset()):
        return False
    tags = (r.get("meta") or {}).get("tag") or []
    return not any(t.get("system") == STATUS_SOURCE and t.get("code") == NOT_RECORDED for t in tags)


def sex_of(value: Any) -> str | None:
    s = str(value or "").strip().lower()
    return s if s in SEXES else None


def verification_of(r: Resource) -> str:
    for c in (r.get("verificationStatus") or {}).get("coding") or []:
        if c.get("code"):
            return str(c["code"])
    return ""


def basis_of(r: Resource) -> str | None:
    """``proposed`` or ``confirmed`` for a site fact (D-135); None for every hospital record."""
    for t in (r.get("meta") or {}).get("tag") or []:
        if t.get("system") == BASIS:
            return str(t.get("code") or "") or None
    return None


def _value(q: dict[str, Any], text: Any) -> dict[str, Any]:
    """``value_num`` / ``value_cmp`` of an observation (D-142, review B-01). A ``valueQuantity`` keeps its comparator
    (``<0.3`` is censored, not 0.3); a ``valueString`` is read with :mod:`tb_common.labvalue` ("75 H" is 75, "<0.3"
    is censored). Anything else is no number: the screening engine treats it as unknown, never as a failed test."""
    if "value" in q:
        try:
            num = float(q["value"])
        except (TypeError, ValueError):
            return {"value_num": None, "value_cmp": None}
        cmp = q.get("comparator")
        return {"value_num": num, "value_cmp": cmp if cmp in ("<", "<=", ">", ">=") else None}
    got = labvalue.parse(text) if isinstance(text, str) else None
    return {"value_num": got[0], "value_cmp": got[1]} if got else {"value_num": None, "value_cmp": None}


def _ref_id(ref: dict[str, Any] | None) -> str | None:
    if not ref or "reference" not in ref:
        return None
    return str(ref["reference"]).split("/")[-1]


# T-616 (STD-012): an inbound Duration in these UCUM units gives an order's end from its start
_DAYS = {"d": 1, "day": 1, "days": 1, "wk": 7, "week": 7, "weeks": 7}


def _supply_days(dur: dict[str, Any] | None) -> int | None:
    """``dispenseRequest.expectedSupplyDuration`` in whole days (days or weeks only; anything else: None)."""
    if not dur:
        return None
    per = _DAYS.get(str(dur.get("code") or dur.get("unit") or "").strip().lower())
    try:
        value = float(dur["value"])
    except (KeyError, TypeError, ValueError):
        return None
    return int(value * per) if per and value >= 0 else None


# T-616 (STD-014, D-400): the inbound FHIR contract. The top-level elements the flattener reads, per resource type
# (``resourceType`` and ``id`` are always read). Any other element a resource carries is *present but not read*:
# :func:`unread_elements` counts it per resource type for the ingest report, and a resource type that is not here
# is not read at all (counted as ``*``). docs/data/01-what-the-box-reads.md is the same table in words.
READ: dict[str, frozenset[str]] = {
    "Patient": frozenset({"meta", "birthDate", "gender", "deceasedDateTime", "deceasedBoolean"}),
    "Practitioner": frozenset({"meta", "identifier", "name"}),
    "Encounter": frozenset({"meta", "status", "class", "serviceType", "subject", "participant", "period"}),
    "Appointment": frozenset({"meta", "status", "serviceType", "start", "participant"}),
    "Condition": frozenset(
        {
            "meta",
            "code",
            "subject",
            "clinicalStatus",
            "verificationStatus",
            "onsetDateTime",
            "recordedDate",
            "encounter",
        }
    ),
    "Observation": frozenset(
        {
            "meta",
            "status",
            "code",
            "subject",
            "category",
            "effectiveDateTime",
            "effectivePeriod",
            "effectiveInstant",
            "valueQuantity",
            "valueString",
            "valueCodeableConcept",
            "valueDateTime",
            "component",
        }
    ),
    "MedicationRequest": frozenset(
        {
            "meta",
            "status",
            "subject",
            "medicationCodeableConcept",
            "medicationReference",
            "contained",
            "authoredOn",
            "dispenseRequest",
            "dosageInstruction",
        }
    ),
    "MedicationStatement": frozenset(
        {
            "meta",
            "status",
            "subject",
            "medicationCodeableConcept",
            "medicationReference",
            "contained",
            "effectiveDateTime",
            "effectivePeriod",
            "dateAsserted",
            "dosage",
        }
    ),
    "Medication": frozenset({"meta", "code"}),  # read through a medicationReference
    "Procedure": frozenset({"meta", "status", "code", "subject", "performedDateTime", "performedPeriod"}),
    "DiagnosticReport": frozenset({"meta", "status", "code", "subject", "effectiveDateTime", "conclusion"}),
    "DocumentReference": frozenset({"meta", "status", "docStatus", "type", "subject", "date", "content", "context"}),
    "Consent": frozenset({"meta", "patient", "status", "provision", "dateTime"}),
    "Claim": frozenset({"meta", "patient", "created", "item"}),
    "ClaimResponse": frozenset({"meta", "request", "disposition", "outcome", "preAuthPeriod"}),
}
ALWAYS_READ = frozenset({"resourceType", "id"})


def unread_elements(by_type: dict[str, list[Resource]]) -> dict[str, dict[str, int]]:
    """Per resource type, how many resources carry each top-level element the flattener does not read (:data:`READ`);
    a resource type the box does not read at all is counted whole under ``*``. Element names only, never values."""
    acc = Unread()
    for items in by_type.values():
        for r in items:
            acc.add(r)
    return acc.result()


class Unread:
    """:func:`unread_elements` counted one resource at a time (T-692: the ingest no longer holds the night)."""

    def __init__(self) -> None:
        self._n: dict[str, int] = {}
        self._counts: dict[str, dict[str, int]] = {}

    def add(self, r: Resource) -> None:
        rtype = str(r.get("resourceType"))
        self._n[rtype] = self._n.get(rtype, 0) + 1
        known = READ.get(rtype)
        if known is None:
            return
        counts = self._counts.setdefault(rtype, {})
        for k in r:
            if k not in known and k not in ALWAYS_READ:
                counts[k] = counts.get(k, 0) + 1

    def result(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for rtype in sorted(self._n):
            if rtype not in READ:
                out[rtype] = {"*": self._n[rtype]}
            elif self._counts.get(rtype):
                out[rtype] = dict(sorted(self._counts[rtype].items()))
        return out


CODED_TYPES = ("Condition", "MedicationRequest", "MedicationStatement", "Observation")


class _Again:
    """An iterable that starts over each time it is iterated (one table of :meth:`Flattener.stream`)."""

    def __init__(self, make: Callable[[], Iterator[Row]]) -> None:
        self.make = make

    def __iter__(self) -> Iterator[Row]:
        return self.make()


class Flattener:
    def __init__(self, tz: str | None = None) -> None:
        from tb_common.config import site_zone

        self.zone = site_zone(tz)  # the site's zone; TB_TZ when not given, never a default (D-315)
        # T-616 (STD-014): the batch's Medication resources by id, for a ``medicationReference`` to one of them
        self.medications: dict[str, Resource] = {}

    def ts(self, value: str | None) -> datetime | None:
        """FHIR date/dateTime/instant -> naive local timestamp in the hospital zone."""
        if not value:
            return None
        if len(value) == 10:
            d = date.fromisoformat(value)
            return datetime(d.year, d.month, d.day)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(self.zone).replace(tzinfo=None)
        return dt

    def d(self, value: str | None) -> date | None:
        ts = self.ts(value)
        return ts.date() if ts else None

    @staticmethod
    def coding(cc: dict[str, Any] | None, prefer: str | None = None) -> tuple[str | None, str | None]:
        codings = (cc or {}).get("coding") or []
        if prefer:
            for c in codings:
                if c.get("system") == prefer:
                    return c.get("code"), c.get("system")
        for c in codings:
            if c.get("code"):
                return c.get("code"), c.get("system")
        return None, None

    def patient(self, r: Resource) -> Row:
        dec = r.get("deceasedDateTime")
        dead = bool(dec) or r.get("deceasedBoolean") is True  # STD-013: a death flag without a date is a death
        return {
            "pid": r["id"],
            "birth_date": self.d(r.get("birthDate")),
            "sex": sex_of(r.get("gender")),
            "deceased_date": self.d(dec) if dec else None,
            "deceased": True if dead else None,
        }

    def practitioner(self, r: Resource) -> Row:
        ident = (r.get("identifier") or [{}])[0]
        nm = (r.get("name") or [{}])[0]
        name = nm.get("text") or " ".join([*(nm.get("given") or []), nm.get("family") or ""]).strip() or None
        return {"practitioner_id": r["id"], "staff_id": ident.get("value"), "name": name}

    def encounter(self, r: Resource) -> Row:
        dept, _ = self.coding(r.get("serviceType") or {})
        part = (r.get("participant") or [{}])[0]
        period = r.get("period") or {}
        return {
            "eid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "start": self.ts(period.get("start")),
            "dept": dept,
            "practitioner_id": _ref_id(part.get("individual")),
            "class": (r.get("class") or {}).get("code"),
            "end": self.ts(period.get("end")),
            "status": r.get("status"),
        }

    def provenance(self, r: Resource) -> Row:
        """The :data:`PROVENANCE` columns of a resource (DATA-010): its source table and row hash (``meta.source``),
        the night it was ingested (``meta.lastUpdated``, in the hospital zone) and its mapping version."""
        meta = r.get("meta") or {}
        src = str(meta.get("source") or "")
        table = row_hash = None
        if "#" in src:
            left, row_hash = src.rsplit("#", 1)
            table = left.rsplit("/", 1)[-1] or None
        version = next((t.get("code") for t in meta.get("tag") or [] if t.get("system") == MAPPING_VERSION), None)
        return {
            "src_table": table,
            "src_row_hash": row_hash or None,
            "ingested_at": self.ts(meta.get("lastUpdated")),
            "mapping_version": version,
        }

    def consent(self, r: Resource) -> Row:
        return {
            "consid": r["id"],
            "pid": _ref_id(r.get("patient")),
            "status": r.get("status"),
            "contact_ok": (r.get("provision") or {}).get("type") == "permit",
            "date": self.d(r.get("dateTime")),
        }

    def appointment(self, r: Resource) -> Row:
        pid = prac = None
        for p in r.get("participant") or []:
            ref = (p.get("actor") or {}).get("reference", "")
            if ref.startswith("Patient/"):
                pid = ref.split("/")[1]
            elif ref.startswith("Practitioner/"):
                prac = ref.split("/")[1]
        dept, _ = self.coding((r.get("serviceType") or [{}])[0])
        return {
            "aid": r["id"],
            "pid": pid,
            "start": self.ts(r.get("start")),
            "practitioner_id": prac,
            "dept": dept,
            "status": r.get("status"),
        }

    def condition(self, r: Resource) -> Row:
        code, system = self.coding(r.get("code"))
        status, _ = self.coding(r.get("clinicalStatus"))
        return {
            "cid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "code": code,
            "system": system,
            "onset": self.d(r.get("onsetDateTime")),
            "recorded": self.d(r.get("recordedDate")),
            "status": status,
            "eid": _ref_id(r.get("encounter")),
        }

    def observation(self, r: Resource) -> Row:
        codings = (r.get("code") or {}).get("coding") or []
        primary = next((c for c in codings if c.get("system") == LOINC), None) or (codings[0] if codings else {})
        local = codings[-1].get("code") if len(codings) > 1 else None
        cat, _ = self.coding((r.get("category") or [{}])[0])
        q = r.get("valueQuantity") or {}
        vcode, _ = self.coding(r.get("valueCodeableConcept"))
        value = _value(q, r.get("valueString"))
        if uncertain("Observation", r):  # D-275: kept, but no usable value (unknown, never a decided answer)
            value, vcode = {"value_num": None, "value_cmp": None}, None
        return {
            "oid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "code": primary.get("code"),
            "system": primary.get("system"),
            "effective": self.effective(r),
            **value,
            "unit": q.get("code") or q.get("unit"),
            "value_code": vcode,
            "category": cat,
            "local_code": local,
        }

    def effective(self, r: Resource) -> datetime | None:
        """An observation's time: ``effectiveDateTime``, else ``effectiveInstant``, else the start of
        ``effectivePeriod`` (T-616, review S-17: a result dated by a period only is read, not undated)."""
        when = r.get("effectiveDateTime") or r.get("effectiveInstant")
        return self.ts(when or (r.get("effectivePeriod") or {}).get("start"))

    def medication_concept(self, r: Resource) -> dict[str, Any]:
        """The drug of an order or statement: ``medicationCodeableConcept``, else the ``code`` of the Medication its
        ``medicationReference`` names, contained (``#id``) or in the batch (``Medication/id``; T-616, STD-014).
        A reference that names no Medication gives no code (the record is kept, its drug unknown)."""
        cc = r.get("medicationCodeableConcept")
        if cc:
            return dict(cc)
        ref = str((r.get("medicationReference") or {}).get("reference") or "")
        if not ref:
            return {}
        med: Resource | None = None
        if ref.startswith("#"):
            med = next((c for c in r.get("contained") or [] if c.get("id") == ref[1:]), None)
        else:
            med = self.medications.get(ref.rsplit("/", maxsplit=1)[-1])
        if not med or med.get("resourceType", "Medication") != "Medication":
            return {}
        code = dict(med.get("code") or {})
        if not code.get("text") and (r.get("medicationReference") or {}).get("display"):
            code["text"] = r["medicationReference"]["display"]
        return code

    def therapy(self, r: Resource) -> tuple[date | None, date | None]:
        """The therapy period of an order (STD-012), in order: ``dosageInstruction[0].timing.repeat.boundsPeriod``,
        ``dispenseRequest.validityPeriod``, then ``authoredOn`` with ``dispenseRequest.expectedSupplyDuration``. A
        statement: its ``effectivePeriod`` (or ``effectiveDateTime``)."""
        if r.get("resourceType") == "MedicationStatement":
            period = r.get("effectivePeriod") or {}
            return self.d(period.get("start") or r.get("effectiveDateTime")), self.d(period.get("end"))
        dosage = (r.get("dosageInstruction") or [{}])[0] or {}
        bounds = ((dosage.get("timing") or {}).get("repeat") or {}).get("boundsPeriod") or {}
        disp = r.get("dispenseRequest") or {}
        period = bounds if (bounds.get("start") or bounds.get("end")) else disp.get("validityPeriod") or {}
        start = self.d(period.get("start") or r.get("authoredOn"))
        end = self.d(period.get("end"))
        days = _supply_days(disp.get("expectedSupplyDuration"))
        if end is None and start is not None and days is not None:
            end = start + timedelta(days=days)
        return start, end

    def medication(self, r: Resource) -> Row:
        cc = self.medication_concept(r)
        nhi = atc = None
        for c in cc.get("coding") or []:
            if "atc" in (c.get("system") or ""):
                atc = c.get("code")
            elif nhi is None:
                nhi = c.get("code")
        rtype = str(r.get("resourceType") or "MedicationRequest")
        statement = rtype == "MedicationStatement"
        placed = not uncertain(rtype, r)  # D-275: an order of unknown status is kept undated
        start, end = self.therapy(r)
        authored = self.d(r.get("dateAsserted") if statement else r.get("authoredOn"))
        dosage = r.get("dosage") if statement else r.get("dosageInstruction")
        return {
            "mid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "nhi_code": nhi,
            "atc": atc,
            "authored": (authored or (start if statement else None)) if placed else None,
            "start": start if placed else None,
            "end": end if placed else None,
            "status": r.get("status"),
            "name": cc.get("text"),
            "dose": ((dosage or [{}])[0] or {}).get("text"),
        }

    def procedure(self, r: Resource) -> Row:
        code, system = self.coding(r.get("code"))
        return {
            "prid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "code": code,
            "system": system,
            "performed": self.d(r.get("performedDateTime") or (r.get("performedPeriod") or {}).get("start")),
        }

    def report(self, r: Resource) -> Row:
        code, system = self.coding(r.get("code"), prefer=LOINC)
        return {
            "rid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "code": code,
            "system": system,
            "effective": self.d(r.get("effectiveDateTime")),
            "conclusion": r.get("conclusion"),
        }

    def document(self, r: Resource) -> Row:
        att = ((r.get("content") or [{}])[0]).get("attachment") or {}
        text = base64.b64decode(att["data"]).decode("utf-8") if att.get("data") else ""
        typ = (r.get("type") or {}).get("text") or self.coding(r.get("type"))[0]
        enc = ((r.get("context") or {}).get("encounter") or [{}])[0]
        return {
            "did": r["id"],
            "pid": _ref_id(r.get("subject")),
            "date": self.ts(r.get("date")),
            "type": typ,
            "eid": _ref_id(enc),
            "text": text,
        }

    def claims(self, claims: Iterable[Resource], responses: Iterable[Resource]) -> list[Row]:
        resp_by_req = {_ref_id(cr.get("request")): cr for cr in responses}
        return [self._claim(c, resp_by_req) for c in claims]

    def _claim(self, c: Resource, resp_by_req: dict[str | None, Resource]) -> Row:
        item = (c.get("item") or [{}])[0]
        product, _ = self.coding(item.get("productOrService"))
        cr = resp_by_req.get(c["id"]) or {}
        period = cr.get("preAuthPeriod") or {}
        return {
            "kid": c["id"],
            "pid": _ref_id(c.get("patient")),
            "created": self.d(c.get("created")),
            "product": product,
            "outcome": cr.get("disposition") or cr.get("outcome"),
            "approval_start": self.d(period.get("start")),
            "approval_end": self.d(period.get("end")),
        }

    def flatten(self, by_type: dict[str, list[Resource]]) -> dict[str, list[Row]]:
        return {name: list(rows) for name, rows in self.stream(by_type).items()}

    def stream(self, by_type: Mapping[str, Iterable[Resource]]) -> dict[str, Iterable[Row]]:
        """The lake tables of ``by_type`` as re-readable streams (T-692, D-473): each table reads its resource types
        again when it is iterated, so a rebuild that writes one table at a time holds one row group, not the night.
        ``by_type``'s values must be re-iterable (lists, or readers of NDJSON files). Rows and order are those of
        :meth:`flatten`: per table the types in the order below, the resources in their order. The ``Medication``
        resources (read through a reference), the ``ClaimResponse`` resources (joined to their claim) and the patient
        rows (one per pid, :func:`merge_patients`) are held; they are a small part of a night."""
        m = {
            "Patient": ("patient", self.patient),
            "Practitioner": ("practitioner", self.practitioner),
            "Encounter": ("encounter", self.encounter),
            "Appointment": ("appointment", self.appointment),
            "Condition": ("condition", self.condition),
            "MedicationRequest": ("medication", self.medication),
            "MedicationStatement": ("medication", self.medication),
            "Procedure": ("procedure", self.procedure),
            "DiagnosticReport": ("report", self.report),
            "DocumentReference": ("document", self.document),
            "Consent": ("consent", self.consent),
        }

        def live(rtype: str) -> Iterator[Resource]:  # D-275 (S-4): a void record is no record
            return (r for r in by_type.get(rtype, ()) if not void(rtype, r))

        def demographic(rtype: str, r: Resource) -> bool:
            return rtype == "Observation" and any(
                c.get("system") == DEMOGRAPHIC for c in (r.get("code") or {}).get("coding") or []
            )

        def screened(rtype: str) -> Iterator[tuple[Resource, str | None, bool]]:
            """(resource, basis, suspected) of a coded type; a refuted record left out of both."""
            for r in live(rtype):
                b = basis_of(r)
                if rtype == "Condition":
                    vs = verification_of(r)
                    if vs in NOT_PRESENT:  # refuted, entered in error: not a diagnosis at all
                        continue
                    if vs in SUSPECTED and b != "proposed":
                        # D-142: a suspected diagnosis (疑い) is listed, never coded: it can only send a patient to
                        # "needs information" (matching.proposed), never count as met or exclude
                        yield r, b, True
                        continue
                yield r, b, False

        def facts() -> Iterator[Row]:
            for rtype in CODED_TYPES:
                for r, b, suspected in screened(rtype):
                    if suspected:
                        yield {**self.site_fact(rtype, r, "suspected"), **self.provenance(r)}
                    elif b is not None or demographic(rtype, r):
                        yield {**self.site_fact(rtype, r, b or "coded"), **self.provenance(r)}

        def coded(rtype: str) -> Iterator[Resource]:
            for r, b, suspected in screened(rtype):
                if not suspected and b != "proposed" and not demographic(rtype, r):  # a proposed fact: never coded
                    yield r

        def table(rtypes: tuple[str, ...]) -> Iterator[Row]:  # a table two types fill (medication): the first first
            for rtype in rtypes:
                fn = m[rtype][1]
                for r in coded(rtype) if rtype in CODED_TYPES else live(rtype):
                    yield {**fn(r), **self.provenance(r)}

        def observations() -> Iterator[Row]:
            for r in coded("Observation"):
                for row in self.observations(r):
                    yield {**row, **self.provenance(r)}

        def claims() -> Iterator[Row]:
            resp_by_req = {_ref_id(cr.get("request")): cr for cr in live("ClaimResponse")}
            for c in live("Claim"):
                yield {**self._claim(c, resp_by_req), **self.provenance(c)}

        self.medications = {str(md["id"]): md for md in live("Medication") if md.get("id")}
        out: dict[str, Iterable[Row]] = {name: () for name in SCHEMAS}
        tables: dict[str, tuple[str, ...]] = {}
        for rtype, (name, _) in m.items():
            tables[name] = (*tables.get(name, ()), rtype)
        for name, rtypes in tables.items():
            out[name] = _Again(lambda rtypes=rtypes: table(rtypes))  # type: ignore[misc]
        out["patient"] = _Again(lambda: iter(merge_patients(list(table(("Patient",))))))
        out["observation"] = _Again(observations)
        out["site_fact"] = _Again(facts)
        out["claim"] = _Again(claims)
        return out

    def site_fact(self, rtype: str, r: Resource, basis: str) -> Row:
        if rtype == "Condition":
            code, system = self.coding(r.get("code"))
            d = self.d(r.get("onsetDateTime")) or self.d(r.get("recordedDate"))
            return {"fid": r["id"], "pid": _ref_id(r.get("subject")), "domain": "condition", "code": code,
                    "system": system, "d": d, "value_num": None, "unit": None, "value_text": None,
                    "basis": basis}  # fmt: skip
        if rtype in ("MedicationRequest", "MedicationStatement"):
            med = self.medication(r)
            return {"fid": r["id"], "pid": med["pid"], "domain": "medication", "code": med["atc"] or med["nhi_code"],
                    "system": "atc" if med["atc"] else None, "d": med["authored"], "value_num": None, "unit": None,
                    "value_text": med["name"], "basis": basis}  # fmt: skip
        obs = self.observation(r)
        demographic = obs["system"] == DEMOGRAPHIC
        text = r.get("valueString") or r.get("valueDateTime") or (r.get("valueCodeableConcept") or {}).get("text")
        return {"fid": r["id"], "pid": obs["pid"], "domain": "demographic" if demographic else "observation",
                "code": obs["code"], "system": obs["system"], "d": None if demographic else obs["effective"],
                "value_num": obs["value_num"], "unit": obs["unit"], "value_text": text, "basis": basis}  # fmt: skip

    def observations(self, r: Resource) -> list[Row]:
        """The observation row plus one row per coded component (e.g. BP panel -> systolic, diastolic)."""
        rows = [self.observation(r)]
        for comp in r.get("component") or []:
            code, system = self.coding(comp.get("code"), prefer=LOINC)
            q = comp.get("valueQuantity") or {}
            vcode, _ = self.coding(comp.get("valueCodeableConcept"))
            value = _value(q, comp.get("valueString"))
            if uncertain("Observation", r):  # the panel's status holds for its components (D-275)
                value, vcode = {"value_num": None, "value_cmp": None}, None
            rows.append(
                {
                    **rows[0],
                    "oid": f"{r['id']}.{code}",
                    "code": code,
                    "system": system,
                    **value,
                    "unit": q.get("code") or q.get("unit"),
                    "value_code": vcode,
                    "local_code": None,
                }
            )
        return rows


def merge_patients(rows: list[Row]) -> list[Row]:
    """One ``patient`` row per pid. The hospital's feed and the site's own inputs (D-135: a sheet, a dump, a chart
    published into the same space) each give a ``Patient`` for the same pseudonym; two rows for one pid would
    multiply every row of a compiled query (each criterion joins ``base`` again: 2^criteria rows per patient, review
    XL-02). A field the rows agree on is kept; a field they give different values for is left out (unknown), as
    ``sitesetup.publish`` does for disagreeing facts. The provenance columns are the first row's (the hospital's)."""
    by: dict[str, Row] = {}
    clash: dict[str, set[str]] = {}
    for r in rows:
        pid = r["pid"]
        if pid not in by:
            by[pid] = dict(r)
            continue
        have = by[pid]
        for k, v in r.items():
            if v is None or k in clash.get(pid, set()) or k in PROVENANCE_COLS:
                continue
            if have.get(k) is None:
                have[k] = v
            elif have[k] != v:
                have[k] = None
                clash.setdefault(pid, set()).add(k)
    return list(by.values())
