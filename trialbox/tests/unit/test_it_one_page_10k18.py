"""10K-18 (D-1378): the one page for hospital IT is made from the preflight's check list, one per delivered form.

The plan's proof: "doclint compares the page with the list". The committed pages are what the list makes; a label
changed in the list, a page edited by hand, a page missing, a check added to the list and placed in no form, an id a
form names that the list lacks, or a text missing in a language each fail ``tools/doclint.py``."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import preflight

from tools import doclint
from tools import it_one_page as iop

ROOT = Path(__file__).resolve().parents[2]
HANDOVER = ROOT / "docs" / "handover"
PAGES = [(form, lang) for form in iop.FORMS for lang in iop.LANGS]


def _relabel(cid: str, lang: str, text: str) -> dict[str, preflight.Item]:
    items = dict(preflight.BY_ID)
    it = items[cid]
    items[cid] = dataclasses.replace(it, label={**it.label, lang: text})
    return items


def test_10k18_doclint_compares_the_page_with_the_list(monkeypatch: pytest.MonkeyPatch) -> None:
    assert iop.problems() == []
    assert doclint.check_it_pages() == []
    # the list changes and the committed page does not: doclint fails, naming each page of that language
    monkeypatch.setattr(preflight, "BY_ID", _relabel("feed", "ja", "病院データの受け取り（変更）"))
    errs = doclint.check_it_pages()
    assert errs == [
        "docs/handover/it-one-page.ja.md:1: one-page: differs from the preflight list (python -m tools.it_one_page)",
        "docs/handover/it-one-page.it-form.ja.md:1: one-page: differs from the preflight list "
        "(python -m tools.it_one_page)",
    ]
    assert doclint.main([]) == 1


def test_10k18_a_page_edited_by_hand_or_missing_fails(tmp_path: Path) -> None:
    iop.write(tmp_path)
    assert iop.problems(folder=tmp_path) == []
    page = tmp_path / "it-one-page.zh-TW.md"
    page.write_text(page.read_text(encoding="utf-8").replace("6 件事", "三件事"), encoding="utf-8")
    (tmp_path / "it-one-page.it-form.en.md").unlink()
    assert iop.problems(folder=tmp_path) == [
        "docs/handover/it-one-page.zh-TW.md:1: one-page: differs from the preflight list (python -m tools.it_one_page)",
        "docs/handover/it-one-page.it-form.en.md:1: one-page: missing (python -m tools.it_one_page)",
    ]


def test_10k18_a_check_added_to_the_list_must_be_placed_in_every_form() -> None:
    new = preflight.Item("ups", "hardware", {lg: "UPS" for lg in iop.LANGS}, {lg: "Plug in." for lg in iop.LANGS})
    errs = iop.problems({**preflight.BY_ID, "ups": new})
    assert errs == [
        "tools/it_one_page.py: one-page: the box form places check ups 0 times (once: asked of IT or prepared by the "
        "supplier)",
        "tools/it_one_page.py: one-page: the it form places check ups 0 times (once: asked of IT or prepared by the "
        "supplier)",
    ]


def test_10k18_an_id_the_list_lacks_or_placed_twice_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    box = iop.FORMS["box"]
    monkeypatch.setitem(iop.FORMS, "box", {"it": (*box["it"], "disk", "gone"), "supplier": box["supplier"]})
    errs = iop.problems()
    assert any("box form places check disk 2 times" in e for e in errs)
    assert any("box form names gone, which the preflight list does not have" in e for e in errs)
    assert not any("one-page: differs" in e for e in errs)  # the pages are compared only when the list is placed


def test_10k18_a_text_missing_in_a_language_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    assert iop.problems(_relabel("clock", "zh-TW", "  ")) == [
        "libs/tb_common/preflight.py: one-page: check clock has no label in zh-TW"
    ]
    monkeypatch.setitem(iop.T, "questions", {"en": "Questions.", "ja": "質問。"})
    assert iop.problems() == ["tools/it_one_page.py: one-page: text questions has no zh-TW"]


@pytest.mark.parametrize(("form", "lang"), PAGES)
def test_10k18_each_page_holds_its_forms_items_in_its_language(form: str, lang: str) -> None:
    text = (HANDOVER / iop.page_name(form, lang)).read_text(encoding="utf-8")
    asked, supplied = iop.FORMS[form]["it"], iop.FORMS[form]["supplier"]
    for cid in asked:
        item = preflight.BY_ID[cid]
        assert f"- **{item.label[lang]}**{iop.SEP[lang]}{item.action[lang]}\n" in text, cid
    for cid in supplied:
        assert f"- {preflight.BY_ID[cid].label[lang]}\n" in text, cid
        assert preflight.BY_ID[cid].action[lang] not in text, cid  # nothing asked of IT for the supplier's
    # the count IT is told is the count of items asked of it: 6 for the box form, 9 for the IT form (review 18)
    reader = text.splitlines()[2]
    assert reader.startswith("**Reader:** hospital IT")
    assert str(len(asked)) in reader and len(asked) == {"box": 6, "it": 9}[form]
    assert "三" not in reader and "three" not in reader
    if lang != "en":  # no English left in a Japanese or Chinese page's items
        for cid in preflight.IDS:
            assert preflight.BY_ID[cid].action["en"] not in text
            assert f"**{preflight.BY_ID[cid].label['en']}**" not in text


@pytest.mark.parametrize(("form", "lang"), PAGES)
def test_10k18_each_page_is_one_page_that_doclint_reads_clean(form: str, lang: str) -> None:
    rel = f"docs/handover/{iop.page_name(form, lang)}"
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 60
    assert doclint.check_doc(rel) == []
    assert doclint.reader_problems(rel, text) == []
    for needed in ("443", "TB_TLS_HOSTNAME", f"network-sheet.{lang}.md"):
        assert needed in text, needed


def test_10k18_the_box_form_keeps_the_linked_name() -> None:
    assert iop.page_name("box", "ja") == "it-one-page.ja.md"
    assert iop.page_name("it", "zh-TW") == "it-one-page.it-form.zh-TW.md"
    assert set(iop.FORMS["box"]["it"]) | set(iop.FORMS["box"]["supplier"]) == set(preflight.IDS)


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    return subprocess.run([sys.executable, "-m", "tools.it_one_page", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


def test_10k18_the_command_line_writes_and_checks(tmp_path: Path) -> None:
    """Run once without PYTHONUNBUFFERED: --check on the committed pages, on an empty folder, after a write."""
    ok = _cli("--check")
    assert (ok.returncode, ok.stdout.strip()) == (0, "up to date"), ok.stderr
    empty = _cli("--check", "--out", str(tmp_path))
    assert empty.returncode == 1 and empty.stdout.count(": missing") == 6
    wrote = _cli("--out", str(tmp_path))
    assert wrote.returncode == 0 and wrote.stdout.count("wrote ") == 6
    assert _cli("--check", "--out", str(tmp_path)).returncode == 0
    assert (tmp_path / "it-one-page.ja.md").read_text(encoding="utf-8") == (HANDOVER / "it-one-page.ja.md").read_text(
        encoding="utf-8"
    )
