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

import contextlib
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
    """PUT the snapshot's resources (all, or per type only the ids in ``only``). A snapshot of another id rule is
    refused before anything is sent (D-1253 round 3)."""
    from tb_common import id_rule

    id_rule.open_snapshot(directory)
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
    base_url: str,
    directory: Path,
    ledger: Path,
    previous: Path | None = None,
    workers: int = 4,
    full: bool = False,
    back: bool = False,
) -> tuple[int, int]:
    """Make fhir-store hold exactly the snapshot: PUT what is new or changed (everything with ``full``), then DELETE
    ids loaded earlier that the snapshot no longer has. Without a ledger yet (first run after an upgrade) the previous
    snapshot stands in for it, without hashes, so everything loads once. Returns (loaded, deleted)."""
    # T-725 (D-491, review F-4): the load is the build of "fhir" from this night. A night older than the one the
    # store holds is not loaded (a late re-run of an earlier night made the store hold the older night before);
    # the store keeps the newer one and this step reports nothing loaded
    # ``back``: a put-back to the served night after a load of a newer night that did not end (D-489); the ledger
    # lets it through only over a build that never finished
    # review of NEW-B-5: one load of the store at a time (the ledger's build lock, held to the end: a put-back
    # waits for a load that runs and never writes under it), and a put-back the ledger refuses is an error
    with contextlib.ExitStack() as held:
        built, book = _begin_night(directory.name, back, held)
        if built is _OLDER:
            return 0, 0
        out = _sync(base_url, directory, ledger, previous, workers, full)
        _finish_night(built, book)
        return out


def _sync(
    base_url: str, directory: Path, ledger: Path, previous: Path | None, workers: int, full: bool
) -> tuple[int, int]:
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
    return loaded, deleted


_OLDER = object()
_NIGHT = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _begin_night(name: str, back: bool, held: contextlib.ExitStack) -> tuple[Any, Any]:
    """Record the start of the FHIR store's load of the night ``name`` in the generation ledger, under the
    ledger's build lock (kept in ``held`` until the load is over). Returns ``(generation, ledger)``; ``_OLDER``
    when the store holds a newer night (the load is then skipped); ``(None, None)`` when there is no ledger to ask
    (a folder that is not a night, no trial database: the load goes on as before). A ledger that is there and
    cannot be read stops the load (review of T-725, M1: it loaded an older night over a newer one, deletes
    included, while the ledger still said "newer, finished"). A put-back (``back``) that the ledger refuses is
    an error, never "nothing to load": the store then holds a night that is not the served one, and the caller
    must say so (review of NEW-B-5, HIGH-1)."""
    if not _NIGHT.match(name) or not os.environ.get("TB_DB_URL"):
        return None, None
    from tb_common.generation import OlderGeneration

    try:
        from datacore.generations import Built

        book = held.enter_context(Built())
        held.enter_context(book.building("fhir"))
        return book.begin("fhir", name, back=back), book
    except OlderGeneration as exc:
        if back:
            raise RuntimeError(f"fhir-store put-back refused: {exc}") from exc
        log.warning("fhir-store not loaded: %s", exc)
        return _OLDER, None
    except Exception as exc:
        raise RuntimeError(
            f"the generation ledger cannot be read ({type(exc).__name__}): the FHIR store is not loaded"
        ) from exc


def _finish_night(built: Any, book: Any) -> None:
    if built is None or built is _OLDER:
        return
    try:
        ended = book.finish("fhir", built)
    except Exception as exc:  # the store is loaded; the ledger still says "building", which no reader takes
        log.warning("fhir-store load not recorded in the generation ledger (%s)", type(exc).__name__)
        return
    if not ended:
        raise RuntimeError(f"the fhir-store load of {built} was overtaken by another load: it does not count")
