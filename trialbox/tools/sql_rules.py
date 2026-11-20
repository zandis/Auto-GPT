"""SQL built from strings: fifteen rules written here, run as a static check of the Python code (10G-42 (b)).

Plan 10 row 10G-42 (b) asks for "about 15 rules written here (no registry rule copied in)" for defect (g), SQL built
from strings; review 21 (OT-4) names Semgrep CE as the engine. Semgrep's pip package brings 67 packages (the
OpenTelemetry stack among them) into a new hashed lock, and a test that runs a rule on its fixtures would need it in
the test environment, so the same rules run here on Python's own ``ast`` instead (no new dependency; D-1344). Like
Semgrep CE the analysis stays inside one function: a name is followed back to its assignments in the same function.

What counts as safe by its form (never reported): a literal; ``int()``, ``float()``, ``len()``, ``round()`` or
``bool()`` of anything; a run of placeholders (``", ".join("?" * n)``, ``["%s"] * n``, a comprehension of ``"?"``);
an UPPER_CASE name or attribute (a module or class constant, fixed in code); a name or loop variable whose every
assignment in the function is one of these, or iterates over one of these. Everything else interpolated into SQL text
is a hit, and a hit is either a finding or a ledger line (``tools/sql_rules_ledger.yaml``: path, rule, count and a
reason a reviewer can check, the form of ``tools/security_scan_ignores.yaml``).

    python -m tools.sql_rules [paths ...] [--json OUT] [--check]

Without ``--check`` it reports and exits 0 (report-only in CI until the tree is clean, plan 10 ruling "the page test
warns"); with ``--check`` a file with more hits of a rule than its ledger count exits 1.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tools" / "sql_rules_ledger.yaml"
#: the trees 10G-42 (a) counts (tools/sql_from_strings.json)
DEFAULT_PATHS = ("services", "libs", "deploy")
SKIP_PARTS = {".venv", "__pycache__", "generated", "node_modules"}

RULES: dict[str, str] = {
    "SQLS01": "an f-string with a non-constant value passed as the SQL text of an execute-like call",
    "SQLS02": "a %-formatted string passed as the SQL text of an execute-like call",
    "SQLS03": "a str.format() string passed as the SQL text of an execute-like call",
    "SQLS04": "a string concatenation with a non-constant part passed as the SQL text of an execute-like call",
    "SQLS05": "a str.join() of non-constant parts passed as the SQL text of an execute-like call",
    "SQLS06": "a local variable built from strings (f-string, %, format, +, join) passed as SQL text",
    "SQLS07": "SQL text grown with += by a non-constant part, then passed as SQL text",
    "SQLS08": "sqlalchemy text() given SQL built from strings",
    "SQLS09": "psycopg sql.SQL() given a string built from strings (defeats sql.Identifier and sql.Literal)",
    "SQLS10": "a COPY statement built from strings",
    "SQLS11": "a value written into SQL as a quoted literal ('{x}') instead of a bound parameter",
    "SQLS12": 'an identifier quoted by hand ("{x}") in SQL text, with embedded quotes not doubled',
    "SQLS13": "an IN (...) list made by joining values instead of placeholders",
    "SQLS14": "a LIMIT or OFFSET value interpolated without int()",
    "SQLS15": "an environment variable reaches SQL text",
}
#: the severity a finding of each rule starts at before review (the finding then gives its own, with its basis)
SEVERITY = {r: "Medium" for r in RULES} | {"SQLS11": "High", "SQLS13": "High", "SQLS15": "Low", "SQLS14": "Low"}

#: methods whose first argument (or keyword sql/query/statement) is SQL text, whatever the text looks like
STRICT_SINKS = {
    "execute",
    "executemany",
    "executescript",
    "exec_driver_sql",
    "fetchval",
    "fetchrow",
    "fetchone",
    "fetchall",
    "mogrify",
    "read_sql",
    "read_sql_query",
}
#: methods that take SQL text in this code base but whose name is common: the text must look like SQL
LOOSE_SINKS = {"query", "sql", "_all", "_run", "_q", "_one", "_exec"}
SQL_KWARGS = {"sql", "query", "statement", "stmt"}
SQL_WORDS = re.compile(
    r"\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WITH|CREATE|DROP|ALTER|TRUNCATE|COPY|MERGE|GRANT|REVOKE|"
    r"VALUES|FROM|WHERE|ON\s+CONFLICT|ATTACH|PRAGMA|VACUUM|ANALYZE)\b|\bSET\s+\w+\s*(?:=|TO\b)",
    re.IGNORECASE,
)
# a statement keyword at the start of the text: what makes a string SQL for the rules that look at any string
SQL_START = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|DROP|ALTER|TRUNCATE|COPY|MERGE|GRANT|REVOKE|ATTACH|PRAGMA|SET|"
    r"LOAD|INSTALL|LOCK|COMMENT\s+ON|CALL)\b",
    re.IGNORECASE,
)
PLACEHOLDERS = {"?", "%s", "?,", "?, ", ", ?", ",?", "%s,", "%s, ", ", %s", ",%s"}
SAFE_CALLS = {"int", "float", "len", "round", "bool", "abs", "Identifier", "Literal", "Placeholder"}
CONST_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
ENV_CALLS = {"getenv", "environ"}


@dataclass(frozen=True)
class Hit:
    rule: str
    path: str
    line: int
    what: str  # the interpolated expression(s), as source text

    def place(self) -> str:
        return f"{self.path}:{self.line}"


# ------------------------------------------------------------------------------------------------ expression helpers


def _const_str(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _literal_text(node: ast.AST) -> str:
    """The constant text a string expression carries (the parts between its holes), for keyword tests."""
    if (s := _const_str(node)) is not None:
        return s
    if isinstance(node, ast.JoinedStr):
        return "".join(_literal_text(v) if not isinstance(v, ast.FormattedValue) else " {} " for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _literal_text(node.left) + " " + _literal_text(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return _literal_text(node.func.value)
        if node.func.attr == "join":
            sep = _literal_text(node.func.value)
            parts = node.args[0] if node.args else None
            inner = ""
            if isinstance(parts, (ast.List, ast.Tuple)):
                inner = " ".join(_literal_text(e) for e in parts.elts)
            return sep + " " + inner
    if isinstance(node, ast.IfExp):
        return _literal_text(node.body) + " " + _literal_text(node.orelse)
    return ""


def _is_placeholder_run(node: ast.AST) -> bool:
    """``"?" * n``, ``["?"] * n``, ``("?" for _ in x)``, ``", ".join(<one of these>)``, a literal of placeholders."""
    if (s := _const_str(node)) is not None:
        return s.strip() in PLACEHOLDERS or set(s.replace(" ", "")) <= set("?,") or s.replace(" ", "") in {"", "%s"}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return any(_is_placeholder_run(x) for x in (node.left, node.right)) and all(
            _is_placeholder_run(x) or not isinstance(x, (ast.Constant, ast.List)) for x in (node.left, node.right)
        )
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(_is_placeholder_run(e) for e in node.elts)
    if isinstance(node, (ast.ListComp, ast.GeneratorExp)):
        return _is_placeholder_run(node.elt)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        return _const_str(node.func.value) is not None and bool(node.args) and _is_placeholder_run(node.args[0])
    return False


class Scope:
    """The assignments of one function (or the module), for following a name back to what it was built from."""

    def __init__(self, body: list[ast.stmt], params: set[str]) -> None:
        self.assigns: dict[str, list[ast.AST]] = {}
        self.loops: dict[str, list[ast.AST]] = {}
        self.augs: dict[str, list[ast.AugAssign]] = {}
        self.params = params
        for node in _walk_scope(body):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.assigns.setdefault(t.id, []).append(node.value)
                    elif isinstance(t, ast.Tuple):
                        # a, b = [], []: element by element when the right side is a literal tuple of that length
                        rhs = node.value.elts if isinstance(node.value, ast.Tuple) else []
                        for i, e in enumerate(t.elts):
                            if isinstance(e, ast.Name):
                                same = len(rhs) == len(t.elts)
                                v = rhs[i] if same else ast.Name(id="?unknown", ctx=ast.Load())
                                self.assigns.setdefault(e.id, []).append(v)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                self.assigns.setdefault(node.target.id, []).append(node.value)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                self.augs.setdefault(node.target.id, []).append(node)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                t, it = node.target, node.iter
                rows = it.elts if isinstance(it, (ast.Tuple, ast.List)) else []
                if (
                    isinstance(t, ast.Tuple)
                    and rows
                    and all(isinstance(r, ast.Tuple) and len(r.elts) == len(t.elts) for r in rows)
                ):
                    # for col, val in (("a", x), ("b", y)): col iterates the first column only
                    for i, e in enumerate(t.elts):
                        for name in _target_names(e):
                            col = ast.List(elts=[r.elts[i] for r in rows if isinstance(r, ast.Tuple)], ctx=ast.Load())
                            self.loops.setdefault(name, []).append(col)
                else:
                    for name in _target_names(t):
                        self.loops.setdefault(name, []).append(it)
            elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                self.assigns.setdefault(node.target.id, []).append(node.value)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.attr in {"append", "extend", "insert"}
                and node.args
            ):
                # a list of SQL clauses grown in place: what goes in counts as an assignment of the list
                item = node.args[-1]
                wrapped = item if node.func.attr == "extend" else ast.List(elts=[item], ctx=ast.Load())
                self.assigns.setdefault(node.func.value.id, []).append(wrapped)


def _target_names(t: ast.AST) -> Iterator[str]:
    if isinstance(t, ast.Name):
        yield t.id
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            yield from _target_names(e)


def _walk_scope(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """Every node of a function body, not descending into nested functions or classes (their own scopes)."""
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue  # its own scope: run() visits each function; a class body and a lambda stay in this one
        yield node
        stack.extend(ast.iter_child_nodes(node))


class Checker:
    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        self.hits: set[Hit] = set()
        self.module_scope = Scope(tree.body, set())
        self._visiting: set[tuple[int, str]] = set()

    # ---------------------------------------------------------------- safety of an interpolated value

    def safe(self, node: ast.AST, scope: Scope, depth: int = 0) -> bool:
        if depth > 16:
            return False
        if isinstance(node, ast.Constant):
            return True
        if _is_placeholder_run(node):
            return True
        if isinstance(node, ast.Name):
            if CONST_NAME.match(node.id):
                return True
            vals = scope.assigns.get(node.id, [])
            loops = scope.loops.get(node.id, [])
            if node.id in scope.params or (not vals and not loops):
                return False
            key = (id(scope), node.id)
            if key in self._visiting:
                return True  # q = q + " AND x = ?": the cycle adds nothing; the other assignments decide
            self._visiting.add(key)
            try:
                augs = scope.augs.get(node.id, [])
                return (
                    all(self.safe(a.value, scope, depth + 1) for a in augs)
                    and all(self.safe(v, scope, depth + 1) for v in vals)
                    and all(self._safe_iter(i, scope, depth + 1) for i in loops)
                )
            finally:
                self._visiting.discard(key)
        if isinstance(node, ast.Attribute):
            return bool(CONST_NAME.match(node.attr))
        if isinstance(node, ast.Subscript):
            # CONST[key]: a value of a fixed mapping or tuple
            return self.safe(node.value, scope, depth + 1) and isinstance(node.value, (ast.Name, ast.Attribute))
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in SAFE_CALLS:
                return True
            if name in {"str", "repr"} and isinstance(node.func, ast.Name) and node.args:
                return self.safe(node.args[0], scope, depth + 1)
            if name == "join" and isinstance(node.func, ast.Attribute) and node.args:
                return self.safe(node.func.value, scope, depth + 1) and self._safe_iter(node.args[0], scope, depth + 1)
            if name == "format" and isinstance(node.func, ast.Attribute):
                return self.safe(node.func.value, scope, depth + 1) and all(
                    self.safe(a, scope, depth + 1) for a in [*node.args, *(k.value for k in node.keywords)]
                )
            if name in {"upper", "lower", "strip"} and isinstance(node.func, ast.Attribute):
                return self.safe(node.func.value, scope, depth + 1)
            return False
        if isinstance(node, ast.JoinedStr):
            return all(self.safe(v.value, scope, depth + 1) for v in node.values if isinstance(v, ast.FormattedValue))
        if isinstance(node, ast.FormattedValue):
            return self.safe(node.value, scope, depth + 1)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Mod) and _const_str(node.left) is not None:
                r = node.right
                items = r.elts if isinstance(r, ast.Tuple) else [r]
                return all(self.safe(i, scope, depth + 1) for i in items)
            return self.safe(node.left, scope, depth + 1) and self.safe(node.right, scope, depth + 1)
        if isinstance(node, ast.IfExp):
            return self.safe(node.body, scope, depth + 1) and self.safe(node.orelse, scope, depth + 1)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return all(self.safe(e, scope, depth + 1) for e in node.elts)
        if isinstance(node, (ast.ListComp, ast.GeneratorExp)):
            inner = Scope([], scope.params)
            inner.assigns, inner.loops, inner.augs = dict(scope.assigns), dict(scope.loops), dict(scope.augs)
            for gen in node.generators:
                for n in _target_names(gen.target):
                    inner.loops[n] = [gen.iter]
                    inner.assigns.pop(n, None)
            return self.safe(node.elt, inner, depth + 1)
        return False

    def _safe_iter(self, node: ast.AST, scope: Scope, depth: int) -> bool:
        """An iterable whose items are safe: a constant, a literal of constants, keys/items of a constant."""
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"keys", "values", "items"}
        ):
            return self.safe(node.func.value, scope, depth)
        if isinstance(node, ast.Call) and _call_name(node) in {"enumerate", "sorted", "zip", "reversed", "list"}:
            return all(self._safe_iter(a, scope, depth) for a in node.args)
        if isinstance(node, ast.Call) and _call_name(node) == "range":
            return True
        return self.safe(node, scope, depth)

    def unsafe_parts(self, node: ast.AST, scope: Scope) -> list[ast.AST]:
        """The holes of a string expression that are not safe by their form."""
        if isinstance(node, ast.JoinedStr):
            return [v.value for v in node.values if isinstance(v, ast.FormattedValue) and not self.safe(v, scope)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            r = node.right
            items = r.elts if isinstance(r, ast.Tuple) else [r]
            if isinstance(r, ast.Dict):
                items = list(r.values)
            return [i for i in items if not self.safe(i, scope)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            out: list[ast.AST] = []
            for side in (node.left, node.right):
                if isinstance(side, (ast.JoinedStr, ast.BinOp)):
                    out += self.unsafe_parts(side, scope)
                elif not self.safe(side, scope):
                    out.append(side)
            return out
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "format":
                args = [*node.args, *(k.value for k in node.keywords)]
                return [a for a in args if not self.safe(a, scope)]
            if node.func.attr == "join" and node.args:
                return [] if self._safe_iter(node.args[0], scope, 0) else [node.args[0]]
        if isinstance(node, ast.IfExp):
            return self.unsafe_parts(node.body, scope) + self.unsafe_parts(node.orelse, scope)
        return []

    # ---------------------------------------------------------------- the rules

    def hit(self, rule: str, node: ast.AST, parts: list[ast.AST]) -> None:
        what = ", ".join(sorted({ast.unparse(p)[:80] for p in parts})) or ast.unparse(node)[:80]
        self.hits.add(Hit(rule, self.path, getattr(node, "lineno", 0), what))

    def run(self) -> list[Hit]:
        self._scope(self.tree.body, set())
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                params = {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]}
                params |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
                self._scope(node.body, params - {"self", "cls"})
        return sorted(self.hits, key=lambda h: (h.path, h.line, h.rule, h.what))

    def _sink_arg(self, call: ast.Call) -> tuple[ast.AST | None, bool]:
        """The SQL-text argument of an execute-like call and whether the sink is strict."""
        if not isinstance(call.func, ast.Attribute):
            if isinstance(call.func, ast.Name) and call.func.id in {"read_sql", "read_sql_query"}:
                return (call.args[0] if call.args else None), True
            return None, False
        name = call.func.attr
        if name not in STRICT_SINKS and name not in LOOSE_SINKS:
            return None, False
        arg = call.args[0] if call.args else None
        if arg is None:
            arg = next((k.value for k in call.keywords if k.arg in SQL_KWARGS), None)
        return arg, name in STRICT_SINKS

    def _scope(self, body: list[ast.stmt], params: set[str]) -> None:
        scope = Scope(body, params) if params or body is not self.tree.body else self.module_scope
        sink_names: set[str] = set()
        for node in _walk_scope(body):
            if isinstance(node, ast.Call):
                self._call(node, scope, sink_names)
            if isinstance(node, (ast.JoinedStr, ast.BinOp, ast.Call)):
                self._text_rules(node, scope)
        # SQLS07: a name grown with a non-constant += and passed to a sink in this function
        for name in sink_names:
            for aug in scope.augs.get(name, []):
                if isinstance(aug.op, ast.Add) and not self.safe(aug.value, scope):
                    parts = self.unsafe_parts(aug.value, scope) or [aug.value]
                    self.hit("SQLS07", aug, parts)

    def _call(self, call: ast.Call, scope: Scope, sink_names: set[str]) -> None:
        name = _call_name(call)
        # SQLS08 / SQLS09: the SQL wrappers that must be given literal text
        if name in {"text", "SQL"} and call.args and len(call.args) == 1 and not call.keywords:
            arg = call.args[0]
            is_sa = name == "text" and isinstance(call.func, (ast.Name, ast.Attribute))
            if _const_str(arg) is None and (name == "SQL" or SQL_WORDS.search(self._resolve_text(arg, scope))):
                built = self._built(arg, scope)
                if built is not None:
                    parts = self.unsafe_parts(built, scope)
                    if parts:
                        self.hit("SQLS09" if name == "SQL" else "SQLS08", built, parts)
                elif isinstance(arg, ast.Name) and not self.safe(arg, scope) and (name == "SQL" or is_sa):
                    self.hit("SQLS09" if name == "SQL" else "SQLS08", call, [arg])
        # SQLS10: COPY text built from strings, whatever method takes it
        if name in {"copy", "copy_expert", "copy_from", "copy_to"} and call.args:
            arg = call.args[0]
            built = self._built(arg, scope)
            if built is not None and re.search(r"\bCOPY\b", _literal_text(built), re.I):
                parts = self.unsafe_parts(built, scope)
                if parts:
                    self.hit("SQLS10", built, parts)
        text_arg, strict = self._sink_arg(call)
        if text_arg is None:
            return
        if not strict and not SQL_WORDS.search(self._resolve_text(text_arg, scope)):
            return
        if isinstance(text_arg, ast.Name):
            sink_names.add(text_arg.id)
            for v in scope.assigns.get(text_arg.id, []):
                if self._is_built(v):
                    parts = self.unsafe_parts(v, scope)
                    if parts:
                        self.hit("SQLS06", v, parts)  # at the line that builds it (where ruff's S608 points)
            return
        rule = self._direct_rule(text_arg)
        if rule:
            parts = self.unsafe_parts(text_arg, scope)
            if parts:
                self.hit(rule, text_arg, parts)

    @staticmethod
    def _is_built(node: ast.AST) -> bool:
        return Checker._direct_rule(node) is not None

    @staticmethod
    def _direct_rule(node: ast.AST) -> str | None:
        if isinstance(node, ast.JoinedStr) and any(isinstance(v, ast.FormattedValue) for v in node.values):
            return "SQLS01"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _const_str(node.left) is not None:
            return "SQLS02"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "format":
                # psycopg's sql.SQL("...").format(sql.Identifier(x)) is the safe composition, not str.format
                recv = node.func.value
                return None if isinstance(recv, ast.Call) and _call_name(recv) == "SQL" else "SQLS03"
            if node.func.attr == "join":
                return "SQLS05"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return "SQLS04"
        if isinstance(node, ast.IfExp):
            return Checker._direct_rule(node.body) or Checker._direct_rule(node.orelse)
        return None

    def _built(self, arg: ast.AST, scope: Scope) -> ast.AST | None:
        if self._is_built(arg):
            return arg
        if isinstance(arg, ast.Name):
            for v in scope.assigns.get(arg.id, []):
                if self._is_built(v):
                    return v
        return None

    def _resolve_text(self, arg: ast.AST, scope: Scope) -> str:
        text = _literal_text(arg)
        if isinstance(arg, ast.Name):
            text += " ".join(_literal_text(v) for v in scope.assigns.get(arg.id, []))
            text += " ".join(_literal_text(a.value) for a in scope.augs.get(arg.id, []))
        return text

    def _text_rules(self, node: ast.AST, scope: Scope) -> None:
        """SQLS11 to SQLS15: shapes inside any string that starts like an SQL statement, wherever it goes."""
        if not self._is_built(node) or isinstance(node, ast.IfExp):
            return
        text = _literal_text(node)
        if not (SQL_START.search(text) or (SQL_WORDS.search(text) and re.search(r"\bFROM\b|\bINTO\b|\bSET\b", text))):
            return
        holes = self._holes(node)
        for before, value in holes:
            if value is not None and not self.safe(value, scope):
                quote = before[-1:]
                if quote in {"'", '"'} and not self._doubles_quotes(value, scope, quote):
                    self.hit("SQLS11" if quote == "'" else "SQLS12", node, [value])
                if re.search(r"\bIN\s*\(\s*$", before, re.I) and self._is_value_join(value, scope):
                    self.hit("SQLS13", node, [value])
                if re.search(r"\b(LIMIT|OFFSET)\s*$", before, re.I):
                    self.hit("SQLS14", node, [value])
                if self._from_env(value, scope):
                    self.hit("SQLS15", node, [value])

    def _doubles_quotes(self, value: ast.AST | None, scope: Scope, quote: str, depth: int = 0) -> bool:
        """``x.replace(q, q + q)`` or a quoting helper (a name with quote, ident, escape or lit), directly or through
        every assignment of a local name: the hand quoting escapes what it wraps."""
        if isinstance(value, ast.Call):
            if isinstance(value.func, ast.Attribute) and value.func.attr == "replace" and len(value.args) == 2:
                return _const_str(value.args[0]) == quote and _const_str(value.args[1]) == quote * 2
            return bool(re.search(r"quote|ident|escape|^_?lit$", _call_name(value), re.I))
        if isinstance(value, ast.IfExp):
            return all(
                self._doubles_quotes(v, scope, quote, depth + 1) or self.safe(v, scope)
                for v in (value.body, value.orelse)
            )
        if isinstance(value, ast.Name) and depth < 4:
            vals = scope.assigns.get(value.id, [])
            return bool(vals) and all(self._doubles_quotes(v, scope, quote, depth + 1) for v in vals)
        return False

    def _is_value_join(self, value: ast.AST | None, scope: Scope) -> bool:
        if isinstance(value, ast.Call) and _call_name(value) == "join":
            return not (value.args and _is_placeholder_run(value.args[0]))
        if isinstance(value, ast.Name):
            return any(
                isinstance(v, ast.Call) and _call_name(v) == "join" and not _is_placeholder_run(v.args[0])
                for v in scope.assigns.get(value.id, [])
                if isinstance(v, ast.Call) and v.args
            )
        return False

    def _from_env(self, value: ast.AST | None, scope: Scope, depth: int = 0) -> bool:
        if value is None or depth > 4:
            return False
        for n in ast.walk(value):
            if isinstance(n, ast.Attribute) and n.attr == "environ":
                return True
            if isinstance(n, ast.Call) and _call_name(n) == "getenv":
                return True
            if isinstance(n, ast.Name) and any(
                self._from_env(v, scope, depth + 1) for v in scope.assigns.get(n.id, [])
            ):
                return True
        return False

    @staticmethod
    def _holes(node: ast.AST) -> list[tuple[str, ast.AST | None]]:
        """Each hole of a built string with the constant text just before it."""
        out: list[tuple[str, ast.AST | None]] = []
        if isinstance(node, ast.JoinedStr):
            before = ""
            for v in node.values:
                if isinstance(v, ast.FormattedValue):
                    out.append((before, v.value))
                    before = ""
                else:
                    before += _const_str(v) or ""
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and (s := _const_str(node.left)) is not None:
            r = node.right
            items: list[ast.AST] = list(r.elts) if isinstance(r, ast.Tuple) else [r]
            pieces = re.split(r"%(?:\([^)]*\))?[sdr]", s)
            for i, piece in enumerate(pieces[:-1]):
                out.append((piece, items[i] if i < len(items) and not isinstance(r, ast.Dict) else None))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            flat: list[ast.AST] = []

            def walk(n: ast.AST) -> None:
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                    walk(n.left)
                    walk(n.right)
                else:
                    flat.append(n)

            walk(node)
            before = ""
            for part in flat:
                if (s := _const_str(part)) is not None:
                    before += s
                elif isinstance(part, ast.JoinedStr):
                    continue  # its own holes are visited as their own node
                else:
                    out.append((before, part))
                    before = ""
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            s = _const_str(node.func.value)
            if s is not None:
                args = list(node.args)
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                idx = 0
                for m in re.finditer(r"\{([^{}]*)\}", s):
                    key = m.group(1).split(":")[0].split("!")[0]
                    val: ast.AST | None
                    if key == "":
                        val = args[idx] if idx < len(args) else None
                        idx += 1
                    elif key.isdigit():
                        val = args[int(key)] if int(key) < len(args) else None
                    else:
                        val = kw.get(key)
                    out.append((s[: m.start()].rsplit("}", 1)[-1], val))
        return out


# ------------------------------------------------------------------------------------------------ files, ledger, CLI


def scan_source(source: str, path: str = "<fixture>") -> list[Hit]:
    return Checker(path, ast.parse(source)).run()


def iter_files(paths: list[str]) -> Iterator[Path]:
    for p in paths:
        base = (ROOT / p) if not Path(p).is_absolute() else Path(p)
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for f in files:
            if not SKIP_PARTS & set(f.relative_to(ROOT).parts if f.is_relative_to(ROOT) else f.parts):
                yield f


def scan(paths: list[str]) -> list[Hit]:
    hits: list[Hit] = []
    for f in iter_files(paths):
        rel = str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError:
            continue
        hits += Checker(rel, tree).run()
    return hits


def load_ledger(path: Path = LEDGER) -> dict[str, list[dict[str, Any]]]:
    """``reviewed``: safe hits (path, rule, count, reason); ``findings``: hits that are open findings (path, rule,
    count, ids), counted so a known finding is not reported as new while it waits for its fix."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, list[dict[str, Any]]] = {"reviewed": [], "findings": []}
    for part, need in (
        ("reviewed", ("path", "rule", "count", "reason")),
        ("findings", ("path", "rule", "count", "ids")),
    ):
        for e in data.get(part) or []:
            missing = [k for k in need if not e.get(k)]
            if missing:
                raise ValueError(f"ledger {part} entry {e!r}: missing {missing}")
            if e["rule"] not in RULES:
                raise ValueError(f"ledger {part} entry {e!r}: no rule {e['rule']}")
            if not isinstance(e["count"], int) or e["count"] < 1:
                raise ValueError(f"ledger {part} entry {e!r}: count is a whole number of at least 1")
            out[part].append(e)
    seen = Counter((str(e["path"]), str(e["rule"])) for e in out["reviewed"])
    if dup := [k for k, n in seen.items() if n > 1]:
        raise ValueError(f"ledger: a file and rule written twice in reviewed: {dup}")
    return out


@dataclass
class Verdict:
    new: list[Hit]  # the hits of a file and rule beyond what the ledger accounts for (all of that file's are listed)
    stale: list[str]  # ledger counts above what is found: lower them (a fix, or a moved site)
    reviewed: int  # hits accounted for as safe
    known: dict[str, int]  # finding id(s) -> hits accounted for as open findings


def judge(hits: list[Hit], ledger: dict[str, list[dict[str, Any]]]) -> Verdict:
    by = Counter((h.path, h.rule) for h in hits)
    safe: Counter[tuple[str, str]] = Counter()
    known: Counter[tuple[str, str]] = Counter()
    for e in ledger["reviewed"]:
        safe[(str(e["path"]), str(e["rule"]))] += int(e["count"])
    ids: dict[str, int] = {}
    left = Counter({k: max(0, by[k] - safe[k]) for k in by})  # the hits of each file and rule beyond the safe ones
    for e in ledger["findings"]:
        key = (str(e["path"]), str(e["rule"]))
        known[key] += int(e["count"])
        took = min(int(e["count"]), left[key])
        left[key] -= took
        if took:
            ids[", ".join(e["ids"])] = ids.get(", ".join(e["ids"]), 0) + took
    allowed = safe + known
    new = [h for h in hits if by[(h.path, h.rule)] > allowed[(h.path, h.rule)]]
    stale = [f"{p} {r}: ledger {n}, found {by[(p, r)]}" for (p, r), n in sorted(allowed.items()) if by[(p, r)] < n]
    reviewed = sum(min(n, by[k]) for k, n in safe.items())
    return Verdict(new, stale, reviewed, ids)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS))
    ap.add_argument("--json", type=Path, help="write every hit and the verdict here")
    ap.add_argument("--check", action="store_true", help="exit 1 on a new hit or a stale ledger line")
    ap.add_argument("--rules", action="store_true", help="print the rules and stop")
    args = ap.parse_args(argv)
    if args.rules:
        for r, text in RULES.items():
            print(f"{r} [{SEVERITY[r]}] {text}")
        return 0
    hits = scan(args.paths)
    v = judge(hits, load_ledger())
    counts = Counter(h.rule for h in hits)
    new_counts = Counter(h.rule for h in v.new)
    for h in v.new:
        print(f"{h.place()}: {h.rule} {RULES[h.rule]}: {h.what}")
    for line in v.stale:
        print(f"stale ledger line (fewer hits than its count; lower it): {line}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "rules": RULES,
                    "hits": [asdict(h) | {"new": h in v.new} for h in hits],
                    "by_rule": {r: {"hits": counts[r], "new": new_counts[r]} for r in RULES},
                    "reviewed": v.reviewed,
                    "known_findings": v.known,
                    "stale": v.stale,
                },
                indent=1,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    summary = " ".join(f"{r}={counts[r]}" for r in RULES if counts[r])
    known = sum(v.known.values())
    print(
        f"sql_rules: {len(hits)} hits ({summary or 'none'}): {v.reviewed} reviewed safe, {known} known findings, "
        f"{len(v.new)} new, {len(v.stale)} stale ledger lines"
    )
    return 1 if args.check and (v.new or v.stale) else 0


if __name__ == "__main__":
    sys.exit(main())
