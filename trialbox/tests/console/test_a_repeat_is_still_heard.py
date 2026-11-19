"""D-1160, its review: a repeat that is not the same act is still heard. An Approach after one that was no override
writes its override; a second break-glass open with a new justification is audited; a digest whose sender died
between its claim and its send is sent by the next run, and shown as received only once sent. Synthetic data only."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from console.backend import read_audit

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture by name
from tests.console.test_d280_breakglass import A as BG_A
from tests.console.test_d280_breakglass import _open
from tests.console.test_lifecycle_mediums_pages import A
from tests.console.test_twice_one_effect import STUDY, _all_events, _marked, lb  # noqa: F401 - the fixture by name


def test_an_approach_after_one_that_was_no_override_writes_its_override(lb: dict[str, Any]) -> None:  # noqa: F811
    pi, csrf = _marked(lb)
    team = lb["app"].state.helpers.team
    team.db.execute("DELETE FROM approach_overrides")  # the first Approach as if made while the IRB was clean
    before = _all_events(lb).count("console.approach_override")
    pi.post(f"/studies/{STUDY}/patients/{A}/mark", data={"csrf": csrf, "mark": "approach"}, follow_redirects=False)
    assert len(team.overrides(STUDY)) == 1, "an Approach under the warning wrote no override"
    assert _all_events(lb).count("console.approach_override") == before + 1


def test_a_second_open_with_a_new_justification_is_audited(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(999))
    admin, _ = login(box["app"])
    _open(admin, kind="patient", ruleset="GZQO", pid=BG_A)
    _open(admin, kind="patient", ruleset="GZQO", pid=BG_A, note="a second call, another question about the patient")
    events = [r.event for r in read_audit(box["dir"] / "audit")]
    assert events.count("console.breakglass_open") == 2, "the new justification was not audited"


def test_a_digest_whose_sender_died_is_sent_by_the_next_run(lb: dict[str, Any]) -> None:  # noqa: F811
    store, clock = lb["app"].state.helpers.store, lb["app"].state.helpers.clock
    now = clock()
    old = (now - timedelta(hours=1)).isoformat()
    assert store.claim_notice("N1", "atdied", "2026-11-11", old)  # claimed, then the process died: never sent
    assert not any(n[0] == "N1" and n[1] == "2026-11-11" for n in store.notices_for("atdied")), "shown as received"
    stale = (now - timedelta(minutes=15)).isoformat()
    assert not store.notice_sent("N1", "atdied", "2026-11-11", stale_before=stale)
    assert store.claim_notice("N1", "atdied", "2026-11-11", now.isoformat(), stale_before=stale)  # the next run
    assert not store.claim_notice("N1", "atdied", "2026-11-11", now.isoformat(), stale_before=stale)  # once
    store.finish_notice("N1", "atdied", "2026-11-11", now.isoformat(), "GZQO: 1 patient before clinic")
    assert any(n[3] == "GZQO: 1 patient before clinic" for n in store.notices_for("atdied"))
