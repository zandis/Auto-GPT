"""NEW-LIFE-6 (D-763, the deep review's LIFE-006): a study closes only when it is empty.

"Closed" was one form post, final, with no check of subjects on study or of open SAE reports; a closed study mails
nothing, so at last-patient-in a coordinator who picked "closed" (the natural word) stopped the visit and overdue-SAE
mails of every subject in follow-up, for good. Now:

* ``closed`` is refused while a subject is consented, enrolled or on study, or an SAE report is still to send, and
  the refusal names the counts; a study store that cannot be read refuses too (never closed by default);
* "paused" reads "closed to recruitment / paused" in the three languages (what the coordinator meant);
* the study's PI may take back a close made the same site day; nobody else, and not on a later day.

On the orchestrator's real lifecycle routes (``tests.console.test_sdv``'s box); synthetic data only."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from console.i18n import CATALOGUES

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW as LPW
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf
from tests.console.test_sdv import NO, PIDS, PW, sb  # noqa: F401 - the fixture is used by name

NOW = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)  # 10:00 in Taipei


def _state(b: dict[str, Any]) -> str:
    return str(b["app"].state.helpers.store.study_state("GZQO").state)


def _post(client: Any, path: str, **form: str) -> Any:
    page = client.get("/studies/GZQO/state").text
    return client.post(path, data={"csrf": _csrf(page), **form}, follow_redirects=False)


def _empty(b: dict[str, Any]) -> None:
    """Both enrolled subjects end: one completes, one withdraws (the study is empty of subjects on study)."""
    for no, to, extra in ((NO, "on_study", {}), (NO, "completed", {}),
                          (b["nos"][PIDS["gone"]], "withdrawn", {"reason": "1"})):  # fmt: skip
        r = b["oc"].post(f"/studies/GZQO/subjects/{no}/step", json={"to": to, "by": "crc", "on_day": "2026-11-04",
                                                                     **extra})  # fmt: skip
        assert r.status_code == 200, (no, to, r.text)


@pytest.fixture
def clock(sb: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    h = sb["app"].state.helpers
    now = {"at": NOW}
    h.clock = lambda: now["at"]
    return now


def test_a_study_with_subjects_on_study_is_not_closed(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    crc, _ = login(sb["app"], "crc", PW)
    r = _post(crc, "/studies/GZQO/state", state="closed", reason="last patient in")
    assert r.status_code == 409 and _state(sb) == "open"
    assert 'data-testid="state-error"' in r.text and "2" in r.text  # two enrolled subjects, named as a count
    assert 'data-testid="close-refused"' in r.text


def test_an_open_sae_report_keeps_the_study_open(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 1  # the SAE register: one report still to send
    crc, _ = login(sb["app"], "crc", PW)
    r = _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out")
    assert r.status_code == 409 and _state(sb) == "open" and 'data-testid="close-refused"' in r.text


def test_a_study_store_that_cannot_be_read_does_not_close(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    from console.backend import Unavailable

    def down(*_a: Any, **_k: Any) -> Any:
        raise Unavailable("orchestrator")

    sb["backend"].study_api = down
    crc, _ = login(sb["app"], "crc", PW)
    r = _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out")
    assert r.status_code == 409 and _state(sb) == "open"


def test_an_empty_study_closes_and_its_pi_takes_it_back_the_same_day(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 0
    crc, _ = login(sb["app"], "crc", PW)
    assert _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out").status_code == 303
    assert _state(sb) == "closed"
    # the coordinator may not take it back; the PI may, the same day, with a reason
    assert _post(crc, "/studies/GZQO/state/take-back", reason="closed by mistake").status_code == 403
    pi, _ = login(sb["app"], "drsato", PW)
    page = pi.get("/studies/GZQO/state").text
    assert 'data-testid="take-back-form"' in page
    assert _post(pi, "/studies/GZQO/state/take-back", reason="").status_code == 400  # a reason is needed
    r = _post(pi, "/studies/GZQO/state/take-back", reason="closed by mistake")
    assert r.status_code == 303 and _state(sb) == "open"
    hist = sb["app"].state.helpers.store.state_history("GZQO")
    assert [(e.prev, e.state) for e in hist][-2:] == [("open", "closed"), ("closed", "open")]


def test_a_close_is_not_taken_back_on_a_later_day(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 0
    crc, _ = login(sb["app"], "crc", PW)
    assert _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out").status_code == 303
    clock["at"] = datetime(2026, 11, 5, 16, 30, tzinfo=UTC)  # 00:30 the next day in Taipei
    pi, _ = login(sb["app"], "drsato", PW)
    assert 'data-testid="take-back-form"' not in pi.get("/studies/GZQO/state").text
    assert _post(pi, "/studies/GZQO/state/take-back", reason="too late").status_code == 409
    assert _state(sb) == "closed"


def test_paused_reads_closed_to_recruitment_in_every_language() -> None:
    assert "recruitment" in CATALOGUES["en"]["sstate.paused"].lower()
    assert "募集" in CATALOGUES["ja"]["sstate.paused"]
    assert "收案" in CATALOGUES["zh-TW"]["sstate.paused"]
    for lang in ("en", "ja", "zh-TW"):
        for key in ("sstate.close_refused", "sstate.close_unknown", "sstate.take_back", "sstate.take_back_help",
                    "sstate.take_back_late"):  # fmt: skip
            assert CATALOGUES[lang].get(key), (lang, key)


# ---------------------------------------------------------------------------------------------- the review's cases
def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    import json

    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines() if x and json.loads(x).get("event") == name]
    return out


def test_a_closed_study_takes_no_subject_back_on_study(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    """The review of D-763 (1): an undo of the last completion, or a step back on study, after the close."""
    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 0
    crc, _ = login(sb["app"], "crc", PW)
    assert _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out").status_code == 303
    page = crc.get(f"/studies/GZQO/subjects/{NO}").text
    r = crc.post(f"/studies/GZQO/subjects/{NO}/undo", data={"csrf": _csrf(page), "note": "by mistake"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 409 and "closed" in r.text
    assert sb["oc"].get(f"/studies/GZQO/subjects/{NO}").json()["subject"]["state"] == "completed"
    cand = sb["nos"][PIDS["cand"]]
    page = crc.get(f"/studies/GZQO/subjects/{cand}").text
    r = crc.post(f"/studies/GZQO/subjects/{cand}/step", data={"csrf": _csrf(page), "to": "consented",
                                                             "on_day": "2026-11-05"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 409


def test_a_register_that_fails_any_way_refuses_the_close_with_its_reason(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    """The review of D-763 (3): a failure inside the register (a database error, a malformed AE) is the plain
    "could not be read" refusal, never a 500."""
    _empty(sb)

    def broken(rid: str) -> int:
        raise KeyError("ae_aware")

    sb["app"].state.helpers.sae_open = broken
    crc, _ = login(sb["app"], "crc", PW)
    r = _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out")
    assert r.status_code == 409 and _state(sb) == "open" and 'data-testid="state-error"' in r.text


def test_only_the_studys_pi_takes_back_and_the_step_is_audited(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    from tests.console.test_team_pages import _log_pi_and_sub

    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 0
    sb["users"].create("drkato", "investigator", PW, "drkato@hospa.test")
    pi, _ = login(sb["app"], "drsato", PW)
    _log_pi_and_sub(sb, pi, ("screen", "enter_data"))  # a sub-investigator of the study, ticked for tasks
    crc, _ = login(sb["app"], "crc", PW)
    assert _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out").status_code == 303
    sub, _ = login(sb["app"], "drkato", PW)
    assert _post(sub, "/studies/GZQO/state/take-back", reason="mine").status_code == 403
    assert _post(pi, "/studies/GZQO/state/take-back", reason="closed by mistake").status_code == 303
    took = [e for e in _events(sb, "console.study_state") if e["detail"].get("take_back")]
    assert len(took) == 1 and took[0]["detail"]["state"] == "open" and took[0]["detail"]["prev"] == "closed"


def test_the_real_register_counts_a_serious_ae_not_yet_acknowledged(lb: dict[str, Any]) -> None:  # noqa: F811
    """The review of D-763 (2, 5): the count over the real register (no stand-in): a serious AE the investigator has
    not acknowledged, with no report rule set chosen yet (no clock, so no report row), keeps the study open."""
    from tests.console.test_sae_d277 import FATAL

    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", LPW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "ae1", "values": FATAL, "by": "rc:read"})
    page = c.get("/studies/GZQO/state").text
    r = c.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "closed", "reason": "end"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 409 and 'data-testid="close-refused"' in r.text
    assert "Not closed: 0 participants" in r.text  # the serious AE alone keeps it open


def test_the_api_twin_takes_back_for_the_pi_only(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    from fastapi.testclient import TestClient

    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 0
    crc, _ = login(sb["app"], "crc", PW)
    assert _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out").status_code == 303

    def api(user: str) -> TestClient:
        c = TestClient(sb["app"])
        tok = c.post("/api/v1/session", json={"username": user, "password": PW}).json()["token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        return c

    path = "/api/v1/studies/GZQO/state/take-back"
    assert api("crc").post(path, json={"reason": "mine"}).status_code == 403
    assert api("drsato").post(path, json={"reason": ""}).status_code == 400
    r = api("drsato").post(path, json={"reason": "closed by mistake"})
    assert r.status_code == 200 and r.json() == {"study": "GZQO", "state": "open"} and _state(sb) == "open"
