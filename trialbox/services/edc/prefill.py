"""Draft eCRF values for one subject and visit, each with its citation (D-160).

:func:`build` reads the subject's record through a :class:`Facts` source (the box's lake: the hospital feed and the
site's confirmed facts) and returns one :class:`Draft` per mapped item. The rules, each tested:

* **A value always has a citation.** A drafted value names the row it came from (table, row id, snapshot, day) or,
  for a note, the note and the verbatim quote; a quote not found in the note is dropped. No citation, no value.
* **Proposed facts never count.** A fact read from a chart that nobody confirmed (``site_fact`` basis ``proposed``
  or ``suspected``) is never the basis of a value; the item stays unknown with the reason ``only_proposed``.
* **Unknown never excludes.** No record means *unknown*, never "No": a ``presence`` item is drafted only as its yes
  code, and the absence of a diagnosis or a medicine leaves it blank for the coordinator.
* **Two records that disagree on the chosen day** leave the item unknown (``conflict``); TrialBox never picks one.
* **A code counts only under its code system** (D-598): a lab, vital sign or diagnosis row whose code is of another
  system than the item's, or of none, is not a record for the item, whatever its code reads.
* A value in another unit than the item's is not converted; it is skipped (``unit``). A censored result
  (``<0.3``) is never a value (``censored``). Every value is checked against the field (type, range, choice); a value
  that fails is not drafted (``invalid``).

A draft is never a value of the trial record: it becomes one only when a person confirms it and signs
(``edc.store``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from datacore.forms import Field, problem
from tb_common.quotes import quote_in

from edc.mapping import ItemMap, systems_of, unit_key

WHY = ("no_record", "only_proposed", "conflict", "unit", "censored", "invalid", "out_of_window", "quote_not_found",
       "not_mapped", "no_model")  # fmt: skip
NOTE_CHARS = 12_000  # note text sent to the model for one item, newest notes first


@dataclass
class Draft:
    item: str
    form: str
    cdash: str
    test: str
    value: str  # "" when unknown
    state: str  # drafted | unknown
    why: str = ""  # the reason it is unknown (WHY)
    citation: dict[str, Any] | None = None
    version: str = ""  # what drafted it: the snapshot, and the prompt version for a note

    def as_dict(self) -> dict[str, Any]:
        return {"item": self.item, "form": self.form, "cdash": self.cdash, "test": self.test, "value": self.value,
                "state": self.state, "why": self.why, "citation": self.citation, "version": self.version}  # fmt: skip


class Facts(Protocol):
    def snapshot(self) -> str: ...
    def patient(self, pid: str) -> dict[str, Any] | None: ...
    def rows(self, pid: str, source: str) -> list[dict[str, Any]]: ...
    def site_facts(self, pid: str) -> list[dict[str, Any]]: ...
    def notes(self, pid: str, until: date) -> list[dict[str, Any]]: ...


_SQL = {
    "observation": "SELECT oid AS row, code, coalesce(system, '') AS system, CAST(effective AS DATE) AS d, "
    "value_num, unit, value_code, coalesce(value_cmp, '') AS cmp FROM observation WHERE pid = $1",
    "condition": "SELECT cid AS row, code, coalesce(system, '') AS system, coalesce(onset, recorded) AS d, "
    "status FROM condition WHERE pid = $1",
    "medication": "SELECT mid AS row, coalesce(atc, '') AS code, coalesce(nhi_code, '') AS code2, "
    "coalesce(start, authored) AS d, name, status FROM medication WHERE pid = $1",
}


class NoSnapshot(RuntimeError):
    """The lake names no snapshot (a box before its first night, or a lake that does not answer)."""


class LakeFacts:
    """The subject's record in the box's lake, at the snapshot the box reads now (recorded on every citation)."""

    def __init__(self, lake: Any) -> None:
        self.lake = lake
        self._snap = str(lake.snapshot() or "")
        if not self._snap:  # D-684: every read of one draft is of one named snapshot, and its citations name it
            raise NoSnapshot("the lake names no snapshot")

    def snapshot(self) -> str:
        return self._snap

    def _q(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = self.lake.query(sql, params, self._snap or None).to_pylist()
        return rows

    def patient(self, pid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT pid, birth_date, sex FROM patient WHERE pid = $1", [pid])
        return rows[0] if rows else None

    def rows(self, pid: str, source: str) -> list[dict[str, Any]]:
        return self._q(_SQL[source], [pid]) if source in _SQL else []

    def site_facts(self, pid: str) -> list[dict[str, Any]]:
        """The patient's site facts. A snapshot built before site facts existed holds none: told by the lake's own
        answer to "is the table there" (``tb_common.lakeprobe``, D-649), never by an error's words (D-684). Any
        other failure stops the draft: no facts read is not "no facts" (a proposed fact holds a draft back)."""
        from tb_common.lakeprobe import rows_or_no_table

        sql = "SELECT fid, domain, coalesce(code, '') AS code, d, basis FROM site_fact WHERE pid = $1"
        rows = rows_or_no_table(self.lake, sql, [pid], self._snap or None, "site_fact")
        return [] if rows is None else rows

    def notes(self, pid: str, until: date) -> list[dict[str, Any]]:
        return self._q(
            "SELECT did AS row, CAST(date AS DATE) AS d, type, text FROM document WHERE pid = $1 "
            "AND CAST(date AS DATE) <= CAST($2 AS DATE) ORDER BY date DESC",
            [pid, until.isoformat()],
        )


def _day(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _norm_code(c: str) -> str:
    return str(c or "").replace(".", "").upper()


# A row in one of these states never counts as a fact (D-162, review E-09): written in error, called off, not yet
# real, or found not to be so. A resolved diagnosis or a stopped medicine still counts as history.
VOID_STATUS = frozenset({"entered-in-error", "cancelled", "draft", "refuted", "not-taken"})
PREFIX_MIN = 3  # an ICD-10 or ATC prefix shorter than this matches too much


def _void(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").strip().lower() in VOID_STATUS


def _matches(m: ItemMap, row: dict[str, Any], fact: bool = False) -> bool:
    # D-598: a code counts only under the item's code system. A hospital's own code that reads like a LOINC or an
    # ICD-10 code is another code; a row that names no system is of none. A medicine is read by column (no system).
    # A chart fact (``fact``) carries no system: it is matched by its code, and is never a value by itself
    want = () if fact else systems_of(m)
    if want and str(row.get("system") or "") not in want:
        return False
    if m.source == "observation":
        return str(row.get("code") or "") in m.codes
    codes = {_norm_code(c) for c in m.codes}
    code, code2 = _norm_code(row.get("code") or ""), _norm_code(row.get("code2") or "")
    # ICD-10 and ATC codes match on their prefix (M10 covers M10.9); a hospital drug code (code2) must match whole
    if code and (code in codes or any(len(c) >= PREFIX_MIN and code.startswith(c) for c in codes)):
        return True
    return bool(code2) and code2 in codes


def _in_window(m: ItemMap, d: date, visit: date) -> bool:
    if m.what in ("presence", "term", "start") or (m.source == "condition" and m.what == "date"):
        return d <= visit and (m.window_days == 0 or d >= visit - timedelta(days=m.window_days))
    if m.pick == "latest_before":
        return visit - timedelta(days=m.window_days) <= d <= visit
    return abs((d - visit).days) <= m.window_days


def _num_text(x: float, f: Field) -> str:
    if f.kind == "integer":
        return str(int(x)) if float(x).is_integer() else f"{x}"
    return f"{x:.6f}".rstrip("0").rstrip(".") if not float(x).is_integer() else str(int(x))


def _cite(kind: str, table: str, row: Any, snap: str, d: date | None, text: str, quote: str = "") -> dict[str, Any]:
    out = {"kind": kind, "table": table, "row": str(row), "snapshot": snap, "day": d.isoformat() if d else "",
           "text": text[:300]}  # fmt: skip
    if quote:
        out["quote"] = quote[:300]
    return out


@dataclass
class _Ctx:
    pid: str
    visit: date
    facts: Facts
    snap: str
    confirmed: set[tuple[str, str, str]] = field(default_factory=set)  # (domain, code, day) a person confirmed
    proposed: list[dict[str, Any]] = field(default_factory=list)


def _kind_of(ctx: _Ctx, domain: str, code: str, d: date | None) -> str:
    return "confirmed" if (domain, _norm_code(code), d.isoformat() if d else "") in ctx.confirmed else "record"


def _only_proposed(ctx: _Ctx, m: ItemMap) -> bool:
    for p in ctx.proposed:
        dom = {"observation": "observation", "condition": "condition", "medication": "medication"}.get(m.source)
        d = _day(p.get("d"))
        if (
            dom
            and p.get("domain") == dom
            and _matches(m, {"code": p.get("code")}, fact=True)
            and (d is None or d <= ctx.visit)
        ):
            return True
        if m.source == "patient" and p.get("domain") in ("demographic", m.what):
            return True
    return False


def _unknown(m: ItemMap, f: Field, why: str, snap: str) -> Draft:
    return Draft(m.item, f.form, m.cdash, m.test, "", "unknown", why, None, snap)


#: NEW-EDC-13 (EDC-016): a drafted date before this year is a date that lost its century, never a patient's
FIRST_YEAR = "1900"


def _value(m: ItemMap, f: Field, value: str, cite: dict[str, Any], version: str) -> Draft:
    if problem(f, value) is not None or (f.kind in ("date", "dateTime") and value[:4] < FIRST_YEAR):
        return Draft(m.item, f.form, m.cdash, m.test, "", "unknown", "invalid", None, version)
    return Draft(m.item, f.form, m.cdash, m.test, value, "drafted", "", cite, version)


def _patient(ctx: _Ctx, m: ItemMap, f: Field) -> Draft:
    row = ctx.facts.patient(ctx.pid)
    if row is None:
        return _unknown(m, f, "only_proposed" if _only_proposed(ctx, m) else "no_record", ctx.snap)
    if m.what == "birth_date":
        d = _day(row.get("birth_date"))
        if d is None:
            return _unknown(m, f, "only_proposed" if _only_proposed(ctx, m) else "no_record", ctx.snap)
        return _value(m, f, d.isoformat(), _cite("record", "patient", "birth_date", ctx.snap, None,
                                                 f"patient birth date {d.isoformat()}"), ctx.snap)  # fmt: skip
    sex = str(row.get("sex") or "").strip().lower()
    sex = {"m": "male", "f": "female", "男": "male", "女": "female"}.get(sex, sex)
    if sex not in m.sex_codes:
        return _unknown(m, f, "only_proposed" if _only_proposed(ctx, m) else "no_record", ctx.snap)
    return _value(m, f, m.sex_codes[sex], _cite("record", "patient", "sex", ctx.snap, None, f"patient sex {sex}"),
                  ctx.snap)  # fmt: skip


def _coded(ctx: _Ctx, m: ItemMap, f: Field) -> Draft:
    rows = [r for r in ctx.facts.rows(ctx.pid, m.source) if _matches(m, r) and not _void(r)]
    dated = [(d, r) for r in rows if (d := _day(r.get("d"))) is not None and _in_window(m, d, ctx.visit)]
    if not dated:
        why = "only_proposed" if _only_proposed(ctx, m) else ("out_of_window" if rows else "no_record")
        return _unknown(m, f, why, ctx.snap)
    if m.what == "presence":  # the latest record in the window; only ever the yes code
        d, r = max(dated, key=lambda x: (x[0], str(x[1].get("row"))))
        status = str(r.get("status") or "").strip()
        text = f"{m.source} {r.get('code') or r.get('code2')} on {d.isoformat()}" + (f" ({status})" if status else "")
        return _value(m, f, m.yes_code, _cite(_kind_of(ctx, m.source, str(r.get("code")), d), m.source, r.get("row"),
                                              ctx.snap, d, text), ctx.snap)  # fmt: skip
    if m.what in ("date", "start") and m.source in ("condition", "medication"):
        d, r = min(dated, key=lambda x: (x[0], str(x[1].get("row"))))  # the first record: when it started
        return _value(m, f, d.isoformat(), _cite(_kind_of(ctx, m.source, str(r.get("code")), d), m.source,
                                                 r.get("row"), ctx.snap, d, f"{m.source} {r.get('code')} first "
                                                 f"recorded {d.isoformat()}"), ctx.snap)  # fmt: skip
    if m.what == "term":
        d, r = max(dated, key=lambda x: (x[0], str(x[1].get("row"))))
        names = {str(x.get("name") or "").strip() for dd, x in dated if dd == d}
        if len(names) != 1 or not next(iter(names)):
            return _unknown(m, f, "conflict" if len(names) > 1 else "no_record", ctx.snap)
        return _value(
            m,
            f,
            next(iter(names)),
            _cite(
                _kind_of(ctx, "medication", str(r.get("code")), d),
                "medication",
                r.get("row"),
                ctx.snap,
                d,
                f"medication {r.get('code')} on {d.isoformat()}",
            ),
            ctx.snap,
        )
    # observation value or date: the latest before the visit, or the nearest to it
    if m.what == "value":
        right = [(d, r) for d, r in dated if unit_key(str(r.get("unit") or "")) == unit_key(m.unit)]
        if not right:
            return _unknown(m, f, "unit", ctx.snap)
        dated = right
    if m.pick == "latest_before":
        best = max(d for d, _ in dated)
        chosen = [(d, r) for d, r in dated if d == best]
    else:
        gap = min(abs((d - ctx.visit).days) for d, _ in dated)
        chosen = [(d, r) for d, r in dated if abs((d - ctx.visit).days) == gap]
    if m.what == "date":
        days = {d for d, _ in chosen}
        if len(days) != 1:
            return _unknown(m, f, "conflict", ctx.snap)
        d, r = chosen[0]
        return _value(m, f, d.isoformat(), _cite(_kind_of(ctx, "observation", str(r.get("code")), d), "observation",
                                                 r.get("row"), ctx.snap, d, f"observation {r.get('code')} on "
                                                 f"{d.isoformat()}"), ctx.snap)  # fmt: skip
    if any(str(r.get("cmp") or "").strip() for _, r in chosen):
        return _unknown(m, f, "censored", ctx.snap)
    vals = {r.get("value_num") for _, r in chosen}
    if len(vals) != 1 or None in vals:
        return _unknown(m, f, "conflict" if len(vals) > 1 else "no_record", ctx.snap)
    d, r = chosen[0]
    text = _num_text(float(r["value_num"]), f)
    cite = _cite(_kind_of(ctx, "observation", str(r.get("code")), d), "observation", r.get("row"), ctx.snap, d,
                 f"observation {r.get('code')} = {text} {r.get('unit') or ''} on {d.isoformat()}")  # fmt: skip
    return _value(m, f, text, cite, ctx.snap)


# a note drafter: (item map, field, notes) -> {"found", "value", "quote", "note", "date"} and its version
NoteDrafter = Callable[[ItemMap, Field, list[dict[str, Any]]], tuple[dict[str, Any], str]]


def _note(ctx: _Ctx, m: ItemMap, f: Field, drafter: NoteDrafter | None) -> Draft:
    if drafter is None:
        return _unknown(m, f, "no_model", ctx.snap)
    notes = []
    used = 0
    skipped = 0
    for n in ctx.facts.notes(ctx.pid, ctx.visit):
        d = _day(n.get("d"))
        if d is None or (m.window_days and d < ctx.visit - timedelta(days=m.window_days)):
            continue
        text = str(n.get("text") or "")
        if used + len(text) > NOTE_CHARS:
            skipped += 1  # a note that does not fit is skipped, never the ones after it (review E-26)
            continue
        used += len(text)
        notes.append({"id": str(n.get("row")), "date": d.isoformat(), "type": str(n.get("type") or ""), "text": text})
    if not notes:
        return _unknown(m, f, "too_long" if skipped else "no_record", ctx.snap)
    ans, version = drafter(m, f, notes)
    stamp = f"{ctx.snap}|{version}"
    if not ans.get("found") or not str(ans.get("value") or "").strip():
        return _unknown(m, f, "no_record", stamp)
    note = next((n for n in notes if n["id"] == str(ans.get("note") or "")), None)
    quote = str(ans.get("quote") or "").strip()
    if note is None or not quote or not quote_in(quote, note["text"]):
        return _unknown(m, f, "quote_not_found", stamp)
    value = str(ans["value"]).strip()
    if len(quote) < QUOTE_MIN or not _value_in_quote(f, value, quote):
        return _unknown(m, f, "quote_not_found", stamp)  # the quote must show the value itself (review E-18)
    if f.kind == "choice" and value != m.yes_code:
        return _unknown(m, f, "only_yes_from_notes", stamp)  # a note never drafts "No" or another code
    d = _day(note["date"])
    cite = _cite("note", "document", note["id"], ctx.snap, d, f"note of {note['date']}", quote)
    return _value(m, f, value, cite, stamp)


QUOTE_MIN = 6  # characters; a shorter quote cannot show where a value comes from


def _value_in_quote(f: Field, value: str, quote: str) -> bool:
    """A number or a date drafted from a note must appear in its quote (digits compared, separators ignored)."""
    if f.kind in ("integer", "decimal"):
        return value in quote or value.rstrip("0").rstrip(".") in quote
    if f.kind in ("date", "dateTime"):
        # NEW-EDC-13: the quote must write the date itself; digits gathered from across the quote (a phone, a lot
        # number, two numbers side by side) never show one
        return value[:10] in dates_in(quote)
    return True


# NEW-EDC-13 (D-697, EDC-016): dates as notes at both sites write them, each turned into a Gregorian date that must
# exist. A Japanese era (the first year written 元) must hold the date; a single letter (R, H, S, T) only in the
# zero-padded form (R06.01.10), never right after a word, a digit, # or -, as a lab flag or a code can look like it;
# a ROC year with 民國 or 民国, or a three-digit year in the zero-padded form 113/01/10; never a two-digit year.
ERAS = {"令和": (2018, date(2019, 5, 1), date(9999, 12, 31)), "平成": (1988, date(1989, 1, 8), date(2019, 4, 30)),
        "昭和": (1925, date(1926, 12, 25), date(1989, 1, 7)), "大正": (1911, date(1912, 7, 30), date(1926, 12, 24)),
        "明治": (1867, date(1868, 1, 25), date(1912, 7, 29))}  # fmt: skip
LETTERS = {"R": "令和", "H": "平成", "S": "昭和", "T": "大正"}
ROC = 1911
_D = r"(?![\d./-])"
_ERA_WORD = re.compile(r"(令和|平成|昭和|大正|明治)\s*(\d{1,2}|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})(?!\d)")
_ERA_NUM = re.compile(r"(令和|平成|昭和|大正|明治)\s*(\d{1,2}|元)([./-])(\d{1,2})\3(\d{1,2})" + _D)
_ERA_LETTER = re.compile(r"(?<![\w#./-])([RHST])(\d{2})([./-])(\d{2})\3(\d{2})" + _D)
_ROC_WORD = re.compile(r"(?:民國|民国)\s*(\d{1,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})(?!\d)")
_ROC_NUM = re.compile(r"(?<![\d./-])(1\d{2})([/.])(\d{2})\2(\d{2})" + _D)
_GREG_SEP = re.compile(r"(?<![\d./-])((?:19|20)\d{2})([-/.])(\d{1,2})\2(\d{1,2})(?![\d])")
_GREG_RUN = re.compile(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)")
_GREG_WORD = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})(?!\d)")


def dates_in(text: str) -> set[str]:
    """The dates a note's text writes, as YYYY-MM-DD: era and ROC years turned into Gregorian ones."""
    out: set[str] = set()

    def day(y: int, mo: str, d: str) -> date | None:
        try:
            return date(y, int(mo), int(d))
        except ValueError:
            return None

    def era(name: str, y: str, mo: str, d: str) -> None:
        base, first, last = ERAS[name]
        n = 1 if y == "元" else int(y)
        got = day(base + n, mo, d) if n >= 1 else None
        if got is not None and first <= got <= last:
            out.add(got.isoformat())

    for name, y, mo, d in _ERA_WORD.findall(text):
        era(name, y, mo, d)
    for name, y, _s, mo, d in _ERA_NUM.findall(text):
        era(name, y, mo, d)
    for letter, y, _s, mo, d in _ERA_LETTER.findall(text):
        era(LETTERS[letter], y, mo, d)
    for y, mo, d in _ROC_WORD.findall(text):
        if (got := day(ROC + int(y), mo, d)) is not None:
            out.add(got.isoformat())
    for y, _s, mo, d in _ROC_NUM.findall(text):
        if (got := day(ROC + int(y), mo, d)) is not None:
            out.add(got.isoformat())
    for y, _s, mo, d in _GREG_SEP.findall(text):
        if (got := day(int(y), mo, d)) is not None:
            out.add(got.isoformat())
    for pat in (_GREG_RUN, _GREG_WORD):
        for y, mo, d in pat.findall(text):
            if (got := day(int(y), mo, d)) is not None:
                out.add(got.isoformat())
    return out


def build(pid: str, visit: date, items: list[ItemMap], fields: dict[str, Field], facts: Facts,
          drafter: NoteDrafter | None = None) -> list[Draft]:  # fmt: skip
    """One draft per mapped item that the dictionary still has, in the map's order."""
    snap = facts.snapshot()
    ctx = _Ctx(pid, visit, facts, snap)
    for sf in facts.site_facts(pid):
        basis = str(sf.get("basis") or "")
        d = _day(sf.get("d"))
        if basis == "confirmed":
            ctx.confirmed.add((str(sf.get("domain")), _norm_code(str(sf.get("code"))), d.isoformat() if d else ""))
        elif basis in ("proposed", "suspected"):
            ctx.proposed.append(sf)
    out: list[Draft] = []
    for m in items:
        f = fields.get(m.item)
        if f is None:
            continue
        if not m.drafted:
            out.append(_unknown(m, f, "not_mapped", snap))
        elif m.source == "patient":
            out.append(_patient(ctx, m, f))
        elif m.source == "note":
            out.append(_note(ctx, m, f, drafter))
        else:
            out.append(_coded(ctx, m, f))
    return out


def gateway_drafter(llm: Any, job_id: str | None = None) -> NoteDrafter:
    """The note drafter through the box's gateway (prompt ``crf_prefill``; the stub in tests and the e2e)."""

    def draft(m: ItemMap, f: Field, notes: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
        choices = [{"code": c, "label": lbl} for c, lbl in f.options.items()]
        res = llm.chat_json("crf_prefill", {"item": {"name": f.name, "label": f.label, "kind": f.kind,
                                                     "choices": choices, "question": m.question},
                                            "notes": notes}, job_id=job_id)  # fmt: skip
        data = res.data if hasattr(res, "data") else res
        version = f"crf_prefill_v{getattr(res, 'prompt_version', '') or '1'}"
        return dict(data or {}), version

    return draft


_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def safe_key(text: str) -> bool:
    return bool(_SAFE.match(text))
