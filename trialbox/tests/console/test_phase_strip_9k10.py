"""9k-10 (D-1385; review 09 DS-10): the phase strip on the console's pages, in three languages and at phone width.

The page tests run everywhere: the coordinator's home (one strip per study), the weekly list (the six steps, one tap
away once set up) and the set-up wizard show ``ol.ps`` with a state on every item, exactly one current item, and the
state said in words in the page's language. The screenshot test opens the same pages with ``console.css`` in Chromium
through Node Playwright (``tests/console/phase_strip.js``; skipped where it is missing) at 390 px and at desktop
width (also 800 px): no label cut or scrolled inside its cell, rows within the limit, no sideways scroll, no one-character
line, the tick only on done and the underline only on current (computed style), a line for the current item in forced colours.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES

from tests.console.test_cjk_layout import _as, _node_playwright, _setup
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("phase_strip.js")
LANGS = ("en", "ja", "zh-TW")
PAGES = (("crc", "/"), ("drsato", "/studies/GZQO/week"))
WIZARD = ("steward", "/site/start")
WIDTHS = ((390, 844), (800, 900), (1280, 860))
STATE_WORDS = ("done", "current", "todo", "off")
WORDS = {  # per state and language, written out (not read from the catalogue the page reads)
    "en": {"done": "done", "current": "current step", "todo": "not done yet", "off": "not used in this study"},
    "ja": {"done": "完了", "current": "現在の手順", "todo": "未完了", "off": "この試験では使いません"},
    "zh-TW": {"done": "已完成", "current": "目前步驟", "todo": "尚未完成", "off": "本試驗不使用"},
}


def _strips(page: str) -> list[str]:
    return re.findall(r'<ol class="ps".*?</ol>', page, flags=re.S)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize(("user", "path"), PAGES)
def test_the_pages_show_the_strip_with_states_in_words(box: dict[str, Any], lang: str, user: str, path: str) -> None:  # noqa: F811
    _setup(box)
    t = CATALOGUES[lang]
    page = _as(box, user, lang).get(path)
    assert page.status_code == 200
    strips = _strips(page.text)
    assert strips, path
    for strip in strips:
        assert 'class="steps"' not in strip and f'aria-label="{html.escape(t["steps.label"])}"' in strip
        states = re.findall(r'<li data-state="(done|current|todo|off)"', strip)
        assert len(states) == strip.count("<li ") >= 5
        assert states.count("current") == 1 and strip.count('aria-current="step"') == 1
        for li_state, said in re.findall(r'<li data-state="(\w+)".*?<span class="sr"> \((.*?)\)</span>', strip):
            assert said == WORDS[lang][li_state], (li_state, said)  # each item says its own state


@pytest.mark.parametrize("lang", LANGS)
def test_the_wizard_shows_the_strip_with_its_current_step(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    _setup(box)
    box["users"].create("steward", "admin", "cjk-layout-password-0001", "steward@hospa.test")
    t = CATALOGUES[lang]
    page = _as(box, "steward", lang).get("/site/start")
    assert page.status_code == 200
    assert (
        f'aria-label="{html.escape(t["site.start.title"])}"' in page.text.split('data-testid="wizard-steps"')[0][-200:]
    )
    strip = _strips(page.text)
    assert len(strip) == 1 and 'data-testid="wizard-steps"' in strip[0]
    assert re.findall(r'data-state="(\w+)"', strip[0]).count("current") == 1


def test_screenshots_every_label_is_whole_at_390_800_and_1280_px_in_three_languages(
    box: dict[str, Any],  # noqa: F811
    tmp_path: Path,
) -> None:
    if not _node_playwright():
        pytest.skip("Node Playwright is not installed")
    _setup(box)
    box["users"].create("steward", "admin", "cjk-layout-password-0001", "steward@hospa.test")
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    css = ""
    for lang in LANGS:
        for user, path in (*PAGES, WIZARD):
            c = _as(box, user, lang)
            r = c.get(path)
            assert r.status_code == 200, (user, path)
            text = r.text
            css = css or c.get("/static/console.css").text
            text = text.replace('href="/static/console.css"', 'href="console.css"')
            # the week page folds the strip once set up: open the fold so the strip has a box
            text = text.replace('<details class="stepsfold"', '<details open class="stepsfold"')
            for width, height in WIDTHS:
                name = f"{user}-{lang}-{width}.html"
                (out / name).write_text(text, encoding="utf-8")
                pages.append({"file": name, "lang": lang, "width": width, "height": height, "forced": width == 390})
    (out / "console.css").write_text(css, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages})],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res["failures"], r.stderr[-2000:])
    assert len(res["seen"]) == len(pages)
