"""Card 10C-3b (D-1241): the header search and a study the investigator is not delegated in.

Synthetic data only. An investigator is a sub-investigator on study A's delegation log (RA-BIO, ticked "screen") and
on no entry of study B's (GZQO, whose log names another PI). The investigator is refused study B's weekly list and its
patient pages (D-147, D-273, D-380). Before D-1241 the header command field (``/cmd?q=``, ``console.step4.search``)
answered a screening number or a pseudonym prefix of study B with a redirect to the patient's page, carrying the full
pseudonym. Now, for an account the patient page of that study refuses, the search answers exactly as it answers a
number or prefix that does not exist: same status, headers, body and audit rows.

The first test is card 10C-3's proof test (draft PR #1132), kept as it was written there, without its expected-fail
mark. The others walk every input kind (a screening number with and without the site's dash, a pseudonym prefix of
8, 12 and 16 characters and the full pseudonym; the ``patient`` and the ``search`` intents), every source the search
reads (the screening numbers, this week's list (D-133), the registry) and every role of the matrix."""

from __future__ import annotations

import json
from typing import Any

import pytest
from console.auth import ROLES
from console.sitestore import StudySettings
from fastapi.testclient import TestClient
from tb_contracts import RegistryEntry

from tests.console.test_console_app import _T0, _done_screen, _ulid, box, login, sub_investigator  # noqa: F401
from tests.console.test_d280_breakglass import _open

PW = "proposal-10c3-password-01"
AT = "2026-11-07T09:00:00+00:00"
PID = "cd" * 16  # a synthetic pseudonym in study B


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


# ---------------------------------------------------------------------------------------------- the world of the walk
WEEK = "a" * 32  # on study B's latest weekly list (``_done_screen``: tier high), found through the week bundle (D-133)
NUMBERED = "cd" * 16  # study B's screening number with the site's dash: the ``patient`` intent
DASHLESS = "c1" * 16  # study B's screening number under a prefix without a dash: the ``search`` intent
REGISTERED = "ef" * 16  # in study B's registry only
BOTH = "d7" * 16  # the same pseudonym in both studies: numbered in A and in B
OWN = "e3" * 16  # study A's own patient (numbered), which the investigator on A's log keeps finding
B_PIDS = (WEEK, NUMBERED, DASHLESS, REGISTERED, BOTH)


def _queries(nos: dict[str, str]) -> list[str]:
    """Every input kind the field accepts for a patient: a screening number (as typed and upper case; with and without
    the site's dash), a pseudonym prefix of 8, 12 and 16 characters and the full pseudonym, for every source; and the
    4 to 7 character prefixes ``search`` accepts but the field reads as no command."""
    qs = [nos[NUMBERED].lower(), nos[NUMBERED], nos[DASHLESS].lower(), nos[DASHLESS], nos[BOTH]]
    for pid in (*B_PIDS, OWN):
        qs += [pid[:8], pid[:12], pid[:16], pid]
    qs += [NUMBERED[:4], WEEK[:7]]
    return qs


def _numbers() -> dict[str, str]:
    """Study B's numbers as they will be given: GZQO-0001 (dash) and GZQONO0002 (no dash); BOTH's number in A."""
    return {NUMBERED: "GZQO-0001", DASHLESS: "GZQONO0002", BOTH: "RA-BIO-0001"}


def _seed(b: dict[str, Any]) -> None:
    """Study B's patients in every source the search reads, and study A's own; synthetic pseudonyms only."""
    store = b["app"].state.helpers.store
    assert store.assign_screening_no("GZQO", NUMBERED, StudySettings(), AT) == "GZQO-0001"
    assert store.assign_screening_no("GZQO", DASHLESS, StudySettings(screening_prefix="GZQONO"), AT) == "GZQONO0002"
    assert store.assign_screening_no("GZQO", BOTH, StudySettings(), AT) == "GZQO-0003"
    assert store.assign_screening_no("RA-BIO", BOTH, StudySettings(), AT) == "RA-BIO-0001"
    assert store.assign_screening_no("RA-BIO", OWN, StudySettings(), AT) == "RA-BIO-0002"
    _done_screen(b["backend"], _ulid(990))  # study B's weekly list: WEEK (high), "b" * 32 (review)
    b["backend"].registry[("GZQO", REGISTERED)] = RegistryEntry(
        ruleset="GZQO", pid=REGISTERED, status="candidate", reason=None, updated_at=_T0, updated_by="lead",
        source="manual", source_job=None, tier=None, events=1,
    )  # fmt: skip


def _audit(b: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line:
                out.append(json.loads(line))
    return out


def _answer(b: dict[str, Any], c: TestClient, q: str) -> dict[str, Any]:
    """One answer of the field, as a person and a later reader of the audit trail see it: the status, every header
    (none is per request here: no date, no cookie), the body and the audit rows the request wrote, without their
    time and chain fields."""
    before = len(_audit(b))
    r = c.get("/cmd", params={"q": q}, follow_redirects=False)
    rows = [{k: v for k, v in x.items() if k in ("event", "actor", "ruleset", "job_id", "detail")}
            for x in _audit(b)[before:]]  # fmt: skip
    return {"status": r.status_code, "headers": sorted(r.headers.items()), "body": r.content, "audit": rows}


def _accounts(b: dict[str, Any]) -> dict[str, TestClient]:
    """One account per role of the matrix, none on study B's log, plus the investigator on A's log only and one on B's
    log (the control). Study B's log names a PI (lead), so its delegation rule is on."""
    sub_investigator(b, "subi_b", ("screen",), rs="GZQO")  # names lead as GZQO's PI too
    sub_investigator(b, "subi_a", ("screen",), rs="RA-BIO")
    out = {}
    for name, role in [*((f"r_{r}", r) for r in ROLES), ("subi_a", "investigator"), ("subi_b", "investigator")]:
        b["users"].create(name, role, PW, f"{name}@hospa.test")
        out[name] = login(b["app"], name, PW)[0]
    return out


def _refused(c: TestClient, rs: str, pid: str) -> bool:
    return bool(c.get(f"/studies/{rs}/patients/{pid}", follow_redirects=False).status_code == 403)


def test_off_the_log_the_answer_is_the_answer_for_a_number_that_does_not_exist(box: dict[str, Any]) -> None:  # noqa: F811
    """Byte for byte, for every role and every input: an account study B's patient page refuses gets for B's numbers
    and pseudonyms what it got before they existed (status, headers, body, audit rows). The accounts B's page admits
    find them (the control: the data is there)."""
    accounts = _accounts(box)
    nos = _numbers()
    queries = _queries(nos)
    # first: none of study B's patients exists yet, and none of A's
    absent = {(name, q): _answer(box, c, q) for name, c in accounts.items() for q in queries}
    assert all(a["audit"] and a["audit"][-1]["event"] == "console.command" for a in absent.values())
    _seed(box)
    refused = {name for name, c in accounts.items() if _refused(c, "GZQO", WEEK)}
    # the matrix as it stands: the patient page refuses every role but the coordinator, and the investigator off B's log
    assert refused == {f"r_{r}" for r in ROLES if r != "coordinator"} | {"subi_a"}, refused
    leaks = []
    for name, c in accounts.items():
        for q in queries:
            if name not in refused:
                continue
            if name == "subi_a" and q in (nos[BOTH], *(OWN[:n] for n in (8, 12, 16, 32))):
                continue  # study A's own patient: found, by the next test
            if name == "subi_a" and q in (BOTH[:8], BOTH[:12], BOTH[:16], BOTH):
                continue  # in A too: found in A only, by the next test
            if _answer(box, c, q) != absent[(name, q)]:
                leaks.append((name, q))
    assert leaks == [], f"answers that differ from a number that does not exist: {leaks}"


def test_off_the_log_nothing_of_study_b_on_the_investigators_own_study_unchanged(box: dict[str, Any]) -> None:  # noqa: F811
    """The investigator on A's log only: study A's own patients are found as before; a pseudonym in both studies opens
    A's page, never B's; no answer names B's patients (pseudonym or page) for any input."""
    accounts = _accounts(box)
    _seed(box)
    c = accounts["subi_a"]
    nos = _numbers()
    for q in (OWN[:8], OWN[:12], OWN):
        r = c.get("/cmd", params={"q": q}, follow_redirects=False)
        assert (r.status_code, r.headers.get("location")) == (303, f"/studies/RA-BIO/patients/{OWN}"), q
    for q in (BOTH[:8], BOTH[:12], BOTH, nos[BOTH]):
        r = c.get("/cmd", params={"q": q}, follow_redirects=False)
        assert (r.status_code, r.headers.get("location")) == (303, f"/studies/RA-BIO/patients/{BOTH}"), q
    for q in _queries(nos):
        r = c.get("/cmd", params={"q": q}, follow_redirects=False)
        assert "/studies/GZQO/patients/" not in r.headers.get("location", "") + r.text, q
        for pid in (WEEK, NUMBERED, DASHLESS, REGISTERED):
            if q == pid:
                continue  # the page repeats what was typed
            assert pid not in r.headers.get("location", "") + r.text, (q, pid)


@pytest.mark.parametrize("name", ["subi_b", "r_coordinator"])
def test_on_the_log_every_source_is_still_found(box: dict[str, Any], name: str) -> None:  # noqa: F811
    """The accounts B's patient page admits (the investigator on B's log, the coordinator) find B's patients from every
    source and every input kind, as before D-1241 (the same answers master gives; the byte comparison against master
    is recorded in the pull request)."""
    accounts = _accounts(box)
    _seed(box)
    c = accounts[name]
    nos = _numbers()
    expect = {
        nos[NUMBERED]: NUMBERED, nos[NUMBERED].lower(): NUMBERED, nos[DASHLESS]: DASHLESS,
        nos[DASHLESS].lower(): DASHLESS,
    }  # fmt: skip
    for pid in (WEEK, NUMBERED, DASHLESS, REGISTERED):
        expect.update({pid[:8]: pid, pid[:12]: pid, pid[:16]: pid, pid: pid})
    for q, pid in expect.items():
        r = c.get("/cmd", params={"q": q}, follow_redirects=False)
        assert (r.status_code, r.headers.get("location")) == (303, f"/studies/GZQO/patients/{pid}"), q
    # a pseudonym in both studies: one patient, the trial's page first (D-133), as before
    r = c.get("/cmd", params={"q": BOTH[:12]}, follow_redirects=False)
    assert (r.status_code, r.headers.get("location")) == (303, f"/studies/GZQO/patients/{BOTH}")


def test_a_break_glass_grant_changes_nothing_in_the_search(box: dict[str, Any]) -> None:  # noqa: F811
    """D-1241 (lane J lead's ruling on #1138): the search asks no grant. An off-log investigator holding an open grant
    for a patient of study B gets for that patient what it got before the patient existed, and no grant use is
    recorded; the grant opens the patient from the patient page, which records the use (D-430)."""
    accounts = _accounts(box)
    c = accounts["subi_a"]
    nos = _numbers()
    queries = (WEEK[:8], WEEK[:12], WEEK, NUMBERED[:12], nos[NUMBERED], REGISTERED[:12])
    absent = {q: _answer(box, c, q) for q in queries}
    _seed(box)
    assert _open(c, kind="patient", ruleset="GZQO", pid=WEEK).status_code == 303
    uses = sum(x.get("event") == "console.breakglass_use" for x in _audit(box))
    for q, before in absent.items():
        assert _answer(box, c, q) == before, q
    assert sum(x.get("event") == "console.breakglass_use" for x in _audit(box)) == uses  # the search used nothing
    assert c.get(f"/studies/GZQO/patients/{WEEK}", follow_redirects=False).status_code == 200  # the control: the page
    assert sum(x.get("event") == "console.breakglass_use" for x in _audit(box)) == uses + 1


def test_no_role_without_phi_view_finds_a_patient_not_even_with_a_grant(box: dict[str, Any]) -> None:  # noqa: F811
    """The ``phi.view`` guard: the administrator (with an open grant for a patient of study B) and every other role
    without ``phi.view`` find no patient by any input, in either study: the answer of a number that does not exist."""
    accounts = _accounts(box)
    nos = _numbers()
    queries = _queries(nos)
    names = [f"r_{r}" for r in ROLES if r not in ("coordinator", "investigator")]
    absent = {(n, q): _answer(box, accounts[n], q) for n in names for q in queries}
    _seed(box)
    assert _open(accounts["r_admin"], kind="patient", ruleset="GZQO", pid=WEEK).status_code == 303
    assert accounts["r_admin"].get(f"/studies/GZQO/patients/{WEEK}").status_code == 200  # the grant holds
    for n in names:
        for q in queries:
            assert _answer(box, accounts[n], q) == absent[(n, q)], (n, q)


SHORT = "a5" * 16  # study B's number under a short prefix: "B-0004", 6 characters


def test_a_screening_number_shorter_than_eight_characters(box: dict[str, Any]) -> None:  # noqa: F811
    """A number under the 8 characters of a pseudonym query (``B-0004``) is answered off the log as one that does not
    exist, and found on the log as before."""
    accounts = _accounts(box)
    off, on = accounts["subi_a"], accounts["subi_b"]
    queries = ("B-0004", "b-0004")
    absent = {q: _answer(box, off, q) for q in queries}
    _seed(box)
    store = box["app"].state.helpers.store
    assert store.assign_screening_no("GZQO", SHORT, StudySettings(screening_prefix="B-"), AT) == "B-0004"
    for q in queries:
        assert _answer(box, off, q) == absent[q], q
        r = on.get("/cmd", params={"q": q}, follow_redirects=False)
        assert (r.status_code, r.headers.get("location")) == (303, f"/studies/GZQO/patients/{SHORT}"), q


def test_the_search_asks_the_patient_pages_own_question(box: dict[str, Any], monkeypatch: Any) -> None:  # noqa: F811
    """The search asks ``Helpers.reads`` (the patient page's question), once per study, and follows its answer: a copied
    rule would not follow it when it changes."""
    accounts = _accounts(box)
    _seed(box)
    h = box["app"].state.helpers
    real = h.reads
    asked: list[tuple[str, str | None]] = []

    def spy(user: Any, rid: str | None) -> bool:
        asked.append((user.username, rid))
        return bool(real(user, rid))

    monkeypatch.setattr(h, "reads", spy)
    r = accounts["subi_a"].get("/cmd", params={"q": WEEK[:12]}, follow_redirects=False)
    assert r.status_code == 200 and ("subi_a", "GZQO") in asked and ("subi_a", "RA-BIO") in asked
    # the answer flips with it: refused, the coordinator finds nothing; admitted, the off-log investigator finds B's
    monkeypatch.setattr(h, "reads", lambda user, rid: user.username != "r_coordinator" and bool(real(user, rid)))
    r = accounts["r_coordinator"].get("/cmd", params={"q": WEEK[:12]}, follow_redirects=False)
    assert r.status_code == 200 and WEEK not in r.text
    monkeypatch.setattr(h, "reads", lambda user, rid: True)
    r = accounts["subi_a"].get("/cmd", params={"q": WEEK[:12]}, follow_redirects=False)
    assert (r.status_code, r.headers.get("location")) == (303, f"/studies/GZQO/patients/{WEEK}")
