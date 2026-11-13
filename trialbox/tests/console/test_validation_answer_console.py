"""NEW-TRUST-2 (D-551): the console's API answers a body of the wrong shape without repeating it."""

from __future__ import annotations

from typing import Any

from tests.console.test_console_app import box  # noqa: F401 - the fixture by name
from tests.console.test_d273_privacy_guards import _api
from tests.console.test_role_pages import _user

CHART = "A1234567"  # synthetic


def test_the_api_does_not_repeat_a_chart_number_it_refuses_for_its_shape(box: dict[str, Any]) -> None:  # noqa: F811
    _user(box, "dpo1", "privacy")
    api, hdr = _api(box, "dpo1")
    r = api.post("/api/v1/site/opt-outs", json={"chart_no": CHART, "lift": "not-a-yes-or-no"}, headers=hdr)
    assert r.status_code == 422 and CHART not in r.text, r.text[:200]
    assert [d["loc"] for d in r.json()["detail"]] == [["body", "lift"]]
    r = api.post("/api/v1/site/opt-outs", json=[CHART], headers=hdr)
    assert r.status_code == 422 and CHART not in r.text
