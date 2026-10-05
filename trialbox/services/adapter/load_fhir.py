"""Load NDJSON snapshots into fhir-store with batch transactions of 500 PUT entries (SPEC §4.4)."""

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
