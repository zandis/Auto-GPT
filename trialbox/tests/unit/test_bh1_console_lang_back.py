"""Bug hunt BH1 (console access): D-1156 says the language switch's way back is checked by
``console.local_path.is_local``; ``POST /lang`` keeps its own check and redirects to a value that rule refuses. The
framework percent-encodes the backslash, so no browser is sent off the site today: the doc's claim is what is untrue.
Synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name


@pytest.mark.xfail(strict=True, reason="open finding: BH1-13: POST /lang skips local_path.is_local, "
                                       "against D-1156")  # fmt: skip
def test_the_language_switch_checks_its_way_back_with_the_one_rule(box: dict[str, Any]) -> None:  # noqa: F811
    """Entry point: ``POST /lang`` (``console.app.set_lang``)."""
    c, csrf = login(box["app"])
    r = c.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/\\evil.example/x"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/", r.headers["location"]
