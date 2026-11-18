"""10K-1: the box's first-run page asks the site's country first (behind ``TB_FIRSTRUN_COUNTRY``, off by default) and
offers SS-MIX2 as a source with the questions it needs. Driven through the real console app; the layout at 390 px is
measured in Chromium (``tests/console/cjk_layout.js``) where Node Playwright is installed. All data is synthetic."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tb_common import firstrun
from tb_common.retention import OVERRIDABLE

from tests.console.test_cjk_layout import PHONE, SCRIPT, _node_playwright
from tests.console.test_firstrun import _answers, _box, _with_code

ROOT = Path(__file__).resolve().parents[2]


def _answered(c: Any, country: str, **over: str) -> Any:
    """The form as the page shows it once the country is chosen (the first step), then posted as in test_firstrun."""
    real_get = c.get
    c.get = lambda url, **kw: real_get(f"{url}?country={country}" if url.endswith("/answers") else url, **kw)
    try:
        r, _ = _answers(c, country=country, **over)
    finally:
        c.get = real_get
    return r


def test_with_the_flag_off_the_page_is_as_before_and_offers_ssmix2(tmp_path: Path) -> None:
    b = _box(tmp_path)
    c = _with_code(b)
    page = c.get("/login/first-run/answers?country=jp").text
    assert 'data-testid="firstrun-country"' not in page and 'name="country"' not in page  # not asked
    assert 'name="site_name"' in page and 'value="ssmix2"' in page and 'name="ssmix2_root"' in page
    r, _ = _answers(c, country="jp", logs_days="1")  # posted all the same: dropped, as the page never asked
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert got["country"] == "" and got["retention_days"] == {}


def test_the_country_is_the_first_question_and_fills_in_its_defaults(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    first = c.get("/login/first-run/answers?lang=ja").text
    assert 'data-testid="firstrun-country"' in first and 'name="site_name"' not in first  # nothing else yet
    for country, word in (("jp", "日本"), ("tw", "台湾"), ("us", "米国"), ("other", "その他の国・地域")):
        assert f'data-testid="country-{country}"' in first and word in first
    jp = c.get("/login/first-run/answers?lang=ja&country=jp").text
    assert 'name="country" value="jp"' in jp and 'id="tz"' in jp and 'value="Asia/Tokyo"' in jp
    assert re.search(r'<option value="ja" selected>', jp)  # the report language
    assert re.search(r'name="source" value="ssmix2" checked', jp)  # SS-MIX2 is Japan's shipped source
    assert 'data-testid="firstrun-retention"' not in jp  # Japan's rules exist (D-138)
    tw = c.get("/login/first-run/answers?country=tw").text
    assert 'value="Asia/Taipei"' in tw and re.search(r'<option value="zh-TW" selected>', tw)
    assert not re.search(r'value="ssmix2" checked', tw)
    us = c.get("/login/first-run/answers?country=us").text
    assert 'data-testid="firstrun-retention"' in us and re.search(r'<option value="en" selected>', us)
    assert 'value="Asia/Tokyo"' in us  # no zone of its own: the box's clock zone, as without a country


def test_a_japanese_box_with_ssmix2_hands_its_answers_to_the_installer(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    r = _answered(c, "jp", source="ssmix2", ssmix2_root="relative")
    assert r.status_code == 422 and 'data-testid="err-ssmix2_root"' in r.text and 'name="country" value="jp"' in r.text
    r = _answered(c, "jp", source="ssmix2", ssmix2_root="/mnt/ssmix2", ssmix2_order_numbers="per_day")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert (got["country"], got["source"], got["ssmix2_root"], got["ssmix2_order_numbers"]) == (
        "jp", "ssmix2", "/mnt/ssmix2", "per_day"
    )  # fmt: skip


def test_a_country_without_rules_asks_the_days(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    r = _answered(c, "other", tz="Europe/Paris", language="en")
    assert r.status_code == 422
    for k in OVERRIDABLE:
        assert f'data-testid="err-{k}"' in r.text, k
    r = _answered(c, "other", tz="Europe/Paris", language="en", **dict.fromkeys(OVERRIDABLE, "400"))
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert got["retention_days"] == dict.fromkeys(OVERRIDABLE, 400)


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_the_new_steps_fit_a_phone_in_three_languages(tmp_path: Path) -> None:
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    for lang in ("en", "ja", "zh-TW"):
        for name, path in (("country", f"?lang={lang}"), ("jp", f"?lang={lang}&country=jp"),
                           ("us", f"?lang={lang}&country=us")):  # fmt: skip
            r = c.get(f"/login/first-run/answers{path}")
            assert r.status_code == 200
            f = f"firstrun-{name}-{lang}.html"
            (out / f).write_text(r.text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
            pages.append({"file": f, "lang": lang, "width": PHONE[0], "height": PHONE[1], "checks": []})
    (out / "console.css").write_text(c.get("/static/console.css").text, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages, "shots": ""})],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res.get("results"), r.stderr[-2000:])
