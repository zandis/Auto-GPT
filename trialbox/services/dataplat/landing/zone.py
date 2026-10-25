"""L0 landing zone (§5.3 L0, DP-04; S1-02).

Layout (Z-IDN, data class D4)::

    <root>/<source>/<batch_id>/manifest.json      the l0_batch_manifest (canonical JSON, read-only)
    <root>/<source>/<batch_id>/objects/<file>     the landed objects, byte-for-byte, read-only
    <root>/<source>/<batch_id>/LEGAL_HOLD          optional marker: retention never prunes the batch

* **Immutable.** A batch is staged in a hidden directory and renamed into place in one step, so no partial batch is
  ever visible. Objects and the manifest are created exclusively and made read-only (``chmod 0444``, standing in for
  object lock or ``chattr +i``). Nothing is transformed.
* **Idempotent.** ``batch_id`` is derived from the source, the sorted ``(object, sha256)`` pairs and the source
  control totals. Landing the same bytes with the same totals again returns the existing manifest
  (``created=False``) and writes nothing.
* **Change detection.** One changed byte changes an object's sha256, hence a new ``batch_id``; :meth:`verify`
  detects an object altered in place after landing; :func:`changed_tables` names the tables that differ between two
  batches.
* **Retention.** :meth:`prune` deletes raw batches older than 90 days (by ``landed_at`` and the injected clock)
  unless a legal hold is set. Deleting the plaintext objects stands in for crypto-shredding until per-batch keys exist.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from tb_contracts.dataclass import ClassLabel
from tb_contracts.landing import D4, ConnectorKind, ControlTotals, L0BatchManifest, LandedObject, canonical_json

from dataplat.common import Clock, canonical, sha256_hex, stable_id, utc_now, write_once
from dataplat.landing.shape import fingerprint, shape, table_name

RAW_RETENTION_DAYS = 90
MANIFEST = "manifest.json"
LEGAL_HOLD = "LEGAL_HOLD"


class LandingError(RuntimeError):
    pass


@dataclass(frozen=True)
class LandingResult:
    manifest: L0BatchManifest
    created: bool
    path: Path


def batch_digest(objects: list[tuple[str, str]]) -> str:
    return sha256_hex(canonical(sorted(objects)).encode("utf-8"))


def changed_tables(old: L0BatchManifest, new: L0BatchManifest) -> list[str]:
    """Tables whose object differs (by sha256), plus tables present in only one of the two batches."""
    a = {o.table: o.sha256 for o in old.objects}
    b = {o.table: o.sha256 for o in new.objects}
    return sorted(t for t in set(a) | set(b) if a.get(t) != b.get(t))


class LandingZone:
    def __init__(self, root: Path, clock: Clock = utc_now) -> None:
        self.root = root
        self.clock = clock
        root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------------------------------------ paths
    def batch_dir(self, source: str, batch_id: str) -> Path:
        return self.root / source / batch_id

    def object_path(self, manifest: L0BatchManifest, obj: LandedObject) -> Path:
        return self.batch_dir(manifest.source, manifest.batch_id) / obj.key

    def objects_dir(self, manifest: L0BatchManifest) -> Path:
        return self.batch_dir(manifest.source, manifest.batch_id) / "objects"

    def read_object(self, manifest: L0BatchManifest, table: str) -> tuple[LandedObject, bytes]:
        obj = manifest.object_for(table)
        if obj is None:
            raise LandingError(f"batch {manifest.batch_id} has no object for table {table!r}")
        return obj, self.object_path(manifest, obj).read_bytes()

    # ------------------------------------------------------------------------------------------------ land
    def land(
        self,
        source: str,
        files: Mapping[str, Path] | list[Path],
        *,
        kind: ConnectorKind = ConnectorKind.FILE_DROP,
        extract_time: datetime | None = None,
        extract_start: datetime | None = None,
        extract_end: datetime | None = None,
        control_totals: Mapping[str, ControlTotals] | None = None,
        control_totals_origin: str = "source",
        watermark_from: str | None = None,
        watermark_to: str | None = None,
        data_class: ClassLabel = D4,
    ) -> LandingResult:
        """Land one batch of files for ``source``. ``files`` are paths (table = file stem) or ``{table: path}``."""
        if not source or "/" in source or source.startswith("."):
            raise LandingError(f"invalid source name {source!r}")
        items = sorted(files.items()) if isinstance(files, Mapping) else sorted((table_name(p), p) for p in files)
        if not items:
            raise LandingError("a batch needs at least one object")
        payloads: list[tuple[str, str, bytes]] = []  # (table, key, bytes)
        for table, path in items:
            payloads.append((table, f"objects/{path.name}", path.read_bytes()))
        keys = [k for _, k, _ in payloads]
        if len(set(keys)) != len(keys):
            raise LandingError("two objects of one batch share a file name")
        digests = [(key, sha256_hex(data)) for _, key, data in payloads]
        totals_doc = {t: v.model_dump(mode="json") for t, v in sorted((control_totals or {}).items())}
        # the source's control totals are part of the batch identity: the same bytes with other totals are another batch
        batch_id = stable_id("b", source, batch_digest(digests), canonical(totals_doc))
        final = self.batch_dir(source, batch_id)
        if (final / MANIFEST).exists():
            manifest = self.load_manifest(source, batch_id)
            bad = self.verify(manifest)
            if bad:
                raise LandingError(f"batch {batch_id} exists but objects changed in place: {bad}")
            return LandingResult(manifest, False, final)
        now = self.clock()
        objects: list[LandedObject] = []
        for (table, key, data), (_, digest) in zip(payloads, digests, strict=True):
            rows, enc, cols = shape(data, key)
            objects.append(
                LandedObject(
                    key=key,
                    table=table,
                    bytes=len(data),
                    sha256=digest,
                    rows=rows,
                    encoding=enc,
                    columns=cols,
                    schema_fingerprint=fingerprint(cols),
                )
            )
        encodings = sorted({o.encoding for o in objects})
        manifest = L0BatchManifest(
            batch_id=batch_id,
            source=source,
            kind=kind,
            extract_time=extract_time or now,
            extract_start=extract_start,
            extract_end=extract_end,
            landed_at=now,
            rows=sum(o.rows for o in objects),
            bytes=sum(o.bytes for o in objects),
            sha256=batch_digest(digests),
            schema_fingerprint=sha256_hex(canonical({o.table: o.schema_fingerprint for o in objects}).encode("utf-8")),
            objects=objects,
            watermark_from=watermark_from,
            watermark_to=watermark_to,
            control_totals=dict(sorted((control_totals or {}).items())),
            control_totals_origin="extract" if control_totals_origin == "extract" else "source",
            encoding=encodings[0] if len(encodings) == 1 else "mixed",
            data_class=data_class,
        )
        staging = self.root / source / f".staging-{batch_id}-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            for (_, key, data), _obj in zip(payloads, objects, strict=True):
                write_once(staging / key, data)
            write_once(staging / MANIFEST, (canonical_json(manifest) + "\n").encode("utf-8"))
            (staging / "objects").chmod(0o555)
            os.rename(staging, final)
        except FileExistsError:  # a concurrent landing of the same bytes won the rename
            _force_rmtree(staging)
            return LandingResult(self.load_manifest(source, batch_id), False, final)
        except BaseException:
            _force_rmtree(staging)
            raise
        return LandingResult(manifest, True, final)

    # ------------------------------------------------------------------------------------------------ read
    def load_manifest(self, source: str, batch_id: str) -> L0BatchManifest:
        path = self.batch_dir(source, batch_id) / MANIFEST
        return L0BatchManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def batches(self, source: str | None = None) -> list[L0BatchManifest]:
        dirs = [self.root / source] if source else sorted(p for p in self.root.iterdir() if p.is_dir())
        out: list[L0BatchManifest] = []
        for d in dirs:
            if not d.is_dir():
                continue
            for b in sorted(d.iterdir()):
                if not b.name.startswith(".") and (b / MANIFEST).exists():
                    out.append(L0BatchManifest.model_validate_json((b / MANIFEST).read_text(encoding="utf-8")))
        return sorted(out, key=lambda m: (m.landed_at, m.source, m.batch_id))

    def verify(self, manifest: L0BatchManifest) -> list[str]:
        """Object keys whose bytes no longer match the manifest sha256 (or that are missing)."""
        bad: list[str] = []
        for obj in manifest.objects:
            path = self.object_path(manifest, obj)
            if not path.exists() or sha256_hex(path.read_bytes()) != obj.sha256:
                bad.append(obj.key)
        return bad

    # ------------------------------------------------------------------------------------------------ retention
    def hold(self, manifest: L0BatchManifest, ticket: str) -> None:
        """Set a legal hold: :meth:`prune` keeps the batch until the hold is released."""
        d = self.batch_dir(manifest.source, manifest.batch_id)
        d.chmod(0o755)
        (d / LEGAL_HOLD).write_text(ticket + "\n", encoding="utf-8")

    def release_hold(self, manifest: L0BatchManifest) -> None:
        (self.batch_dir(manifest.source, manifest.batch_id) / LEGAL_HOLD).unlink(missing_ok=True)

    def prune(self, retention_days: int = RAW_RETENTION_DAYS) -> list[str]:
        """Delete raw batches whose ``landed_at`` is older than ``retention_days`` (clock-injected), except held ones.
        Returns the pruned batch ids, sorted."""
        cutoff = self.clock() - timedelta(days=retention_days)
        gone: list[str] = []
        for m in self.batches():
            d = self.batch_dir(m.source, m.batch_id)
            if m.landed_at < cutoff and not (d / LEGAL_HOLD).exists():
                _force_rmtree(d)
                gone.append(m.batch_id)
        return sorted(gone)


def _force_rmtree(path: Path) -> None:
    if not path.exists():
        return
    for p in [path, *path.rglob("*")]:
        if p.is_dir():
            p.chmod(0o755)
    shutil.rmtree(path, ignore_errors=True)
