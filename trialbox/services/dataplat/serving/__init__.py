"""L5 serving pin (§5.3 L5, §5.9.3, §5.13.2; S1-04).

``CURRENT.json`` names the one signed snapshot that downstream runs read. It moves only by an atomic replace after a
``PUBLISH`` (:meth:`Serving.pin`). On ``HOLD`` it stays on the last good snapshot T−1 and the hold is written to the
pin history (:meth:`Serving.hold`). :meth:`Serving.pin_previous` is the ``lake pin T-1`` rollback of §18. Readers open
DuckDB only through :meth:`Serving.connect`, which verifies the manifest signature first (DP-32). The v1 lake's own
``CURRENT`` file is kept in step, so v1 readers (``lake.store.Lake``) see the same snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tb_contracts.landing import ServingPointer, SnapshotManifest

from dataplat import curated
from dataplat.common import Clock, canonical, utc_now, write_atomic


class ServingError(RuntimeError):
    pass


class Serving:
    def __init__(self, root: Path, curated_root: Path, lake_dir: Path, *, tz: str, clock: Clock = utc_now) -> None:
        self.root = root
        self.curated_root = curated_root
        self.lake_dir = lake_dir
        self.tz = tz
        self.clock = clock
        root.mkdir(parents=True, exist_ok=True)

    @property
    def pointer_path(self) -> Path:
        return self.root / "CURRENT.json"

    def current(self) -> ServingPointer | None:
        p = self.pointer_path
        return ServingPointer.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None

    def history(self) -> list[dict[str, Any]]:
        p = self.root / "history.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _log(self, action: str, **fields: Any) -> None:
        with (self.root / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(canonical({"action": action, "at": self.clock().isoformat(), **fields}) + "\n")

    def pin(self, manifest: SnapshotManifest, reason: str) -> ServingPointer:
        if not curated.verify(manifest):
            raise ServingError(f"snapshot {manifest.snapshot_id}: manifest signature does not verify")
        ptr = ServingPointer(
            snapshot_id=manifest.snapshot_id,
            snapshot=manifest.snapshot,
            manifest_sha256=curated.manifest_sha(manifest),
            pinned_at=self.clock(),
            reason=reason,
        )
        write_atomic(self.pointer_path, (ptr.model_dump_json() + "\n").encode("utf-8"))
        write_atomic(self.lake_dir / "CURRENT", manifest.snapshot.encode("utf-8"))
        self._log("pin", snapshot_id=manifest.snapshot_id, reason=reason)
        return ptr

    def hold(self, reason: str) -> ServingPointer | None:
        """A held cycle: the pointer stays on T−1 (re-asserted in the v1 lake too) and the hold is logged."""
        cur = self.current()
        if cur is not None:
            write_atomic(self.lake_dir / "CURRENT", cur.snapshot.encode("utf-8"))
        self._log("hold", snapshot_id=cur.snapshot_id if cur else None, reason=reason)
        return cur

    def pin_previous(self, reason: str) -> ServingPointer:
        """Roll back to the snapshot pinned before the current one (``lake pin T-1``)."""
        cur = self.current()
        pinned = [h["snapshot_id"] for h in self.history() if h["action"] == "pin"]
        older = [s for s in pinned if cur is None or s != cur.snapshot_id]
        if not older:
            raise ServingError("no earlier snapshot to pin")
        snap = older[-1].removeprefix("snap_")
        return self.pin(curated.load(self.curated_root, snap), reason)

    def manifest(self) -> SnapshotManifest:
        cur = self.current()
        if cur is None:
            raise ServingError("nothing is pinned yet")
        m = curated.load(self.curated_root, cur.snapshot)
        if curated.manifest_sha(m) != cur.manifest_sha256 or not curated.verify(m):
            raise ServingError(f"snapshot {cur.snapshot_id}: manifest does not match the pin or its signature")
        return m

    def connect(self) -> Any:
        """A read-only DuckDB connection to the pinned snapshot, after the manifest check."""
        from lake.store import Lake

        m = self.manifest()
        return Lake(self.lake_dir, self.tz).connect(m.snapshot)


__all__ = ["Serving", "ServingError"]
