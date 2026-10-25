"""L2 standardise (§5.3 L2; S1-04). Wraps the v1 adapter (see the deviation note in ``dataplat/__init__``).

* Tabular sources (``format: csv``): the L1 accepted rows go through the v1 declarative mapping engine
  (``adapter.mapping.engine``: ``Mapping.normalize`` then ``Mapper``) to FHIR R4 resources.
* FHIR bulk sources: the MIMIC-IV demo goes through the v1 normaliser (``adapter.mapping.mimic``) and
  ``adapter.pipeline.pseudonymise_bulk`` (ids and references re-keyed, direct identifiers dropped).

Patient references at L2 are **working tokens** ``hex(HMAC(K_l2, MRN))[:32]`` keyed with an L2-only key held in
Z-IDN, not pids: the set stays D4 and L3 replaces every token with ``pid = HMAC(K_pid, mpi_id)``. Undated
medication orders are dropped with a reason, as in v1. The working set is written with the v1 NDJSON writer, and a
deterministic 1 % sample is profile-checked with the v1 structural validator (§5.9.3 condition 4).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from tb_common.crypto import pid_for_mrn
from tb_contracts.landing import Equation

from dataplat.contracts import DataContract
from dataplat.reconcile import exact, field_value

Resource = dict[str, Any]
Row = dict[str, Any]

V1_DEMO_MAPPING = Path(__file__).resolve().parents[2] / "adapter" / "mapping" / "tw_core" / "demo_his.yaml"


@dataclass
class L2Output:
    source: str
    by_type: dict[str, list[Resource]]
    patient_keys: list[str]  # source patient identifiers (MRNs) of the patient table, sorted
    equations: list[Equation] = field(default_factory=list)
    drops: dict[str, int] = field(default_factory=dict)
    mapping_spec: str = ""
    validation_error_pct: float = 0.0
    validation_sampled: int = 0
    validation_messages: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {t: len(v) for t, v in sorted(self.by_type.items())}


def working_token(k_l2: bytes, mrn: str) -> str:
    """The L2 patient token of an MRN (D4 working key, replaced at L3)."""
    return pid_for_mrn(k_l2, mrn)


def _sha_files(paths: Sequence[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
    return "sha256:" + h.hexdigest()


def _undated_order(r: Resource) -> bool:
    period = (r.get("dispenseRequest") or {}).get("validityPeriod") or {}
    return r.get("resourceType") == "MedicationRequest" and not r.get("authoredOn") and not period.get("start")


def _drop_undated(by_type: dict[str, list[Resource]], drops: Counter[str]) -> None:
    meds = by_type.get("MedicationRequest", [])
    kept = [r for r in meds if not _undated_order(r)]
    if len(kept) != len(meds):
        drops["MedicationRequest: no authoredOn and no validity start (v1 rule)"] += len(meds) - len(kept)
        by_type["MedicationRequest"] = kept


def standardise_tabular(
    source: str,
    accepted: Mapping[str, list[Row]],
    *,
    k_l2: bytes,
    site_id: str,
    mapping_path: Path = V1_DEMO_MAPPING,
) -> L2Output:
    from adapter.mapping.engine import Mapper, Mapping

    mapping = Mapping.load(mapping_path)
    mapper = Mapper(mapping, k_l2, site_id)
    by_type: dict[str, list[Resource]] = {}
    for res in mapper.static_resources():
        by_type.setdefault(res["resourceType"], []).append(res)
    drops: Counter[str] = Counter()
    equations: list[Equation] = []
    patient_keys: set[str] = set()
    for table, tspec in mapping.tables.items():
        rows = accepted.get(table, [])
        mapped_rows = 0
        for raw in rows:
            row = mapping.normalize(table, raw)
            out = list(mapper.map_table(table, iter([row])))
            if out:
                mapped_rows += 1
            for res in out:
                by_type.setdefault(res["resourceType"], []).append(res)
        dropped = len(rows) - mapped_rows
        if dropped:
            drops[f"{table}: rows filtered by the mapping spec"] += dropped
        equations.append(exact("L1→L2", "accepted = mapped + explicit drops", len(rows), mapped_rows + dropped, table))
        if table == "patient":
            key = str(tspec.get("key") or "mrn")
            patient_keys = {str(mapping.normalize(table, r).get(key) or "").strip() for r in rows} - {""}
    _drop_undated(by_type, drops)
    files = [mapping_path]
    if mapping_path != V1_DEMO_MAPPING and V1_DEMO_MAPPING.exists():
        files.append(V1_DEMO_MAPPING)
    return L2Output(
        source=source,
        by_type={t: v for t, v in sorted(by_type.items())},
        patient_keys=sorted(patient_keys),
        equations=equations,
        drops=dict(sorted(drops.items())),
        mapping_spec=_sha_files(files),
    )


def standardise_mimic(
    source: str,
    accepted: Mapping[str, list[Resource]],
    *,
    k_l2: bytes,
    window_start: date,
    window_end: date,
) -> L2Output:
    from adapter.mapping.mimic.normalise import TABLES, MimicNormaliser, MimicTables
    from adapter.pipeline import pseudonymise_bulk

    raw: dict[str, list[Resource]] = {}
    for items in accepted.values():
        for r in items:
            raw.setdefault(str(r["resourceType"]), []).append(r)
    norm = MimicNormaliser(MimicTables.load(), window_start, window_end)
    normalised = norm.normalise(raw)
    patient_keys = sorted(str(r["id"]) for r in normalised.get("Patient", []))
    by_type: dict[str, list[Resource]] = {}
    for r in pseudonymise_bulk((r for t in sorted(normalised) for r in normalised[t]), k_l2):
        by_type.setdefault(r["resourceType"], []).append(r)
    drops: Counter[str] = Counter()
    equations: list[Equation] = []
    for rtype in sorted(set(raw) | set(by_type)):
        n_in = len(raw.get(rtype, []))
        n_out = len(normalised.get(rtype, []))
        if n_in > n_out:
            drops[f"{rtype}: consumed or out of scope in the MIMIC normaliser"] += n_in - n_out
        equations.append(
            exact("L1→L2", "accepted = mapped + explicit drops", n_in, n_out + max(n_in - n_out, 0), rtype)
        )
    _drop_undated(by_type, drops)
    return L2Output(
        source=source,
        by_type={t: v for t, v in sorted(by_type.items())},
        patient_keys=patient_keys,
        equations=equations,
        drops=dict(sorted(drops.items())),
        mapping_spec=_sha_files(sorted(TABLES.glob("*.csv"))),
    )


def profile_check(out: L2Output, fraction: float = 0.01) -> None:
    """Deterministic sample (v1 ``sample``) through the v1 structural validator; fills the error rate."""
    from adapter.validate.validator import StructuralValidator, sample

    picked = sample((r for items in out.by_type.values() for r in items), fraction)
    res = StructuralValidator().validate(picked)
    out.validation_error_pct = round(res.error_pct, 3)
    out.validation_sampled = res.sampled
    out.validation_messages = res.messages[:50]


def write_working_set(out: L2Output, directory: Path) -> dict[str, int]:
    """Write the L2 working set with the v1 NDJSON writer (sorted by id, canonical JSON)."""
    from adapter.ndjson import write_snapshot

    return write_snapshot(directory, out.by_type)


def patient_key_values(rows: Sequence[Row], contract: DataContract) -> list[str]:
    col = contract.keys.patient
    if not col:
        return []
    return sorted({str(v).strip() for r in rows if (v := field_value(r, col)) not in (None, "")})


__all__ = [
    "V1_DEMO_MAPPING",
    "L2Output",
    "patient_key_values",
    "profile_check",
    "standardise_mimic",
    "standardise_tabular",
    "working_token",
    "write_working_set",
]
