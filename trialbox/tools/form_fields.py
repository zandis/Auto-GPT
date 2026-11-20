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
# 9k-6a (D-1376): the console templates whose POST forms do not use the field macro yet (templates/_fields.html).
# One line per template: <template> <raw POST forms> <why it is not converted>. `python -m tools.form_fields` holds it
# against the tree (`tests/unit/test_form_fields_guard.py`): a new raw POST form fails until it is converted or its
# template's line says why; a converted form lowers its line in the same pull request (9k-6b), and a line at 0 goes.
# `python -m tools.form_fields --write` rewrites the counts from the tree and keeps each reason.
"""

FORM = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.S | re.I)
POST = re.compile(r"""\bmethod\s*=\s*["']?post\b""", re.I)
FIELDS = re.compile(r"""\bdata-fields\s*=\s*["']([^"']*)["']""", re.I)
RAW_FIELD = re.compile(r"""<(?:select|textarea)\b|<input\b(?![^>]*\btype\s*=\s*["']?(?:hidden|submit)\b)""", re.I)
IMPORT = re.compile(r"""\{%-?\s*import\s+["']_fields\.html["']\s+as\s+fm\s+with\s+context""")


@dataclass(frozen=True)
class Form:
    template: str
    name: str | None  # the data-fields name of a converted form; None for a raw one
    body: str


def post_forms(path: Path, root: Path) -> list[Form]:
    """The POST forms of one template, in order."""
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(root).as_posix()
    out: list[Form] = []
    for m in FORM.finditer(text):
        if POST.search(m.group(1)):
            named = FIELDS.search(m.group(1))
            out.append(Form(rel, named.group(1) if named else None, m.group(2)))
    return out


def scan(root: Path = TEMPLATES) -> dict[str, list[Form]]:
    """Every template under ``root`` with a POST form, by its path relative to ``root``."""
    out: dict[str, list[Form]] = {}
    for p in sorted(root.rglob("*.html")):
        forms = post_forms(p, root)
        if forms:
            out[p.relative_to(root).as_posix()] = forms
    return out


def read_list(text: str) -> tuple[dict[str, tuple[int, str]], list[str]]:
    """The list's lines as {template: (count, reason)}, and the lines it cannot read."""
    out: dict[str, tuple[int, str]] = {}
    bad: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[1].isdigit() or parts[0] in out:
            bad.append(f"{RATCHET.name}:{n}: cannot read {line!r} (<template> <count> <reason>, once per template)")
            continue
        out[parts[0]] = (int(parts[1]), parts[2].strip() if len(parts) > 2 else "")
    return out, bad


def converted(tree: dict[str, list[Form]]) -> dict[str, str]:
    """{form name: template} of every converted form."""
    return {f.name: t for t, forms in tree.items() for f in forms if f.name is not None}


def problems(root: Path = TEMPLATES, ratchet_text: str | None = None) -> list[str]:
    """Every way the tree and the list disagree, and every converted form that breaks the macro's contract."""
    tree = scan(root)
    listed, out = read_list(RATCHET.read_text(encoding="utf-8") if ratchet_text is None else ratchet_text)
    raw = {t: sum(1 for f in forms if f.name is None) for t, forms in tree.items()}
    for t, n in sorted(raw.items()):
        if n == 0:
            continue
        if t not in listed:
            out.append(f"{t}: {n} POST form(s) outside the field macro and not on the list: convert them to "
                       f"templates/_fields.html (D-1376) or add '{t} {n} <why not yet>' to {RATCHET.name}")  # fmt: skip
        elif n > listed[t][0]:
            out.append(f"{t}: {n} POST form(s) outside the field macro, the list says {listed[t][0]}: a new form uses "
                       f"the macro, or the line says why it cannot yet")  # fmt: skip
    for t, (n, reason) in sorted(listed.items()):
        have = raw.get(t)
        if not (root / t).is_file():
            out.append(f"{t}: on the list but not in the tree: remove its line from {RATCHET.name}")
        elif not have:
            out.append(f"{t}: on the list with {n} but every POST form of it uses the macro: remove its line")
        elif have < n:
            out.append(f"{t}: {have} POST form(s) outside the macro, the list says {n}: lower the line to {have}")
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
    old, _ = read_list(old_text)
    lines = [HEADER.rstrip("\n")]
    for t, forms in sorted(scan(root).items()):
        n = sum(1 for f in forms if f.name is None)
        if n:
            lines.append(f"{t} {n} {old.get(t, (0, NEW_REASON))[1] or NEW_REASON}")
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
    raw = sum(1 for forms in tree.values() for f in forms if f.name is None)
    listed = sum(1 for forms in tree.values() if any(f.name is None for f in forms))
    print(f"form_fields: {len(converted(tree))} converted form(s); {raw} raw POST form(s) in {listed} template(s); "
          f"{len(found)} problem(s)")  # fmt: skip
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
