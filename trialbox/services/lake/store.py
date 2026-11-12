"""Lake storage: NDJSON snapshot -> Parquet (partitioned by snapshot) -> per-snapshot DuckDB with FTS (SPEC §3.2, §4.5).

Layout under ``<lake_dir>``::

    ndjson/<snapshot>/<Type>.ndjson           written by the adapter
    parquet/snapshot=<snapshot>/<table>.parquet  (+ <table>.parquet.sha256)
    db/<snapshot>.duckdb                     tables + document_chunk(text, tokens, sha) + FTS index + lake_meta
    db/<snapshot>.duckdb.sha256              sidecar hash of the finished file (``Lake.verify``)
    db/<snapshot>.duckdb.source              the NDJSON folder it was built from, when not ndjson/<snapshot> (D-271)
    embed_cache.duckdb                       sha256(chunk text) -> embedding: the one vector store of the lake
    CURRENT                                  snapshot served by default
    FEED                                     the lake has held a hospital feed: an empty rebuild is refused (D-271)
    db/<snapshot>.duckdb.siteonly            the snapshot was built from the site's own inputs only (D-271)
    holds/<holder>.json                      a running job reads this snapshot: never rebuilt or pruned (T-305b)
    .rebuild.lock                            ``flock``: hold, release, pruning and a rebuild's start and swap (D-462)
    locks/<snapshot>.build.lock              ``flock`` held by the one rebuild of the snapshot that runs (D-462)
    locks/<snapshot>.rebuild.json            the state of the snapshot's last rebuild job, polled (T-690, D-472)
    db/<snapshot>.building, parquet/.building/snapshot=<snapshot>/   a build in progress, swapped in when done
    db/.open/<inode>-<mtime>-<size>/<snapshot>.duckdb   a hard link per file identity that readers open (D-462)

Dataflow review P0 (D-149): the embeddings live only in ``embed_cache.duckdb`` and are read by chunk sha at query
time; a snapshot file holds the chunk text, its tokens for BM25 and its sha. Before, every snapshot carried its own
copy of every vector (``document_chunk.embedding FLOAT[1024]``): about 18 GB at 50,000 patients, times the 39 kept
snapshots. Snapshots of schema version 1 (with the column) are still read as they are. ``lake_meta`` carries the
lake schema version and a fingerprint of the table layout; a reader refuses a snapshot outside the versions it knows
with a plain message (WS-03.1), instead of failing later on a missing column.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from embed_service.embedder import Embedder
from tb_common import feedguard
from tb_common.crypto import sha256_text
from tb_common.phi_guard import NOTE_MASK_VERSION, mask_note

from lake.flatten import SCHEMAS
from lake.source import lake_rows
from lake.textproc import chunk, token_string

log = logging.getLogger("lake")
DIM = 1024
INSERT_BATCH = 4096  # chunk rows per Arrow batch: bounds memory on hospital-size snapshots (D-105)
_ARROW = {
    "VARCHAR": pa.string(),
    "DATE": pa.date32(),
    "TIMESTAMP": pa.timestamp("us"),
    "DOUBLE": pa.float64(),
    "BOOLEAN": pa.bool_(),
}


_CONNECT_LOCK = threading.Lock()
# one open of embed_cache.duckdb at a time in this process: DuckDB refuses a read-only and a read-write connection to
# the same file side by side, and a rebuild writes vectors while a search reads them
_CACHE_LOCK = threading.Lock()

# 1: tables + document_chunk with its own embedding column (before D-149); 2: no embedding in the snapshot, chunk sha,
# lake_meta.schema_version / schema_sha / embed_store; 3 (T-106b): the encounter's end and status, and the four
# provenance columns on every table (``lake.flatten.PROVENANCE``); 4 (T-616): ``patient.deceased``. A reader serves
# every version from MIN to CURRENT (an older snapshot reads ``patient.deceased`` as unknown: :func:`_compat_views`).
LAKE_SCHEMA_VERSION = 4
MIN_READABLE_SCHEMA = 1
CHUNK_COLUMNS: list[tuple[str, str]] = [
    ("did", "VARCHAR"),
    ("chunk_no", "INTEGER"),
    ("pid", "VARCHAR"),
    ("date", "TIMESTAMP"),
    ("type", "VARCHAR"),
    ("text", "VARCHAR"),
    ("tok", "VARCHAR"),
    ("sha", "VARCHAR"),
    ("chunk_key", "VARCHAR"),
]


def schema_sha() -> str:
    """Fingerprint of the table layout this code writes (every table, column and type, and the chunk table)."""
    body = json.dumps({"tables": SCHEMAS, "document_chunk": CHUNK_COLUMNS, "v": LAKE_SCHEMA_VERSION}, sort_keys=True)
    return sha256_text(body)


class LakeSchemaError(RuntimeError):
    """The snapshot was built with a lake layout this reader does not serve."""


class RebuildError(RuntimeError):
    """A rebuild refused before anything was written (D-271): its NDJSON folder is missing or holds no record. An
    empty lake made ``CURRENT`` would screen every patient out (and with ``TB_LAKE_SOURCE=omop`` tombstone the whole
    feed in the store of record); the previous ``CURRENT`` stays."""


#: the lake service's 409 for :class:`LakeBusy` carries this header (``held`` or ``building``), D-462
BUSY_HEADER = "X-TB-Lake-Busy"


class LakeBusy(RebuildError):
    """The snapshot cannot be rebuilt now, through no fault of its data (D-462): a running job holds it, or another
    rebuild of it runs. Nothing is written; the caller tries again later (the site publish waits, the adapter's night
    ends "lake busy" and is run again). Never a refusal of the night's data. The service answers 409 with the header
    ``X-TB-Lake-Busy`` (``held`` or ``building``)."""

    reason = "busy"


class SnapshotHeld(LakeBusy):
    """A rebuild of a snapshot that a running job holds (T-305b, D-403, FR-REP-02): the job reads it to its end, so
    its bytes may not change under it. Nothing is written; the publish waits for the job (``sitesetup`` batches it).
    Checked when the rebuild starts and again, under the lake lock, at the swap (D-462): a hold taken during the
    build makes the build be discarded, the held bytes stay."""

    reason = "held"


class SnapshotBuilding(LakeBusy):
    """Another rebuild of the same snapshot is running (D-462): never two writers of ``<snapshot>.building``. Nothing
    is written; the caller shows "already building" (the site publish waits, T-690 polls)."""

    reason = "building"


#: a hold older than this is a job that died without releasing it; it no longer protects its snapshot (D-403)
HOLD_TTL_SECONDS = 14 * 24 * 3600
_HOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _holds_dir(lake_dir: Path) -> Path:
    return lake_dir / "holds"


@contextlib.contextmanager
def lake_lock(lake_dir: Path) -> Iterator[None]:
    """The lake's one lock (D-462): an exclusive ``flock`` on ``<lake_dir>/.rebuild.lock``, so it holds across the
    lake's worker processes, the adapter and the tools sharing the folder; a killed holder releases it. ``hold``,
    ``release``, the adapter's pruning and a rebuild's start and swap take it, each for a short step only."""
    lake_dir.mkdir(parents=True, exist_ok=True)
    with (lake_dir / ".rebuild.lock").open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def building(lake_dir: Path, snapshot: str) -> Iterator[None]:
    """The one rebuild of ``snapshot`` that runs (D-462): an exclusive ``flock`` on ``locks/<snapshot>.build.lock``
    held for the whole build and taken without waiting; a second rebuild of the snapshot gets
    :class:`SnapshotBuilding`. The file is never deleted: a deleted file would let a second holder in (the pruning
    takes this lock too, without waiting, and leaves a snapshot that is building alone)."""
    locks = lake_dir / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / f"{snapshot}.build.lock").open("a") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SnapshotBuilding(
                f"lake snapshot {snapshot} is already building (another rebuild of it runs); nothing built, "
                "CURRENT unchanged"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ------------------------------------------------------------------ rebuilds as polled jobs (T-690, D-472)
#: a rebuild job's states: ``running`` is followed; the others end it (``busy``: held at the swap, nothing replaced;
#: ``refused``: the data was refused, D-271; ``failed``: an error; ``interrupted``: its process ended without an answer)
JOB_STATES = ("running", "done", "busy", "refused", "failed", "interrupted")


def _job_path(lake_dir: Path, snapshot: str) -> Path:
    return lake_dir / "locks" / f"{snapshot}.rebuild.json"


def write_rebuild_job(lake_dir: Path, job: dict[str, Any]) -> None:
    """The state of the last rebuild job of ``job['snapshot']`` (one small file beside its build lock, no patient
    data: an id, times, counts, a reason), written whole so a reader never sees half of it."""
    p = _job_path(lake_dir, str(job["snapshot"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(job, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _read_job(lake_dir: Path, snapshot: str) -> dict[str, Any] | None:
    try:
        body = json.loads(_job_path(lake_dir, snapshot).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def build_running(lake_dir: Path, snapshot: str) -> bool:
    """Whether a live process holds the build lock of ``snapshot`` (D-462): a rebuild of it runs now. The test takes
    the lock without waiting and lets it go at once."""
    p = lake_dir / "locks" / f"{snapshot}.build.lock"
    if not p.exists():
        return False
    with p.open("a") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return False


def _inline(run: Any) -> None:
    run()


def _open_dir(lake_dir: Path) -> Path:
    return lake_dir / "db" / ".open"


def reader_path(db: Path) -> Path:
    """The path a reader opens for the snapshot file ``db`` (D-462): a hard link named after the file's identity.

    DuckDB keeps one open copy of a file per path in a process; while any connection to it is open, a new connection
    to the same path after the file was replaced still reads the old bytes. A link per identity gives replaced bytes a
    new path, so a reader that comes after a swap never gets the old copy. The link keeps the snapshot's name (the
    database name inside DuckDB). A file system without hard links falls back to ``db`` itself."""
    for _ in range(3):  # the file can be replaced between the stat and the link: then look again
        st = db.stat()
        link = _open_dir(db.parent.parent) / f"{st.st_ino}-{st.st_mtime_ns}-{st.st_size}" / db.name
        try:
            if link.stat().st_ino == st.st_ino:
                return link
        except FileNotFoundError:
            pass
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
            tmp = link.with_name(f".{db.name}.{os.getpid()}.{threading.get_ident()}")
            tmp.unlink(missing_ok=True)
            os.link(db, tmp)
        except FileNotFoundError:
            continue
        except OSError as exc:  # no hard links here: the old behaviour
            log.warning("lake: no reader link for %s (%s); readers open the file itself", db.name, exc)
            return db
        if tmp.stat().st_ino != st.st_ino:
            tmp.unlink(missing_ok=True)
            continue
        tmp.replace(link)
        return link
    return db


def drop_reader_links(lake_dir: Path, snapshot: str) -> int:
    """Remove the reader links of ``snapshot`` that no longer name its file (after a swap, or every one after a prune;
    call under :func:`lake_lock`). An open reader keeps its own copy; the old bytes are freed when it closes."""
    db = lake_dir / "db" / f"{snapshot}.duckdb"
    try:
        keep = db.stat().st_ino
    except FileNotFoundError:
        keep = -1
    n = 0
    for link in _open_dir(lake_dir).glob(f"*/{snapshot}.duckdb"):
        with contextlib.suppress(FileNotFoundError):
            if link.stat().st_ino != keep:
                link.unlink()
                n += 1
                with contextlib.suppress(OSError):
                    link.parent.rmdir()
    return n


def _is_held(lake_dir: Path, snapshot: str) -> bool:
    """A built snapshot a running job holds (call under :func:`lake_lock`)."""
    return (lake_dir / "db" / f"{snapshot}.duckdb").exists() and snapshot in held_snapshots(lake_dir).values()


def held_snapshots(lake_dir: Path, now: float | None = None) -> dict[str, str]:
    """``holder -> snapshot`` of every live hold on the lake in ``lake_dir`` (T-305b, D-403). A hold older than
    :data:`HOLD_TTL_SECONDS` or unreadable is left out (a job that died holds nothing). The adapter's pruning and
    every rebuild read this; it needs no lake service."""
    now = time.time() if now is None else now
    out: dict[str, str] = {}
    for f in sorted(_holds_dir(lake_dir).glob("*.json")):
        try:
            body = json.loads(f.read_text(encoding="utf-8"))
            at, snap = float(body["at"]), str(body["snapshot"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if now - at <= HOLD_TTL_SECONDS:
            out[f.stem] = snap
    return out


class StaleSnapshotError(RuntimeError):
    """The lake snapshot a job would pin holds a night older than the box allows (T-305a, D-383, CR-063): the
    nightly ingest has not published for days, and a list built from it would miss every recent record."""


def snapshot_age_days(snapshot: str, today: date) -> int:
    """Whole days from the night ``snapshot`` holds (its name, ``YYYY-MM-DD``) to ``today``; a snapshot named after a
    later day (a box whose clock is pinned behind the feed) is 0 days old."""
    try:
        night = date.fromisoformat(snapshot)
    except ValueError:
        raise StaleSnapshotError(
            f"LAKE-STALE: lake snapshot {snapshot!r} is not named after a night (YYYY-MM-DD); its age is unknown"
        ) from None
    return max(0, (today - night).days)


def check_snapshot_age(snapshot: str, today: date, max_age_days: int) -> int | None:
    """The snapshot's age in days, or :class:`StaleSnapshotError` when it is more than ``max_age_days`` old.
    ``max_age_days`` 0 means no check (None is returned). Pinned jobs are checked once, when they pin (D-383)."""
    if max_age_days <= 0:
        return None
    age = snapshot_age_days(snapshot, today)
    if age > max_age_days:
        raise StaleSnapshotError(
            f"LAKE-STALE: the newest lake snapshot is {snapshot}, {age} days before {today.isoformat()}; this box "
            f"refuses a snapshot more than {max_age_days} days old (TB_LAKE_MAX_SNAPSHOT_AGE_DAYS). The nightly "
            "ingest has not published since: check the adapter's last runs (trialbox doctor) before running again."
        )
    return age


def schema_version(con: duckdb.DuckDBPyConnection) -> int | None:
    """The lake schema version of an open snapshot: None without ``lake_meta``, 1 for a snapshot built before
    the version was recorded."""
    cols = {
        r[0] for r in con.execute("SELECT column_name FROM duckdb_columns() WHERE table_name = 'lake_meta'").fetchall()
    }
    if not cols:
        return None
    if "schema_version" not in cols:
        return 1
    row = con.execute("SELECT schema_version FROM lake_meta").fetchone()
    return int(row[0]) if row and row[0] is not None else 1


def cosine_rank(
    cand: list[tuple[str, str]], vecs: dict[str, np.ndarray], qvec: Any, depth: int
) -> list[tuple[str, float]]:
    """``(chunk_key, cosine)`` best first (ties by key), as ``array_cosine_similarity`` ordered in SQL; a chunk
    whose vector is not in the store is left out of the dense ranking (BM25 still finds it)."""
    have = [(key, vecs[sha]) for key, sha in cand if sha in vecs]
    if not have:
        return []
    q = np.asarray(qvec, dtype=np.float32)
    mat = np.stack([v for _, v in have]).astype(np.float32, copy=False)
    norms = np.linalg.norm(mat, axis=1) * float(np.linalg.norm(q))
    with np.errstate(divide="ignore", invalid="ignore"):
        scores = (mat @ q) / norms
    ranked = sorted(
        ((key, float(s)) for (key, _), s in zip(have, scores, strict=True) if np.isfinite(s)),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return ranked[:depth]


def check_schema(con: duckdb.DuckDBPyConnection, snapshot: str) -> int:
    """The snapshot's schema version, or :class:`LakeSchemaError` with a message a steward can act on."""
    v = schema_version(con)
    if v is None or v < MIN_READABLE_SCHEMA:
        raise LakeSchemaError(
            f"LAKE-SCHEMA: lake snapshot {snapshot} was built by an older TrialBox (lake schema "
            f"{'unrecorded' if v is None else v}; this box reads {MIN_READABLE_SCHEMA} to {LAKE_SCHEMA_VERSION}). "
            "Rebuild it from its NDJSON (adapter run, or the lake /rebuild call) before using it."
        )
    if v > LAKE_SCHEMA_VERSION:
        raise LakeSchemaError(
            f"LAKE-SCHEMA: lake snapshot {snapshot} was built by a newer TrialBox (lake schema {v}; this box reads "
            f"{MIN_READABLE_SCHEMA} to {LAKE_SCHEMA_VERSION}). Finish the update of every service before using it."
        )
    return v


def _tombstones(src: Path) -> dict[str, list[str]]:
    """The ids the source deleted in this snapshot (``tombstones.json`` beside its NDJSON, written by the adapter on a
    delta night), by resource type; {} when there is none or it cannot be read."""
    try:
        body = json.loads((src / "tombstones.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(t): [str(i) for i in ids] for t, ids in body.items()} if isinstance(body, dict) else {}


def _compat_views(con: duckdb.DuckDBPyConnection, version: int) -> None:
    """A snapshot built before schema 4 has no ``patient.deceased``: a temporary view of this connection adds it as
    unknown (NULL), so the compiled SQL of today reads a pinned older snapshot as it read it before (T-616)."""
    if version >= 4:
        return
    row = con.execute("SELECT current_database()").fetchone()
    db = str(row[0]).replace('"', '""') if row else "main"
    with contextlib.suppress(duckdb.Error):  # no patient table (a partial test lake): nothing to add
        con.execute(f'CREATE TEMP VIEW patient AS SELECT *, CAST(NULL AS BOOLEAN) AS deceased FROM "{db}".main.patient')


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_sidecar(path: Path, digest: str | None = None) -> str:
    """``<file>.sha256`` in the ``sha256sum`` format, written atomically; returns the hash (``digest`` when the caller
    hashed the same bytes already)."""
    digest = digest or _file_sha(path)
    side = path.with_name(path.name + ".sha256")
    tmp = side.with_name(side.name + ".tmp")
    tmp.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    tmp.replace(side)
    return digest


def check_sidecar(path: Path) -> str | None:
    """None when ``path`` matches its sidecar; else what is wrong, in words."""
    side = path.with_name(path.name + ".sha256")
    if not path.exists():
        return f"{path.name}: missing"
    if not side.exists():
        return f"{path.name}: no .sha256 sidecar"
    want = side.read_text(encoding="utf-8").split()[0]
    return None if _file_sha(path) == want else f"{path.name}: content does not match its .sha256 sidecar"


def fts_extension_path() -> str:
    import duckdb_extension_fts as ext

    candidates = sorted(Path(ext.__file__).parent.glob("extensions/*/fts.duckdb_extension"))
    if not candidates:
        raise RuntimeError("duckdb-extension-fts wheel has no extension binary")
    return str(candidates[-1])


@dataclass
class RebuildStats:
    snapshot: str
    tables: dict[str, int]
    chunks: int
    embedded_new: int
    seconds: float
    promoted: bool = True  # False: built but not made CURRENT (not asked, or older than CURRENT: DATA-007)


CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")  # cgroup v2: the container's cap (compose mem_limit)


def _cgroup_memory_max() -> int | None:
    """The container's memory cap in bytes, or None when there is none (``max``) or no cgroup v2 file."""
    try:
        raw = CGROUP_MEMORY_MAX.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return int(raw) if raw.isdigit() else None


def memory_limit() -> str:
    """``TB_LAKE_MEMORY_LIMIT`` (e.g. ``8GB``) or 40 % of the memory this process may use: the smaller of physical
    memory and the container's cap (T-108a, D-360: with ``mem_limit`` set, 40 % of the host would get the lake
    killed). The lake shares the host with HAPI and (on GB10) the model in unified memory."""
    env = os.environ.get("TB_LAKE_MEMORY_LIMIT")
    if env:
        return env
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    cap = _cgroup_memory_max()
    if cap is not None:
        total = min(total, cap)
    return f"{max(1, int(total * 0.4 / 2**30))}GB"


def temp_limit(temp_dir: Path) -> str:
    """``TB_LAKE_MAX_TEMP`` (e.g. ``20GB``) or a quarter of the free space where the lake spills, at most 50 GB and
    at least 1 GB: a query that needs more fails with :class:`LakeLimitError` instead of filling the disk the lake,
    the audit log and the backups share (review XL-02)."""
    env = os.environ.get("TB_LAKE_MAX_TEMP")
    if env:
        return env
    try:
        free = shutil.disk_usage(temp_dir).free
    except OSError:
        free = 4 * 2**30
    return f"{max(1, min(50, int(free * 0.25 / 2**30)))}GB"


def temp_dir(lake_dir: Path) -> Path:
    """Where DuckDB spills: ``TB_LAKE_TEMP_DIR`` or ``<lake>/tmp`` (on the lake volume, never the container's root)."""
    env = os.environ.get("TB_LAKE_TEMP_DIR")
    return Path(env) if env else lake_dir / "tmp"


class LakeLimitError(RuntimeError):
    """A lake query needed more memory or spill space than the box allows (``TB_LAKE_MEMORY_LIMIT``,
    ``TB_LAKE_MAX_TEMP``). The query is stopped; nothing is left on disk."""


def _limit_message(exc: Exception) -> str:
    return (
        "LAKE-LIMIT: the lake query needed more than the box allows (memory_limit "
        f"{memory_limit()}, spill limit TB_LAKE_MAX_TEMP) and was stopped before it filled the disk. This usually "
        "means a join that multiplies rows (one patient listed twice); raise TB_LAKE_MAX_TEMP only if the data "
        f"really is that large. DuckDB: {str(exc).splitlines()[0][:200]}"
    )


class Lake:
    def __init__(self, lake_dir: Path, tz: str | None = None, mrn_regex: str | None = None) -> None:
        from tb_common.config import site_tz

        self.dir = lake_dir
        self.tz = site_tz(tz)  # the site's zone; TB_TZ when not given, never a default (D-315)
        # T-600 (D-337): the site's chart number pattern; note text is masked with it, and with the labelled
        # patterns of ``phi_guard.mask_note``, before chunks, the full-text index and the embeddings are made
        self.mrn_regex = mrn_regex
        self._lock = threading.Lock()
        for sub in ("ndjson", "parquet", "db"):
            (lake_dir / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ snapshots
    def current(self) -> str | None:
        p = self.dir / "CURRENT"
        return p.read_text().strip() if p.exists() else None

    def pin(self, today: date, max_age_days: int) -> str:
        """The snapshot a job starting ``today`` reads to its end (T-305a, D-383): ``CURRENT`` now, checked for age.
        A later publish moves ``CURRENT`` but never the pin: the job passes its snapshot to every query."""
        snap = self.current()
        if not snap:
            raise FileNotFoundError("lake has no snapshot yet (run adapter / rebuild)")
        self.db_path(snap)
        check_snapshot_age(snap, today, max_age_days)
        return snap

    # ------------------------------------------------------------------ holds (T-305b, D-403)
    def hold(self, snapshot: str, holder: str) -> None:
        """``holder`` (a job id) reads ``snapshot`` until :meth:`release`: the snapshot is neither rebuilt
        (:class:`SnapshotHeld`) nor pruned meanwhile. Holding again refreshes the hold's time."""
        if not _HOLDER.match(holder):
            raise ValueError(f"lake hold: {holder!r} is not a job id")
        with lake_lock(self.dir):  # D-462: never between a rebuild's last hold check and its swap
            self.db_path(snapshot)
            d = _holds_dir(self.dir)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f".{holder}.tmp"
            tmp.write_text(json.dumps({"snapshot": snapshot, "holder": holder, "at": time.time()}), encoding="utf-8")
            tmp.replace(d / f"{holder}.json")

    def release(self, holder: str) -> bool:
        """End ``holder``'s hold; False when it held nothing."""
        if not _HOLDER.match(holder):
            return False
        p = _holds_dir(self.dir) / f"{holder}.json"
        with lake_lock(self.dir):
            existed = p.exists()
            p.unlink(missing_ok=True)
        return existed

    def holds(self) -> dict[str, str]:
        """``holder -> snapshot`` of the live holds (expired ones left out)."""
        return held_snapshots(self.dir)

    def snapshots(self) -> list[str]:
        return sorted(p.stem for p in (self.dir / "db").glob("*.duckdb"))

    def db_path(self, snapshot: str | None = None) -> Path:
        snap = snapshot or self.current()
        if not snap:
            raise FileNotFoundError("lake has no snapshot yet (run adapter / rebuild)")
        path = self.dir / "db" / f"{snap}.duckdb"
        if not path.exists():
            raise FileNotFoundError(f"no lake snapshot {snap}")
        return path

    def promote(self, snapshot: str) -> None:
        """Make ``snapshot`` the one served by default (``CURRENT``), atomically."""
        self.db_path(snapshot)
        tmp = self.dir / "CURRENT.tmp"
        tmp.write_text(snapshot)
        tmp.replace(self.dir / "CURRENT")

    def verify(self, snapshot: str | None = None) -> list[str]:
        """Every Parquet and DuckDB file of the snapshot against its ``.sha256`` sidecar; [] when all match."""
        path = self.db_path(snapshot)
        snap = path.stem
        problems = [p for p in [check_sidecar(path)] if p]
        pdir = self.dir / "parquet" / f"snapshot={snap}"
        if not any(pdir.glob("*.parquet")):  # D-462: a swap cut short leaves no folder; that is not "all match"
            problems.append(f"parquet/snapshot={snap}: missing or empty")
        for f in sorted(pdir.glob("*.parquet")):
            if (why := check_sidecar(f)) is not None:
                problems.append(why)
        return problems

    # ------------------------------------------------------------------ site inputs (D-135)
    def put_site(self, resources: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        """Replace the site's own inputs (FHIR resources by type, from ``sitesetup.publish``); the next rebuild
        joins them to the snapshot. Written beside the snapshots, in the lake's own folder (in every backup)."""
        site = self.dir / "site"
        site.mkdir(parents=True, exist_ok=True)
        for old in site.glob("*.ndjson"):
            if old.stem not in resources:
                old.unlink()
        for rtype, items in resources.items():
            tmp = site / f"{rtype}.ndjson.tmp"
            with tmp.open("w", encoding="utf-8") as fh:
                for r in items:
                    fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            tmp.replace(site / f"{rtype}.ndjson")
        return {k: len(v) for k, v in resources.items()}

    # ------------------------------------------------------------------ rebuild
    def _source(self, snapshot: str) -> Path:
        """The NDJSON folder of ``snapshot``: ``ndjson/<snapshot>``, else the folder the snapshot was last built from
        (``db/<snapshot>.duckdb.source``; a lake built elsewhere may have no ``ndjson/<snapshot>``)."""
        own = self.dir / "ndjson" / snapshot
        rec = self.dir / "db" / f"{snapshot}.duckdb.source"
        if not own.is_dir() and rec.exists():
            return Path(rec.read_text(encoding="utf-8").strip())
        return own

    def fed(self) -> bool:
        """Whether this lake has ever held a hospital feed (D-271): a ``FEED`` marker (written by a rebuild that read
        patient or clinical records), an NDJSON snapshot folder, a recorded source folder, or a snapshot not marked
        as built from the site's inputs alone (a lake built before the marker existed counts as fed)."""
        db = self.dir / "db"
        return (
            (self.dir / "FEED").exists()
            or any(p.is_dir() for p in (self.dir / "ndjson").glob("*"))
            or any(db.glob("*.duckdb.source"))
            or any(not p.with_name(p.name + ".siteonly").exists() for p in db.glob("*.duckdb"))
        )

    def _check_drop(self, snapshot: str, have: dict[str, int]) -> None:
        """D-271: a snapshot that would replace ``CURRENT`` with (nearly) none of a kind of its records is refused,
        unless ``TB_FEED_DROP_OVERRIDE`` names this snapshot."""
        cur = self.current()
        if not cur or cur == snapshot:
            return
        src = self._source(cur)
        before = {}
        for f in src.glob("*.ndjson") if src.is_dir() else ():
            with f.open("rb") as fh:
                before[f.stem] = sum(1 for line in fh if line.strip())
        try:
            pct = feedguard.max_drop_pct()
        except feedguard.FeedGuardError as e:
            raise RebuildError(f"lake snapshot {snapshot}: {e}") from None
        bad = feedguard.drops(before, {t: n - have.get(t, 0) for t, n in before.items()}, pct)
        if bad and not feedguard.override_for(snapshot):
            raise RebuildError(
                f"lake snapshot {snapshot} would drop {'; '.join(bad)} records of CURRENT {cur} (limit {pct:g} %); "
                f"nothing built, CURRENT unchanged. To build it anyway set "
                f"{feedguard.OVERRIDE_ENV}='{snapshot}: <reason>'"
            )

    def rebuild(
        self,
        snapshot: str,
        embedder: Embedder,
        ndjson_dir: Path | None = None,
        promote: bool = True,
        allow_empty: bool = False,
        check: bool = False,
    ) -> RebuildStats:
        """Build ``db/<snapshot>.duckdb`` (into ``.building``, renamed when complete, with ``.sha256`` sidecars) and,
        with ``promote``, make it ``CURRENT``. The adapter calls this only for a night that passed validation.

        ``check`` (T-723, D-489): build without promoting, but judge the data as a night that will be promoted (the
        drop against ``CURRENT``): the publish builds first, loads the other stores, and promotes last
        (:meth:`promote_built`).

        A snapshot older than ``CURRENT`` (a late re-run of an earlier night) is built but never made ``CURRENT``
        (T-106b, DATA-007): the box does not move back in time, the same rule as the OMOP store's.

        Once the lake has held a hospital feed (``fed``), a missing NDJSON folder, or one without a single record, is
        refused (``RebuildError``) before anything is written, unless ``allow_empty``. A lake that never had a feed
        (the practice site, a box before its first night) is built from the site's own inputs alone.

        D-462: one rebuild of a snapshot at a time (:class:`SnapshotBuilding`); the build is written beside the served
        files and swapped in under :func:`lake_lock` after the holds are read again: a snapshot a job came to hold
        during the build is refused there (:class:`SnapshotHeld`) and its bytes stay as the job pinned them."""
        with building(self.dir, snapshot):
            return self._rebuild(snapshot, embedder, ndjson_dir, promote, allow_empty, check)

    def promote_built(self, snapshot: str) -> bool:
        """T-723 (D-489): make the built ``snapshot`` the served one, as the last step of a publish. False, and
        nothing changed, when a newer night is served (the box never moves back in time: DATA-007). Under the lake's
        lock, so two publishes cannot cross."""
        with lake_lock(self.dir):
            cur = self.current()
            if cur is not None and snapshot < cur:
                return False
            self.promote(snapshot)
            return True

    def start_rebuild(
        self,
        snapshot: str,
        embedder: Embedder,
        ndjson_dir: Path | None = None,
        promote: bool = True,
        allow_empty: bool = False,
        spawn: Any = None,
        check: bool = False,
    ) -> dict[str, Any]:
        """Start a rebuild of ``snapshot`` as a job and answer its state (T-690, D-472): the lake service's 202.

        What can be decided at once is decided here and raised as before, nothing written: another rebuild of the
        snapshot runs (:class:`SnapshotBuilding`), a job holds it (:class:`SnapshotHeld`), its NDJSON folder is
        missing (:class:`RebuildError`). The build itself runs in ``spawn`` (the service: a thread; default: here,
        so an in-process lake answers the job's end), holding the build lock taken here, and records its end in the
        job's state (:meth:`rebuild_state`). No time limit: the job runs as long as the build does (OD-10)."""
        lock = contextlib.ExitStack()
        lock.enter_context(building(self.dir, snapshot))
        try:
            with lake_lock(self.dir):
                if _is_held(self.dir, snapshot):
                    raise SnapshotHeld(
                        f"lake snapshot {snapshot} is being read by a running job; it is not rebuilt until the job "
                        "ends (nothing built, CURRENT unchanged)"
                    )
            self._source_or_refuse(snapshot, ndjson_dir, allow_empty)
            job: dict[str, Any] = {
                "job": os.urandom(8).hex(),
                "snapshot": snapshot,
                "state": "running",
                "started": time.time(),
                "ended": None,
                "result": None,
                "busy": None,
                "detail": "",
            }
            write_rebuild_job(self.dir, job)
        except BaseException:
            lock.close()
            raise

        def run() -> None:
            with lock:
                end: dict[str, Any] = {}
                try:
                    st = self._rebuild(snapshot, embedder, ndjson_dir, promote, allow_empty, check)
                    end = {"state": "done", "result": {"snapshot": st.snapshot, "tables": st.tables,
                                                       "chunks": st.chunks, "embedded_new": st.embedded_new,
                                                       "seconds": st.seconds, "promoted": st.promoted}}  # fmt: skip
                except LakeBusy as exc:
                    end = {"state": "busy", "busy": exc.reason, "detail": str(exc)[:500]}
                except RebuildError as exc:
                    end = {"state": "refused", "detail": str(exc)[:500]}
                except Exception as exc:
                    if type(exc).__name__ == "OmopError":  # D-271: the OMOP store refused the batch
                        end = {"state": "refused", "detail": str(exc)[:500]}
                    else:
                        log.exception("lake rebuild of %s failed", snapshot)
                        end = {"state": "failed", "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}
                write_rebuild_job(self.dir, {**job, **end, "ended": time.time()})

        (spawn or _inline)(run)
        return self.rebuild_state(snapshot)

    def rebuild_state(self, snapshot: str) -> dict[str, Any]:
        """The state of the last rebuild job of ``snapshot`` (T-690, D-472): ``none`` when there was none; a job
        recorded ``running`` whose build lock no live process holds ended without an answer: ``interrupted``."""
        job = _read_job(self.dir, snapshot)
        if job is None:
            return {"snapshot": snapshot, "state": "none"}
        if job.get("state") == "running" and not build_running(self.dir, snapshot):
            again = _read_job(self.dir, snapshot) or job  # it may have just ended and written its answer
            if again.get("state") == "running":
                why = "the rebuild stopped without an answer (its process ended); start it again"
                return {**again, "state": "interrupted", "detail": why}
            return again
        return job

    def _source_or_refuse(self, snapshot: str, ndjson_dir: Path | None, allow_empty: bool) -> tuple[Path, bool]:
        """The NDJSON folder of the rebuild and whether an empty one is allowed; a missing folder of a fed lake is
        refused (D-271) before anything is written."""
        src = ndjson_dir or self._source(snapshot)
        allow_empty = allow_empty or not self.fed()
        if not src.is_dir() and not allow_empty:
            raise RebuildError(f"lake snapshot {snapshot}: no NDJSON folder {src}; nothing built, CURRENT unchanged")
        return src, allow_empty

    def _rebuild(
        self,
        snapshot: str,
        embedder: Embedder,
        ndjson_dir: Path | None,
        promote: bool,
        allow_empty: bool,
        check: bool = False,
    ) -> RebuildStats:
        t0 = time.perf_counter()
        db_path = self.dir / "db" / f"{snapshot}.duckdb"
        tmp = db_path.with_suffix(".building")
        stage = self.dir / "parquet" / ".building" / f"snapshot={snapshot}"  # D-462: beside the served Parquet
        old = stage.with_name(f"snapshot={snapshot}.old")
        # leftovers of a rebuild of this snapshot that was killed (this one holds its build lock: nobody else writes)
        tmp.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        # T-305b (D-403, FR-REP-02): a built snapshot a running job holds is never rebuilt under it
        with lake_lock(self.dir):
            if _is_held(self.dir, snapshot):
                raise SnapshotHeld(
                    f"lake snapshot {snapshot} is being read by a running job; it is not rebuilt until the job ends "
                    "(nothing built, CURRENT unchanged)"
                )
        cur = self.current()
        if promote and cur is not None and snapshot < cur:
            log.warning("lake snapshot %s is older than CURRENT %s: built, not promoted (DATA-007)", snapshot, cur)
            promote = False
        src, allow_empty = self._source_or_refuse(snapshot, ndjson_dir, allow_empty)
        by_type: dict[str, list[dict[str, Any]]] = {}
        for f in sorted(src.glob("*.ndjson")):
            with f.open(encoding="utf-8") as fh:
                by_type[f.stem] = [json.loads(line) for line in fh if line.strip()]
        have = {t: len(v) for t, v in by_type.items() if v and t not in feedguard.STATIC_TYPES}
        if not have and not allow_empty:
            raise RebuildError(
                f"lake snapshot {snapshot}: {src} holds no patient or clinical record; nothing built, CURRENT unchanged"
            )
        if (promote or check) and not allow_empty:  # only a snapshot that replaces CURRENT is compared with it
            self._check_drop(snapshot, have)
        try:
            counts, n_chunks, new = self._build(snapshot, embedder, src, by_type, stage, tmp)
        except BaseException:
            tmp.unlink(missing_ok=True)
            shutil.rmtree(stage, ignore_errors=True)
            raise
        digest = _file_sha(tmp)
        with lake_lock(self.dir):  # D-462: the swap; no hold can land between this check and the rename
            if _is_held(self.dir, snapshot):
                tmp.unlink(missing_ok=True)
                shutil.rmtree(stage, ignore_errors=True)
                raise SnapshotHeld(
                    f"lake snapshot {snapshot} came to be read by a running job while it was rebuilt; the new build "
                    "is discarded and the snapshot is not rebuilt until the job ends (CURRENT unchanged)"
                )
            pdir = self.dir / "parquet" / f"snapshot={snapshot}"
            if pdir.exists():
                pdir.rename(old)
            stage.rename(pdir)
            shutil.rmtree(old, ignore_errors=True)
            tmp.replace(db_path)
            write_sidecar(db_path, digest)  # hashed before the lock: holds and releases never wait for a hash
            drop_reader_links(self.dir, snapshot)
            rec = self.dir / "db" / f"{snapshot}.duckdb.source"  # pruned with the snapshot (``<snap>.duckdb*``)
            if src.is_dir() and src.resolve() != (self.dir / "ndjson" / snapshot).resolve():
                rec.write_text(str(src.resolve()) + "\n", encoding="utf-8")
            else:
                rec.unlink(missing_ok=True)
            siteonly = self.dir / "db" / f"{snapshot}.duckdb.siteonly"
            if have:
                (self.dir / "FEED").write_text(snapshot + "\n", encoding="utf-8")
                siteonly.unlink(missing_ok=True)
            else:
                siteonly.write_text("built from the site's own inputs only\n", encoding="utf-8")
            cur = self.current()  # another night may have been promoted during the build (DATA-007)
            if promote and cur is not None and snapshot < cur:
                log.warning("lake snapshot %s is older than CURRENT %s: built, not promoted (DATA-007)", snapshot, cur)
                promote = False
            if promote:
                self.promote(snapshot)
        return RebuildStats(snapshot, counts, n_chunks, new, round(time.perf_counter() - t0, 2), promote)

    def _build(
        self,
        snapshot: str,
        embedder: Embedder,
        src: Path,
        by_type: dict[str, list[dict[str, Any]]],
        pdir: Path,
        tmp: Path,
    ) -> tuple[dict[str, int], int, int]:
        """The build itself, into ``pdir`` (the staging Parquet folder) and ``tmp`` (``<snapshot>.building``): nothing
        a reader sees is touched here."""
        # D-135: the site's own inputs (sheets, dumps, charts; ``put_site``) join every snapshot built here
        site: dict[str, list[dict[str, Any]]] = {}
        for f in sorted((self.dir / "site").glob("*.ndjson")):
            with f.open(encoding="utf-8") as fh:
                site.setdefault(f.stem, []).extend(json.loads(line) for line in fh if line.strip())
        # D-151: flattened from the NDJSON (TB_LAKE_SOURCE=legacy) or exported from the OMOP store (omop)
        rows = lake_rows(by_type, site, tz=self.tz, snapshot=snapshot, lake_dir=self.dir, deleted=_tombstones(src))
        by_type.clear()  # the flat rows replace the resources; free them before the embedding pass
        site.clear()
        counts = {name: len(rows[name]) for name in SCHEMAS}
        pdir.mkdir(parents=True, exist_ok=True)
        for name, cols in SCHEMAS.items():
            schema = pa.schema([(c, _ARROW[t]) for c, t in cols])
            table = pa.Table.from_pylist(rows[name], schema=schema)
            pq.write_table(table, pdir / f"{name}.parquet")
            del table
            if name != "document":
                rows[name] = []  # DuckDB reads the Parquet file; only document rows are needed for chunking
        # chunks: from the masked note text (T-600, D-337). The ``document`` table and its Parquet file, labelled
        # ``phi`` (``lake.flatten.PHI_COLUMNS``), keep the original; chunks, BM25 tokens and embeddings never see it.
        chunk_rows: list[dict[str, Any]] = []
        for doc in sorted(rows["document"], key=lambda r: r["did"]):
            for i, text in enumerate(chunk(mask_note(doc["text"] or "", self.mrn_regex))):
                chunk_rows.append(
                    {
                        "did": doc["did"],
                        "chunk_no": i,
                        "pid": doc["pid"],
                        "date": doc["date"],
                        "type": doc["type"],
                        "text": text,
                        "tok": token_string(text),
                        "sha": sha256_text(text),
                    }
                )
        new = self._embed(chunk_rows, embedder)
        tmp.unlink(missing_ok=True)
        con = duckdb.connect(str(tmp))
        try:
            con.execute(f"LOAD '{fts_extension_path()}'")
            for name in SCHEMAS:
                con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet(?)", [str(pdir / f"{name}.parquet")])
            con.execute("CREATE TABLE document_chunk (" + ", ".join(f"{c} {t}" for c, t in CHUNK_COLUMNS) + ")")
            if chunk_rows:
                for i in range(0, len(chunk_rows), INSERT_BATCH):
                    part = chunk_rows[i : i + INSERT_BATCH]
                    batch: dict[str, Any] = {
                        k: [r[k] for r in part]
                        for k in ("did", "chunk_no", "pid", "date", "type", "text", "tok", "sha")
                    }
                    batch["chunk_key"] = [f"{r['did']}#{r['chunk_no']}" for r in part]
                    con.register("chunks_arrow", pa.table(batch))
                    chunk_cols = ", ".join(c for c, _ in CHUNK_COLUMNS)
                    con.execute(f"INSERT INTO document_chunk SELECT {chunk_cols} FROM chunks_arrow")
                    con.unregister("chunks_arrow")
                con.execute(
                    "PRAGMA create_fts_index('document_chunk', 'chunk_key', 'tok', stemmer='none', "
                    "stopwords='none', ignore='\\s+', strip_accents=0, lower=1, overwrite=1)"
                )
            con.execute(
                "CREATE TABLE lake_meta AS SELECT ? AS snapshot, ? AS built_at, ? AS schema_version, ? AS schema_sha, "
                "? AS embed_store, ? AS embed_model, ? AS note_mask",
                [
                    snapshot,
                    datetime.now(UTC).isoformat(timespec="seconds"),  # D-315: never the container's own zone
                    LAKE_SCHEMA_VERSION,
                    schema_sha(),
                    "embed_cache.duckdb",
                    embedder.model,
                    NOTE_MASK_VERSION,
                ],
            )
            con.execute("CHECKPOINT")
        finally:
            con.close()
        for f in sorted(pdir.glob("*.parquet")):
            write_sidecar(f)
        return counts, len(chunk_rows), new

    def _cache(self, read_only: bool) -> duckdb.DuckDBPyConnection:
        """A connection to the vector store; another process holding the write lock is waited for (up to 30 s)."""
        path = self.dir / "embed_cache.duckdb"
        deadline = time.monotonic() + 30
        while True:
            try:
                return duckdb.connect(str(path), read_only=read_only)
            except duckdb.IOException:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)

    def _embed(self, chunk_rows: list[dict[str, Any]], embedder: Embedder) -> int:
        """Make sure every chunk's vector is in ``embed_cache.duckdb`` (embed new texts only); return how many were
        new. The store is opened only for each read or write, never across the embedding calls, so a search can
        read vectors while a long first build runs."""
        shas = sorted({r["sha"] for r in chunk_rows})
        with _CACHE_LOCK:
            cache = self._cache(read_only=False)
            try:
                cache.execute(
                    f"CREATE TABLE IF NOT EXISTS cache (sha VARCHAR, model VARCHAR, vec FLOAT[{DIM}], "
                    "PRIMARY KEY (sha, model))"
                )
                have: set[str] = set()
                if shas:
                    cache.register("want", pa.table({"sha": shas}))
                    have = {
                        r[0]
                        for r in cache.execute(
                            "SELECT c.sha FROM cache c JOIN want w USING (sha) WHERE c.model = ?", [embedder.model]
                        ).fetchall()
                    }
                    cache.unregister("want")
            finally:
                cache.close()
        missing = [s for s in shas if s not in have]
        text_by_sha = {r["sha"]: r["text"] for r in chunk_rows}
        pending: dict[str, list[Any]] = {"sha": [], "vec": []}

        def flush() -> None:
            if not pending["sha"]:
                return
            with _CACHE_LOCK:
                cache = self._cache(read_only=False)
                try:
                    table = pa.table(
                        {"sha": pending["sha"], "model": [embedder.model] * len(pending["sha"]), "vec": pending["vec"]}
                    )
                    cache.register("newvecs", table)
                    cache.execute(f"INSERT OR REPLACE INTO cache SELECT sha, model, vec::FLOAT[{DIM}] FROM newvecs")
                    cache.unregister("newvecs")
                finally:
                    cache.close()
            pending["sha"], pending["vec"] = [], []

        for i in range(0, len(missing), 64):
            batch = missing[i : i + 64]
            vecs = embedder.embed([text_by_sha[s] for s in batch])
            pending["sha"].extend(batch)
            pending["vec"].extend(np.asarray(v, dtype=np.float32).tolist() for v in vecs)
            if len(pending["sha"]) >= INSERT_BATCH:
                flush()
        flush()
        return len(missing)

    def vectors(self, shas: list[str], model: str) -> dict[str, np.ndarray]:
        """sha -> float32 vector from the vector store, for the given embedding model (absent shas are left out)."""
        if not shas or not (self.dir / "embed_cache.duckdb").exists():
            return {}
        out: dict[str, np.ndarray] = {}
        with _CACHE_LOCK:
            cache = self._cache(read_only=True)
            try:
                cache.register("want", pa.table({"sha": sorted(set(shas))}))
                got = cache.execute(
                    "SELECT c.sha, c.vec FROM cache c JOIN want w USING (sha) WHERE c.model = ?", [model]
                ).to_arrow_table()
                cache.unregister("want")
            finally:
                cache.close()
        if got.num_rows:
            mat = got.column("vec").combine_chunks().flatten().to_numpy(zero_copy_only=False)
            mat = mat.astype(np.float32).reshape(-1, DIM)
            for sha, row in zip(got.column("sha").to_pylist(), mat, strict=True):
                out[sha] = row
        return out

    # ------------------------------------------------------------------ query
    def connect(self, snapshot: str | None = None) -> duckdb.DuckDBPyConnection:
        """Read-only connection with FTS loaded, external file access disabled and configuration locked."""
        # DuckDB shares one database instance per file inside a process: a concurrent connection finds the
        # instance already hardened (FTS loaded, external access off, configuration locked) and must not re-set it.
        with _CONNECT_LOCK:
            for attempt in range(3):
                path = reader_path(self.db_path(snapshot))  # D-462: replaced bytes are never a cached copy
                try:
                    con = duckdb.connect(str(path), read_only=True)
                    break
                except duckdb.IOException:
                    if path.exists() or attempt == 2:  # a link removed by a swap meanwhile: look again
                        raise
            row = con.execute("SELECT current_setting('lock_configuration')").fetchone()
            if not (row and row[0]):
                con.execute(f"LOAD '{fts_extension_path()}'")
                # bounded memory, spill to the lake volume: a hospital-scale FEAS must not take the host down (D-80)
                tmp = temp_dir(self.dir)
                tmp.mkdir(parents=True, exist_ok=True)
                con.execute(f"SET memory_limit = '{memory_limit()}'")
                con.execute(f"SET temp_directory = '{tmp}'")
                con.execute(f"SET max_temp_directory_size = '{temp_limit(tmp)}'")
                con.execute("SET preserve_insertion_order = false")
                con.execute("SET enable_external_access = false")
                con.execute("SET lock_configuration = true")
        try:
            _compat_views(con, check_schema(con, snapshot or self.current() or ""))
        except LakeSchemaError:
            con.close()
            raise
        return con

    def query(
        self, sql: str, params: list[Any] | None = None, snapshot: str | None = None, timeout_s: int = 300
    ) -> pa.Table:
        from lake.sqlguard import check_select

        check_select(sql)
        con = self.connect(snapshot)
        timer = threading.Timer(timeout_s, con.interrupt)
        timer.start()
        try:
            return con.execute(sql, params or []).to_arrow_table()
        except duckdb.OutOfMemoryException as exc:
            log.error("lake query stopped at its limit: %s", str(exc).splitlines()[0][:200])
            raise LakeLimitError(_limit_message(exc)) from exc
        finally:
            timer.cancel()
            con.close()

    def search(
        self,
        pid: str,
        query: str,
        embedder: Embedder,
        k: int = 5,
        date_from: date | None = None,
        date_to: date | None = None,
        snapshot: str | None = None,
        depth: int = 50,
    ) -> list[dict[str, Any]]:
        """Hybrid retrieval restricted to ``pid`` and a date window: BM25 ∪ cosine, reciprocal-rank fusion."""
        con = self.connect(snapshot)
        try:
            where = "c.pid = ?"
            args: list[Any] = [pid]
            if date_from:
                where += " AND c.date::DATE >= ?"
                args.append(date_from)
            if date_to:
                where += " AND c.date::DATE <= ?"
                args.append(date_to)
            bm25 = con.execute(
                f"SELECT chunk_key, score FROM (SELECT c.chunk_key, "
                f"fts_main_document_chunk.match_bm25(c.chunk_key, ?) AS score FROM document_chunk c WHERE {where}) "
                f"WHERE score IS NOT NULL ORDER BY score DESC, chunk_key LIMIT {int(depth)}",
                [token_string(query), *args],
            ).fetchall()
            qvec = embedder.embed([query])[0]
            if check_schema(con, snapshot or self.current() or "") < 2:  # a snapshot that still carries its vectors
                dense = con.execute(
                    f"SELECT c.chunk_key, array_cosine_similarity(c.embedding, ?::FLOAT[{DIM}]) AS score "
                    f"FROM document_chunk c WHERE {where} ORDER BY score DESC, chunk_key LIMIT {int(depth)}",
                    [qvec, *args],
                ).fetchall()
            else:  # D-149: vectors from the one store, by chunk sha
                cand = con.execute(f"SELECT c.chunk_key, c.sha FROM document_chunk c WHERE {where}", args).fetchall()
                dense = cosine_rank(cand, self.vectors([s for _, s in cand], embedder.model), qvec, depth)
            fused: dict[str, float] = {}
            for ranking in (bm25, dense):
                for rank, (key, _) in enumerate(ranking, start=1):
                    fused[key] = fused.get(key, 0.0) + 1.0 / (60 + rank)
            top = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
            if not top:
                return []
            keys = [kk for kk, _ in top]
            rows = {
                r[0]: r
                for r in con.execute(
                    "SELECT chunk_key, did, chunk_no, text, date, type FROM document_chunk WHERE chunk_key IN "
                    f"({', '.join('?' for _ in keys)})",
                    keys,
                ).fetchall()
            }
            return [
                {
                    "did": rows[kk][1],
                    "chunk_no": rows[kk][2],
                    "text": rows[kk][3],
                    "date": rows[kk][4].date().isoformat(),
                    "score": round(score, 6),
                    "note_type": rows[kk][5],
                }
                for kk, score in top
            ]
        finally:
            con.close()

    def vec_s2b(
        self, pid: str, dids: list[str], query: str, embedder: Embedder, store: Any, snapshot: str | None = None
    ) -> dict[str, Any]:
        """T-203b (D-449, flag ``vec.s2b``): S2b's ranking of one patient's window notes from the vector store
        (schema ``vec``, read by this service only, D-378). The notes are read from ``snapshot`` (the job's pinned
        one) and checked against the stored chunks; a store that is not there, not this snapshot's or not of the
        embedder's model answers ``{"state": "fallback", "reason"}`` and the cascade ranks on the fly
        (:func:`vec.s2b.rank_chunks`)."""
        from vec.index import Note
        from vec.s2b import UNAVAILABLE, fallback, rank_chunks

        if store is None:
            return fallback(UNAVAILABLE)
        want = sorted(set(dids))
        rows = self.query(
            "SELECT did, pid, CAST(date AS DATE) AS d, type, text FROM document "
            "WHERE pid = $1 AND list_contains(CAST($2 AS VARCHAR[]), did) ORDER BY did",
            [pid, want],
            snapshot,
        ).to_pylist()
        if sorted(str(r["did"]) for r in rows) != want:  # a note the cascade read is not this patient's in the snapshot
            return fallback("a window note is not in the pinned snapshot")
        notes = [
            Note(pid, str(r["did"]), str(r["text"] or ""), r["d"].isoformat() if r["d"] else None, r["type"])
            for r in rows
        ]
        return rank_chunks(store, embedder, pid, notes, query, self.mrn_regex)
