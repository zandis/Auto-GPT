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

from edc.mapping import ItemMap, unit_key

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
    "observation": "SELECT oid AS row, code, CAST(effective AS DATE) AS d, value_num, unit, value_code, "
    "coalesce(value_cmp, '') AS cmp FROM observation WHERE pid = $1",
    "condition": "SELECT cid AS row, code, coalesce(onset, recorded) AS d, status FROM condition WHERE pid = $1",
    "medication": "SELECT mid AS row, coalesce(atc, '') AS code, coalesce(nhi_code, '') AS code2, "
    "coalesce(start, authored) AS d, name, status FROM medication WHERE pid = $1",
}


class LakeFacts:
    """The subject's record in the box's lake, at the snapshot the box reads now (recorded on every citation)."""

    def __init__(self, lake: Any) -> None:
        self.lake = lake
        self._snap = str(lake.snapshot() or "")

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
        try:
            return self._q("SELECT fid, domain, coalesce(code, '') AS code, d, basis FROM site_fact WHERE pid = $1",
                           [pid])  # fmt: skip
        except Exception as exc:  # a snapshot built before site facts existed holds none
            if "site_fact" in str(exc):
                return []
            raise

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


def _matches(m: ItemMap, row: dict[str, Any]) -> bool:
    if m.source == "observation":
        return str(row.get("code") or "") in m.codes
    codes = {_norm_code(c) for c in m.codes}
    got = [_norm_code(row.get("code") or "")] + ([_norm_code(row.get("code2") or "")] if row.get("code2") else [])
    # ICD-10 and ATC codes match on their prefix (M10 covers M10.9); a hospital drug code must match whole
    return any(g and (g in codes or any(g.startswith(c) for c in codes)) for g in got if g)


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
        if dom and p.get("domain") == dom and _matches(m, {"code": p.get("code")}) and (d is None or d <= ctx.visit):
            return True
        if m.source == "patient" and p.get("domain") in ("demographic", m.what):
            return True
    return False


def _unknown(m: ItemMap, f: Field, why: str, snap: str) -> Draft:
    return Draft(m.item, f.form, m.cdash, m.test, "", "unknown", why, None, snap)


def _value(m: ItemMap, f: Field, value: str, cite: dict[str, Any], version: str) -> Draft:
    if problem(f, value) is not None:
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
    rows = [r for r in ctx.facts.rows(ctx.pid, m.source) if _matches(m, r)]
    dated = [(d, r) for r in rows if (d := _day(r.get("d"))) is not None and _in_window(m, d, ctx.visit)]
    if not dated:
        why = "only_proposed" if _only_proposed(ctx, m) else ("out_of_window" if rows else "no_record")
        return _unknown(m, f, why, ctx.snap)
    if m.what == "presence":  # the latest record in the window; only ever the yes code
        d, r = max(dated, key=lambda x: (x[0], str(x[1].get("row"))))
        text = f"{m.source} {r.get('code') or r.get('code2')} on {d.isoformat()}"
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
    for n in ctx.facts.notes(ctx.pid, ctx.visit):
        d = _day(n.get("d"))
        if d is None or (m.window_days and d < ctx.visit - timedelta(days=m.window_days)):
            continue
        text = str(n.get("text") or "")
        if used + len(text) > NOTE_CHARS:
            break
        used += len(text)
        notes.append({"id": str(n.get("row")), "date": d.isoformat(), "type": str(n.get("type") or ""), "text": text})
    if not notes:
        return _unknown(m, f, "no_record", ctx.snap)
    ans, version = drafter(m, f, notes)
    stamp = f"{ctx.snap}|{version}"
    if not ans.get("found") or not str(ans.get("value") or "").strip():
        return _unknown(m, f, "no_record", stamp)
    note = next((n for n in notes if n["id"] == str(ans.get("note") or "")), None)
    quote = str(ans.get("quote") or "").strip()
    if note is None or not quote or not quote_in(quote, note["text"]):
        return _unknown(m, f, "quote_not_found", stamp)
    d = _day(note["date"])
    cite = _cite("note", "document", note["id"], ctx.snap, d, f"note of {note['date']}", quote)
    return _value(m, f, str(ans["value"]).strip(), cite, stamp)


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
