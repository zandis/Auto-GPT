"""REDCap's calculation and branching-logic syntax, read by a small evaluator of our own (T-302b, D-414).

Nothing here calls ``eval`` or ``exec`` or compiles code: a tokenizer, a recursive-descent parser that builds a tuple
tree, and an interpreter over that tree. Text longer than :data:`MAX_TEXT`, more than :data:`MAX_TOKENS` tokens or
deeper nesting than :data:`MAX_DEPTH` is refused, so a hostile data dictionary cannot exhaust the box.

What it reads (the common part of REDCap's syntax):

* references: ``[field]``, ``[event][field]``, ``[field(code)]`` (a checkbox code, ``1`` or ``0``), ``[field][2]``
  and ``[event][field][2]`` (a repeat instance);
* values: numbers, ``'text'`` and ``"text"``;
* operators: ``+ - * / ^``, ``= <> != < > <= >=``, ``and`` ``or`` (also ``&&`` ``||``), parentheses;
* functions: ``if``, ``sum``, ``mean``, ``median``, ``min``, ``max``, ``round``, ``roundup``, ``rounddown``, ``abs``,
  ``sqrt``, ``exponential``, ``log``, ``datediff``, ``isnumber``, ``isinteger``, ``contains``, ``not_contain``,
  ``starts_with``, ``ends_with``.

Anything else (smart variables such as ``[event-name]``, ``now``, action tags, other functions) raises
:class:`LogicError`: the caller then knows TrialBox cannot tell what REDCap would compute or hide, and fails closed.

Blanks follow REDCap: arithmetic on a blank is blank (``sum``, ``mean``, ``median``, ``min`` and ``max`` skip
blanks); a division by zero is blank; ``[x] = ''`` is true when ``x`` is blank; an order comparison with a blank is
false. A calculated value is written as REDCap stores it: a whole number without a decimal point, otherwise the
shortest text that reads back as the same number.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

MAX_TEXT = 4000
MAX_TOKENS = 1000
MAX_DEPTH = 40

Value = str | float | bool
Node = tuple[Any, ...]
#: ``lookup(event, field, code, instance)``: the value REDCap holds ("" when blank); raises :class:`LogicError` when
#: the reference cannot be resolved (an unknown field, a repeat instance it cannot pick)
Lookup = Callable[[str | None, str, str | None, int | None], str]


class LogicError(ValueError):
    """The text is outside what this evaluator reads, or a reference cannot be resolved."""


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<ref>(?:\[[^\[\]]{1,120}\])+)
      | '(?P<sq>[^']*)'
      | "(?P<dq>[^"]*)"
      | (?P<num>\d+(?:\.\d+)?|\.\d+)
      | (?P<op><>|!=|<=|>=|&&|\|\||[=<>+\-*/^(),])
      | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.X,
)
_NAME = re.compile(r"[a-z][a-z0-9_]*")
_CODE = re.compile(r"([a-z][a-z0-9_]*)\(([A-Za-z0-9_.\-]{1,60})\)")
FUNCTIONS = frozenset({"if", "sum", "mean", "median", "min", "max", "round", "roundup", "rounddown", "abs", "sqrt",
                       "exponential", "log", "datediff", "isnumber", "isinteger", "contains", "not_contain",
                       "starts_with", "ends_with"})  # fmt: skip
_CMP = ("=", "<>", "!=", "<", ">", "<=", ">=")


def _ref(text: str) -> Node:
    parts = re.findall(r"\[([^\[\]]*)\]", text)
    if not 1 <= len(parts) <= 3:
        raise LogicError(f"cannot read the reference {text}")
    instance: int | None = None
    if len(parts) > 1 and parts[-1].isdigit():
        instance = int(parts[-1])
        parts = parts[:-1]
    if len(parts) > 2 or instance == 0:
        raise LogicError(f"cannot read the reference {text}")
    event = parts[0] if len(parts) == 2 else None
    name, code = parts[-1], None
    m = _CODE.fullmatch(name)
    if m:
        name, code = m.group(1), m.group(2)
    if not _NAME.fullmatch(name) or (event is not None and not _NAME.fullmatch(event)):
        raise LogicError(f"{text} is not a field reference TrialBox reads (smart variables are not read)")
    return ("ref", event, name, code, instance)


def _tokens(text: str) -> list[tuple[str, Any]]:
    if len(text) > MAX_TEXT:
        raise LogicError("the logic is too long")
    out: list[tuple[str, Any]] = []
    pos, text = 0, text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise LogicError(f"cannot read the logic at {text[pos : pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup or ""
        val = m.group(kind)
        if kind == "ref":
            out.append(("ref", _ref(val)))
        elif kind in ("sq", "dq"):
            out.append(("str", val))
        elif kind == "num":
            out.append(("num", float(val)))
        elif kind == "op":
            out.append(("op", {"&&": "and", "||": "or", "!=": "<>"}.get(val, val)))
        else:
            low = val.lower()
            if low in ("and", "or"):
                out.append(("op", low))
            elif low in ("true", "false"):
                out.append(("bool", low == "true"))
            elif low in FUNCTIONS:
                out.append(("fn", low))
            else:
                raise LogicError(f"{val} is not a function or word TrialBox reads")
        if len(out) > MAX_TOKENS:
            raise LogicError("the logic is too long")
    return out


class _Parser:
    def __init__(self, toks: list[tuple[str, Any]]) -> None:
        self.toks = toks
        self.i = 0
        self.depth = 0

    def peek(self) -> tuple[str, Any] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, kind: str, val: Any = None) -> bool:
        t = self.peek()
        if t is not None and t[0] == kind and (val is None or t[1] == val):
            self.i += 1
            return True
        return False

    def need(self, kind: str, val: Any) -> None:
        if not self.take(kind, val):
            raise LogicError(f"expected {val!r}")

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise LogicError("the logic is nested too deeply")

    def expr(self) -> Node:
        self.enter()
        try:
            node = self.and_()
            while self.take("op", "or"):
                node = ("or", node, self.and_())
            return node
        finally:
            self.depth -= 1

    def and_(self) -> Node:
        node = self.cmp()
        while self.take("op", "and"):
            node = ("and", node, self.cmp())
        return node

    def cmp(self) -> Node:
        node = self.add()
        t = self.peek()
        if t is not None and t[0] == "op" and t[1] in _CMP:
            self.i += 1
            node = ("cmp", t[1], node, self.add())
        return node

    def add(self) -> Node:
        node = self.mul()
        while True:
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] in ("+", "-"):
                self.i += 1
                node = ("arith", t[1], node, self.mul())
            else:
                return node

    def mul(self) -> Node:
        node = self.unary()
        while True:
            t = self.peek()
            if t is not None and t[0] == "op" and t[1] in ("*", "/"):
                self.i += 1
                node = ("arith", t[1], node, self.unary())
            else:
                return node

    def unary(self) -> Node:
        if self.take("op", "-"):
            self.enter()
            try:
                return ("neg", self.unary())
            finally:
                self.depth -= 1
        if self.take("op", "+"):
            return self.unary()
        return self.power()

    def power(self) -> Node:
        node = self.atom()
        if self.take("op", "^"):
            self.enter()
            try:
                return ("arith", "^", node, self.unary())
            finally:
                self.depth -= 1
        return node

    def atom(self) -> Node:
        t = self.peek()
        if t is None:
            raise LogicError("the logic ends too early")
        self.i += 1
        kind, val = t
        if kind == "num":
            return ("lit", val)
        if kind in ("str", "bool"):
            return ("lit", val)
        if kind == "ref":
            return tuple(val)
        if kind == "fn":
            self.need("op", "(")
            args: list[Node] = []
            if not self.take("op", ")"):
                args.append(self.expr())
                while self.take("op", ","):
                    args.append(self.expr())
                self.need("op", ")")
            return ("fn", val, tuple(args))
        if kind == "op" and val == "(":
            node = self.expr()
            self.need("op", ")")
            return node
        raise LogicError(f"unexpected {val!r}")


@lru_cache(maxsize=512)
def parse(text: str) -> Node:
    """The tree of ``text``; raises :class:`LogicError` when it is empty or outside what TrialBox reads."""
    toks = _tokens(text or "")
    if not toks:
        raise LogicError("the logic is empty")
    p = _Parser(toks)
    node = p.expr()
    if p.i != len(toks):
        raise LogicError(f"cannot read the logic after token {p.i}")
    return node


def refs(text: str) -> set[tuple[str | None, str]]:
    """The ``(event, field)`` pairs ``text`` reads (raises :class:`LogicError` like :func:`parse`)."""
    out: set[tuple[str | None, str]] = set()

    def walk(n: Any) -> None:
        if isinstance(n, tuple):
            if n and n[0] == "ref":
                out.add((n[1], n[2]))
                return
            for x in n:
                walk(x)

    walk(parse(text))
    return out


def fields_of(text: str) -> set[str]:
    """The field names ``text`` reads; an empty set when it cannot be read."""
    try:
        return {f for _e, f in refs(text)}
    except LogicError:
        return set()


# ------------------------------------------------------------------ values
def _num(v: Value) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    s = v.strip()
    if not s or not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", s):
        return None
    x = float(s)
    return x if math.isfinite(x) else None


def _blank(v: Value) -> bool:
    return isinstance(v, str) and v.strip() == ""


def _text(v: Value) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return number_text(v)
    return v


def number_text(x: float) -> str:
    """A number as REDCap stores a calculated value."""
    if not math.isfinite(x):
        return ""
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return repr(x)


def truthy(v: Value) -> bool:
    if isinstance(v, bool):
        return v
    n = _num(v)
    if n is not None:
        return n != 0
    return not _blank(v)


def _equal(a: Value, b: Value) -> bool:
    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na == nb
    return _text(a) == _text(b)


def _order(op: str, a: Value, b: Value) -> bool:
    if _blank(a) or _blank(b):
        return False
    na, nb = _num(a), _num(b)
    x: Any
    y: Any
    if na is not None and nb is not None:
        x, y = na, nb
    else:
        x, y = _text(a), _text(b)
    return bool({"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op])


def _arith(op: str, a: Value, b: Value) -> Value:
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return ""
    try:
        if op == "+":
            r = x + y
        elif op == "-":
            r = x - y
        elif op == "*":
            r = x * y
        elif op == "/":
            if y == 0:
                return ""
            r = x / y
        else:  # ^
            if abs(y) > 1000:
                return ""
            r = math.pow(x, y)
    except (OverflowError, ValueError, ZeroDivisionError):
        return ""
    return r if math.isfinite(r) else ""


def _round(x: float, places: int, how: str) -> float:
    q = Decimal(1).scaleb(-places)
    try:
        return float(Decimal(repr(x)).quantize(q, rounding=how))
    except InvalidOperation:
        return x


def _day(v: Value, today: date) -> datetime | None:
    s = _text(v).strip()
    if not s:
        return None
    if s.lower() == "today":
        return datetime(today.year, today.month, today.day)
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise LogicError(f"{s!r} is not a date TrialBox reads (YYYY-MM-DD, or 'today')")


_UNITS = {"y": 86400 * 365.2425, "M": 86400 * 30.44, "d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}


class _Eval:
    def __init__(self, lookup: Lookup, today: date) -> None:
        self.lookup = lookup
        self.today = today

    def run(self, n: Node) -> Value:
        kind = n[0]
        if kind == "lit":
            return n[1]  # type: ignore[no-any-return]
        if kind == "ref":
            return str(self.lookup(n[1], n[2], n[3], n[4]) or "")
        if kind == "neg":
            v = self.run(n[1])
            x = _num(v)
            return "" if x is None else -x
        if kind == "arith":
            return _arith(n[1], self.run(n[2]), self.run(n[3]))
        if kind == "cmp":
            a, b = self.run(n[2]), self.run(n[3])
            if n[1] == "=":
                return _equal(a, b)
            if n[1] == "<>":
                return not _equal(a, b)
            return _order(n[1], a, b)
        if kind == "and":
            return truthy(self.run(n[1])) and truthy(self.run(n[2]))
        if kind == "or":
            return truthy(self.run(n[1])) or truthy(self.run(n[2]))
        if kind == "fn":
            return self.fn(n[1], n[2])
        raise LogicError(f"cannot evaluate {kind}")  # pragma: no cover - the parser makes no other node

    def fn(self, name: str, args: tuple[Node, ...]) -> Value:
        def arity(lo: int, hi: int) -> None:
            if not lo <= len(args) <= hi:
                raise LogicError(f"{name}() takes {lo} to {hi} values")

        if name == "if":
            arity(3, 3)
            return self.run(args[1]) if truthy(self.run(args[0])) else self.run(args[2])
        if name in ("sum", "mean", "median", "min", "max"):
            arity(1, 200)
            nums = [x for x in (_num(self.run(a)) for a in args) if x is not None]
            if not nums:
                return ""
            if name == "sum":
                return math.fsum(nums)
            if name == "mean":
                return math.fsum(nums) / len(nums)
            if name == "median":
                s = sorted(nums)
                mid = len(s) // 2
                return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
            return min(nums) if name == "min" else max(nums)
        if name in ("round", "roundup", "rounddown"):
            arity(1, 2)
            x = _num(self.run(args[0]))
            places = _num(self.run(args[1])) if len(args) == 2 else 0.0
            if x is None or places is None or places != int(places) or not 0 <= places <= 15:
                return ""
            mode = {"round": ROUND_HALF_UP, "roundup": ROUND_UP, "rounddown": ROUND_DOWN}[name]
            return _round(x, int(places), mode)
        if name in ("abs", "sqrt", "exponential"):
            arity(1, 1)
            x = _num(self.run(args[0]))
            if x is None or (name == "sqrt" and x < 0):
                return ""
            try:
                return abs(x) if name == "abs" else math.sqrt(x) if name == "sqrt" else math.exp(x)
            except OverflowError:
                return ""
        if name == "log":
            arity(1, 2)
            x = _num(self.run(args[0]))
            base = _num(self.run(args[1])) if len(args) == 2 else math.e
            if x is None or base is None or x <= 0 or base <= 0 or base == 1:
                return ""
            return math.log(x, base)
        if name == "datediff":
            return self.datediff(args)
        if name in ("isnumber", "isinteger"):
            arity(1, 1)
            v = self.run(args[0])
            x = _num(v)
            if name == "isnumber":
                return x is not None
            return x is not None and x == int(x) and "." not in _text(v)
        if name in ("contains", "not_contain", "starts_with", "ends_with"):
            arity(2, 2)
            hay, needle = _text(self.run(args[0])).lower(), _text(self.run(args[1])).lower()
            if name == "contains":
                return needle in hay
            if name == "not_contain":
                return needle not in hay
            return hay.startswith(needle) if name == "starts_with" else hay.endswith(needle)
        raise LogicError(f"{name}() is not read")  # pragma: no cover - the tokenizer refuses other names

    def datediff(self, args: tuple[Node, ...]) -> Value:
        if not 3 <= len(args) <= 5:
            raise LogicError("datediff() takes 3 to 5 values")
        unit = _text(self.run(args[2]))
        if unit not in _UNITS:
            raise LogicError(f"datediff() unit {unit!r} is not y, M, d, h, m or s")
        signed = False
        for a in args[3:]:
            v = self.run(a)
            t = _text(v).strip().lower()
            if t in ("ymd", "mdy", "dmy"):  # the date format: the API always gives YYYY-MM-DD
                continue
            if t in ("true", "false", "1", "0") or isinstance(v, bool):
                signed = truthy(v) if isinstance(v, bool) else t in ("true", "1")
                continue
            raise LogicError(f"datediff() does not read {t!r}")
        d1, d2 = _day(self.run(args[0]), self.today), _day(self.run(args[1]), self.today)
        if d1 is None or d2 is None:
            return ""
        diff = (d2 - d1).total_seconds() / _UNITS[unit]
        return diff if signed else abs(diff)


def evaluate(text: str, lookup: Lookup, today: date) -> Value:
    """The value of ``text`` (raises :class:`LogicError` when it cannot be read or a reference cannot be resolved)."""
    try:
        return _Eval(lookup, today).run(parse(text))
    except RecursionError as exc:  # pragma: no cover - MAX_DEPTH keeps well below the interpreter's limit
        raise LogicError("the logic is nested too deeply") from exc


def shown(text: str, lookup: Lookup, today: date) -> bool:
    """Whether REDCap shows a field with branching logic ``text`` (an empty rule always shows it)."""
    if not (text or "").strip():
        return True
    return truthy(evaluate(text, lookup, today))


def calculate(text: str, lookup: Lookup, today: date) -> str:
    """The value REDCap stores for a calculated field with equation ``text`` ("" when blank)."""
    v = evaluate(text, lookup, today)
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return number_text(v)
    x = _num(v)
    return number_text(x) if x is not None else ""


def same_number(a: str, b: str) -> bool:
    """Two stored calculated values are the same (as numbers when both are, to 1e-9 relative)."""
    if a.strip() == b.strip():
        return True
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return False
    return math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12)
