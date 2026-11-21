"""The answer store (D-1360; plan 10 card 10A-4, commitment C-5): one answer per patient, criterion and ruleset version.

Every screening run (SCREEN, and MICROBATCH's re-checks and screens) writes the answer it gave each patient on each
criterion: the status, the reason code, the rung (the cascade's stage, ``S0`` to ``S5``; none on the v1 path), the
basis (records, a pair, a single model, a person), the verified quote and its date, the flip date (D-1263: the
cascade computes it for a criterion written in criterion model v3; none for a v1 criterion and on the v1 path), and
the index date, snapshot and job that gave it. The services read it
(CASE shows the last screening's answer beside its own; MICROBATCH tells what changed for a patient listed again)
and none of them re-implements matching.

* **What is stored** is the answer as the run gave it, the same row the candidate list carries, never a new
  decision: the status with its basis and ``final`` (D-476, D-478), so a reader shows it through
  :func:`shown` (``tb_common.verdict_word.shown_of``): a single model's "not met", or one given while notes could not
  exclude, is an open point, never "not met".
* **The latest answer stands.** One row per (patient, ruleset, version, criterion); a run of a later or the same
  index date replaces it, an older one (a re-run of a past day) never does. An answer nobody gave (not evaluated,
  the model down: D-642) never replaces a "met" or "not met" stored before; it is stored only where none is.
* **The rung** is the cascade's stage; the v1 path (MICROBATCH's re-check) has none, and its answer stores none.
* **Opt-out** (D-513): the register is read before every write and every read; a patient on it is neither written
  nor read; a register that does not answer means no write and no read (D-127: fail closed). After a write the
  register is read again and the rows of a patient who opted out meanwhile are deleted; the opt-out worker deletes
  the rest (``datacore.optout_worker.OWED_TABLES``).
* **Retention:** a row stays with the snapshot whose notes its quote came from; at each write the rows of a snapshot
  the site's retention (D-452) no longer keeps are deleted, by the judged-pair store's rule (``kept_snapshots``).
* **A fault of the store is never the run's:** the list is sent; the store's failure is logged and the run's
  record says how many answers were stored (none).

Class D3: in the orchestrator's trial database, never exported, never in a support bundle.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from tb_common.reasons import Reason
from tb_common.verdict_word import shown_of

from orchestrator.judged_store import kept_snapshots

log = logging.getLogger(__name__)

#: an answer nobody gave (MICROBATCH's ``NOT_ASKED``, D-642)
NOT_ASKED = (Reason.NOT_EVALUATED.value, Reason.MODEL_DOWN.value)


def shown(row: Mapping[str, Any]) -> tuple[str, str | None]:
    """``(word, reason)`` a page shows for a stored answer: :func:`tb_common.verdict_word.shown_of` over its status,
    basis and ``final``."""
    return shown_of({"verdict": row.get("status"), "basis": row.get("basis"), "final": row.get("final")})


def asked(row: tuple[Any, ...]) -> bool:
    """Whether a row of :func:`rows_of` is an answer somebody gave (not an unknown nobody was asked for)."""
    return not (row[4] == "unknown" and row[5] in NOT_ASKED)


def rows_of(
    ruleset: str, version: str, results: Mapping[str, Any], index_date: date, snapshot: str, job_id: str, at: str
) -> list[tuple[Any, ...]]:
    """The store's rows for a run's results (``PatientVerdicts`` by pseudonym), one per patient and criterion, in
    the order of ``orchestrator.db.ANSWER_COLUMNS``."""
    out: list[tuple[Any, ...]] = []
    for pid, pv in results.items():
        rungs = getattr(pv, "rungs", None) or {}
        flips = getattr(pv, "flips", None) or {}  # D-1263: criterion model v3 computes it; none for a v1 criterion
        for v in pv.verdicts:
            ev = v.evidence
            out.append(
                (
                    pid, ruleset, version, v.id, v.verdict,
                    ev.reason if ev is not None else None,
                    rungs.get(v.id),
                    v.basis,
                    v.final,
                    ev.quote if ev is not None else None,
                    ev.quote_date if ev is not None else None,
                    flips.get(v.id),
                    index_date.isoformat(), snapshot, job_id, at,
                )
            )  # fmt: skip
    return out


def _retention(ctx: Any) -> tuple[int, int]:
    ret = getattr(getattr(getattr(ctx, "cfg", None), "settings", None), "retention", None)
    nightly = getattr(ret, "nightly_snapshots", None)
    months = getattr(ret, "month_end_snapshots_months", None)
    return int(nightly if nightly is not None else 3), int(months if months is not None else 36)


def _now(ctx: Any) -> str:
    clock = getattr(getattr(ctx, "orch", None), "_now", None)
    return (clock() if callable(clock) else datetime.now(UTC)).isoformat()


def record(ctx: Any, ruleset: str, version: str, results: Mapping[str, Any], index_date: date, snapshot: str) -> int:
    """Store a run's answers (see the module's rules). The number of answers sent to the store (an older run's are
    sent and not taken); 0 when nothing was to be stored, the register did not answer or the store failed. Never
    raises: a fault of the store is never the run's."""
    if not results:
        return 0
    try:
        db = ctx.orch.db
        gone = frozenset(ctx.decision.register_now())
    except Exception:
        log.warning("answer store: the opt-out register did not answer; nothing stored")
        return 0
    try:
        kept = {p: pv for p, pv in results.items() if p not in gone}
        rows = rows_of(ruleset, version, kept, index_date, snapshot, str(ctx.job.job_id), _now(ctx))
        db.answer_store_put([r for r in rows if asked(r)], [r for r in rows if not asked(r)])
    except Exception:
        log.warning("answer store: the write failed; the run's answers are not stored")
        return 0
    try:
        late = sorted(frozenset(ctx.decision.register_now()) & set(kept))
        if late:  # opted out while the run wrote: their rows go now
            db.answer_store_drop_pids(late)
            rows = [r for r in rows if r[0] not in set(late)]
    except Exception:  # the register did not answer: the opt-out worker deletes them at its next tick (every tick
        # clears every patient on the register)
        log.warning("answer store: the opt-out check after the write failed")
    try:
        retain(db, snapshot, ctx.today(), *_retention(ctx))
    except Exception:
        log.warning("answer store: the retention sweep failed; it runs again at the next write")
    return len(rows)


def retain(db: Any, snapshot: str, today: date, nightly: int, months: int) -> int:
    """Delete the answers of every snapshot the site's retention no longer keeps."""
    try:
        snaps = db.answer_store_snapshots()
        if not snaps:
            return 0
        keep = kept_snapshots(snaps, snapshot, today, nightly, months)
        return int(db.answer_store_drop_snapshots(sorted(keep))) if set(snaps) - keep else 0
    except Exception:
        log.warning("answer store: the retention sweep failed; it runs again at the next write")
        return 0


def last(ctx: Any, pid: str | None, ruleset: str, version: str) -> dict[str, dict[str, Any]]:
    """The stored answers of one patient on one ruleset version, by criterion id: nothing for no patient, a patient
    on the register, a register that does not answer, or a store that fails."""
    if not pid:
        return {}
    try:
        if pid in frozenset(ctx.decision.register_now()):
            return {}
        return {r["criterion"]: r for r in ctx.orch.db.answer_store_of(pid, ruleset, version)}
    except Exception:
        log.warning("answer store: the read failed")
        return {}


def last_of(ctx: Any, pids: Iterable[str], ruleset: str, version: str) -> dict[str, dict[str, dict[str, Any]]]:
    """:func:`last` for several patients, by pseudonym (the register read once)."""
    try:
        gone = frozenset(ctx.decision.register_now())
    except Exception:
        log.warning("answer store: the opt-out register did not answer; nothing read")
        return {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for pid in pids:
        if pid in gone:
            continue
        try:
            out[pid] = {r["criterion"]: r for r in ctx.orch.db.answer_store_of(pid, ruleset, version)}
        except Exception:
            log.warning("answer store: the read failed")
            return {}
    return out


__all__ = ["NOT_ASKED", "asked", "last", "last_of", "record", "retain", "rows_of", "shown"]
