"""What a first look at a real source may say about it without saying anything about a patient (T-731, D-588).

``tools/mapping_check.py --share <file>`` builds its report from these: the *shape* of a date, never the date; a
code only when it looks like one; counts. :class:`Net` is the second net: every text taken from the source is
compared with the identifying values of the rows that were read and with the repository's data scan patterns, and
withheld on a hit.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from adapter.mapping.engine import _CODE_SHAPE, NO_CODE, NOT_A_CODE, Mapper, MappingError, ResourceSpec
from adapter.sources.base import Row

WITHHELD = "(withheld)"
NOT_A_UNIT = "(not a unit)"
DATE_TYPES = ("date", "datetime", "instant")
# A shape longer than this is cut: a date is never this long, and a long text put in a date column is a mis-mapped
# column, which the first 40 marks already show
SHAPE_MAX = 40
# The longest unit spelling written out. The longest in the shared table is 15 characters ("10*3/uL{cells}" class);
# a site's own suffix fits in the rest, a sentence does not
UNIT_MAX = 20
# An identifying value this long is also looked for inside a longer text (a chart number inside a reason); a
# shorter one only as the whole text, or "12" would withhold every count
INSIDE_MIN = 6
IDENT_MIN = 3  # a one- or two-character value (a sex code) identifies nobody and is in every table
# Words of a date that say which calendar it is: kept as written, they are not a patient's
_DATE_WORDS = (
    *("民國", "民国", "中華民國", "西元", "令和", "平成", "昭和", "大正", "明治"),
    *("年", "月", "日", "時", "分", "秒", "上午", "下午", "午前", "午後"),
)
_WORDS = re.compile("|".join(sorted(_DATE_WORDS, key=len, reverse=True)))
_DIGIT_RUN = re.compile(r"\d{5,}")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_TOKEN = re.compile(r"\S+")


def shape(text: Any) -> str:
    """``2026-05-12 08:30`` → ``9999-99-99 99:99``: a digit is 9, a letter A, another script 字; the words of a
    calendar (民國, 令和, 年月日, 上午) and the ``T`` between a date and a time stay."""
    s = "" if text is None else str(text)
    out: list[str] = []
    i = 0
    while i < len(s) and len(out) < SHAPE_MAX:
        m = _WORDS.match(s, i)
        c = s[i]
        if m:
            out.append(m.group())
            i = m.end()
            continue
        if c.isdigit():
            out.append("9")
        elif c == "T" and 0 < i < len(s) - 1 and s[i - 1].isdigit() and s[i + 1].isdigit():
            out.append("T")
        elif c.isascii() and c.isalpha():
            out.append("A")
        elif c.isspace():
            out.append(" ")
        elif c.isascii():
            out.append(c)
        else:
            out.append("字" if c.isalpha() else "?")
        i += 1
    return "".join(out) + ("…" if i < len(s) else "")


def scrub_reason(message: str) -> str:
    """Why the mapping refused a row, with nothing of the row in it: quoted values out, and every other word
    that holds a digit or a letter of another script given by its shape."""

    def word(m: re.Match[str]) -> str:
        w = m.group()
        return w if w.isascii() and not re.search(r"\d", w) else shape(w)

    return _TOKEN.sub(word, _QUOTED.sub("<value>", message))


def date_columns(specs: Iterable[ResourceSpec]) -> dict[str, str]:
    """``{canonical column: date | datetime | instant}`` for every column a resource of the table reads as a date."""
    out: dict[str, str] = {}

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            typ = x.get("type")
            if typ in DATE_TYPES:
                for k in ("column", "start", "end"):
                    if isinstance(x.get(k), str):
                        out.setdefault(x[k], typ)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for spec in specs:
        walk(spec.elements)
    return out


def date_shapes(mapper: Mapper, rows: list[Row], columns: dict[str, str]) -> dict[str, dict[str, Any]]:
    """For each date column: how its values are written (by shape, the commonest first), and how many the mapping
    reads, refuses and finds empty. A column no row has is left out (it is under the missing columns)."""
    out: dict[str, dict[str, Any]] = {}
    for col, typ in sorted(columns.items()):
        if not any(col in r for r in rows):
            continue
        shapes: Counter[str] = Counter()
        read = refused = empty = 0
        for r in rows:
            v = r.get(col)
            if v is None or not str(v).strip():
                empty += 1
                continue
            shapes[shape(str(v).strip())] += 1
            try:
                mapper.convert(v, typ)
                read += 1
            except (MappingError, ValueError):
                refused += 1
        out[col] = {"type": typ, "read": read, "refused": refused, "empty": empty,
                    "shapes": dict(sorted(shapes.items(), key=lambda kv: (-kv[1], kv[0])))}  # fmt: skip
    return out


def repeated_keys(rows: list[Row], key: str, day_column: str | None) -> dict[str, Any]:
    """Counts of keys that come more than once: copies that are the same row, copies that differ, and of those
    the ones whose ``day_column`` (the first ten characters) differs: an order number used again another day."""
    groups: dict[str, list[Row]] = {}
    for r in rows:
        k = str(r.get(key) or "").strip()
        if k:
            groups.setdefault(k, []).append(r)
    rep = [g for g in groups.values() if len(g) > 1]
    differing = [g for g in rep if any(r != g[0] for r in g[1:])]
    out: dict[str, Any] = {
        "key": key,
        "rows_without_key": sum(1 for r in rows if not str(r.get(key) or "").strip()),
        "keys_repeated": len(rep),
        "rows_in_them": sum(len(g) for g in rep),
        "identical_copies": len(rep) - len(differing),
        "differing_copies": len(differing),
    }
    if day_column:
        out["day_column"] = day_column
        out["differing_on_another_day"] = sum(
            1 for g in differing if len({str(r.get(day_column) or "").strip()[:10] for r in g}) > 1
        )
    return out


def map_rows(mapper: Mapper, table: str, rows: list[Row]) -> tuple[list[dict[str, Any]], Counter[str]]:
    """The table's resources and the rows the mapping refused, by reason, as the night counts them (T-615a): a
    refused row does not stop the check."""
    out: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for row in rows:
        try:
            out.extend(mapper.map_table(table, iter([row])))
        except ValueError as exc:
            rejected[scrub_reason(str(exc))] += 1
    return out, rejected


class Net:
    """The second net (D-588): a text taken from the source is withheld when it is, or holds, an identifying
    value of the rows that were read, or when the data scan (``scan``: text → whether it hits) knows its kind."""

    def __init__(self, scan: Callable[[str], bool], chart_pattern: str | None = None) -> None:
        self.scan = scan
        self.chart = re.compile(chart_pattern) if chart_pattern else None
        self.exact: set[str] = set()
        self.inside: set[str] = set()
        self.withheld = 0

    def learn(self, rows: Iterable[Row], columns: Iterable[str] | None) -> None:
        """Remember the values of ``columns`` (every column when None) as identifying."""
        cols = None if columns is None else set(columns)
        for r in rows:
            for k, v in r.items():
                s = "" if v is None else str(v).strip()
                if len(s) >= IDENT_MIN and (cols is None or k in cols):
                    self.exact.add(s)
                    if len(s) >= INSIDE_MIN:
                        self.inside.add(s)

    def identifying(self, s: str) -> bool:
        t = s.strip()
        return t in self.exact or any(i in t for i in self.inside)

    def text(self, s: Any) -> str:
        """A text from the source (a column name, a recognised answer), or WITHHELD."""
        t = "" if s is None else str(s).strip()
        if t and (self.identifying(t) or self.scan(t)):
            self.withheld += 1
            return WITHHELD
        return t

    def code(self, s: Any) -> str:
        """A code as fed, when it looks like one (D-580) and the net lets it through."""
        t = "" if s is None else str(s).strip()
        if not t:
            return NO_CODE
        if t in (NO_CODE, NOT_A_CODE):
            return t
        if not _CODE_SHAPE.fullmatch(t) or (self.chart is not None and self.chart.fullmatch(t)):
            return NOT_A_CODE
        return self.text(t)

    def unit(self, s: Any) -> str:
        t = "" if s is None else str(s).strip()
        if not t:
            return ""
        if len(t) > UNIT_MAX or _DIGIT_RUN.search(t) or len(t.split()) > 2:
            return NOT_A_UNIT
        return self.text(t)

    def counts(self, by: dict[Any, int], how: Callable[[Any], str]) -> dict[str, int]:
        """``{value: rows}`` with every value passed through ``how``; values that become the same word add up."""
        out: Counter[str] = Counter()
        for k, n in by.items():
            out[how(k)] += n
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    def sweep(self, x: Any) -> Any:
        """The last pass over a finished report: any text that is or holds an identifying value is withheld,
        wherever it stands (a key, a value, a list)."""
        if isinstance(x, dict):
            out: dict[Any, Any] = {}
            for k, v in x.items():
                k2 = self._swept(k) if isinstance(k, str) else k
                v2 = self.sweep(v)
                if k2 in out and isinstance(out[k2], int) and isinstance(v2, int):
                    v2 += out[k2]
                out[k2] = v2
            return out
        if isinstance(x, list):
            return [self.sweep(v) for v in x]
        return self._swept(x) if isinstance(x, str) else x

    def _swept(self, s: str) -> str:
        if s != WITHHELD and self.identifying(s):
            self.withheld += 1
            return WITHHELD
        return s
