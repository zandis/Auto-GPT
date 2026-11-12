"""T-716 (D-484; trust review F5, TR-4): the orchestrator reads the break-glass grant itself, on the real box.

The acceptance of the card: a grant for patient A used for patient B is 403 at the orchestrator. The console of the
box (its real backend, the real orchestrator in the production trust configuration, ``tests/orch_box.py``) opens a
grant as the administrator does on the page; then the orchestrator is asked directly, with the console's own token
and a signed claim that names that grant, for another patient, as another person, after the grant ended, and with
a grant that does not exist. Synthetic patients only.
"""

from __future__ import annotations

from typing import Any

import pytest
from console.backend import Refused
from console.breakglass import BreakGlassStore

from tests.actor3 import log_pi, signer
from tests.console.test_console_app import ADMIN_PW, CRC_PW, login
from tests.console.test_d280_breakglass import _open
from tests.console.test_orch_box import site  # noqa: F401  (the console of the box)
from tests.console.test_role_pages import _csrf
from tests.orch_box import STUDY, OrchBox


def _uses(gid: int) -> list[tuple[str, str, str]]:
    store = BreakGlassStore()
    try:
        return [(u.what, u.pid, u.job_id) for u in store.uses_of([gid]).get(gid, [])]
    finally:
        store.close()


def _grant_of(ob: OrchBox, n: int = -1) -> int:
    return int(ob.events("console.breakglass_open")[n]["detail"]["grant"])


def test_a_grant_for_patient_a_used_for_patient_b_is_403_at_the_orchestrator(site: dict[str, Any]) -> None:  # noqa: F811
    ob: OrchBox = site["ob"]
    bk, job = site["backend"], ob.screen()
    a, b = ob.listed()[:2]
    log_pi("drsato", STUDY)  # the study has a PI (the steward's log); the administrator is not on it
    adm, _ = login(site["app"], "admin", ADMIN_PW)
    assert _open(adm, kind="patient", ruleset=STUDY, pid=a).headers["location"] == "/breakglass?done=open"
    gid = _grant_of(ob)
    as_admin: dict[str, Any] = {"sub": "console:admin", "role": "admin", "grant": {"id": str(gid)}}
    # the acceptance: the same grant, patient B, asked of the orchestrator with the console's own token
    with pytest.raises(Refused, match="break-glass grant: the grant is for another patient"):
        bk.reveal(job.job_id, b, signer(STUDY, **as_admin))
    refused = ob.events("screen.reveal_refused")[-1]
    assert refused["actor"] == "console:admin" and refused["detail"] == {
        "pid": b, "reason": "break-glass grant: the grant is for another patient", "role": "admin", "grant": str(gid),
    }  # fmt: skip
    r = ob.client("console").post(
        f"/jobs/{job.job_id}/reveal", json={"pid": b},
        headers=signer(STUDY, **as_admin)("POST", f"/jobs/{job.job_id}/reveal", {"pid": b}),
    )  # fmt: skip
    assert r.status_code == 403
    assert not ob.events("screen.reveal") and _uses(gid) == []
    # every other way the claim's word for a grant is not the row
    for sign, why in (
        (signer(STUDY, sub="console:admin", role="admin", grant={"id": "999999"}), "no such grant"),
        (signer(STUDY, sub="console:admin", role="admin", grant={"id": "x"}), "no such grant"),
        (signer(STUDY, sub="console:other", role="admin", grant={"id": str(gid)}), "another person's grant"),
        (signer(STUDY, sub="console:crc", role="coordinator", grant={"id": str(gid)}), "grant"),  # may hold none
        (signer(STUDY, sub="console:admin", role="admin"), "right"),  # no grant named: the administrator's own role
        (signer(STUDY, sub="console:admin", role="breakglass"), "right"),  # the old word
    ):
        with pytest.raises(Refused, match=why):
            bk.reveal(job.job_id, a, sign)
    assert not ob.events("screen.reveal") and _uses(gid) == []
    # the grant for patient A, used for patient A: the chart number, and the use written by the orchestrator
    assert bk.reveal(job.job_id, a, signer(STUDY, **as_admin), purpose="patient") == ob.mrn[a]
    given = ob.events("screen.reveal")
    assert len(given) == 1 and given[0]["actor"] == "console:admin"
    assert given[0]["detail"]["grant"] == str(gid) and given[0]["detail"]["role"] == "admin"
    assert _uses(gid) == [("reveal", a, job.job_id)]
    # ended by hand: the same claim opens nothing any more
    page = adm.get("/breakglass").text
    assert adm.post(f"/breakglass/{gid}/end", data={"csrf": _csrf(page)}, follow_redirects=False).status_code == 303
    with pytest.raises(Refused, match="break-glass grant: the grant is not open"):
        bk.reveal(job.job_id, a, signer(STUDY, **as_admin))
    assert _uses(gid) == [("reveal", a, job.job_id)]


def test_the_administrator_reveals_under_a_grant_through_the_console(site: dict[str, Any]) -> None:  # noqa: F811
    """The whole path: the page, the console's rule, the claim with the grant's id, the orchestrator's reading of
    the row, the pid map; and the use on the steward's list is the orchestrator's row."""
    ob: OrchBox = site["ob"]
    job = ob.screen()
    a, b = ob.listed()[:2]
    log_pi("drsato", STUDY)
    adm, csrf = login(site["app"], "admin", ADMIN_PW)
    r = adm.post(f"/pilot/jobs/{job.job_id}/reveal", data={"csrf": csrf, "pid": a, "reason": "contact"})
    assert r.status_code == 403 and not ob.events("screen.reveal")  # no grant: the console refuses first
    assert _open(adm, kind="job", job_id=job.job_id).headers["location"] == "/breakglass?done=open"
    gid = _grant_of(ob)
    r = adm.post(f"/pilot/jobs/{job.job_id}/reveal", data={"csrf": csrf, "pid": a, "reason": "contact"})
    assert r.status_code == 200 and ob.mrn[a] in r.text, r.text[-300:]
    r = adm.post(f"/pilot/jobs/{job.job_id}/reveal", data={"csrf": csrf, "pid": b, "reason": "contact"})
    assert r.status_code == 200 and ob.mrn[b] in r.text  # a job grant covers the job's list
    given = ob.events("screen.reveal")
    assert [e["detail"]["grant"] for e in given] == [str(gid)] * 2 and {e["detail"]["role"] for e in given} == {"admin"}
    reveals = [u for u in _uses(gid) if u[0] == "reveal"]
    assert reveals == [("reveal", a, job.job_id), ("reveal", b, job.job_id)]  # written where the number was given
    shown = ob.events("console.reveal_patient")
    assert len(shown) == 2 and {e["detail"]["breakglass"] for e in shown} == {gid}
    assert len([e for e in ob.events("console.breakglass_use") if e["detail"]["what"] == "reveal"]) == 2


def test_an_investigator_reveals_by_the_log_the_orchestrator_reads(site: dict[str, Any]) -> None:  # noqa: F811
    """The delegation log: an investigator the log does not name gets nothing from the orchestrator, whatever
    standing the claim carries; the PI the log names does."""
    from tb_common.authz import Standing

    ob: OrchBox = site["ob"]
    bk, job, pid = site["backend"], ob.screen(), ob.listed()[0]
    as_pi = Standing(is_pi=True, tasks=frozenset({"screen"}), log_names_pi=True)
    dr: dict[str, Any] = {"sub": "console:drlee", "role": "investigator", "standing": as_pi}
    with pytest.raises(Refused, match="delegation"):
        bk.reveal(job.job_id, pid, signer(STUDY, **dr))  # a claim that says "PI": the log names nobody
    log_pi("drsato", STUDY)
    with pytest.raises(Refused, match="delegation"):
        bk.reveal(job.job_id, pid, signer(STUDY, **dr))  # the log names another person
    assert not ob.events("screen.reveal")
    assert (
        bk.reveal(job.job_id, pid, signer(STUDY, sub="console:drsato", role="investigator", standing=as_pi))
        == ob.mrn[pid]
    )
    c, csrf = login(site["app"], "crc", CRC_PW)  # and the coordinator's own row needs no log
    r = c.post(f"/pilot/jobs/{job.job_id}/reveal", data={"csrf": csrf, "pid": pid, "reason": "contact"})
    assert r.status_code == 200 and ob.mrn[pid] in r.text


def test_a_store_that_cannot_be_read_gives_nothing(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """A box updated without the role script: the orchestrator's role is not in the two schemas yet. It fails
    closed with the reason on the record; a coordinator, whose right needs neither store, is not affected."""
    import console.breakglass as bg_mod
    import console.teamstore as team_mod

    ob: OrchBox = site["ob"]
    bk, job, pid = site["backend"], ob.screen(), ob.listed()[0]

    def denied(*_a: Any, **_k: Any) -> Any:
        raise PermissionError("permission denied for schema")

    monkeypatch.setattr(bg_mod, "BreakGlassStore", denied)
    monkeypatch.setattr(team_mod, "TeamStore", denied)
    with pytest.raises(Refused, match="break-glass grant: the grant store cannot be read"):
        bk.reveal(job.job_id, pid, signer(STUDY, sub="console:admin", role="admin", grant={"id": "1"}))
    with pytest.raises(Refused, match="the delegation log cannot be read"):
        bk.reveal(job.job_id, pid, signer(STUDY, sub="console:drsato", role="investigator"))
    assert not ob.events("screen.reveal") and len(ob.events("screen.reveal_refused")) == 2
    assert bk.reveal(job.job_id, pid, signer(STUDY)) == ob.mrn[pid]
