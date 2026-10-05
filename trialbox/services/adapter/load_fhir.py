"""Load NDJSON snapshots into fhir-store with batch transactions of 500 PUT entries (SPEC §4.4), and delete what left
the source.

fhir-store must mirror the snapshot the lake is built from, or CQL (SCREEN / NAV default) and SQL disagree: a
diagnosis deleted in the HIS would keep excluding (or including) a patient. PUT alone never removes anything, so a
ledger (``<lake>/fhir_ledger/<Type>.txt``) remembers the ids loaded; ids in the ledger but not in the new snapshot are
deleted (dependents first). The ledger is widened before loading, so a run that fails half way loses nothing."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from adapter.ndjson import read_type

log = logging.getLogger("adapter.load")
LOAD_ORDER = [
    "Organization",
    "Practitioner",
    "Patient",
    "Coverage",
    "Encounter",
    "Appointment",
    "Condition",
    "Observation",
    "MedicationRequest",
    "Procedure",
    "DiagnosticReport",
    "DocumentReference",
    "Claim",
    "ClaimResponse",
]
BATCH = 500


def _delete_bundle(refs: list[str]) -> dict[str, Any]:
    entries = [{"request": {"method": "DELETE", "url": r}} for r in refs]
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def _bundle(resources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"resource": r, "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"}} for r in resources
        ],
    }


def post_batches(base_url: str, resources: Iterable[dict[str, Any]], workers: int = 4, timeout: float = 600) -> int:
    batches: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for r in resources:
        cur.append(r)
        if len(cur) == BATCH:
            batches.append(cur)
            cur = []
    if cur:
        batches.append(cur)
    headers = {"Content-Type": "application/fhir+json"}

    def send(batch: list[dict[str, Any]]) -> int:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(base_url.rstrip("/"), json=_bundle(batch), headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"fhir-store transaction failed ({resp.status_code}): {resp.text[:500]}")
        return len(batch)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return sum(pool.map(send, batches))


def load_snapshot(base_url: str, directory: Path, workers: int = 4) -> int:
    total = 0
    present = {p.stem for p in directory.glob("*.ndjson")}
    for rtype in LOAD_ORDER + sorted(present - set(LOAD_ORDER)):
        if rtype in present:
            n = post_batches(base_url, read_type(directory, rtype), workers)
            log.info("loaded", extra={"type": rtype, "count": n})
            total += n
    return total


def snapshot_ids(directory: Path) -> dict[str, set[str]]:
    return {p.stem: {str(r["id"]) for r in read_type(directory, p.stem)} for p in sorted(directory.glob("*.ndjson"))}


def _read_ledger(ledger: Path) -> dict[str, set[str]]:
    if not ledger.is_dir():
        return {}
    return {p.stem: set(p.read_text(encoding="utf-8").split()) for p in sorted(ledger.glob("*.txt"))}


def _write_ledger(ledger: Path, ids: dict[str, set[str]]) -> None:
    ledger.mkdir(parents=True, exist_ok=True)
    for p in ledger.glob("*.txt"):
        if p.stem not in ids:
            p.unlink()
    for rtype, values in ids.items():
        tmp = ledger / f".{rtype}.tmp"
        tmp.write_text("".join(f"{v}\n" for v in sorted(values)), encoding="utf-8")
        tmp.replace(ledger / f"{rtype}.txt")


def delete_refs(base_url: str, refs: list[str], timeout: float = 600) -> int:
    headers = {"Content-Type": "application/fhir+json"}
    with httpx.Client(timeout=timeout) as client:
        for i in range(0, len(refs), BATCH):
            chunk = refs[i : i + BATCH]
            resp = client.post(base_url.rstrip("/"), json=_delete_bundle(chunk), headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"fhir-store delete failed ({resp.status_code}): {resp.text[:500]}")
    return len(refs)


def sync_snapshot(
    base_url: str, directory: Path, ledger: Path, previous: Path | None = None, workers: int = 4
) -> tuple[int, int]:
    """Make fhir-store hold exactly the snapshot: PUT everything, then DELETE ids loaded earlier that the snapshot no
    longer has. Without a ledger yet (first run after an upgrade) the previous snapshot stands in for it. Returns
    (loaded, deleted)."""
    current = snapshot_ids(directory)
    known = _read_ledger(ledger)
    if not known and previous is not None and previous.is_dir():
        known = snapshot_ids(previous)
    _write_ledger(ledger, {t: known.get(t, set()) | current.get(t, set()) for t in set(known) | set(current)})
    loaded = load_snapshot(base_url, directory, workers)
    order = list(reversed(LOAD_ORDER)) + sorted(set(known) - set(LOAD_ORDER))
    stale = [f"{t}/{i}" for t in order for i in sorted(known.get(t, set()) - current.get(t, set()))]
    deleted = delete_refs(base_url, stale) if stale else 0
    if deleted:
        log.info("deleted", extra={"count": deleted})
    _write_ledger(ledger, current)
    return loaded, deleted
