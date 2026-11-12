"""A lake generation as a value with an order, and what a reader is told about a derived artefact (T-725, D-491).

A generation is ``<date>.g<n>`` (T-724, D-490): the snapshot date and a sequence number. A bare date is that date's
generation 0: a lake without generations, or a store that only knows the night. Generations are ordered by date,
then by number: "older" and "newer" mean this order everywhere. The date is a calendar date written
``YYYY-MM-DD`` and the number is written in ASCII digits from 1: any other name (a tool's snapshot, ``latest``, a
date without its zeros) is not a generation and has no place in the order (:meth:`Generation.parse` refuses it).

:class:`Verdict` is the answer of the one reader question, "may a job pinned to generation G read this artefact"
(``datacore.generations.Built.readable``): ``ok`` only when the artefact is finished and built from exactly G.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import total_ordering

_GEN = re.compile(r"^(?P<snap>[0-9]{4}-[0-9]{2}-[0-9]{2})(?:\.g(?P<seq>[1-9][0-9]*))?$", re.ASCII)
#: the derived artefacts, in the order the night builds them
ARTEFACTS = ("fhir", "derived", "twin", "vec")
BUILDING, FINISHED = "building", "finished"


@total_ordering
@dataclass(frozen=True)
class Generation:
    snapshot: str
    seq: int = 0

    @classmethod
    def parse(cls, name: str) -> Generation:
        m = _GEN.match(str(name))
        if not m:  # also "<date>.g0", "<date>.g": a number from 1, or no suffix
            raise ValueError(f"not a generation: {name!r}")
        try:
            date.fromisoformat(m["snap"])
        except ValueError:
            raise ValueError(f"not a generation: {name!r} (not a calendar date)") from None
        return cls(m["snap"], int(m["seq"] or 0))

    def __str__(self) -> str:
        return f"{self.snapshot}.g{self.seq}" if self.seq else self.snapshot

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Generation):
            return NotImplemented
        return (self.snapshot, self.seq) < (other.snapshot, other.seq)


class OlderGeneration(RuntimeError):
    """A build from a generation older than the one the artefact holds: refused, nothing is written."""

    def __init__(self, artefact: str, asked: Generation, holds: Generation) -> None:
        super().__init__(
            f"{artefact} is built from {holds}; a build from the older {asked} is refused (an older generation never "
            "overwrites a newer one)"
        )
        self.artefact, self.asked, self.holds = artefact, asked, holds


@dataclass(frozen=True)
class Verdict:
    """``ok``: the artefact may be read by a job pinned to the generation asked about. Else ``reason`` says why not,
    in words a person can read; the reader then treats what it wanted from the artefact as unknown."""

    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def verdict(artefact: str, pinned: Generation, built: Generation | None, state: str | None) -> Verdict:
    """The one rule: finished, and from exactly the pinned generation."""
    if built is None:
        return Verdict(False, f"{artefact} was never built")
    if built != pinned:
        when = "an older" if built < pinned else "a newer"
        return Verdict(False, f"{artefact} is built from {when} generation ({built}), not from {pinned}")
    if state != FINISHED:
        return Verdict(False, f"{artefact} is still being built from {pinned}")
    return Verdict(True)


__all__ = ["ARTEFACTS", "BUILDING", "FINISHED", "Generation", "OlderGeneration", "Verdict", "verdict"]
