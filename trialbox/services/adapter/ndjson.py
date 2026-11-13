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

import heapq
import io
import json
import os
import shutil
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import IO, Any

Resource = dict[str, Any]
TOMBSTONES = "tombstones.json"
SORT_ENV = "TB_INGEST_SORT_MB"
CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")
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


def _canon(r: Resource) -> str:
    return json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _memory_cap() -> int:
    """The memory this process may use: the smaller of the host's and the container's cap (cgroup v2)."""
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    try:
        raw = CGROUP_MEMORY_MAX.read_text(encoding="ascii").strip()
    except OSError:
        raw = ""
    return min(total, int(raw)) if raw.isdigit() else total


def sort_run_bytes() -> int:
    """T-692 (D-473): the most a sort run of the merge holds, in bytes of NDJSON lines: ``TB_INGEST_SORT_MB``, else a
    sixteenth of :func:`_memory_cap` (the lines take about twice their size as Python strings; the rest of the cap is
    the validator's heap, the source table being read and the samples)."""
    env = os.environ.get(SORT_ENV, "").strip()
    if not env:
        return max(1, _memory_cap() // 16)
    if not env.isdigit() or int(env) <= 0:
        raise ValueError(f"{SORT_ENV}={env!r}: a whole number of megabytes above 0")
    return int(env) * 2**20


class Spool:
    """The night's resources on disk as they are mapped (T-692, D-473): one file per type, canonical JSON lines in
    arrival order. :func:`write_snapshot` reads it back type by type, so the adapter never holds the night."""

    def __init__(self, root: Path, run_bytes: int | None = None) -> None:
        shutil.rmtree(root, ignore_errors=True)  # a killed night's leftovers
        root.mkdir(parents=True)
        self.root = root
        self.run_bytes = run_bytes or sort_run_bytes()
        self._files: dict[str, IO[str]] = {}
        self._n: dict[str, int] = {}

    def add(self, r: Resource) -> None:
        rtype = str(r["resourceType"])
        fh = self._files.get(rtype)
        if fh is None:
            fh = self._files[rtype] = (self.root / f"{rtype}.ndjson").open("w", encoding="utf-8")
        fh.write(_canon(r) + "\n")
        self._n[rtype] = self._n.get(rtype, 0) + 1

    def counts(self) -> dict[str, int]:
        """Resources spooled per type (every one sent, an id sent twice counted twice)."""
        return dict(sorted(self._n.items()))

    def read(self, rtype: str) -> Iterator[Resource]:
        fh = self._files.get(rtype)
        if fh is not None:
            fh.flush()
        return read_type(self.root, rtype)

    def close(self) -> None:
        for fh in self._files.values():
            fh.close()
        self._files.clear()
        shutil.rmtree(self.root, ignore_errors=True)


_RUN_READ_COST = 4 * io.DEFAULT_BUFFER_SIZE  # what one open run file holds while it is merged (bytes and text)
_Item = tuple[Any, int, str]  # (id, sequence, canonical line): the sequence keeps arrival order among equal ids


def _sorted(items: Iterable[_Item], run_bytes: int, work: Path) -> Iterator[_Item]:
    """``items`` sorted by (id, sequence): in memory up to ``run_bytes`` of lines, else in runs on disk merged."""
    buf: list[_Item] = []
    size = 0
    runs: list[Path] = []
    for item in items:
        buf.append(item)
        size += len(item[2]) + 100  # the line and its tuple
        if size >= run_bytes:
            buf.sort()
            work.mkdir(parents=True, exist_ok=True)
            run = work / f"run-{len(runs):05d}"
            with run.open("w", encoding="utf-8") as fh:
                fh.writelines(f"{json.dumps(i)}\t{n}\t{line}\n" for i, n, line in buf)
            runs.append(run)
            buf, size = [], 0
    buf.sort()
    if not runs:
        yield from buf
        return

    # each open run costs its read buffer: at most as many runs at once as fit the budget, merged in passes
    fan = max(2, run_bytes // _RUN_READ_COST)
    while len(runs) + 1 > fan:
        merged = work / f"run-{len(runs):05d}-m"
        with merged.open("w", encoding="utf-8") as fh:
            fh.writelines(
                f"{json.dumps(i)}\t{n}\t{line}\n" for i, n, line in heapq.merge(*(_items(r) for r in runs[:fan]))
            )
        for r in runs[:fan]:
            r.unlink()
        runs = [*runs[fan:], merged]
    yield from heapq.merge(iter(buf), *(_items(r) for r in runs))


def _items(path: Path) -> Iterator[_Item]:
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            i, n, line = raw.rstrip("\n").split("\t", 2)
            yield json.loads(i), int(n), line


class _Unsorted(Exception):
    """The previous snapshot's file is not sorted by id (written by hand): merged through the sort instead."""


def _base_lines(base: Path, rtype: str, check: bool) -> Iterator[_Item]:
    prev: Any = None
    for n, r in enumerate(read_type(base, rtype)):
        rid = r["id"]
        if check and prev is not None and rid < prev:
            raise _Unsorted(rtype)
        prev = rid
        yield rid, n - 2**62, _canon(r)  # before every record of the night


def write_snapshot(
    directory: Path,
    by_type: Mapping[str, Iterable[Resource]] | Spool,
    base: Path | None = None,
    tombstones: Mapping[str, Iterable[str]] | None = None,
    transform: Callable[[Resource], bool] | None = None,
    run_bytes: int | None = None,
    left_out: Mapping[str, Iterable[str]] | None = None,
    removed: dict[str, int] | None = None,
) -> dict[str, int]:
    """Write all resource types; with ``base`` (previous snapshot) resources are merged by id.

    ``tombstones`` (type -> ids deleted at the source) are removed from the merged snapshot. A record sent again in
    the same run wins over its tombstone (deleted and entered again inside one delta window). What was dropped is
    written to ``tombstones.json``; with nothing dropped the file is absent, so a run without deletes is unchanged.

    ``left_out`` (D-528: type -> ids a feed row gave before and does not give tonight) are written from neither
    the previous snapshot nor the night, and are **not** listed in ``tombstones.json``: the source did not delete
    them, and the file is what says "deleted at the source" downstream. How many left the snapshot, per type, is
    added to ``removed`` when given.

    T-692 (D-473): in streams. ``by_type`` may be a :class:`Spool`; the night's records are sorted in runs of at most
    ``run_bytes`` (:func:`sort_run_bytes`) and merged with the previous snapshot's file, which is read line by line
    (it is sorted by id: this function wrote it). ``transform`` sees each record of the night once, in the order it
    was sent, before it is sorted; it may change it in place, and returns False to leave it out."""
    directory.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    dead = {t: set(ids) for t, ids in (tombstones or {}).items()}
    out = {t: set(ids) for t, ids in (left_out or {}).items()}
    dropped: dict[str, list[str]] = {}
    spool = by_type if isinstance(by_type, Spool) else None
    given: Mapping[str, Iterable[Resource]] = {} if isinstance(by_type, Spool) else by_type
    types = set(spool.counts()) if spool is not None else set(given)
    budget = run_bytes or (spool.run_bytes if spool is not None else sort_run_bytes())
    has_base = base is not None and base.exists()
    if base is not None and has_base:
        types |= {p.stem for p in base.glob("*.ndjson")}
    for rtype in sorted(types):
        work = directory / f".{rtype}.runs"
        night = directory / f".{rtype}.night"
        shutil.rmtree(work, ignore_errors=True)
        night.unlink(missing_ok=True)
        try:
            # the night's records, transformed in arrival order, sorted once into a file of (id, seq, line)
            fresh: Iterable[Resource] = spool.read(rtype) if spool is not None else given.get(rtype, ())
            kept = (r for r in fresh if transform is None or transform(r))
            items = ((r["id"], n, _canon(r)) for n, r in enumerate(kept))
            with night.open("w", encoding="utf-8") as fh:
                fh.writelines(
                    f"{json.dumps(i)}\t{n}\t{line}\n" for i, n, line in _sorted(items, budget, work / "night")
                )
            left = [0]
            try:
                n, gone = _write_type(
                    directory, rtype, night, base if has_base else None, dead, True, budget, work, out.get(rtype), left
                )
            except _Unsorted:
                left[0] = 0
                n, gone = _write_type(directory, rtype, night, base, dead, False, budget, work, out.get(rtype), left)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            night.unlink(missing_ok=True)
        if gone:
            dropped[rtype] = gone
        if removed is not None and left[0]:
            removed[rtype] = removed.get(rtype, 0) + left[0]
        counts[rtype] = n
    marker = directory / TOMBSTONES
    if dropped:
        marker.write_text(json.dumps(dropped, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    else:
        marker.unlink(missing_ok=True)
    return counts


def _write_type(
    directory: Path,
    rtype: str,
    night: Path,
    base: Path | None,
    dead: dict[str, set[str]],
    base_sorted: bool,
    budget: int,
    work: Path,
    left_out: set[str] | None = None,
    left: list[int] | None = None,
) -> tuple[int, list[str]]:
    """One type: the previous snapshot's records and the night's, by id; per id the night's last record, else the
    previous snapshot's last one unless the source deleted it. Returns (records written, ids dropped).

    ``left_out`` (D-528): ids written from neither side, the night's record included (the caller takes an id out
    of the set when a later row gives the record again: the last row of a key decides). ``left[0]`` counts those
    that were in the previous snapshot."""
    old: Iterable[_Item] = ()
    if base is not None:
        old = (
            _base_lines(base, rtype, check=True)
            if base_sorted
            else _sorted(_base_lines(base, rtype, check=False), budget, work / "base")
        )
    killed = dead.get(rtype, set())
    gone: list[str] = []
    n = 0
    tmp = directory / f".{rtype}.ndjson.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        cur: Any = None
        line = ""
        from_night = False
        from_base = False

        def flush() -> None:
            nonlocal n
            if left_out and cur in left_out:
                if from_base and left is not None:
                    left[0] += 1
                return
            if not from_night and cur in killed:
                gone.append(cur)
                return
            fh.write(line + "\n")
            n += 1

        for rid, seq, body in heapq.merge(old, _items(night)):
            if cur is not None and rid != cur:
                flush()
            if rid != cur:
                cur, from_night, from_base = rid, False, False
            line = body
            from_night = from_night or seq >= 0
            from_base = from_base or seq < 0
        if cur is not None:
            flush()
    tmp.replace(directory / f"{rtype}.ndjson")
    return n, sorted(gone)


def tombstone_count(directory: Path) -> int:
    """How many records ``write_snapshot`` dropped from this snapshot as deleted at the source."""
    marker = directory / TOMBSTONES
    if not marker.exists():
        return 0
    return sum(len(v) for v in json.loads(marker.read_text(encoding="utf-8")).values())
