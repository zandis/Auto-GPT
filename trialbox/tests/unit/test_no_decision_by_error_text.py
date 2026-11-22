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
``services/gateway/core.py`` (a model called busy by the endings of collected error texts; not about a patient).

F-4 (#639, 7078734731): ``detail`` and ``reason`` are a code or a typed field in some classes (a refusal's stable
code, an HTTP error's parsed body) and words in others. Reading one, comparing it whole (folded or trimmed too) with a
code, testing it for emptiness, parsing it or showing it is no decision by text (those places are listed in
``READ_AS_CODE``). Deciding by its words is: ``"x" in e.detail``; a string search or a regular expression over it;
ordering it; a part of it, or it inside a longer text (an f-string, ``%``, ``.format``, ``+``), compared; it compared
with a sentence, or with a name the module binds to one; a ``match`` on it with such cases; a lookup in a mapping
keyed by sentences; it handed to a helper (one defined in the module is read one level; another may search it). The
error under a second name, ``e.__cause__``, ``vars(e)["detail"]`` and ``getattr`` are the same error. A name assigned
from any of these is a decision too. Not seen: a name not bound in the module (an imported constant or mapping reads
as a code), a code-like literal (ASCII letters, digits and ``_.:/-`` only) compared whole, the words read outside the ``except`` block."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
#: the places found, each read (2026-11-13), with whose it is and what it does: a type, a status or a typed field
#: read inside a helper; a sentence of the service's own error class; or the words of another service's refusal
#: (adapter/publish.py, sitesetup/service.py: the lake's). The one that gave "no facts" for a failure
#: (services/edc/prefill.py) is gone with D-684. A new place fails the test until it is read and listed.
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
    "services/orchestrator/scenarios/screen_cascade.py": (
        1,
        "SCREEN: _transport_fault(exc) reads the embed service error's type and HTTP status to wait for a restart "
        "(D-902), no text",
    ),
    "services/sitesetup/service.py": (
        3,
        "site set-up: the lake's refusal of a rebuild by its type, its 409 and header, then the answer's words; "
        "and lake_down(exc) (D-709, #538), which reads the error's type and its status, no text",
    ),
}

#: F-4 (#639, 7078734731): the places that read a caught error's ``detail`` / ``reason`` in a condition, a comparison
#: or a lookup and are no decision by its words: each read, with its verdict. Exact by file and by how many lines; a
#: new one fails until it is read and listed (a decision by the words fails the test above instead). Read through a
#: helper and not counted here: services/console/dataops_page.py:187 (``_detail`` parses the refusal's body; the
#: branches are by HTTP status, then by its typed fields).
READ_AS_CODE: dict[str, tuple[int, str]] = {
    "libs/tb_common/llm.py": (
        5,
        "the prompt registry's and the gateway's stable refusal codes, compared whole or "
        "looked up in MODEL_FAULTS: a decision by a code (178, 539, 541, 543, 545)",
    ),
    "libs/tb_common/workdays.py": (1, "the codec's reason cut to 160 characters for a message: a display (280)"),
    "services/channels/native/engine.py": (1, "the refusal's code 'model_busy' compared whole: a decision by a code"),
    "services/console/backend.py": (
        4,
        "the orchestrator's refusal parsed (json.loads) and its message shown; the only "
        "branch is a type check of the parsed body: a display (396, 413, 554, 555)",
    ),
    "services/console/site_pages.py": (1, "the refusal's typed field 'column', shown: a display (647)"),
    "services/gateway/core.py": (
        2,
        "the gateway's own refusal code looked up in RETRY_AFTER: a decision by a code (439, 440)",
    ),
}

#: what reads an error's text
_TEXT_CALLS = {"str", "repr", "format", "ascii"}
#: what reads its type
_TYPE_CALLS = {"type", "isinstance", "issubclass", "getattr", "hasattr"}
#: attributes of an error that are its text; R22-14 (G-5, R5): a failed process's output (``CalledProcessError``)
#: and an HTTP error's body are text too
_TEXT_ATTRS = {"args", "message", "msg", "strerror", "stderr", "stdout", "output", "text"}
#: F-4: attributes that are a code or a typed field in some classes and words in others; held by their use (above)
_WORD_ATTRS = {"detail", "reason"}
#: string methods that give the same value folded or trimmed: compared whole with a code, still a code
_SAME = {"lower", "upper", "casefold", "strip", "lstrip", "rstrip", "title", "encode", "decode"}
#: string methods that give a part of the words, or the words inside a longer text
_PARTS = {"replace", "removeprefix", "removesuffix", "split", "rsplit", "splitlines", "partition", "rpartition",
          "format", "join"}  # fmt: skip
#: string methods and regular-expression calls that search the words
_SEARCHES = {"startswith", "endswith", "find", "rfind", "index", "rindex", "count", "__contains__", "search", "match",
             "fullmatch", "findall", "finditer"}  # fmt: skip
#: calls that read no words of what they are given: the type, the length, a parse into fields, a display
_NO_WORDS = _TYPE_CALLS | {"len", "bool", "id", "loads", "literal_eval", "model_validate_json", "flash", "render",
                           "escape", "print", "debug", "info", "warning", "error", "exception", "critical"}  # fmt: skip


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


class _Module:
    """What the F-4 reading needs of a whole module: the names bound to a sentence (or to a collection holding one),
    the names bound to a mapping keyed by sentences, and the functions defined in it (a helper is read one level)."""

    def __init__(self, tree: ast.AST) -> None:
        self.texts: set[str] = set()
        self.text_maps: set[str] = set()
        self.defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                self.defs.setdefault(n.name, n)
            elif isinstance(n, ast.Assign | ast.AnnAssign) and n.value is not None:
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                names = {t.id for t in targets if isinstance(t, ast.Name)}
                if _sentence(n.value):
                    self.texts |= names
                elif _text_map(n.value):
                    self.text_maps |= names


_CODE_SHAPE = re.compile(r"[A-Za-z0-9_.:/-]*")


def _sentence(node: ast.AST) -> bool:
    """A literal that is a sentence, not a code: a string that is not of a code's shape (ASCII letters, digits and
    ``_.:/-`` only: a space, or a letter of another script, makes it words, e.g. a Japanese sentence has no space),
    or a collection holding one."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bytes):
            return _CODE_SHAPE.fullmatch(node.value.decode("latin-1")) is None
        return isinstance(node.value, str) and _CODE_SHAPE.fullmatch(node.value) is None
    return isinstance(node, ast.Tuple | ast.List | ast.Set) and any(_sentence(e) for e in node.elts)


def _text_map(node: ast.AST) -> bool:
    """A mapping literal keyed by sentences."""
    return isinstance(node, ast.Dict) and any(k is not None and _sentence(k) for k in node.keys)


def _empty(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in (None, "", b"")


class _Words:
    """F-4: the words of ``detail`` / ``reason`` of one caught error, and the names that carry them in its block."""

    def __init__(self, errs: set[str], module: _Module, whole: set[str] | None = None) -> None:
        self.errs = set(errs)  # the error and its other names (``e2 = exc``)
        self.m = module
        self.whole: set[str] = set(whole or ())  # names that hold the words as they are
        self.parts: set[str] = set()  # ... a part of them, or them inside a longer text
        self.decided: set[str] = set()  # ... the outcome of a search of them

    def err(self, node: ast.AST) -> bool:
        """The error, under any of its names, or what it carries (``exc.__cause__``, ``exc.response``)."""
        if isinstance(node, ast.Name):
            return node.id in self.errs
        return isinstance(node, ast.Attribute) and node.attr not in _WORD_ATTRS and self.err(node.value)

    def whole_(self, node: ast.AST) -> bool:
        """The words as they are, or folded or trimmed (``.lower()``, ``.strip()``, ``str``)."""
        if isinstance(node, ast.Name):
            return node.id in self.whole
        if isinstance(node, ast.Attribute):
            return node.attr in _WORD_ATTRS and self.err(node.value)
        if isinstance(node, ast.Subscript):  # vars(exc)["detail"], exc.__dict__["reason"]
            key, of = node.slice, node.value
            store = (isinstance(of, ast.Call) and isinstance(of.func, ast.Name) and of.func.id == "vars"
                     and len(of.args) == 1 and self.err(of.args[0])) or (
                isinstance(of, ast.Attribute) and of.attr == "__dict__" and self.err(of.value))  # fmt: skip
            return bool(store) and isinstance(key, ast.Constant) and key.value in _WORD_ATTRS
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "getattr" and len(node.args) >= 2 and self.err(node.args[0]):
                key = node.args[1]
                return isinstance(key, ast.Constant) and key.value in _WORD_ATTRS
            if isinstance(fn, ast.Name) and fn.id in _TEXT_CALLS and node.args:
                return self.whole_(node.args[0])
            if isinstance(fn, ast.Attribute) and fn.attr in _SAME:
                return self.whole_(fn.value)
        return False

    def part(self, node: ast.AST) -> bool:
        """A part of the words (a slice, ``.split()[0]``), or the words inside a longer text (an f-string, ``%``,
        ``.format``, ``+``)."""
        if isinstance(node, ast.Name):
            return node.id in self.parts
        if isinstance(node, ast.Subscript):
            return self.words(node.value)
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in _PARTS:
                return self.words(fn.value) or any(self.words(a) for a in node.args)
            if isinstance(fn, ast.Attribute) and fn.attr in _SAME:
                return self.part(fn.value)
            if isinstance(fn, ast.Name) and fn.id in _TEXT_CALLS and node.args:
                return self.part(node.args[0])
            return False
        if isinstance(node, ast.JoinedStr):
            return any(isinstance(v, ast.FormattedValue) and self.words(v.value) for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            right = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
            return any(self.words(a) for a in right)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.words(node.left) or self.words(node.right)
        return False

    def words(self, node: ast.AST) -> bool:
        return self.whole_(node) or self.part(node)

    def _against(self, a: ast.AST, b: ast.AST) -> bool:
        """``a`` (the words) compared for equality or membership with ``b``: by its words?"""
        if self.part(a):
            return not _empty(b)  # a part of the words compared
        if not self.whole_(a):
            return False
        if _sentence(b) or (isinstance(b, ast.Name) and b.id in self.m.texts):
            return True  # with a sentence, or a name bound to one
        folded = isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute) and a.func.attr in _SAME
        return folded and isinstance(b, ast.Name) and b.id not in self.m.defs  # folded, against a name not read

    def _lookup(self, mapping: ast.AST, key: ast.AST) -> bool:
        keyed = _text_map(mapping) or (isinstance(mapping, ast.Name) and mapping.id in self.m.text_maps)
        return keyed and self.words(key)

    def helper_searches(self, fn: ast.AST, args: list[ast.expr]) -> bool:
        """The words handed to a helper: one defined in the module is read (one level); any other may search them."""
        name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
        if name in _NO_WORDS | _TEXT_CALLS | _SAME | _PARTS | _SEARCHES | {"get"}:  # read by their own rules
            return False
        handed = [i for i, a in enumerate(args) if self.words(a)]
        if not handed:
            return False
        f = self.m.defs.get(name) if isinstance(fn, ast.Name) else None
        if f is None or self.errs == set():  # not in the module, or a helper's helper: it may search them
            return True
        params = [a.arg for a in [*f.args.posonlyargs, *f.args.args]]
        inner = _Words(set(), self.m, whole={params[i] for i in handed if i < len(params)})
        body = [n for b in f.body for n in ast.walk(b)]
        inner.learn(body)
        returned = [n.value for n in body if isinstance(n, ast.Return) and n.value is not None]
        return any(inner.searches(t) for t in [*_tests(body), *returned])

    def searches(self, node: ast.AST) -> bool:
        """Does the expression decide by the words (F-4), not by them as a code or a typed field."""
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id in self.decided:
                return True
            if isinstance(n, ast.Compare):
                sides = [n.left, *n.comparators]
                for op, left, right in zip(n.ops, sides[:-1], sides[1:], strict=True):
                    if isinstance(op, ast.In | ast.NotIn) and self.words(right):
                        return True  # "x" in e.detail: the words are searched
                    if isinstance(op, ast.Lt | ast.LtE | ast.Gt | ast.GtE) and (self.words(left) or self.words(right)):
                        return True  # the words ordered
                    if self._against(left, right) or self._against(right, left):
                        return True
            elif isinstance(n, ast.Subscript) and self._lookup(n.value, n.slice):
                return True  # MAP[e.detail]
            elif isinstance(n, ast.Call):
                fn = n.func
                if isinstance(fn, ast.Attribute) and fn.attr in _SEARCHES:
                    if self.words(fn.value):
                        return True  # e.detail.startswith(...)
                    if any(self.words(a) for a in n.args):
                        return True  # re.search(..., e.detail), PATTERN.match(e.reason)
                if isinstance(fn, ast.Attribute) and fn.attr == "get" and n.args and self._lookup(fn.value, n.args[0]):
                    return True  # MAP.get(e.detail)
                if self.helper_searches(fn, [*n.args, *(k.value for k in n.keywords)]):
                    return True  # the words handed to a helper that searches them, or may
            elif isinstance(n, ast.Match) and self.words(n.subject):
                cases = [p for c in n.cases for p in ast.walk(c.pattern) if isinstance(p, ast.MatchValue)]
                if self.part(n.subject) or any(self._against(n.subject, p.value) for p in cases):
                    return True  # match e.detail: case "Too many fields"
        return False

    def learn(self, body: list[ast.AST]) -> None:
        """The names in the block that carry the error, its words, a part of them, or a search of them."""
        for _ in range(3):  # names assigned from these, and from those
            for n in body:
                if not isinstance(n, ast.Assign | ast.AnnAssign | ast.NamedExpr) or n.value is None:
                    continue
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                names = {t.id for tg in targets for t in ast.walk(tg) if isinstance(t, ast.Name)}
                if isinstance(n.value, ast.Name) and n.value.id in self.errs:
                    self.errs |= names
                elif self.whole_(n.value):
                    self.whole |= names
                elif self.part(n.value):
                    self.parts |= names
                elif self.searches(n.value):
                    self.decided |= names


def _tests(body: list[ast.AST]) -> list[ast.AST]:
    """The conditions of a block, and what decides without one: a comparison, a lookup, a search, a ``match``."""
    out: list[ast.AST] = []
    for n in body:
        if isinstance(n, ast.If | ast.While | ast.IfExp | ast.Assert):
            out.append(n.test)
        elif isinstance(n, ast.Compare | ast.BoolOp | ast.Subscript | ast.Match):
            out.append(n)
        elif isinstance(n, ast.comprehension):
            out.extend(n.ifs)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {*_SEARCHES, "get"}:
            out.append(n)
    return out


def decisions_by_text(root: Path) -> list[str]:
    """``file:line`` of every condition, under ``root``, that reads the text of an error caught there, or hands
    the error to a helper to decide."""
    out = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _Module(tree)
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
            words = _Words({caught}, module)  # F-4
            words.learn(body)
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
            for d in _tests(body):
                if words.searches(d):
                    out.append(f"{path.relative_to(root)}:{getattr(d, 'lineno', 0)}")
    return sorted(set(out))


def reads_as_code(root: Path) -> list[str]:
    """F-4: ``file:line`` of every condition, comparison or lookup that reads a caught error's ``detail`` /
    ``reason`` and is no search of its words."""
    out = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _Module(tree)
        for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name):
            body = [n for b in handler.body for n in ast.walk(b)]
            words = _Words({str(handler.name)}, module)
            words.learn(body)
            for t in _tests(body):
                if not words.searches(t) and any(words.words(x) for x in ast.walk(t)):
                    out.append(f"{path.relative_to(root)}:{getattr(t, 'lineno', 0)}")
    return sorted(set(out))


def test_the_places_that_read_detail_or_reason_as_a_code_are_the_listed_ones() -> None:
    """F-4: a code, a typed field or a display is listed with its verdict, not left out silently."""
    found: dict[str, int] = {}
    for top in ("libs", "services"):
        for hit in reads_as_code(ROOT / top):
            name = f"{top}/{hit.rsplit(':', 1)[0]}"
            found[name] = found.get(name, 0) + 1
    listed = {name: n for name, (n, _) in READ_AS_CODE.items()}
    assert found == listed, sorted(set(found.items()) ^ set(listed.items()))


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
        # R22-14 (G-5, R5): a failed process's output and an HTTP error's body
        '    if "no such table" in exc.stderr:\n        pass\n',
        '    if "no such table" in exc.stdout:\n        pass\n',
        '    if exc.output.endswith(b"busy"):\n        pass\n',
        '    if "quota" in exc.text:\n        pass\n',
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
