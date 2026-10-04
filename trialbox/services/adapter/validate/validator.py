"""FHIR validation of a deterministic sample of adapter output (SPEC §3.1: 1 % per nightly run, >0.5 % errors fails).

Primary engine: the HL7 validator CLI (``validator_cli.jar``) running fully offline against a pre-filled package cache
(``tools/fetch_fhir_packages.py``; DECISIONS D-26). Fallback when no JRE/jar is present (developer laptops): a
structural validator (``fhir.resources`` R4B parsing + SPEC §3.1 required elements) — reported as such in
``ingest_report.json`` so a production run can never silently use it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Resource = dict[str, Any]

# SPEC §3.1 elements the engine needs, per resource type (dotted; "a|b" = either)
REQUIRED: dict[str, list[str]] = {
    "Patient": ["id", "birthDate", "gender"],
    "Encounter": ["id", "subject", "class", "period.start", "serviceType", "participant"],
    "Appointment": ["id", "participant", "start", "status", "serviceType"],
    "Condition": ["id", "subject", "code", "onsetDateTime|recordedDate", "clinicalStatus"],
    "Observation": ["id", "subject", "code", "effectiveDateTime", "category"],
    "MedicationRequest": [
        "id",
        "subject",
        "medicationCodeableConcept",
        "authoredOn",
        "status",
        "dispenseRequest.validityPeriod",
    ],
    "Procedure": ["id", "subject", "code", "performedDateTime"],
    "DiagnosticReport": ["id", "subject", "code", "effectiveDateTime", "conclusion"],
    "DocumentReference": ["id", "subject", "date", "type", "content"],
    "Claim": ["patient", "created", "item"],
    "ClaimResponse": ["patient", "created", "outcome"],
    "Practitioner": ["id", "identifier"],
}


def _has(res: Resource, path: str) -> bool:
    for alt in path.split("|"):
        cur: Any = res
        ok = True
        for part in alt.split("."):
            if isinstance(cur, list):
                cur = cur[0] if cur else None
            if not isinstance(cur, dict) or part not in cur or cur[part] in (None, "", [], {}):
                ok = False
                break
            cur = cur[part]
        if ok:
            return True
    return False


def missing_required(res: Resource) -> list[str]:
    return [p for p in REQUIRED.get(res.get("resourceType", ""), []) if not _has(res, p)]


def sample(
    resources: Iterable[Resource], fraction: float = 0.01, minimum_per_type: int = 3, seed: str = "trialbox"
) -> list[Resource]:
    """Deterministic sample: ``fraction`` of resources by hash of type/id, at least ``minimum_per_type`` per type."""
    by_type: dict[str, list[tuple[str, Resource]]] = {}
    for r in resources:
        h = hashlib.sha256(f"{seed}|{r['resourceType']}|{r['id']}".encode()).hexdigest()
        by_type.setdefault(r["resourceType"], []).append((h, r))
    out: list[Resource] = []
    for _, items in sorted(by_type.items()):
        items.sort(key=lambda t: t[0])
        k = max(minimum_per_type, round(len(items) * fraction))
        out.extend(r for _, r in items[:k])
    return out


@dataclass
class ValidationResult:
    validator: str
    sampled: int
    errors: int  # resources with >= 1 error/fatal issue
    messages: list[str] = field(default_factory=list)

    @property
    def error_pct(self) -> float:
        return 100.0 * self.errors / self.sampled if self.sampled else 0.0


class Hl7Validator:
    """Wraps ``java -jar validator_cli.jar`` with an offline package cache."""

    def __init__(
        self, jar: Path, cache_home: Path, igs: list[str] | None = None, xmx: str = "4g", java: str = "java"
    ) -> None:
        self.jar = jar
        self.cache_home = cache_home
        self.igs = igs or []
        self.xmx = xmx
        self.java = java

    @classmethod
    def from_env(cls) -> Hl7Validator | None:
        jar = Path(os.environ.get("TB_HL7_VALIDATOR_JAR", "/opt/hl7/validator_cli.jar"))
        home = Path(os.environ.get("TB_FHIR_PACKAGE_HOME", "/opt/hl7/home"))
        java = os.environ.get("TB_JAVA", "java")
        if not jar.exists() or shutil.which(java) is None or not (home / ".fhir" / "packages").exists():
            return None
        igs = [s for s in os.environ.get("TB_VALIDATOR_IGS", "tw.gov.mohw.twcore#1.0.0").split(",") if s]
        return cls(jar, home, igs, os.environ.get("TB_VALIDATOR_XMX", "4g"), java)

    def validate(self, resources: list[Resource], extra_args: list[str] | None = None) -> ValidationResult:
        if not resources:
            return ValidationResult("hl7-validator", 0, 0)
        with tempfile.TemporaryDirectory(prefix="tbval-") as td:
            files = []
            for i, r in enumerate(resources):
                p = Path(td) / f"r{i:05d}-{r['resourceType']}.json"
                p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
                files.append(p.name)
            out = Path(td) / "out.json"
            cmd = [
                self.java,
                f"-Xmx{self.xmx}",
                f"-Duser.home={self.cache_home}",
                "-jar",
                str(self.jar),
                *files,
                "-version",
                "4.0.1",
                "-tx",
                "n/a",
                "-no-http-access",
                "-output",
                str(out),
            ]
            for ig in self.igs:
                cmd += ["-ig", ig]
            cmd += extra_args or []
            proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=1800, check=False)
            if not out.exists():
                raise RuntimeError(f"HL7 validator failed to run: {proc.stdout[-1500:]}{proc.stderr[-1500:]}")
            return self._parse(json.loads(out.read_text(encoding="utf-8")), len(resources))

    @staticmethod
    def _parse(doc: Resource, n: int) -> ValidationResult:
        oos = [e["resource"] for e in doc.get("entry", [])] if doc["resourceType"] == "Bundle" else [doc]
        errors = 0
        messages: list[str] = []
        for oo in oos:
            fname = next(
                (
                    x.get("valueString", "")
                    for x in oo.get("extension", [])
                    if x.get("url", "").endswith("operationoutcome-file")
                ),
                "?",
            )
            errs = [i for i in oo.get("issue", []) if i.get("severity") in ("error", "fatal")]
            if errs:
                errors += 1
                for i in errs[:3]:
                    text = (i.get("details") or {}).get("text") or i.get("diagnostics", "")
                    loc = (i.get("expression") or i.get("location") or [""])[0]
                    messages.append(f"{fname} {loc}: {text[:300]}")
        return ValidationResult("hl7-validator", n, errors, messages[:200])


class StructuralValidator:
    """Fallback: R4B model parsing + SPEC §3.1 required elements (no profile/terminology checks)."""

    def validate(self, resources: list[Resource]) -> ValidationResult:
        from fhir.resources.R4B import get_fhir_model_class

        errors = 0
        messages: list[str] = []
        for r in resources:
            problems = missing_required(r)
            try:
                get_fhir_model_class(r["resourceType"]).model_validate(r)
            except Exception as exc:  # pydantic validation error text
                problems.append(str(exc).splitlines()[0][:200])
            if problems:
                errors += 1
                messages.append(f"{r['resourceType']}/{r['id']}: {'; '.join(problems)}")
        return ValidationResult("structural-fallback", len(resources), errors, messages[:200])
