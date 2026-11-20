"""form_fields: every console POST form uses the field macro, or is on the ratchet list with a reason (9k-6a, D-1376).

    python -m tools.form_fields            # exit 1 on a problem, each named with its template
    python -m tools.form_fields --write    # rewrite the list from the tree, keeping each line's reason

A **converted** form carries ``data-fields="<name>"`` on its ``<form>`` and takes every field through
``fm.field(fe, '<name>', ...)`` of ``templates/_fields.html``; its template shows ``fm.error_summary(...)`` and
``fm.title(...)``. Any other ``<form method="post">`` is a **raw** form. ``tools/form_fields_ratchet.txt`` lists each
template that still has raw POST forms, with how many and why. The check fails on:

* a template with raw POST forms that is not on the list, or with more of them than the list says (a new form
  outside the macro: convert it, or add the line with the reason it cannot be converted yet);
* a listed template with fewer raw forms than the list says, or gone from the tree (the list goes down with the
  forms: 9k-6b lowers or removes the line in the same pull request);
* a line without a reason (``--write`` gives a new template the reason ``REASON NEEDED``, which fails);
* a converted form with a field outside the macro (an ``<input>`` other than hidden or submit, a ``<select>`` or a
  ``<textarea>``), with no ``fm.field`` call naming it, a form name used twice, or a template that imports the macro
  without showing the summary and the title's "Error:".

**Typed and action forms (9k-6c, D-1384).** Each raw POST form is first classified by what it takes. A **typed** form
holds at least one control a person edits: an ``<input>`` of a type other than hidden, submit, button, image or reset
(a text field, a file, a checkbox, a radio, or an ``<input>`` with no literal type), a ``<select>`` or a
``<textarea>``. An **action** form holds nothing but hidden inputs and buttons (a button with the CSRF token and perhaps
ids). Only typed raw forms are on the ratchet's first section: an action form cannot be converted to the macro, so it is
not counted there, but each one must be a POST with the token field (``name="csrf"``) and a non-empty ``action``; the
second section lists, per template, the action forms that break that rule today (they can only go down; a new action
form must keep it). The classification reads text: a control drawn by ``{% include %}``, ``{% call %}``,
``{% import %}``,
``{% extends %}`` or by a call in ``{{ }}`` that is not one of the known text helpers (``TEXT_CALLS``) is invisible to
it, so a form with any of these is treated as typed, the stricter class; a control whose ``type`` is written by an
expression (``type="{{ x }}"``) is typed; a form whose controls are all written through ``fm.field`` is converted.

What it reads is the templates' text (a regular expression per form, as the other template lints do); that a
converted form shows its summary and ties each error to its field when a POST fails is proved by rendering it
(``tests/console/test_form_errors_9k6a.py``, one case per form name in ``tests/console/form_cases_9k6a.py``).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "services" / "console" / "templates"
RATCHET = ROOT / "tools" / "form_fields_ratchet.txt"
NEW_REASON = "REASON NEEDED"
HEADER = """\
# 9k-6a (D-1376), 9k-6c (D-1384): the form guard's two lists. `python -m tools.form_fields` holds them against the tree
# (`tests/unit/test_form_fields_guard.py`). One line per template: <template> <count> <reason>.
# `python -m tools.form_fields --write` rewrites the counts from the tree and keeps each reason.
@typed
# TYPED raw POST forms (a form with a control a person edits) that do not use the field macro yet
# (templates/_fields.html):
# a new one fails until it is converted or its template's line says why; a converted form lowers its line in the same
# pull request (9k-6b), and a line at 0 goes. Action forms (hidden inputs and buttons only) are not counted here.
"""
ACTION_HEADER = """\
@action
# ACTION forms (hidden inputs and buttons only) that break the rule: POST, the CSRF field `name="csrf"`, a non-empty
# `action`; as measured on 2026-11-20 (9k-6c). A new action form must keep the rule; these lines only go down.
"""
ACTION_REASON = "action form without the csrf field or the action, as measured (9k-6c)"

FORM = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.S | re.I)
POST = re.compile(r"""\bmethod\s*=\s*["']?post\b""", re.I)
FIELDS = re.compile(r"""\bdata-fields\s*=\s*["']([^"']*)["']""", re.I)
RAW_FIELD = re.compile(r"""<(?:select|textarea)\b|<input\b(?![^>]*\btype\s*=\s*["']?(?:hidden|submit)\b)""", re.I)
# a control a person edits: any <input> but a literal hidden/submit/button/image/reset one, <select>, <textarea>
TYPED_CONTROL = re.compile(
    r"""<(?:select|textarea)\b|<input\b(?![^>]*\btype\s*=\s*["']?(?:hidden|submit|button|image|reset)["'\s/>])""", re.I
)
OPAQUE_STMT = re.compile(r"\{%-?\s*(?:include|call|import|extends|from|macro)\b")
CALL = re.compile(r"([A-Za-z_][\w.]*)\s*\(")
EXPR = re.compile(r"\{\{(.*?)\}\}", re.S)
# calls in {{ }} known to write text, not a control (the catalogue lookups and plain value methods)
TEXT_CALLS = frozenset(
    {
        "t",
        "tp",
        "t_or",
        "pname",
        "get",
        "items",
        "isoformat",
        "join",
        "replace",
        "map",
        "strftime",
        "urlencode",
        "lower",
        "upper",
        "int",
        "string",
        "length",
        "default",
    }
)
CSRF = re.compile(r"""<input\b[^>]*\bname\s*=\s*["']csrf["']""", re.I)
ACTION_ATTR = re.compile(r"""\baction\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
IMPORT = re.compile(r"""\{%-?\s*import\s+["']_fields\.html["']\s+as\s+fm\s+with\s+context""")


@dataclass(frozen=True)
class Form:
    template: str
    name: str | None  # the data-fields name of a converted form; None for a raw one
    body: str
    attrs: str = ""  # the text of the <form ...> tag between "<form" and ">"

    @property
    def typed(self) -> bool:
        """True when the form takes typed input, or holds something the text cannot see through (the stricter class)."""
        return is_typed(self.body)

    def action_problem(self) -> str | None:
        """Why an action form breaks the rule (POST, the csrf field, a non-empty action), or None."""
        found = ACTION_ATTR.search(self.attrs)
        if not found or not (found.group(1) or found.group(2) or "").strip():
            return "no action address"
        if not CSRF.search(self.body):
            return 'no hidden input named "csrf"'
        return None


def is_typed(body: str) -> bool:
    """TYPED: a control a person edits, or an include, call, import or unknown call the text does not show through."""
    if TYPED_CONTROL.search(body) or OPAQUE_STMT.search(body):
        return True
    for expr in EXPR.finditer(body):
        for call in CALL.finditer(expr.group(1)):
            if call.group(1).rsplit(".", 1)[-1] not in TEXT_CALLS:
                return True
    return False


def post_forms(path: Path, root: Path) -> list[Form]:
    """The POST forms of one template, in order."""
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(root).as_posix()
    out: list[Form] = []
    for m in FORM.finditer(text):
        if POST.search(m.group(1)):
            named = FIELDS.search(m.group(1))
            out.append(Form(rel, named.group(1) if named else None, m.group(2), m.group(1)))
    return out


def scan(root: Path = TEMPLATES) -> dict[str, list[Form]]:
    """Every template under ``root`` with a POST form, by its path relative to ``root``."""
    out: dict[str, list[Form]] = {}
    for p in sorted(root.rglob("*.html")):
        forms = post_forms(p, root)
        if forms:
            out[p.relative_to(root).as_posix()] = forms
    return out


def read_sections(text: str) -> tuple[dict[str, dict[str, tuple[int, str]]], list[str]]:
    """The list's two sections, each {template: (count, reason)}: ``typed`` (lines before any marker count there too)
    and ``action`` (after ``@action``), and the lines it cannot read."""
    out: dict[str, dict[str, tuple[int, str]]] = {"typed": {}, "action": {}}
    bad: list[str] = []
    section = "typed"
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.strip() in ("@typed", "@action"):
            section = line.strip()[1:]
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[1].isdigit() or parts[0] in out[section]:
            bad.append(f"{RATCHET.name}:{n}: cannot read {line!r} (<template> <count> <reason>, once per template)")
            continue
        out[section][parts[0]] = (int(parts[1]), parts[2].strip() if len(parts) > 2 else "")
    return out, bad


def read_list(text: str) -> tuple[dict[str, tuple[int, str]], list[str]]:
    """The typed section as {template: (count, reason)}, and the lines the list cannot read."""
    sections, bad = read_sections(text)
    return sections["typed"], bad


def read_action_list(text: str) -> dict[str, tuple[int, str]]:
    """The action section: {template: (action forms breaking the rule, reason)}."""
    return read_sections(text)[0]["action"]


def raw_counts(tree: dict[str, list[Form]]) -> tuple[dict[str, int], dict[str, int]]:
    """(typed raw forms, action forms breaking the rule) per template, the zero ones left out."""
    typed: dict[str, int] = {}
    broken: dict[str, int] = {}
    for t, forms in tree.items():
        for f in forms:
            if f.name is not None:
                continue
            if f.typed:
                typed[t] = typed.get(t, 0) + 1
            elif f.action_problem():
                broken[t] = broken.get(t, 0) + 1
    return typed, broken


def converted(tree: dict[str, list[Form]]) -> dict[str, str]:
    """{form name: template} of every converted form."""
    return {f.name: t for t, forms in tree.items() for f in forms if f.name is not None}


def problems(root: Path = TEMPLATES, ratchet_text: str | None = None) -> list[str]:
    """Every way the tree and the list disagree, and every converted form that breaks the macro's contract."""
    tree = scan(root)
    listed, out = read_list(RATCHET.read_text(encoding="utf-8") if ratchet_text is None else ratchet_text)
    raw, broken = raw_counts(tree)
    actions = read_action_list(RATCHET.read_text(encoding="utf-8") if ratchet_text is None else ratchet_text)
    for t, n in sorted(broken.items()):
        why = next(w for f in tree[t] if f.name is None and not f.typed and (w := f.action_problem()))
        if t not in actions:
            out.append(f"{t}: {n} action form(s) (hidden inputs and buttons only) break the rule and are not on the "
                       f"list ({why}): a POST with the csrf field and an action address")  # fmt: skip
        elif n > actions[t][0]:
            out.append(f"{t}: {n} action form(s) break the rule, the list says {actions[t][0]} ({why}): a new action "
                       f"form is a POST with the csrf field and an action address")  # fmt: skip
    for t, (n, reason) in sorted(actions.items()):
        have = broken.get(t, 0)
        if not (root / t).is_file():
            out.append(f"{t}: on the action list but not in the tree: remove its line from {RATCHET.name}")
        elif not have:
            out.append(f"{t}: on the action list with {n} but every action form of it keeps the rule: remove its line")
        elif have < n:
            out.append(f"{t}: {have} action form(s) break the rule, the list says {n}: lower the line to {have}")
        if not reason:
            out.append(f"{t}: the action line gives no reason")
    for t, n in sorted(raw.items()):
        if n == 0:
            continue
        if t not in listed:
            out.append(f"{t}: {n} typed POST form(s) outside the field macro and not on the list: convert them to "
                       f"templates/_fields.html (D-1376) or add '{t} {n} <why not yet>' to {RATCHET.name}")  # fmt: skip
        elif n > listed[t][0]:
            out.append(f"{t}: {n} typed POST form(s) outside the field macro, the list says {listed[t][0]}: a new "
                       f"form uses the macro, or the line says why it cannot yet")  # fmt: skip
    for t, (n, reason) in sorted(listed.items()):
        have = raw.get(t, 0)
        if not (root / t).is_file():
            out.append(f"{t}: on the list but not in the tree: remove its line from {RATCHET.name}")
        elif not have:
            out.append(f"{t}: on the list with {n} but no typed POST form of it is outside the macro: remove its line")
        elif have < n:
            out.append(f"{t}: {have} typed POST form(s) outside the macro, the list says {n}: lower the line to {have}")
        if not reason or reason == NEW_REASON:
            out.append(f"{t}: the line gives no reason why its forms are not converted")
    seen: dict[str, str] = {}
    for t, forms in sorted(tree.items()):
        text = (root / t).read_text(encoding="utf-8")
        names = [f.name for f in forms if f.name is not None]
        if names:
            if not IMPORT.search(text):
                out.append(f'{t}: a data-fields form without {{% import "_fields.html" as fm with context %}}')
            if "fm.error_summary(" not in text:
                out.append(f"{t}: converted forms but no fm.error_summary(...) at the top of the page")
            if "fm.title(" not in text:
                out.append(f"{t}: converted forms but no fm.title(...) in the page's title block")
        for f in forms:
            if f.name is None:
                continue
            if not f.name or f.name in seen:
                out.append(f"{t}: the form name {f.name!r} is empty or used twice (also in {seen.get(f.name)})")
            seen[f.name] = t
            for m in RAW_FIELD.finditer(f.body):
                out.append(
                    f"{t}: form {f.name!r} has a field outside the macro: {f.body[m.start() : m.start() + 60]!r}"
                )
            if not re.search(r"""fm\.field\(\s*fe\s*,\s*["']""" + re.escape(f.name) + r"""["']""", f.body):
                out.append(f"{t}: form {f.name!r} has no fm.field(fe, '{f.name}', ...) call")
    return out


def render_list(root: Path = TEMPLATES, old_text: str = "") -> str:
    """The list as the tree has it now, each kept line's reason kept, a new line's reason ``REASON NEEDED``."""
    old, _ = read_sections(old_text)
    typed, broken = raw_counts(scan(root))
    lines = [HEADER.rstrip("\n")]
    lines += [f"{t} {n} {old['typed'].get(t, (0, NEW_REASON))[1] or NEW_REASON}" for t, n in sorted(typed.items())]
    lines.append(ACTION_HEADER.rstrip("\n"))
    for t, n in sorted(broken.items()):
        lines.append(f"{t} {n} {old['action'].get(t, (0, ACTION_REASON))[1] or ACTION_REASON}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--write"]:
        old = RATCHET.read_text(encoding="utf-8") if RATCHET.exists() else ""
        RATCHET.write_text(render_list(TEMPLATES, old), encoding="utf-8")
    elif args:
        print(__doc__)
        return 2
    found = problems()
    for p in found:
        print(p)
    tree = scan()
    typed, broken = raw_counts(tree)
    every = [f for forms in tree.values() for f in forms if f.name is None]
    n_action = sum(1 for f in every if not f.typed)
    print(f"form_fields: {len(converted(tree))} converted form(s); {len(every)} raw POST form(s): "
          f"{sum(typed.values())} typed in {len(typed)} template(s), {n_action} action of which "
          f"{sum(broken.values())} break the rule in {len(broken)} template(s); {len(found)} problem(s)")  # fmt: skip
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
