"""fhir-store client: CQL evaluation (HAPI CR ``Library/$evaluate``, SPEC §4.4) and Library/ValueSet loading.

Shared by the criteria-compiler (equivalence gate) and the orchestrator (SCREEN / NAV structured evaluation).
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

import httpx
from tb_contracts import PatientEvaluation

log = logging.getLogger("fhir_eval")
LIB_BASE = "http://trialbox.local/fhir/Library"


def library_name(ruleset: str, version: str) -> str:
    """``TB_<RULESET>_v<major>_<minor>`` (SPEC §6.1; ``-`` in ruleset ids becomes ``_``)."""
    major, minor, *_ = [*version.split("."), "0", "0"][:3]
    return f"TB_{ruleset.replace('-', '_')}_v{major}_{minor}"


def library_id(name: str) -> str:
    return name.replace("_", "-")


class FhirEvalError(RuntimeError):
    pass


_PATIENT_REF = re.compile(r"\b(Patient|subject)([/=:]\s*)([\w.\-]+)", re.IGNORECASE)


def server_said(exc: BaseException, limit: int = 300) -> str:
    """G11 of the P1b review (D-959): what the FHIR server said, safe for a job's error and the log. D-910 kept only
    the error's type and status, since an ``$evaluate`` error can quote a patient's id; a refused ``PUT`` of a
    ValueSet then read "FhirEvalError, HTTP 422" with nothing to act on. The text is kept with patient references
    (``Patient/…``, ``subject=…``), identifying keys (``mrn=…``) and identifier-shaped tokens masked (``redact``)."""
    from tb_common.audit import ID_MASK, mask_ids
    from tb_common.logging import redact

    text = " ".join(str(exc).split())
    text = _PATIENT_REF.sub(lambda m: f"{m.group(1)}{m.group(2)}{ID_MASK}", text)
    text = redact(mask_ids(text))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def library_resource(name: str, version: str, cql: str, elm: str | None) -> dict[str, Any]:
    content = [{"contentType": "text/cql", "data": base64.b64encode(cql.encode()).decode()}]
    if elm:
        content.append({"contentType": "application/elm+json", "data": base64.b64encode(elm.encode()).decode()})
    return {
        "resourceType": "Library",
        "id": library_id(name),
        "url": f"{LIB_BASE}/{name}",
        "name": name,
        "version": version,
        "status": "active",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/library-type", "code": "logic-library"}]},
        "content": content,
    }


# The one code a ValueSet with no code lists in its FHIR-store copy: of TrialBox's own system, which no record is
# coded in, so the copy has no member a record can match, as the ValueSet itself
NO_MEMBER = {"system": "https://trialbox.local/fhir/CodeSystem/no-member", "code": "no-member",
             "display": "no code: the concept mapped to none"}  # fmt: skip


def store_valueset(vs: dict[str, Any]) -> dict[str, Any]:
    """The copy of a compiled ValueSet the FHIR store is given: expanded already, from the codes it lists. The store
    holds no code system (none is loaded into it, and none needs to be): its CQL engine read each ValueSet's
    ``compose`` and warned that results may be wrong, and a ValueSet with no code (a concept that mapped to none) has
    no ``compose`` at all, which it cannot expand: "Failed to expand ValueSet", and the whole equivalence check of the
    protocol could not run (MVP walk, step 3). An expansion it reads as it is, offline, for every ValueSet. A ValueSet
    with no code lists :data:`NO_MEMBER` in its copy (the engine reads an empty expansion as none). A ValueSet that is
    not a plain list of codes (a filter, another ValueSet, an exclusion, a whole code system) or is expanded already is
    given as it is."""
    compose = vs.get("compose") or {}
    includes = compose.get("include") or []
    if (
        vs.get("expansion")
        or compose.get("exclude")
        or any(
            inc.get("filter") or inc.get("valueSet") or not (inc.get("system") and inc.get("concept"))
            for inc in includes
        )
    ):
        return vs
    contains = [
        {"system": inc["system"], "code": c["code"], **({"display": c["display"]} if c.get("display") else {})}
        for inc in includes
        for c in inc.get("concept") or []
    ]
    out = dict(vs)
    if not contains:
        contains = [dict(NO_MEMBER)]
        member = {"code": NO_MEMBER["code"], "display": NO_MEMBER["display"]}
        out["compose"] = {"include": [{"system": NO_MEMBER["system"], "concept": [member]}]}
    out["expansion"] = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "total": len(contains),
        "contains": contains,
    }
    return out


class FhirEvaluator:
    def __init__(self, base_url: str, timeout: float = 120.0, workers: int = 8) -> None:
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)
        self.workers = workers

    def put(self, resource: dict[str, Any]) -> None:
        resp = self.client.put(
            f"{self.base}/{resource['resourceType']}/{resource['id']}",
            json=resource,
            headers={"Content-Type": "application/fhir+json"},
        )
        if resp.status_code >= 400:
            raise FhirEvalError(
                f"PUT {resource['resourceType']}/{resource['id']}: {resp.status_code} {resp.text[:400]}"
            )

    def load(self, libraries: list[dict[str, Any]], valuesets: Iterable[dict[str, Any]]) -> None:
        for vs in valuesets:
            self.put(store_valueset(vs))
        for lib in libraries:
            self.put(lib)

    def evaluate(self, library_name: str, pid: str, index_date: date, expressions: list[str]) -> PatientEvaluation:
        params: list[dict[str, Any]] = [
            {"name": "subject", "valueString": f"Patient/{pid}"},
            {
                "name": "parameters",
                "resource": {
                    "resourceType": "Parameters",
                    "parameter": [{"name": "IndexDate", "valueDate": index_date.isoformat()}],
                },
            },
        ]
        params.extend({"name": "expression", "valueString": e} for e in expressions)
        resp = self.client.post(
            f"{self.base}/Library/{library_id(library_name)}/$evaluate",
            json={"resourceType": "Parameters", "parameter": params},
            headers={"Content-Type": "application/fhir+json"},
        )
        if resp.status_code >= 400:
            raise FhirEvalError(f"$evaluate {pid}: {resp.status_code} {resp.text[:500]}")
        return self.parse(pid, index_date, resp.json(), expressions)

    @staticmethod
    def parse(pid: str, index_date: date, body: dict[str, Any], expressions: list[str]) -> PatientEvaluation:
        results: dict[str, bool | None] = {}
        evidence: dict[str, list[str]] = {}
        for p in body.get("parameter", []):
            name = p.get("name", "")
            if name == "evaluation error":
                issues = (p.get("resource") or {}).get("issue", [])
                raise FhirEvalError(
                    f"CQL evaluation error for {pid}: " + "; ".join(i.get("diagnostics", "") for i in issues)[:800]
                )
            if name.startswith("C_"):
                if "valueBoolean" in p:
                    results[name[2:]] = bool(p["valueBoolean"])
                else:
                    results.setdefault(name[2:], None)
            elif name.startswith("E_") and "valueString" in p:
                evidence.setdefault(name[2:], []).append(str(p["valueString"]))
        for e in expressions:
            if e.startswith("C_"):
                results.setdefault(e[2:], None)
        return PatientEvaluation(pid=pid, index_date=index_date, engine="cql", results=results, evidence=evidence)

    def evaluate_many(
        self, library_name: str, pids: list[str], index_date: date, expressions: list[str]
    ) -> list[PatientEvaluation]:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(lambda p: self.evaluate(library_name, p, index_date, expressions), pids))
