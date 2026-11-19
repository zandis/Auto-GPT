"""Card 10C-3 (lane J proposes, lane C2 decides): the header search and a study the investigator is not delegated in.

Synthetic data only. An investigator is a sub-investigator on study A's delegation log (RA-BIO, ticked "screen") and
on no entry of study B's (GZQO, whose log names another PI). Study B has one pre-consent candidate with a screening
number. The investigator is refused study B's weekly list and the candidate's patient page (D-147, D-273, D-380).

The proposal (``docs/handover/matrix-proposal-pre-consent-lists-2026-11-19.md`` section 4.1; D-1238, proposed): the
header search (``/cmd?q=``, ``console.step4.search``) finds no patient of a study the account's log does not reach.
Today it does: it answers a screening number or a 12-character pseudonym prefix of study B with a redirect to the
patient's page, carrying the full pseudonym. So the test is an expected failure, with the reason "proposal 10C-3,
awaiting lane C2's decision": not strict by default, strict under ``TB_PROPOSAL_10C3=1`` (as the table test
``tests/unit/test_proposal_10c3_pre_consent_matrix.py``). It changes no other test and no behaviour."""

from __future__ import annotations

import os
from typing import Any

import pytest
from console.sitestore import StudySettings

from tests.console.test_console_app import box, login, sub_investigator  # noqa: F401 - the fixture is used by name

REASON = "proposal 10C-3, awaiting lane C2's decision"
SWITCHED_ON = os.environ.get("TB_PROPOSAL_10C3") == "1"
PW = "proposal-10c3-password-01"
AT = "2026-11-07T09:00:00+00:00"
PID = "cd" * 16  # a synthetic pseudonym in study B


@pytest.mark.xfail(strict=SWITCHED_ON, reason=f"{REASON}: the search does not ask the delegation log today")
def test_the_header_search_finds_no_patient_of_a_study_off_the_investigators_log(box: dict[str, Any]) -> None:  # noqa: F811
    box["users"].create("subi_a", "investigator", PW, "subi_a@hospa.test")
    sub_investigator(box, "subi_a", ("screen",), rs="RA-BIO")  # on study A's log only
    sub_investigator(box, "other_subi", ("screen",), rs="GZQO")  # study B's log names a PI (lead), not subi_a
    no = box["app"].state.helpers.store.assign_screening_no("GZQO", PID, StudySettings(), AT)
    c, _ = login(box["app"], "subi_a", PW)

    # the controls: the pages of study B refuse this investigator today (D-147, D-273)
    assert c.get("/studies/GZQO/week", follow_redirects=False).status_code == 403
    assert c.get(f"/studies/GZQO/patients/{PID}", follow_redirects=False).status_code == 403

    # the proposal: the search gives nothing of study B either, by screening number or by pseudonym prefix
    for q in (no.lower(), PID[:12]):
        r = c.get("/cmd", params={"q": q}, follow_redirects=False)
        where = r.headers.get("location", "")
        assert "/studies/GZQO/patients/" not in where, f"q={q!r}: {r.status_code} to {where}"
        assert PID not in r.text, f"q={q!r}: the page names the pseudonym"
