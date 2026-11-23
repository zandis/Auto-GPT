"""U5-01 (card U-5, the owner's rule as the integrator relayed it on #639): a missing piece of site information never
stops a PoC box. The walk on a VALIDATION box found that a study which reports serious adverse events could not open
without the trial office's mailbox, because the gate exempted DEV and TEST only. D-1091's PoC set is DEV, TEST and
VALIDATION: each opens without it. A PRODUCTION box still refuses (the go-live gate), and opens once it is given.

Synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest

import tests.console.test_console_app as _app
import tests.console.test_lifecycle_pages as _life
from tests.console.test_role_pages import _csrf

# the fixtures, found by name: the box, and the lifecycle box built on it
box = _app.box
lb = _life.lb
login, name_pi, PW = _app.login, _app.name_pi, _life.PW


def _try_open(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch, env: str) -> int:
    from console import study_setup

    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)
    name_pi(lb, "pi")
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"}, follow_redirects=True)
    c.post("/studies/GZQO/state", data={"csrf": csrf, "state": "paused", "reason": "set-up"}, follow_redirects=False)
    monkeypatch.setattr(study_setup, "environment_name", lambda _env: env)
    page = c.get("/studies/GZQO/state").text
    r = c.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "open"}, follow_redirects=False)
    return int(r.status_code)


@pytest.mark.parametrize("env", ["DEV", "TEST", "VALIDATION"])
def test_a_poc_box_opens_a_study_without_the_office_mailbox(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    env: str,
) -> None:
    assert _try_open(lb, monkeypatch, env) == 303


def test_a_production_box_still_refuses_without_the_office_mailbox(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _try_open(lb, monkeypatch, "PRODUCTION") == 409
