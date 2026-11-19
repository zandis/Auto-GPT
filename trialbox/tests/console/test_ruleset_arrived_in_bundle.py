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
