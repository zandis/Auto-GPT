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
  ``UNCHECKED_FAMILIES`` with the reason; and a family no catalogue key starts with (a misspelled prefix).

What it cannot see is caught at run time: under the test suite (``TB_STRICT_TEXT=1``, set by ``tests/conftest.py``)
``translate`` raises on a key no catalogue has, so a page a test renders cannot show a raw key. A box keeps the old
fallback (the key itself), so a missing text never takes a page down.
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
#: the shape of a text key: lower-case words joined by dots (``life.vstate.due``, ``role.cro``)
KEY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_-]+)+$")
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


def _entries(node: ast.Dict, scope: dict[str, Any]) -> Iterator[tuple[str, Any, int]]:
    """Each ``key: value`` of a dict display, evaluated in its module's namespace (a ``**{...}`` unpack too)."""

    def value(expr: ast.expr) -> Any:
        return eval(compile(ast.Expression(expr), "<text_keys>", "eval"), dict(scope))

    for k, v in zip(node.keys, node.values, strict=True):
        if k is None:  # ``**mapping``
            for kk, vv in value(v).items():
                yield str(kk), vv, v.lineno
        else:
            yield value(k), value(v), k.lineno


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


def _loop_updates(tree: ast.Module, scope: dict[str, Any]) -> Iterator[tuple[str, dict[Any, Any], int]]:
    """(language, joined dict, line) of ``for _i, _cat in enumerate((EN, JA, ZH)): _cat.update({...})`` at module
    level (i18n_audit: a label table ``name -> (en, ja, zh-TW)`` joined under a prefix), one per language."""
    for node in tree.body:
        if not isinstance(node, ast.For):
            continue
        it, numbered = node.iter, False
        if isinstance(it, ast.Call) and getattr(it.func, "id", "") == "enumerate" and it.args:
            it, numbered = it.args[0], True
        if not isinstance(it, ast.Tuple) or not all(CAT_NAME.match(getattr(e, "id", "")) for e in it.elts):
            continue
        names = [t.id for t in (node.target.elts if isinstance(node.target, ast.Tuple) else [node.target])]  # type: ignore[attr-defined]
        for i, elt in enumerate(it.elts):
            lang = LANG_OF[CAT_NAME.match(elt.id).group(1)]  # type: ignore[attr-defined,union-attr]
            bound = dict(zip(names, (i, None) if numbered else (None,), strict=False))
            for sub in node.body:
                call = sub.value if isinstance(sub, ast.Expr) else None
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "update"
                    and getattr(call.func.value, "id", "") == names[-1]
                    and call.args
                ):
                    expr = ast.Expression(call.args[0])
                    got = eval(compile(expr, "<text_keys>", "eval"), {**scope, **bound})
                    yield lang, got, call.lineno


def definitions(served: dict[str, dict[str, str]] | None = None) -> list[Definition]:
    """Every literal definition of a text key in the console's modules, in file order. A dict counts when at least
    one of its keys is in the served catalogue of its language (``_SRC_EN`` of i18n_demoja is the raw material of a
    comprehension, not a catalogue: its keys are not text keys)."""
    served = served if served is not None else served_catalogue()
    out: list[Definition] = []
    for path in sorted(CONSOLE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"\b(EN|JA|ZH)\b|\"zh-TW\"", text):
            continue
        tree = ast.parse(text)
        found = list(_dicts(tree))
        if not found:
            continue
        scope = vars(_module(path))
        rel = path.relative_to(ROOT).as_posix()
        groups = [(lang, list(_entries(d, scope))) for lang, d in found]
        groups += [(lang, [(k, v, line) for k, v in got.items()]) for lang, got, line in _loop_updates(tree, scope)]
        for lang, entries in groups:
            rows = [(k, v, line) for k, v, line in entries if isinstance(k, str) and isinstance(v, str)]
            if not any(k in served[lang] for k, _, _ in rows):
                continue
            out += [Definition(lang, k, v, f"{rel}:{line}") for k, v, line in rows]
    return out


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


_TPL_LITERAL = re.compile(r"""\bt\(\s*(['"])([^'"{}]+?)\1\s*[,)]""")
_TPL_FAMILY = re.compile(r"""\bt\(\s*(['"])([^'"{}]*?)\1\s*[+~]""")  # t_or has its own fallback
#: macros whose second argument is a key the macro hands to ``t`` (``_nav.html`` item)
_TPL_MACRO = re.compile(r"""\bitem\(\s*(['"])[^'"]*\1\s*,\s*(['"])([^'"]+)\2""")


def template_uses() -> list[Use]:
    out: list[Use] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = path.relative_to(ROOT).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            out += [Use(m.group(2), f"{rel}:{n}") for m in _TPL_LITERAL.finditer(line)]
            out += [Use(m.group(3), f"{rel}:{n}") for m in _TPL_MACRO.finditer(line)]
            out += [Use(m.group(2), f"{rel}:{n}", family=True) for m in _TPL_FAMILY.finditer(line)]
    return out


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
            at = _CALLS.get(name)
            if at is None:
                continue
            if name == "t" and len(node.args) >= 2 and getattr(node.args[0], "id", "") == "lang":
                at = 1  # an orchestrator-style t(lang, key)
            if len(node.args) <= at:
                continue
            arg = node.args[at]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append(Use(arg.value, f"{rel}:{node.lineno}"))
            else:
                pre = _prefix(arg)
                if pre:
                    out.append(Use(pre, f"{rel}:{node.lineno}", family=True))
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


#: a family checked member by member: its prefix and every suffix the code can produce
FAMILIES: dict[str, Callable[[], Iterable[str]]] = {
    "life.vstate.": _union(
        _values("datacore.lifecycle", "VISIT_STATES"),
        _assigned("services/datacore/lifecycle.py", "visit_status", "status"),
    ),
    "life.state.": _values("datacore.lifecycle", "STATES"),
    "life.reason.sf.": _values("datacore.lifecycle", "SCREEN_FAIL_REASONS"),
    "life.reason.wd.": _values("datacore.lifecycle", "WITHDRAW_REASONS"),
    "life.anchor.": _values("datacore.lifecycle", "ANCHORS"),
    "registry.status.": _values("orchestrator.candidates", "STATUSES"),
    "sstate.": _values("console.sitestore", "STUDY_STATES"),
    "role.": _values("console.auth", "ROLES"),
    "lang.name.": _values("console.i18n", "LANGS"),
    "help.role.": _values("console.guides", "ROLES"),
    "help.page.": _union(_values("console.step4", "HELP_SLUGS"), _guide_pages),
    "guide.page.": _guide_pages,
    "life.gloss.": _values("console.guides", "GLOSSARY"),
}

_RUN = "a value of stored data or of a service's answer (a state, a kind, a source): no one list in the code holds it"
_ERR = "a refusal, error or failure code that a service or a form returns"
_DONE = "the word a page is sent back with after an action (?done=...), set by the route that redirects"
_AUDIT = "an audit kind: tests/console/test_audit_browser.py holds every one the code writes"
#: a family not checked member by member, with the reason. What a test renders is still checked: under the suite a
#: missing member raises (``TB_STRICT_TEXT``). A family asked with ``t_or`` has its own fallback and is not listed.
UNCHECKED_FAMILIES: dict[str, str] = {
    "audit.kind.": _AUDIT,
    **dict.fromkeys(
        (
            "cmd.refused.",
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
            "dc.source.",
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
            "site.sex.",
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
            "wb.",
            "wb.list.",
            "wb.pipe.",
            "wb.task.",
            "wstatus.",
        ),
        _RUN,
    ),
}


def problems() -> list[str]:
    served = served_catalogue()
    defs = definitions(served)
    out: list[str] = []
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
    return out


def main(argv: list[str] | None = None) -> int:
    found = problems()
    for p in found:
        print(p)
    print(f"text_keys: {len(found)} problem(s)", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
