"""10C-13 (D-1229): the CASE sheet and the released consent page with "both"-style dates at 390 px, in ja, zh-TW and
en: no line of a date holds one character, and no page is wider than the same page with Western dates (the English
CASE sheet already scrolls sideways at 390 px with Western dates, on master too: not this card's). Measured in Chromium
(``tests/console/printed_dates_layout.js``) where Node Playwright is installed. All data is synthetic."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from orchestrator.reports import case_html, consent_html
from orchestrator.scenarios import consent as c

from tests.console.test_cjk_layout import PHONE, _node_playwright
from tests.unit.test_consent_unit import _rec as _consent_rec
from tests.unit.test_wording_outputs import _case_rec

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("printed_dates_layout.js")
CASE_DATES = [
    "2026年（令和8年）10月5日",
    "2026年（令和8年）10月4日",
    "2026年（令和8年）9月1日",
    "2026年（令和8年）9月18日",
]
CONSENT_DATE = "2026年（令和8年）11月18日"


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_both_style_dates_fit_a_phone_on_the_printed_pages(tmp_path: Path) -> None:
    pages: list[dict[str, Any]] = []
    release = {"by": "crc1@hospa.test", "at": "2026-11-18T10:00:00+09:00", "job_id": "01J"}
    crec = _consent_rec()
    for lang in ("ja", "zh-TW", "en"):
        for style in ("both", "western"):
            f = f"case-{lang}-{style}.html"
            (tmp_path / f).write_bytes(case_html.sheet(_case_rec(lang), style))
            pages.append({"file": f, "width": PHONE[0], "height": PHONE[1], "dates": CASE_DATES * (style == "both")})
            if lang in crec["languages"]:
                g = f"consent-{lang}-{style}.html"
                view = c.released_view(crec, lang, [], [])
                (tmp_path / g).write_bytes(consent_html.patient(crec, lang, view, release=release, dates=style))
                dates = [CONSENT_DATE] * (style == "both")
                pages.append({"file": g, "width": PHONE[0], "height": PHONE[1], "dates": dates})
    assert any(p["file"].startswith("consent-") for p in pages)
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(tmp_path), "pages": pages})],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res.get("results"), r.stderr[-2000:])
    width = {x["file"]: x["scrollWidth"] for x in res["results"]}
    for f, w in width.items():
        if f.endswith("-both.html"):
            assert w <= width[f.replace("-both", "-western")], (f, width)
    assert res["checks"] >= 3 * len(CASE_DATES)
