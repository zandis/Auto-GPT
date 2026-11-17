"""D-1220 (review L-4; journey review A-M4, G-5): a console text key cannot go wrong silently.

The catalogue is joined from about forty modules with a plain ``dict.update``, so a key two modules defined with
different words was won by the later one (``edc.title`` titled the administrator's EDC connection page "EDC prefill")
and a key nobody defined showed raw ("life.vstate.unplanned" on the participant page). ``tools.text_keys`` reads every
definition where it is written and every use; these tests hold its findings at zero, and show that it would see each
kind of mistake. In the suite's own process ``translate`` raises on a missing key (``console.i18n.STRICT``, tests/conftest.py); a box a
test starts as a child process does not."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys

import pytest

from tools import text_keys as tk

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database


@pytest.fixture(scope="module")
def served() -> dict[str, dict[str, str]]:
    return tk.served_catalogue()


@pytest.fixture(scope="module")
def defs(served: dict[str, dict[str, str]]) -> list[tk.Definition]:
    return tk.definitions(served)


def test_no_key_is_defined_twice_with_different_words(defs: list[tk.Definition]) -> None:
    bad, _same = tk.doubles(defs)
    assert not bad, "\n".join(f"{c.lang} {c.key}: " + "; ".join(f"{r.where} {r.text!r}" for r in c.rows) for c in bad)


def test_the_reader_sees_every_source_of_the_served_catalogue(
    defs: list[tk.Definition], served: dict[str, dict[str, str]]
) -> None:
    """Every key (and its words) the served console has comes from a definition the reader saw: a new way of joining
    keys cannot slip past the double check."""
    assert len(defs) > 9000
    assert tk.unseen(defs, served) == []


def test_every_key_a_template_or_the_code_asks_for_exists(served: dict[str, dict[str, str]]) -> None:
    uses = tk.template_uses() + tk.python_uses()
    assert sum(not u.family for u in uses) > 3000  # the reader finds the literal uses (t('…'), translate(lang, "…"))
    missing = [f"{u.key} ({u.where})" for u in uses if not u.family and u.key not in served["en"]]
    assert missing == []


def test_every_dynamic_family_is_checked_member_by_member_or_listed_with_a_reason() -> None:
    assert tk.problems() == []
    for prefix, reason in tk.UNCHECKED_FAMILIES.items():
        assert prefix.endswith(".") and reason, prefix
    assert not set(tk.FAMILIES) & set(tk.UNCHECKED_FAMILIES)


def test_the_participant_pages_visit_states_are_read_from_the_code() -> None:
    """A-M4: ``visit_status`` sets "unplanned" (no anchor date yet), which ``VISIT_STATES`` does not list."""
    states = set(tk.FAMILIES["life.vstate."]())
    assert {"due", "open", "overdue", "done", "missed", "stopped", "unplanned"} <= states


def test_the_edc_connection_page_and_the_prefill_page_have_their_own_words(served: dict[str, dict[str, str]]) -> None:
    """G-5: the administrator's /admin/edc page (edc_link.html) and the coordinator's prefill page meant different
    things by ``edc.title`` and ``edc.help``; each has its own key now."""
    tpl = (tk.TEMPLATES / "edc_link.html").read_text(encoding="utf-8")
    assert "t('edc.conn.title')" in tpl and "t('edc.title')" not in tpl
    for lang in tk.LANGS:
        assert served[lang]["edc.conn.title"] != served[lang]["edc.title"]
        assert served[lang]["edc.conn.help"] != served[lang]["edc.help"]
    assert served["en"]["edc.conn.title"] == "EDC connection"


# ------------------------------------------------------------------ the reader sees each kind of mistake
def _read(source: str) -> tuple[list[tk.Definition], list[tk.Dynamic]]:
    tree = ast.parse(source)
    tables = tk._tables(tree)
    groups = [(lang, tk._entries(d, tables, {}, "x.py")) for lang, d in tk._dicts(tree)]
    groups += [(lang, tk._entries(e, tables, b, "x.py")) for lang, e, b in tk._loop_updates(tree)]
    defs: list[tk.Definition] = []
    dyn: list[tk.Dynamic] = []
    for lang, entries in groups:
        for e in entries:
            if isinstance(e, tk.Dynamic):
                dyn.append(e)
            else:
                defs.append(tk.Definition(lang, e[0], e[1], f"x.py:{e[2]}"))
    return defs, dyn


def _defs_of(source: str) -> list[tk.Definition]:
    defs, dyn = _read(source)
    assert dyn == []
    return defs


def test_a_comprehension_and_a_loop_over_a_label_table_are_read_without_running_code() -> None:
    """i18n_demoja's ``**{f"refdata.src.{k}": v for k, v in _SRC_EN.items()}`` and i18n_audit's ``for _i, _cat in
    enumerate((EN, JA, ZH)): _cat.update({f"audit.ev.{n}": labels[_i] ...})`` are read from literal tables."""
    defs = _defs_of(
        '_SRC = {"ctgov": "CT.gov"}\n'
        'EVENTS = {"x.done": ("Done", "完了", "完成")}\n'
        'EN = {"a.b": "A", **{f"src.{k}": v for k, v in _SRC.items()}}\n'
        "JA = {}\nZH = {}\n"
        "for _i, _cat in enumerate((EN, JA, ZH)):\n"
        '    _cat.update({f"audit.ev.{name}": labels[_i] for name, labels in EVENTS.items()})\n'
    )
    assert {(d.lang, d.key, d.text) for d in defs} == {
        ("en", "a.b", "A"), ("en", "src.ctgov", "CT.gov"),
        ("en", "audit.ev.x.done", "Done"), ("ja", "audit.ev.x.done", "完了"), ("zh-TW", "audit.ev.x.done", "完成"),
    }  # fmt: skip


def test_a_definition_that_is_not_a_literal_is_a_problem_of_its_own() -> None:
    _defs, dyn = _read('EN = {"a.b": WORDS, f"c.{X}": "c", **other()}\nJA = {**{k: v for k, v in sorted(T)}}\n')
    assert [d.expr for d in dyn] == ["'a.b': WORDS", "f'c.{X}': 'c'", "other()", "{k: v for k, v in sorted(T)}"]


def test_the_reader_runs_no_code_of_the_modules_it_reads() -> None:
    """The scan's rule (no eval, no exec): the reader takes literals only (``ast.literal_eval``)."""
    tree = ast.parse((tk.ROOT / "tools" / "text_keys.py").read_text(encoding="utf-8"))
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not calls & {"eval", "exec", "compile", "__import__"}


def test_a_double_in_two_dicts_and_a_double_inside_one_dict_are_both_seen() -> None:
    defs = _defs_of(
        'EN = {"a.title": "One", "a.help": "Same"}\n'
        '_B_EN = {"a.title": "Two", "a.help": "Same"}\n'
        'JA = {"b.x": "一", "b.x": "二"}\n'  # Python keeps the second without a word
        'EN.update({"c.y": "Three"})\n'
        'WORDS = {"en": {"c.y": "Four"}, "ja": {}, "zh-TW": {}}\n'
    )
    bad, same = tk.doubles(defs)
    assert [(c.lang, c.key) for c in bad] == [("en", "a.title"), ("en", "c.y"), ("ja", "b.x")]
    assert [(c.lang, c.key) for c in same] == [("en", "a.help")]


def test_an_unseen_source_is_named() -> None:
    defs = [tk.Definition("en", "a.b", "words", "x.py:1")]
    served = {"en": {"a.b": "other words", "a.c": "c"}, "ja": {}, "zh-TW": {}}
    found = tk.unseen(defs, served)
    assert len(found) == 2 and "a.b" in found[0] and "a.c" in found[1]


def test_a_missing_member_of_a_checked_family_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """On master the family ``life.vstate.`` lacked "unplanned"; the check names such a member."""
    monkeypatch.setitem(tk.FAMILIES, "life.vstate.", lambda: ["due", "not_a_state"])
    found = tk.problems()
    assert found == [
        f"missing key 'life.vstate.not_a_state' of the family 'life.vstate.' used at {_first_use('life.vstate.')}"
    ]


def _first_use(prefix: str) -> str:
    return next(u.where for u in tk.template_uses() + tk.python_uses() if u.family and u.key == prefix)


def test_a_new_family_must_be_checked_or_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(tk.UNCHECKED_FAMILIES, "wstatus.")
    assert [p for p in tk.problems() if "'wstatus.'" in p and "neither FAMILIES nor" in p]


# ------------------------------------------------------------------ translate in the suite and on a box
def test_a_box_the_suite_starts_as_a_child_process_is_not_strict() -> None:
    """Strict mode never leaks into a box a test starts (a walk's demo box, an e2e console): the suite switches it on
    in process, not through the environment, so a child process started with the suite's environment keeps the
    fallback, and a missing text there is the key, never a 500 that fails another lane's walk."""
    conftest = (tk.ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "TB_STRICT_TEXT" not in conftest  # the suite never adds it to the environment its children inherit
    env = {k: v for k, v in os.environ.items() if k != "TB_STRICT_TEXT"}  # a developer may export it by hand
    child = subprocess.run(
        [sys.executable, "-c", "from console import i18n; print(i18n.STRICT, i18n.translate('en', 'no.such.key'))"],
        env={**env, "PYTHONPATH": os.pathsep.join(str(tk.ROOT / p) for p in ("libs", "services", "."))},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert child.stdout.split() == ["False", "no.such.key"], child.stderr


def test_a_missing_key_raises_in_the_suite_and_shows_raw_on_a_box(monkeypatch: pytest.MonkeyPatch) -> None:
    from console import i18n

    assert i18n.STRICT  # tests/conftest.py switches it on in the suite's own process
    with pytest.raises(i18n.MissingText, match="no.such.key"):
        i18n.translate("ja", "no.such.key")
    assert i18n.lookup("ja", "no.such.key") is None
    assert i18n.lookup("ja", "nav.studies") == i18n.CATALOGUES["ja"]["nav.studies"]
    monkeypatch.setattr(i18n, "STRICT", False)
    assert i18n.translate("ja", "no.such.key") == "no.such.key"  # a box keeps the fallback: no page goes down
    assert issubclass(i18n.MissingText, LookupError) and not issubclass(i18n.MissingText, KeyError)


def _calls(node: ast.AST) -> str:
    f = node.func if isinstance(node, ast.Call) else None
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _own_nodes(fn: ast.FunctionDef) -> list[ast.AST]:
    """The nodes of one function, without those of the functions defined inside it (each is its own scope)."""
    out: list[ast.AST] = []
    todo: list[ast.AST] = list(fn.body)
    while todo:
        n = todo.pop()
        out.append(n)
        if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            todo += list(ast.iter_child_nodes(n))
    return out


def test_no_page_tests_a_translation_against_its_key() -> None:
    """Under strict mode ``translate`` raises on a missing key, so "the text equals the key" never tests whether a
    text exists: ``lookup`` (Python) and ``t_or`` (templates) do. No console module compares a ``translate``/``t``
    result (or a name bound to one) with anything, and no template writes ``t(k) != k``."""
    found = []
    for path in sorted(tk.CONSOLE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            nodes = _own_nodes(fn)
            bound = {  # names bound to a translate()/t() result in this function
                t.id
                for n in nodes
                if isinstance(n, ast.Assign) and _calls(n.value) in ("translate", "t")
                for t in n.targets
                if isinstance(t, ast.Name)
            }
            for n in nodes:
                if isinstance(n, ast.Compare) and any(isinstance(o, ast.Eq | ast.NotEq) for o in n.ops):
                    for side in (n.left, *n.comparators):
                        if _calls(side) in ("translate", "t") or (isinstance(side, ast.Name) and side.id in bound):
                            found.append(f"{path.name}:{n.lineno}")
    assert sorted(set(found)) == []
    tpl = [p.name for p in tk.TEMPLATES.rglob("*.html") if re.search(r"\bt\((\w+)\) *!= *\1\b", p.read_text())]
    assert tpl == []


def test_the_late_fallbacks_read_through_lookup_in_strict_mode() -> None:
    from console.copy_assist_page import source_line
    from console.i18n import STRICT

    assert STRICT
    assert isinstance(source_line({"kind": "no_such_kind", "text": "x"}, {}, "ja"), str)  # edc.cite.<kind>


def test_a_problem_pages_key_and_both_branches_of_a_conditional_are_uses() -> None:
    py = {(u.key, u.where.split(":")[0].rsplit("/", 1)[-1]) for u in tk.python_uses() if not u.family}
    assert ("forbidden", "reveal.py") in py and ("reveal.rate_limited", "reveal.py") in py  # refuse(…, 429, key)
    assert ("csrf", "app.py") in py  # _Problem(400, "csrf")
    assert not {k for k, _ in py} & set(tk.API_ONLY)  # JSON on /api/ only, never rendered
    assert ("log.no", "screening_log.py") in py  # "log.no" if c == … else f"log.xlsx.col.{c}"
    tpl = {u.key for u in tk.template_uses() if not u.family}
    assert {"asof.stale", "asof.line", "pilot.banner.public", "pilot.banner", "site.help.remote.off"} <= tpl
    fam = {u.key for u in tk.template_uses() if u.family}
    assert {"verdict.exclusion.", "wb.list."} <= fam  # {% set k = '…' + … %}, then t(k)
