"""The site's facts into the lake (D-135): FHIR resources the lake's flattener knows, joined by pseudonym.

* A patient from several inputs (a hospital dump, a PI's sheet, a chart) is one ``Patient`` whose id is the
  pseudonym: every input is keyed by the chart number turned into the pseudonym with the site key, never by a name.
  When the counted facts disagree (two different dates of birth), the value is left out (unknown: the patient needs
  information) and the disagreement is listed (:func:`disagreements`) until a person rejects the wrong one.
* ``coded`` and ``confirmed`` facts become coded records (``Condition``, ``Observation``, ``MedicationRequest``); a
  local code is written with the standard code a person mapped it to first, else only in its local system (D-130:
  unknown code system). Confirmed facts carry the ``confirmed`` tag (counted, and listed in ``site_fact``).
* ``proposed`` facts carry the ``proposed`` tag: the flattener lists them in ``site_fact`` and never in a coded table.
* ``rejected`` facts are left out. A chart's text (identifiers redacted) is a ``DocumentReference``: note text stays
  notes, read by the two models at screening.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from lake.flatten import BASIS, DEMOGRAPHIC

from sitesetup import mapping
from sitesetup.store import COUNTED

Resources = dict[str, list[dict[str, Any]]]


def _tag(r: dict[str, Any], status: str) -> dict[str, Any]:
    if status in ("proposed", "confirmed"):
        r["meta"] = {"tag": [{"system": BASIS, "code": status}]}
    return r


def _rid(f: Mapping[str, Any]) -> str:
    prefix = {"coded": "tbsd", "confirmed": "tbcf", "proposed": "tbpf"}[str(f["status"])]
    return f"{prefix}-{f['id']}"


def _codings(f: Mapping[str, Any], maps: Mapping[tuple[str, str, str], Mapping[str, str]]) -> list[dict[str, str]]:
    out = []
    if f["code"] and f["system"]:
        out.append({"system": f["system"], "code": f["code"]})
    if f["local_code"]:
        m = maps.get((f["domain"], f["local_system"], f["local_code"]))
        if m and not out:
            out.append({"system": m["system"], "code": m["code"], "display": m.get("display", "")})
        out.append({"system": f["local_system"], "code": f["local_code"], "display": f["term"]})
    return out


def disagreements(facts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per patient and demographic item, the different values the counted facts give (never resolved silently)."""
    vals: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for f in facts:
        if f["domain"] == "demographic" and f["status"] in COUNTED and f["value"]:
            vals[(f["pid"], f["code"])][f["value"]].append(int(f["id"]))
    return [
        {"pid": pid, "what": what, "values": [{"value": v, "facts": ids} for v, ids in sorted(by.items())]}
        for (pid, what), by in sorted(vals.items())
        if len(by) > 1
    ]


def resources(
    facts: Sequence[Mapping[str, Any]],
    maps: Mapping[tuple[str, str, str], Mapping[str, str]],
    charts: Iterable[Mapping[str, Any]],
) -> Resources:
    """Every resource of one workspace; ``charts``: ``{id, pid, day, text}`` of each chart (text redacted)."""
    out: Resources = defaultdict(list)
    pids: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    days: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        if f["status"] == "rejected":
            continue
        pid = str(f["pid"])
        pids[pid]
        if f["day"] and f["status"] in COUNTED:
            days[pid].add(str(f["day"]))
        subject = {"reference": f"Patient/{pid}"}
        if f["domain"] == "demographic":
            if f["status"] in COUNTED:
                pids[pid][str(f["code"])].add(str(f["value"]))
            if f["status"] in ("proposed", "confirmed"):
                out["Observation"].append(
                    _tag(
                        {
                            "resourceType": "Observation",
                            "id": _rid(f),
                            "subject": subject,
                            "code": {"coding": [{"system": DEMOGRAPHIC, "code": f["code"]}]},
                            "valueString": f["value"],
                            "status": "final",
                        },
                        str(f["status"]),
                    )
                )
            continue
        codings = _codings(f, maps)
        if f["domain"] == "condition":
            r: dict[str, Any] = {
                "resourceType": "Condition",
                "id": _rid(f),
                "subject": subject,
                "code": {"coding": codings, "text": f["term"]} if codings else {"text": f["term"]},
            }
            if f["day"]:
                r["onsetDateTime"] = f["day"]
                r["recordedDate"] = f["day"]
        elif f["domain"] == "observation":
            r = {
                "resourceType": "Observation",
                "id": _rid(f),
                "subject": subject,
                "status": "final",
                "code": {"coding": codings, "text": f["term"]},
                "category": [{"coding": [{"code": "laboratory"}]}],
            }
            try:
                r["valueQuantity"] = {"value": float(f["value"]), "unit": f["unit"], "code": f["unit"]}
            except ValueError:
                r["valueString"] = f["value"]
            if f["day"]:
                r["effectiveDateTime"] = f["day"]
        elif f["domain"] == "medication":
            meds = [c for c in codings if "atc" in c["system"]] + [c for c in codings if "atc" not in c["system"]]
            r = {
                "resourceType": "MedicationRequest",
                "id": _rid(f),
                "subject": subject,
                "status": "active",
                "intent": "order",
                "medicationCodeableConcept": {"coding": meds, "text": f["term"]},
            }
            if f["day"]:
                r["authoredOn"] = f["day"]
        else:
            continue
        out[r["resourceType"]].append(_tag(r, str(f["status"])))
    for ch in charts:
        pid = str(ch["pid"])
        pids[pid]
        days[pid].add(str(ch["day"]))
        out["DocumentReference"].append(
            {
                "resourceType": "DocumentReference",
                "id": f"tbch-{ch['id']}",
                "status": "current",
                "subject": {"reference": f"Patient/{pid}"},
                "date": str(ch["day"]),
                "type": {"text": "chart"},
                "content": [
                    {"attachment": {"contentType": "text/plain; charset=utf-8", "data": _b64(str(ch["text"]))}}
                ],
            }
        )
    for pid, demo in sorted(pids.items()):
        p: dict[str, Any] = {"resourceType": "Patient", "id": pid}
        if len(demo.get("birth_date", set())) == 1:
            p["birthDate"] = next(iter(demo["birth_date"]))
        if len(demo.get("sex", set())) == 1:
            p["gender"] = next(iter(demo["sex"]))
        out["Patient"].append(p)
        for d in sorted(days[pid]):
            out["Encounter"].append(
                {
                    "resourceType": "Encounter",
                    "id": f"tbenc-{pid[:12]}-{d}",
                    "status": "finished",
                    "subject": {"reference": f"Patient/{pid}"},
                    "period": {"start": d},
                    "class": {"code": "AMB"},
                }
            )
    return {k: sorted(v, key=lambda r: str(r["id"])) for k, v in sorted(out.items())}


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def digest(res: Resources) -> str:
    return hashlib.sha256(json.dumps(res, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def counts(res: Resources) -> dict[str, int]:
    return {k: len(v) for k, v in res.items()}


__all__ = ["Resources", "counts", "digest", "disagreements", "mapping", "resources"]
