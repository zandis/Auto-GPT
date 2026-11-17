"""D-1220 (review L-4; journey review A-M4, G-5): a console text key cannot go wrong silently.

The catalogue is joined from about forty modules with a plain ``dict.update``, so a key two modules defined with
different words was won by the later one (``edc.title`` titled the administrator's EDC connection page "EDC prefill")
and a key nobody defined showed raw ("life.vstate.unplanned" on the participant page). ``tools.text_keys`` reads every
definition where it is written and every use; these tests hold its findings at zero, and show that it would see each
kind of mistake. Under the suite ``translate`` raises on a missing key (``TB_STRICT_TEXT``, tests/conftest.py)."""

from __future__ import annotations

import ast

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
def _defs_of(source: str) -> list[tk.Definition]:
    out = []
    for lang, d in tk._dicts(ast.parse(source)):
        out += [tk.Definition(lang, k, v, f"x.py:{line}") for k, v, line in tk._entries(d, {})]
    return out


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


# ------------------------------------------------------------------ translate under the suite and on a box
def test_a_missing_key_raises_under_the_suite_and_shows_raw_on_a_box(monkeypatch: pytest.MonkeyPatch) -> None:
    from console import i18n

    assert i18n.STRICT  # tests/conftest.py sets TB_STRICT_TEXT=1 before the console is imported
    with pytest.raises(i18n.MissingText, match="no.such.key"):
        i18n.translate("ja", "no.such.key")
    assert i18n.lookup("ja", "no.such.key") is None
    assert i18n.lookup("ja", "nav.studies") == i18n.CATALOGUES["ja"]["nav.studies"]
    monkeypatch.setattr(i18n, "STRICT", False)
    assert i18n.translate("ja", "no.such.key") == "no.such.key"  # a box keeps the fallback: no page goes down
