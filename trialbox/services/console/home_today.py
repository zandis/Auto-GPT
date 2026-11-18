"""J-6 (D-1225; the journey review's R8, R19 and R35, root review 09's J3 and DS-13): the opening page's "Next" for
the whole life of a study, and "Needs you today".

* **The flag** ``layout.home_today`` (``tb_common.flags``, audited, off by default) changes what the opening page
  shows first. Off, ``/home`` is as before. On, ``/home`` gives the coordinator, the investigator, the CRO and the
  viewer one page: a "Needs you today" block of at most :data:`LIMIT` lines, then one "Next" line per study the
  person is on. The steward, the privacy office and the administrator are on no study: their opening pages (their
  review queues, the health page) are unchanged. The flag is read like ``layout.phone_first`` (``console.phone``):
  a page gets the value last read, never waits for the store, and a value older than 5 s starts one background read.
* **Next** is one sentence per study with one link, from :func:`life_step`. It does not compute a second step: it
  starts from the step the study's week page shows (``studies.procedure_step``, through ``home.study_step``) and goes
  on past enrolment with the study's recorded state (``SiteStore.study_state``: start-up, open, paused, closed) and
  the one state of each person (``console.person_state``, D-1221). When the step is another role's the line names
  whose it is and that nothing is needed from this person, with no link. A closed study's archive is kept outside
  the product: the line says so, with no link.
* **Needs you today** (:func:`today_lines`): at most five lines, safety clocks first (a serious adverse event, one
  line per event however many reasons it has), then what is overdue, then what is due today, each with the page
  where it is done; more than five says how many more and links to the whole list (``/home?today=all``); none says
  so. What is not due yet is not on it.
* **Only what the role may read.** Each source a line draws on is asked for only when the permission matrix lets the
  role read it in that study (``home.today_home``); a role without patient-level rows gets lines from the
  aggregate reads it already has (the feasibility report, a CRO's monitor grant)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from tb_common.flags import Flags

from console import i18n_today
from console.i18n import CATALOGUES

FLAG = "layout.home_today"
#: the lines of "Needs you today" shown before "N more"
LIMIT = 5
#: the roles whose opening page is this one with the flag on (the others are on no study)
ROLES = ("coordinator", "investigator", "cro", "viewer")
#: the life of a study as the Next line says it, in order (the steps after "close" are the study's own states)
STEPS: tuple[str, ...] = (
    "startup",
    "approve",
    "feas",
    "screen",
    "review",
    "contact",
    "consent",
    "conduct",
    "close",
    "paused",
    "closed",
    "unknown",
    "report",
    "report_none",
    "monitor",
)
#: whose step it is (the role named on another person's home); "" = nobody in the product
OWNER: dict[str, str] = {
    "startup": "coordinator",
    "approve": "investigator",
    "feas": "coordinator",
    "screen": "coordinator",
    "review": "investigator",
    "contact": "coordinator",
    "consent": "coordinator",
    "conduct": "coordinator",
    "close": "coordinator",
    "paused": "coordinator",
    "closed": "",
    "unknown": "",
    "report": "",
    "report_none": "coordinator",
    "monitor": "",
}
#: every Next sentence's key (``today.next.<step>.<mine|other>``), for ``tools.text_keys``
NEXT_KEYS: tuple[str, ...] = tuple(f"{s}.{w}" for s in STEPS for w in ("mine", "other"))
#: the kinds of a "Needs you today" line (``today.line.<kind>``)
KINDS: tuple[str, ...] = (
    "sae_ack",
    "sae_overdue",
    "sae_noclock",
    "sae_wait_pi",
    "visits_overdue",
    "visits_today",
    "site",
    "call",
    "info",
    "prepare",
    "refer",
    "delegation",
)
#: the ordering rule: safety clocks, then overdue, then due today
SAFETY, OVERDUE, TODAY = 0, 1, 2

for _lang, _cat in (("en", i18n_today.EN), ("ja", i18n_today.JA), ("zh-TW", i18n_today.ZH)):
    CATALOGUES[_lang].update(_cat)


# ------------------------------------------------------------------------------------------------- the flag's read
_clock = time.monotonic
_kept: tuple[bool, float] | None = None
_guard = threading.Lock()  # guards _kept and _reading only, never held during a read
_reading = False
FLAG_SECONDS = 5.0


def _read() -> bool:
    return Flags().row(FLAG) == "on"


def clear_cache() -> None:
    global _kept
    with _guard:
        _kept = None


def _refresh() -> None:
    global _kept, _reading
    try:
        value = bool(_read())
    except Exception:  # the store is down, not installed, no URL: off until the next read
        value = False
    with _guard:
        _kept = (value, _clock())
        _reading = False


def flag_now() -> bool:
    """The value last read, at once (off before the first read); a value older than 5 s starts one background read."""
    global _reading
    with _guard:
        kept = _kept
        stale = kept is None or _clock() - kept[1] >= FLAG_SECONDS
        start = stale and not _reading
        if start:
            _reading = True
    if start:
        threading.Thread(target=_refresh, name="home-today-flag", daemon=True).start()
    return kept[0] if kept is not None else False


def flag_on() -> bool:
    """The flag read now, waiting for the store (a command line, a test); never raises."""
    global _reading
    with _guard:
        _reading = True
    _refresh()
    return flag_now()


# ------------------------------------------------------------------------------------------------- Next
def life_step(
    *,
    state: str,
    step: int,
    screen_done: bool,
    counts: Mapping[str, int] | None,
) -> str:
    """The study's next step in its life (one of :data:`STEPS`) for a reader of patient-level rows.

    ``state`` the study's recorded state; ``step`` the index ``studies.procedure_step`` gives the week page (1
    criteria waiting, 2 no feasibility, 3 screening, 4 someone contacted, 5 someone enrolled); ``counts`` the people
    by their one state (``People.counts()``), ``None`` when they could not be read."""
    if state == "closed":
        return "closed"
    if state == "paused":
        return "paused"
    if state == "startup":
        return "startup"
    if step <= 1:
        return "approve"
    if step == 2:
        return "feas"
    if not screen_done:
        return "screen"
    if counts is None:
        return "unknown"
    active = sum(int(counts.get(s, 0)) for s in ("consented", "enrolled", "on_study"))
    if step >= 5:
        return "conduct" if active else "close"
    if step == 4:
        return "consent"
    return "contact" if counts.get("to_contact") else "review"


def report_step(*, report: bool, grant: tuple[str, str, str] | None) -> str:
    """The next step for a reader of aggregate counts only (viewer, CRO): the feasibility report and the monitor
    grant are what such an account reads; the patient-level steps are not read for it."""
    if grant is not None:
        return "monitor"
    return "report" if report else "report_none"


def href_of(step: str, rs: str, *, approval: str = "") -> str:
    """The page where ``step`` is done (empty: none in the product)."""
    return {
        "startup": f"/studies/{rs}/state",
        "approve": approval,
        "feas": f"/pilot/request?ruleset={rs}",
        "screen": f"/pilot/request?ruleset={rs}",
        "review": f"/studies/{rs}/week?list=review",
        "contact": f"/studies/{rs}/week?list=approached",
        "consent": f"/studies/{rs}/subjects",
        "conduct": f"/studies/{rs}/visits",
        "close": f"/studies/{rs}/state",
        "paused": f"/studies/{rs}/state",
        "report": f"/studies/{rs}/feasibility",
        "monitor": f"/studies/{rs}/monitor",
    }.get(step, "")


@dataclass
class NextLine:
    rs: str
    step: str
    mine: bool
    href: str  # empty when the step is not this person's or has no page
    values: dict[str, Any] = field(default_factory=dict)
    in_today: bool = False  # the same page is a line of "Needs you today": the link is there, not here

    @property
    def key(self) -> str:
        return f"today.next.{self.step}.{'mine' if self.mine else 'other'}"


def next_line(rs: str, step: str, mine: bool, href: str, **values: Any) -> NextLine:
    if step in ("closed", "unknown"):
        mine = False  # nobody acts in the product: a sentence, no link
    owner = OWNER.get(step, "")
    return NextLine(rs, step, mine, href if mine else "", {"rs": rs, "owner": owner, **values})


# ------------------------------------------------------------------------------------------------- Needs you today
@dataclass
class TodayLine:
    kind: str
    rs: str
    href: str
    rank: int  # SAFETY, OVERDUE or TODAY
    due: str = ""  # YYYY-MM-DD, empty for none
    what: str = ""  # the event, the patient or the count the line is about; its identity on the page
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"today.line.{self.kind}"

    @property
    def ident(self) -> tuple[str, str, str]:
        return (self.kind.split("_")[0], self.rs, self.what)


def sae_lines(rs: str, unacked: Iterable[Mapping[str, Any]], reports: Iterable[Mapping[str, Any]], *,
              acknowledges: bool) -> list[TodayLine]:  # fmt: skip
    """One line per serious adverse event of one study, whatever number of reasons it has (root review 09: the same
    event was in two cards). Of its reasons the line says the one this person acts on first: the acknowledgement
    (the investigator), an overdue report, a report with no deadline yet, the PI's acknowledgement awaited."""
    events: dict[tuple[str, str], dict[str, Any]] = {}
    for a in unacked:
        e = events.setdefault((str(a.get("record") or ""), str(a.get("event") or "")), {"a": a})
        e["unacked"] = True
    for a in reports:
        e = events.setdefault((str(a.get("record") or ""), str(a.get("event") or "")), {"a": a})
        if a.get("party") == "no_clock" or not a.get("due"):
            e["noclock"] = True
        else:
            e.setdefault("overdue", []).append(a)
    out = []
    for (record, event), e in events.items():
        a = e["a"]
        href = f"/studies/{rs}/subjects/{record}"
        values: dict[str, Any] = {"r": record, "rs": rs, "term": str(a.get("ae_term") or "")}
        due = ""
        if e.get("unacked") and acknowledges:
            kind = "sae_ack"
        elif e.get("overdue"):
            kind = "sae_overdue"
            due = min(str(x.get("due") or "") for x in e["overdue"])
            values["day"] = due
        elif e.get("noclock"):
            kind = "sae_noclock"
        else:
            kind = "sae_wait_pi"
        out.append(TodayLine(kind, rs, href, SAFETY, due, f"{record}/{event}", values))
    return out


def visit_lines(rs: str, overdue: int, today_n: int, day: date) -> list[TodayLine]:
    """One line per study for its overdue visits and one for today's (the visits page lists them one by one)."""
    out = []
    if overdue:
        out.append(TodayLine("visits_overdue", rs, f"/studies/{rs}/visits", OVERDUE, "", "overdue",
                             {"rs": rs, "n": overdue}))  # fmt: skip
    if today_n:
        out.append(TodayLine("visits_today", rs, f"/studies/{rs}/visits", TODAY, day.isoformat(), "today",
                             {"rs": rs, "n": today_n}))  # fmt: skip
    return out


#: the home's tasks (``home.study_card``) that are this page's lines; "approve" is the investigator's step and is
#: the study's Next line
TASK_KINDS = ("site", "call", "info", "prepare", "refer", "delegation")


def task_lines(tasks: Iterable[Mapping[str, Any]], today: date) -> list[TodayLine]:
    """The study tasks due today or before (a task not due yet is not today's)."""
    out = []
    for tk in tasks:
        due = tk.get("due")
        if tk.get("kind") not in TASK_KINDS or not isinstance(due, date) or due > today:
            continue
        rank = OVERDUE if due < today else TODAY
        out.append(TodayLine(str(tk["kind"]), str(tk["rs"]), str(tk["href"]), rank, due.isoformat(),
                             str(tk.get("short") or ""), {"p": tk.get("short") or "", "rs": tk["rs"]}))  # fmt: skip
    return out


def ordered(lines: Iterable[TodayLine]) -> list[TodayLine]:
    """Safety clocks first, then overdue, then due today; within one, the oldest due day first, then the study and
    the line; each thing once (the first of two lines about the same thing is kept)."""
    seen: set[tuple[str, str, str]] = set()
    out = []
    for ln in sorted(lines, key=lambda x: (x.rank, x.due or "9999-12-31", x.rs, KINDS.index(x.kind), x.what)):
        if ln.ident in seen:
            continue
        seen.add(ln.ident)
        out.append(ln)
    return out


def mark_in_today(nexts: Iterable[NextLine], lines: Iterable[TodayLine]) -> None:
    """A Next line whose page is already a line of "Needs you today" keeps its sentence and points to the block: the
    page is linked once."""
    hrefs = {ln.href.split("#")[0] for ln in lines}
    for n in nexts:
        if n.href and n.href.split("#")[0] in hrefs:
            n.in_today, n.href = True, ""


__all__ = [
    "FLAG",
    "KINDS",
    "LIMIT",
    "NEXT_KEYS",
    "OWNER",
    "ROLES",
    "STEPS",
    "NextLine",
    "TodayLine",
    "flag_now",
    "flag_on",
    "href_of",
    "life_step",
    "mark_in_today",
    "next_line",
    "ordered",
    "report_step",
    "sae_lines",
    "task_lines",
    "visit_lines",
]
