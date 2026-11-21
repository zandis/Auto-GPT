"""10F-1 (D-1387; the review's M-5 and L-6): the chosen text size and colour mode, measured in a real browser.

At 150 % text a wide table no longer fits its box on a 1280 px desktop in ja and zh-TW, nor on a 390 px phone: it
scrolls inside its own ``.scroll`` box, a focusable region with a visible focus ring, and the page never scrolls
sideways. The week page's list was such a table; since 9k-14 (D-1386) it is person cards, which must fit their list at
150 % (the ``cards-fit`` check) instead. The account page (a form) is
measured the same way. A dark mode prints on the paper's colours. Rendered by the in-process box with the person's
own preferences, opened in Chromium through Node Playwright (``tests/console/prefs_layout_10f1.js``), skipped where
it is missing, as ``test_cjk_layout``. Synthetic data only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_cjk_layout import PW as CJK_PW
from tests.console.test_cjk_layout import _node_playwright, _setup
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("prefs_layout_10f1.js")
DESKTOP, PHONE = (1280, 860), (390, 844)


def _as(b: dict[str, Any], user: str, values: dict[str, str]) -> Any:
    c, csrf = login(b["app"], user, CJK_PW)
    r = c.post("/account/prefs", data={"csrf": csrf, **values}, follow_redirects=False)
    assert r.status_code == 303
    return c


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_at_150_percent_a_wide_table_scrolls_in_its_box_and_the_page_never_sideways(
    box: dict[str, Any],  # noqa: F811
    tmp_path: Path,
) -> None:
    _setup(box)
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    css = ""

    def put(c: Any, name: str, path: str, lang: str, size: tuple[int, int], checks: list[str]) -> None:
        nonlocal css
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code)
        (out / name).write_text(r.text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
        pages.append({"file": name, "lang": lang, "width": size[0], "height": size[1], "checks": checks})
        css = css or c.get("/static/console.css").text

    for lang in ("ja", "zh-TW"):
        pi = _as(box, "drsato", {"lang": lang, "text_size": "150"})
        assert 'data-text-size="150"' in pi.get("/home").text
        # 9k-14: the week list is person cards now (no table to scroll): the cards hold their list at 150 % text
        put(pi, f"week-{lang}-desktop.html", "/studies/GZQO/week", lang, DESKTOP, ["cards-fit"])
        put(pi, f"week-{lang}-phone.html", "/studies/GZQO/week", lang, PHONE, ["cards-fit"])
        # the candidates' table is still a table: it does not fit at 150 % and scrolls inside its box
        put(pi, f"candidates-{lang}-desktop.html", "/studies/GZQO/candidates", lang, DESKTOP, ["has-wide-table"])
        put(pi, f"candidates-{lang}-phone.html", "/studies/GZQO/candidates", lang, PHONE, ["has-wide-table"])
        put(pi, f"account-{lang}-desktop.html", "/account", lang, DESKTOP, [])
        put(pi, f"account-{lang}-phone.html", "/account", lang, PHONE, [])
        dark = _as(box, "crc", {"lang": lang, "mode": "dark", "text_size": "150"})
        put(dark, f"account-{lang}-dark-print.html", "/account", lang, DESKTOP, ["print-light"])
        put(dark, f"registry-{lang}-phone.html", "/pilot/registry/GZQO", lang, PHONE, [])
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
    assert r.returncode == 0 and res["failed"] == 0, (res.get("error"), r.stderr[-3000:])
    assert res["checks"] >= len(pages)
