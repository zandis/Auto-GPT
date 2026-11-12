"""Which generation each derived artefact is built from (T-725, D-491; lifecycle review F-4, proposal G-4).

One row per artefact (``tb_common.generation.ARTEFACTS``: the FHIR store's night, the derived rows, the twins, the
vectors) in ``dataops.built``: the generation it is built from, ``building`` or ``finished``, and when. No patient
data.

* :meth:`Built.begin` records the start of a build and refuses a generation older than the one the artefact holds
  (:class:`tb_common.generation.OlderGeneration`): an older night's follow-up steps never overwrite a newer state.
* :meth:`Built.finish` marks it finished only while the row still names that generation.
* :meth:`Built.readable` is the one answer to "may a job pinned to generation G read this artefact".
* :func:`guarded` wraps a builder: begin, run, finish; a refused build does not run.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tb_common.db import ENV
from tb_common.generation import ARTEFACTS, BUILDING, FINISHED, Generation, OlderGeneration, Verdict, verdict

from datacore.dataops import DataOps

log = logging.getLogger("datacore.generations")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Built:
    """The ledger, in schema ``dataops`` of the trial database (``TB_DB_URL`` when ``url`` is None)."""

    def __init__(self, url: str | None = None) -> None:
        self._ops = DataOps(url)  # the schema's one owner opens and migrates it
        self._db = self._ops.db

    def close(self) -> None:
        self._ops.close()

    def __enter__(self) -> Built:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _check(artefact: str) -> None:
        if artefact not in ARTEFACTS:
            raise ValueError(f"unknown artefact {artefact!r}: one of {', '.join(ARTEFACTS)}")

    def state(self, artefact: str) -> tuple[Generation, str] | None:
        """``(generation, building | finished)`` of ``artefact``, or None when it was never built."""
        self._check(artefact)
        row = self._db.fetchone("SELECT snapshot, seq, state FROM built WHERE artefact = ?", (artefact,))
        return (Generation(str(row[0]), int(row[1])), str(row[2])) if row else None

    def begin(self, artefact: str, generation: Generation | str) -> Generation:
        """A build of ``artefact`` from ``generation`` starts. Refused (:class:`OlderGeneration`, nothing written)
        when the artefact holds a newer generation, whatever its state; the same generation again is a retry."""
        self._check(artefact)
        gen = generation if isinstance(generation, Generation) else Generation.parse(generation)
        with self._db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"dataops.built:{artefact}",))
            row = tx.fetchone("SELECT snapshot, seq FROM built WHERE artefact = ?", (artefact,))
            if row is not None:
                holds = Generation(str(row[0]), int(row[1]))
                if gen < holds:
                    raise OlderGeneration(artefact, gen, holds)
            tx.execute(
                "INSERT INTO built (artefact, snapshot, seq, state, started_at, finished_at) VALUES (?,?,?,?,?,NULL) "
                "ON CONFLICT (artefact) DO UPDATE SET snapshot = excluded.snapshot, seq = excluded.seq, "
                "state = excluded.state, started_at = excluded.started_at, finished_at = NULL",
                (artefact, gen.snapshot, gen.seq, BUILDING, _now()),
            )
        return gen

    def finish(self, artefact: str, generation: Generation | str) -> bool:
        """The build from ``generation`` ended well. True when the artefact is now ``finished`` from it; False when
        a newer build overtook it meanwhile (nothing changes: that build's own finish counts)."""
        self._check(artefact)
        gen = generation if isinstance(generation, Generation) else Generation.parse(generation)
        with self._db.transaction() as tx:
            n = tx.execute(
                "UPDATE built SET state = ?, finished_at = ? WHERE artefact = ? AND snapshot = ? AND seq = ?",
                (FINISHED, _now(), artefact, gen.snapshot, gen.seq),
            )
        return bool(n)

    def readable(self, artefact: str, pinned: Generation | str) -> Verdict:
        """May a job pinned to ``pinned`` read ``artefact``? Only when it is finished and built from exactly that
        generation (:func:`tb_common.generation.verdict`)."""
        gen = pinned if isinstance(pinned, Generation) else Generation.parse(pinned)
        got = self.state(artefact)
        return verdict(artefact, gen, got[0] if got else None, got[1] if got else None)

    def readable_all(self, pinned: Generation | str) -> dict[str, Verdict]:
        return {a: self.readable(a, pinned) for a in ARTEFACTS}


def guarded[T](artefact: str, generation: Generation | str, build: Callable[[], T], url: str | None = None) -> T | None:
    """Run ``build`` as the build of ``artefact`` from ``generation``: recorded before it starts and when it ends
    well. A generation older than the artefact's is refused: ``build`` does not run and None is returned (logged).
    Without a trial database there is no ledger and the build runs as before. ``build``'s own error propagates and
    leaves the artefact ``building`` (never ``finished``)."""
    if not (url or os.environ.get(ENV)):
        return build()
    with Built(url) as ledger:
        try:
            gen = ledger.begin(artefact, generation)
        except OlderGeneration as exc:
            log.warning("%s", exc)
            return None
        out = build()
        ledger.finish(artefact, gen)
        return out


def generation_of(lake: Any, snapshot: str) -> str:
    """The lake's generation of ``snapshot`` where the lake has generations (T-724), else the date itself."""
    ask = getattr(lake, "generation", None)
    if ask is not None:
        try:
            got = ask(snapshot)
        except Exception:  # a lake that cannot say: the date
            got = None
        if isinstance(got, str) and got:
            return got
    return snapshot


__all__ = ["Built", "generation_of", "guarded"]
