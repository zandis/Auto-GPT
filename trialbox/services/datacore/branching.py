"""A small subset of REDCap's branching logic (TB-PLAN-04 step 4, D-129).

Supported: ``[field] = 'v'``, ``[field] <> 'v'`` (also ``!=``), values in single or double quotes or a bare number,
``and``, ``or`` (``and`` binds tighter) and parentheses. Anything else (functions, ``[field(1)]`` checkbox codes,
``>``, events, smart variables) is *unsupported*: ``parse`` answers ``None`` and the field is always shown; its
required check is then skipped, because TrialBox cannot know whether REDCap would hide it. A REDCap dictionary
with such a rule still imports unchanged.

The parsed rule is a small JSON-able tree, evaluated here on the server (always) and turned into a CSS rule for
the entry page where every compared field is a choice (the browser applies it with no script).
"""

from __future__ import annotations

import re
from typing import Any

Node = list[Any]  # ["or"|"and", node, ...] | ["="|"<>", field, value]

_TOKEN = re.compile(
    r"""\s*(?:
        \[(?P<field>[a-z][a-z0-9_]*)\]
      | '(?P<sq>[^']*)'
      | "(?P<dq>[^"]*)"
      | (?P<num>-?\d+(?:\.\d+)?)(?![\w.])
      | (?P<op><>|!=|=)
      | (?P<paren>[()])
      | (?P<word>[A-Za-z]+)
    )""",
    re.X,
)


def _tokens(text: str) -> list[tuple[str, str]] | None:
    out: list[tuple[str, str]] = []
    pos, text = 0, text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            return None
        pos = m.end()
        kind = m.lastgroup or ""
        val = m.group(kind)
        if kind in ("sq", "dq", "num"):
            out.append(("value", val))
        elif kind == "word":
            if val.lower() not in ("and", "or"):
                return None
            out.append((val.lower(), val))
        elif kind == "op":
            out.append(("op", "<>" if val == "!=" else val))
        else:
            out.append((kind, val))
    return out


def parse(text: str) -> Node | None:
    """The rule as a tree, or ``None`` when it is empty or outside the subset."""
    toks = _tokens(text or "")
    if not toks:
        return None
    pos = 0

    def peek() -> str:
        return toks[pos][0] if pos < len(toks) else ""

    def take(kind: str) -> str:
        nonlocal pos
        if peek() != kind:
            raise ValueError(kind)
        pos += 1
        return toks[pos - 1][1]

    def expr() -> Node:
        parts = [term()]
        while peek() == "or":
            take("or")
            parts.append(term())
        return parts[0] if len(parts) == 1 else ["or", *parts]

    def term() -> Node:
        parts = [atom()]
        while peek() == "and":
            take("and")
            parts.append(atom())
        return parts[0] if len(parts) == 1 else ["and", *parts]

    def atom() -> Node:
        if peek() == "paren" and toks[pos][1] == "(":
            take("paren")
            inner = expr()
            if take("paren") != ")":
                raise ValueError(")")
            return inner
        name = take("field")
        op = take("op")
        return [op, name, take("value")]

    try:
        tree = expr()
    except ValueError:
        return None
    return tree if pos == len(toks) else None


def supported(text: str) -> bool:
    return not (text or "").strip() or parse(text) is not None


def _same(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return a == b


def evaluate(node: Node, values: dict[str, str]) -> bool:
    op = node[0]
    if op == "or":
        return any(evaluate(n, values) for n in node[1:])
    if op == "and":
        return all(evaluate(n, values) for n in node[1:])
    have = str(values.get(node[1]) or "")
    eq = have != "" and _same(have, str(node[2])) if node[2] != "" else have == ""
    return eq if op == "=" else not eq


def shown(rule: str, values: dict[str, str]) -> bool:
    """Whether a field with this rule is shown: no rule, or a rule outside the subset, is always shown."""
    node = parse(rule) if rule else None
    return True if node is None else evaluate(node, values)


def fields_in(node: Node) -> list[str]:
    if node[0] in ("or", "and"):
        return [f for n in node[1:] for f in fields_in(n)]
    return [str(node[1])]


_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


def css_show(node: Node, choice_fields: set[str]) -> list[str] | None:
    """Compound selectors for the form element (any one matching means the field is shown) for a rule on choice
    fields only, else ``None``.

    Choice fields are radio buttons named ``f_<field>``; ``=`` is ``:has(<checked>)`` and ``<>`` is
    ``:not(:has(<checked>))``. The rule is put in or-of-ands form first."""

    def dnf(n: Node) -> list[list[Node]]:
        if n[0] == "or":
            return [c for x in n[1:] for c in dnf(x)]
        if n[0] == "and":
            out: list[list[Node]] = [[]]
            for x in n[1:]:
                out = [a + b for a in out for b in dnf(x)]
            return out
        return [[n]]

    sels = []
    for conj in dnf(node):
        parts = []
        for op, name, val in conj:
            if name not in choice_fields or not _SAFE.match(str(val)):
                return None
            has = f':has(input[name="f_{name}"][value="{val}"]:checked)'
            parts.append(has if op == "=" else f":not({has})")
        sels.append("".join(parts))
    return sels


def css_rules(rules: dict[str, str], choice_fields: set[str], form_id: str = "entry") -> str:
    """A stylesheet that hides each field (``.q-<field>``) whose rule is false, for the rules ``css_show`` can
    express. Written as ``#form:not(<shown>) .q-<field> {display: none}``, so a browser without ``:has`` drops the
    rule and shows the field: the server's check still applies (a hidden field is never required or written)."""
    out = []
    for name, rule in rules.items():
        node = parse(rule) if rule else None
        sels = css_show(node, choice_fields) if node is not None else None
        if sels and re.fullmatch(r"[a-z][a-z0-9_]*", name):
            out.append(f"#{form_id}:not({', '.join(sels)}) .q-{name} {{ display: none; }}")
    return "\n".join(out) + ("\n" if out else "")
