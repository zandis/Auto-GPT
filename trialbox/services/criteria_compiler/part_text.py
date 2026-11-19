"""The comments a rule-set part's CQL and SQL may hold: the compiler's own, and nothing else (plan 10 row 10D-28;
D-1369, the third review's B2).

A part carries the compiled CQL and SQL as their bytes: removing a comment from code could change what it means, so a
comment is never stripped. Each comment is held against what the compiler writes instead (``compile_cql.generator``
and ``compile_sql.generator``): the generated header of the file, each criterion's line (its id, kind and the
criterion text of the part's own IR, as the generator writes it), and the fixed comments of the shared library
``TB_Common``. Any other comment (a reviewer's note, a name, a pasted line) refuses the export, naming the file and the
line; the receiving box checks the same.

The scanner knows the two languages' strings and quoted names (a ``//`` inside ``'http://loinc.org'`` is no comment).

Only comments are checked. **String literals are not**: no literal grammar is held against the compiler's, so a
literal is free text the approver may have typed (``define "X": 'any words'``, ``SELECT 'any words'``) and travels as
written, like the criterion text and the other free-text fields D-1369 names under "What travels".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

#: the library line of a CQL file: its name and version
LIBRARY = re.compile(r"^library\s+([A-Za-z0-9_]+)\s+version\s+'([^'\n]{1,64})'", re.M)


def comments(text: str, lang: str) -> list[tuple[int, str]]:
    """``(line, comment)`` of every comment in ``text`` (``lang`` "cql" or "sql"), the comment with its markers;
    a line comment without its line break and trailing spaces."""
    out: list[tuple[int, str]] = []
    i, n, line = 0, len(text), 1
    quotes = ("'", '"', "`") if lang == "cql" else ("'", '"')
    line_mark = "//" if lang == "cql" else "--"
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
        elif ch in quotes:
            j = i + 1
            while j < n:
                if lang == "cql" and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    if lang == "sql" and j + 1 < n and text[j + 1] == ch:  # '' inside an SQL string
                        j += 2
                        continue
                    break
                j += 1
            line += text.count("\n", i, j + 1)
            i = j + 1
        elif text.startswith(line_mark, i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append((line, text[i:j].rstrip()))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append((line, text[i:j]))
            line += text.count("\n", i, j)
            i = j
        else:
            i += 1
    return out


def _sql_text(text: str) -> str:
    """``compile_sql.generator._comment``: the criterion text on one line, at most 150 characters."""
    return " ".join(text.split())[:150]


def _cql_text(text: str) -> str:
    return text.strip()[:160].replace("*/", "* /")


def allowed(path: str, text: str, ruleset: str, version: str, criteria: Iterable[Mapping[str, Any]]) -> set[str]:
    """The comments the compiler writes in the part's file ``path`` (``cql/<name>.cql`` or ``sql/<ID>.sql``)."""
    crit = [(str(c.get("id")), str(c.get("kind")), str(c.get("text") or "")) for c in criteria]
    if path.startswith("sql/"):
        from criteria_compiler.compile_sql.generator import HEADER, MARK

        head = HEADER.format(ruleset=ruleset, version=version, mark=MARK)
        return {ln.rstrip() for ln in head.splitlines() if ln.strip()} | {
            f"-- {cid} ({kind}): {_sql_text(t)}".rstrip() for cid, kind, t in crit
        }
    from criteria_compiler.compile_cql.generator import _env, render_common

    if path == "cql/TB_Common.cql":
        return {c for _ln, c in comments(render_common(), "cql")}
    m = LIBRARY.search(text)
    library, lib_version = (m.group(1), m.group(2)) if m else ("", "")
    head = _env.get_template("library.cql.j2").render(
        library=library, ruleset=ruleset, version=lib_version, lookback=0, codesystems=[], codes=[], valuesets=[],
        defines=[],
    )  # fmt: skip
    return {c for _ln, c in comments(head, "cql")} | {f"/* {cid} ({kind}): {_cql_text(t)} */" for cid, kind, t in crit}


def problems(path: str, data: bytes, ruleset: str, version: str, criteria: Iterable[Mapping[str, Any]]) -> list[str]:
    """Each comment of ``path`` the compiler does not write, as ``<path> line <n>``; empty when there is none."""
    text = data.decode("utf-8")
    lang = "sql" if path.startswith("sql/") else "cql"
    ok = allowed(path, text, ruleset, version, list(criteria))
    return [f"{path} line {ln}" for ln, c in comments(text, lang) if c not in ok]
