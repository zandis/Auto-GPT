"""ERASE-A2 (D-875, the owner's D-532): the screening log keeps its rows, not the patient.

A never-consented patient who opts out keeps every screening-log row and its number (D-762: the numbered row stays,
and a deleted number would be given again to the next patient), and the rows lose the pseudonym: in each study the
patient's rows in ``site.screening_no``, ``site.weekly_seen``, ``site.pi_marks``, ``orch.candidates`` and
``orch.candidate_events`` take one random token (:func:`tb_common.optout.erased_token`, with the site's day of the
opt-out, which the log shows), and the free text goes (the PI's note, the registry's reasons).

A trial subject's rows stay (OD-8), per study, erring toward keeping (the definition of D-532). A study is a trial
study of a patient when any of these shows consent for the patient or a chart merged with theirs (``pid_alias``,
both ways) or one of their screening numbers in it:

* the registry: a candidate now, or ever (an event's status or previous), ``consented`` or ``enrolled``;
* the lifecycle: a subject in a consenting state, or any step that reached one (undone ones included);
* the consent forms: an ``ic_date`` or ``ic_reconsent_date`` in the values or their history;
* REDCap's read-back: a consent date, or ``consented``/``enrolled``/``withdrawn`` (``screen_fail`` too when the
  link reads no consent field), or a number of the patient not read back yet while the link is on;
* the EDC: any draft (drafts exist only for visit data).

Any source that exists and cannot be read raises: nothing is tokenized in that tick. Counts only, never who."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime
from typing import Any

from tb_common.optout import erased_token

#: the registry statuses that mean consent was given (a later ``withdrawn`` or ``screen_fail`` needs the history)
REGISTRY_CONSENT = ("consented", "enrolled")
#: the lifecycle states that mean consent was given (``withdrawn`` is reachable only after it)
LIFE_CONSENT = ("consented", "enrolled", "on_study", "completed", "withdrawn")
RC_CONSENT = ("consented", "enrolled", "withdrawn")
IC_FIELDS = ("ic_date", "ic_reconsent_date")

#: (schema, table, the count of the patients' rows by study, the update that gives one study's rows of one patient
#: the token): written out, no SQL is put together
TOKENED: tuple[tuple[str, str, str, str], ...] = (
    ("site", "screening_no", "SELECT ruleset, pid, count(*) FROM screening_no WHERE pid = ANY(?) GROUP BY 1, 2",
     "UPDATE screening_no SET pid = ? WHERE ruleset = ? AND pid = ?"),
    ("site", "weekly_seen", "SELECT ruleset, pid, count(*) FROM weekly_seen WHERE pid = ANY(?) GROUP BY 1, 2",
     "UPDATE weekly_seen SET pid = ? WHERE ruleset = ? AND pid = ?"),
    ("site", "pi_marks", "SELECT ruleset, pid, count(*) FROM pi_marks WHERE pid = ANY(?) GROUP BY 1, 2",
     "UPDATE pi_marks SET pid = ?, note = NULL WHERE ruleset = ? AND pid = ?"),
    ("orch", "candidates", "SELECT ruleset, pid, count(*) FROM candidates WHERE pid = ANY(?) GROUP BY 1, 2",
     "UPDATE candidates SET pid = ?, reason = NULL WHERE ruleset = ? AND pid = ?"),
    ("orch", "candidate_events", "SELECT ruleset, pid, count(*) FROM candidate_events WHERE pid = ANY(?) GROUP BY 1, 2",
     "UPDATE candidate_events SET pid = ?, reason = NULL WHERE ruleset = ? AND pid = ?"),
    # the review of D-875: the lifecycle's subject of the number keeps its row (and its state); its pseudonym takes the
    # log's token, or the kept number would join the token back to the patient, and the lifecycle's refresh would put
    # the patient back on the registry under the pseudonym (a subject whose pseudonym the registry no longer has)
    ("datacore", "subject", "SELECT study, pid, count(*) FROM subject WHERE pid = ANY(?) GROUP BY 1, 2",
     "UPDATE subject SET pid = ? WHERE study = ? AND pid = ?"),
)  # fmt: skip
#: an open candidate is withdrawn first (the ``candidate_registry`` clear, earlier in the tick): until then it stays
OPEN = ("candidate", "contacted")

Has = Callable[[str, str], bool]
Open = Callable[[str], Any]


def _classes(pids: frozenset[str], has: Has, open_: Open) -> list[frozenset[str]]:
    """The merge classes of ``pids``: each with every pseudonym a chart merge joined to it, both ways, chains
    followed (one person's charts; the register follows a merge from the old chart only, D-477)."""
    edges: list[tuple[str, str]] = []
    if has("pidmap", "pid_alias"):
        with open_("pidmap") as db:
            edges = [(str(a), str(b)) for a, b in db.fetchall("SELECT old_pid, pid FROM pid_alias")]
    near: dict[str, set[str]] = {}
    for a, b in edges:
        near.setdefault(a, set()).add(b)
        near.setdefault(b, set()).add(a)
    out: list[frozenset[str]] = []
    done: set[str] = set()
    for p in sorted(pids):
        if p in done:
            continue
        seen, todo = {p}, [p]
        while todo:
            for q in near.get(todo.pop(), ()):
                if q not in seen:
                    seen.add(q)
                    todo.append(q)
        done |= seen
        out.append(frozenset(seen))
    return out


def _rows(pids: list[str], has: Has, open_: Open) -> dict[tuple[str, str], int]:
    """(study, pseudonym) -> how many rows of the tokened tables hold it."""
    out: dict[tuple[str, str], int] = {}
    for schema, table, count, _upd in TOKENED:
        if not pids or not has(schema, table):
            continue
        with open_(schema) as db:
            for rs, pid, n in db.fetchall(count, (pids,)):
                out[(str(rs), str(pid))] = out.get((str(rs), str(pid)), 0) + int(n)
    return out


def _any(db: Any, sql: str, params: tuple[Any, ...]) -> bool:
    return db.fetchone(sql, params) is not None


def _trial(study: str, people: list[str], has: Has, open_: Open) -> bool:
    """Whether any source shows consent in ``study`` for one of ``people`` (a merge class): errs toward keeping. A
    screening number is compared as the lifecycle keys it (upper case; the review of D-875: a study's prefix is free
    text)."""
    nums: list[str] = []
    if has("site", "screening_no"):
        with open_("site") as db:
            nums = sorted({str(r[0]).strip().upper() for r in db.fetchall(
                "SELECT no FROM screening_no WHERE ruleset = ? AND pid = ANY(?)", (study, people))})  # fmt: skip
    if has("orch", "candidates"):
        with open_("orch") as db:
            if _any(db, "SELECT 1 FROM candidates WHERE ruleset = ? AND pid = ANY(?) AND status = ANY(?)",
                    (study, people, list(REGISTRY_CONSENT))):  # fmt: skip
                return True
    if has("orch", "candidate_events"):
        with open_("orch") as db:
            if _any(db, "SELECT 1 FROM candidate_events WHERE ruleset = ? AND pid = ANY(?) AND (status = ANY(?) OR "
                    "previous = ANY(?))", (study, people, list(REGISTRY_CONSENT), list(REGISTRY_CONSENT))):  # fmt: skip
                return True
    records = set(nums) | {p.upper() for p in people}
    if has("datacore", "subject"):
        with open_("datacore") as db:
            for rec, state in db.fetchall(
                "SELECT record, state FROM subject WHERE study = ? AND (pid = ANY(?) OR upper(record) = ANY(?))",
                (study, people, sorted(records)),
            ):
                records.add(str(rec).strip().upper())
                if str(state) in LIFE_CONSENT:
                    return True
    recs = sorted(records)
    if has("datacore", "subject_step"):
        with open_("datacore") as db:
            if _any(db, "SELECT 1 FROM subject_step WHERE study = ? AND upper(record) = ANY(?) AND (new = ANY(?) OR "
                    "old = ANY(?))", (study, recs, list(LIFE_CONSENT), list(LIFE_CONSENT))):  # fmt: skip
                return True
    if has("datacore", "value"):
        with open_("datacore") as db:
            if _any(db, "SELECT 1 FROM value WHERE study = ? AND upper(record) = ANY(?) AND field = ANY(?) AND "
                    "value <> ''", (study, recs, list(IC_FIELDS))):  # fmt: skip
                return True
    if has("datacore", "history"):
        with open_("datacore") as db:
            if _any(db, "SELECT 1 FROM history WHERE study = ? AND upper(record) = ANY(?) AND field = ANY(?) AND "
                    "(new <> '' OR COALESCE(old, '') <> '')", (study, recs, list(IC_FIELDS))):  # fmt: skip
                return True
    if has("study", "rc_record"):
        with open_("study") as db:
            link = db.fetchone("SELECT body, enabled FROM rc_project_link WHERE ruleset = ?", (study,)) \
                if has("study", "rc_project_link") else None  # fmt: skip
            consent_field = str(json.loads(link[0]).get("consent_field") or "") if link is not None else ""
            reads = db.fetchall(
                "SELECT link_value, status, consent_date FROM rc_record WHERE ruleset = ? AND (pid = ANY(?) OR "
                "upper(link_value) = ANY(?))", (study, people, nums))  # fmt: skip
            for _lv, status, day in reads:
                if str(day or "").strip() or str(status or "") in RC_CONSENT:
                    return True
                if str(status or "") == "screen_fail" and not consent_field:
                    return True
            if link is not None and int(link[1] or 0) and set(nums) - {str(r[0]).strip().upper() for r in reads}:
                return True  # a number not read back yet while the link is on: unknown, so kept
    if has("edc", "draft"):
        with open_("edc") as db:
            if _any(db, "SELECT 1 FROM draft WHERE study = ? AND (pid = ANY(?) OR upper(record) = ANY(?))",
                    (study, people, recs)):  # fmt: skip
                return True
    return False


#: one study's rows of one person (a merge class): the pseudonyms that hold them and the count
Pair = tuple[str, frozenset[str]]


def plan(pids: frozenset[str], has: Has, open_: Open) -> tuple[dict[Pair, tuple[list[str], int]], int]:
    """Per study and person (the opted-out pseudonyms with their merged charts), the pseudonyms whose rows take one
    token and how many rows; and how many stay (a trial subject's, or an open candidate not withdrawn yet)."""
    classes = _classes(pids, has, open_)
    rows = _rows(sorted(set().union(*classes)) if classes else [], has, open_)
    if not rows:
        return {}, 0
    out: dict[Pair, tuple[list[str], int]] = {}
    kept = 0
    for people in classes:
        for study in sorted({rs for rs, p in rows if p in people}):
            holders = sorted(p for rs, p in rows if rs == study and p in people)
            if _held(study, sorted(people), has, open_) or _trial(study, sorted(people), has, open_):
                kept += 1
            else:
                out[(study, people)] = (holders, sum(rows[(study, p)] for p in holders))
    return out, kept


def _held(study: str, people: list[str], has: Has, open_: Open) -> bool:
    """An open candidate is withdrawn first (the ``candidate_registry`` clear): until then the rows stay."""
    if not has("orch", "candidates"):
        return False
    with open_("orch") as db:
        return _any(db, "SELECT 1 FROM candidates WHERE ruleset = ? AND pid = ANY(?) AND status = ANY(?)",
                    (study, people, list(OPEN)))  # fmt: skip


def opted_out_days(register: Any, pids: frozenset[str], now: datetime) -> dict[str, str]:
    """The site's day each pseudonym was opted out: the first opt-out since its last lift (as D-762's log reads it);
    none for the surviving chart of a merge, which has no opt-out event of its own."""
    first: dict[str, str] = {}
    for e in register.events():
        if e.pid not in pids:
            continue
        if e.action == "lift":
            first.pop(e.pid, None)
        elif e.action == "opt_out":
            first.setdefault(e.pid, e.at)
    out: dict[str, str] = {}
    for p, at in first.items():
        try:
            when = datetime.fromisoformat(at.replace("Z", "+00:00"))
            out[p] = (when.astimezone(now.tzinfo) if when.tzinfo and now.tzinfo else when).date().isoformat()
        except ValueError:
            continue
    return out


#: asked again under a lock before a person's rows take the token: a consent recorded since the plan keeps them
_RECHECK = "SELECT 1 FROM candidates WHERE ruleset = ? AND pid = ANY(?) AND status = ANY(?) FOR UPDATE"


def apply(todo: dict[Pair, tuple[list[str], int]], days: dict[str, str], has: Has, open_: Open) -> int:
    """Give each chart's rows in each study one token, a person's merged charts kept or tokened together; the rows
    changed."""
    if not todo:
        return 0
    stores = [(schema, [upd for s, t, _c, upd in TOKENED if s == schema and has(s, t)])
              for schema in ("site", "datacore", "orch")]  # fmt: skip
    n = 0
    # the stores in one go: a failure before the commits leaves them all as they were (the next tick plans again).
    # The commits run orchestrator, lifecycle, site; a failure between two leaves the rest to the next tick, with a
    # token of their own (a row then reads as an opted-out patient's with its registry status unknown, never who)
    with ExitStack() as stack:
        txs = {schema: (stack.enter_context(stack.enter_context(open_(schema)).transaction()), upds)
               for schema, upds in stores if upds}  # fmt: skip
        recheck = has("orch", "candidates") and "orch" in txs
        for (study, people), (holders, _n) in sorted(todo.items(), key=lambda x: (x[0][0], sorted(x[0][1]))):
            if recheck and txs["orch"][0].fetchone(_RECHECK, (study, sorted(people), [*REGISTRY_CONSENT, *OPEN])):
                continue
            day = next((days[p] for p in sorted(people) if days.get(p)), "")
            for pid in holders:  # a chart of its own keeps a token of its own (a study numbers each chart once)
                token = erased_token(day)
                for tx, upds in txs.values():
                    for upd in upds:
                        n += int(tx.execute(upd, (token, study, pid)) or 0)
    return n
