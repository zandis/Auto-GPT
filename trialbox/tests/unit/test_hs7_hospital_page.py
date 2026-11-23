"""HS-7: the hospital's install page (docs/plan/design/hospital-simple-install.md, section 5 row 7).

The design's test: the hospital's page holds one shell command and no setting name. With it: the page names no
flag, path, setting or internal number outside that one command; every line it quotes from the screen is a line the
installer prints; the three languages carry the same steps in the same order; and the runbook sends a hospital to it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tb_common.wording import check

from tools import doclint

ROOT = Path(__file__).resolve().parents[2]
LANGS = ("en", "ja", "zh-TW")
PAGES = {lang: ROOT / "docs" / "handover" / f"hospital-install.{lang}.md" for lang in LANGS}
INSTALLER = ("deploy/launcher.sh", "deploy/bootstrap.sh", "deploy/box-install.sh")
FENCE = re.compile(r"^ *```\n(.*?)^ *```\n", re.M | re.S)

pytestmark = pytest.mark.nodb


def _text(lang: str) -> str:
    return PAGES[lang].read_text(encoding="utf-8")


def _prose(text: str) -> str:
    """The page without its one fenced command."""
    return FENCE.sub("", text)


def _quotes(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", _prose(text))


def _shape(text: str) -> list[tuple[str, int]]:
    """Per heading: the heading's level and how many numbered steps, bullets and table rows follow it."""
    shape: list[tuple[str, int]] = []
    for part in re.split(r"^(#+) ", _prose(text), flags=re.M)[1:]:
        if part.startswith("#"):
            shape.append(("h", len(part)))
            continue
        shape.append(("steps", len(re.findall(r"^[1-9]\. ", part, re.M))))
        shape.append(("bullets", len(re.findall(r"^- ", part, re.M))))
        shape.append(("rows", len(re.findall(r"^\| ", part, re.M))))
    return shape


@pytest.mark.parametrize("lang", LANGS)
def test_the_hospitals_page_holds_one_shell_command(lang: str) -> None:
    text = _text(lang)
    blocks = FENCE.findall(text)
    assert len(blocks) == 1, lang
    lines = [ln.strip() for ln in blocks[0].splitlines() if ln.strip()]
    assert len(lines) == 1, lang
    # the delivery sheet's line: a private copy of the stick's launcher, its code shown, then that copy run
    assert lines[0].startswith("sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && ")
    assert lines[0].endswith("&& sudo bash /root/trialbox-install /media/<user>/TRIALBOX")
    assert lines[0].count("sudo bash ") == 1
    prose = _prose(text)
    assert not re.search(r"^\s*(\$ |sudo |bash |python)", prose, re.M), lang
    assert not [q for q in _quotes(text) if re.match(r"(sudo|bash|python3?|docker|cd) ", q)], lang


@pytest.mark.parametrize("lang", LANGS)
def test_the_hospitals_page_names_no_setting_flag_path_or_internal_number(lang: str) -> None:
    prose = _prose(_text(lang))
    for pattern in (
        r"\bTB_[A-Z]", r"\b[A-Z][A-Z0-9]+_[A-Z0-9_]+\b",  # a setting name
        r"(?<![\w-])--?[A-Za-z]",  # a flag
        r"deploy/|\.env\b|\.ya?ml\b|\.sh\b|\.json\b|/opt/|/root/|/media/|/etc/",  # a path or a settings file
        r"RUNBOOK|§|\bD-\d", r"\b(?:HS|H|T|K|10K|OPS|HW|ENG|REG|NEW-WIN)-\d",  # a decision or card number
    ):  # fmt: skip
        found = re.search(pattern, prose, re.ASCII)  # ASCII: a Japanese or Chinese letter is not part of a name
        assert not found, (lang, pattern, found)
    assert check(_text(lang)) == [], lang
    assert doclint.check_doc(f"docs/handover/{PAGES[lang].name}") == [], lang


def test_every_line_the_page_quotes_from_the_screen_is_one_the_installer_prints() -> None:
    printed = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in INSTALLER)
    quotes = _quotes(_text("en"))
    assert len(quotes) >= 15
    for quote in quotes:
        assert quote in printed, quote


def test_the_three_languages_carry_the_same_steps_in_the_same_order() -> None:
    shapes = {lang: _shape(_text(lang)) for lang in LANGS}
    assert shapes["en"] == shapes["ja"] == shapes["zh-TW"]
    assert ("steps", 7) in shapes["en"] and ("steps", 6) in shapes["en"]
    quotes = {lang: _quotes(_text(lang)) for lang in LANGS}
    assert quotes["en"] == quotes["ja"] == quotes["zh-TW"]
    blocks = {lang: FENCE.findall(_text(lang))[0].strip() for lang in LANGS}
    assert blocks["en"] == blocks["ja"] == blocks["zh-TW"]
    for lang in LANGS:
        assert _text(lang).splitlines()[2].startswith("**Reader:** hospital IT"), lang


def test_the_runbook_sends_a_hospital_to_its_page() -> None:
    assert "(handover/hospital-install.en.md)" in (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    first = (ROOT / "docs" / "runbook" / "01-install-a-new-site.md").read_text(encoding="utf-8").splitlines()[2]
    assert first.startswith("**Reader:** Aimedics") and "../handover/hospital-install.en.md" in first
