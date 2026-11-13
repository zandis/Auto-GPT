"""No code decides by the text of an error it caught (D-651).

Three places told "the lake has no such table" from words in a caught error's text: the proposed facts (D-649), the
cascade's note reader (D-650) and the opt-out registry (D-651). The last one leaned to a pass: another failure
whose text held the words read as "no registry", and no opt-out was applied. The scan of D-700 looks at an error's
text going into an answer or a record; it did not see a text that only decides.

This scan looks at every ``except ... as name`` under ``libs`` and ``services``: the caught error's text (``str``,
``repr``, ``format``, an f-string, ``%``, ``.args``, the error handed to a helper, or a name assigned from any of
these) used in a condition. A decision by the error's type or by a typed field of it is not text.

What the scan does not see (the review of D-651 tried 21 spellings): ``exc.__str__()``, ``traceback.format_exc()``,
``str(exc.__cause__)``, the error under a second name, a text tested outside the ``except`` block, a helper's result
assigned and tested later, ``match str(exc)``. A grep of ``libs`` and ``services`` for these found one real place,
``services/gateway/core.py`` (a model called busy by the endings of collected error texts; not about a patient)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: the places found, each read (2026-11-13), with whose it is and what it does. The one decision by an error's
#: text that could hide a failure (services/edc/prefill.py) is gone with D-684; these decide by a type, a status or a typed field inside a helper,
#: or by a sentence of the service's own error class. A new place fails the test until it is read and listed.
LISTED: dict[str, tuple[int, str]] = {
    "libs/tb_common/jobpoll.py": (1, "library: no_answer(exc) reads the error's type and HTTP status, no text"),
    "libs/tb_llm/timeouts.py": (1, "models: dropped(exc) reads the error's type, no text"),
    "services/adapter/publish.py": (
        1,
        "adapter: _other_generation(exc) reads the lake's refusal by its words ('built again since') to try a "
        "promotion again; theirs",
    ),
    "services/console/entry_pages.py": (
        1,
        "console: err_of(exc) builds the page's error from the EDC error's typed fields; no decision",
    ),
    "services/orchestrator/app.py": (
        1,
        "orchestrator: one sentence of its own ActorError ('no signed-in user') picks 400 over 403",
    ),
    "services/orchestrator/lifecycle_api.py": (
        1,
        "orchestrator: 'classic' in the EDC adapter's own error message (a REDCap project without arms)",
    ),
    "services/sitesetup/service.py": (
        2,
        "site set-up: the lake's refusal of a rebuild by its type, its 409 and header, then the answer's words",
    ),
}

#: what reads an error's text
_TEXT_CALLS = {"str", "repr", "format", "ascii"}
#: what reads its type
_TYPE_CALLS = {"type", "isinstance", "issubclass", "getattr", "hasattr"}
#: attributes of an error that are its text
_TEXT_ATTRS = {"args", "message", "msg", "strerror"}


def _is(node: ast.AST, caught: str) -> bool:
    return isinstance(node, ast.Name) and node.id == caught


def _reads_text(node: ast.AST, caught: str, tainted: set[str]) -> bool:
    """Does the expression read the caught error's text: ``str(e)`` and its kin, an f-string or ``%`` with it,
    ``e.args`` / ``e.message``, or a name assigned from one of these."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in tainted:
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _TEXT_CALLS:
            if any(_is(a, caught) for a in n.args):
                return True
        elif isinstance(n, ast.FormattedValue) and _is(n.value, caught):
            return True
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod):
            right = n.right.elts if isinstance(n.right, ast.Tuple) else [n.right]
            if any(_is(a, caught) for a in right):
                return True
        elif isinstance(n, ast.Attribute) and _is(n.value, caught) and n.attr in _TEXT_ATTRS:
            return True
    return False


def _hands_on(node: ast.AST, caught: str) -> bool:
    """Is the caught error itself handed to a helper (which may read its text; the note reader's did)."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and any(isinstance(a, ast.Name) and a.id == caught for a in n.args):
            name = n.func.id if isinstance(n.func, ast.Name) else ""
            if name not in _TEXT_CALLS and name not in _TYPE_CALLS:
                return True
    return False


def decisions_by_text(root: Path) -> list[str]:
    """``file:line`` of every condition, under ``root``, that reads the text of an error caught there, or hands
    the error to a helper to decide."""
    out = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name):
            caught = handler.name
            assert caught is not None
            tainted: set[str] = set()
            body = [n for b in handler.body for n in ast.walk(b)]
            for _ in range(3):  # names assigned from the error's text, and from those
                for n in body:
                    if not isinstance(n, ast.Assign | ast.AnnAssign | ast.NamedExpr) or n.value is None:
                        continue
                    if _reads_text(n.value, caught, tainted):
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        tainted |= {t.id for tg in targets for t in ast.walk(tg) if isinstance(t, ast.Name)}
            for n in body:
                tests: list[ast.expr] = []
                if isinstance(n, ast.If | ast.While | ast.IfExp | ast.Assert):
                    tests.append(n.test)
                elif isinstance(n, ast.Compare | ast.BoolOp):
                    tests.append(n)
                elif isinstance(n, ast.comprehension):
                    tests.extend(n.ifs)
                for t in tests:
                    if _reads_text(t, caught, tainted) or _hands_on(t, caught):
                        out.append(f"{path.relative_to(root)}:{t.lineno}")
    return sorted(set(out))


def test_the_scan_sees_every_spelling_and_leaves_the_type_alone(tmp_path: Path) -> None:
    head = "try:\n    pass\nexcept Exception as exc:\n"
    by_text = [
        '    if "x" in str(exc):\n        pass\n',
        '    msg = str(exc)\n    if "x" in msg and "y" in msg:\n        pass\n',
        '    if "x" in repr(exc):\n        pass\n',
        '    if "x" in format(exc):\n        pass\n',
        '    if "x" in f"{exc}":\n        pass\n',
        '    if "x" in "%s" % exc:\n        pass\n',
        "    if exc.args and exc.args[0] == 2:\n        pass\n",
        '    if "x" in exc.message:\n        pass\n',
        '    if not missing(exc, "t"):\n        raise\n',
        '    y = 1 if "x" in str(exc) else 2\n',
        '    return_value = "x" in str(exc)\n',
        '    text = str(exc)\n    low = text.lower()\n    while "x" in low:\n        break\n',
        '    z = [1 for _ in range(2) if "x" in str(exc)]\n',
    ]
    by_type = [
        "    if isinstance(exc, KeyError):\n        pass\n",
        "    if type(exc) is KeyError or exc.errno == 2 or getattr(exc, 'reason', '') == 'busy':\n        pass\n",
        "    fault = classify(exc)\n    if fault is None:\n        pass\n",
        "    if exc.status_code == 404 and exc.reason:\n        pass\n",
        "    log.error('x %s', exc)\n    raise RuntimeError(str(exc)) from exc\n",
        "    if other:\n        raise\n",
    ]
    for i, body in enumerate(by_text):
        (tmp_path / f"t{i:02d}.py").write_text(head + body, encoding="utf-8")
    for i, body in enumerate(by_type):
        (tmp_path / f"u{i:02d}.py").write_text(head + body, encoding="utf-8")
    assert sorted({f.split(":")[0] for f in decisions_by_text(tmp_path)}) == [
        f"t{i:02d}.py" for i in range(len(by_text))
    ]


def test_no_code_decides_by_the_text_of_an_error_it_caught() -> None:
    """Exact by file and by how many conditions: a new one in a listed file fails too (the review of this card)."""
    found: dict[str, int] = {}
    for top in ("libs", "services"):
        for hit in decisions_by_text(ROOT / top):
            name = f"{top}/{hit.rsplit(':', 1)[0]}"
            found[name] = found.get(name, 0) + 1
    listed = {name: n for name, (n, _) in LISTED.items()}
    assert found == listed, sorted(set(found.items()) ^ set(listed.items()))
