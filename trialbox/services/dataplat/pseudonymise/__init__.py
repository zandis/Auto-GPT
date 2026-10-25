"""L3 pseudonymise (§5.3 L3, §5.14, DP-35, PRIV-10; S1-04).

1. Every source patient key (MRN) of the cycle is resolved through the MPI (a new MRN gets a random ``mpi_id``).
2. Merge events (ADT A40 or a steward merge table) are applied, so two MRNs can share one ``mpi_id``.
3. Every L2 working token is replaced by ``pid = HMAC(K_pid, mpi_id)``. A patient reference that resolves to no
   known identity is quarantined with ``IDN_UNRESOLVED`` (never passed on with an unkeyed id: fail closed).
4. Patient resources that collapse onto one pid after a merge are de-duplicated (the survivor's record is kept).

``mapped = pseudonymised + identity-quarantined + merged`` is an exact equation (§5.9.1 L2 → L3, with the merge
term made explicit). Output is D3: MRNs remain only in the MPI (Z-IDN) and in L0.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from tb_contracts.landing import Equation, ReasonCode

from dataplat.mpi import MergeEvent, Mpi
from dataplat.reconcile import exact
from dataplat.standardise import L2Output, working_token

Resource = dict[str, Any]
_PATIENT_REF = re.compile(r"^Patient/([0-9a-f]{32})$")


@dataclass
class L3Output:
    by_type: dict[str, list[Resource]]
    equations: list[Equation] = field(default_factory=list)
    quarantined: list[tuple[str, str, str]] = field(default_factory=list)  # (resourceType, id, reason)
    merged: int = 0
    total_in: int = 0
    persons: int = 0
    aliases: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {t: len(v) for t, v in sorted(self.by_type.items())}


def _rekey(node: Any, table: dict[str, str], unresolved: list[str]) -> Any:
    if isinstance(node, dict):
        return {k: _rekey(v, table, unresolved) for k, v in node.items()}
    if isinstance(node, list):
        return [_rekey(v, table, unresolved) for v in node]
    if isinstance(node, str):
        if node in table:
            return table[node]
        m = _PATIENT_REF.match(node)
        if m:
            if m.group(1) in table:
                return f"Patient/{table[m.group(1)]}"
            unresolved.append(node)
    return node


def pseudonymise(l2: L2Output, mpi: Mpi, *, merges: Sequence[MergeEvent] = ()) -> L3Output:
    for mrn in l2.patient_keys:
        mpi.register(mrn)
    for ev in sorted(merges, key=lambda e: (e.source_event, e.from_mrn, e.to_mrn)):
        mpi.merge(ev)
    token_to_pid: dict[str, str] = {}
    preferred: set[str] = set()  # tokens whose MRN is the survivor's own identifier
    involved = {m for ev in merges for m in (ev.from_mrn, ev.to_mrn)}
    for mrn in sorted(set(l2.patient_keys) | involved):
        mpi_id = mpi.lookup(mrn)
        if mpi_id is None:
            continue
        tok = working_token(mpi.keys.k_l2, mrn)
        token_to_pid[tok] = mpi.pid(mpi_id)
        if mpi.direct_id("mrn", mrn) == mpi_id:
            preferred.add(tok)
    out: dict[str, list[Resource]] = {}
    quarantined: list[tuple[str, str, str]] = []
    total = 0
    patients: dict[str, tuple[bool, Resource]] = {}
    for rtype in sorted(l2.by_type):
        for res in l2.by_type[rtype]:
            total += 1
            unresolved: list[str] = []
            original_id = str(res.get("id", ""))
            new = _rekey(res, token_to_pid, unresolved)
            if rtype == "Patient" and original_id not in token_to_pid:
                unresolved.append(f"Patient/{original_id}")
            if unresolved:
                quarantined.append((rtype, original_id, ReasonCode.IDN_UNRESOLVED.value))
                continue
            if rtype == "Patient":
                pid = str(new["id"])
                is_pref = original_id in preferred
                if pid not in patients or (is_pref and not patients[pid][0]):
                    patients[pid] = (is_pref, new)
                continue
            out.setdefault(rtype, []).append(new)
    if patients or "Patient" in l2.by_type:
        out["Patient"] = [patients[p][1] for p in sorted(patients)]
    n_patient_in = len(l2.by_type.get("Patient", []))
    n_patient_q = sum(1 for t, _, _ in quarantined if t == "Patient")
    merged = n_patient_in - n_patient_q - len(patients)
    n_out = sum(len(v) for v in out.values())
    eqs = [
        exact(
            "L2→L3",
            "mapped = pseudonymised + identity-quarantined + merged",
            total,
            n_out + len(quarantined) + merged,
        )
    ]
    return L3Output(
        by_type={t: sorted(v, key=lambda r: str(r.get("id"))) for t, v in sorted(out.items())},
        equations=eqs,
        quarantined=sorted(quarantined),
        merged=merged,
        total_in=total,
        persons=len(patients),
        aliases=mpi.aliases(),
    )


__all__ = ["L3Output", "pseudonymise"]
