"""The JP Core ``$validate`` of the adapter's output, offline and in Python (TB-PLAN-04 step 7, D-137).

Why not the HL7 validator jar: it needs the R4 core package beside JP Core to snapshot JP Core's differential-only
profiles, the box has no internet, and the tests must not need either. So the check reads ``jp_core_rules.json``,
derived at build time from the pinned JP Core 1.1.0 package by ``tools/jpcore_rules.py``, and checks each resource:

1. **The claim.** A resource of a type JP Core profiles (Patient, Practitioner, Encounter, Condition, Observation,
   MedicationRequest, AllergyIntolerance, Procedure, DiagnosticReport) must claim a JP Core profile in
   ``meta.profile``; a TW Core claim on Japanese output is an error (plan v4 F5); a JP Core URL the rules do not know is
   an error.
2. **Base R4.** The resource parses as its R4 type (``fhir.resources`` R4B models: types, required elements,
   choice types; R4B differs from R4 only in resources TrialBox does not produce).
3. **The profile and its parents** (JP_Observation_LabResult -> JP_Observation_Common -> Observation): every
   element's cardinality per parent instance, fixed and pattern values, slices with ``value`` / ``pattern``
   discriminators (their own cardinality and the elements inside them), and ``required`` bindings whose ValueSet
   the package enumerates.
4. **The code systems we hold.** ICD-10-CM codes must be in the full ICD-10-CM list (D-122); a WHO ICD-10 code (the
   system Japan codes in, D-314) not written as a WHO code (``E14.9``, ``M10.97``) is a warning: a code with an
   ICD-10-CM-only shape (``C50.911``, ``M1A.9XX0``) under the WHO URI is listed, never failed; LOINC codes must pass
   the check digit; JLAC10, YJ, HOT9, ATC and MEDIS 病名交換用コード codes must have their shape; when the site's
   licensed release is loaded (``adapter.licensed``), a code missing from it is a warning (a newer code), never an
   error, and so is a MEDIS code the release marks deleted (変更区分 1, D-1261).

Errors fail the resource; warnings are listed. Nothing is dropped: the ingest records the result
(``jp_core_validation.json`` in the snapshot, ``profile_validation`` in the ingest report) and lists every failure.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from tb_common.icd10_who import comparable

Resource = dict[str, Any]
RULES = Path(__file__).resolve().parent / "jp_core_rules.json"
JP = "http://jpfhir.jp/fhir/core/StructureDefinition/"
TW = "https://twcore.mohw.gov.tw/"
PROFILED = (
    "Patient",
    "Practitioner",
    "Encounter",
    "Condition",
    "Observation",
    "MedicationRequest",
    "AllergyIntolerance",
    "Procedure",
    "DiagnosticReport",
)
DEFAULT_PER_TYPE = 50
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10_WHO = "http://hl7.org/fhir/sid/icd-10"
_WHO_SHAPE = re.compile(r"^[A-Z][0-9]{2}(\.[0-9]{1,2})?$")
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"
_SHAPES = {
    "urn:oid:1.2.392.200119.4.504": ("JLAC10", re.compile(r"^[0-9A-Z]{15}([0-9A-Z]{2})?$"), "jlac10"),
    "urn:oid:1.2.392.100495.20.1.73": ("YJ", re.compile(r"^[0-9A-Z]{12}$"), "yj"),
    "urn:oid:1.2.392.200119.4.403.1": ("HOT9", re.compile(r"^\d{9}$"), ""),
    "urn:oid:1.2.392.200119.4.402.1": ("HOT13", re.compile(r"^\d{13}$"), ""),
    "urn:oid:1.2.392.200119.4.101.6": ("MEDIS 病名交換用コード", re.compile(r"^[0-9A-Z]{4}$"), "medis"),
    ATC: ("ATC", re.compile(r"^[A-Z](\d{2}([A-Z]([A-Z](\d{2})?)?)?)?$"), ""),
}


@dataclass
class Issue:
    severity: str  # error | warning
    expression: str
    text: str


@dataclass
class Outcome:
    resource: str  # "<type>/<id>"
    profile: str
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def operation_outcome(self) -> dict[str, Any]:
        """The FHIR ``OperationOutcome`` of ``$validate`` for this resource."""
        issues = [
            {
                "severity": i.severity,
                "code": "invariant" if i.severity == "error" else "informational",
                "diagnostics": i.text,
                "expression": [i.expression],
            }
            for i in self.issues
        ] or [{"severity": "information", "code": "informational", "diagnostics": "no issues"}]
        return {"resourceType": "OperationOutcome", "issue": issues}


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    out: dict[str, Any] = json.loads(RULES.read_text(encoding="utf-8"))
    return out


def validator_name() -> str:
    pkg = rules()["package"]
    return f"jp-core {pkg['id']}#{pkg['version']} (offline structural, D-137)"


@lru_cache(maxsize=1)
def _icd10cm() -> frozenset[str]:
    import pyarrow.parquet as pq

    path = Path(__file__).resolve().parents[2] / "criteria_compiler" / "terminology" / "icd10cm_full.parquet"
    if not path.exists():
        return frozenset()
    return frozenset(
        str(c) for c in pq.read_table(path, columns=["code"], use_threads=False).column("code").to_pylist()
    )


def _medis_current(row: dict[str, Any]) -> bool:
    """D-1261: is a loaded MEDIS row current (変更区分 not 1, deleted in the release)? A row without the column (a
    release loaded before D-1252) counts as current, as it was read before."""
    try:
        extra = json.loads(row.get("extra") or "{}")
    except (TypeError, ValueError):
        return True
    return not (isinstance(extra, dict) and str(extra.get("change") or "").strip() == "1")


def loinc_ok(code: str) -> bool:
    """LOINC's mod-10 check digit (``2160-0``)."""
    m = re.fullmatch(r"(\d{1,7})-(\d)", code)
    if not m:
        return False
    digits = m.group(1)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d = d // 10 + d % 10
        total += d
    return (10 - total % 10) % 10 == int(m.group(2))


# ---------------------------------------------------------------------------------------------- element navigation
def _children(node: Any, name: str) -> list[Any]:
    """Values of ``name`` under one node, flattened; ``x[x]`` matches any ``x<Type>``."""
    if not isinstance(node, dict):
        return []
    if name.endswith("[x]"):
        stem = name[:-3]
        vals = [v for k, v in node.items() if k.startswith(stem) and k[len(stem) : len(stem) + 1].isupper()]
    else:
        vals = [node[name]] if name in node else []
    out: list[Any] = []
    for v in vals:
        out.extend(v if isinstance(v, list) else [v])
    return [v for v in out if v not in (None, "", [], {})]


def _contains(have: Any, want: Any) -> bool:
    """FHIR pattern matching: ``have`` holds at least ``want`` (lists: each wanted item matches some item)."""
    if isinstance(want, dict):
        return isinstance(have, dict) and all(_contains(have.get(k), v) for k, v in want.items())
    if isinstance(want, list):
        items = have if isinstance(have, list) else [have]
        return all(any(_contains(h, w) for h in items) for w in want)
    return bool(have == want)


@dataclass
class _El:
    id: str
    path: str
    min: int | None = None
    max: str | None = None
    value: dict[str, Any] | None = None
    binding: dict[str, Any] | None = None
    slicing: dict[str, Any] | None = None


def _merged(profile_url: str) -> tuple[str, dict[str, _El]]:
    """The profile's elements merged with its JP Core parents' (the child wins), and the resource type."""
    profs = rules()["profiles"]
    chain = []
    url = profile_url
    while url in profs:
        chain.append(profs[url])
        url = profs[url]["base"]
    merged: dict[str, _El] = {}
    for p in reversed(chain):
        for e in p["elements"]:
            el = merged.get(e["id"]) or _El(e["id"], e["path"])
            for k in ("min", "max", "value", "binding", "slicing"):
                if k in e:
                    setattr(el, k, e[k])
            merged[e["id"]] = el
    return chain[0]["type"], merged


def _split(eid: str) -> list[tuple[str, str]]:
    """``"Obs.category:lab.coding"`` -> ``[("category", "lab"), ("coding", "")]`` (the type dropped)."""
    out = []
    for part in eid.split(".")[1:]:
        name, _, sl = part.partition(":")
        out.append((name, sl))
    return out


def _base_problem(exc: Exception) -> str:
    """D-668: what the base model refused, as the element and the kind of problem (pydantic's ``loc`` and ``type``
    of its first error), never its message: the message quotes the value (``input_value='...'``). An error that is
    not pydantic's is its type."""
    try:
        first = exc.errors(include_input=False, include_context=False, include_url=False)[0]  # type: ignore[attr-defined]
        where = ".".join(str(part) for part in first["loc"] if isinstance(part, str | int))
        return f"{where}: {first['type']}"
    except Exception:
        return type(exc).__name__


class JpCoreValidator:
    """Checks resources against JP Core 1.1.0 (see the module text)."""

    name = "jp-core"

    def __init__(self, licensed: dict[str, dict[str, dict[str, str]]] | None = None) -> None:
        self.licensed = licensed if licensed is not None else {}

    # ------------------------------------------------------------------ one resource
    def check(self, res: Resource) -> Outcome:
        rtype = str(res.get("resourceType", ""))
        ref = f"{rtype}/{res.get('id', '?')}"
        claims = [str(p) for p in (res.get("meta") or {}).get("profile") or []]
        jp = [p for p in claims if p.startswith(JP)]
        out = Outcome(ref, jp[0] if jp else "")
        for p in claims:
            if p.startswith(TW):
                out.issues.append(Issue("error", f"{rtype}.meta.profile", f"claims a TW Core profile ({p})"))
        if rtype in PROFILED and not jp:
            out.issues.append(Issue("error", f"{rtype}.meta.profile", "claims no JP Core profile"))
        self._base(res, out)
        for p in jp:
            if p not in rules()["profiles"]:
                out.issues.append(Issue("error", f"{rtype}.meta.profile", f"{p} is not a JP Core 1.1.0 profile"))
                continue
            ptype, elements = _merged(p)
            if ptype != rtype:
                out.issues.append(Issue("error", f"{rtype}.meta.profile", f"{p} profiles {ptype}, not {rtype}"))
                continue
            self._profile(res, rtype, elements, out)
        self._codes(res, rtype, out)
        return out

    @staticmethod
    def _base(res: Resource, out: Outcome) -> None:
        from fhir.resources.R4B import get_fhir_model_class

        try:
            get_fhir_model_class(str(res.get("resourceType"))).model_validate(res)
        except Exception as exc:
            out.issues.append(Issue("error", str(res.get("resourceType")), "base R4: " + _base_problem(exc)))

    def _profile(self, res: Resource, rtype: str, elements: dict[str, _El], out: Outcome) -> None:
        def slice_members(parent: Any, name: str, sl: str, sliced_id: str) -> list[Any]:
            items = _children(parent, name)
            base = elements.get(sliced_id)
            disc = (base.slicing or {}).get("discriminator") if base else None
            if not disc:
                return []
            members = []
            for it in items:
                ok = True
                for d in disc:
                    if d["type"] == "value":
                        want = elements.get(f"{sliced_id}:{sl}.{d['path']}")
                        if want is None or want.value is None:
                            ok = False
                            break
                        got = _children(it, d["path"])
                        ok = ok and bool(got) and got[0] == want.value["value"]
                    elif d["type"] == "pattern" and d["path"] == "$this":
                        want = elements.get(f"{sliced_id}:{sl}")
                        ok = ok and want is not None and want.value is not None and _contains(it, want.value["value"])
                    else:  # type / profile / exists discriminators: not checked offline
                        ok = False
                if ok:
                    members.append(it)
            return members

        def resolvable(sliced_id: str) -> bool:
            """A slice can be told apart offline: its discriminators are ``value`` or ``pattern`` ones."""
            base = elements.get(sliced_id)
            disc = (base.slicing or {}).get("discriminator") if base else None
            return bool(disc) and all(d["type"] in ("value", "pattern") for d in disc or [])

        def instances(eid: str) -> list[Any] | None:
            """Values of an element id (``None`` when a slice cannot be resolved offline)."""
            nodes: list[Any] = [res]
            prefix = rtype
            for name, sl in _split(eid):
                if sl and not resolvable(f"{prefix}.{name}"):
                    return None
                nxt: list[Any] = []
                for n in nodes:
                    nxt.extend(slice_members(n, name, sl, f"{prefix}.{name}") if sl else _children(n, name))
                prefix = f"{prefix}.{name}" + (f":{sl}" if sl else "")
                nodes = nxt
            return nodes

        for eid in sorted(elements, key=lambda i: i.count(".")):
            el = elements[eid]
            if "." not in eid:
                continue
            parent_id, _, last = eid.rpartition(".")
            name, _, sl = last.partition(":")
            parents = [res] if parent_id == rtype else instances(parent_id)
            if parents is None:
                continue
            if sl and not resolvable(f"{parent_id}.{name}"):
                continue
            for p in parents:
                vals = slice_members(p, name, sl, f"{parent_id}.{name}") if sl else _children(p, name)
                if el.min and len(vals) < el.min:
                    what = f"slice {sl} of {name}" if sl else name
                    out.issues.append(Issue("error", eid, f"{what}: at least {el.min} required, {len(vals)} found"))
                if el.max not in (None, "*") and len(vals) > int(str(el.max)):
                    out.issues.append(Issue("error", eid, f"{name}: at most {el.max} allowed, {len(vals)} found"))
                if el.value is not None and not sl:
                    want = el.value["value"]
                    for v in vals:
                        good = v == want if el.value["kind"] == "fixed" else _contains(v, want)
                        if not good:
                            out.issues.append(
                                Issue("error", eid, f"{name} must be {json.dumps(want, ensure_ascii=False)}")
                            )
                if el.binding and el.binding.get("strength") == "required":
                    self._required(eid, el.binding.get("valueSet", ""), vals, out)

    @staticmethod
    def _required(eid: str, vs_url: str, vals: list[Any], out: Outcome) -> None:
        vs = rules()["valuesets"].get(vs_url)
        if not vs or vs.get("codes") is None:
            return
        codes: dict[str, list[str]] = vs["codes"]
        for v in vals:
            codings = (v.get("coding") or []) if isinstance(v, dict) and "coding" in v else [v]
            listed = [c for c in codings if isinstance(c, dict) and c.get("system") in codes]
            if not listed or not any(c.get("code") in codes[c["system"]] for c in listed):
                out.issues.append(Issue("error", eid, f"no code from the required value set {vs_url}"))

    def _codes(self, res: Resource, rtype: str, out: Outcome) -> None:
        """Every coding of a code system we hold: in the list (ICD-10-CM), a valid check digit (LOINC), the shape
        of the code (WHO ICD-10 as a warning, JLAC10, YJ, HOT, MEDIS, ATC), and, when the site's release is loaded,
        in the release."""

        def walk(node: Any, path: str) -> Iterable[tuple[str, dict[str, Any]]]:
            if isinstance(node, dict):
                if "system" in node and "code" in node:
                    yield path, node
                for k, v in node.items():
                    yield from walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for v in node:
                    yield from walk(v, path)

        for path, c in walk({k: v for k, v in res.items() if k != "meta"}, rtype):
            system, code = str(c.get("system") or ""), str(c.get("code") or "")
            if system == ICD10CM:
                cm = _icd10cm()
                if cm and code not in cm:
                    out.issues.append(Issue("error", path, "the code is not an ICD-10-CM code"))
            elif system == ICD10_WHO:
                if not _WHO_SHAPE.match(code):
                    # D-1261: a code as the MEDIS master writes it (E119, E109a) is named with its comparable form
                    as_cm = comparable(code)
                    said = f" (the MEDIS master's form of {as_cm})" if as_cm and as_cm != code else ""
                    out.issues.append(Issue("warning", path, f"the code is not written as a WHO ICD-10 code{said}"))
            elif system == LOINC and path.endswith(".coding"):
                if re.fullmatch(r"L[AGP]\d+-\d", code):  # answer, group and part codes: their own numbering
                    continue
                if not loinc_ok(code):
                    out.issues.append(Issue("error", path, "the code is not a valid LOINC code (check digit)"))
            elif system in _SHAPES:
                label, shape, kind = _SHAPES[system]
                if not shape.match(code):
                    out.issues.append(Issue("error", path, f"the code is not a {label} code"))
                elif kind and self.licensed.get(kind) and code not in self.licensed[kind]:
                    out.issues.append(Issue("warning", path, f"the code is not in the loaded {label} release"))
                elif kind == "medis" and self.licensed.get(kind) and not _medis_current(self.licensed[kind][code]):
                    # D-1261: a code the loaded release marks deleted (変更区分 1) is real but no longer current
                    out.issues.append(Issue("warning", path, f"the code is deleted in the loaded {label} release"))

    # ------------------------------------------------------------------ a sample
    def validate(self, resources: list[Resource]) -> ValidationReport:
        outcomes = [self.check(r) for r in resources]
        return ValidationReport(validator_name(), outcomes)


@dataclass
class ValidationReport:
    validator: str
    outcomes: list[Outcome]

    @property
    def sampled(self) -> int:
        return len(self.outcomes)

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if not o.ok)

    @property
    def error_pct(self) -> float:
        return 100.0 * self.errors / self.sampled if self.sampled else 0.0

    def by_type(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for o in self.outcomes:
            t = out.setdefault(o.resource.split("/", 1)[0], {"sampled": 0, "failed": 0, "warnings": 0})
            t["sampled"] += 1
            t["failed"] += 0 if o.ok else 1
            t["warnings"] += sum(1 for i in o.issues if i.severity == "warning")
        return dict(sorted(out.items()))

    def messages(self, limit: int = 200) -> list[str]:
        """Every failure in plain words: ``<type>/<id> <element>: <what is wrong>`` (errors first)."""
        lines = [
            f"{o.resource} {i.expression}: {i.text}"
            for sev in ("error", "warning")
            for o in self.outcomes
            for i in o.issues
            if i.severity == sev
        ]
        return lines[:limit]

    def as_json(self) -> dict[str, Any]:
        return {
            "validator": self.validator,
            "package": rules()["package"],
            "sampled": self.sampled,
            "failed": self.errors,
            "error_pct": round(self.error_pct, 3),
            "by_type": self.by_type(),
            "messages": self.messages(),
            "failures": [
                {"resource": o.resource, "profile": o.profile, "outcome": o.operation_outcome()}
                for o in self.outcomes
                if not o.ok
            ][:200],
        }


def sample_per_type(
    resources: Iterable[Resource], per_type: int = DEFAULT_PER_TYPE, seed: str = "jp-core"
) -> list[Resource]:
    """Up to ``per_type`` resources of each type, the same ones every run (by a hash of type and id)."""
    from adapter.validate.validator import Sampler

    picker = Sampler(seed, lambda _t: per_type)
    for r in resources:
        picker.add(r)
    return picker.result()


def validate_snapshot(
    ndjson_dir: Path, per_type: int = DEFAULT_PER_TYPE, licensed: dict[str, dict[str, dict[str, str]]] | None = None
) -> ValidationReport:
    """``$validate`` over a sample of a written NDJSON snapshot (``<lake>/ndjson/<snapshot>/``)."""
    from adapter.ndjson import read_type

    if not ndjson_dir.is_dir():
        raise FileNotFoundError(f"no snapshot at {ndjson_dir}")
    resources = (r for p in sorted(ndjson_dir.glob("*.ndjson")) for r in read_type(ndjson_dir, p.stem))
    return JpCoreValidator(licensed).validate(sample_per_type(resources, per_type))
