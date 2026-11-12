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

**The stores stay at one night.** The FHIR store is the only store written before the promotion. When the
promotion does not happen (the FHIR load failed part-way, the lake's one call did not end well, a newer night was
promoted meanwhile), the FHIR store is put back to the night the lake serves (``fhir_back``); if that fails too,
the publish says so and its ``fhir`` step stays ``failed``.

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

import hashlib
import json
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tb_contracts import RebuildResult

from adapter.load_fhir import sync_snapshot
from adapter.ndjson import snapshot_dir

if TYPE_CHECKING:
    from adapter.pipeline import AdapterConfig

log = logging.getLogger("adapter")

RECORD = "publish.json"  # in the night's folder: the publish's step record (no patient data)
STEPS = ("build", "omop", "fhir", "lake", "pidmap")
DONE, SKIPPED, FAILED, BUSY, REFUSED, PENDING = "done", "skipped", "failed", "busy", "refused", "pending"
STALE = "stale"  # a newer night is served: this one is not published (the box never moves back in time)
ENDED = (DONE, SKIPPED)
BUSY_ERROR = "lake busy: the night is run again once the lake is free (nothing was written)"


class NothingToPublish(RuntimeError):
    """No held night of that date is on the box."""


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
    tmp = folder / f"{RECORD}.tmp"
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(folder / RECORD)


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
    return sync_snapshot(cfg.fhir_base_url, folder, cfg.lake_dir / "fhir_ledger", previous)


def recover(cfg: AdapterConfig, snap: str) -> str:
    """Undo what a re-run of the served night ``snap`` left on disk when its process was killed inside the lake
    step (review MED-2): the re-run's folder in the served folder's place and the served one aside
    (``ndjson-rerun/<snap>.replaced``; a publish that ends removes it). Returns what was done:

    * ``""``: nothing was left;
    * ``"forward"``: the lake had finished the build (the served file is newer than the swap): the re-run is what
      is served, so the folder stays and only the leftover goes;
    * ``"back"``: the served folder is put back, the re-run goes back beside it (unless a later re-run is already
      there: then the killed one is dropped), and the FHIR store, which the killed run had loaded with the re-run,
      is put back to the served folder."""
    from adapter.pipeline import RERUN_DIR

    aside = cfg.lake_dir / RERUN_DIR / f"{snap}.replaced"
    if not aside.is_dir():
        return ""
    final_dir = snapshot_dir(cfg.lake_dir, snap)
    rerun_dir = cfg.lake_dir / RERUN_DIR / snap
    rec = read_record(final_dir) if final_dir.is_dir() else {}
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
    aside.rename(final_dir)
    log.warning("publish of %s was interrupted in its lake step: the served folder is put back", snap)
    if steps.get("fhir") == DONE and cfg.fhir_base_url:
        try:
            _sync_fhir(cfg, final_dir, None)
        except Exception as exc:
            log.error("the FHIR store could not be put back to %s (%s)", snap, type(exc).__name__)
        if rerun_dir.is_dir() and read_record(rerun_dir):
            again = read_record(rerun_dir)
            again["steps"] = {**again.get("steps", {}), "fhir": PENDING}
            _write_record(rerun_dir, again)
    return "back"


def recover_all(cfg: AdapterConfig) -> list[str]:
    """:func:`recover` for every night a killed re-run left swapped. Called before a publish and before an ingest
    reads the lake's folders."""
    from adapter.pipeline import RERUN_DIR

    home = cfg.lake_dir / RERUN_DIR
    if not home.is_dir():
        return []
    return [p.name[: -len(".replaced")] for p in sorted(home.glob("*.replaced")) if recover(cfg, p.name[:-9])]


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
    from adapter.dual_write import load_night
    from adapter.pipeline import BUSY as BUSY_CLASSES
    from adapter.pipeline import HELD as HELD_FILE
    from adapter.pipeline import PASSED, REFUSALS, RERUN_DIR

    recover_all(cfg)
    final_dir = snapshot_dir(cfg.lake_dir, snap)
    rerun = night_dir.resolve() != final_dir.resolve()
    out = Published(snap, night_dir)
    rec = read_record(night_dir)
    mark = fingerprint(night_dir)
    if rec.get("fingerprint") != mark or rec.get("snapshot") != snap:
        rec = {"snapshot": snap, "fingerprint": mark, "steps": {}, "at": {}}
    steps: dict[str, str] = {s: str(rec["steps"].get(s) or PENDING) for s in STEPS}
    out.steps = steps
    fhir_on = bool(load_fhir and cfg.fhir_base_url)
    lake_on = bool(rebuild_lake and (cfg.rebuild is not None or (cfg.build is not None and cfg.promote is not None)))
    # the lake in two steps (build, then promote last) for a night that is not served yet; a re-run of the served
    # night replaces the served file by building, so there the build is the promotion
    two_step = lake_on and not rerun and cfg.build is not None and cfg.promote is not None

    def note(step: str, state: str) -> None:
        steps[step] = state
        rec["steps"], rec["at"] = dict(steps), {**rec.get("at", {}), step: _now()}
        _write_record(out.out_dir, rec)
        if on_step is not None:
            on_step(step, dict(steps))

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

    def stale(served: str | None, step: str) -> None:
        out.stale = True
        out.errors.append(
            f"night {snap} is not published: a newer night ({served}) is already served, and the box never moves "
            "back in time"
        )
        note(step, STALE)

    def fhir_back() -> None:
        """The promotion did not happen: the FHIR store goes back to the night the lake serves (review MED-1)."""
        if not fhir_on or steps["fhir"] not in (DONE, FAILED):
            return
        served = _current(cfg.lake_dir)
        folder = snapshot_dir(cfg.lake_dir, served) if served else None
        if folder is None or not folder.is_dir():
            return  # no night is served yet: there is nothing to go back to
        try:
            _sync_fhir(cfg, folder, None)
        except Exception as exc:
            out.errors.append(f"fhir-store put-back failed: {exc}")
            note("fhir", FAILED)
            return
        if steps["fhir"] == DONE:
            note("fhir", PENDING)

    served = _current(cfg.lake_dir)
    if lake_on and served is not None and snap < served and steps["lake"] not in ENDED:
        stale(served, "build" if two_step else "lake")  # review HIGH-1: before any step, nothing loaded
        return out
    if rerun and steps["lake"] not in ENDED:
        held_by = holders(cfg.lake_dir, snap)
        if held_by:  # F-3: nothing of the served night is touched while a job reads it
            out.lake_busy = True
            out.errors += [f"lake rebuild failed: snapshot {snap} is held by {len(held_by)} running job(s)", BUSY_ERROR]
            note("lake", BUSY)
            return out
    if todo("build"):
        if two_step:
            assert cfg.build is not None
            try:
                out.lake = cfg.build(snap, final_dir)
            except Exception as exc:  # review MED-1: the lake's verdict first; no other store was touched
                lake_error("build", exc)
                return out
            note("build", DONE)
        else:
            note("build", SKIPPED)
    if todo("omop"):  # T-106 (D-339): its refusal or failure never holds the night; None: the flag is off
        out.omop = load_night(cfg, snap, night_dir)
        note("omop", DONE if out.omop is not None else SKIPPED)
    if todo("fhir"):
        if fhir_on:
            try:
                out.fhir_loaded, out.fhir_deleted = _sync_fhir(
                    cfg, night_dir, snapshot_dir(cfg.lake_dir, last_good) if last_good else None
                )
            except Exception as exc:  # F-2: the lake is not promoted after this
                out.errors.append(f"fhir-store load failed: {exc}")
                note("fhir", FAILED)
                fhir_back()  # what was loaded before the failure does not stay
                return out
            note("fhir", DONE)
        else:
            note("fhir", SKIPPED)
    if todo("lake"):
        aside = cfg.lake_dir / RERUN_DIR / f"{snap}.replaced"
        if two_step:
            assert cfg.promote is not None
            try:
                moved = cfg.promote(snap)
            except Exception as exc:
                lake_error("lake", exc)
                fhir_back()
                return out
            if not moved:  # a newer night was promoted while this one was published
                stale(_current(cfg.lake_dir), "lake")
                fhir_back()
                return out
            note("lake", DONE)
        elif lake_on:
            assert cfg.rebuild is not None
            if rerun:  # the re-run takes the served folder's place for the build; put back unless it ends well
                shutil.rmtree(aside, ignore_errors=True)
                rec["swapped_ns"] = time.time_ns()  # what a killed run leaves is told from a finished build by this
                _write_record(out.out_dir, rec)
                if final_dir.exists():
                    final_dir.rename(aside)
                night_dir.rename(final_dir)
                out.out_dir = final_dir

            def put_back() -> None:
                if not rerun:
                    return
                final_dir.rename(night_dir)
                if aside.exists():
                    aside.rename(final_dir)
                out.out_dir = night_dir

            try:
                out.lake = cfg.rebuild(snap, final_dir)
            except Exception as exc:
                put_back()
                lake_error("lake", exc)
                fhir_back()
                return out
            except BaseException:  # the process is dying mid-step: leave the served folder as it was
                put_back()
                raise
            if _current(cfg.lake_dir) != snap:  # built, not promoted: a newer night came to be served meanwhile
                put_back()
                stale(_current(cfg.lake_dir), "lake")
                fhir_back()
                return out
            note("lake", DONE)
        else:
            note("lake", SKIPPED)
        shutil.rmtree(aside, ignore_errors=True)
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
            return out
        note("pidmap", DONE)
    out.promoted = _current(cfg.lake_dir) == snap
    # D-271: the only NDJSON a later delta night may merge over; written last, after every step
    (out.out_dir / PASSED).write_text(json.dumps({"snapshot": snap}) + "\n", encoding="utf-8")
    (out.out_dir / HELD_FILE).unlink(missing_ok=True)
    return out


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

    return publish_night(cfg, snap, held_folder(cfg, snap), last_good=merge_base(cfg.lake_dir, snap), on_step=on_step)


__all__ = [
    "RECORD",
    "STEPS",
    "NothingToPublish",
    "Published",
    "fingerprint",
    "holders",
    "publish_held",
    "publish_night",
    "published",
    "read_record",
    "recover",
    "recover_all",
]
