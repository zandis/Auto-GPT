"""D-364 (T-621, LIFE-009, LIFE-010): amendment handling on the console. The approval takes the effective date and
the IRB approval number and date of the protocol version (a record, not a gate: D-311) onto the APPROVE line; every
mark keeps the criteria version of the list it was made on; after an amendment the re-screen list brings back a
patient set aside under the earlier version when a relaxed criterion now passes, with the reason."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from console import studies as st
from console.approval import amendment_line
from console.i18n import CATALOGUES, translate
from console.sitestore import Mark, SiteStore
from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_criterion_labels import _approval_job, _gzqo, _gzqo_rows

PW = "amendment-rescreen-password-01"
A, B, C, D = "a" * 32, "b" * 32, "c" * 32, "d" * 32
RELAXED = "GZQO-INC-05"  # the criterion the amendment relaxes (two flares in 12 months -> one)


def _row(pid: str, tier: str, verdict: str) -> dict[str, Any]:
    return {"pid": pid, "tier": tier, "next_appointment": None, "practitioner_id": "DR-LIN", "department": "RHEU",
            "criteria": [{"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": []}},
                         {"id": RELAXED, "verdict": verdict, "evidence": {"resource_refs": []}}],
            "actions": [], "n_unknown": 0}  # fmt: skip


def _list(version: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ruleset": "GZQO", "version": version, "snapshot": "2026-10-04", "scope": {}, "rows": rows,
            "summary": {}}  # fmt: skip


def _screen(b: dict[str, Any], n: int, version: str, rows: list[dict[str, Any]], hours: int) -> Job:
    """A done SCREEN job of ``version`` whose candidate list is ``rows``, ``hours`` after the first."""
    job = _done_screen(b["backend"], _ulid(n))
    data = json.dumps(_list(version, rows)).encode()
    name = f"candidate_list_GZQO_v{version}.json"
    key = f"outputs/{job.job_id}/{name}"
    b["backend"].objects[key] = data
    outs = [o for o in job.outputs or [] if not o.filename.startswith("candidate_list_")]
    outs.append(JobOutput(filename=name, sha256=sha256_bytes(data), minio_key=key, recipients=[], tag="phi"))
    when = datetime(2026, 10, 25, 9, 0, tzinfo=UTC) + timedelta(hours=hours)
    new = job.model_copy(update={"outputs": outs, "ruleset_version": version, "updated_at": when})
    b["backend"].jobs[job.job_id] = new
    return new


def _csrf(page: str) -> str:
    import re

    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def test_the_planted_set_aside_patient_returns_after_the_amendment(box: dict[str, Any]) -> None:  # noqa: F811
    """LIFE-010 acceptance: under v3 the investigator set patient B aside ("Not suitable now"); v4 relaxes INC-05,
    which B did not meet; B is back on the re-screen list with the reason "criteria changed in v4.0.0"."""
    _gzqo(box)
    _screen(box, 9701, "3.0.0", [_row(A, "high", "pass"), _row(B, "review", "fail")], 0)
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")  # D-380 (ROLE-008): the steward names the PI
    pi, _ = login(box["app"], "pi", PW)
    week = pi.get("/studies/GZQO/week").text
    assert 'data-testid="to-rescreen"' in week
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(week), "mark": "not_suitable",
                                                          "reason": "comorbidity"}, follow_redirects=True)  # fmt: skip
    assert r.status_code == 200
    pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(week), "mark": "need_info"})
    store = SiteStore()
    assert store.latest_marks("GZQO")[B].version == "3.0.0"  # the version is on every mark
    events = [json.loads(x) for f in sorted((box["dir"] / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()
              if x and '"console.pi_mark"' in x]  # fmt: skip
    assert events and all(e["detail"]["version"] == "3.0.0" for e in events)
    # before any list of a new version: nothing to re-screen
    assert 'data-testid="rescreen-none"' in pi.get("/studies/GZQO/rescreen").text
    # v4 screens: B now meets the relaxed criterion; A no longer meets the criteria
    _screen(box, 9702, "4.0.0", [_row(A, "excluded", "fail"), _row(B, "high", "pass")], 24)
    page = pi.get("/studies/GZQO/rescreen").text
    assert 'data-testid="rescreen-versions"' in page and "Version 4.0.0 against 3.0.0" in page
    returns = page.split('data-testid="rescreen-returns"')[1].split("</table>")[0]
    assert 'data-testid="rescreen-row-bbbbbbbb"' in returns and "Not suitable now" in returns
    assert "criteria changed in v4.0.0" in returns and "(v3.0.0)" in returns
    gone = page.split('data-testid="rescreen-no_longer"')[1].split("</table>")[0]
    assert 'data-testid="rescreen-row-aaaaaaaa"' in gone and "does not meet the criteria of v4.0.0" in gone
    # a new mark on the v4 list takes B off; the history keeps both marks with their versions
    week = pi.get("/studies/GZQO/week").text
    pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(week), "mark": "approach"})
    assert [(m.mark, m.version) for m in store.mark_history("GZQO", B)] == [
        ("not_suitable", "3.0.0"),
        ("approach", "4.0.0"),
    ]
    assert 'data-testid="rescreen-row-bbbbbbbb"' not in pi.get("/studies/GZQO/rescreen").text
    store.close()
    # the page in Japanese
    ja, jcsrf = login(box["app"], "pi", PW)
    ja.post("/lang", data={"csrf": jcsrf, "lang": "ja", "back": "/"})
    assert "改訂後の再確認" in ja.get("/studies/GZQO/rescreen").text
    # roles: a viewer never sees it
    box["users"].create("v2", "viewer", PW)
    viewer, _ = login(box["app"], "v2", PW)
    assert viewer.get("/studies/GZQO/rescreen").status_code == 403


def _mk(pid: str, mark: str, version: str | None) -> Mark:
    return Mark(pid, mark, None, None, "pi", "2026-11-01T00:00:00+00:00", "J1", version)


def test_the_three_groups_of_the_re_screen_list() -> None:
    crit = {RELAXED: st.CriterionMeta(RELAXED, "inclusion", "note", "Gout flares in 12 months")}
    old = _list("3.0.0", [_row(A, "high", "pass"), _row(B, "review", "fail"), _row(C, "high", "pass"),
                          _row(D, "excluded", "fail")])  # fmt: skip
    new = _list("4.0.0", [_row(A, "excluded", "fail"), _row(B, "high", "pass"), _row(C, "high", "pass"),
                          _row(D, "high", "pass")])  # fmt: skip
    marks = {A: _mk(A, "approach", "3.0.0"), B: _mk(B, "not_now", None), C: _mk(C, "not_suitable", "3.0.0")}
    reg = {D: "screen_fail", "e" * 32: "consented", "f" * 32: "enrolled"}
    rows = st.rescreen_list(new, marks, reg, crit, old)
    got = {(r["group"], r["short"], r["was"]) for r in rows}
    assert got == {
        ("returns", "bbbbbbbb", "not_now"),  # a mark from before D-364 (no version) counts as earlier
        ("returns", "dddddddd", "screen_fail"),  # closed under v3, the relaxed criterion passes now
        ("no_longer", "aaaaaaaa", "approach"),
        ("in_screening", "eeeeeeee", "consented"),
    }
    # C was set aside under v3 with every answer the same in v4: nothing changed for C, so C stays set aside
    assert next(r for r in rows if r["short"] == "bbbbbbbb")["criteria"] == ["Gout flares in 12 months"]
    assert [r["group"] for r in rows] == sorted((r["group"] for r in rows), key=st.RESCREEN_GROUPS.index)
    # no list of an earlier version: no amendment has screened, the list is empty
    assert st.rescreen_list(new, marks, reg, crit, None) == []
    assert st.rescreen_list(new, marks, reg, crit, _list("4.0.0", [])) == []
    assert st.semver("10.0.0") > st.semver("9.1.0") > st.semver(None)


def test_the_amendment_record_on_the_approve_line() -> None:
    today = date(2026, 11, 11)
    assert amendment_line("", "", "", today) == ""
    assert amendment_line("2026-12-01", "IRB-SYN-0004", "2026-11-05", today) == (
        "effective=2026-12-01 irbdate=2026-11-05 irb=IRB-SYN-0004"
    )
    for args, key in ((("2026-11-10", "", ""), "amend.past_effective"), (("", "", "2026-11-12"), "amend.future_irb"),
                      (("12/01", "", ""), "amend.bad_date.effective"), (("", "IRB 4/2026", ""), "amend.bad_irb")):  # fmt: skip
        with pytest.raises(ValueError, match=key):
            amendment_line(*args, today)
    for lang in ("ja", "zh-TW"):
        assert set(CATALOGUES[lang]) >= {k for k in CATALOGUES["en"] if k.startswith(("amend.", "rescreen."))}
    assert translate("en", "rescreen.reason.returns", version="4") == "criteria changed in v4"


def test_approve_all_sends_the_effective_date_and_irb_reference(box: dict[str, Any]) -> None:  # noqa: F811
    _gzqo(box)
    job = _approval_job(box, _gzqo_rows("GZQO-INC-01", "GZQO-EXC-01"))
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")  # D-380 (ROLE-008): the steward names the PI
    p, csrf = login(box["app"], "pi", PW)
    s20 = p.get(f"/pilot/jobs/{job.job_id}/approval").text
    for amber in ("GZQO-INC-01", "GZQO-EXC-01"):
        s20 = p.get(f"/pilot/jobs/{job.job_id}/approval?open={amber}").text
    assert 'data-testid="amend-effective"' in s20 and 'data-testid="amend-irb"' in s20
    record = {"effective_from": "2099-12-01", "irb_reference": "IRB-SYN-0004", "irb_approved_on": "2026-11-05"}
    r = p.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf, **record}, follow_redirects=False)
    assert r.status_code == 200 and "It screens from 2099-12-01" in r.text and 'value="IRB-SYN-0004"' in r.text
    bad = p.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf, "confirm": "yes", "irb_reference": "a b"})
    assert bad.status_code == 400
    r = p.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf, "confirm": "yes", **record},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    appr = box["backend"].created[-1]
    assert appr.type == "APPROVE" and appr.options == {
        "version": job.ruleset_version,
        "effective": "2099-12-01",
        "irb": "IRB-SYN-0004",
        "irbdate": "2026-11-05",
    }
