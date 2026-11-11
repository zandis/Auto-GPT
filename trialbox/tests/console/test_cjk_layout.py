"""T-684 (D-361; UX-023, UX-025, UX-037, with the font, registry-word and keyboard parts of UX-024, UX-033, UX-026):
the clinical pages' layout in Japanese and Traditional Chinese.

Two layers. The page and style-sheet tests run everywhere (CI included): the per-language font stacks, the no-wrap
rules for pills and buttons, the folded procedure and one-line SAE banners of the week page, the full patient page's
sticky mark bar, the second skip link, the registry page's words. The screenshot test renders the same pages with the
in-process box, writes them with ``console.css`` into one folder and opens them in Chromium through Node Playwright
(``tests/console/cjk_layout.js``; the preinstalled browser, never ``playwright install``), at desktop and phone
widths, and measures what the review saw by eye: no pill or button with one character on a line, no sideways scroll,
no link clipped at the window edge, the mark bar on the first screen of the full page and the first patient row on
the first screen of the week page. It is skipped where Node Playwright is missing. ``TB_UX_SHOTS=<dir>`` keeps the
screenshots.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES
from console.i18n_layout import EN as LAYOUT_EN

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "services" / "console" / "static" / "console.css"
SCRIPT = Path(__file__).with_name("cjk_layout.js")
PW = "cjk-layout-password-0001"
B = "b" * 32
LANGS = ("ja", "zh-TW", "en")


def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


def _rule(css: str, selector: str) -> str:
    """The declarations of the first rule whose selector list starts with ``selector``."""
    i = css.index(selector)
    j = css.index("{", i)
    return css[j + 1 : css.index("}", j)]


def _families(decl: str) -> list[str]:
    m = re.search(r"font-family:\s*([^;]+);", decl)
    assert m, decl
    return [f.strip().strip('"') for f in m.group(1).split(",")]


def _setup(b: dict[str, Any]) -> None:
    """A finished screening run, two users, and (synthetic) one unacknowledged SAE, one overdue SAE report and the
    delegation-log reminder: the week page's first screen as the review saw it."""
    _done_screen(b["backend"], _ulid(961))
    b["users"].create("drsato", "investigator", PW, "drsato@hospa.test")
    b["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    h = b["app"].state.helpers
    h.life_sae = lambda rid: [
        {"record": "S-0001", "event": "ae1", "ae_term": "synthetic event", "ae_onset": "2026-10-01", "fatal": False}
    ]
    h.life_reports = lambda rid: [{"record": "S-0001", "event": "ae1", "party": "sponsor", "due": "2026-10-03"}]
    h.team_due = lambda rid: True


def _as(b: dict[str, Any], user: str, lang: str) -> Any:
    c, csrf = login(b["app"], user, PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    return c


def _main(page: str) -> str:
    return page[page.index("<main") : page.index("</main>")]


# ------------------------------------------------------------------------------------------- the style sheet


def test_one_font_stack_per_language_with_the_language_own_face_first() -> None:
    """UX-024: the base stack names no CJK face; the ja stack names Japanese faces only, the zh-TW stack Taiwanese
    faces only, so a page never takes the other language's glyph forms. System fonts only: no @font-face, no url()."""
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"body \{ margin: 0; font: 15px/1\.5 ([^;]+);", css)
    assert m
    base = [f.strip().strip('"') for f in m.group(1).split(",")]
    assert not [f for f in base if re.search(r"JP|TC|SC|Hiragino|Yu Gothic|Meiryo|JhengHei|PingFang", f)]
    ja = _families(_rule(css, 'body:lang(ja), body [lang|="ja"]'))
    zh = _families(_rule(css, 'body:lang(zh-TW), body [lang="zh-TW"]'))
    assert ja[-1] == zh[-1] == "sans-serif"
    assert {"Hiragino Sans", "Yu Gothic UI", "Meiryo", "Noto Sans JP"} <= set(ja)
    assert {"PingFang TC", "Microsoft JhengHei", "Noto Sans TC"} <= set(zh)
    assert not [f for f in ja if re.search(r"TC|SC|JhengHei|PingFang", f)]
    assert not [f for f in zh if re.search(r"JP|Hiragino|Yu Gothic|Meiryo|IPA", f)]
    assert "@font-face" not in css and "url(" not in css


def test_pills_and_buttons_keep_cjk_words_whole() -> None:
    """UX-023: a pill, badge or button breaks only between words (keep-all: a CJK label is one word), and its
    last-resort break (break-word) does not lower its minimum width the way ``anywhere`` would."""
    css = CSS.read_text(encoding="utf-8")
    btn = _rule(css, ".pill, .state, button, .button { word-break")
    assert "word-break: keep-all" in btn and "overflow-wrap: break-word" in btn and "anywhere" not in btn
    assert "line-break: strict" in _rule(css, "body:lang(ja), body:lang(zh-TW) { line-break")


# ------------------------------------------------------------------------------------------- the pages


@pytest.mark.parametrize("lang", LANGS)
def test_week_page_first_screen_folds_procedure_and_sae_banners(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    """UX-037: once set up, the six steps fold to one line naming the current step; the SAE banner and the overdue
    report banner are one line each with the count, still red and still an alert, and the acknowledgement is still
    on the page; the second skip link goes to the patient list (UX-026)."""
    _setup(box)
    t = CATALOGUES[lang]
    page = _as(box, "drsato", lang).get("/studies/GZQO/week").text
    fold = re.search(r'<details class="stepsfold" data-testid="steps-fold"><summary>(.*?)</summary>', page)
    assert fold
    assert html.unescape(fold.group(1)) == t["steps.fold"].format(n=3, of=6, name=t["steps.feasibility"])
    assert 'data-testid="steps"' in page.split('data-testid="steps-fold"')[1][:400]  # all six, one tap away
    sae = page.split('data-testid="sae-banner"')[1].split("</section>")[0]
    assert 'role="alert"' in page.split('data-testid="sae-banner"')[0][-80:]
    assert f"{html.escape(t['life.sae.title'])} · 1</h2>" in sae and 'data-testid="sae-ack-S-0001-ae1"' in sae
    rep = page.split('data-testid="sae-reports"')[1].split("</section>")[0]
    assert (
        f"{html.escape(t['life.reports.title'])} · 1</h2>" in rep
        and 'data-testid="sae-report-S-0001-ae1-sponsor"' in rep
    )
    assert 'data-testid="team-due"' in page
    skip = re.search(r'<a class="skip" href="#worklist" data-testid="skip-worklist">([^<]+)</a>', page)
    assert skip and html.unescape(skip.group(1)) == t["skip.worklist"]
    assert page.index('href="#main"') < page.index('href="#worklist"') < page.index("<header")
    assert '<section class="wlist" id="worklist" tabindex="-1">' in page


def test_other_pages_keep_the_full_sae_banner() -> None:
    """The fold is for the week page only: the coordinator's home and the study picker call the banners unfolded."""
    tpl = ROOT / "services" / "console" / "templates"
    for name in ("home_crc.html", "week_pick.html"):
        text = (tpl / name).read_text(encoding="utf-8")
        assert "sae_banner(life.sae)" in text and "compact" not in text, name


@pytest.mark.parametrize("lang", LANGS)
def test_full_patient_page_has_the_sticky_mark_bar_last_in_main(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    """UX-025: the mark bar of the full patient page is the last element of main, in its sticky dock, with the three
    mark buttons wired to the mark forms above; the mark card no longer holds a second one."""
    _setup(box)
    page = _as(box, "drsato", lang).get(f"/studies/GZQO/patients/{B}").text
    main = _main(page)
    assert main.count('data-testid="markbar"') == 1
    dock = main.split('<div class="markdock" data-testid="markdock">')[1]
    assert re.sub(r"\s+", "", dock).endswith("</div></div>")  # nothing after the dock in main
    s = B[:8]
    for testid, form in ((f"approach-{s}", f"mk-{s}"), (f"need_info-{s}", f"mk-{s}"), (f"not_suitable-{s}", f"ns-{s}")):
        assert re.search(rf'form="{form}"[^>]*data-testid="{testid}"', dock), testid
        assert f'id="{form}"' in main  # the form the button submits is on the page
    card = main.split(f"<h2>{html.escape(CATALOGUES[lang]['patient.your_mark'])}</h2>")[1].split("</section>")[0]
    assert 'data-testid="markbar"' not in card


def test_the_coordinator_full_page_has_no_mark_dock(box: dict[str, Any]) -> None:  # noqa: F811
    _setup(box)
    page = _as(box, "crc", "ja").get(f"/studies/GZQO/patients/{B}").text
    assert 'data-testid="markdock"' not in page and 'data-testid="markbar"' not in page


ALLOWED_LATIN = {"GZQO", "TrialBox", "SCREEN", "CASE", "CRC", "XLSX", "TB_ENV", "TEST", "DEV"}


@pytest.mark.parametrize("lang", ["ja", "zh-TW"])
def test_registry_page_words(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    """UX-033 (the words; one consent path stays UX-012's): no English word on the ja and zh-TW registry pages beyond
    the study id, the product and the command names; the menu item has the page's own name, so the week panel no
    longer shows two links called "Screening log"; the chart-number field has no English abbreviation."""
    _setup(box)
    t = CATALOGUES[lang]
    c = _as(box, "crc", lang)
    for path in ("/pilot/registry", "/pilot/registry/GZQO"):
        main = re.sub(r"<script.*?</script>", "", _main(c.get(path).text), flags=re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", main))
        words = set(re.findall(r"[A-Za-z][A-Za-z_\-]{2,}", text)) - ALLOWED_LATIN
        assert words == set(), (path, words)
    assert t["nav.patients"] == t["registry.title"]
    page = c.get("/pilot/registry/GZQO").text
    assert f'<label for="mrn">{html.escape(t["registry.mrn"])}</label>' in page and "MRN" not in t["registry.mrn"]
    week = c.get(f"/studies/GZQO/week?pid={B}").text
    links = re.search(r'<p class="chartlinks">(.*?)</p>', week, re.S)
    assert links
    names = [html.unescape(x) for x in re.findall(r">([^<>]+)</a>", links.group(1))]
    assert len(names) == len(set(names)), names


def test_new_layout_keys_in_every_language() -> None:
    for lang in LANGS:
        assert set(LAYOUT_EN) <= set(CATALOGUES[lang]), lang
        for k in LAYOUT_EN:
            assert CATALOGUES[lang][k].strip(), (lang, k)
    for lang in ("ja", "zh-TW"):
        for k in ("nav.patients", "registry.promote.help", "registry.help", "registry.mrn"):
            assert not re.search(r"\b(tier|high|review|screening log|MRN)\b", CATALOGUES[lang][k]), (lang, k)


# ------------------------------------------------------------------------------------------- the screenshots

DESKTOP = (1280, 860)
PHONE = (390, 844)


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_screenshots_ja_and_zh_tw_no_one_character_wrapping(box: dict[str, Any], tmp_path: Path) -> None:  # noqa: F811
    """The review's runs again, measured: walk-pi-ja-desktop-_week (確/認/待/ち, first row at y≈700 of 860), the
    zh-TW phone sheet (clipped referral link) and the full patient page (mark bar below the fold)."""
    _setup(box)
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    css_text = ""

    def put(c: Any, name: str, path: str, lang: str, size: tuple[int, int], checks: list[str]) -> None:
        nonlocal css_text
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code)
        (out / name).write_text(r.text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
        pages.append({"file": name, "lang": lang, "width": size[0], "height": size[1], "checks": checks})
        css_text = css_text or c.get("/static/console.css").text

    for lang in LANGS:
        pi = _as(box, "drsato", lang)
        crc = _as(box, "crc", lang)
        put(
            pi,
            f"pi-{lang}-week-desktop.html",
            "/studies/GZQO/week",
            lang,
            DESKTOP,
            ["row-first-screen", "worklist-fits"],
        )
        put(pi, f"pi-{lang}-week-phone.html", "/studies/GZQO/week", lang, PHONE, [])
        put(pi, f"pi-{lang}-sheet-phone.html", f"/studies/GZQO/week?pid={B}", lang, PHONE, [])
        put(pi, f"pi-{lang}-patient-phone.html", f"/studies/GZQO/patients/{B}", lang, PHONE, ["markbar-first-screen"])
        put(
            pi,
            f"pi-{lang}-patient-desktop.html",
            f"/studies/GZQO/patients/{B}",
            lang,
            DESKTOP,
            ["markbar-first-screen"],
        )
        put(crc, f"crc-{lang}-week-desktop.html", "/studies/GZQO/week", lang, DESKTOP, [])
        put(crc, f"crc-{lang}-registry-desktop.html", "/pilot/registry/GZQO", lang, DESKTOP, [])
        put(crc, f"crc-{lang}-registry-phone.html", "/pilot/registry/GZQO", lang, PHONE, [])
    (out / "console.css").write_text(css_text, encoding="utf-8")
    shots = os.environ.get("TB_UX_SHOTS", "")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages, "shots": shots})],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res.get("error"), r.stderr[-3000:])
    assert res["checks"] >= len(pages) * 4
