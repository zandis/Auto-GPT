"""T-715 (D-483; trust review F2): the person on the lifecycle routes, on the real box.

The console of the box (its real backend, the real orchestrator in the production trust configuration,
``tests/orch_box.py``) records a participant's step: the orchestrator's record names the verified person. The
console's own token with a name in the body, the review's confirmed case, changes nothing and names nobody.
"""

from __future__ import annotations

from typing import Any

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
