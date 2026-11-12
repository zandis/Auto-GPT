"""T-715 (D-483; trust review F2): the person on the lifecycle routes, on the real box.

The console of the box (its real backend, the real orchestrator in the production trust configuration,
``tests/orch_box.py``) records a participant's step: the orchestrator's record names the verified person. The
console's own token with a name in the body, the review's confirmed case, changes nothing and names nobody.
"""

from __future__ import annotations

from typing import Any

from orchestrator import actor as ra

from tests.actor3 import signed
from tests.console.test_console_app import CRC_PW, login
from tests.console.test_orch_box import site  # noqa: F401  (the console of the box)
from tests.orch_box import STUDY, OrchBox


def test_a_name_in_the_body_changes_nothing_and_names_nobody(orch_box: OrchBox) -> None:
    """F2 as the review ran it, on the lifecycle routes: a service token and ``"by": "dr_tanaka"``."""
    c = orch_box.client("console")
    r = c.put(f"/studies/{STUDY}/sae-rule", json={"rule_set": "tw_trial", "by": "console:dr_tanaka"})
    assert r.status_code == 403, r.text[:300]
    assert c.get(f"/studies/{STUDY}/sae-rule").json()["rule_set"] == ""  # nothing was saved
    r = c.post(f"/studies/{STUDY}/subjects/refresh", json={"screening": {"GZQO-0001": "a" * 32}, "by": "dr_tanaka"})
    assert r.status_code == 403 and c.get(f"/studies/{STUDY}/subjects").json()["subjects"] == []
    r = c.put(f"/studies/{STUDY}/sponsor/layout", json={"layout": {"log": []}, "by": "console:dr_tanaka"})
    assert r.status_code == 403
    named = [e for kind in ("life.sae_rule", "life.step", "life.log_sync", "sponsor.layout")
             for e in orch_box.events(kind)]  # fmt: skip
    assert named == []  # no record under the typed name


def test_a_coordinators_step_is_recorded_under_the_verified_person(site: dict[str, Any]) -> None:  # noqa: F811
    ob: OrchBox = site["ob"]
    h = site["app"].state.helpers
    pid = ob.listed()[0]
    no = h.store.assign_screening_no(STUDY, pid, h.settings_of(STUDY), "2026-10-05T09:00:00+08:00")
    c, csrf = login(site["app"], "crc", CRC_PW)
    page = c.get(f"/studies/{STUDY}/subjects")  # the page brings the participants up to date: a signed refresh
    assert page.status_code == 200 and f'data-testid="subject-{no}"' in page.text, page.text[-400:]
    r = c.post(f"/studies/{STUDY}/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-10-05"})
    assert r.status_code == 200 and 'data-testid="life-saved"' in r.text, r.text[-400:]
    steps = ob.events("life.step")
    assert steps and {e["actor"] for e in steps} == {"console:crc"}
    assert steps[-1]["detail"]["steps"][-1][-1] == "approached" and steps[-1]["detail"]["source"] == "manual"
    assert not ob.events("actor.refused")
    # the same step by a viewer never leaves the console (the one minting place asks the matrix)
    v, vcsrf = login(site["app"], "viewer", "viewer-password-0001")
    r = v.post(f"/studies/{STUDY}/subjects/{no}/step", data={"csrf": vcsrf, "to": "consented"})
    assert r.status_code in (403, 404) and len(ob.events("life.step")) == len(steps)
    # and the orchestrator refuses the same request replayed by hand with the console's token alone
    raw = ob.client("console").post(
        f"/studies/{STUDY}/subjects/{no}/step", json={"to": "consented", "by": "console:crc"}
    )
    assert raw.status_code == 403 and ob.events("actor.refused")[-1]["detail"]["route"].endswith("/step")


def test_a_step_derived_from_a_saved_form_names_a_verified_person_or_nobody(orch_box: OrchBox) -> None:
    """Review H2: the data core is in stage `report`, so an unsigned save of a lifecycle form is let through; the
    step the orchestrator derives from it must not be recorded under the name typed in the body."""
    c = orch_box.client("console")
    assert c.post(f"/studies/{STUDY}/forms/builtin", json={"by": "console:crc", "ctcae": ""}).status_code == 200
    for form, values in (("tb_consent", {"ic_date": "2026-10-05", "ic_version": "v1", "ic_copy": "1"}),
                         ("tb_enrolment", {"en_date": "2026-10-06", "en_eligible": "1"})):  # fmt: skip
        r = c.post(f"/studies/{STUDY}/entry/{STUDY}-0042",
                   json={"form": form, "event": "", "values": values, "by": "console:dr_tanaka"})  # fmt: skip
        assert r.status_code == 200, r.text[:300]
    actors = {e["actor"] for kind in ("life.step", "life.log_sync") for e in orch_box.events(kind)}
    assert actors and "console:dr_tanaka" not in actors and actors == {ra.UNVERIFIED}
    # the same save signed by the person (as the console's entry page signs it) names that person
    path = f"/studies/{STUDY}/entry/{STUDY}-0043"
    body = {"form": "tb_consent", "event": "", "values": {"ic_date": "2026-10-05", "ic_version": "v1", "ic_copy": "1"},
            "by": "console:crc"}  # fmt: skip
    r = c.post(path, json=body, headers=signed("task.enter_data", STUDY, "POST", path, body))
    assert r.status_code == 200, r.text[:300]
    mine = [e for e in orch_box.events("life.step") if e["detail"].get("record") == f"{STUDY}-0043"]
    assert mine and {e["actor"] for e in mine} == {"console:crc"}
    # a claim for another action, or by a role the matrix refuses it, is not a verified person
    path = f"/studies/{STUDY}/entry/{STUDY}-0044"
    r = c.post(path, json=body, headers=signed("task.enter_data", STUDY, "POST", path, body, role="viewer"))
    assert r.status_code == 200
    other = [e for e in orch_box.events("life.step") if e["detail"].get("record") == f"{STUDY}-0044"]
    assert other and {e["actor"] for e in other} == {ra.UNVERIFIED}
