"""text_keys: a console text key cannot go wrong silently (D-1220, review L-4, journey review A-M4 and G-5).

    python -m tools.text_keys            # exit 1 on a problem, each named with its file and line; `make lint`

The console's catalogue (``services/console/i18n.py``, en, ja, zh-TW) is joined from about forty modules with a plain
``dict.update``: ``i18n.py`` joins some, ``i18n_home.py`` others, and a page module joins its own when it is imported
(``admin_flags.py``, the break-glass pages, ``acting.py``). A key two modules define with different words was silently
won by the later one (``edc.title`` made the EDC connection page read "EDC prefill"), and a key nobody defines showed
as the raw key ("life.vstate.unplanned" on the participant page). This tool reads every definition where it is
written, so the loser of an override is seen too, and fails on:

* **a conflicting double**: one key, one language, two different texts (in two modules, or twice in one dict, where
  Python keeps the second without a word). The same text twice is listed, not failed;
* **an unseen source**: a key the served catalogue holds that no definition here wrote, or holds with words no
  definition wrote (a new way of joining keys this reader does not know: teach it, ``definitions``);
* **a missing key**: a key a template or the Python code asks for with a literal (``t('x.y')``, ``translate(lang,
  "x.y")``, a key handed to a nav macro) that the catalogue does not have;
* **a dynamic family** (``t('life.vstate.' + v.status)``, ``translate(lang, f"life.state.{s}")``) that is neither
  checked member by member (``FAMILIES``: every value the code can produce has its key) nor listed in
  ``UNCHECKED_FAMILIES`` with the reason; and a family no catalogue key starts with (a misspelled prefix);
* **a refused spelling** of one of the twenty core words (``tools.core_words``, ``services/console/core_words.yaml``;
  it also reads the job mails, the report titles and the refusal sentences, ``core_words.SERVICE_CATALOGUES``).

It also checks the live preflight's texts (``tb_common.preflight``, :func:`preflight_problems`): the host's
``python3`` prints them, so they are not in the console's catalogue, and each is checked in all three languages.

It reads the source with ``ast`` and ``ast.literal_eval`` only (no code of a module runs, apart from importing the
console to read the served catalogue); a definition that is not a literal is a problem of its own.

What it cannot see is caught at run time: in the test suite's own process (``console.i18n.STRICT``, switched on by
``tests/conftest.py``) ``translate`` raises on a key no catalogue has, so a page a test renders cannot show a raw
key. A box, a box a test starts included, keeps the old fallback (the key itself), so a missing text never takes a
page down; ``TB_STRICT_TEXT=1`` turns strict mode on for a box by hand.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "services" / "console"
TEMPLATES = CONSOLE / "templates"
LANG_OF = {"EN": "en", "JA": "ja", "ZH": "zh-TW"}
LANGS = ("en", "ja", "zh-TW")
#: a name that holds one language's words: ``EN``, ``_HOME_EN``, ``_CAP_JA`` ...
CAT_NAME = re.compile(r"^(?:\w*_)?(EN|JA|ZH)$")
#: keys the code computes into every catalogue (no literal): the key and where its words come from
COMPUTED = {"footer.statement": "libs/tb_common/wording.py STATEMENT (joined in services/console/i18n.py)"}


@dataclass(frozen=True)
class Definition:
    lang: str
    key: str
    text: str
    where: str  # services/console/i18n_x.py:12

    @property
    def module(self) -> str:
        return self.where.split(":")[0]


# ------------------------------------------------------------------ where keys are defined
def _module(path: Path) -> ModuleType:
    return importlib.import_module(f"console.{path.stem}")


@dataclass(frozen=True)
class Dynamic:
    """A definition in a catalogue dict that is not a literal the reader can read (``**something``, an f-string key, a
    name): a problem, named with its place, so that no definition escapes the double check unseen."""

    where: str
    expr: str


_NO = object()  # not a literal


def _literal(node: ast.expr) -> Any:
    """The value of a literal node (a string, implicit concatenation and parentheses included; a tuple or a dict of
    literals), read with ``ast.literal_eval``; ``_NO`` for anything else. No code is evaluated."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _NO


def _tables(tree: ast.Module) -> dict[str, ast.expr]:
    """The module-level ``NAME = {...}`` displays: the tables a comprehension or a loop joins under a prefix."""
    out: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


Entry = tuple[str, Any, int] | Dynamic


def _key_parts(key: ast.expr, name: str) -> list[str | None] | None:
    """The pieces of ``f"prefix.{name}"``: strings, and None where the table's key goes; None for another shape."""
    if not isinstance(key, ast.JoinedStr):
        return None
    parts: list[str | None] = []
    for part in key.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            parts.append(part.value)
        elif (
            isinstance(part, ast.FormattedValue)
            and part.conversion == -1
            and part.format_spec is None
            and isinstance(part.value, ast.Name)
            and part.value.id == name
        ):
            parts.append(None)
        else:
            return None
    return parts


def _comprehension(dc: ast.DictComp, tables: dict[str, ast.expr], bound: dict[str, int], where: str) -> list[Entry]:
    """``{f"prefix.{k}": v for k, v in TABLE.items()}`` (or ``v[i]``, ``i`` the loop's index over the three
    catalogues) over a literal module-level ``TABLE``, read without running code; any other shape is ``Dynamic``."""
    dyn: list[Entry] = [Dynamic(where, ast.unparse(dc))]
    gen = dc.generators[0]
    it, target = gen.iter, gen.target
    if (
        len(dc.generators) != 1
        or gen.ifs
        or gen.is_async
        or not isinstance(target, ast.Tuple)
        or len(target.elts) != 2
        or not isinstance(it, ast.Call)
        or it.args
        or not isinstance(it.func, ast.Attribute)
        or it.func.attr != "items"
        or not isinstance(it.func.value, ast.Name)
        or it.func.value.id not in tables
    ):
        return dyn
    kn, vn = (e.id if isinstance(e, ast.Name) else "" for e in target.elts)
    table = _literal(tables[it.func.value.id])
    parts = _key_parts(dc.key, kn)
    if not isinstance(table, dict) or parts is None or not kn or not vn:
        return dyn
    val = dc.value
    index: int | None = None
    if isinstance(val, ast.Subscript) and isinstance(val.value, ast.Name) and val.value.id == vn:
        sl = val.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, int):
            index = sl.value
        elif isinstance(sl, ast.Name) and sl.id in bound:
            index = bound[sl.id]
        else:
            return dyn
    elif not (isinstance(val, ast.Name) and val.id == vn):
        return dyn
    return [
        ("".join(str(k) if p is None else p for p in parts), v if index is None else v[index], dc.lineno)
        for k, v in table.items()
    ]


def _entries(node: ast.expr, tables: dict[str, ast.expr], bound: dict[str, int], rel: str) -> list[Entry]:
    """Each ``key: value`` of a dict display (or of a comprehension over a table), read as literals."""
    if isinstance(node, ast.DictComp):
        return _comprehension(node, tables, bound, f"{rel}:{node.lineno}")
    if not isinstance(node, ast.Dict):
        return [Dynamic(f"{rel}:{node.lineno}", ast.unparse(node))]
    out: list[Entry] = []
    for k, v in zip(node.keys, node.values, strict=True):
        if k is None:  # ``**mapping``
            if isinstance(v, ast.Name) and isinstance(tables.get(v.id), ast.Dict):
                if not CAT_NAME.match(v.id):  # a catalogue-named table is read where it is written
                    out += _entries(tables[v.id], tables, bound, rel)
                continue
            out += _entries(v, tables, bound, rel)
            continue
        key, text = _literal(k), _literal(v)
        if key is _NO or text is _NO:
            out.append(Dynamic(f"{rel}:{k.lineno}", f"{ast.unparse(k)}: {ast.unparse(v)}"))
        else:
            out.append((key, text, k.lineno))
    return out


def _dicts(tree: ast.Module) -> Iterator[tuple[str, ast.Dict]]:
    """(language, dict display) for every display that holds one language's words: assigned to a catalogue name,
    passed to ``<catalogue name>.update``, or one value of a ``{"en": {...}, "ja": {...}, "zh-TW": {...}}``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, ast.Dict):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                m = CAT_NAME.match(getattr(target, "id", ""))
                if m:
                    yield LANG_OF[m.group(1)], node.value
            d = node.value
            if d.keys and all(isinstance(k, ast.Constant) and k.value in LANGS for k in d.keys):
                for k, v in zip(d.keys, d.values, strict=True):
                    if isinstance(v, ast.Dict) and isinstance(k, ast.Constant):
                        yield str(k.value), v
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            m = CAT_NAME.match(node.func.value.id)
            if m:
                yield LANG_OF[m.group(1)], node.args[0]


def _loop_updates(tree: ast.Module) -> Iterator[tuple[str, ast.expr, dict[str, int]]]:
    """(language, the joined expression, the loop's index) of ``for _i, _cat in enumerate((EN, JA, ZH)):
    _cat.update({...})`` at module level (i18n_audit: a label table ``name -> (en, ja, zh-TW)`` joined under a
    prefix), one per language."""
    for node in tree.body:
        if not isinstance(node, ast.For):
            continue
        it, numbered = node.iter, False
        if isinstance(it, ast.Call) and getattr(it.func, "id", "") == "enumerate" and it.args:
            it, numbered = it.args[0], True
        if not isinstance(it, ast.Tuple):
            continue
        langs = [CAT_NAME.match(e.id) if isinstance(e, ast.Name) else None for e in it.elts]
        targets = node.target.elts if isinstance(node.target, ast.Tuple) else [node.target]
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names or not all(langs):
            continue
        for i, m in enumerate(langs):
            bound = {names[0]: i} if numbered and len(names) == 2 else {}
            for sub in node.body:
                call = sub.value if isinstance(sub, ast.Expr) else None
                if (
                    m is not None
                    and isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "update"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == names[-1]
                    and call.args
                ):
                    yield LANG_OF[m.group(1)], call.args[0], bound


def read_definitions(served: dict[str, dict[str, str]] | None = None) -> tuple[list[Definition], list[Dynamic]]:
    """Every definition of a text key in the console's modules, in file order, read from the source with ``ast`` and
    ``ast.literal_eval`` only (no code runs), and every definition that is not a literal (``Dynamic``). A dict counts
    when one of its keys is in the served catalogue of its language, or when it holds something that is not a literal
    (``_SRC_EN`` of i18n_demoja is the raw material of a comprehension: its keys are not text keys)."""
    served = served if served is not None else served_catalogue()
    out: list[Definition] = []
    dynamic: list[Dynamic] = []
    for path in sorted(CONSOLE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"\b(EN|JA|ZH)\b|\"zh-TW\"", text):
            continue
        tree = ast.parse(text)
        rel = path.relative_to(ROOT).as_posix()
        tables = _tables(tree)
        groups = [(lang, _entries(d, tables, {}, rel)) for lang, d in _dicts(tree)]
        groups += [(lang, _entries(e, tables, bound, rel)) for lang, e, bound in _loop_updates(tree)]
        for lang, entries in groups:
            dyn = [e for e in entries if isinstance(e, Dynamic)]
            rows = [
                e for e in entries if not isinstance(e, Dynamic) and isinstance(e[0], str) and isinstance(e[1], str)
            ]
            if not dyn and not any(k in served[lang] for k, _, _ in rows):
                continue
            dynamic += dyn
            out += [Definition(lang, k, v, f"{rel}:{line}") for k, v, line in rows]
    return out, dynamic


def definitions(served: dict[str, dict[str, str]] | None = None) -> list[Definition]:
    return read_definitions(served)[0]


def served_catalogue() -> dict[str, dict[str, str]]:
    """The catalogue as the served console has it: every console module imported (a page module joins its keys when
    it is imported, and ``create_app`` imports some only when it builds the app)."""
    for path in sorted(CONSOLE.glob("*.py")):
        if path.stem not in ("__main__",):
            _module(path)
    from console.i18n import CATALOGUES

    return CATALOGUES


@dataclass(frozen=True)
class Conflict:
    lang: str
    key: str
    rows: tuple[Definition, ...]  # in file order; at least two different texts


def doubles(defs: Iterable[Definition]) -> tuple[list[Conflict], list[Conflict]]:
    """(conflicting doubles, harmless doubles): a key defined more than once in one language, with different texts
    or with the same text."""
    by: dict[tuple[str, str], list[Definition]] = defaultdict(list)
    for d in defs:
        by[(d.lang, d.key)].append(d)
    bad: list[Conflict] = []
    same: list[Conflict] = []
    for (lang, key), rows in sorted(by.items()):
        if len(rows) > 1:
            (bad if len({r.text for r in rows}) > 1 else same).append(Conflict(lang, key, tuple(rows)))
    return bad, same


def unseen(defs: Iterable[Definition], served: dict[str, dict[str, str]]) -> list[str]:
    """Keys (or texts) the served catalogue holds that no definition here wrote."""
    texts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for d in defs:
        texts[(d.lang, d.key)].add(d.text)
    out = []
    for lang in LANGS:
        for key, text in sorted(served[lang].items()):
            if key in COMPUTED:
                continue
            got = texts.get((lang, key))
            if not got:
                out.append(f"{lang} {key}: in the served catalogue, defined nowhere this reader looks")
            elif text not in got:
                out.append(f"{lang} {key}: served with words no definition has (something else overwrote it)")
    return out


# ------------------------------------------------------------------ where keys are used
@dataclass(frozen=True)
class Use:
    key: str  # a whole key, or a family's prefix
    where: str
    family: bool = False


#: ``t`` and J-7's ``tp`` (D-1251: the plain key with ``layout.plain_menu`` on, the key itself with it off)
_TPL_LITERAL = re.compile(r"""\btp?\(\s*(['"])([^'"{}]+?)\1\s*[,)]""")
_TPL_FAMILY = re.compile(r"""\btp?\(\s*(['"])([^'"{}]*?)\1\s*[+~]""")  # t_or has its own fallback
#: macros whose second argument is a key the macro hands to ``t`` (``_nav.html`` item)
_TPL_MACRO = re.compile(r"""\bitem\(\s*(['"])[^'"]*\1\s*,\s*(['"])([^'"]+)\2""")


#: ``t('a' if x else 'b')``: both branches are keys
_TPL_IF = re.compile(r"""\btp?\(\s*(['"])([^'"{}]+?)\1\s+if\s+[^()]*?\s+else\s+(['"])([^'"{}]+?)\3\s*[,)]""")
#: ``{% set k = 'x.' + … %}`` later asked as ``t(k)``: a family of its own
_TPL_SET = re.compile(r"""\{%-?\s*set\s+\w+\s*=\s*(['"])([a-z][a-z0-9_.]*\.)\1\s*[+~]""")
_TPL_SET_IF = re.compile(
    r"""\{%-?\s*set\s+\w+\s*=\s*(['"])([a-z][a-z0-9_.]*\.)\1\s*[+~][^%]*?\belse\s+(['"])([a-z][a-z0-9_.]*\.)\3\s*[+~]"""
)


def template_uses() -> list[Use]:
    out: list[Use] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = path.relative_to(ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            out += [Use(m.group(2), f"{rel}:{n}") for m in _TPL_LITERAL.finditer(line)]
            out += [Use(m.group(3), f"{rel}:{n}") for m in _TPL_MACRO.finditer(line)]
            out += [Use(m.group(2), f"{rel}:{n}", family=True) for m in _TPL_FAMILY.finditer(line)]
            for m in _TPL_IF.finditer(line):
                out += [Use(m.group(2), f"{rel}:{n}"), Use(m.group(4), f"{rel}:{n}")]
            out += [Use(m.group(2), f"{rel}:{n}", family=True) for m in _TPL_SET.finditer(line)]
            out += [Use(m.group(4), f"{rel}:{n}", family=True) for m in _TPL_SET_IF.finditer(line)]
    return out


#: a problem page's key: ``problem.html`` renders ``t(key)`` for ``h.problem(400, "key")``, ``_Problem(…)``,
#: ``reveal.refuse(…, 403, "key")`` (the string right after the status)
_PROBLEM_CALLS = {"problem", "_Problem", "refuse"}  # backend.Problem carries a service code (dc.err.<code>), not a key
#: problem keys that only ever answer JSON on /api/: never rendered, never translated
API_ONLY = {
    "bad": "services/console/edc_door.py: the EDC door's API answers JSON on /api/, never translated",
    "login.code": "services/console/home.py /api/v1/session: answers JSON on /api/, never translated",
}


def _branches(node: ast.expr) -> list[ast.expr]:
    """Both branches of ``"a" if x else "b"`` (nested too); the node itself otherwise."""
    if isinstance(node, ast.IfExp):
        return _branches(node.body) + _branches(node.orelse)
    return [node]


#: the functions that take a text key: ``translate(lang, key)`` and the pages' ``t(key)``
_CALLS = {"translate": 1, "t": 0}


def _prefix(node: ast.expr) -> str | None:
    """The literal start of a key built at run time (``f"life.state.{s}"``, ``"x." + y``); None when it has none."""
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return str(node.values[0].value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            return node.left.value
        return _prefix(node.left)
    return None


def python_uses() -> list[Use]:
    out: list[Use] = []
    for path in sorted(CONSOLE.glob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            where = f"{rel}:{node.lineno}"
            if name in _PROBLEM_CALLS:
                args = node.args
                for i in range(len(args) - 1):
                    st, k = args[i], args[i + 1]
                    if isinstance(st, ast.Constant) and type(st.value) is int and 400 <= st.value < 600:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value not in API_ONLY:
                            out.append(Use(k.value, where))
                        break
                continue
            at = _CALLS.get(name)
            if at is None:
                continue
            if name == "t" and len(node.args) >= 2 and getattr(node.args[0], "id", "") == "lang":
                at = 1  # an orchestrator-style t(lang, key)
            if len(node.args) <= at:
                continue
            for arg in _branches(node.args[at]):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.append(Use(arg.value, where))
                else:
                    pre = _prefix(arg)
                    if pre:
                        out.append(Use(pre, where, family=True))
    return out


# ------------------------------------------------------------------ the dynamic families
def _values(module: str, name: str) -> Callable[[], Iterable[str]]:
    """The members of a tuple, a dict's keys or a set the code takes a family's suffix from."""

    def get() -> Iterable[str]:
        return [str(v) for v in getattr(importlib.import_module(module), name)]

    return get


def _assigned(path: str, function: str, var: str) -> Callable[[], Iterable[str]]:
    """Every string the function assigns to ``var``: the values it can produce, read from the code itself (the
    participant page's visit states: ``visit_status`` sets ``status`` to "unplanned", which no tuple listed)."""

    def get() -> Iterable[str]:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
        return [
            n.value.value
            for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == var for t in n.targets)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        ]

    return get


def _union(*parts: Callable[[], Iterable[str]]) -> Callable[[], Iterable[str]]:
    return lambda: sorted({v for p in parts for v in p()})


def _guide_pages() -> Iterable[str]:
    from console.guides import ROLE_PAGES

    return {slug for pages in ROLE_PAGES.values() for slug, _ in pages}


def _view_keys() -> Iterable[str]:
    from console.people_lists import VIEWS

    return sorted({v.key for v in VIEWS})


#: a family checked member by member: its prefix and every suffix the code can produce
FAMILIES: dict[str, Callable[[], Iterable[str]]] = {
    "life.vstate.": _union(
        _values("datacore.lifecycle", "VISIT_STATES"),
        _assigned("services/datacore/lifecycle.py", "visit_status", "status"),
    ),
    "life.state.": _values("datacore.lifecycle", "STATES"),
    "pm.jobtype.": _values("console.plain_menu", "JOB_TYPE_WORDS"),  # J-7 (D-1251): every job type, and "other"
    "life.reason.sf.": _values("datacore.lifecycle", "SCREEN_FAIL_REASONS"),
    "life.reason.wd.": _values("datacore.lifecycle", "WITHDRAW_REASONS"),
    "life.anchor.": _values("datacore.lifecycle", "ANCHORS"),
    # 10C-14: how a visit window counts, and why a day is off at the site (the schedule page)
    "life.unit.": lambda: ("days", "working"),
    "life.daysoff.why.": _values("tb_common.workdays", "DAY_OFF_KINDS"),
    "dataops.layer.row.": _values("console.country_profile", "KEYS"),  # 10C-25 (D-1250)
    "dataops.layer.source.": _values("console.country_profile", "SOURCES"),
    # D-1253: the kinds of a night's record-id counts on the data-ops batch page
    "dataops.ids.kind.": lambda: [k for k, _ in importlib.import_module("console.dataops_page").ID_COUNTS],
    "life.daysoff.end.": lambda: ("soon", "past"),  # Calendar.runs_out
    "registry.status.": _values("orchestrator.candidates", "STATUSES"),
    "sstate.": _values("console.sitestore", "STUDY_STATES"),
    "role.": _values("console.auth", "ROLES"),
    "lang.name.": _values("console.i18n", "LANGS"),
    "help.role.": _values("console.guides", "ROLES"),
    # the provenance search page (D-1155): its five search fields and the two kinds of event the index holds
    "prov.f.": lambda: ("model", "build_sha", "prompt_sha", "prompt_id", "prompt_version"),
    "prov.event.": lambda: ("used", "confirmed"),
    # the study state page's list of what comes before Open (WALK-2, D-1154): the SAE type and the IRB record
    "sstate.before.": lambda: ("sae", "irb", "committee"),  # 10C-4 (D-1227): the Japan profile's committee
    # 10C-4 (D-1227): the Japan profile's committee page (kinds, committees, findings, refused fields)
    "cmt.kind.": _union(_values("tb_common.committees", "KINDS"), lambda: ["none"]),
    "cmt.permission_is.": _values("tb_common.committees", "KINDS"),
    "cmt.committee.": _values("tb_common.committees", "COMMITTEES"),
    "cmt.f.": _values("tb_common.committees", "CODES"),
    "cmt.bad.": _values("tb_common.committees", "BAD_FIELDS"),
    "help.page.": _union(_values("console.step4", "HELP_SLUGS"), _guide_pages),
    "guide.page.": _guide_pages,
    "life.gloss.": _values("console.guides", "GLOSSARY"),
    "log.xlsx.col.": _union(
        lambda: [c for c in _values("datacore.sponsor", "LOG_COLUMNS")() if c != "screening_no"],
        _values("console.screening_log", "PROXY_COLUMNS"),  # 10C-19 (D-1232): at the end while the setting is on
    ),
    # 10C-19 (D-1232): consent by a representative and assent: the warnings, the relation and reason codes
    "consent.proxy.w.": _values("datacore.proxy_consent", "FLAGS"),
    "consent.proxy.short.": _values("datacore.proxy_consent", "FLAGS"),
    "consent.proxy.rel.": _values("datacore.proxy_consent", "RELATIONS"),
    "consent.proxy.why.": _values("datacore.proxy_consent", "ASSENT_WHY"),
    "consent.proxy.proceed.": _values("datacore.proxy_consent", "PROCEED_REASONS"),
    "nav.grp.": _values("console.phone", "MENU_GROUPS"),  # J-3 (D-1222): the groups of "More" behind the flag
    # the box's first-run page (10K-1): the countries, the retention days asked where TrialBox has no rules, and the
    # SS-MIX2 order-number keys
    "firstrun.country.": _values("tb_common.site_country", "COUNTRIES"),
    "firstrun.retention.": _values("tb_common.retention", "OVERRIDABLE"),
    "firstrun.ssmix2_order_numbers.": _values("tb_common.site_country", "SSMIX2_ORDER_NUMBERS"),
    "firstrun.printed_dates.": _values("tb_common.dates", "PRINTED_STYLES"),  # 10C-13
    "firstrun.year_basis.": _values("tb_common.dates", "YEAR_BASES"),  # 10C-15
    # J-2 (D-1221): a person's one state, every name and the state of facts that could not be read
    "person.state.": _union(_values("console.person_state", "STATES"), lambda: ["unknown"]),
    # J-5 (D-1223): the two lists of people and the views of each, behind the flag layout.people_lists
    "people.": _values("console.people_lists", "LISTS"),
    "people.view.": _view_keys,
    "people.side.": _values("console.people_lists", "LISTS"),
    "tier.lacks.": _values("console.tier_words", "WORDED"),  # 10E-17 (D-1244): the tier's worded absences
}

_RUN = "a value of stored data or of a service's answer (a state, a kind, a source): no one list in the code holds it"
_ERR = "a refusal, error or failure code that a service or a form returns"
_DONE = "the word a page is sent back with after an action (?done=...), set by the route that redirects"
_OWN = "a problem page's heading or reason, asked with t_or after a set: a key with none has the general one"
_AUDIT = "an audit kind: tests/console/test_audit_browser.py holds every one the code writes"
#: a family not checked member by member, with the reason. What a test renders is still checked: under the suite a
#: missing member raises (``console.i18n.STRICT``). A family asked with ``t_or`` has its own fallback and is not listed.
UNCHECKED_FAMILIES: dict[str, str] = {
    "audit.kind.": _AUDIT,
    **dict.fromkeys(("problem.h.", "problem.why."), _OWN),
    **dict.fromkeys(
        (
            "cmd.refused.",
            "dc.err.",
            "edc.err.",
            "conflicts.err.",
            "dataops.err.",
            "edc.why.",
            "firstrun.err.",
            "miss.",
            "rc.err.",
            "s20.why.",
            "sae.why.",
            "site.check.why.",
            "site.fix.",
            "site.miss.",
            "totp.failed.",
        ),
        _ERR,
    ),
    **dict.fromkeys(
        (
            "bg.done.",
            "copy.done.",
            "dataops.done.",
            "dc.done.",
            "dev.done.",
            "edc.done.",
            "nm.done.",
            "site.fact.done.",
            "site.help.done.",
            "site.people.done.",
            "team.log.done.",
            "team.optout.done.",
            "team.ref.done.",
            "users.done.",
            "wb.done.",
        ),
        _DONE,
    ),
    **dict.fromkeys(
        (
            "account.notice.",
            "admin.jobs.",
            "admin.jobs.confirm.",
            "admin.notice.",
            "admin.tab.",
            "aff.",
            "as.",
            "audit.verify.",
            "bg.reason.",
            "bg.what.",
            "cap.",
            "capv.",
            "class.",
            "cohort.help.",
            "confirm.outcome.",
            "conflicts.state.",
            "consent.flag.",
            "consent.record.",
            "dataops.feed.",
            "dataops.light.",
            "dataops.state.",
            "day.",
            "dc.dir.",
            "dc.kept.",
            "demo.ack.",
            "dev.kind.",
            "dev.state.",
            "dev.text.",
            "edc.action.",
            "edc.cite.",
            "edc.fate.",
            "edc.kind.",
            "edc.result.",
            "edc.source.",
            "edc.switch.",
            "edc.trail.method.",
            "edc.what.",
            "edc.word.",
            "elsewhere.",
            "ex.rule.",
            "ex.src.",
            "factor.held.",
            "feedback.flag.",
            "feedback.rating.",
            "firstrun.chartno.kind.",
            "firstrun.source.",
            "flags.kind.",
            "health.line.",
            "how.",
            "icf.act.",
            "icf.w.",
            "identity.mfa.",
            "identity.oidc.",
            "instruments.licence.",
            "irbt.f.",
            "irbt.hint.",
            "items.fit.",
            "items.storable.",
            "life.clock.party.",
            "life.go.",
            "life.visits.",
            "mark.",
            "next.",
            "nm.answer.",
            "notices.help.",
            "office.",
            "opinion.",
            "opinion.says.",
            "ops.action.",
            "ops.confirm.",
            "ops.state.",
            "ops.tab.",
            "ops.update.",
            "outcome.",
            "ov.",
            "overview.models.canary.",
            "pre.later.",
            "rc.write.mode.",
            "reading.",
            "reason.",
            "received.kind.",
            "ref.doc.lang.",
            "registry.source.",
            "request.proposal.source.",
            "requests.kind.",
            "requests.secret.",
            "rescreen.group.",
            "rescreen.reason.",
            "rescreen.was.",
            "reveal.reason.",
            "s20.class.",
            "s20.pins.",
            "sae.flag.",
            "sae.kind.",
            "sae.rule.source.",
            "sae.set.",
            "sae.state.",
            "sae.tk.",
            "sae.trail.",
            "sae.yesno.",
            "setup.cohort.",
            "setup.scope.",
            "setup.type.",
            "sid.",
            "sid.hint.",
            "sid.registry.",
            "site.chart.method.",
            "site.check.kind.",
            "site.check.opt.",
            "site.codes.kind.",
            "site.codes.list.",
            "site.codes.method.",
            "site.demo.",
            "site.domain.",
            "site.facts.none.",
            "site.facts.show.",
            "site.fix.kind.",
            "site.gloss.",
            "site.overall.",
            "site.pc.",
            "site.q.",
            "site.role.",
            "site.sheets.kind.",
            "site.state.",
            "site.verdict.",
            "site.wiz.",
            "src.",
            "sstate.effect.",
            "stage.",
            "steps.",
            "team.answer.",
            "team.channel.",
            "team.decline.",
            "team.ev.",
            "team.irb.w.",
            "team.log.ev.",
            "team.log.result.",
            "team.optout.ev.",
            "team.optout.src.",
            "team.purpose.",
            "team.role.",
            "team.route.",
            "team.staff.",
            "team.state.",
            "team.task.",
            "team.view.",
            "tier.",
            "verdict.",
            "verdict.exclusion.",
            "wb.",
            "wb.list.",
            "wb.pipe.",
            "wb.task.",
        ),
        _RUN,
    ),
}


def problems() -> list[str]:
    served = served_catalogue()
    defs, dynamic = read_definitions(served)
    out = [f"dynamic definition at {d.where}: {d.expr[:100]} (not a literal: write it as one)" for d in dynamic]
    bad, _same = doubles(defs)
    for c in bad:
        rows = "; ".join(f"{r.where} {r.text!r}" for r in c.rows)
        out.append(f"conflicting double {c.lang} {c.key}: {rows}")
    out += [f"unseen source: {u}" for u in unseen(defs, served)]
    en = served["en"]
    uses = template_uses() + python_uses()
    for u in uses:
        if not u.family and u.key not in en:
            out.append(f"missing key {u.key!r} used at {u.where}")
    for prefix in sorted({u.key for u in uses if u.family}):
        where = next(u.where for u in uses if u.family and u.key == prefix)
        if prefix in FAMILIES:
            for suffix in FAMILIES[prefix]():
                if prefix + suffix not in en:
                    out.append(f"missing key {prefix + suffix!r} of the family {prefix!r} used at {where}")
        elif prefix not in UNCHECKED_FAMILIES:
            out.append(f"dynamic family {prefix!r} used at {where}: in neither FAMILIES nor UNCHECKED_FAMILIES")
        if not any(k.startswith(prefix) for k in en):
            out.append(f"dynamic family {prefix!r} used at {where}: no catalogue key starts with it")
    used = {u.key for u in uses if u.family}
    out += [
        f"dynamic family {p!r} is listed but nothing uses it" for p in sorted({*FAMILIES, *UNCHECKED_FAMILIES} - used)
    ]
    from tools import core_words  # 9k-16 (D-1371): a core word has one spelling per language

    out += core_words.problems(defs)
    return out + preflight_problems()


def preflight_problems() -> list[str]:
    """10K-3 (D-1361): the preflight's own texts (``tb_common.preflight``: the groups, each check's label and next
    action, the time-out's, the summary). They live outside the console's catalogue because the host's ``python3``
    prints them too; the first-run page, ``doctor --preflight`` and later the console's doctor page (10K-5) and the IT
    one-page (10K-18) show them. Each must be there, non-empty, in en, ja and zh-TW, and a ja or zh-TW text must not
    be the English one."""
    from tb_common import preflight

    where = "libs/tb_common/preflight.py"
    texts = preflight.all_texts()
    out = [f"preflight text {name} has no {lg} words ({where})" for name, lg, t in texts if not t.strip()]
    en = {name: t for name, lg, t in texts if lg == "en"}
    out += [
        f"preflight text {name} {lg} is the English text ({where})"
        for name, lg, t in texts
        if lg != "en" and t.strip() and t == en.get(name)
    ]
    return out


def main(argv: list[str] | None = None) -> int:
    found = problems()
    for p in found:
        print(p)
    print(f"text_keys: {len(found)} problem(s)", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
