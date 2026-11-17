"""One state for one person in one study, read the same way by every list and every count (D-1221, review R10).

The console holds four facts about a person in a study, each written by a different step:

* the investigator's **mark** on the weekly list (Approach, Need info, Not suitable now, Not now; ``SiteStore``);
* the coordinator's **contact outcome** (reached and booked, declined, not reached, not approached, lost contact);
* the **screening log** row (the candidate registry in the orchestrator: candidate, contacted, consented ...);
* the **participant record** and its last life step (the data core's lifecycle: consented, enrolled, on study ...).

Before this module each list read one or two of them and named what it found in its own words: the weekly page
"new this week" / "pending" / "contacted" / "consented", the registry "candidate" / "contacted" / "consented",
Participants "Candidate" / "Approached" / "On study", the home card a cumulative funnel and the research office its
own counts. :func:`state_of` reads all four and returns ONE name from :data:`STATES`; its text key is
``person.state.<name>`` in en, zh-TW and ja (``console.i18n_person``). Every list and every count imports it from
here; the older key families (``life.state.*``, ``registry.status.*``) are aliases of these words.

**When the facts disagree** (the rule, D-1221):

1. An end state on the participant record (completed, withdrawn, screen failure) wins: it is the later fact and a
   person recorded it on the participant page.
2. Else an end state on the screening log (declined, screen failure, withdrawn) wins: the participant record takes
   it at its next refresh (the data core moves a subject forward to the log, never back).
3. Else the further of the participant record and the screening log on the main line (on the list, contacted,
   consented, enrolled, on study, completed); a tie goes to the participant record.
4. Only while neither says more than "on the list" or "contacted": the latest contact outcome in force (it is the
   later fact: "not approached" and "not reached" leave the log as it was).
5. Only while nothing above says more than "on the list": the investigator's mark (a "Not now" whose re-check day
   has come no longer sets the person aside).
6. Otherwise: on the list.

The console never writes a state here: this is the console's reading of what the other steps recorded.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

#: every state, in the order a person moves through a study; the first eight are a Candidate's (before consent),
#: the last five a Participant's (review table "One thing, several names")
STATES: tuple[str, ...] = (
    "listed",
    "need_info",
    "set_aside",
    "to_contact",
    "contacted",
    "not_approached",
    "declined",
    "screen_fail",
    "consented",
    "enrolled",
    "on_study",
    "completed",
    "withdrawn",
)
CANDIDATE: tuple[str, ...] = STATES[:8]
PARTICIPANT: tuple[str, ...] = STATES[8:]
ENDED: frozenset[str] = frozenset({"not_approached", "declined", "screen_fail", "completed", "withdrawn"})
#: the states counted on the home card, the registry and the research office: a person somebody has acted on (all but
#: "On the list", which is every listed patient nobody has reviewed yet)
COUNTED: tuple[str, ...] = STATES[1:]
KEY = "person.state."
MAIN_LINE: tuple[str, ...] = ("listed", "contacted", "consented", "enrolled", "on_study", "completed")

#: the participant record's life step (``datacore.lifecycle.STATES``) as a person state
FROM_LIFE: dict[str, str] = {
    "candidate": "listed",
    "approached": "contacted",
    "consented": "consented",
    "enrolled": "enrolled",
    "on_study": "on_study",
    "completed": "completed",
    "withdrawn": "withdrawn",
    "screen_fail": "screen_fail",
}
#: the screening log's status (``orchestrator.candidates.STATUSES``) as a person state
FROM_REGISTRY: dict[str, str] = {
    "candidate": "listed",
    "contacted": "contacted",
    "consented": "consented",
    "enrolled": "enrolled",
    "screen_fail": "screen_fail",
    "declined": "declined",
    "withdrawn": "withdrawn",
}
#: a contact outcome in force (``sitestore.OUTCOMES``) as a person state
FROM_OUTCOME: dict[str, str] = {
    "reached_booked": "contacted",
    "reached_declined": "declined",
    "not_reached": "to_contact",
    "not_approached": "not_approached",
    "lost_contact": "screen_fail",
}
#: the investigator's current mark (``sitestore.MARKS``) as a person state
FROM_MARK: dict[str, str] = {
    "approach": "to_contact",
    "need_info": "need_info",
    "not_suitable": "set_aside",
    "not_now": "set_aside",
}
#: the weekly list's own row status (``studies.derive_status``), for a row nobody has a fact about yet
FROM_WEEK: dict[str, str] = {
    "new": "listed",
    "pending": "listed",
    "contacted": "contacted",
    "screened": "consented",
    "enrolled": "enrolled",
    "set_aside": "set_aside",
}


def key(name: str) -> str:
    """The text key of a state (``person.state.to_contact``)."""
    return KEY + name


@dataclass(frozen=True)
class Facts:
    """What the console holds about one person in one study. Every field may be missing."""

    mark: str | None = None  # the investigator's current mark (a withdrawn mark is no mark)
    mark_at: str = ""
    mark_by: str = ""
    recheck: str = ""  # a "Not now" mark's re-check day (ISO date)
    outcome: str | None = None  # the latest contact outcome in force
    outcome_at: str = ""
    outcome_by: str = ""
    registry: str | None = None  # the screening log's status
    registry_at: str = ""
    registry_by: str = ""
    life: str | None = None  # the participant record's state
    life_reason: str = ""
    life_at: str = ""
    life_by: str = ""
    record: str = ""  # the participant record (screening number), when there is one


@dataclass(frozen=True)
class PersonState:
    """The one state of a person, where it came from (``participant``, ``registry``, ``outcome``, ``mark`` or
    ``list``), since when and by whom, as far as the deciding fact says."""

    name: str
    source: str = "list"
    since: str = ""
    by: str = ""
    record: str = ""

    @property
    def key(self) -> str:
        return key(self.name)

    @property
    def phase(self) -> str:
        """``candidate`` before consent, ``participant`` once consented."""
        return "participant" if self.name in PARTICIPANT else "candidate"

    @property
    def ended(self) -> bool:
        return self.name in ENDED

    @property
    def contactable(self) -> bool:
        """A contact outcome still makes sense: a candidate the study has not finished with (review F-13)."""
        return self.phase == "candidate" and not self.ended


def _recheck_due(day: str, today: date | None) -> bool:
    if today is None:
        return False
    try:
        return date.fromisoformat(day[:10]) <= today
    except ValueError:
        return True  # a "Not now" with no readable day is back on the list, as on the weekly page


def _rank(name: str | None) -> int:
    return MAIN_LINE.index(name) if name in MAIN_LINE else -1


def state_of(f: Facts, today: date | None = None) -> PersonState:
    """The one state of a person from what the console holds (the rule is in the module's docstring)."""
    life = FROM_LIFE.get(f.life or "")
    if life == "screen_fail" and f.life_reason == "declined":
        life = "declined"
    reg = FROM_REGISTRY.get(f.registry or "")
    by_life = PersonState(life or "listed", "participant", f.life_at, f.life_by, f.record)
    by_reg = PersonState(reg or "listed", "registry", f.registry_at, f.registry_by, f.record)
    if life in ENDED:  # 1
        return by_life
    if reg in ENDED:  # 2
        return by_reg
    best: PersonState | None = None  # 3
    if _rank(life) >= max(_rank(reg), 1):
        best = by_life
    elif _rank(reg) >= 1:
        best = by_reg
    if best is not None and best.name != "contacted":
        return best
    oc = FROM_OUTCOME.get(f.outcome or "")  # 4
    if oc is not None and (best is None or oc in ENDED):
        return PersonState(oc, "outcome", f.outcome_at, f.outcome_by, f.record)
    if best is not None:
        return best
    mk = FROM_MARK.get(f.mark or "")  # 5
    if mk is not None and not (f.mark == "not_now" and _recheck_due(f.recheck, today)):
        return PersonState(mk, "mark", f.mark_at, f.mark_by, f.record)
    if life is not None:  # 6
        return by_life
    if reg is not None:
        return by_reg
    return PersonState("listed", "list", record=f.record)


def counts(states: Iterable[PersonState | str]) -> dict[str, int]:
    """How many people are in each state (every state is a key)."""
    out = dict.fromkeys(STATES, 0)
    for s in states:
        name = s if isinstance(s, str) else s.name
        out[name] = out.get(name, 0) + 1
    return out


def shown_counts(c: Mapping[str, int], keep: Iterable[str] = COUNTED) -> list[tuple[str, int]]:
    """``(state, n)`` for the states with someone in them, in the order of :data:`STATES` (what a count strip shows)."""
    wanted = set(keep)
    return [(s, int(c.get(s, 0))) for s in STATES if s in wanted and c.get(s, 0)]


# ---------------------------------------------------------------------------------------------- one study's people
@dataclass
class People:
    """Every person of one study the console holds a fact about, and the state of each. ``readable`` is False when
    the screening log or the participant records could not be read for this reader: a count is then unknown, never
    zero (CR-010)."""

    facts: dict[str, Facts]
    today: date | None = None
    readable: bool = True
    gone: frozenset[str] = frozenset()  # opted out: on no list and in no count, as everywhere (D-147, D-273)
    _cache: dict[str, PersonState] = field(default_factory=dict)

    def of(self, pid: str) -> PersonState:
        """The state of ``pid`` (a person nobody recorded anything about is on the list)."""
        got = self._cache.get(pid)
        if got is None:
            got = self._cache[pid] = state_of(self.facts.get(pid) or Facts(), self.today)
        return got

    def states(self) -> dict[str, PersonState]:
        return {pid: self.of(pid) for pid in self.facts if pid not in self.gone}

    def counts(self) -> dict[str, int]:
        return counts(self.states().values())

    def in_year(self, year: int) -> dict[str, int]:
        """The counts of the people whose state began in ``year`` (the research office's calendar year)."""
        return counts(s for s in self.states().values() if s.since[:4] == str(year))


def _at(v: Any) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else str(v or "")


def gather(
    *,
    registry: Iterable[Any] = (),
    marks: Mapping[str, Any] | None = None,
    outcomes: Iterable[Any] = (),
    subjects: Iterable[Mapping[str, Any]] = (),
    gone: Iterable[str] = (),
    today: date | None = None,
    readable: bool = True,
) -> People:
    """The people of one study from the four sources: ``registry`` the screening log's rows (``RegistryEntry``),
    ``marks`` the current mark per pseudonym (``Mark``), ``outcomes`` the contact outcomes in force, oldest first
    (``Outcome``), ``subjects`` the participant records (dicts with ``pid``, ``record``, ``state``, ``since``). A person
    in ``gone`` (opted out) is in no count and no population (:meth:`People.states`), as on every list; a page that
    keeps their trial record (NEW-LIFE-5) still reads their state with :meth:`People.of`. A participant record with
    no pseudonym yet is keyed by ``#`` and its screening number."""
    raw: dict[str, dict[str, Any]] = {}

    def one(pid: str) -> dict[str, Any]:
        return raw.setdefault(pid, {})

    for e in registry:
        one(str(e.pid)).update(registry=str(e.status), registry_at=_at(getattr(e, "updated_at", "")),
                               registry_by=str(getattr(e, "updated_by", "") or ""))  # fmt: skip
    for pid, m in (marks or {}).items():
        one(str(pid)).update(mark=str(m.mark), mark_at=str(m.at or ""), mark_by=str(m.by or ""),
                             recheck=str(m.reason or "") if m.mark == "not_now" else "")  # fmt: skip
    for o in outcomes:  # oldest first: the last one in force stays
        one(str(o.pid)).update(outcome=str(o.outcome), outcome_at=str(o.at or ""), outcome_by=str(o.by or ""))
    for s in subjects:
        pid = str(s.get("pid") or "")
        rec = str(s.get("record") or "")
        k = pid or f"#{rec}"
        one(k).update(life=str(s.get("state") or ""), life_reason=str(s.get("reason") or ""),
                      life_at=str(s.get("since") or ""), life_by=str(s.get("changed_by") or ""),
                      record=rec)  # fmt: skip
    facts = {pid: Facts(**v) for pid, v in raw.items()}
    return People(facts, today, readable, frozenset(gone))


def read(h: Any, rs: str, *, subjects: list[dict[str, Any]] | None = None) -> People:
    """The people of study ``rs`` as this reader may read them (``h`` is ``console.home.Helpers``). The screening log
    and the participant records are read signed for the person of the request, as every patient read (D-717); a
    refused or failed read leaves ``readable`` False for a page, and is an error for a mail round (never "no
    status"). ``subjects``: the participant records when the caller already holds them."""
    from console import actor as console_actor
    from console import s28
    from console.backend import Problem, Unavailable

    readable = True
    rows: list[Any] = []
    try:
        rows = list(h.bk.registry_rows(rs))
    except Exception:
        if not console_actor.reading_for_a_person():
            raise
        readable = False
    today = h.today()
    subs: list[dict[str, Any]] = list(subjects or [])
    if subjects is None and readable and s28.has_api(h.bk):  # a reader refused the log is not asked twice
        try:
            got = s28.call(h.bk, "GET", f"/studies/{rs}/subjects?today={today.isoformat()}")
            subs = [x for x in (got or {}).get("subjects") or [] if isinstance(x, dict)]
        except (Problem, Unavailable):
            readable = False
    outcomes: list[Any] = []
    marks: dict[str, Any] = {}
    with contextlib.suppress(Exception):  # a store without the tables (an old box) holds no mark or outcome
        marks = h.store.latest_marks(rs)
        outcomes = h.store.outcomes(rs)
    gone: set[str] = set()
    gone_of: Callable[[], set[str]] | None = getattr(h, "gone", None)
    if callable(gone_of):
        with contextlib.suppress(Exception):
            gone = set(gone_of())
    return gather(registry=rows, marks=marks, outcomes=outcomes, subjects=subs, gone=gone, today=today,
                  readable=readable)  # fmt: skip


__all__ = [
    "CANDIDATE",
    "COUNTED",
    "ENDED",
    "FROM_LIFE",
    "FROM_MARK",
    "FROM_OUTCOME",
    "FROM_REGISTRY",
    "FROM_WEEK",
    "KEY",
    "PARTICIPANT",
    "STATES",
    "Facts",
    "People",
    "PersonState",
    "counts",
    "gather",
    "key",
    "read",
    "shown_counts",
    "state_of",
]
