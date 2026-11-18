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

**When the facts disagree** (the rule, D-1221): time decides, and an older fact never overrides a newer one.

1. The record is the newer of the participant record's last step and the screening log's row ("on the list" on
   either says nothing). Once consented (consented, enrolled, on study, completed, withdrawn) the record is the
   state: no mark or contact outcome speaks for a participant.
2. Before consent, the newest of the record, the contact outcome in force and the investigator's latest mark event
   is the state. A mark taken back, or a "Not now" whose re-check day has come, is a fact too: on the list.
3. On a tie of times (or facts with no time), the later step in the work wins: participant record, then screening
   log, then contact outcome, then mark.
4. Nothing recorded: on the list. The facts could not be read for this reader: **unknown** (never "on the list",
   never contactable; a count of it is "–").

The console never writes a state here: this is the console's reading of what the other steps recorded.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from tb_common.erased import is_erased

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
#: the state when the facts could not be read for this reader (CR-010): never "on the list", never contactable
UNKNOWN = "unknown"

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
    marks: int = 0  # how many mark events the investigator made (a re-marked Approach is the second or later)
    ever: tuple[str, ...] = ()  # every step the participant record ever reached and still stands (not undone)


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
        """A contact outcome may be recorded: a candidate, before consent (review F-13); never an unknown state."""
        return self.phase == "candidate" and self.name != UNKNOWN


def _recheck_due(day: str, today: date | None) -> bool:
    if today is None:
        return False
    try:
        return date.fromisoformat(day[:10]) <= today
    except ValueError:
        return True  # a "Not now" with no readable day is back on the list, as on the weekly page


#: the contact outcomes that write the screening log (``sitestore.OUTCOMES``); a log row "on the list" newer than one
#: of them says the step was taken back
LOGGED = frozenset({"reached_booked", "reached_declined", "lost_contact"})
#: the order of the work at one instant (a frozen clock, a demo, a drill: every fact of a page view shares one time).
#: Within a source the store's own order decides (the latest mark event, the outcome in force). Across sources what
#: the work makes certain: a contact outcome needs an Approach mark before it, so a mark other than Approach at the
#: same instant came after the outcome (rank 4); a re-marked Approach (the investigator's second mark or later) came
#: after the outcome it reopens (rank 4); the participant record follows the log it is refreshed from (3), the log
#: follows the outcome that wrote it (2); the first Approach mark came before every outcome (0)
_RANK = {"participant": 3, "registry": 2, "outcome": 1, "mark": 4}


def _rank(ps: PersonState, f: Facts) -> int:
    if ps.source == "mark" and f.mark == "approach" and f.marks < 2:
        return 0
    return _RANK.get(ps.source, -1)


#: which zone a time WITHOUT an offset is in, by its source: the console stamps marks and contact outcomes in UTC
#: (``Helpers.clock``, aware); the orchestrator stamps the screening log and the participant record in the site's zone
#: (``orchestrator.app`` ``_now``: ``datetime.now(ZoneInfo(site.tz))``, aware too). A plain day (a participant's
#: ``since``) is that day's start in the site's zone, and is coarse: within its day it never beats a timed fact
_SITE_SOURCES = frozenset({"participant", "registry", "list"})
_COARSE = timedelta(days=1) - timedelta(microseconds=1)


def _instant(at: str, source: str, tz: tzinfo) -> datetime | None:
    """A stored time as a UTC instant; ``None`` when there is none (or it cannot be read)."""
    text = str(at or "").strip()
    if not text:
        return None
    try:
        if len(text) <= 10:  # a plain day: its start in the site's zone (coarse, see :data:`_COARSE`)
            return datetime.combine(date.fromisoformat(text), time(0), tz).astimezone(UTC)
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz if source in _SITE_SOURCES else UTC)
    return t.astimezone(UTC)


_NEVER = datetime(1, 1, 1, tzinfo=UTC)


def state_of(f: Facts, today: date | None = None, tz: tzinfo = UTC) -> PersonState:
    """The one state of a person from what the console holds (the rule is in the module's docstring). ``tz``: the
    site's zone (for a plain day and a time without an offset from the orchestrator)."""

    def key(x: PersonState) -> tuple[datetime, int]:
        at = _instant(x.since, x.source, tz) or _NEVER
        if len(str(x.since or "").strip()) == 10:
            at = at - _COARSE  # a plain day says only "that day": any timed fact of the same day is later
        return (at, _rank(x, f))

    life = FROM_LIFE.get(f.life or "")
    if life == "screen_fail" and f.life_reason == "declined":
        life = "declined"
    reg = FROM_REGISTRY.get(f.registry or "")
    by_life = PersonState(life, "participant", f.life_at, f.life_by, f.record) if life else None
    by_reg = PersonState(reg, "registry", f.registry_at, f.registry_by, f.record) if reg else None
    # 1. the record: the newer of the participant record and the screening log ("on the list" says nothing)
    record = max((x for x in (by_life, by_reg) if x is not None and x.name != "listed"), key=key, default=None)
    if by_life is not None and by_life.name == "listed" and record is not None and key(by_life) > key(record):
        record = by_life  # the participant record was set back after the log's step (an undo the log did not follow)
    if record is not None and record.name in PARTICIPANT:
        return record  # 2. once consented, no mark or contact outcome speaks for the person
    facts: list[PersonState] = [record] if record is not None else []
    oc = FROM_OUTCOME.get(f.outcome or "")
    if oc is not None and reg == "listed" and f.outcome in LOGGED:
        log_at = _instant(f.registry_at, "registry", tz) or _NEVER
        out_at = (_instant(f.outcome_at, "outcome", tz) or _NEVER).replace(microsecond=0)  # the log keeps seconds
        if log_at >= out_at:
            # the log was set back after the outcome wrote it (an undo; in the same second too: an undo follows its
            # original): the outcome is older
            oc = None
    if oc is not None:
        facts.append(PersonState(oc, "outcome", f.outcome_at, f.outcome_by, f.record))
    if f.mark == "withdrawn" or (f.mark == "not_now" and _recheck_due(f.recheck, today)):
        facts.append(PersonState("listed", "mark", f.mark_at, f.mark_by, f.record))  # taken back, or re-check due
    elif f.mark in FROM_MARK:
        facts.append(PersonState(FROM_MARK[f.mark], "mark", f.mark_at, f.mark_by, f.record))
    if facts:  # 3. the newest fact wins: an older fact never overrides a newer one
        return max(facts, key=key)
    return by_life or by_reg or PersonState("listed", "list", record=f.record)


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
    the screening log or the participant records could not be read for this reader: every state is then
    :data:`UNKNOWN` and a count is unknown, never zero (CR-010). ``log_ok``: the screening log itself was read (the
    authority before consent, as on master). ``gone``: the opt-out register as the console reads it
    (``tb_common.erased.Gone``: an opted-out pseudonym, and an erased token ``erased:<day>:<hex>`` by its own match)."""

    facts: dict[str, Facts]
    today: date | None = None
    readable: bool = True
    gone: Any = frozenset()  # anything that answers ``pid in gone`` (D-147, D-273, D-875)
    tz: tzinfo = UTC  # the site's zone
    log_ok: bool = True
    _cache: dict[str, PersonState] = field(default_factory=dict)

    def left_out(self, pid: str) -> bool:
        """Opted out or erased: on no list and in no count (D-147, D-273, D-875)."""
        return pid in self.gone or is_erased(pid)

    def of(self, pid: str) -> PersonState:
        """The state of ``pid`` (a person nobody recorded anything about is on the list)."""
        if not self.readable:
            return PersonState(UNKNOWN, "list")
        got = self._cache.get(pid)
        if got is None:
            got = self._cache[pid] = state_of(self.facts.get(pid) or Facts(), self.today, self.tz)
        return got

    def log_state(self, pid: str) -> PersonState | None:
        """The state from the screening log, the outcome and the mark only (the participant records unread), or
        ``None`` when the log itself was not read: the authority for a person before consent, as on master."""
        if not self.log_ok:
            return None
        f = self.facts.get(pid) or Facts()
        return state_of(Facts(**{**f.__dict__, "life": None, "ever": ()}), self.today, self.tz)

    def states(self) -> dict[str, PersonState]:
        return {pid: self.of(pid) for pid in self.facts if not self.left_out(pid)}

    def counts(self) -> dict[str, int]:
        return counts(self.states().values())

    def in_year(self, year: int) -> dict[str, int]:
        """The counts of the people whose state began in ``year`` (the research office's calendar year)."""
        return counts(s for s in self.states().values() if s.since[:4] == str(year))

    def reached(self, step: str, year: int | None = None) -> int:
        """How many people ever reached ``step`` (:data:`REACHED`): their state now, or a step their participant
        record took and still stands (an enrolled participant who withdrew was enrolled). ``year``: only the people
        whose state began in that year (the research office)."""
        n = 0
        for pid, st in self.states().items():
            if year is not None and st.since[:4] != str(year):
                continue
            ever = {st.name, *(FROM_LIFE.get(x, "") for x in (self.facts.get(pid) or Facts()).ever)}
            n += bool(ever & REACHED[step])
        return n


#: "reached at least", as master counted it (the registry's ranks: contacted 1, consented 2, enrolled 3, with a screen
#: failure among the contacted; a decline and a withdrawal are not ranks), and cumulative: a person is counted at
#: every step they ever reached. contacted = contacted, screen failure or any later step of the main line; consented =
#: consented or later; enrolled = enrolled, on study or completed. "Ever" is the participant record's steps that still
#: stand (an enrolled participant who withdrew stays counted as consented and enrolled)
REACHED: dict[str, frozenset[str]] = {
    "contacted": frozenset({"contacted", "screen_fail", "consented", "enrolled", "on_study", "completed"}),
    "consented": frozenset({"consented", "enrolled", "on_study", "completed"}),
    "enrolled": frozenset({"enrolled", "on_study", "completed"}),
}


def reached(c: Mapping[str, int], step: str) -> int:
    """How many people of the counts ``c`` are in a state of ``step`` now (:data:`REACHED`; no history)."""
    return sum(int(c.get(s, 0)) for s in REACHED[step])


def funnel(people: People, listed: Iterable[str] = ()) -> dict[str, int]:
    """The home card's funnel, as master showed it (Found, PI reviewed, Contacted, Consented, Enrolled; cumulative),
    from the one state: found = on the latest list or with a fact; reviewed = an investigator's mark or past it."""
    st = people.states()
    found = {p for p in listed if not people.left_out(p)} | set(st)
    marked = {p for p, f in people.facts.items() if f.mark and f.mark != "withdrawn" and not people.left_out(p)}
    passed = {p for p, x in st.items() if x.name not in ("listed",)}
    return {"found": len(found), "reviewed": len(marked | passed), "contacted": people.reached("contacted"),
            "consented": people.reached("consented"), "enrolled": people.reached("enrolled")}  # fmt: skip


def _at(v: Any) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else str(v or "")


def gather(
    *,
    registry: Iterable[Any] = (),
    marks: Mapping[str, Any] | None = None,
    outcomes: Iterable[Any] = (),
    subjects: Iterable[Mapping[str, Any]] = (),
    gone: Any = frozenset(),
    today: date | None = None,
    readable: bool = True,
    tz: tzinfo = UTC,
    log_ok: bool = True,
    mark_events: Mapping[str, int] | None = None,
) -> People:
    """The people of one study from the four sources: ``registry`` the screening log's rows (``RegistryEntry``),
    ``marks`` the latest mark event per pseudonym (``Mark``; a ``withdrawn`` event is a mark taken back),
    ``outcomes`` the contact outcomes in force, oldest first (``Outcome``), ``subjects`` the participant records
    (dicts with ``pid``, ``record``, ``state``, ``since``, ``changed_at``; of two records of one pseudonym the latest
    is kept). A person in ``gone`` (opted out) is in no count and no population (:meth:`People.states`), as on every
    list; a page that keeps their trial record (NEW-LIFE-5) still reads their state with :meth:`People.of`. A
    participant record with no pseudonym yet is keyed by ``#`` and its screening number."""
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
        at = str(s.get("changed_at") or s.get("since") or "")
        mine = one(pid or f"#{rec}")
        if mine.get("life") and (_instant(mine.get("life_at", ""), "participant", UTC) or _NEVER) > (
                _instant(at, "participant", UTC) or _NEVER):  # fmt: skip
            continue  # an older record of the same pseudonym
        mine.update(life=str(s.get("state") or ""), life_reason=str(s.get("reason") or ""), life_at=at,
                    life_by=str(s.get("changed_by") or ""), record=rec,
                    ever=tuple(str(x) for x in s.get("ever") or ()))  # fmt: skip
    for pid, n in (mark_events or {}).items():
        if pid in raw:
            raw[pid]["marks"] = n
    facts = {pid: Facts(**v) for pid, v in raw.items()}
    return People(facts, today, readable, gone, tz, log_ok)


def latest_marks(all_marks: Iterable[Any]) -> dict[str, Any]:
    """The latest mark event per pseudonym, a mark taken back (``withdrawn``) included: it is a fact with a time."""
    out: dict[str, Any] = {}
    for m in all_marks:  # oldest first
        out[str(m.pid)] = m
    return out


_REQUEST: ContextVar[dict[tuple[str, str], Any] | None] = ContextVar("person_state_request", default=None)


def begin_request() -> Token[dict[tuple[str, str], Any] | None]:
    """One page view: reads made during it are kept for it (a GET only; a write reads afresh)."""
    return _REQUEST.set({})


def end_request(token: Token[dict[tuple[str, str], Any] | None]) -> None:
    _REQUEST.reset(token)


def _kept(name: str, rs: str, make: Callable[[], Any]) -> Any:
    cache = _REQUEST.get()
    if cache is None:
        return make()
    k = (name, rs)
    if k not in cache:
        cache[k] = make()
    return cache[k]


def per_view(name: str, rs: str, make: Callable[[], Any]) -> Any:
    """``make()`` once per page view (a GET) for ``(name, rs)``; afresh outside one. For a read that every part of one
    page asks again for the same study, such as an account's standing in its delegation log (J-6, D-1225)."""
    return _kept(name, rs, make)


def registry_rows(h: Any, rs: str) -> list[Any]:
    """The screening log's rows of ``rs``, read once per page view (signed for the reader, D-717)."""
    return list(_kept("registry", rs, lambda: list(h.bk.registry_rows(rs))))


def may_read_rows(rs: str) -> bool:
    """Whether the reader of this request may read patient-level rows of ``rs`` (``phi.view`` on the study); a timer
    (no person) reads as its own principal. Asked before a read so a refused read is never attempted."""
    from console import actor as console_actor

    check = getattr(console_actor, "may_read", None)
    return bool(check(rs)) if callable(check) else True


def subject_rows(h: Any, rs: str) -> list[dict[str, Any]] | None:
    """The participant records of ``rs``: record, pseudonym, state, since and when it changed (the slim read), once
    per page view; ``None`` when they could not be read; ``[]`` on a box with no study store."""
    from console import s28
    from console.backend import Problem, Unavailable

    if not s28.has_api(h.bk):
        return []

    def make() -> list[dict[str, Any]] | None:
        try:
            got = s28.call(h.bk, "GET", f"/studies/{rs}/subjects?slim=1")
        except (Problem, Unavailable):
            return None
        return [x for x in (got or {}).get("subjects") or [] if isinstance(x, dict)]

    return _kept("subjects", rs, make)  # type: ignore[no-any-return]


def read(h: Any, rs: str, *, subjects: list[dict[str, Any]] | None = None) -> People:
    """The people of study ``rs`` as this reader may read them (``h`` is ``console.home.Helpers``), once per page view.
    The screening log and the participant records are read signed for the person of the request (D-717); a reader
    without the right to patient-level rows is not asked to read them (no refused read is attempted). A refused,
    failed or not permitted read leaves ``readable`` False (every state unknown) for a page, and is an error for a
    mail round (never "no status"). ``subjects``: the participant records when the caller already holds them."""
    from console import actor as console_actor

    log = logging.getLogger("console.person_state")
    mail = not console_actor.reading_for_a_person()
    if not mail and not may_read_rows(rs):
        return People({}, h.today(), False, log_ok=False)
    readable = log_ok = True
    rows: list[Any] = []
    try:
        rows = registry_rows(h, rs)
    except Exception:
        if mail:
            raise
        readable = log_ok = False
    subs: list[dict[str, Any]] = list(subjects or [])
    if subjects is None and readable:
        got = subject_rows(h, rs)
        if got is None:
            readable = False
            if mail:  # a mail round never goes on with an unknown state as if it were known
                log.error("the participant records could not be read", extra={"study": rs})
        else:
            subs = got
    outcomes: list[Any] = []
    marks: dict[str, Any] = {}
    events: dict[str, int] = {}
    with contextlib.suppress(Exception):  # a store without the tables (an old box) holds no mark or outcome
        every = h.store.all_marks(rs)
        marks = latest_marks(every)
        for m in every:
            events[str(m.pid)] = events.get(str(m.pid), 0) + 1
        outcomes = h.store.outcomes(rs)
    gone: Any = frozenset()
    gone_of: Callable[[], Any] | None = getattr(h, "gone", None)
    if callable(gone_of):
        with contextlib.suppress(Exception):
            gone = gone_of()  # the register itself: it matches an erased token too (D-875)
    tz: tzinfo = UTC
    with contextlib.suppress(Exception):
        from console.timefmt import site_zone

        tz = site_zone(h.bk)
    return gather(registry=rows, marks=marks, outcomes=outcomes, subjects=subs, gone=gone, today=h.today(),
                  readable=readable, tz=tz, log_ok=log_ok, mark_events=events)  # fmt: skip


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
    "REACHED",
    "STATES",
    "UNKNOWN",
    "Facts",
    "People",
    "PersonState",
    "begin_request",
    "counts",
    "end_request",
    "funnel",
    "gather",
    "key",
    "latest_marks",
    "per_view",
    "reached",
    "read",
    "registry_rows",
    "shown_counts",
    "state_of",
]
