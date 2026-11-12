"""``publish(night)``: one resumable function (T-723, D-489; lifecycle review F-2, F-3, F-12, proposal G-2).

A night that may be published (it passed the gate, or a steward accepted it) is published by :func:`publish_night`,
in this order, each step only when the one before it is done:

1. ``pidmap``: the night's staged chart numbers enter the pid map (they wait in ``pidmap.pending`` until here, so a
   held night's never reach the reverse map);
2. ``omop``: the dual write into OMOP, where it is on;
3. ``fhir``: the FHIR store;
4. ``lake``: the lake's build and promotion. The lake promotes at its swap, so the promotion is the last thing that
   happens: a step that fails before it leaves ``CURRENT`` on the previous snapshot.

Then, and only then, ``passed.json`` is written.

**Resumable.** Each step's state is kept in ``publish.json`` in the night's folder, with a fingerprint of the
folder's NDJSON. A second call on the same content skips the steps that are done and starts at the first that is
not. Other content (the night was run again from a changed source) starts from the first step.

**A re-run of the served night** is written beside the served folder (``ndjson-rerun/<night>``, D-271). While a job
holds the snapshot the publish is refused as "lake busy" before any step: nothing is loaded and nothing a job reads
is touched. Without a hold, the re-run's folder takes the served folder's place only for the lake step and is put
back if that step does not end well, so the served folder always holds what the served file was built from.

:func:`publish_held` publishes a held night's folder as it stands: the steward's accept (``POST /publish``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
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
STEPS = ("pidmap", "omop", "fhir", "lake")
DONE, SKIPPED, FAILED, BUSY, REFUSED, PENDING = "done", "skipped", "failed", "busy", "refused", "pending"
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

    final_dir = snapshot_dir(cfg.lake_dir, snap)
    rerun = night_dir.resolve() != final_dir.resolve()
    out = Published(snap, night_dir)
    rec = read_record(night_dir)
    mark = fingerprint(night_dir)
    if rec.get("fingerprint") != mark or rec.get("snapshot") != snap:
        rec = {"snapshot": snap, "fingerprint": mark, "steps": {}, "at": {}}
    steps: dict[str, str] = {s: str(rec["steps"].get(s) or PENDING) for s in STEPS}
    out.steps = steps

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

    if rerun and steps["lake"] not in ENDED:
        held_by = holders(cfg.lake_dir, snap)
        if held_by:  # F-3: nothing of the served night is touched while a job reads it
            out.lake_busy = True
            out.errors += [f"lake rebuild failed: snapshot {snap} is held by {len(held_by)} running job(s)", BUSY_ERROR]
            note("lake", BUSY)
            return out
    if todo("pidmap"):
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
    if todo("omop"):  # T-106 (D-339): its refusal or failure never holds the night; None: the flag is off
        out.omop = load_night(cfg, snap, night_dir)
        note("omop", DONE if out.omop is not None else SKIPPED)
    if todo("fhir"):
        if load_fhir and cfg.fhir_base_url:
            try:
                out.fhir_loaded, out.fhir_deleted = sync_snapshot(
                    cfg.fhir_base_url,
                    night_dir,
                    cfg.lake_dir / "fhir_ledger",
                    snapshot_dir(cfg.lake_dir, last_good) if last_good else None,
                )
            except Exception as exc:  # F-2: the lake is not built and not promoted after this
                out.errors.append(f"fhir-store load failed: {exc}")
                note("fhir", FAILED)
                return out
            note("fhir", DONE)
        else:
            note("fhir", SKIPPED)
    if todo("lake"):
        aside = cfg.lake_dir / RERUN_DIR / f"{snap}.replaced"
        if rerun:  # the re-run takes the served folder's place for the build; put back unless the build ends well
            shutil.rmtree(aside, ignore_errors=True)
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

        if rebuild_lake and cfg.rebuild is not None:
            try:
                out.lake = cfg.rebuild(snap, final_dir)
            except Exception as exc:
                put_back()
                out.errors.append(f"lake rebuild failed: {exc}")
                kind = type(exc).__name__
                if kind in BUSY_CLASSES:  # D-462: nothing written, not the data's fault
                    out.lake_busy = True
                    out.errors.append(BUSY_ERROR)
                    note("lake", BUSY)
                elif kind in REFUSALS:  # D-271: the lake or the OMOP store refused the data: a held night
                    out.held = True
                    out.errors.append(
                        "night held: the lake refused the snapshot; CURRENT still names the previous snapshot"
                    )
                    note("lake", REFUSED)
                else:
                    note("lake", FAILED)
                return out
            except BaseException:  # the process is dying mid-step: leave the served folder as it was
                put_back()
                raise
            note("lake", DONE)
        else:
            note("lake", SKIPPED)
        shutil.rmtree(aside, ignore_errors=True)
    out.promoted = _current(cfg.lake_dir) == snap
    # D-271: the only NDJSON a later delta night may merge over; written last, after every step
    (out.out_dir / PASSED).write_text(json.dumps({"snapshot": snap}) + "\n", encoding="utf-8")
    (out.out_dir / HELD_FILE).unlink(missing_ok=True)
    return out


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
    "read_record",
]
