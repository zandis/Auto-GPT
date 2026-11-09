"""FHIR NDJSON snapshot files: ``<lake>/ndjson/<snapshot>/<ResourceType>.ndjson`` (one resource per line).

Files are written sorted by id with canonical JSON so the same input produces identical bytes (SPEC §11.2
reproducibility). A delta run merges its resources over the previous snapshot (upsert by id) and drops the
*tombstones*: the ids the source says were deleted in the delta window (SS-MIX2 flag ``0``, a FHIR Bulk ``deleted``
entry, a ``deleted`` column in a CSV or SQL export; dataflow review P0-1, WS-03.7). Without them a record removed at
the hospital stayed in every later snapshot until the next full run. The ids dropped are listed in
``tombstones.json`` beside the snapshot (a JSON object, not NDJSON: the lake never reads it as a resource type), and
fhir-store follows, because its ledger deletes whatever left the snapshot (``load_fhir.sync_snapshot``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

Resource = dict[str, Any]
TOMBSTONES = "tombstones.json"
_DELETED = {"1", "true", "t", "y", "yes", "d", "del", "deleted"}


def snapshot_dir(lake_dir: Path, snapshot: str) -> Path:
    return lake_dir / "ndjson" / snapshot


def list_snapshots(lake_dir: Path) -> list[str]:
    base = lake_dir / "ndjson"
    return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []


def read_type(directory: Path, rtype: str) -> Iterator[Resource]:
    path = directory / f"{rtype}.ndjson"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def read_all(directory: Path) -> dict[str, list[Resource]]:
    return {p.stem: list(read_type(directory, p.stem)) for p in sorted(directory.glob("*.ndjson"))}


def is_deleted_flag(value: object) -> bool:
    """A source's "deleted" marker: ``1``, ``true``, ``y``, ``yes``, ``d``, ``deleted`` (any case) means deleted."""
    return str(value if value is not None else "").strip().lower() in _DELETED


def write_snapshot(
    directory: Path,
    by_type: Mapping[str, Iterable[Resource]],
    base: Path | None = None,
    tombstones: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, int]:
    """Write all resource types; with ``base`` (previous snapshot) resources are merged by id.

    ``tombstones`` (type -> ids deleted at the source) are removed from the merged snapshot. A record sent again in
    the same run wins over its tombstone (deleted and entered again inside one delta window). What was dropped is
    written to ``tombstones.json``; with nothing dropped the file is absent, so a run without deletes is unchanged."""
    directory.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    dead = {t: set(ids) for t, ids in (tombstones or {}).items()}
    dropped: dict[str, list[str]] = {}
    types = set(by_type)
    if base is not None and base.exists():
        types |= {p.stem for p in base.glob("*.ndjson")}
    for rtype in sorted(types):
        merged: dict[str, Resource] = {}
        if base is not None and base.exists():
            merged.update({r["id"]: r for r in read_type(base, rtype)})
        fresh = {r["id"]: r for r in by_type.get(rtype, [])}
        gone = sorted(rid for rid in dead.get(rtype, ()) if rid in merged and rid not in fresh)
        for rid in gone:
            del merged[rid]
        if gone:
            dropped[rtype] = gone
        merged.update(fresh)
        tmp = directory / f".{rtype}.ndjson.tmp"
        with tmp.open("w", encoding="utf-8") as fh:
            for rid in sorted(merged):
                fh.write(json.dumps(merged[rid], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        tmp.replace(directory / f"{rtype}.ndjson")
        counts[rtype] = len(merged)
    marker = directory / TOMBSTONES
    if dropped:
        marker.write_text(json.dumps(dropped, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    else:
        marker.unlink(missing_ok=True)
    return counts


def tombstone_count(directory: Path) -> int:
    """How many records ``write_snapshot`` dropped from this snapshot as deleted at the source."""
    marker = directory / TOMBSTONES
    if not marker.exists():
        return 0
    return sum(len(v) for v in json.loads(marker.read_text(encoding="utf-8")).values())
