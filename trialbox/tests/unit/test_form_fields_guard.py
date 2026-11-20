"""9k-6a (D-1376, review 09 DS-6, A11Y-4): the guard of the field macro, on by default.

* The ratchet list (``tools/form_fields_ratchet.txt``) is the tree's: every template with a POST form outside the
  macro is on it with its count and a reason (``python -m tools.form_fields``). A planted template with a raw POST
  form fails; a listed template removed from the tree, or converted, without its line lowered fails; a line without
  a reason fails; a converted form with a raw field, without the summary or without a case fails.
* 9k-6c (D-1384): a raw form is TYPED (a control a person edits, or something the text cannot see through) or ACTION
  (hidden inputs and buttons). The ratchet's typed section counts only typed forms and never exceeds the D-1376 list
  (kept as a fixture); an action form needs POST, the csrf field and an action address, and the action section lists the
  ones that do not (none on master today).
* Each converted form has its failed-POST case (``tests/console/form_cases_9k6a.py``), which
  ``tests/console/test_form_errors_9k6a.py`` renders in three languages.
* The macro itself, rendered without the console: the summary's links target the fields' ids, ``aria-describedby``
  resolves, "required" is in words, a password is never given a value; the helper keeps typed values and never a
  secret.
* Every text in en, ja and zh-TW, and a message for every field the two converted forms' checks can name.
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tools import form_fields

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "services" / "console" / "templates"
RAW = '<form method="post" action="/x"><input type="hidden" name="csrf" value=""><input name="note"></form>\n'


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "templates"
    shutil.copytree(TEMPLATES, root)
    return root


def _ratchet() -> str:
    return form_fields.RATCHET.read_text(encoding="utf-8")


def _typed_plus(line: str) -> str:
    """The list with one more line at the end of its typed section."""
    return _ratchet().replace("@action\n", line + "@action\n", 1)


def test_the_ratchet_list_is_the_trees() -> None:
    assert form_fields.problems() == []
    assert form_fields.render_list(TEMPLATES, _ratchet()) == _ratchet()  # --write would change nothing
    listed, bad = form_fields.read_list(_ratchet())
    assert bad == [] and listed and all(reason for _n, reason in listed.values())


def test_a_planted_template_with_a_raw_post_form_fails(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    (root / "planted_9k6a.html").write_text('{% extends "base.html" %}{% block content %}' + RAW + "{% endblock %}")
    found = form_fields.problems(root, _ratchet())
    assert len(found) == 1 and found[0].startswith("planted_9k6a.html: 1 typed POST form(s) outside the field macro")
    # on the list with a reason, it passes; with the reason --write gives a new line, it does not
    assert form_fields.problems(root, _typed_plus("planted_9k6a.html 1 a planted form (test)\n")) == []
    assert form_fields.problems(root, _typed_plus(f"planted_9k6a.html 1 {form_fields.NEW_REASON}\n")) != []
    # a second raw form in a listed template fails too
    listed = next(t for t in form_fields.read_list(_ratchet())[0] if (root / t).is_file())
    with (root / listed).open("a", encoding="utf-8") as f:
        f.write(RAW)
    assert any(x.startswith(f"{listed}: ") and "the list says" in x for x in form_fields.problems(root, _ratchet()))


def test_a_listed_template_removed_or_converted_without_the_list_fails(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    listed = sorted(form_fields.read_list(_ratchet())[0])
    gone = listed[0]
    (root / gone).unlink()
    found = form_fields.problems(root, _ratchet())
    assert found == [f"{gone}: on the list but not in the tree: remove its line from {form_fields.RATCHET.name}"]
    # the template's line taken out: green again
    kept = "".join(x + "\n" for x in _ratchet().splitlines() if not x.startswith(gone + " "))
    assert form_fields.problems(root, kept) == []
    # a count higher than the tree's (a form converted, the line not lowered) fails
    t, (n, reason) = next((t, v) for t, v in form_fields.read_list(_ratchet())[0].items() if t != gone)
    higher = _ratchet().replace(f"{t} {n} {reason}\n", f"{t} {n + 1} {reason}\n")
    assert any(x.startswith(f"{t}: {n} typed POST form(s) outside the macro, the list says {n + 1}") for x in
               form_fields.problems(root, higher))  # fmt: skip


def test_a_converted_form_keeps_to_the_contract(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    page = root / "study_state.html"
    text = page.read_text(encoding="utf-8")
    assert 'data-fields="identity"' in text and 'data-fields="irb-text"' in text
    # a raw field inside a converted form
    page.write_text(text.replace('data-fields="identity">\n', 'data-fields="identity">\n<input name="extra">\n'))
    assert any("form 'identity' has a field outside the macro" in x for x in form_fields.problems(root, _ratchet()))
    # no summary, no title
    page.write_text(text.replace("fm.error_summary(", "fm.nothing(").replace("fm.title(", "fm.nothing2("))
    found = form_fields.problems(root, _ratchet())
    assert any("no fm.error_summary" in x for x in found) and any("no fm.title" in x for x in found)
    # a form name used twice
    page.write_text(text.replace('data-fields="irb-text"', 'data-fields="identity"'))
    assert any("used twice" in x for x in form_fields.problems(root, _ratchet()))


def test_every_converted_form_has_its_failed_post_case() -> None:
    from tests.console.form_cases_9k6a import CASES

    tree = form_fields.converted(form_fields.scan())
    assert tree == {name: case.template for name, case in CASES.items()}
    for name, case in CASES.items():
        assert set(case.failing) <= set(case.bad) and set(case.kept) <= set(case.bad), name


# ---------------------------------------------------------------------------------------------- typed and action (9k-6c)
OLD_LIST = ROOT / "tests" / "unit" / "fixtures" / "form_fields_ratchet_d1376.txt"
ACTION = (
    '<form method="post" action="/x/go"><input type="hidden" name="csrf" value="{{ csrf }}">'
    '<input type="hidden" name="id" value="{{ i }}"><button type="submit">{{ t("go") }}</button></form>\n'
)


def _plant(tmp_path: Path, form: str) -> tuple[Path, list[str]]:
    root = _copy(tmp_path)
    (root / "planted_9k6c.html").write_text('{% extends "base.html" %}{% block content %}' + form + "{% endblock %}")
    return root, form_fields.problems(root, _ratchet())


def test_a_new_typed_raw_form_fails_the_guard(tmp_path: Path) -> None:
    _root, found = _plant(tmp_path, RAW)
    assert len(found) == 1 and found[0].startswith("planted_9k6c.html: 1 typed POST form(s) outside the field macro")


def test_a_new_action_form_with_the_token_passes_without_a_list(tmp_path: Path) -> None:
    _root, found = _plant(tmp_path, ACTION + ACTION.replace("/x/go", "/x/stop"))
    assert found == []
    assert [f.typed for f in form_fields.post_forms(_root / "planted_9k6c.html", _root)] == [False, False]


def test_a_new_action_form_without_the_token_or_the_action_fails(tmp_path: Path) -> None:
    no_token = ACTION.replace('<input type="hidden" name="csrf" value="{{ csrf }}">', "")
    _root, found = _plant(tmp_path, no_token)
    assert len(found) == 1 and found[0].startswith("planted_9k6c.html: 1 action form(s)") and "csrf" in found[0]
    no_action = ACTION.replace(' action="/x/go"', "")
    assert "no action address" in _plant(tmp_path / "b", no_action)[1][0]
    empty_action = ACTION.replace('action="/x/go"', 'action=""')
    assert "no action address" in _plant(tmp_path / "c", empty_action)[1][0]
    # on the action list with its count, the old ones pass; a second one still fails
    root = _plant(tmp_path / "d", no_token)[0]
    listed = _ratchet() + f"planted_9k6c.html 1 {form_fields.ACTION_REASON}\n"  # the action section is last
    assert form_fields.problems(root, listed) == []
    (root / "planted_9k6c.html").write_text(
        '{% extends "base.html" %}{% block content %}' + no_token * 2 + "{% endblock %}"
    )
    assert any("the list says 1" in x for x in form_fields.problems(root, listed))
    # a line whose forms keep the rule, or whose count is above the tree's, fails: the list only goes down
    (root / "planted_9k6c.html").write_text('{% extends "base.html" %}{% block content %}' + ACTION + "{% endblock %}")
    assert any("remove its line" in x for x in form_fields.problems(root, listed))


def test_what_makes_a_form_typed() -> None:
    typed = form_fields.is_typed
    assert typed('<input type="checkbox" name="a">') and typed('<input type="radio" name="a">')
    assert typed('<input type="file" name="a">') and typed('<input name="a">') and typed('<input type="text">')
    assert typed("<select name=a></select>") and typed("<textarea name=a></textarea>")
    assert typed('<input type="{{ kind }}" name="a">')  # a type written by an expression is not seen
    assert typed('<input name="a" type=email>') and typed('<input name="a" type="hidden-ish">')
    for kind in ("hidden", "submit", "button", "image", "reset"):
        assert not typed(f'<input type="{kind}" name="a"><input name="b" type={kind}>'), kind
    assert not typed(
        '<input type="hidden" name="a" value="{{ t(\'x\') }}{{ d.isoformat() }}"><button>{{ t("k") }}</button>'
    )
    # what the text cannot see through is typed, the stricter class
    assert typed('{% include "_x.html" %}') and typed("{% call box() %}{% endcall %}")
    assert typed("{{ pick(a, b) }}") and typed("{{ fm.field(fe, 'f', 'f', 'n', 'N', '') }}")


def test_a_form_with_a_checkbox_counts_as_typed(tmp_path: Path) -> None:
    box = '<form method="post" action="/x"><input type="hidden" name="csrf" value="">'
    box += '<input type="checkbox" name="ok" value="1"><button>go</button></form>\n'
    _root, found = _plant(tmp_path, box)
    assert len(found) == 1 and "typed POST form(s) outside the field macro" in found[0]


def _fresh() -> tuple[dict[str, int], dict[str, int], int, int]:
    typed: dict[str, int] = {}
    n_action = 0
    broken: dict[str, int] = {}
    for p in sorted(TEMPLATES.rglob("*.html")):
        for f in form_fields.post_forms(p, TEMPLATES):
            if f.name is not None:
                continue
            t = p.relative_to(TEMPLATES).as_posix()
            if form_fields.is_typed(f.body):
                typed[t] = typed.get(t, 0) + 1
                continue
            n_action += 1
            has_action = bool(re.search(r"""\baction\s*=\s*["'][^"']+["']""", f.attrs))
            if not (has_action and 'name="csrf"' in f.body):
                broken[t] = broken.get(t, 0) + 1
    return typed, broken, n_action, sum(typed.values())


def test_the_recount_equals_a_fresh_measurement() -> None:
    typed, broken, n_action, n_typed = _fresh()
    listed, _bad = form_fields.read_list(_ratchet())
    assert {t: n for t, (n, _r) in listed.items()} == typed
    assert {t: n for t, (n, _r) in form_fields.read_action_list(_ratchet()).items()} == broken
    tree = form_fields.scan()
    assert sum(1 for forms in tree.values() for f in forms if f.name is None) == n_typed + n_action
    assert (n_typed, n_action, len(typed), sum(broken.values())) == (102, 54, 62, 0)  # as measured on 2026-11-20
    # 9f-3/5 added three button-only forms (no typed input, none broken): 51 -> 54 action forms


def test_the_typed_list_did_not_go_up_against_master() -> None:
    old, bad = form_fields.read_list(OLD_LIST.read_text(encoding="utf-8"))
    assert bad == [] and sum(n for n, _r in old.values()) == 153 and len(old) == 76  # D-1376's list, as it was
    new, _bad = form_fields.read_list(_ratchet())
    assert sum(n for n, _r in new.values()) <= 153
    for t, (n, _reason) in new.items():
        assert t in old and n <= old[t][0], f"{t}: {n} typed against {old.get(t)} on master"
    # and, with git at hand, against the list on origin/master itself
    import subprocess

    shown = subprocess.run(["git", "show", "origin/master:trialbox/tools/form_fields_ratchet.txt"], cwd=ROOT,
                           capture_output=True, text=True, check=False)  # fmt: skip
    if shown.returncode == 0:
        master, _ = form_fields.read_list(shown.stdout)
        for t, (n, _reason) in new.items():
            assert t in master and n <= master[t][0], f"{t}: {n} typed against {master.get(t)} on origin/master"


# ---------------------------------------------------------------------------------------------- the macro, alone
CATALOGUE = {
    "fe.summary": "There is a problem",
    "fe.title": "Error: {title}",
    "fe.error": "Error:",
    "fe.required": "required",
    "m.name": "Write the name.",
    "m.pw": "Write the password.",
}

PAGE = """{% import "_fields.html" as fm with context %}<title>{{ fm.title(fe, 'Page') }}</title>
{{ fm.error_summary(fe) }}<h1>Page</h1>
<form method="post" data-fields="f"><input type="hidden" name="csrf" value="{{ csrf }}">
{{ fm.field(fe, 'f', 'f', 'name', 'Name', 'stored', hint='As written', required=True) }}
{{ fm.field(fe, 'f', 'f', 'pw', 'Password', 'stored-secret', kind='password', required=True) }}
{{ fm.field(fe, 'f', 'f', 'kind', 'Kind', 'b', kind='select', options=[('a', 'A'), ('b', 'B')]) }}
{{ fm.field(fe, 'f', 'f', 'note', 'Note', 'old note', kind='textarea') }}
{{ fm.field(fe, 'f', 'f', 'ok', 'Agreed', '1', kind='checkbox') }}
</form>"""


def _render(fe: Any) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    env.globals["t"] = lambda key, **kw: CATALOGUE[key].format(**kw)
    return env.from_string(PAGE).render(fe=fe, csrf="c" * 8)


def _ids(text: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', text))


def test_the_macro_ties_each_error_to_its_field_and_keeps_no_secret() -> None:
    from console.form_errors import FAILED, failed, is_secret, kept_values

    assert FAILED == 400
    clean = _render(None)
    assert "fm-summary" not in clean and "<title>Page</title>" in clean and "aria-invalid" not in clean
    assert clean.count("(required)") == 2 and clean.count('aria-required="true"') == 2  # in words, not colour
    assert 'value="stored"' in clean and "stored-secret" not in clean  # a password is never given a value
    fe = failed("f", "f", [("name", "m.name"), ("pw", "m.pw"), ("name", "m.pw")],
                {"name": "typed", "pw": "typed-secret", "kind": "a", "note": "typed note", "ok": "1",
                 "csrf": "token-1", "enrol_code": "c-1"})  # fmt: skip
    assert [(e.name, e.key) for e in fe.errors] == [("name", "m.name"), ("pw", "m.pw")]  # a name once, form order
    assert "pw" not in fe.values and "csrf" not in fe.values and "enrol_code" not in fe.values
    out = _render(fe)
    assert "<title>Error: Page</title>" in out
    assert out.index("fm-summary") < out.index("<h1>")
    links = re.findall(r'<a href="#([^"]+)"[^>]*>([^<]*)</a>', out)
    assert links == [("f-name", "Write the name."), ("f-pw", "Write the password.")]
    ids = _ids(out)
    for fid, words in links:
        tag = re.search(rf'<(input|select|textarea)\b[^>]*\bid="{fid}"[^>]*>', out)
        assert tag and 'aria-invalid="true"' in tag.group(0), fid
        described = re.search(r'aria-describedby="([^"]+)"', tag.group(0))
        assert described and all(d in ids for d in described.group(1).split()) and f"{fid}-err" in described.group(1)
        assert re.search(rf'id="{fid}-err"><span class="sr">Error:</span> {re.escape(words)}</p>', out)
    assert 'value="typed"' in out and '<option value="a" selected>' in out and ">typed note</textarea>" in out
    assert re.search(r'id="f-ok"[^>]*\bchecked\b', out)
    for secret in ("typed-secret", "stored-secret", "token-1", "c-1"):
        assert secret not in out
    # a form's errors are not another form's
    other = _render(failed("g", "f", [("name", "m.name")], {"name": "elsewhere"}))
    assert "elsewhere" not in other and 'value="stored"' in other
    for name in ("password", "new_password", "otp", "totp", "enrol_code", "csrf", "api_key", "token", "pin"):
        assert is_secret(name), name
    for name in ("sponsor", "protocol_no", "note", "approval_ref", "passage", "keyword", "codex"):
        assert not is_secret(name), name
    assert kept_values([("a", "1"), ("a", "2"), ("f", b"x")]) == {"a": "2"}
    assert len(kept_values({"a": "x" * 5000})["a"]) == 2000


# ---------------------------------------------------------------------------------------------- the texts
def test_every_text_in_three_languages_and_a_message_per_checked_field() -> None:
    from console import i18n_form_errors as cat
    from console.sitestore import REGISTRIES, IrbText, StudyIdentity
    from console.study_setup import IDENTITY_MESSAGES, IRB_TEXT_MESSAGES

    assert set(cat.EN) == set(cat.JA) == set(cat.ZH)
    for key in cat.EN:
        assert not cat.JA[key].isascii() and not cat.ZH[key].isascii(), key
        for lang in (cat.EN, cat.JA, cat.ZH):
            assert set(re.findall(r"\{\w+\}", lang[key])) == set(re.findall(r"\{\w+\}", cat.EN[key])), key
    assert set(IDENTITY_MESSAGES) == {"sponsor", "protocol_no", "siv_date"} | {f"registry.{r}" for r in REGISTRIES}
    every_irb = IrbText(covers=False, approval_ref="-x", text_version="#1", approved_on="2099-01-01").problems(
        date(2026, 11, 2))  # fmt: skip
    assert set(every_irb) == set(IRB_TEXT_MESSAGES)
    assert set(IDENTITY_MESSAGES.values()) | set(IRB_TEXT_MESSAGES.values()) <= set(cat.EN)
    every_bad = StudyIdentity("x\x00" * 100, "-bad", "2026-02-30", {r: "?" for r in REGISTRIES}).problems()
    assert set(every_bad) == set(IDENTITY_MESSAGES)
