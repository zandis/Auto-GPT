"""Advisory reading of the time expressions in a criterion line (standard library only).

``parse_windows`` returns every temporal expression of a line, durations included, each with its value and unit as
written (a range is ``(low, high)``), its anchor, its kind (``window``, ``duration``, ``none`` or ``unparsed``) and
its place in the line. A line the rules do not fully understand carries an expression that is not ``high_confidence``,
and ``advise`` says nothing about it.

``advise`` compares what the line says with the windows the extraction put on the atoms and returns one ``Advice`` for
each difference: a window of the line the extraction gives differently or lacks, an anchor that is not the run's
date, a clause whose atom cannot be told. A window the extraction has and the line does not say gets no advice (the
stand-in extractions put one on every "latest" lab and on a second atom of "X within a year without Y"). It is
advisory only: it never changes the logic it is given, never decides anything, and what it returns is for the
criteria reviewer (``say`` words it in English, Japanese and Traditional Chinese, both windows side by side).

Units are kept as written; 1 week = 7 d, 1 month = 30 d, 1 year = 365 d only when a window becomes days. A bare "N days
ago" is an offset ("exact"), not a lookback; an explicit day or week count is compared exactly, and only a month or
year, which have no fixed length in days, is compared with a small tolerance. An unbounded window has no value and no
unit, never an invented zero.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from typing import Any

#: anchors that are the patient's entry into the study: evaluated from the index date, as ``randomization`` is
INDEX_LIKE = frozenset({"screening", "randomization", "enrollment", "consent"})
#: anchors that are the study's own dosing or end: not a date at pre-screening, so no index-relative form exists
HELD = frozenset({"first_dose", "last_dose", "end_of_study"})
DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


@dataclass(frozen=True)
class Result:
    win_val: Any = None
    win_unit: str = ""
    anchor: str = ""
    kind: str = "none"
    relation: str = ""
    evidence: str = ""
    high_confidence: bool = True
    reason: str = ""
    #: "within", "less_than" (strict), "at_least" or "more_than" (strict: a minimum distance), "exact", or "course"
    #: (a state lasting N up to the anchor: "no drugs for at least 12 weeks prior to consent"); empty for a duration
    bound: str = ""
    implicit: bool = False  # no event is named ("in the past 3 months", "2 years ago"): counted from the run's date
    span: tuple[int, int] = (-1, -1)  # where the amount stands in the lowercased line (``_norm``); -1: not in the line

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ONES = {
    w: n
    for n, w in enumerate(
        [
            *[
                "zero",
                "one",
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
                "ten",
                "eleven",
                "twelve",
            ],
            *["thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"],
        ]
    )
}
_TENS = {
    w: n
    for n, w in zip(
        range(20, 100, 10), ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"], strict=True
    )
}
_WORD = "(?:" + "|".join([*_ONES, *_TENS, "hundred"]) + ")"
_NUM = rf"(?:\d+(?:\.\d+)?|{_WORD}(?:[ -]+(?:and[ -]+)?{_WORD})*)"
_UNIT = r"(?:minutes?|mins?|hours?|hrs?|heures|days?|weeks?|wks?|months?|mos?|years?|yrs?|d|h|wk|mo|yr)"
_AMOUNT = re.compile(
    rf"(?<![\w.])(?P<a>{_NUM})(?:\s*\(\s*\d+(?:\.\d+)?\s*\))?(?:\s*(?:-|–|—|to)\s*(?P<b>{_NUM}))?[ -]*"
    rf"(?:consecutive\s+)?(?P<u>{_UNIT})\b",
    re.IGNORECASE,
)
_BETWEEN = re.compile(rf"\bbetween\s+(?P<a>{_NUM})\s+and\s+(?P<b>{_NUM})\s+(?P<u>{_UNIT})\b", re.IGNORECASE)
_IMPLICIT = re.compile(rf"\b(?P<p>last|past|previous|prior|next)\s+(?P<u>{_UNIT})\b", re.IGNORECASE)
_SINGULAR = re.compile(rf"\bthe\s+(?P<u>{_UNIT})\s+(?=prior to|before|after|preceding)")
_REL = re.compile(
    r"^\s*\)?\s*(?:\([^)]*\)\s*)?(?:or more\s+)?"
    r"(?P<r>before or after|prior\s+to|prior|before|after|following|since|from|of|preceding"
    r"|at(?!\s+(?:least|most)\b))\s+(?P<event>.+)"
)
_UNITS = {
    **dict.fromkeys(["minute", "minutes", "min", "mins"], "minute"),
    **dict.fromkeys(["hour", "hours", "hr", "hrs", "h", "heures"], "hour"),
    **dict.fromkeys(["day", "days", "d"], "day"),
    **dict.fromkeys(["week", "weeks", "wk", "wks"], "week"),
    **dict.fromkeys(["month", "months", "mo", "mos"], "month"),
    **dict.fromkeys(["year", "years", "yr", "yrs"], "year"),
}
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_STATE = re.compile(
    r"(?:stable (?:dose|doses|regimen)|dose is stable|postmenopausal|no menses|no menstruation|free from menses|"
    r"smoker|symptoms|suffering from|unchanged administration|minimum duration|life expectancy|expected survival|"
    r"total of)[^;,.]*$"
)
_ACTIVITY = re.compile(r"\b(?:complete|completed|chronic use)\b[^;,.]*$")
#: the comparator before the number, read whole: "no more than" is a "within", never a "more than" (the negated
#: forms are tried first, so the suffix of one is not read as the other)
_BOUNDS = [
    (re.compile(rf"(?:{words}|{signs})[ (]*(?:a |an )?$"), bound)
    for words, signs, bound in [
        (r"\b(?:no|not) (?:more|greater|longer) than|\bup to|\bat most|\bmaximum of", "<=", "within"),
        (r"\bat least|\b(?:no|not) (?:less|fewer|sooner|shorter) than|\bminimum(?: of)?", ">=", "at_least"),
        (r"\b(?:less|fewer|shorter) than", "<", "less_than"),
        (r"\b(?:more|greater|longer) than", ">", "more_than"),
    ]
]
_OR_MORE = re.compile(r"\s*(?:\([^)]*\)\s*)?or (?:more|longer)\b")
_EXACT = re.compile(r"(?:exactly|precisely)\s*$")
#: "for (at least) N" before a named date: how long a state lasted up to it, not a distance from it
_COURSE = re.compile(r"\bfor\s+(?:(?:at least|a minimum of|minimum of|(?:no|not) less than|more than|over)\s+)?$")
#: a signed negative amount ("-7 days", "−7 days"): no sure reading, a person reads it (D-914); the sign sits on
#: its digits, a spaced dash is a range ("6 months - 17 years")
_NEGATIVE = re.compile(r"(?:^|[\s(\[:=,;])-$")
_UNBOUNDED_FIRST_DOSE = r"\b(?:prior to|before|after|since)\s+(?:the )?first dose\b"
NEGATIVE = "A negative amount has no sure reading (D-914)"
ALTERNATIVE = "Alternative anchors in one window"
#: an event text that is no event name: a verb phrase cut short ("having received a single ...")
_NOT_EVENT = re.compile(r"^(?:having|being|been|receiving|received|taking|taken|undergoing|undergone|least|most)\b|^\d")
#: a window counted from the index disease or a prior event the line names elsewhere, not from screening
_INDEX_DISEASE = re.compile(r"\b(?:synchronous|metachronous|second primary|index (?:cancer|tumou?r|lesion))\b")
_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯]")


_KNOWN_ANCHORS = frozenset(
    ["screening", "consent", "randomization", "enrollment", "last_dose", "first_dose", "birth", "end_of_study", ""]
)


def _number(s: str) -> int | float:
    try:
        n = float(s)
    except ValueError:
        n = 0
        for w in re.split(r"[ -]+", s):
            if w == "hundred":
                n *= 100
            elif w != "and":
                n += _ONES.get(w, _TENS.get(w, 0))
    return int(n) if n == int(n) else n


def event_anchor(event: str) -> str:
    """Keep distinct event identities; baseline, Visit 1 and Day 1 are not turned into screening."""
    event = re.split(r"[;,.()]|\b(?:and|or|who|which|participants|patients|subjects)\b", event)[0].strip()
    event = re.sub(r"^(?:the |a |an )", "", event)
    patterns = [
        (r"^(?:study )?screening\b", "screening"),
        (r"^(?:the )?(?:signing (?:the )?)?informed consent\b|^consent\b", "consent"),
        (r"^(?:study )?randomi[sz]ation\b", "randomization"),
        (r"^(?:study |trial )?(?:enrol\w*|entry|entrance|registration|recruitment|inclusion)\b", "enrollment"),
        (r"^last (?:dose|dosing|administration)\b", "last_dose"),
        (r"^first (?:dose|dosing|administration)\b", "first_dose"),
        (
            r"^(?:(?:the )?start of (?:the )?|taking |scheduled |administration of )?"
            r"(?:study|trial) (?:drug administration|treatment|therapy)\b",
            "first_dose",
        ),
        (r"^(?:study )?day 1\b", "study_day_1"),
        (r"^(?:study )?visit 1\b", "visit_1"),
        (r"^baseline\b", "baseline"),
        (r"^(?:delivery|birth)\b", "birth"),
        (r"^(?:trial completion|end of (?:the )?study)\b", "end_of_study"),
    ]
    for pattern, anchor in patterns:
        if re.search(pattern, event):
            return anchor
    return event or "event"


def _alternatives(event: str) -> bool:
    """Whether the event phrase names a second study date beside the first ("screening or first dose"), which
    ``event_anchor`` would cut off."""
    head = re.split(r"[;,.()]", event)[0]
    return any(
        event_anchor(part) in (_KNOWN_ANCHORS - {""}) | {"study_day_1", "visit_1", "baseline"}
        for part in re.split(r"\b(?:and/or|or|and)\b", head)[1:]
    )


def _norm(text: str) -> str:
    return text.lower().replace("\\", "").replace("−", "-").replace("≥", ">=").replace("≤", "<=")


def parse_windows(text: str) -> list[Result]:
    s = _norm(text)
    if re.search(rf"half[ -]li(?:fe|ves)|\b(?:{_MONTHS})\s+\d", s):
        return [
            Result(
                kind="unparsed",
                evidence=text,
                high_confidence=False,
                reason="Half-life alternative or calendar interval needs a richer schema",
            )
        ]
    ranges = list(_BETWEEN.finditer(s))
    amounts = ranges + [m for m in _AMOUNT.finditer(s) if not any(r.start() <= m.start() < r.end() for r in ranges)]
    matches = [
        (m.start(), m.end(), _number(m["a"]), _number(m["b"]) if m["b"] else None, _UNITS[m["u"]], m.group())
        for m in amounts
    ]
    matches += [(m.start(), m.end(), 1, None, _UNITS[m["u"]], m.group()) for m in _IMPLICIT.finditer(s)]
    matches += [(m.start(), m.end(), 1, None, _UNITS[m["u"]], m.group()) for m in _SINGULAR.finditer(s)]
    matches.sort(key=lambda m: m[:2])
    out: list[Result] = []
    spans: list[tuple[int, int]] = []
    bare: list[bool] = []  # a window written only as "within N", whose anchor may be a later clause's
    for start, end, val, upper, unit, evidence in matches:
        before = s[max(0, start - 110) : start]
        after = s[end : end + 180]
        # Ages, frequency/rate denominators and counts of days within a lookback are values, not windows.
        if (
            re.match(r"\s*of age\b", after)
            or re.search(r"\b(?:aged?|ages)\s*$", before)
            or (re.match(r"\s*old\b", after) and not re.search(r"injury", before))
        ):
            continue
        if re.match(r"\s*(?:of\s+)?(?:padle\s+)?training per\b|\s*per\b", after):
            continue
        if re.match(r"\s+in (?:the )?(?:last|past|previous)\b", after):
            continue
        rel = _REL.match(after)
        lookback = bool(
            re.search(r"\b(?:within|last|past|previous|prior|preceding|next|recent)\s*(?:the\s+)?[ (<>=]*$", before)
            or evidence.split()[0] in ("last", "past", "previous", "prior", "next")
        )
        state = _STATE.search(before)
        activity_duration = (
            re.match(r"\s+(?:collection|treatment arm)\b", after)
            or (re.match(r"\s*\)?\s+of\b", after) and _ACTIVITY.search(before))
            or re.search(r"\b(?:diet and exercise control)\s+for\s+(?:at least\s+)?$", before)
        )
        if activity_duration or (state and not re.search(r"\b(?:within|over the past)\b[^;,.]*$", before)):
            kind, anchor, relation = "duration", "", "duration"
        elif rel:
            kind, anchor, relation = "window", event_anchor(rel["event"]), rel["r"]
        elif lookback or re.match(r"\s+ago\b", after):
            # the side is the word's: "next" ahead, "last", "past", "ago" ... back; a bare "within N" says neither,
            # and the rules do not pick one (a person does)
            cue = re.search(r"\b(within|last|past|previous|prior|preceding|next|recent)\s*(?:the\s+)?[ (<>=]*$", before)
            word = evidence.split()[0] if evidence.split()[0] in ("last", "past", "previous", "prior", "next") else ""
            word = word or (cue[1] if cue else "")
            kind, anchor = "window", "screening"
            relation = (
                "after"
                if word == "next"
                else "before"
                if word not in ("", "within") or re.match(r"\s+(?:ago|before|prior|earlier)\b", after)
                else ""
            )
        elif re.match(r"\s+thereafter\b", after) and re.search(r"\bdelivery\b[^.;]*$", before):
            kind, anchor, relation = "window", "birth", "after"
        elif re.search(r"\bfor\b[^;,.]*$", before) or re.match(r"\s+postmenopausal\b", after):
            kind, anchor, relation = "duration", "", "duration"
        elif re.search(r"\bprior to visit 1\b", s[:start]):
            kind, anchor, relation = "window", "visit_1", "before"
        elif re.search(r"(?:diagnos|embolism|injury|recent)", before) and re.search(r"[<>]=?\s*$", before):
            kind, anchor, relation = "window", "screening", "before"
        else:
            kind, anchor, relation = "unparsed", "", ""
        # Mixed-unit ranges: propagate the explicit right-hand event leftward.
        to_ = re.match(r"\s+to\s+", after)
        if kind == "unparsed" and to_:
            following = _AMOUNT.match(s, end + to_.end())
            if following and (r := _REL.match(s[following.end() :])):
                kind, anchor, relation = "window", event_anchor(r["event"]), "range_lower"
        uncertain = kind == "unparsed" or anchor in ("baseline", "visit_1", "study_day_1", "event")
        if kind == "window" and anchor not in _KNOWN_ANCHORS:  # free text: an event name, or a garbled phrase
            uncertain = uncertain or bool(
                _NOT_EVENT.match(anchor)
                or len(anchor.split()) > 5
                or re.search(r"\b(?:prior to|before|after)\b", anchor)
            )
        if kind == "window" and anchor == "screening" and not rel and _INDEX_DISEASE.search(before + after[:40]):
            uncertain = True
        reason = "Unresolved expression or study-event definition" if uncertain else ""
        if kind == "window" and rel and _alternatives(rel["event"]):
            uncertain, reason = True, ALTERNATIVE
        if _NEGATIVE.search(s[max(0, start - 2) : start]):
            uncertain, reason = True, NEGATIVE
        bound = ""
        if kind == "window":
            bound = next((b for pattern, b in _BOUNDS if pattern.search(before)), "within")
            if _EXACT.search(before):
                bound = "exact"
            elif rel and _COURSE.search(before):
                bound = "course"
            elif _OR_MORE.match(after):
                bound = "at_least"
            elif re.match(r"\s+ago\b", after) and not lookback and not any(p.search(before) for p, _ in _BOUNDS):
                bound = "exact"  # a bare "N days ago" is an offset, not "within N days" (W05)
        out.append(
            Result(
                (val, upper) if upper is not None else val,
                unit,
                anchor,
                kind,
                relation,
                evidence,
                not uncertain,
                reason,
                bound,
                kind == "window" and not rel and anchor == "screening" and relation != "range_lower",
                (start, end),
            )
        )
        spans.append((start, end))
        bare.append(kind == "window" and not rel and bool(re.search(r"\bwithin\s*(?:the\s+)?[ (<>=]*$", before)))
    # A bare "within 2 weeks" before a clause that names its event ("..., any other X within 4 weeks before
    # randomization") may share that event; which one is not the rules' to guess.
    named = [i for i, w in enumerate(out) if w.kind == "window" and w.anchor not in ("screening", "")]
    for i, w in enumerate(out):
        if bare[i] and w.kind == "window" and w.anchor == "screening" and any(j > i for j in named):
            gap = s[spans[i][1] : spans[max(j for j in named if j > i)][0]]
            if re.search(r"[,;]|\b(?:and|or)\b", gap) and not re.search(r"\bscreening\b", s[spans[i][1] :]):
                out[i] = replace(w, high_confidence=False, reason="Shared anchor of coordinated clauses")
    # an unbounded "prior to the first dose" in a clause of its own is read beside the numbers ("chemotherapy in the
    # past month and surgery prior to the first dose"), not only on a line that has none
    for fd in re.finditer(_UNBOUNDED_FIRST_DOSE, s):
        attached = (
            e <= fd.start() and re.fullmatch(r"[\s)]*(?:\([^)]*\)\s*)?(?:or more\s+)?", s[e : fd.start()])
            for _, e in spans
        )
        if not any(attached):
            out.append(Result(None, "", "first_dose", "window", "unbounded", fd.group()))
    if out:
        # A single temporal tuple cannot encode alternative anchors/arm scope.
        if re.search(r"\bfor arm\b|\bwhichever\b|\b(?:through|until|to the) (?:week|day)\s*\d", s):
            out.append(
                Result(
                    kind="unparsed",
                    evidence=text,
                    high_confidence=False,
                    reason="Conditional alternatives need clause/arm scope",
                )
            )
        return out
    if re.search(r"\bon the same day as\b", s):
        event = s.split("on the same day as", 1)[1]
        return [Result(0, "day", event_anchor(event), "window", "at", "on the same day as")]
    for pattern, anchor in [
        (r"\b(?:at|in) (?:the )?screening\b", "screening"),
        (r"\bduring (?:the )?study\b", "study"),
        (r"\bat any time\b", "any_time"),
    ]:
        if m := re.search(pattern, s):
            return [Result(None, "", anchor, "window", "at" if anchor == "screening" else "during", m.group())]
    if re.search(_UNBOUNDED_FIRST_DOSE, s):
        return [Result(None, "", "first_dose", "window", "unbounded", text)]
    if re.search(r"\b(?:within|since|until|baseline|visit \d|day\s*\+?\d|recently|postmenopausal|after|before)\b", s):
        return [
            Result(
                kind="unparsed",
                evidence=text,
                high_confidence=False,
                reason="Temporal cue without supported interval",
            )
        ]
    return [Result(evidence=text)]


def parse_window(text: str) -> Result:
    results = parse_windows(text)
    if len(results) == 1:
        return results[0]
    return Result(
        kind="unparsed", evidence=text, high_confidence=False, reason="Multiple expressions; use parse_windows"
    )


def reads_text(text: str) -> bool:
    """The rules read English (and French "heures"); a line with Chinese, Japanese or Korean script is not theirs."""
    return _CJK.search(text) is None


# ---------------------------------------------------------------------------------------- the line, in whole days
def _days(r: Result) -> tuple[int, ...] | None:
    """The rule's number or range in whole days, or None when the unit has no whole-day form (minutes, odd hours)."""
    vals = r.win_val if isinstance(r.win_val, tuple) else (r.win_val,)
    out: list[int] = []
    for v in vals:
        if r.win_unit not in DAYS or v * DAYS[r.win_unit] != int(v * DAYS[r.win_unit]):
            return None  # minutes and hours have no whole-day form
        out.append(int(v * DAYS[r.win_unit]))
    return tuple(out)


def _signed(r: Result, vals: tuple[Any, ...]) -> tuple[Any, Any] | None:
    """The rule's window on its side of the anchor, in the unit of ``vals``; None when the line gives no side or the
    window has an open future end (no form in the IR window). A strict bound is one unit inside the inclusive one."""
    side = -1 if r.relation in ("before", "prior to", "prior", "preceding") else 0
    side = side or (1 if r.relation in ("after", "following", "since") else 0)
    if not side:
        return None
    if len(vals) == 2:
        lo, hi = sorted(vals)
        return (-hi, -lo) if side < 0 else (lo, hi)
    n = vals[0]
    if r.bound == "exact":
        return (side * n, side * n)
    if r.bound in ("at_least", "more_than"):
        n += r.bound == "more_than"
        return (None, -n) if side < 0 else None
    n -= r.bound == "less_than"
    return (-n, 0) if side < 0 else (0, n)  # within, or a course lasting up to the anchor


def interval(r: Result) -> tuple[int | None, int | None] | None:
    """``(from_days, to_days)`` of the rule's window relative to its anchor, or None when the line does not say which
    side of the anchor ("within 28 days of ...", a bare "within 1 month"), the unit has no whole-day form, or the
    window is an exact offset or a course ("for at least 12 weeks prior to ..."), which a window does not encode."""
    days = _days(r)
    if days is None or r.bound in ("exact", "course"):
        return None
    return _signed(r, days)


def _scaled(r: Result) -> tuple[tuple[Any, ...], int] | None:
    """The rule's number(s) in the unit it is compared in (days; hours or minutes when the line counts in them) and
    the factor that turns an atom's days into that unit; None for no number."""
    vals = r.win_val if isinstance(r.win_val, tuple) else (r.win_val,)
    if r.win_unit in DAYS:
        return tuple(v * DAYS[r.win_unit] for v in vals), 1
    return (vals, {"hour": 24, "minute": 1440}[r.win_unit]) if r.win_unit in ("hour", "minute") else None


def _near(a: float | None, b: float | None, loose: bool) -> bool:
    """Two counts, or two open ends, that are one length. A count of days, weeks or hours the line gives is compared
    exactly (W06: "<7 days ago" is not [-7, 0]); only a month or a year, which have no fixed length in days ("12
    months" is 360 by the 30-day month and a year by 365), is within 2 % (and a day)."""
    if a is None or b is None:
        return a is b
    return abs(a - b) <= (max(1, 0.02 * max(abs(a), abs(b))) if loose else 1e-6)


def _same_lengths(pair: tuple[Any, Any], vals: tuple[Any, ...], loose: bool) -> bool:
    """The atom's window and the line give the same lengths, whichever side of the anchor each is on."""
    got = sorted({abs(x) for x in pair if x})
    return len(got) == len(vals) and all(_near(g, w, loose) for g, w in zip(got, sorted(vals), strict=True))


def _fits(pair: tuple[float | None, float | None], r: Result) -> bool | None:
    """Whether the atom's window (days) is the rule's, compared in the line's own unit (96 hours is not two days): both
    signed ends when the line gives a side of an entry anchor, the stated distance on both ends for an exact offset,
    else the lengths. None when the rule has no number to compare."""
    scaled = _scaled(r)
    if scaled is None:
        return None
    vals, factor = scaled
    loose = r.win_unit in ("month", "year")
    got = (None if pair[0] is None else pair[0] * factor, None if pair[1] is None else pair[1] * factor)
    signed = _signed(r, vals) if r.anchor in INDEX_LIKE else None  # a named event's side is not the index date's
    if signed is not None:
        return _near(got[0], signed[0], loose) and _near(got[1], signed[1], loose)
    if r.bound == "exact":
        return None not in got and _near(got[0], got[1], loose) and _near(abs(got[0] or 0), vals[0], loose)
    return _same_lengths(got, vals, loose)


def _pair(w: dict[str, Any]) -> tuple[float | None, float | None]:
    """The extraction window's ends in days (``unit: h`` counts them in hours)."""
    k = 24 if w.get("unit") == "h" else 1
    lo, hi = (None if w.get(e) is None else round(w[e] / k, 6) for e in ("from_days", "to_days"))
    return lo, hi


def _atoms(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict) and "domain" in node:
        return [node]
    if isinstance(node, dict):
        return [a for arg in node.get("args") or [] for a in _atoms(arg)]
    return []


def _stems(text: str) -> set[str]:
    words = {w for w in re.findall(r"[a-z]{4,}", text.lower())} - {
        "study",
        "trial",
        "protocol",
        "first",
        "last",
        "date",
    }
    return {w[:5] for w in words}


def _own_event(anchor: str, atoms: list[dict[str, Any]]) -> bool:
    """The named event is what an atom itself is about ("within 6 months of surgery" on the surgery atom), so the
    window counted from the index date is the line's window; otherwise it is counted from another event."""
    mine = _stems(anchor)
    return any(mine & _stems(str(a.get("concept") or "")) for a in atoms)


_SEP = re.compile(r"[;,]|\b(?:and|or)\b")


def _owners(s: str, ws: list[Result], k: int, atoms: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The atoms clause ``k`` of the line (its window ``ws[k]``) is about, by the words of the clause: the text before
    the window back to the previous clause, else the text after it. A criterion of one atom needs no words. None when
    the line does not tell (the clause names no atom's concept)."""
    if len(atoms) == 1:
        return atoms
    st, en = ws[k].span
    lo = ws[k - 1].span[1] if k else 0
    if k and (m := _SEP.search(s, lo, st)):
        lo = m.end()
    nxt = ws[k + 1].span[0] if k + 1 < len(ws) else len(s)
    after = _SEP.search(s, en, nxt)
    for part in (s[lo:st], s[after.end() : nxt] if after else ""):
        words = _stems(part)
        if owners := [a for a in atoms if words & _stems(str(a.get("concept") or ""))]:
            return owners
    return None


# ------------------------------------------------------------------------------------------------------ the advice
@dataclass(frozen=True)
class Shown:
    """A window as the reviewer reads it: its ends (``None``: open) in ``unit`` counted from ``anchor``; or, when the
    line does not say which side of the anchor, only its ``length``; or, with no ``unit``, no window. ``who`` names
    the atom's concept."""

    lo: float | None = None
    hi: float | None = None
    unit: str = ""
    anchor: str = ""
    length: tuple[Any, ...] | None = None
    who: str = ""


@dataclass(frozen=True)
class Advice:
    """One difference between a line and the extraction, for the criteria reviewer. ``stated`` is what the line says
    (None: nothing about a window) and ``extracted`` what the atoms concerned have. ``unclear``: the line does not say
    which atom the window is for, so every atom's window is listed."""

    stated: Shown | None
    extracted: tuple[Shown, ...]
    unclear: bool = False


def _n(x: float | None) -> float | None:
    return int(x) if x is not None and x == int(x) else x


def _stated(r: Result) -> Shown:
    scaled = _scaled(r)
    unit = r.win_unit if r.win_unit in ("hour", "minute") else "day"
    vals = scaled[0] if scaled else ()
    signed = _signed(r, vals) if scaled else None
    if signed is None:
        return Shown(None, None, unit, r.anchor, tuple(_n(v) for v in vals))
    return Shown(_n(signed[0]), _n(signed[1]), unit, r.anchor)


def _extracted(a: dict[str, Any], r: Result | None = None) -> Shown:
    """The atom's window in the unit the line counts in; a ``Shown`` with no unit when the atom has none."""
    who = str(a.get("concept") or "")
    w = a.get("window")
    if not w:
        return Shown(who=who)
    scaled = _scaled(r) if r is not None else None
    factor = scaled[1] if scaled else 1
    unit = r.win_unit if r is not None and r.win_unit in ("hour", "minute") else "day"
    lo, hi = _pair(w)
    return Shown(
        _n(None if lo is None else lo * factor),
        _n(None if hi is None else hi * factor),
        unit,
        str(w.get("anchor_text") or w.get("anchor") or "index"),
        who=who,
    )


def _norm_anchor(x: Any) -> Any:
    return "screening" if x in (None, "index") else x


def _agrees(a: dict[str, Any], r: Result, owners: list[dict[str, Any]]) -> bool:
    """The atom's window is the line's: the same ends and the same anchor (W02: ``randomization`` is not the index
    date, only ``screening`` is), a window counted from a named event only on the atom that event is."""
    w = a.get("window")
    if not w:
        return False
    if r.anchor in INDEX_LIKE or r.anchor in HELD:
        if _norm_anchor(w.get("anchor")) != _norm_anchor(r.anchor):
            return False
    elif not _own_event(r.anchor, owners):
        return False
    return _fits(_pair(w), r) is not False


def advise(text: str, logic: Any) -> list[Advice]:
    """What the criteria reviewer should look at: where the line's time windows and the extraction's differ. Nothing
    is changed, dropped or decided; ``logic`` is only read. A line the rules do not fully read, or in a script they do
    not read, gets no advice."""
    if not text or not reads_text(text):
        return []
    res = parse_windows(text)
    if not all(r.high_confidence and r.kind != "unparsed" for r in res):
        return []
    atoms = [a for a in _atoms(logic) if a.get("domain") != "demographic" and not a.get("duration")]
    windowed = tuple(_extracted(a) for a in atoms if a.get("window"))
    wins = [r for r in res if r.kind == "window"]
    if not wins:  # a line with no window of its own says nothing: the stand-in extractions put a recency window on
        return []  # every "latest" lab and on pregnancy, which the prompt does not ask for, and that is not told here
    out = [  # "prior to the first dose" has no number, and no window of the extraction's counts from the first dose
        Advice(Shown(None, None, "day", r.anchor), windowed)
        for r in wins
        if r.win_val is None and r.anchor in HELD and windowed
    ]
    s = _norm(text)
    ws = [r for r in wins if r.win_val is not None and r.span[0] >= 0]
    for k, r in enumerate(ws):
        owners = _owners(s, ws, k, atoms)
        if owners is None:  # W03/W04: which atom the clause is for is not said
            if len(atoms) > 1 and not all(_agrees(a, r, atoms) for a in atoms):
                out.append(Advice(_stated(r), tuple(_extracted(a, r) for a in atoms), True))
            continue
        for a in owners:
            if not _agrees(a, r, owners):
                out.append(Advice(_stated(r), (_extracted(a, r),)))
    return out


# -------------------------------------------------------------------------------------------- the reviewer's words
_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "head": "the line and the extracted time window differ; check it",
        "line": "the line says",
        "got": "extracted",
        "nothing": "no time window",
        "from": "counted from",
        "side": "before or after not said",
        "unclear": "the line does not say which item each window is for",
        "day": "days",
        "hour": "hours",
        "minute": "minutes",
        "colon": ": ",
        "stop": ". ",
    },
    "ja": {
        "head": "条文と抽出された期間が一致しません。確認してください",
        "line": "条文",
        "got": "抽出",
        "nothing": "期間なし",
        "from": "起点",
        "side": "前後の記載なし",
        "unclear": "どの項目の期間か条文からは分かりません",
        "day": "日",
        "hour": "時間",
        "minute": "分",
        "colon": "：",
        "stop": "。",
    },
    "zh-TW": {
        "head": "條文與擷取的時間範圍不一致，請確認",
        "line": "條文",
        "got": "擷取",
        "nothing": "無時間範圍",
        "from": "起點",
        "side": "未說明之前或之後",
        "unclear": "條文未說明各時間範圍屬於哪一項",
        "day": "天",
        "hour": "小時",
        "minute": "分鐘",
        "colon": "：",
        "stop": "。",
    },
}
_ANCHORS = {
    "en": [
        "the index date",
        "screening",
        "randomization",
        "enrollment",
        "consent",
        "first dose",
        "last dose",
        "end of study",
    ],
    "ja": ["基準日", "スクリーニング", "無作為化", "登録", "同意取得", "初回投与", "最終投与", "試験終了"],
    "zh-TW": ["基準日", "篩選", "隨機分派", "收案", "取得同意", "首次給藥", "最後給藥", "試驗結束"],
}
_ANCHOR_KEYS = [
    "index",
    "screening",
    "randomization",
    "enrollment",
    "consent",
    "first_dose",
    "last_dose",
    "end_of_study",
]
LANGS = tuple(_WORDS)


def _show(sh: Shown | None, lang: str) -> str:
    w = _WORDS[lang]
    if sh is None or not sh.unit:
        text = w["nothing"]
    else:
        key = sh.anchor or "index"
        anchor = _ANCHORS[lang][_ANCHOR_KEYS.index(key)] if key in _ANCHOR_KEYS else sh.anchor.replace("_", " ")
        if sh.length is not None:
            span = "-".join(str(v) for v in sh.length)
            text = f"{span} {w[sh.unit]} ({w['side']}; {w['from']}{w['colon']}{anchor})"
        else:
            lo = "-∞" if sh.lo is None else sh.lo
            hi = "+∞" if sh.hi is None else sh.hi
            text = f"[{lo} .. {hi}] {w[sh.unit]} ({w['from']}{w['colon']}{anchor})"
    return f"{sh.who}{w['colon']}{text}" if sh is not None and sh.who else text


def say(cid: str, advice: Advice) -> str:
    """The reviewer's sentence, in English, Japanese and Traditional Chinese, the line's window and the extraction's
    side by side (``warnings`` of the review has one line of text per item, so the three share it)."""
    parts = []
    for lang in LANGS:
        w = _WORDS[lang]
        got = "; ".join(_show(e, lang) for e in advice.extracted)
        unclear = f"{w['unclear']}{w['stop']}" if advice.unclear else ""
        parts.append(
            f"{w['head']}{w['stop']}{unclear}{w['line']}{w['colon']}{_show(advice.stated, lang)}{w['stop']}"
            f"{w['got']}{w['colon']}{got}"
        )
    return f"{cid}: " + " | ".join(parts)
