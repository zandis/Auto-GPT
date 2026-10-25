"""L4 curated snapshot and its signed manifest (§5.3 L4, §5.13, DP-32; S1-04).

Write-audit-publish on the §5.13.1 fallback store (immutable per-snapshot NDJSON + Parquet + DuckDB, the v1 lake
layout, built by the v1 ``lake.store.Lake.rebuild``):

1. :func:`stage` writes the L3 output to a staging directory with the v1 NDJSON writer and computes the L3 → L4
   balance per table: ``rows(T−1) + inserts − deletes = rows(T)`` and ``rows(T) = rows(L3)``.
2. The caller evaluates the publish gate.
3. :func:`commit` (gate passed) moves the staging directory into place, builds the lake, writes and signs the
   snapshot manifest (Ed25519, ``tb_common.crypto``). :func:`discard` (gate held) removes the staging directory, so
   nothing of a held cycle is ever referenced.
"""

from __future__ import annotations

import base64
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from tb_common.crypto import ed25519_sign, ed25519_verify
from tb_contracts.landing import Equation, SnapshotManifest, TableSnapshot, canonical_json

from dataplat.common import sha256_hex, write_once
from dataplat.pseudonymise import L3Output
from dataplat.reconcile import exact

MANIFEST = "manifest.json"


class CuratedError(RuntimeError):
    pass


@dataclass
class Staged:
    snapshot: str
    snapshot_id: str
    directory: Path
    tables: dict[str, TableSnapshot]
    equations: list[Equation] = field(default_factory=list)

    @property
    def balanced(self) -> bool:
        return all(e.verdict == "pass" for e in self.equations)


def snapshot_id_for(snapshot: str) -> str:
    return f"snap_{snapshot}"


def snapshots_dir(root: Path) -> Path:
    return root / "snapshots"


def ndjson_dir(root: Path, snapshot: str) -> Path:
    return snapshots_dir(root) / snapshot / "ndjson"


def _ids(directory: Path, rtype: str) -> set[str]:
    from adapter.ndjson import read_type

    return {str(r["id"]) for r in read_type(directory, rtype)}


def stage(l3: L3Output, root: Path, snapshot: str, previous: SnapshotManifest | None) -> Staged:
    from adapter.ndjson import write_snapshot

    if (snapshots_dir(root) / snapshot / MANIFEST).exists():
        raise CuratedError(f"snapshot {snapshot} is already published (snapshots are immutable)")
    staging = root / "staging" / snapshot
    shutil.rmtree(staging, ignore_errors=True)
    nd = staging / "ndjson"
    counts = write_snapshot(nd, l3.by_type)
    tables = {
        t: TableSnapshot(rows=n, sha256=sha256_hex((nd / f"{t}.ndjson").read_bytes()))
        for t, n in sorted(counts.items())
    }
    prev_dir = ndjson_dir(root, previous.snapshot) if previous else None
    eqs: list[Equation] = []
    for t in sorted(set(tables) | set(previous.tables if previous else {})):
        now_ids = _ids(nd, t)
        old_ids = _ids(prev_dir, t) if prev_dir is not None and prev_dir.exists() else set()
        inserts, deletes = len(now_ids - old_ids), len(old_ids - now_ids)
        eqs.append(
            exact("L3→L4", "rows(T−1) + inserts − deletes = rows(T)", len(old_ids) + inserts - deletes, len(now_ids), t)
        )
        eqs.append(
            exact("L3→L4", "rows(L3) = rows(T)", len(l3.by_type.get(t, [])), tables[t].rows if t in tables else 0, t)
        )
    return Staged(snapshot, snapshot_id_for(snapshot), staging, tables, eqs)


def discard(staged: Staged) -> None:
    shutil.rmtree(staged.directory, ignore_errors=True)


def _parquet_digest(lake_dir: Path, snapshot: str) -> str:
    pdir = lake_dir / "parquet" / f"snapshot={snapshot}"
    pairs = [[p.name, sha256_hex(p.read_bytes())] for p in sorted(pdir.glob("*.parquet"))]
    return sha256_hex(canonical_json(pairs).encode("utf-8"))


def sign(manifest: SnapshotManifest, private_pem: bytes, public_pem: bytes) -> SnapshotManifest:
    body = manifest.model_copy(update={"signature": None, "signer_public_key": None})
    sig = ed25519_sign(private_pem, canonical_json(body).encode("utf-8"))
    return manifest.model_copy(
        update={"signature": base64.b64encode(sig).decode("ascii"), "signer_public_key": public_pem.decode("ascii")}
    )


def verify(manifest: SnapshotManifest) -> bool:
    if not manifest.signature or not manifest.signer_public_key:
        return False
    body = manifest.model_copy(update={"signature": None, "signer_public_key": None})
    return ed25519_verify(
        manifest.signer_public_key.encode("ascii"),
        canonical_json(body).encode("utf-8"),
        base64.b64decode(manifest.signature),
    )


def manifest_sha(manifest: SnapshotManifest) -> str:
    return "sha256:" + sha256_hex(canonical_json(manifest).encode("utf-8"))


def commit(
    staged: Staged,
    root: Path,
    lake_dir: Path,
    *,
    tz: str,
    created_at: datetime,
    signing_key: tuple[bytes, bytes],
    fields: dict[str, Any],
) -> SnapshotManifest:
    """Move the staged snapshot into place, build the v1 lake for it and write the signed manifest."""
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    final = snapshots_dir(root) / staged.snapshot
    if final.exists():
        raise CuratedError(f"snapshot directory {final} already exists")
    final.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staged.directory, final)
    try:
        stats = Lake(lake_dir, tz).rebuild(staged.snapshot, HashEmbedder(), final / "ndjson")
    except Exception:
        shutil.rmtree(final, ignore_errors=True)
        raise
    manifest = SnapshotManifest(
        snapshot_id=staged.snapshot_id,
        snapshot=staged.snapshot,
        created_at=created_at,
        tables=staged.tables,
        lake_tables=dict(sorted(stats.tables.items())),
        lake_sha256=_parquet_digest(lake_dir, staged.snapshot),
        **fields,
    )
    manifest = sign(manifest, *signing_key)
    write_once(final / MANIFEST, (canonical_json(manifest) + "\n").encode("utf-8"))
    return manifest


def load(root: Path, snapshot: str) -> SnapshotManifest:
    path = snapshots_dir(root) / snapshot / MANIFEST
    if not path.exists():
        raise CuratedError(f"no published snapshot {snapshot}")
    return SnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))


def published(root: Path) -> list[str]:
    d = snapshots_dir(root)
    return sorted(p.name for p in d.iterdir() if (p / MANIFEST).exists()) if d.exists() else []


__all__ = [
    "CuratedError",
    "Staged",
    "commit",
    "discard",
    "load",
    "manifest_sha",
    "published",
    "sign",
    "snapshot_id_for",
    "stage",
    "verify",
]
