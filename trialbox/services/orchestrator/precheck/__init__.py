"""NHI TWPAS pre-check loader and runner (SPEC §9.5): a pre-check CQL library (NHI's when published; TrialBox ships
stand-ins under ``precheck/``) is translated, loaded into fhir-store and evaluated against the application bundle
itself (``Library/$evaluate`` with ``data`` = the Bundle and ``useServerData`` = false)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tb_common.fhir import FhirEvaluator, library_id, library_resource

HERE = Path(__file__).resolve().parent


@dataclass
class PrecheckResult:
    passed: bool | None
    issues: list[str] = field(default_factory=list)
    library: str = ""


class PrecheckRunner:
    def __init__(self, fhir: FhirEvaluator | None, library_dir: Path = HERE) -> None:
        self.fhir = fhir
        self.dir = library_dir
        self._loaded: dict[str, str] = {}

    def available(self, name: str) -> bool:
        return (self.dir / f"{name}.cql").exists()

    def _load(self, name: str) -> str:
        """Translate (cql-to-elm) and load once per content hash; returns the Library version."""
        assert self.fhir is not None
        cql = (self.dir / f"{name}.cql").read_text(encoding="utf-8")
        version = "1.0.0-p" + hashlib.sha256(cql.encode()).hexdigest()[:8]
        if self._loaded.get(name) == version:
            return version
        from criteria_compiler.compile_cql.translator import Translator, fhirhelpers_source

        tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), name: cql})
        text = cql.replace(f"library {name} version '1.0.0'", f"library {name} version '{version}'")
        elm = (
            tr.elm[name]
            .replace('"version" : "1.0.0"', f'"version" : "{version}"')
            .replace('"version":"1.0.0"', f'"version":"{version}"')
        )
        self.fhir.load(
            [
                library_resource("FHIRHelpers", "4.0.1", fhirhelpers_source(), tr.elm.get("FHIRHelpers")),
                library_resource(name, version, text, elm),
            ],
            [],
        )
        self._loaded[name] = version
        return version

    def run(self, name: str, bundle: dict[str, Any]) -> PrecheckResult:
        if not self.available(name):
            return PrecheckResult(None, [f"no pre-check library {name}"], name)
        if self.fhir is None:
            return PrecheckResult(None, ["pre-check engine (fhir-store) unavailable"], name)
        self._load(name)
        patient = next(e["resource"]["id"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient")
        params = [
            {"name": "subject", "valueString": f"Patient/{patient}"},
            {"name": "useServerData", "valueBoolean": False},
            {"name": "data", "resource": bundle},
            {"name": "expression", "valueString": "Passed"},
            {"name": "expression", "valueString": "Issues"},
        ]
        resp = self.fhir.client.post(
            f"{self.fhir.base}/Library/{library_id(name)}/$evaluate",
            json={"resourceType": "Parameters", "parameter": params},
            headers={"Content-Type": "application/fhir+json"},
        )
        if resp.status_code >= 400:
            return PrecheckResult(None, [f"pre-check failed to run: HTTP {resp.status_code}"], name)
        passed: bool | None = None
        issues: list[str] = []
        for p in resp.json().get("parameter", []):
            if p.get("name") == "Passed" and "valueBoolean" in p:
                passed = bool(p["valueBoolean"])
            elif p.get("name") == "Issues" and "valueString" in p:
                issues.append(str(p["valueString"]))
            elif p.get("name") == "evaluation error":
                diag = "; ".join(i.get("diagnostics", "") for i in (p.get("resource") or {}).get("issue", []))
                return PrecheckResult(None, [f"pre-check evaluation error: {diag[:300]}"], name)
        return PrecheckResult(passed, issues, name)


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()
