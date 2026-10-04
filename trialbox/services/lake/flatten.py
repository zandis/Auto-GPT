"""Flatten FHIR NDJSON into the lake tables of SPEC §3.2 (local-time dates/timestamps in the hospital zone)."""

from __future__ import annotations

import base64
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

Resource = dict[str, Any]
Row = dict[str, Any]

LOINC = "http://loinc.org"

SCHEMAS: dict[str, list[tuple[str, str]]] = {
    "patient": [("pid", "VARCHAR"), ("birth_date", "DATE"), ("sex", "VARCHAR"), ("deceased_date", "DATE")],
    "practitioner": [("practitioner_id", "VARCHAR"), ("staff_id", "VARCHAR")],
    "encounter": [
        ("eid", "VARCHAR"),
        ("pid", "VARCHAR"),
        ("start", "TIMESTAMP"),
        ("dept", "VARCHAR"),
        ("practitioner_id", "VARCHAR"),
        ("class", "VARCHAR"),
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
}


def _ref_id(ref: dict[str, Any] | None) -> str | None:
    if not ref or "reference" not in ref:
        return None
    return str(ref["reference"]).split("/")[-1]


class Flattener:
    def __init__(self, tz: str = "Asia/Taipei") -> None:
        self.zone = ZoneInfo(tz)

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
        return {
            "pid": r["id"],
            "birth_date": self.d(r.get("birthDate")),
            "sex": r.get("gender"),
            "deceased_date": self.d(dec) if dec else None,
        }

    def practitioner(self, r: Resource) -> Row:
        ident = (r.get("identifier") or [{}])[0]
        return {"practitioner_id": r["id"], "staff_id": ident.get("value")}

    def encounter(self, r: Resource) -> Row:
        dept, _ = self.coding(r.get("serviceType") or {})
        part = (r.get("participant") or [{}])[0]
        return {
            "eid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "start": self.ts((r.get("period") or {}).get("start")),
            "dept": dept,
            "practitioner_id": _ref_id(part.get("individual")),
            "class": (r.get("class") or {}).get("code"),
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
        return {
            "oid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "code": primary.get("code"),
            "system": primary.get("system"),
            "effective": self.ts(r.get("effectiveDateTime")),
            "value_num": float(q["value"]) if "value" in q else None,
            "unit": q.get("code") or q.get("unit"),
            "value_code": vcode,
            "category": cat,
            "local_code": local,
        }

    def medication(self, r: Resource) -> Row:
        cc = r.get("medicationCodeableConcept") or {}
        nhi = atc = None
        for c in cc.get("coding") or []:
            if "atc" in (c.get("system") or ""):
                atc = c.get("code")
            elif nhi is None:
                nhi = c.get("code")
        period = (r.get("dispenseRequest") or {}).get("validityPeriod") or {}
        return {
            "mid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "nhi_code": nhi,
            "atc": atc,
            "authored": self.d(r.get("authoredOn")),
            "start": self.d(period.get("start") or r.get("authoredOn")),
            "end": self.d(period.get("end")),
            "status": r.get("status"),
            "name": cc.get("text"),
            "dose": ((r.get("dosageInstruction") or [{}])[0] or {}).get("text"),
        }

    def procedure(self, r: Resource) -> Row:
        code, system = self.coding(r.get("code"))
        return {
            "prid": r["id"],
            "pid": _ref_id(r.get("subject")),
            "code": code,
            "system": system,
            "performed": self.d(r.get("performedDateTime")),
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
        rows = []
        for c in claims:
            item = (c.get("item") or [{}])[0]
            product, _ = self.coding(item.get("productOrService"))
            cr = resp_by_req.get(c["id"]) or {}
            period = cr.get("preAuthPeriod") or {}
            rows.append(
                {
                    "kid": c["id"],
                    "pid": _ref_id(c.get("patient")),
                    "created": self.d(c.get("created")),
                    "product": product,
                    "outcome": cr.get("disposition") or cr.get("outcome"),
                    "approval_start": self.d(period.get("start")),
                    "approval_end": self.d(period.get("end")),
                }
            )
        return rows

    def flatten(self, by_type: dict[str, list[Resource]]) -> dict[str, list[Row]]:
        m = {
            "Patient": ("patient", self.patient),
            "Practitioner": ("practitioner", self.practitioner),
            "Encounter": ("encounter", self.encounter),
            "Appointment": ("appointment", self.appointment),
            "Condition": ("condition", self.condition),
            "MedicationRequest": ("medication", self.medication),
            "Procedure": ("procedure", self.procedure),
            "DiagnosticReport": ("report", self.report),
            "DocumentReference": ("document", self.document),
        }
        out: dict[str, list[Row]] = {name: [] for name in SCHEMAS}
        for rtype, (table, fn) in m.items():
            out[table] = [fn(r) for r in by_type.get(rtype, [])]
        out["observation"] = [row for r in by_type.get("Observation", []) for row in self.observations(r)]
        out["claim"] = self.claims(by_type.get("Claim", []), by_type.get("ClaimResponse", []))
        return out

    def observations(self, r: Resource) -> list[Row]:
        """The observation row plus one row per coded component (e.g. BP panel -> systolic, diastolic)."""
        rows = [self.observation(r)]
        for comp in r.get("component") or []:
            code, system = self.coding(comp.get("code"), prefer=LOINC)
            q = comp.get("valueQuantity") or {}
            vcode, _ = self.coding(comp.get("valueCodeableConcept"))
            rows.append(
                {
                    **rows[0],
                    "oid": f"{r['id']}.{code}",
                    "code": code,
                    "system": system,
                    "value_num": float(q["value"]) if "value" in q else None,
                    "unit": q.get("code") or q.get("unit"),
                    "value_code": vcode,
                    "local_code": None,
                }
            )
        return rows
