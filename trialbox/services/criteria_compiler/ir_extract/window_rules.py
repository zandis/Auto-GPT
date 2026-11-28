"""Deterministic reading of the time expressions in a criterion line (standard library only).

The first step of ``postprocess`` (OPT-1 W3): a window written in the line is read here, by rules, before the model's
window is trusted. ``parse_windows`` returns every temporal expression of a line, durations included, each with its
value and unit as written (a range is ``(low, high)``), its anchor and its kind (``window``, ``duration``, ``none`` or
``unparsed``). A line the rules do not fully understand carries an expression that is not ``high_confidence``, and
nothing in it is acted on. ``reconcile`` compares the confident reading with the windows the model put on the atoms:

* the line has one window the model's atoms lack or give differently: the rule's window wins when it has a form in
  days from the index date (``window_rules_override``), else the atom is left as it is and flagged
  (``window_disagrees``, ``window_unattached``);
* the line has no window (no time expression, or only durations such as "stable dose for 3 months"): the model's
  windows are left alone unless ``DROP_UNSTATED_WINDOWS`` is on, which drops them (``window_not_in_text``);
* the window is anchored on the study's own dosing or end (``first_dose``, ``last_dose``, ``end_of_study``): a date
  that does not exist at pre-screening, so the criterion is held for a person (``window_anchor_unsupported``).

Every change or disagreement flags the criterion ``needs_review`` (the caller's job). A line in a script the rules
do not read (Chinese, Japanese, Korean) is left alone.

Units are kept as written; 1 week = 7 d, 1 month = 30 d, 1 year = 365 d only when a window becomes days.
An unbounded window has no value and no unit, never an invented zero.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
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
    bound: str = ""  # "within" or "at_least" (a minimum distance); empty for a duration or no number

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
    r"(?P<r>before or after|prior\s+to|prior|before|after|following|since|from|of|preceding|at)\s+(?P<event>.+)"
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
_AT_LEAST = re.compile(
    r"(?:at least|no (?:less|fewer|sooner) than|not (?:less|fewer|sooner) than|more than|greater than"
    r"|minimum of|minimum|>=|>)[ (]*(?:a |an )?$"
)
_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯]")
_TIME_WORD = re.compile(
    rf"\b{_UNIT}\b|\b(?:recent|recently|annual|annually|daily|weekly|monthly|yearly|ever|currently|ago)\b|"
    r"\b(?:last|past|previous)\s+(?:dose|cycle|visit|line)",
    re.IGNORECASE,
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


def parse_windows(text: str) -> list[Result]:
    s = text.lower().replace("\\", "").replace("−", "-").replace("≥", ">=").replace("≤", "<=")
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
            kind, anchor = "window", "screening"
            relation = "after" if re.search(r"\bnext\b", before + evidence) else "before"
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
        bound = ""
        if kind == "window":
            bound = "at_least" if _AT_LEAST.search(before) else "within"
        out.append(
            Result(
                (val, upper) if upper is not None else val,
                unit,
                anchor,
                kind,
                relation,
                evidence,
                not uncertain,
                "Unresolved expression or study-event definition" if uncertain else "",
                bound,
            )
        )
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
    if re.search(r"\b(?:prior to|before|after|since)\s+(?:the )?first dose\b", s):
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


def has_time_word(text: str) -> bool:
    """Whether a line says anything about time at all (a unit, "recent", "ago", ...), in any of the scripts."""
    return _TIME_WORD.search(text) is not None or _CJK.search(text) is not None


# ------------------------------------------------------------------------------------------------ the model's windows
def _days(r: Result) -> tuple[int, ...] | None:
    """The rule's number or range in whole days, or None when the unit has no whole-day form (minutes, odd hours)."""
    vals = r.win_val if isinstance(r.win_val, tuple) else (r.win_val,)
    out: list[int] = []
    for v in vals:
        n = v / 24 if r.win_unit == "hour" else v * DAYS[r.win_unit] if r.win_unit in DAYS else None
        if n is None or n != int(n):
            return None
        out.append(int(n))
    return tuple(out)


def interval(r: Result) -> tuple[int | None, int | None] | None:
    """``(from_days, to_days)`` of the rule's window relative to its anchor, or None when the line does not say which
    side of the anchor ("within 28 days of ..."), or the unit has no whole-day form."""
    days = _days(r)
    if days is None:
        return None
    before = r.relation in ("before", "prior to", "prior", "preceding")
    after = r.relation in ("after", "following", "since")
    if not before and not after:
        return None
    if len(days) == 2:
        lo, hi = sorted(days)
        return (-hi, -lo) if before else (lo, hi)
    n = days[0]
    if r.bound == "at_least":
        return (None, -n) if before else (n, None)
    return (-n, 0) if before else (0, n)


def _near(a: int | None, b: int | None) -> bool:
    """Two day counts, or two open ends, that are one length: "12 months" is 360 days by the 30-day month and a year by
    the model's 365; within 2 % (and a day) is the same window."""
    if a is None or b is None:
        return a is b
    return abs(a - b) <= max(1, 0.02 * max(abs(a), abs(b)))


def _same(pair: tuple[int | None, int | None], iv: tuple[int | None, int | None]) -> bool:
    return _near(pair[0], iv[0]) and _near(pair[1], iv[1])


def _same_lengths(pair: tuple[int | None, int | None], days: tuple[int, ...]) -> bool:
    """The atom's window and the line give the same lengths, whichever side of the anchor each is on."""
    got = sorted(abs(x) for x in pair if x)
    return len(got) == len(days) and all(_near(g, w) for g, w in zip(got, sorted(days), strict=True))


def _window(iv: tuple[int | None, int | None]) -> dict[str, Any]:
    """The IR window of an interval; an open end is left out, as a dumped extraction leaves it."""
    return {k: v for k, v in (("from_days", iv[0]), ("to_days", iv[1])) if v is not None} | {"anchor": "index"}


def _atoms(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict) and "domain" in node:
        return [node]
    if isinstance(node, dict):
        return [a for arg in node.get("args") or [] for a in _atoms(arg)]
    return []


@dataclass
class Reconciled:
    logic: dict[str, Any]
    flags: list[str]
    hold: str | None = None  # the reason the criterion goes to a person, else None


#: A window the line never states is the model's own: the stand-in extractions put a recency window on every "latest"
#: lab and on pregnancy (-365, -180, -90, -280 days), which is not what the prompt asks for but is what the committed
#: rulesets were built from. ``True`` drops such a window (``window_not_in_text``) and refuses one on a line with no
#: word about time (``window_invented``, check (iii)); it changes those rulesets' regenerated output, so it waits for a
#: ruling (REPORT of W3).
DROP_UNSTATED_WINDOWS = False


def reconcile(text: str, logic: dict[str, Any], *, drop_unstated: bool = False) -> Reconciled:
    """Compare the line's windows with the model's. ``logic`` is changed in place (the caller owns a fresh dump)."""
    if not text or not reads_text(text):
        return Reconciled(logic, [])
    res = parse_windows(text)
    if not all(r.high_confidence and r.kind != "unparsed" for r in res):
        return Reconciled(logic, [])  # the rules abstain; the model's windows stand
    # an age or sex has no time limit; an atom with a duration reads "for at least 3 months" as a course inside its
    # window, which the rules do not (a duration in a window is the medication construct of ``semantics``)
    atoms = [a for a in _atoms(logic) if a.get("domain") != "demographic" and not a.get("duration")]
    windowed = [a for a in atoms if a.get("window")]
    if not any(r.kind == "window" for r in res):
        if not drop_unstated or (has_time_word(text) and not any(r.kind == "duration" for r in res)):
            return Reconciled(logic, [])  # or a time word the rules did not read ("in the preceding year")
        for a in windowed:  # a window the line does not say, or a duration ("stable dose for 3 months")
            del a["window"]
        return Reconciled(logic, ["window_not_in_text"] if windowed else [])
    wins = [r for r in res if r.kind == "window" and r.win_val is not None]
    held = next((r for r in wins if r.anchor in HELD), None)
    if held is not None:
        return Reconciled(
            logic,
            ["window_anchor_unsupported"],
            f"its window counts from the study's {held.anchor.replace('_', ' ')}, which is not a date before "
            "pre-screening",
        )
    flags: list[str] = []
    if len(wins) == 1:
        iv = interval(wins[0])
        days = _days(wins[0])
        can_write = iv is not None and wins[0].anchor in INDEX_LIKE
        if not windowed:
            if len(atoms) == 1 and can_write:
                atoms[0]["window"] = _window(iv)  # type: ignore[arg-type]
                flags.append("window_rules_override")
            elif days and atoms:
                flags.append("window_unattached")
            return Reconciled(logic, flags)
        for a in windowed:
            pair = (a["window"].get("from_days"), a["window"].get("to_days"))
            if not days or (_same(pair, iv) if iv is not None else _same_lengths(pair, days)):
                continue
            if can_write and len(windowed) == 1:  # with more atoms the line does not say which
                a["window"] = _window(iv)  # type: ignore[arg-type]
                flags.append("window_rules_override")
            else:
                flags.append("window_disagrees")
        return Reconciled(logic, sorted(set(flags)))
    lengths = [d for r in wins if (d := _days(r))]
    for a in windowed:
        pair = (a["window"].get("from_days"), a["window"].get("to_days"))
        if lengths and not any(_same_lengths(pair, d) for d in lengths):
            flags.append("window_disagrees")
    return Reconciled(logic, sorted(set(flags)))


def lint(text: str, logic: Any) -> str | None:
    """Compile check (iii) of OPT-1 §3 on an extracted criterion: no word about time in its line, yet an atom has a
    window, so the window was invented. Returns the refusal that names the line, or None. (iv) and (v) are in
    ``semantics.window``; this one runs only with ``DROP_UNSTATED_WINDOWS``."""
    if any(a.get("window") for a in _atoms(logic)) and not has_time_word(text):
        return f"a window on an atom, but its line says nothing about time: {text!r}"
    return None
