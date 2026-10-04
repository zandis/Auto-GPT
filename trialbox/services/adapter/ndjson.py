"""FHIR NDJSON snapshot files: ``<lake>/ndjson/<snapshot>/<ResourceType>.ndjson`` (one resource per line).

Files are written sorted by id with canonical JSON so the same input produces identical bytes (SPEC §11.2
reproducibility). A delta run merges its resources over the previous snapshot (upsert by id).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

Resource = dict[str, Any]


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


def write_snapshot(
    directory: Path, by_type: Mapping[str, Iterable[Resource]], base: Path | None = None
) -> dict[str, int]:
    """Write all resource types; with ``base`` (previous snapshot) resources are merged by id."""
    directory.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    types = set(by_type)
    if base is not None and base.exists():
        types |= {p.stem for p in base.glob("*.ndjson")}
    for rtype in sorted(types):
        merged: dict[str, Resource] = {}
        if base is not None and base.exists():
            merged.update({r["id"]: r for r in read_type(base, rtype)})
        merged.update({r["id"]: r for r in by_type.get(rtype, [])})
        tmp = directory / f".{rtype}.ndjson.tmp"
        with tmp.open("w", encoding="utf-8") as fh:
            for rid in sorted(merged):
                fh.write(json.dumps(merged[rid], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        tmp.replace(directory / f"{rtype}.ndjson")
        counts[rtype] = len(merged)
    return counts
