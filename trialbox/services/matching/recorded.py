"""The kinds of coded record each patient has at all (red of lane G's run, 2026-11-16; D-914).

A coded criterion matches its value set against the rows of one domain. For a patient with no row of that domain at
all (no medication, no observation: the public TREC 2023 patients, whose facts are a questionnaire in a note; a
hospital patient whose prescriptions are written elsewhere) the compiled SQL answers FALSE, and an inclusion's FALSE
excluded them: nine of lane G's ten wrong exclusions. Their record says nothing either way. This module reads, once
per run and from the same snapshot, which domains each patient's rows cover, and names a criterion's atoms the
patient has no row of. The runtime turns an excluding answer such an atom could have changed into unknown with the
reason ``no_record_of_kind``: an inclusion's FALSE where a record would have made the atom truer, an exclusion's TRUE
where it would have made it falser ("none"). An answer that keeps the patient stands. It is D-795's rule
(``matching.carried``) per patient, on the excluding side only. The approved SQL is unchanged; the study's own
condition (the index criterion) keeps its scope rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from tb_common.reasons import Reason
from tb_contracts import CriterionIR

from matching.carried import DOMAINS, _atoms

NO_RECORD = Reason.NO_RECORD_OF_KIND.value
#: one query for every domain, written out (O1, CODED-PROFILE R3: seven round trips, each carrying the whole scope,
#: became one): the patients of the list ($1) who have any row of a domain, the domain in its own column
QUERY = "WITH scope AS (SELECT unnest(CAST($1 AS VARCHAR[])) AS pid)\n" + "\nUNION ALL\n".join(
    f"SELECT DISTINCT '{table}' AS domain, pid FROM {table} WHERE pid IN (SELECT pid FROM scope)" for table in DOMAINS
)
#: rows made Python objects at a time: up to one per patient and domain (700,000 at 100,000 patients), never all at once
BATCH = 65_536


def is_index_criterion(c: CriterionIR) -> bool:
    """The study's own condition (``matching.cascade.engine.is_index_criterion``): its scope rule stands."""
    return bool(getattr(c, "index", None))


class _Lake(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


@dataclass(frozen=True)
class Recorded:
    """Per patient, the domains their rows cover; empty (not read): no check."""

    domains: dict[str, frozenset[str]] = field(default_factory=dict)
    read: bool = False

    @classmethod
    def load(cls, lake: _Lake, pids: Iterable[str], snapshot: str | None) -> Recorded:
        ids = sorted(set(pids))
        out: dict[str, set[str]] = {p: set() for p in ids}
        if ids:
            # no SQL is put together from data
            for batch in lake.query(QUERY, [ids], snapshot).to_batches(BATCH):
                for r in batch.to_pylist():
                    out.setdefault(str(r["pid"]), set()).add(str(r["domain"]))
        return cls({p: frozenset(d) for p, d in out.items()}, True)

    @classmethod
    def for_criteria(
        cls, lake: _Lake, criteria: list[CriterionIR], pids: Iterable[str], snapshot: str | None
    ) -> Recorded:
        """Read only when a non-index criterion has a coded atom (no lake query otherwise)."""
        if not any(c.logic is not None and not is_index_criterion(c) and _atoms(c.logic) for c in criteria):
            return cls()
        return cls.load(lake, pids, snapshot)

    def missing(self, c: CriterionIR, pid: str) -> tuple[list[str], list[str]]:
        """The domains of ``c``'s atoms ``pid`` has no row of: those a record would make truer, and falser."""
        if not self.read or c.logic is None or is_index_criterion(c):
            return [], []
        have = self.domains.get(pid, frozenset())
        truer: list[str] = []
        falser: list[str] = []
        for atom, up in _atoms(c.logic):
            if atom.domain in have:
                continue
            side = truer if up else falser
            if atom.domain not in side:
                side.append(atom.domain)
        return truer, falser

    def doubt(self, c: CriterionIR, pid: str, value: bool | None) -> list[str]:
        """The domains whose absence leaves an excluding ``value`` unsettled for ``pid``: an inclusion's FALSE a
        record could have made TRUE, or an exclusion's TRUE (under "none") a record could have made FALSE. An answer
        that keeps the patient stands: turning it to unknown would prevent no wrong exclusion and only add review
        (D-914). Empty: the answer stands."""
        if value is None:
            return []
        truer, falser = self.missing(c, pid)
        if c.kind == "inclusion" and value is False:
            return truer
        if c.kind == "exclusion" and value is True:
            return falser
        return []


__all__ = ["NO_RECORD", "QUERY", "Recorded"]
