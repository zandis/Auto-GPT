"""Which generation each derived artefact is built from (T-725, D-491; lifecycle review F-4, proposal G-4).

One row per artefact (``tb_common.generation.ARTEFACTS``: the FHIR store's night, the derived rows, the twins, the
vectors) in ``dataops.built``: the generation it is built from, ``building`` or ``finished``, and when. No patient
data.

* :meth:`Built.begin` records the start of a build and refuses a generation older than the one the artefact holds
  (:class:`tb_common.generation.OlderGeneration`): an older night's follow-up steps never overwrite a newer state.
* :meth:`Built.finish` marks it finished only while the row still names that generation, with what the build made
  (``ref``: the derive batch's run id), so a reader takes that and no other.
* :meth:`Built.readable` is the one answer to "may a job pinned to generation G read this artefact".
* :func:`guarded` wraps a builder: begin, run, finish; a refused build does not run. **Builds of one artefact are
  serial from begin to finish** (:meth:`Built.building`, a session lock in the database): an older build that is
  still writing when a newer one arrives ends first, and the newer one then builds over it; the same generation
  asked for twice is built twice, one after the other. A build whose finish changes nothing (a writer outside
  this lock recorded a newer generation meanwhile) is a failed build: :class:`Overtaken`.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from tb_common.db import ENV
from tb_common.generation import ARTEFACTS, BUILDING, FINISHED, Generation, OlderGeneration, Verdict, verdict

from datacore.dataops import DataOps

log = logging.getLogger("datacore.generations")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Overtaken(RuntimeError):
    """The build ended, and the artefact no longer names its generation: it does not count as finished."""


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

    @contextlib.contextmanager
    def building(self, artefact: str) -> Iterator[None]:
        """One build of ``artefact`` at a time, in every process: a session lock on this ledger's own connection,
        held from before ``begin`` to after ``finish`` and waited for as long as the build before it runs (never
        timed: OD-10). A connection that is lost gives the lock up with it."""
        self._check(artefact)
        key = f"dataops.built.build:{artefact}"
        self._db.fetchone("SELECT pg_advisory_lock(hashtext(?))", (key,))
        try:
            yield
        finally:
            with contextlib.suppress(Exception):  # a lost connection has given it up already
                self._db.fetchone("SELECT pg_advisory_unlock(hashtext(?))", (key,))

    def ref(self, artefact: str) -> str:
        """What the artefact's last finished build made (``""``: not said, or not finished)."""
        self._check(artefact)
        row = self._db.fetchone("SELECT ref FROM built WHERE artefact = ? AND state = ?", (artefact, FINISHED))
        return str(row[0]) if row else ""

    def state(self, artefact: str) -> tuple[Generation, str] | None:
        """``(generation, building | finished)`` of ``artefact``, or None when it was never built."""
        self._check(artefact)
        row = self._db.fetchone("SELECT snapshot, seq, state FROM built WHERE artefact = ?", (artefact,))
        return (Generation(str(row[0]), int(row[1])), str(row[2])) if row else None

    def begin(self, artefact: str, generation: Generation | str, back: bool = False) -> Generation:
        """A build of ``artefact`` from ``generation`` starts. Refused (:class:`OlderGeneration`, nothing written)
        when the artefact holds a newer generation, whatever its state; the same generation again is a retry.

        ``back``: a put-back. The build of the newer generation did not end (its row is still ``building``) and the
        store is taken back to the generation that is served (T-723's FHIR put-back after a load that broke, D-489).
        Allowed only over a build that never finished: a finished newer generation is never gone back from."""
        self._check(artefact)
        gen = generation if isinstance(generation, Generation) else Generation.parse(generation)
        with self._db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"dataops.built:{artefact}",))
            row = tx.fetchone("SELECT snapshot, seq, state FROM built WHERE artefact = ?", (artefact,))
            if row is not None:
                holds = Generation(str(row[0]), int(row[1]))
                if gen < holds and not (back and str(row[2]) == BUILDING):
                    raise OlderGeneration(artefact, gen, holds)
            tx.execute(
                "INSERT INTO built (artefact, snapshot, seq, state, started_at, finished_at) VALUES (?,?,?,?,?,NULL) "
                "ON CONFLICT (artefact) DO UPDATE SET snapshot = excluded.snapshot, seq = excluded.seq, "
                "state = excluded.state, started_at = excluded.started_at, finished_at = NULL, ref = ''",
                (artefact, gen.snapshot, gen.seq, BUILDING, _now()),
            )
        return gen

    def finish(self, artefact: str, generation: Generation | str, ref: str = "") -> bool:
        """The build from ``generation`` ended well (``ref``: what it made, in the store's own terms). True when
        the artefact is now ``finished`` from it; False when a newer build overtook it meanwhile (nothing changes:
        that build's own finish counts)."""
        self._check(artefact)
        gen = generation if isinstance(generation, Generation) else Generation.parse(generation)
        with self._db.transaction() as tx:
            n = tx.execute(
                "UPDATE built SET state = ?, finished_at = ?, ref = ? WHERE artefact = ? AND snapshot = ? AND seq = ?",
                (FINISHED, _now(), ref, artefact, gen.snapshot, gen.seq),
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


def guarded[T](
    artefact: str,
    generation: Generation | str,
    build: Callable[[], T],
    url: str | None = None,
    ref: Callable[[T], str] | None = None,
) -> T | None:
    """Run ``build`` as the build of ``artefact`` from ``generation``: recorded before it starts and when it ends
    well (with ``ref(result)``: what it made), and alone (:meth:`Built.building`: it waits for a build of the
    artefact that runs). A generation older than the artefact's is refused: ``build`` does not run and None is
    returned (logged). ``build``'s own error propagates and leaves the artefact ``building`` (never ``finished``);
    so does :class:`Overtaken`. Not recorded, the build runs as before: without a trial database, and for a
    snapshot whose name is not a generation (a tool's, a test's: it has no place in the order)."""
    if not (url or os.environ.get(ENV)):
        return build()
    try:
        asked = generation if isinstance(generation, Generation) else Generation.parse(generation)
    except ValueError:
        log.warning("%s built from a snapshot that is not a night: not recorded in the generation ledger", artefact)
        return build()
    with Built(url) as ledger, ledger.building(artefact):
        try:
            gen = ledger.begin(artefact, asked)
        except OlderGeneration as exc:
            log.warning("%s", exc)
            return None
        out = build()
        if not ledger.finish(artefact, gen, ref(out) if ref is not None else ""):
            raise Overtaken(f"the build of {artefact} from {gen} was overtaken by a newer one: it does not count")
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


__all__ = ["Built", "Overtaken", "generation_of", "guarded"]
