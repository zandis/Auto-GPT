"""10D-28 (D-1369): where the console lists rule sets, a version that arrived in a vendor bundle (compiled and approved
on another box) says so, in en, ja and zh-TW; a version approved here reads as before. Synthetic data only."""

from __future__ import annotations

import re
from typing import Any

import pytest
from console.backend import RulesetInfo
from console.i18n import translate

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_overview_marks_a_rule_set_that_arrived_in_a_vendor_bundle(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    box["backend"].rulesets = lambda: [RulesetInfo("GZQO", "1.0.0", "approved", "trial", "vendor_bundle"),
                                       RulesetInfo("RA-BIO", "1.0.0", "approved", "nhi")]  # fmt: skip
    c, _ = login(box["app"])
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
    assert csrf
    c.post("/lang", data={"csrf": csrf.group(1), "lang": lang, "back": "/"})
    page = c.get("/").text
    words = translate(lang, "overview.arrived_in_bundle")
    assert words != "overview.arrived_in_bundle" and words in page
    assert page.count('data-testid="arrived-in-bundle"') == 1  # GZQO only; RA-BIO was approved here


def test_a_rule_set_approved_here_has_no_mark(box: dict[str, Any]) -> None:  # noqa: F811
    c, _ = login(box["app"])
    page = c.get("/").text
    assert "GZQO" in page and 'data-testid="arrived-in-bundle"' not in page


def test_the_administrators_page_marks_it(box: dict[str, Any]) -> None:  # noqa: F811
    """``admin.html`` (the administrator's page, ``/admin``): the approvals tile lists the approved versions."""
    box["backend"].rulesets = lambda: [RulesetInfo("GZQO", "1.0.0", "approved", "trial", "vendor_bundle"),
                                       RulesetInfo("RA-BIO", "1.0.0", "approved", "nhi")]  # fmt: skip
    c, _ = login(box["app"])
    page = c.get("/admin").text
    tile = page[page.index('data-testid="tile-approvals"') :]
    tile = tile[: tile.index("</section>")]
    assert f"GZQO v1.0.0 · approved · {translate('en', 'overview.arrived_in_bundle')}" in tile
    assert "RA-BIO v1.0.0 · approved</li>" in tile


def test_the_administrators_home_without_step_4_marks_it() -> None:
    """``home_admin.html`` (the administrator's home where the step-4 page is not installed): rendered on its own,
    with the console's text catalogue, as ``console.home.admin_home`` renders it."""
    from pathlib import Path

    import console
    from jinja2 import ChainableUndefined, Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(Path(console.__file__).parent / "templates"),
                      undefined=ChainableUndefined, autoescape=True)  # fmt: skip
    env.filters.update(local=lambda v, n=16: str(v), mask_ids=str, who=str)
    env.globals.update(t=lambda k, **kw: translate("ja", k), permit=lambda *a, **k: None, public_url="",
                       reason_label=lambda *a: "", feas_notes=lambda *a: "")  # fmt: skip
    rulesets = [RulesetInfo("GZQO", "1.0.0", "approved", "trial", "vendor_bundle"),
                RulesetInfo("RA-BIO", "1.0.0", "approved", "nhi")]  # fmt: skip
    page = env.get_template("home_admin.html").render(
        rulesets=rulesets,
        waiting=[],
        users=[],
        by_aff={},
        soon=[],
        reveals=[],
        counts={},
        health=[],
        models=None,
        term_refused=[],
    )
    words = translate("ja", "overview.arrived_in_bundle")
    assert page.count(words) == 1 and f"GZQO v1.0.0 · {translate('ja', 'admin.approved')} · {words}" in page
