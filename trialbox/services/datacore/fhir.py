"""The data core as FHIR R4 for HAPI (D-123): each study form is a Questionnaire, each record's answers on a form a
QuestionnaireResponse whose subject is the pseudonymous Patient. ``to_hapi`` loads them with the adapter's batch
loader (the same path as the nightly snapshot), so CQL, Subscriptions and searches see the study data."""

from __future__ import annotations

from typing import Any

from datacore.forms import Field, fields_of
from datacore.store import DataCore


def typed(f: Field, v: str) -> dict[str, Any]:
    if f.kind in ("choice", "multi"):
        return {"valueCoding": {"code": v, "display": f.options.get(v, v)}}
    if f.kind == "date":
        return {"valueDate": v}
    if f.kind == "dateTime":
        return {"valueDateTime": v}
    if f.kind == "integer":
        return {"valueInteger": int(v)}
    if f.kind == "decimal":
        return {"valueDecimal": float(v)}
    return {"valueString": v}


def _rid(*parts: str) -> str:
    return "-".join(p.lower().replace("_", "-") for p in parts if p)[:64]


def resources(dc: DataCore, study: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    forms = dc.forms(study)
    out.extend(forms)
    for q in forms:
        fields = {f.name: f for f in fields_of(q)}
        for rec in dc.records(study):
            by_event: dict[str, list[dict[str, Any]]] = {}
            for r in dc.values(study, rec):
                f = fields.get(r["field"])
                if f is None or r["value"] == "":
                    continue
                vals = r["value"].split(",") if f.kind == "multi" else [r["value"]]
                by_event.setdefault(r["event"], []).append({"linkId": f.name, "answer": [typed(f, v) for v in vals]})
            for ev, items in by_event.items():
                qr: dict[str, Any] = {
                    "resourceType": "QuestionnaireResponse",
                    "id": _rid(study, q["name"], rec, ev),
                    "questionnaire": q["url"],
                    "status": "completed",
                    "subject": {"reference": f"Patient/{rec.lower()}", "display": rec},
                    "item": items,
                }
                if ev:
                    qr["extension"] = [{"url": "urn:trialbox:event", "valueString": ev}]
                out.append(qr)
    return out


def to_hapi(dc: DataCore, study: str, base_url: str) -> int:
    from adapter.load_fhir import post_batches

    return post_batches(base_url, resources(dc, study))
