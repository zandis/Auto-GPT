"""FHIR validation of a deterministic sample of adapter output (SPEC §3.1: 1 % per nightly run, >0.5 % errors fails).

Primary engine: the HL7 validator CLI (``validator_cli.jar``) running fully offline against a pre-filled package cache
(``tools/fetch_fhir_packages.py``; DECISIONS D-26). Fallback when no JRE/jar is present (developer laptops): a
structural validator (``fhir.resources`` R4B parsing + SPEC §3.1 required elements) — reported as such in
``ingest_report.json`` so a production run can never silently use it.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Resource = dict[str, Any]

# SPEC §3.1 elements the engine needs, per resource type (dotted; "a|b" = either)
REQUIRED: dict[str, list[str]] = {
    "Patient": ["id", "birthDate", "gender"],
    "Encounter": ["id", "subject", "class", "period.start", "serviceType", "participant"],
    "Appointment": ["id", "participant", "start", "status", "serviceType"],
    # D-587: a diagnosis whose status code nobody knows has no clinical status and is "unconfirmed" instead
    "Condition": ["id", "subject", "code", "onsetDateTime|recordedDate", "clinicalStatus|verificationStatus"],
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


CAP_ENV = "TB_VALIDATION_SAMPLE_CAP"


def sample_cap(max_pct: float, env: Mapping[str, str] | None = None) -> int | None:
    """The most resources of one type the gate's sample takes (T-693, D-457), or None for no cap.

    ``TB_VALIDATION_SAMPLE_CAP`` when set (``0``: no cap). Else derived from the gate's own limit ``max_pct``
    (``validation_error_max_pct``, in percent): the sample size at which the standard error of the measured failure
    share is a fifth of the limit, ``ceil(25 x (1 - p) / p)``: 4,975 at 0.5 %. A limit of 0 or of 100 % and more
    gives no cap (there is nothing to derive one from)."""
    e = os.environ if env is None else env
    raw = (e.get(CAP_ENV) or "").strip()
    if raw:
        try:
            cap = int(raw)
        except ValueError as exc:
            raise ValueError(f"{CAP_ENV} must be a whole number of resources per type (0: no cap)") from exc
        if cap < 0:
            raise ValueError(f"{CAP_ENV} must be a whole number of resources per type (0: no cap)")
        return cap or None
    p = max_pct / 100.0
    if not 0.0 < p < 1.0:
        return None
    return math.ceil(25.0 * (1.0 - p) / p)


def sample_size(n: int, fraction: float, minimum_per_type: int = 3, cap: int | None = None) -> int:
    """How many of a type's ``n`` resources the sample takes: its share, at least ``minimum_per_type``, at most
    ``cap`` (never under the minimum), never more than there are. One rule for the night and the back-fill."""
    k = max(minimum_per_type, round(n * fraction))
    if cap is not None:
        k = min(k, max(cap, minimum_per_type))
    return min(n, k)


def capped_types(
    counts: Mapping[str, int], fraction: float, minimum_per_type: int = 3, cap: int | None = None
) -> dict[str, int]:
    """The resource types the cap cut, with the number of their resources (for the night's report)."""
    return {
        t: n
        for t, n in sorted(counts.items())
        if sample_size(n, fraction, minimum_per_type, cap) < sample_size(n, fraction, minimum_per_type, None)
    }


def sample(
    resources: Iterable[Resource],
    fraction: float = 0.01,
    minimum_per_type: int = 3,
    seed: str = "trialbox",
    cap_per_type: int | None = None,
) -> list[Resource]:
    """Deterministic sample: ``fraction`` of resources by hash of type/id, at least ``minimum_per_type`` per type
    and at most ``cap_per_type`` (T-693, D-457; None: no cap). A type under the cap is sampled exactly as without."""
    items = list(resources)
    counts: dict[str, int] = {}
    for r in items:
        counts[r["resourceType"]] = counts.get(r["resourceType"], 0) + 1
    picker = Sampler(seed, lambda t: sample_size(counts.get(t, 0), fraction, minimum_per_type, cap_per_type))
    for r in items:
        picker.add(r)
    return picker.result()


class Sampler:
    """T-692 (D-473): a hash sample taken from a stream. Per type the ``k_of(type)`` resources with the smallest
    ``sha256(seed|type|id)`` (the earlier one first on a tie), in type order: the same resources as sorting all of
    them by that hash, holding only the ``k`` kept so far."""

    def __init__(self, seed: str, k_of: Callable[[str], int]) -> None:
        self.seed, self.k_of = seed, k_of
        self._heaps: dict[str, list[tuple[int, int, Resource]]] = {}
        self._seq = 0

    def add(self, r: Resource) -> None:
        rtype = str(r.get("resourceType"))
        k = self.k_of(rtype)
        self._seq += 1
        if k <= 0:
            return
        h = int(hashlib.sha256(f"{self.seed}|{r.get('resourceType')}|{r.get('id')}".encode()).hexdigest(), 16)
        heap = self._heaps.setdefault(rtype, [])
        entry = (-h, -self._seq, r)  # a max-heap: the largest kept hash is the first one out
        if len(heap) < k:
            heapq.heappush(heap, entry)
        elif entry[:2] > heap[0][:2]:
            heapq.heapreplace(heap, entry)

    def result(self) -> list[Resource]:
        out: list[Resource] = []
        for _, heap in sorted(self._heaps.items()):
            out.extend(r for _, _, r in sorted(heap, key=lambda e: (-e[0], -e[1])))
        return out


@dataclass
class ValidationResult:
    validator: str
    sampled: int
    errors: int  # resources with >= 1 error/fatal issue
    messages: list[str] = field(default_factory=list)
    per_file: dict[int, list[str]] = field(default_factory=dict)  # resource index -> error messages
    # T-619a: resource index -> the elements the validator matched to no slice of the profile (its information
    # "does not match any known slice"), so a check can tell a filled slice from an open one
    unsliced: dict[int, list[str]] = field(default_factory=dict)
    # U4: the sampled Patients and those of them with no birthDate (its own class, not in ``errors``)
    patients: int = 0
    no_birthdate: int = 0

    @property
    def error_pct(self) -> float:
        return 100.0 * self.errors / self.sampled if self.sampled else 0.0


#: U4 (REAL100K §3, REAL2 Q2): a Patient with no birthDate is its own class, not a validation error. The twin carries
#: it on 7.1 % of persons, which decided every night's hold against the 0.5 % gate by sampling chance; an age criterion
#: reads such a patient as unknown, never as met. The class is counted against the sampled Patients (the Patient table
#: is re-read whole on a delta night) and holds above its own limit: a broken feed empties the field for most.
NO_BIRTHDATE_MAX_PCT = 25.0
_BIRTHDATE_STAND_IN = "1900-01-01"  # only what the validator is shown: it still judges every other element


def validate_sample(validator: Any, resources: list[Resource]) -> ValidationResult:
    """``validator.validate`` with the absent-birthDate class counted apart (U4): a Patient without one is shown to the
    validator with a stand-in date, so another error of that Patient still counts."""
    patients = [r for r in resources if r.get("resourceType") == "Patient"]
    absent = {id(r) for r in patients if not _has(r, "birthDate")}
    res: ValidationResult = validator.validate(
        [{**r, "birthDate": _BIRTHDATE_STAND_IN} if id(r) in absent else r for r in resources]
    )
    res.patients, res.no_birthdate = len(patients), len(absent)
    return res


def no_birthdate_hold(res: ValidationResult, max_pct: float = NO_BIRTHDATE_MAX_PCT) -> str | None:
    """The hold of the absent-birthDate class, or None under its limit."""
    pct = 100.0 * res.no_birthdate / res.patients if res.patients else 0.0
    if pct <= max_pct:
        return None
    return f"Patient.birthDate absent on {pct:.2f}% of sampled patients exceeds {max_pct}%"


# files per ``java`` run: far under the kernel's argument limit (about 65,000 names of 32 bytes in 2 MiB), and a size
# the 1,800 s limit of one run was set for (the 5,000-patient hospital's whole sample is under it)
BATCH = 5000


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
        """One ``java`` run per :data:`BATCH` resources: the sample grows with the hospital (1 % of the load), and one
        command line holds only about 65,000 file names (``ARG_MAX``). A file keeps its index in the whole sample."""
        if not resources:
            return ValidationResult("hl7-validator", 0, 0)
        total = ValidationResult("hl7-validator", len(resources), 0)
        for start in range(0, len(resources), BATCH):
            part = self._validate_batch(resources[start : start + BATCH], start, extra_args)
            total.errors += part.errors
            total.messages = (total.messages + part.messages)[:200]
            total.per_file.update(part.per_file)
            total.unsliced.update(part.unsliced)
        return total

    def _validate_batch(self, resources: list[Resource], start: int, extra_args: list[str] | None) -> ValidationResult:
        with tempfile.TemporaryDirectory(prefix="tbval-") as td:
            files = []
            for i, r in enumerate(resources, start):
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
        per_file: dict[int, list[str]] = {}
        unsliced: dict[int, list[str]] = {}
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
            m = re.search(r"(?:^|[\\/])r(\d{5,})-[A-Za-z]+\.json$", fname)
            if m:
                unsliced[int(m.group(1))] = [
                    (i.get("expression") or i.get("location") or [""])[0]
                    for i in oo.get("issue", [])
                    if "does not match any known slice" in ((i.get("details") or {}).get("text") or "")
                ]
                per_file[int(m.group(1))] = [
                    f"{(i.get('expression') or i.get('location') or [''])[0]}: "
                    f"{((i.get('details') or {}).get('text') or i.get('diagnostics', ''))[:300]}"
                    for i in errs
                ]
            if errs:
                errors += 1
                for i in errs[:3]:
                    messages.append(_issue_line(fname, i))
        return ValidationResult("hl7-validator", n, errors, messages[:200], per_file, unsliced)


_FILE = re.compile(r"r\d{5,}-[A-Za-z]+\.json")
# An element as the validator writes it (D-669, D-671): names joined by dots, each with at most one numbered place
# (``coding[0]``) or the choice mark (``value[x]``), and after a name the validator's own way to name a choice's
# type, once (``value.ofType(Quantity)``). A name and a type's name are one word of the plain letters and digits
# (A-Z, a-z, 0-9), a place is a number in plain digits: no value of a row.
_NAME = r"[A-Za-z][A-Za-z0-9]*"
_ELEMENT = rf"{_NAME}(?:\[[0-9]+\]|\[x\])?(?:\.ofType\({_NAME}\))?"
_PLACE = re.compile(rf"{_ELEMENT}(?:\.{_ELEMENT})*")
_KIND = re.compile(r"[a-z][a-z-]*")
_MESSAGE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
_MESSAGE_ID_URL = "http://hl7.org/fhir/StructureDefinition/operationoutcome-message-id"


def _issue_line(fname: str, issue: dict[str, Any]) -> str:
    """One line of the night's ``validation.messages`` (NEW-B-28, D-669): the sample file, the element, the kind
    of problem (the issue's ``code``) and the validator's message id when it gives one. **Never the validator's
    sentence** (``details.text``, ``diagnostics``): it quotes what it refuses (``Unknown Code 'N18.30'``), and the
    night's report travels to the console and the mail. Each part is kept only in its own shape (a sample file's
    name, an element path, a code); anything else is ``?`` or left out."""

    def token(value: object, shape: re.Pattern[str]) -> str:
        return value if isinstance(value, str) and shape.fullmatch(value) else ""

    name = token(fname.replace("\\", "/").rsplit("/", 1)[-1], _FILE) or "?"
    places = issue.get("expression") or issue.get("location") or [""]
    place = token(places[0] if isinstance(places, list) and places else "", _PLACE) or "?"
    kind = token(issue.get("code"), _KIND) or "error"
    ext = issue.get("extension")
    ids = [x.get("valueCode") for x in (ext if isinstance(ext, list) else []) if isinstance(x, dict)
           and x.get("url") == _MESSAGE_ID_URL]  # fmt: skip
    mid = token(ids[0], _MESSAGE_ID) if ids else ""
    return f"{name} {place}: {kind}" + (f" ({mid})" if mid else "")


def _count_line(count: int, model: str) -> str:
    """What the night's report keeps of a resource the R4B model refused (D-669): pydantic's count line
    ("1 validation error for Patient"), made from the error's own count and model name (typed fields), never from
    its text (its other lines quote the value). A model name that is not a plain name is not kept."""
    if not re.fullmatch(r"[A-Za-z]+", model):
        return "ValidationError"
    return f"{count} validation error{'' if count == 1 else 's'} for {model}"


class StructuralValidator:
    """Fallback: R4B model parsing + SPEC §3.1 required elements (no profile/terminology checks)."""

    def validate(self, resources: list[Resource]) -> ValidationResult:
        from fhir.resources.R4B import get_fhir_model_class
        from pydantic import ValidationError

        errors = 0
        messages: list[str] = []
        for r in resources:
            problems = missing_required(r)
            try:
                get_fhir_model_class(r["resourceType"]).model_validate(r)
            except ValidationError as exc:  # the count and the model name only: typed fields, no text
                problems.append(_count_line(exc.error_count(), str(exc.title)))
            except Exception as exc:
                problems.append(type(exc).__name__)
            if problems:
                errors += 1
                messages.append(f"{r['resourceType']}/{r['id']}: {'; '.join(problems)}")
        return ValidationResult("structural-fallback", len(resources), errors, messages[:200])
