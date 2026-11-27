"""``publish(night)``: one resumable function (T-723, D-489; lifecycle review F-2, F-3, F-12, proposal G-2).

A night that may be published (it passed the gate, or a steward accepted it) is published by :func:`publish_night`,
in this order, each step only when the one before it is done:

1. ``build``: the lake builds the night and judges it (the drop against the served night), **without serving it**
   (``AdapterConfig.build``). A lake that refuses the data, is busy or fails ends the publish here: no other store
   was touched;
2. ``omop``: the dual write into OMOP, where it is on;
3. ``fhir``: the FHIR store;
4. ``lake``: the promotion (``AdapterConfig.promote``), one atomic move; with a lake that only builds and promotes
   in one call (``AdapterConfig.rebuild`` alone: the tools, and a re-run of the served night, whose build replaces
   the served file), that call;
5. ``pidmap``: the night's staged chart numbers enter the pid map. They wait in ``pidmap.pending`` until the night
   is served, so the numbers of a night that is held, refused or not promoted never reach the reverse map.

Then, and only then, ``passed.json`` is written.

**The stores stay at one night.** When the promotion does not happen (the FHIR load failed part-way, the lake's
one call did not end well, a newer night was promoted meanwhile), the FHIR store is put back to the night the lake
serves (``fhir_back``: every resource of that night is loaded again, so a resource the broken load had changed goes
back too); if that fails, the publish says so and its ``fhir`` step stays ``failed``. The OMOP store of record
(dual write, where it is on) is the one store that can be a night ahead until the publish is resumed: it never moves
back (D-339).

**The FHIR store's intent is one box-level file** (E2E P-03): ``<lake>/FHIR_STATE`` holds what the store was last
told to become (a night and its NDJSON's fingerprint, or nothing) and whether it was checked to be that since
(``verified``); it is written only under ``<lake>/fhir.lock`` (an exclusive ``flock`` the kernel drops with its
process: a held lock is a live owner). "Clean" is never stored: it is derived at every read (:func:`derive`) from the
intent and what the lake serves (``CURRENT`` and the served folder's fingerprint), so anything that moves ``CURRENT``
or the served folder (a killed load, a lake build that outlived its publisher, a backup restore) leaves the store
owed by arithmetic. An owed store is put back to the served night before any store is touched (:func:`restore`), and
is clean again only once a put-back was checked against the store (:func:`settle`). While it cannot be, nothing is
published (:class:`FhirRestoreOutstanding`). The FHIR store and the lake are published together or not at all
(:func:`refuse_split`). Two owed states are never put back by the box itself, only refused by name until a person
acts (the known limitations): a store transaction that may still commit after its loader is gone (:data:`UNFENCED`)
and a lake restored behind the trial database's generation ledger (:data:`LAKE_BEHIND`).

**What the lake serves is read, not remembered.** ``Published.promoted`` is ``CURRENT == night`` on every way out,
so a publish that failed after the promotion (the pid map's step, an answer of the lake that was lost) never says
"nothing is served". A promotion whose answer did not arrive is read from ``CURRENT``: when it names the night, the
step is done. A served night whose ``pidmap`` step did not end is finished by :func:`finish_served` before the next
ingest stages anything and before the next publish.

**Never back in time.** A night older than the served one is refused before any step (``stale``): the lake would
build it and not promote it, and the FHIR store would have gone back to it.

**Resumable.** Each step's state is kept in ``publish.json`` in the night's folder, with a fingerprint of the
folder's NDJSON. A second call on the same content skips the steps that are done and starts at the first that is
not. Other content (the night was run again from a changed source) starts from the first step.

**A re-run of the served night** is written beside the served folder (``ndjson-rerun/<night>``, D-271). While a job
holds the snapshot the publish is refused as "lake busy" before any step: nothing is loaded and nothing a job reads
is touched. Without a hold, the re-run's folder takes the served folder's place only for the lake step and is put
back if that step does not end well, so the served folder always holds what the served file was built from. A
process that is killed inside that step leaves the swap on disk (``ndjson-rerun/<night>.replaced``);
:func:`recover_all` puts it back before the next publish or ingest reads anything.

:func:`publish_held` publishes a held night's folder as it stands: the steward's accept (``POST /publish``).
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import logging
import os
import shutil
import socket
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from tb_contracts import RebuildResult

from adapter.load_fhir import (
    LedgerError,
    finish_load,
    finished_after,
    snapshot_ids,
    sync_snapshot,
    upgrade_put_back,
)
from adapter.ndjson import snapshot_dir

if TYPE_CHECKING:
    from adapter.pipeline import AdapterConfig

log = logging.getLogger("adapter")

RECORD = "publish.json"  # in the night's folder: the publish's step record (no patient data)
STEPS = ("build", "omop", "fhir", "lake", "pidmap")
DONE, SKIPPED, FAILED, BUSY, REFUSED, PENDING = "done", "skipped", "failed", "busy", "refused", "pending"
LOADING = "loading"  # the FHIR load began and its end is not recorded yet: a killed process leaves it (P-03)
STALE = "stale"  # a newer night is served: this one is not published (the box never moves back in time)
ENDED = (DONE, SKIPPED)
BUSY_ERROR = "lake busy: the night is run again once the lake is free (nothing was written)"
FHIR_STATE = "FHIR_STATE"  # beside CURRENT: the FHIR store's intent (P-03); never in a night's folder
FHIR_LOCK = "fhir.lock"  # beside CURRENT: held across every FHIR write and every write of FHIR_STATE
FHIR_BUSY_ERROR = "fhir store busy: another publish or recovery holds it (nothing was written)"
# the two refusals that only a person ends (E2E P-03 known limitations; ``tools/trialbox/doctor.py`` fails by them)
UNFENCED = "fhir_write_unfenced"  # review H4: a store transaction may still commit after its loader is gone
LAKE_BEHIND = "lake_behind_generation_ledger"  # review G2: the lake restored to another point than the trial database
_PROCESS_START = datetime.now(UTC).isoformat(timespec="seconds")  # diagnostic only (FHIR_STATE ``by``)


class NothingToPublish(RuntimeError):
    """No held night of that date is on the box."""


class RecoveryBusy(RuntimeError):
    """Another live process holds ``fhir.lock``: a publish or a recovery runs. Refused, never queued."""


class FhirRestoreOutstanding(RuntimeError):
    """The FHIR store is not known to be back to the served night: nothing is published until it is."""


class FhirMismatch(RuntimeError):
    """The FHIR store does not hold the night it was checked against (or did not answer the check)."""


class NightRefused(RuntimeError):
    """The night is refused before any step (:func:`refuse_split`): nothing is read, loaded or promoted."""


@dataclass
class Published:
    snapshot: str
    out_dir: Path  # where the night's folder is now (the served folder once a re-run took its place)
    steps: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    promoted: bool = False  # CURRENT names this night
    held: bool = False  # the lake refused the data (D-271): a held night
    lake_busy: bool = False  # a job holds the snapshot or another rebuild runs (D-462): run again, nothing written
    stale: bool = False  # a newer night is served: refused before any step, nothing loaded
    omop: Any = None
    fhir_loaded: int = 0
    fhir_deleted: int = 0
    lake: RebuildResult | None = None
    fhir_outstanding: str = ""  # a put-back of the FHIR store is owed (FhirRestoreOutstanding's words)

    @property
    def ok(self) -> bool:
        return not self.errors and all(self.steps.get(s) in ENDED for s in STEPS)


def fingerprint(folder: Path) -> str:
    """A hash of the folder's NDJSON files (name, size, content): the content a step record belongs to."""
    h = hashlib.sha256()
    for f in sorted(folder.glob("*.ndjson")):
        h.update(f.name.encode() + b"\0" + str(f.stat().st_size).encode() + b"\0")
        with f.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        h.update(b"\0")
    return h.hexdigest()


def read_record(folder: Path) -> dict[str, Any]:
    try:
        rec = json.loads((folder / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def _write_record(folder: Path, rec: dict[str, Any]) -> None:
    # durable like FHIR_STATE (review D1): a record written before the marker is on disk before it, power cut or not
    _durable(folder / RECORD, json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _durable(path: Path, text: str) -> None:
    """Write ``path`` atomically and durably: the file, then its folder, are synced, so two such writes reach the
    disk in their order. Every durable write of the publish and of the recovery ends in :func:`_checkpoint`."""
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    _checkpoint(path.name)


def _checkpoint(name: str) -> None:
    """A durable write of the publish or the recovery path (``name``: the file, the store or the lake) has just
    ended. Nothing is done here: the crash-point test kills the night at every one in turn and checks that the
    marker is owed or that the store, the records and ``CURRENT`` describe one night
    (``tests/unit/test_killed_fhir_load.py``)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _current(lake_dir: Path) -> str | None:
    p = lake_dir / "CURRENT"
    return p.read_text(encoding="utf-8").strip() or None if p.exists() else None


def holders(lake_dir: Path, snap: str) -> list[str]:
    """The jobs that hold ``snap`` on the lake in ``lake_dir`` (D-403), read from the lake's own hold files."""
    from lake.store import held_snapshots

    return sorted(h for h, s in held_snapshots(lake_dir).items() if s == snap)


def _sync_fhir(cfg: AdapterConfig, folder: Path, previous: Path | None) -> tuple[int, int]:
    assert cfg.fhir_base_url is not None
    # P-03: the load is finished in the generation ledger once the night is served and checked (finish_load), not
    # when its last resource is in: the ledger never lets a put-back go back from a finished newer load, and the
    # put-back to the served night after a promotion that failed is owed exactly then (found by the crash points)
    return sync_snapshot(cfg.fhir_base_url, folder, cfg.lake_dir / "fhir_ledger", previous, finish=False)


def _fhir_put_back(cfg: AdapterConfig, folder: Path) -> tuple[int, int]:
    """Make the FHIR store hold ``folder`` again after a load of another night that may have broken part-way. The
    ledger keeps a changed resource's old hash until a load ends, so a delta would skip exactly the resources the
    broken load changed (second review, H3): every resource is loaded."""
    assert cfg.fhir_base_url is not None
    # ``back``: the generation ledger (D-491) holds the broken load's night as "building"; going back to the served
    # night over it is a put-back, not an older build (found when T-723 and T-725 met on train 4). ``finish`` False:
    # the ledgers move in :func:`settle`, once the store was checked
    return sync_snapshot(
        cfg.fhir_base_url, folder, cfg.lake_dir / "fhir_ledger", None, full=True, back=True, finish=False
    )


def recover(cfg: AdapterConfig, snap: str) -> str:
    """Undo what a re-run of the served night ``snap`` left on disk when its process was killed inside the lake
    step (review MED-2): the re-run's folder in the served folder's place and the served one aside
    (``ndjson-rerun/<snap>.replaced``; a publish that ends removes it). Returns what was done:

    * ``""``: nothing was left;
    * ``"forward"``: the lake had finished the build (the served file is newer than the swap): the re-run is what
      is served, so the folder stays and only the leftover goes;
    * ``"back"``: the served folder is put back, the re-run goes back beside it (unless a later re-run is already
      there: then the killed one is dropped). The FHIR store, which the killed run had loaded with the re-run, is
      put back after this by :func:`restore` (review N3: the swap first, so it goes back to the served folder)."""
    from lake.store import building

    from adapter.pipeline import RERUN_DIR

    aside = cfg.lake_dir / RERUN_DIR / f"{snap}.replaced"
    if not aside.is_dir():
        return ""
    # second review, M3: the adapter was killed, the lake service may still be building from the folder the re-run
    # was moved into. The folder is not taken from under the build: ``SnapshotBuilding`` (the caller says "lake
    # busy" and comes again); the build's lock is held while the folders are moved
    with building(cfg.lake_dir, snap):
        return _recover(cfg, snap, aside)


def _recover(cfg: AdapterConfig, snap: str, aside: Path) -> str:
    from adapter.pipeline import RERUN_DIR

    final_dir = snapshot_dir(cfg.lake_dir, snap)
    rerun_dir = cfg.lake_dir / RERUN_DIR / snap
    # killed between the two renames (M4): no served folder on disk; the re-run, with its record, is still beside
    rec = read_record(final_dir) if final_dir.is_dir() else read_record(rerun_dir) if rerun_dir.is_dir() else {}
    steps = rec.get("steps") or {}
    built = cfg.lake_dir / "db" / f"{snap}.duckdb"
    swapped = int(rec.get("swapped_ns") or 0)
    if final_dir.is_dir() and (
        steps.get("lake") == DONE or (swapped and built.exists() and built.stat().st_mtime_ns > swapped)
    ):
        shutil.rmtree(aside, ignore_errors=True)
        log.warning("publish of %s was interrupted after its lake step: the re-run is the served night", snap)
        return "forward"
    if final_dir.is_dir():
        if rerun_dir.exists():  # a later re-run was written since: it is the one to publish
            shutil.rmtree(final_dir)
        else:
            final_dir.rename(rerun_dir)
        _checkpoint("served folder renamed aside")  # review F5: a kill here leaves no served folder on disk
    aside.rename(final_dir)
    _checkpoint("served folder put back")
    log.warning("publish of %s was interrupted in its lake step: the served folder is put back", snap)
    return "back"


def recover_all(cfg: AdapterConfig) -> list[str]:
    """:func:`recover` for every night a killed re-run left swapped, then (with a FHIR endpoint) :func:`restore`,
    under ``fhir.lock`` (another live holder: :class:`RecoveryBusy`). Called before a publish and before an ingest
    touches any store. A put-back that is owed and fails raises :class:`FhirRestoreOutstanding`; a lake build of the
    night the store was loaded with that still runs, ``SnapshotBuilding``. Returns the nights swapped back."""
    with fhir_lock(cfg, wait=False):
        return _recover_all(cfg)


def _recover_all(cfg: AdapterConfig) -> list[str]:
    """:func:`recover_all`'s body; the caller holds ``fhir.lock``."""
    from adapter.pipeline import RERUN_DIR

    home = cfg.lake_dir / RERUN_DIR
    swapped = sorted(home.glob("*.replaced")) if home.is_dir() else []
    done = [p.name[: -len(".replaced")] for p in swapped if recover(cfg, p.name[:-9])]
    if cfg.fhir_base_url:
        restore(cfg)
    return done


# ------------------------------------------------------------------------------- the FHIR store's intent (P-03)
class Derived(NamedTuple):
    """:func:`derive`'s answer. ``reason``: why the store is owed ("" when clean)."""

    clean: bool
    intent: dict[str, Any]
    served: str | None
    served_fp: str
    reason: str


def read_intent(cfg: AdapterConfig) -> dict[str, Any] | None:
    """``FHIR_STATE``: ``want`` (the night the store was told to hold, "" for nothing), ``fingerprint`` (that night's
    NDJSON as loaded), ``verified`` (the store was checked to be that after its last write), ``reason`` and
    ``attempts`` (why and how often it is still not), ``undoing`` (the night whose load a put-back undoes) and
    ``by``/``updated_at`` (diagnostic only; ``undoing`` only words a refusal). None: no file. A file that cannot be
    read, or one of an earlier version (a box from before this record, any shape): never checked, so owed, and
    ``upgrade`` (never written: the recovery may take the generation ledger back once, review H5)."""
    try:
        st = json.loads((cfg.lake_dir / FHIR_STATE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        st = None
    if (
        not isinstance(st, dict)
        or st.get("version") != 2
        or not isinstance(st.get("want"), str)
        or not isinstance(st.get("fingerprint"), str)
        or not isinstance(st.get("verified"), bool)
    ):
        return {"version": 2, "want": "", "fingerprint": "", "verified": False, "attempts": 0, "upgrade": True,
                "reason": f"{FHIR_STATE} is not this version's: the store was never checked on this box"}  # fmt: skip
    return st


def _served_fp(cfg: AdapterConfig, served: str | None) -> str:
    """The served folder's fingerprint, hashed from its NDJSON every time (review H3: never from its record, which a
    restore of the folder's data can leave as it was)."""
    folder = snapshot_dir(cfg.lake_dir, served) if served else None
    if folder is None or not folder.is_dir():
        return ""
    return fingerprint(folder)


def derive(cfg: AdapterConfig) -> Derived:
    """Whether the FHIR store is clean, derived at every read (never stored): the intent was checked, names the night
    ``CURRENT`` serves (or nothing when none is) and, for a night, the served folder's fingerprint. No file and no
    id ledger: nothing was ever sent (the loader widens its ledger before it sends), so the store held nothing,
    checked. No file beside a ledger (a box from before the file): owed, put back once (reviews D2, D3)."""
    served = _current(cfg.lake_dir)
    fp = _served_fp(cfg, served)
    intent = read_intent(cfg)
    if intent is None:
        intent = {"want": "", "fingerprint": "", "verified": True} if not _ledger_types(cfg) else {
            "want": "", "fingerprint": "", "verified": False, "attempts": 0, "upgrade": True,
            "reason": f"never checked on this box (no {FHIR_STATE} beside the loader's ledger)"}  # fmt: skip
    want = intent["want"]
    if not intent["verified"]:
        why = str(intent.get("reason") or "not checked")
    elif want != (served or ""):
        why = f"CURRENT moved: the store was checked for {want or 'nothing'}, the lake serves {served or 'nothing'}"
    elif want and intent["fingerprint"] != fp:
        why = f"the served folder of {want} is not the NDJSON the store was checked for"
    else:
        why = ""
    return Derived(not why, intent, served, fp, why)


def _write_intent(cfg: AdapterConfig, intent: dict[str, Any]) -> dict[str, Any]:
    """Write ``FHIR_STATE`` atomically and durably (the file, then the folder, are synced). The caller holds
    ``fhir.lock``. Its writes: the publish's FHIR step begins (W1), a put-back begins (W2), a check passed (W3, the
    only ``verified`` True), and a W1 or W2 that is still owed says why (``reason``, ``attempts``)."""
    st = {"version": 2, "want": str(intent["want"]), "fingerprint": str(intent["fingerprint"]),
          "verified": bool(intent.get("verified")), "reason": str(intent.get("reason") or ""),
          "attempts": int(intent.get("attempts") or 0), "undoing": str(intent.get("undoing") or ""),
          "by": _me(), "updated_at": _now()}  # fmt: skip
    _durable(cfg.lake_dir / FHIR_STATE, json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return st


def _me() -> dict[str, Any]:
    return {"pid": os.getpid(), "start": _PROCESS_START, "host": socket.gethostname()}


def outstanding(intent: dict[str, Any]) -> str:
    """The words of an owed put-back (``fhir_restore_outstanding: ...``)."""
    target = intent.get("want") or "nothing (no night served)"
    return (f"fhir_restore_outstanding: the FHIR store is not back to {target} after the load of "
            f"{intent.get('undoing') or 'an earlier night'} ({intent.get('reason')}; attempt "
            f"{int(intent.get('attempts') or 0)}); nothing is published until it is")  # fmt: skip


@contextlib.contextmanager
def fhir_lock(cfg: AdapterConfig, *, wait: bool) -> Iterator[None]:
    """``<lake>/fhir.lock``, ``flock(LOCK_EX)`` on a file opened fresh each time (flock is per open file, so two
    threads of one process exclude each other too). The kernel drops it when its process dies: no stale lock and no
    pid check. Held by a live process and ``wait`` False: :class:`RecoveryBusy`. Order: this lock first, then the
    lake's ``building``."""
    import fcntl

    cfg.lake_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(cfg.lake_dir / FHIR_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise RecoveryBusy("the FHIR store is held by another publish or recovery") from exc
        yield
    finally:
        os.close(fd)


def _ledger_types(cfg: AdapterConfig) -> set[str]:
    return {p.stem for p in (cfg.lake_dir / "fhir_ledger").glob("*.txt")}


def verify_fhir(cfg: AdapterConfig, folder: Path, *, ids: bool = False, also: Iterable[str] = ()) -> dict[str, int]:
    """Check that the FHIR store holds ``folder``: per resourceType, the store's count (``_summary=count``) is the
    number of resources in the folder's NDJSON (0 for every type the folder lacks: an empty folder is "the store
    holds none of this box's resources"); with ``ids``, the store's ids (paged ``_elements=id``) hash to the
    folder's. The types: the folder's, the ledger's (which keeps every id until a check passed) and ``also``. The
    loader is the only writer of these types (the terminology tools write terminology resources), so the store's
    count of a type is this box's. Returns the counts; :class:`FhirMismatch` names what differs (types and counts,
    no resource's content). A store that does not answer raises the transport's error: not checked is not a
    mismatch, and never clean. A count that is not a whole number of zero or more is no count (review D5): a
    mismatch, never zero. Every request asks the store not to answer from its search cache (review Q3: HAPI reuses a
    search's results for a while, so a count asked right after a put-back could be the one from before it)."""
    import httpx

    from adapter.load_fhir import delete_refs

    assert cfg.fhir_base_url is not None
    base = cfg.fhir_base_url.rstrip("/")
    want = snapshot_ids(folder)
    types = sorted(set(want) | _ledger_types(cfg) | set(also))
    counts: dict[str, int] = {}
    wrong: list[str] = []
    # one answer of the store is bounded as the loader bounds one of its transactions (listed: load_fhir.py)
    bound = inspect.signature(delete_refs).parameters["timeout"].default
    with httpx.Client(timeout=bound, headers={"Cache-Control": "no-cache"}) as client:
        for t in types:
            resp = client.get(f"{base}/{t}", params={"_summary": "count"})
            resp.raise_for_status()
            total = resp.json().get("total")
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise FhirMismatch(f"{t}: the store gave no count")
            counts[t] = total
            if counts[t] != len(want.get(t, ())):
                wrong.append(f"{t}: store {counts[t]}, night {len(want.get(t, ()))}")
            elif ids and counts[t]:
                got: list[str] = []
                url: str | None = f"{base}/{t}?_elements=id&_count=1000"
                while url:
                    page = client.get(url)
                    page.raise_for_status()
                    body = page.json()
                    got += [str(e["resource"]["id"]) for e in body.get("entry") or []]
                    url = next((ln["url"] for ln in body.get("link") or [] if ln.get("relation") == "next"), None)
                if _ids_hash(got) != _ids_hash(want.get(t, set())):
                    wrong.append(f"{t}: the store's ids are not the night's")
    if wrong:
        raise FhirMismatch("; ".join(wrong))
    return counts


def _ids_hash(ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def _still_owed(cfg: AdapterConfig, intent: dict[str, Any], why: str) -> FhirRestoreOutstanding:
    """A put-back or a check that did not end well: the intent says why (``attempts`` + 1) and stays unverified;
    returns the :class:`FhirRestoreOutstanding` to raise. A write that fails here leaves the file unverified as it
    was: owed either way. ``why``: a mismatch's or the generation ledger's words (types, counts, nights), else the
    error's type (D-668: no other error's text is kept)."""
    intent = {**intent, "verified": False, "reason": why, "attempts": int(intent.get("attempts") or 0) + 1}
    with contextlib.suppress(OSError):
        intent = _write_intent(cfg, intent)
    log.error("%s", outstanding(intent))
    return FhirRestoreOutstanding(outstanding(intent))


def settle(cfg: AdapterConfig, intent: dict[str, Any], folder: Path, *, ids: bool) -> None:
    """The store was just made to hold ``folder`` (the intent's ``want``; W1 or W2 is on disk): check it
    (:func:`verify_fhir`, with ``ids`` after a put-back), shrink the id ledger to it and finish its load in the
    generation ledger (:func:`load_fhir.finish_load`), then write ``verified`` (W3). The one way to clean, for the
    publish and the put-back alike (reviews F3, E2). Anything that fails or does not answer: still owed
    (:class:`FhirRestoreOutstanding`). The caller holds ``fhir.lock``."""
    try:
        verify_fhir(cfg, folder, ids=ids)
        finish_load(str(intent["want"]), cfg.lake_dir / "fhir_ledger", snapshot_ids(folder))
        _checkpoint("generation ledger finished")
        _write_intent(cfg, {**intent, "verified": True, "reason": "", "attempts": 0})
    except Exception as exc:
        why = str(exc) if isinstance(exc, (FhirMismatch, LedgerError)) else f"no answer ({type(exc).__name__})"
        raise _still_owed(cfg, intent, why) from exc


def restore(cfg: AdapterConfig, reason: str = "") -> None:
    """Put the FHIR store back to the night the lake serves (with none served, to nothing) when it is owed
    (:func:`derive`): every resource of the served folder again and every other id the ledger knows deleted
    (:func:`_fhir_put_back`), then :func:`settle` with ids. The target is always read from ``CURRENT``, never from
    the intent. While a lake build of the night the store was loaded with still runs (a killed publisher's build:
    review E1), ``SnapshotBuilding``, the intent untouched: the build's lock is held for the put-back, so it never
    promotes under it. ``reason``: the caller's words (the publish's). No FHIR endpoint: nothing to put back (only
    a box that never had a store publishes its lake alone: :func:`refuse_split`). The caller holds ``fhir.lock``.

    Two states are refused by name and never put back, until a person acts (the known limitations): a store
    transaction that may still commit (:data:`UNFENCED`, review H4) and a lake behind the generation ledger
    (:data:`LAKE_BEHIND`, review G2). A box without ``FHIR_STATE`` whose generation ledger has a newer night
    finished (the loader before this record finished at its last resource) takes the ledger back to the served
    night first (review H5: :func:`load_fhir.upgrade_put_back`)."""
    from lake.store import building

    if not cfg.fhir_base_url:
        return
    d = derive(cfg)
    _refuse_behind(cfg, d)
    if d.clean:
        return
    unfenced = _unfenced(cfg, d.intent, reason)
    if unfenced:
        raise _still_owed(cfg, _back_to(d, unfenced), unfenced)
    with contextlib.ExitStack() as held:
        if d.intent["want"] and d.intent["want"] != (d.served or ""):
            held.enter_context(building(cfg.lake_dir, d.intent["want"]))
            d = derive(cfg)  # CURRENT read again under the build's lock: the build may have promoted before it
        served, intent = d.served, _back_to(d, reason or d.reason)
        try:
            if d.intent.get("upgrade") and served and finished_after(served):
                upgrade_put_back(served)  # before W2: until W2 is on disk the box still reads as an upgrade
            intent = _write_intent(cfg, intent)  # W2, before the put-back's first store write
            target = snapshot_dir(cfg.lake_dir, served) if served else _empty_night(cfg)
        except LedgerError as exc:
            raise _still_owed(cfg, intent, str(exc)) from exc
        except OSError as exc:  # a full lake volume: owed, by name (review E4)
            raise _still_owed(cfg, intent, f"the put-back could not begin ({type(exc).__name__})") from exc
        if served and not target.is_dir():
            raise _still_owed(cfg, intent, "served night folder missing")
        try:
            _fhir_put_back(cfg, target)
            _checkpoint("FHIR store put back")
        except Exception as exc:
            why = str(exc) if isinstance(exc, (FhirMismatch, LedgerError)) else f"no answer ({type(exc).__name__})"
            raise _still_owed(cfg, intent, _unfenced_words(served or "nothing") if _answer_lost(exc) else why) from exc
        settle(cfg, intent, target, ids=True)
    log.warning("the FHIR store is back to %s (after the load of %s)",
                f"the served night {served}" if served else "nothing (no night is served yet)",
                intent.get("undoing") or "an earlier night")  # fmt: skip


def _back_to(d: Derived, reason: str) -> dict[str, Any]:
    """The intent of a put-back to what the lake serves (W2's content), from :func:`derive`'s answer."""
    prior, served = d.intent, d.served
    moved = (prior["want"], prior["fingerprint"]) != (served or "", d.served_fp)
    return {"want": served or "", "fingerprint": d.served_fp, "verified": False, "reason": reason,
            "attempts": int(prior.get("attempts") or 0),
            "undoing": prior["want"] if moved and prior["want"] else prior.get("undoing", "")}  # fmt: skip


def _refuse_behind(cfg: AdapterConfig, d: Derived) -> None:
    """Review G2 (detect and refuse): on a box with this version's ``FHIR_STATE``, the generation ledger has the
    FHIR store finished at a night newer than the one the lake serves. Only ``settle`` finishes a load, after the
    lake served it, so the lake was restored to another point than the trial database (with its ``FHIR_STATE`` or
    without): the store is owed by :data:`LAKE_BEHIND` and nothing is put back (the owner decides which point
    stands). A ledger that does not answer refuses too, the intent untouched. Nothing to ask without a trial
    database."""
    if d.intent.get("upgrade") or not (cfg.lake_dir / FHIR_STATE).is_file():
        return
    try:
        newer = finished_after(d.served or "")
    except LedgerError as exc:
        raise FhirRestoreOutstanding(f"fhir_restore_outstanding: {exc}; nothing is published until it answers") from exc
    if newer:
        why = (f"{LAKE_BEHIND}: the generation ledger has the FHIR store finished at {newer}, the lake serves "
               f"{d.served or 'nothing'} (the lake was restored to another point than the trial database: a known "
               "limitation, the owner decides)")  # fmt: skip
        raise _still_owed(cfg, _back_to(d, why), why)


def _unfenced_words(night: str) -> str:
    return (f"{UNFENCED}: the load of {night} ended with a store transaction out (its process killed, or its answer "
            "lost), which the FHIR store may still commit; nothing fences it (a known limitation): restart the "
            f"FHIR store, then remove {FHIR_STATE} to put the store back to the served night")  # fmt: skip


def _answer_lost(exc: BaseException) -> bool:
    """A store request that was sent and whose answer did not arrive (it timed out, the connection broke, the store
    hung up): the store may have taken it. One that was never sent (no connection) or was answered is not."""
    import httpx

    return isinstance(exc, (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError))


def _unfenced(cfg: AdapterConfig, prior: dict[str, Any], reason: str) -> str:
    """Review H4 (detect and refuse): the words of :data:`UNFENCED` when a store transaction may still be out (""
    when none is): the caller says so (a request without an answer in time), the intent already says so, or the
    intent's load was killed while it sent: W1 on disk and the night's record still says ``loading`` (the record
    says ``done`` once every transaction was answered, and ``failed`` before an in-process put-back)."""
    from adapter.pipeline import RERUN_DIR

    if reason.startswith(UNFENCED):
        return reason
    said = str(prior.get("reason") or "")
    if prior.get("verified"):
        return ""
    if said.startswith(UNFENCED):
        return said
    want = str(prior.get("want") or "")
    if said != LOADING or not want:
        return ""
    for folder in (snapshot_dir(cfg.lake_dir, want), cfg.lake_dir / RERUN_DIR / want):
        rec = read_record(folder)
        if (rec.get("snapshot"), rec.get("fingerprint")) == (want, prior.get("fingerprint")) and (
            rec.get("steps") or {}
        ).get("fhir") == LOADING:
            return _unfenced_words(want)
    return ""


def _fhir_on(cfg: AdapterConfig, load_fhir: bool) -> bool:
    return bool(load_fhir and cfg.fhir_base_url)


def _lake_on(cfg: AdapterConfig, rebuild_lake: bool) -> bool:
    return bool(rebuild_lake and (cfg.rebuild is not None or (cfg.build is not None and cfg.promote is not None)))


def refuse_split(cfg: AdapterConfig, *, load_fhir: bool, rebuild_lake: bool) -> None:
    """The FHIR store and the lake are published together or not at all (review F1): a night that would move one
    and not the other is refused before any step (:class:`NightRefused`). Only a box that never had a FHIR store
    (no ``FHIR_STATE``, no id ledger: nothing was ever sent to one) publishes its lake alone; it is derived owed
    once a night is served, so a store it gains is put forward to that night once. So no FHIR endpoint, or ``load_fhir``
    off, on a box whose store holds a night refuses until the endpoint is back; a FHIR store without a lake step is
    refused too, on a fresh box as well (review H2: a FHIR-only box is not supported, so no store is ever loaded with
    a night the lake does not serve)."""
    fhir_on, lake_on = _fhir_on(cfg, load_fhir), _lake_on(cfg, rebuild_lake)
    if fhir_on == lake_on:
        return
    intent, ledger = read_intent(cfg), _ledger_types(cfg)
    if lake_on and intent is None and not ledger:
        return
    holds = (intent or {}).get("want") or ("what its ledger lists" if intent is None and ledger else "nothing")
    raise NightRefused(
        f"the FHIR store and the lake are published together or not at all (fhir {'on' if fhir_on else 'off'}, "
        f"lake {'on' if lake_on else 'off'}; the store holds {holds})"
    )


def _empty_night(cfg: AdapterConfig) -> Path:
    """An empty folder: the FHIR store put back to it holds none of this box's resources (no night served yet; the
    loader deletes every id its ledger knows). Not named as a night, so the generation ledger is not asked. Emptied
    each time (review N6): a file left in it is never loaded as the "empty" night."""
    empty = cfg.lake_dir / "tmp" / "fhir-nothing-served"
    shutil.rmtree(empty, ignore_errors=True)
    empty.mkdir(parents=True)
    return empty


def finish_served(cfg: AdapterConfig) -> bool:
    """Second review, H2: the served night was promoted and its ``pidmap`` step did not end (the step failed, or the
    process was killed between the two). Its staged chart numbers enter the pid map now and the folder gets its
    ``passed.json``: the stores are on one night again. Called before an ingest stages or drops anything and before
    a publish. True when it finished a night; a failure is logged and left for the next call (never raised: the
    night that is running must not fail for it)."""
    from adapter.pipeline import HELD as HELD_FILE
    from adapter.pipeline import PASSED

    served = _current(cfg.lake_dir)
    folder = snapshot_dir(cfg.lake_dir, served) if served else None
    if served is None or folder is None or not folder.is_dir():
        return False
    rec = read_record(folder)
    steps = rec.get("steps") or {}
    if rec.get("snapshot") != served or steps.get("lake") != DONE or steps.get("pidmap") in ENDED:
        return False
    try:
        pm = cfg.pidmap()
        try:
            pm.commit(served)
        finally:
            pm.close()
    except Exception as exc:
        log.error("the pid map of the served night %s is still not written (%s)", served, type(exc).__name__)
        return False
    rec["steps"], rec["at"] = {**steps, "pidmap": DONE}, {**rec.get("at", {}), "pidmap": _now()}
    _write_record(folder, rec)
    if all(rec["steps"].get(s) in ENDED for s in STEPS):
        (folder / PASSED).write_text(json.dumps({"snapshot": served}) + "\n", encoding="utf-8")
        (folder / HELD_FILE).unlink(missing_ok=True)
    log.warning("the served night %s: its pid map step is finished now", served)
    return True


def _other_generation(exc: Exception) -> bool:
    """The lake's refusal of a promotion that names a generation the date no longer is (``Lake.promote_built``:
    a ValueError in process, the service's 409 over HTTP). Told by its words, which both ways carry."""
    return "built again since" in _said(exc)


def _said(exc: Exception) -> str:
    """The error's own words, with the service's answer when it is an HTTP refusal (its ``detail``): the client's
    text alone is "409 Conflict for url ...", which tells the operator nothing (review MED-2)."""
    text = str(exc)
    resp = getattr(exc, "response", None)
    if resp is not None:
        with contextlib.suppress(Exception):
            body = resp.json()
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, str) and detail:  # D-671: the service's own sentence; never another body
                text = f"{detail} ({text})"
    return text


def publish_night(
    cfg: AdapterConfig,
    snap: str,
    night_dir: Path,
    *,
    last_good: str | None = None,
    load_fhir: bool = True,
    rebuild_lake: bool = True,
    on_step: Callable[[str, dict[str, str]], None] | None = None,
) -> Published:
    """Publish the night in ``night_dir`` (see the module docstring). Never raises for a step's failure: the result
    names the step and the errors, in the words the ingest report has always used. ``on_step(step, steps)`` is
    called when a step starts and when it ends (the data-operations row, the failure's audit)."""
    out = Published(snap, night_dir)
    try:  # D-529 (review HIGH): every way to the served lake goes through here, a steward's accept included
        from zoneinfo import ZoneInfo

        from adapter.pipeline import refuse_future_night

        refuse_future_night(snap, datetime.now(ZoneInfo(cfg.tz)).date())
    except ValueError as exc:
        out.steps = {s: PENDING for s in STEPS}
        out.errors.append(f"night {snap} is not published: {exc}")
        return out
    with contextlib.ExitStack() as held:
        try:  # P-03 (reviews R1, N2): one owner of the FHIR store for the whole publish; a second is refused
            held.enter_context(fhir_lock(cfg, wait=False))
        except RecoveryBusy:
            out.steps = {s: PENDING for s in STEPS}
            out.lake_busy = True
            out.errors.append(FHIR_BUSY_ERROR)
            out.promoted = _current(cfg.lake_dir) == snap  # review D6: read from CURRENT on this way out too
            return out
        return _publish_locked(cfg, snap, night_dir, out, last_good=last_good, load_fhir=load_fhir,
                               rebuild_lake=rebuild_lake, on_step=on_step)  # fmt: skip


def _publish_locked(
    cfg: AdapterConfig,
    snap: str,
    night_dir: Path,
    out: Published,
    *,
    last_good: str | None,
    load_fhir: bool,
    rebuild_lake: bool,
    on_step: Callable[[str, dict[str, str]], None] | None,
) -> Published:
    """:func:`publish_night`'s body; the caller holds ``fhir.lock``."""
    from lake.store import SnapshotBuilding

    from adapter.dual_write import load_night
    from adapter.pipeline import BUSY as BUSY_CLASSES
    from adapter.pipeline import HELD as HELD_FILE
    from adapter.pipeline import PASSED, REFUSALS, RERUN_DIR

    final_dir = snapshot_dir(cfg.lake_dir, snap)

    def end() -> Published:
        """Every way out: what the lake serves is read from ``CURRENT`` (second review, H1; review F6)."""
        out.promoted = _current(cfg.lake_dir) == snap
        return out

    try:
        _recover_all(cfg)
    except SnapshotBuilding as exc:  # a killed publisher's lake build still runs: nothing is read or moved
        out.steps = {s: PENDING for s in STEPS}
        out.lake_busy = True
        out.errors += [f"lake rebuild failed: {exc}", BUSY_ERROR]
        return end()
    except FhirRestoreOutstanding as exc:  # review R5: before any store is touched
        out.steps = {s: PENDING for s in STEPS}
        out.errors = [str(exc)]
        out.fhir_outstanding = str(exc)
        return end()
    try:
        refuse_split(cfg, load_fhir=load_fhir, rebuild_lake=rebuild_lake)
    except NightRefused as exc:
        out.steps = {s: PENDING for s in STEPS}
        out.errors = [f"night refused: {exc}"]
        return end()
    if _current(cfg.lake_dir) != snap:
        finish_served(cfg)
    rerun = night_dir.resolve() != final_dir.resolve()
    rec = read_record(night_dir)
    mark = fingerprint(night_dir)
    if rec.get("fingerprint") != mark or rec.get("snapshot") != snap:
        rec = {"snapshot": snap, "fingerprint": mark, "steps": {}, "at": {}}
    steps: dict[str, str] = {s: str(rec["steps"].get(s) or PENDING) for s in STEPS}
    out.steps = steps
    fhir_on, lake_on = _fhir_on(cfg, load_fhir), _lake_on(cfg, rebuild_lake)
    # the lake in two steps (build, then promote last) for a night that is not served yet; a re-run of the served
    # night replaces the served file by building, so there the build is the promotion
    two_step = lake_on and not rerun and cfg.build is not None and cfg.promote is not None

    def note(step: str, state: str) -> None:
        steps[step] = state
        rec["steps"], rec["at"] = dict(steps), {**rec.get("at", {}), step: _now()}
        _write_record(out.out_dir, rec)
        if on_step is not None:
            on_step(step, dict(steps))

    def set_step(step: str, state: str) -> None:
        """The record alone (P-03: what a kill leaves), without a step event."""
        steps[step] = state
        rec["steps"] = dict(steps)
        _write_record(out.out_dir, rec)

    def todo(step: str) -> bool:
        if steps[step] in ENDED:
            return False
        if on_step is not None:
            on_step(step, dict(steps))
        return True

    def lake_error(step: str, exc: Exception) -> None:
        out.errors.append(f"lake rebuild failed: {exc}")
        kind = type(exc).__name__
        if kind in BUSY_CLASSES:  # D-462: nothing written, not the data's fault
            out.lake_busy = True
            out.errors.append(BUSY_ERROR)
            note(step, BUSY)
        elif kind in REFUSALS:  # D-271: the lake or the OMOP store refused the data: a held night
            out.held = True
            out.errors.append("night held: the lake refused the snapshot; CURRENT still names the previous snapshot")
            note(step, REFUSED)
        else:
            note(step, FAILED)

    def stale(served: str | None, step: str | None) -> None:
        out.stale = True
        out.errors.append(
            f"night {snap} is not published: a newer night ({served}) is already served, and the box never moves "
            "back in time"
        )
        if step is not None:
            note(step, STALE)

    def fhir_back(why: str) -> None:
        """The promotion did not happen: the FHIR store goes back to the night the lake serves, with none served to
        nothing (reviews MED-1, R4; :func:`restore`, which does nothing when the store is not owed). A put-back that
        fails leaves the store owed and the step ``failed``; so does a lake build of this night that still runs."""
        try:
            restore(cfg, why)
        except (FhirRestoreOutstanding, SnapshotBuilding) as exc:
            from adapter import failure

            cause = exc.__cause__ or exc
            failure.log_failure(log, "fhir-store put-back failed", cause)
            out.errors.append(f"fhir-store put-back failed: {failure.words(cause)}")  # D-668
            out.fhir_outstanding = (
                str(exc) if isinstance(exc, FhirRestoreOutstanding) else outstanding(derive(cfg).intent)
            )
            out.errors.append(out.fhir_outstanding)
            note("fhir", FAILED)
            return
        note("fhir", PENDING)

    served = _current(cfg.lake_dir)
    if lake_on and served is not None and snap < served:
        # review HIGH-1: before any step, nothing loaded; review H1: whatever its record says (a night served before
        # the newer one, asked for again, loads nothing and keeps its record as it is)
        stale(served, None if steps["lake"] in ENDED else "build" if two_step else "lake")
        return end()
    if rerun and steps["lake"] not in ENDED:
        held_by = holders(cfg.lake_dir, snap)
        if held_by:  # F-3: nothing of the served night is touched while a job reads it
            out.lake_busy = True
            out.errors += [f"lake rebuild failed: snapshot {snap} is held by {len(held_by)} running job(s)", BUSY_ERROR]
            note("lake", BUSY)
            return end()
    if todo("build"):
        if two_step:
            assert cfg.build is not None
            try:
                out.lake = cfg.build(snap, final_dir)
            except Exception as exc:  # review MED-1: the lake's verdict first; no other store was touched
                lake_error("build", exc)
                return end()
            # D-531: the generation this publish built; the promotion names it, also after a restart
            built_gen = getattr(out.lake, "generation", None)
            if built_gen:
                rec["lake_generation"] = str(built_gen)
            else:
                rec.pop("lake_generation", None)
            note("build", DONE)
        else:
            note("build", SKIPPED)
    if todo("omop"):  # T-106 (D-339): its refusal or failure never holds the night; None: the flag is off
        out.omop = load_night(cfg, snap, night_dir)
        note("omop", DONE if out.omop is not None else SKIPPED)
    touched = False  # this call loaded the FHIR store or promoted the night: only then is the end check owed (D7)
    intent: dict[str, Any] = {"want": snap, "fingerprint": mark, "verified": False, "reason": LOADING}
    if fhir_on:
        # P-03: whether this night's NDJSON is in the store is read from the intent alone (the record's ``fhir`` is
        # what it shows): a settled retry loads nothing, asks the store nothing and writes nothing (review D7)
        now = read_intent(cfg) or {}
        if now.get("verified") is True and now.get("want") == snap and now.get("fingerprint") == mark:
            if steps["fhir"] != DONE:
                note("fhir", DONE)
        else:
            from adapter import failure

            if on_step is not None:
                on_step("fhir", dict(steps))
            try:  # W1, before the store's first write; a full disk fails the step, nothing sent (reviews E4, G3)
                intent = _write_intent(cfg, intent)
                set_step("fhir", LOADING)
            except OSError as exc:
                failure.log_failure(log, "fhir-store load failed", exc)
                out.errors.append(f"fhir-store load failed: {failure.words(exc)}")  # D-668
                steps["fhir"] = FAILED
                with contextlib.suppress(OSError):  # review M1: the record too, when the volume still takes it
                    note("fhir", FAILED)
                return end()
            try:
                out.fhir_loaded, out.fhir_deleted = _sync_fhir(
                    cfg, night_dir, snapshot_dir(cfg.lake_dir, last_good) if last_good else None
                )
            except Exception as exc:  # F-2: the lake is not promoted after this
                failure.log_failure(log, "fhir-store load failed", exc)
                said = failure.words(exc)
                out.errors.append(f"fhir-store load failed: {said}")  # D-668
                note("fhir", FAILED)
                # what was loaded before the failure does not stay; a transaction without its answer may still
                # commit, so the store is not put back over it (review H4: refused by name)
                fhir_back(_unfenced_words(snap) if _answer_lost(exc) else f"load failed: {said}")
                return end()
            note("fhir", DONE)  # every transaction was answered (review H4: a kill before this is refused by name)
            _checkpoint("FHIR store loaded")
            touched = True
    elif todo("fhir"):
        note("fhir", SKIPPED)
    if todo("lake"):
        aside = cfg.lake_dir / RERUN_DIR / f"{snap}.replaced"
        if two_step:
            assert cfg.promote is not None
            mine = rec.get("lake_generation")
            try:
                moved = cfg.promote(snap, str(mine)) if mine else cfg.promote(snap)
            except Exception as exc:
                if mine and _other_generation(exc):
                    # D-531: the date was built again since this publish's build. What the date names now was not
                    # built by this publish. The build is owed again; the next run does it. Asked before "the
                    # answer was lost" (review MED-1): a rebuild by hand that promoted makes CURRENT name the
                    # night too, and that is not this publish's promotion
                    served_other = _current(cfg.lake_dir) == snap
                    out.errors.append(f"lake rebuild failed: {_said(exc)}")
                    if served_other:
                        out.errors.append(
                            f"night {snap} is served from a lake generation this publish did not build (it was "
                            "rebuilt and promoted by another rebuild); run the night again to build and serve its own"
                        )
                    rec.pop("lake_generation", None)
                    steps["build"] = PENDING
                    note("lake", FAILED)
                    if not served_other:
                        fhir_back("the lake date was built again since this publish's build")
                    return end()
                if _current(cfg.lake_dir) == snap:  # H1: the lake promoted it and its answer was lost
                    log.warning("the promotion of %s gave no answer (%s); CURRENT names it", snap, type(exc).__name__)
                    moved = True
                else:
                    lake_error("lake", exc)
                    fhir_back(f"the promotion failed ({type(exc).__name__})")
                    return end()
            if not moved:  # a newer night was promoted while this one was published
                stale(_current(cfg.lake_dir), "lake")
                fhir_back("a newer night was promoted")
                return end()
            _checkpoint("lake promoted")
            note("lake", DONE)
            touched = True
        elif lake_on:
            assert cfg.rebuild is not None
            if rerun:  # the re-run takes the served folder's place for the build; put back unless it ends well
                shutil.rmtree(aside, ignore_errors=True)
                rec["swapped_ns"] = time.time_ns()  # what a killed run leaves is told from a finished build by this
                _write_record(out.out_dir, rec)
                if final_dir.exists():
                    final_dir.rename(aside)
                    _checkpoint("re-run swap: served folder aside")  # review F5: between the two renames
                night_dir.rename(final_dir)
                out.out_dir = final_dir
                _checkpoint("re-run swapped in")

            def put_back() -> None:
                if not rerun:
                    return
                final_dir.rename(night_dir)
                if aside.exists():
                    aside.rename(final_dir)
                out.out_dir = night_dir
                _checkpoint("re-run swapped out")

            try:
                out.lake = cfg.rebuild(snap, final_dir)
            except Exception as exc:
                put_back()
                lake_error("lake", exc)
                fhir_back(f"the lake step failed ({type(exc).__name__})")
                return end()
            except BaseException:  # the process is dying mid-step: leave the served folder as it was
                put_back()
                raise
            _checkpoint("lake promoted")
            now_served = _current(cfg.lake_dir)
            if now_served is not None and now_served > snap:  # built, not promoted: a newer night is served now
                put_back()
                stale(now_served, "lake")
                fhir_back("a newer night is served")
                return end()
            note("lake", DONE)
            touched = True
        else:
            note("lake", SKIPPED)
        shutil.rmtree(aside, ignore_errors=True)
    # P-03: the store is clean only once checked against the night the lake serves now (:func:`settle`, counts after
    # the publish's own load under the lock). A served night that is not settled writes no pid map and no PASSED and
    # keeps its hold (review F4): the next recovery puts the store to it and its resume ends it
    if fhir_on and touched:
        try:
            settle(cfg, intent, final_dir, ids=False)
        except FhirRestoreOutstanding as exc:
            out.errors.append(str(exc))
            out.fhir_outstanding = str(exc)
            note("fhir", FAILED)
            return end()
    if todo("pidmap"):  # last: only a served night's chart numbers reach the reverse map (F-12)
        try:
            pm = cfg.pidmap()
            try:
                pm.commit(snap)
            finally:
                pm.close()
        except Exception as exc:
            out.errors.append(f"pid map write failed: {type(exc).__name__}")
            note("pidmap", FAILED)
            return end()
        _checkpoint("pid map committed")
        note("pidmap", DONE)
    # D-271: the only NDJSON a later delta night may merge over; written last, after every step
    (out.out_dir / PASSED).write_text(json.dumps({"snapshot": snap}) + "\n", encoding="utf-8")
    (out.out_dir / HELD_FILE).unlink(missing_ok=True)
    _checkpoint(PASSED)
    return end()


def published(cfg: AdapterConfig, snap: str) -> bool:
    """Whether the night ``snap`` has been published as it stands on disk: its folder says it passed and its
    record says every step ended (review HIGH-2: a repeated accept is answered "done", not "no such held night")."""
    from adapter.pipeline import HELD as HELD_FILE
    from adapter.pipeline import PASSED

    folder = snapshot_dir(cfg.lake_dir, snap)
    if not (folder / PASSED).is_file() or (folder / HELD_FILE).exists():
        return False
    steps = read_record(folder).get("steps") or {}
    return bool(steps) and all(steps.get(s) in ENDED for s in STEPS)


def held_folder(cfg: AdapterConfig, snap: str) -> Path:
    """The folder of the held night ``snap``: the re-run beside the served folder when there is one, else the
    night's own folder. :class:`NothingToPublish` when neither says it is held."""
    from adapter.pipeline import HELD as HELD_FILE
    from adapter.pipeline import RERUN_DIR

    for folder in (cfg.lake_dir / RERUN_DIR / snap, snapshot_dir(cfg.lake_dir, snap)):
        if (folder / HELD_FILE).is_file():
            return folder
    raise NothingToPublish(f"no held night {snap} on this box (its folder has no {HELD_FILE})")


def publish_held(
    cfg: AdapterConfig, snap: str, *, on_step: Callable[[str, dict[str, str]], None] | None = None
) -> Published:
    """The steward's accept (T-723, D-489): publish the held night's folder as it stands, with the same function a
    night that passed the gate goes through. The gate's verdict is what the steward overrode; the lake's own
    refusal of the data (D-271) still stands."""
    from adapter.pipeline import merge_base

    folder = held_folder(cfg, snap)
    try:  # 10B-23 (D-1254): whether the held night read whole, from its own report, before the publish moves it
        since = json.loads((folder / "ingest_report.json").read_text(encoding="utf-8")).get("since")
        full: bool | None = not since
    except (OSError, ValueError, AttributeError):
        full = None  # not known: the record is not moved
    out = publish_night(cfg, snap, folder, last_good=merge_base(cfg.lake_dir, snap), on_step=on_step)
    if out.ok and out.promoted and full is not None:  # an accepted night that is served completed
        from adapter import full_nights

        full_nights.completed(cfg.lake_dir, snap, full=full)
    return out


__all__ = [
    "RECORD",
    "STEPS",
    "Derived",
    "FhirMismatch",
    "FhirRestoreOutstanding",
    "NightRefused",
    "NothingToPublish",
    "Published",
    "RecoveryBusy",
    "derive",
    "fingerprint",
    "finish_served",
    "holders",
    "publish_held",
    "publish_night",
    "published",
    "read_intent",
    "read_record",
    "recover",
    "recover_all",
    "refuse_split",
    "restore",
    "settle",
    "verify_fhir",
]
