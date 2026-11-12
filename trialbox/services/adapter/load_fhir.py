"""Load NDJSON snapshots into fhir-store with batch transactions of 500 PUT entries (SPEC §4.4), and delete what left
the source.

fhir-store must mirror the snapshot the lake is built from, or CQL (SCREEN / NAV default) and SQL disagree: a
diagnosis deleted in the HIS would keep excluding (or including) a patient. PUT alone never removes anything, so a
ledger (``<lake>/fhir_ledger/<Type>.txt``) remembers the ids loaded; ids in the ledger but not in the new snapshot are
deleted (dependents first). The ledger is widened before loading, so a run that fails half way loses nothing.

Delta loads (TB-PLAN-03 step 7, D-122): the ledger also keeps a content hash per id (``<id>\t<sha256>``), and a
night PUTs only the resources that are new or whose content changed. A full 500k-patient reload took about 8 h on
HAPI (TB-REC-02); a night where 1 % of patients changed now sends about 1 % of the resources. A ledger line without a
hash (written before D-122) counts as changed, so the first night after the upgrade is one full load."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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


def load_snapshot(base_url: str, directory: Path, workers: int = 4, only: dict[str, set[str]] | None = None) -> int:
    """PUT the snapshot's resources (all, or per type only the ids in ``only``)."""
    total = 0
    present = {p.stem for p in directory.glob("*.ndjson")}
    for rtype in LOAD_ORDER + sorted(present - set(LOAD_ORDER)):
        if rtype not in present:
            continue
        if only is not None and not only.get(rtype):
            continue
        rows: Iterable[dict[str, Any]] = read_type(directory, rtype)
        if only is not None:
            want = only[rtype]
            rows = (r for r in rows if str(r["id"]) in want)
        n = post_batches(base_url, rows, workers)
        log.info("loaded", extra={"type": rtype, "count": n})
        total += n
    return total


def content_hash(resource: dict[str, Any]) -> str:
    """Canonical JSON hash of one resource, ignoring ``meta`` (the store sets versionId and lastUpdated)."""
    body = {k: v for k, v in resource.items() if k != "meta"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def snapshot_hashes(directory: Path) -> dict[str, dict[str, str]]:
    return {
        p.stem: {str(r["id"]): content_hash(r) for r in read_type(directory, p.stem)}
        for p in sorted(directory.glob("*.ndjson"))
    }


def snapshot_ids(directory: Path) -> dict[str, set[str]]:
    return {p.stem: {str(r["id"]) for r in read_type(directory, p.stem)} for p in sorted(directory.glob("*.ndjson"))}


def _read_ledger(ledger: Path) -> dict[str, dict[str, str]]:
    """``{type: {id: hash}}``; a line written before D-122 has no hash (``""``)."""
    if not ledger.is_dir():
        return {}
    out: dict[str, dict[str, str]] = {}
    for p in sorted(ledger.glob("*.txt")):
        rows: dict[str, str] = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            rid, _, digest = line.strip().partition("\t")
            if rid:
                rows[rid] = digest
        out[p.stem] = rows
    return out


def _write_ledger(ledger: Path, ids: dict[str, dict[str, str]]) -> None:
    ledger.mkdir(parents=True, exist_ok=True)
    for p in ledger.glob("*.txt"):
        if p.stem not in ids:
            p.unlink()
    for rtype, values in ids.items():
        tmp = ledger / f".{rtype}.tmp"
        tmp.write_text("".join(f"{v}\t{values[v]}\n" for v in sorted(values)), encoding="utf-8")
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
    base_url: str, directory: Path, ledger: Path, previous: Path | None = None, workers: int = 4, full: bool = False
) -> tuple[int, int]:
    """Make fhir-store hold exactly the snapshot: PUT what is new or changed (everything with ``full``), then DELETE
    ids loaded earlier that the snapshot no longer has. Without a ledger yet (first run after an upgrade) the previous
    snapshot stands in for it, without hashes, so everything loads once. Returns (loaded, deleted)."""
    # T-725 (D-491, review F-4): the load is the build of "fhir" from this night. A night older than the one the
    # store holds is not loaded (a late re-run of an earlier night made the store hold the older night before);
    # the store keeps the newer one and this step reports nothing loaded
    built = _begin_night(directory.name)
    if built is _OLDER:
        return 0, 0
    current = snapshot_hashes(directory)
    known = _read_ledger(ledger)
    if not known and previous is not None and previous.is_dir():
        known = {t: dict.fromkeys(ids, "") for t, ids in snapshot_ids(previous).items()}
    changed = {t: {i for i, h in rows.items() if full or known.get(t, {}).get(i) != h} for t, rows in current.items()}
    # widen first: every id stays known; a changed id keeps its old hash until it is loaded, so a failed night
    # reloads it the next night
    widened = {t: dict(known.get(t, {})) for t in set(known) | set(current)}
    for t, rows in current.items():
        for i in rows:
            widened[t].setdefault(i, "")
    _write_ledger(ledger, widened)
    loaded = load_snapshot(base_url, directory, workers, only=changed)
    unchanged = sum(len(r) for r in current.values()) - loaded
    log.info("delta load", extra={"loaded": loaded, "unchanged": unchanged})
    order = list(reversed(LOAD_ORDER)) + sorted(set(known) - set(LOAD_ORDER))
    stale = [f"{t}/{i}" for t in order for i in sorted(set(known.get(t, {})) - set(current.get(t, {})))]
    deleted = delete_refs(base_url, stale) if stale else 0
    if deleted:
        log.info("deleted", extra={"count": deleted})
    _write_ledger(ledger, current)
    _finish_night(built)
    return loaded, deleted


_OLDER = object()
_NIGHT = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _begin_night(name: str) -> Any:
    """Record the start of the FHIR store's load of the night ``name`` in the generation ledger; ``_OLDER`` when
    the store holds a newer night (the load is then skipped), None when there is no ledger to ask (a folder that
    is not a night, no trial database, a store that cannot be reached: the load goes on as before)."""
    if not _NIGHT.match(name) or not os.environ.get("TB_DB_URL"):
        return None
    from tb_common.generation import OlderGeneration

    try:
        from datacore.generations import Built

        with Built() as ledger:
            return ledger.begin("fhir", name)
    except OlderGeneration as exc:
        log.warning("fhir-store not loaded: %s", exc)
        return _OLDER
    except Exception as exc:
        log.warning("fhir-store load not recorded in the generation ledger (%s)", type(exc).__name__)
        return None


def _finish_night(built: Any) -> None:
    if built is None or built is _OLDER:
        return
    try:
        from datacore.generations import Built

        with Built() as ledger:
            ledger.finish("fhir", built)
    except Exception as exc:
        log.warning("fhir-store load not recorded in the generation ledger (%s)", type(exc).__name__)
