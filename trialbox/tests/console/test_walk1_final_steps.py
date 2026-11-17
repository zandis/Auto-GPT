"""WALK-1 (lane H's walk H-20, PR #994): the life cycle's defects and final steps. Synthetic data only.

F-14: a new study was never put in start-up ("No state has been recorded: the study counts as open"), so its type for
SAE reporting was never asked: D-415's gate (a trial opens only with its type) had a hole. D-386 point 3 says a new
study is put in start-up when it is set up; the console now records that itself when a protocol is sent for a study
the box does not know, so the study opens only through the SAE check."""

from __future__ import annotations

import json
from typing import Any

from console.sitestore import SiteStore

from tests.console.test_close_only_an_empty_study import _empty, _post, _state, clock  # noqa: F401 - fixture
from tests.console.test_console_app import box, login  # noqa: F401 - box is a fixture
from tests.console.test_lifecycle_pages import PW as LB_PW
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name
from tests.console.test_sdv import PW as SB_PW
from tests.console.test_sdv import sb  # noqa: F401 - the fixture is used by name

CRITERIA = "Inclusion criteria\n1. Adults with gout\n\nExclusion criteria\n1. Pregnancy\n"


def _events(b: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    root = b.get("dir") or b["backend"].audit_dir.parent
    return [e for f in sorted(root.rglob("*.jsonl")) for x in f.read_text(encoding="utf-8").splitlines() if x
            for e in [json.loads(x)] if e.get("event") == kind]  # fmt: skip


def test_a_new_study_starts_in_start_up(lb: dict[str, Any]) -> None:  # noqa: F811
    c, csrf = login(lb["app"], "crc", LB_PW)
    r = c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "NEWSTUDY", "criteria": CRITERIA},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text
    st = SiteStore().study_state("NEWSTUDY")
    assert st.state == "startup" and st.by == "console:crc" and st.prev is None
    (ev,) = [e for e in _events(lb, "console.study_state") if e.get("ruleset") == "NEWSTUDY"]
    assert ev["detail"]["state"] == "startup" and ev["actor"] == "console:crc"
    # a second protocol for the same id: the box knows the ruleset now (its first job made it), so it keeps its state
    c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "NEWSTUDY", "criteria": CRITERIA})
    assert len(SiteStore().state_history("NEWSTUDY")) == 1


def test_a_refused_request_leaves_no_study_behind(lb: dict[str, Any], monkeypatch: Any) -> None:  # noqa: F811
    """The review of D-1153: the state is written once the job is accepted; a refused request (a limit, a role)
    records nothing."""
    from console.backend import Refused

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise Refused("rate limit reached (5 FEAS jobs today)")

    monkeypatch.setattr(lb["backend"], "create_job", refuse)
    c, csrf = login(lb["app"], "crc", LB_PW)
    r = c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": "REFUSED1", "criteria": CRITERIA})
    assert r.status_code == 429
    assert SiteStore().state_history("REFUSED1") == []


def test_a_protocol_for_a_study_the_box_knows_records_no_state(lb: dict[str, Any]) -> None:  # noqa: F811
    """A running study (before D-386, no state recorded) keeps counting as open: a new protocol version for it is no
    new study."""
    c, csrf = login(lb["app"], "crc", LB_PW)
    known = lb["backend"].rulesets()[0].id
    r = c.post("/pilot/protocol", data={"csrf": csrf, "ruleset": known, "criteria": CRITERIA}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert SiteStore().state_history(known) == []


# ---------------------------------------------------------------- F-11: a participant's final step is named first
def test_a_withdrawal_names_what_becomes_final_before_it_is_recorded(lb: dict[str, Any]) -> None:  # noqa: F811
    """F-11 (D-178: an outcome that ends the contact names its consequence first): Withdraw and Screen fail are
    final; the page asks once, saying so, before the step is recorded. Without a reason it is refused as before."""
    _no, other = lb["nos"]
    c, csrf = login(lb["app"], "crc", LB_PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    page = c.get(f"/studies/GZQO/subjects/{other}").text
    assert 'data-testid="step-reason-required"' in page  # the reason is marked required for the final steps
    r = c.post(f"/studies/GZQO/subjects/{other}/step", data={"csrf": csrf, "to": "screen_fail"})
    assert r.status_code == 409 and "choose a reason" in r.text  # no reason: refused, no sheet
    r = c.post(f"/studies/GZQO/subjects/{other}/step", data={"csrf": csrf, "to": "screen_fail", "reason": "declined"})
    assert r.status_code == 200 and 'data-testid="confirm"' in r.text
    assert "final" in r.text and other in r.text and 'name="reason" value="declined"' in r.text
    assert not any(x.status == "screen_fail" for x in lb["reg"].rows("GZQO"))  # nothing recorded yet
    r = c.post(f"/studies/GZQO/subjects/{other}/step",
               data={"csrf": csrf, "to": "screen_fail", "reason": "declined", "confirm": "yes"})  # fmt: skip
    assert 'data-testid="life-saved"' in r.text


def test_a_step_that_would_be_refused_shows_no_sheet(lb: dict[str, Any]) -> None:  # noqa: F811
    """The review of D-1153: every check of the step runs before its sheet (who, the record, the day, the criterion); a
    step that would be refused is refused at once, never after a Yes."""
    _no, other = lb["nos"]
    c, csrf = login(lb["app"], "crc", LB_PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")  # the list makes the participants
    r = c.post(f"/studies/GZQO/subjects/{other}/step",
               data={"csrf": csrf, "to": "screen_fail", "reason": "not_eligible", "criterion": "GZQO-EXC-99"})  # fmt: skip
    assert r.status_code == 409 and 'data-testid="confirm"' not in r.text and 'data-testid="life-refused"' in r.text
    pi, pcsrf = login(lb["app"], "pi", LB_PW)
    r = pi.post(f"/studies/GZQO/subjects/{other}/step", data={"csrf": pcsrf, "to": "screen_fail", "reason": "declined"})
    assert r.status_code == 403 and 'data-testid="confirm"' not in r.text


# ---------------------------------------------------------------- F-15: the close is named before it is made
def test_a_close_names_what_becomes_final_before_it_is_made(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    """F-15 (D-763, D-178): Closed is final (only the PI may take it back the same day); the page says so, with the
    day the files are kept until, and closes only on Yes. The reason is marked required."""
    _empty(sb)
    crc, _ = login(sb["app"], "crc", SB_PW)
    page = crc.get("/studies/GZQO/state").text
    assert 'id="state-reason"' in page and 'data-testid="state-reason-required"' in page
    r = _post(crc, "/studies/GZQO/state", state="closed", reason="last visit done", keep_years="5")
    assert r.status_code == 200 and 'data-testid="confirm"' in r.text and _state(sb) == "open"
    assert "final" in r.text and "2031-11-05" in r.text  # 2026-11-05 10:00 Taipei plus five years
    assert 'name="keep_years" value="5"' in r.text
    r = _post(crc, "/studies/GZQO/state", state="closed", reason="last visit done", keep_years="5", confirm="yes")
    assert r.status_code == 303 and _state(sb) == "closed"
