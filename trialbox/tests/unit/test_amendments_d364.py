"""D-364 (T-621, LIFE-009, LIFE-012): amendment handling below the console. A criteria version carries its effective
date and the IRB approval it rests on (a record, not a gate: D-311); a version whose effective date has not come is
not used, its predecessor screens until then; the APPROVE line carries the record; a visit done is judged by the
schedule in force on the visit day."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from criteria_compiler.repo import RulesetRepo
from criteria_compiler.service import CompileFailed, amendment_record
from datacore.builtin import builtin_questionnaires
from datacore.lifecycle import Lifecycle, LifeError, Visit, in_force_on
from datacore.store import DataCore
from orchestrator.clients import StepFailed
from orchestrator.scenarios.approve import amendment_options
from tb_common.ruleset import RulesetNotApproved, in_force, load_approved
from tb_common.subject import parse_subject
from tb_contracts import ApproveRequest, RulesetManifest

from tests.unit.test_compiler_service import _compile, _decisions, env  # noqa: F401 - env is a fixture

RID = "AMND"
TODAY = date(2026, 11, 11)


def _manifest(version: str, **extra: Any) -> bytes:
    m = {
        "id": RID,
        "kind": "trial",
        "title": "Synthetic amendment study",
        "version": version,
        "status": "approved",
        "index_date_rule": "run_date",
        "scopes": {},
        "routing": {},
        "thresholds": {},
        "criteria": [],
        **extra,
    }
    return yaml.safe_dump(m, sort_keys=False).encode()


def _approve(repo: RulesetRepo, version: str, **extra: Any) -> None:
    branch = f"draft/{version}"
    repo.write_dir(branch, "main", f"{RID}/", {"manifest.yaml": _manifest(version, **extra)}, f"v{version}")
    repo.tag(f"{RID}/v{version}", branch, f"{RID} v{version} approved")
    repo.promote(RID, f"{RID}/v{version}", f"release v{version}")


@pytest.fixture
def repo(tmp_path: Path) -> RulesetRepo:
    r = RulesetRepo(tmp_path / "rulesets")
    _approve(r, "3.0.0", irb_reference="IRB-SYN-0003")
    _approve(r, "4.0.0", effective_from="2026-12-01", irb_reference="IRB-SYN-0004", irb_approved_on="2026-11-05")
    return r


def test_a_version_with_a_future_effective_date_is_not_used(repo: RulesetRepo) -> None:
    """LIFE-009 acceptance: v4 approved today with effective date 2026-12-01; v3 screens until then."""
    d = repo.path
    assert load_approved(d, RID).version == "4.0.0"  # the newest approved, whatever its date (approval checks)
    before = load_approved(d, RID, on=date(2026, 11, 30))
    assert before.version == "3.0.0" and before.manifest.irb_reference == "IRB-SYN-0003"
    on = load_approved(d, RID, on=date(2026, 12, 1))
    assert on.version == "4.0.0" and str(on.manifest.irb_approved_on) == "2026-11-05"
    with pytest.raises(RulesetNotApproved, match="takes effect on 2026-12-01"):
        load_approved(d, RID, "4.0.0", on=date(2026, 11, 30))
    assert load_approved(d, RID, "3.0.0", on=date(2026, 11, 30)).version == "3.0.0"


def test_no_earlier_version_in_force_is_a_refusal(tmp_path: Path) -> None:
    r = RulesetRepo(tmp_path / "rs")
    _approve(r, "1.0.0", effective_from="2026-12-01")
    assert load_approved(r.path, RID).version == "1.0.0"
    with pytest.raises(RulesetNotApproved, match="no earlier approved version is in force"):
        load_approved(r.path, RID, on=date(2026, 11, 20))
    plain = tmp_path / "plain" / RID  # a vendor copy without the repository: nothing earlier to fall back to
    plain.mkdir(parents=True)
    (plain / "manifest.yaml").write_bytes(_manifest("2.0.0", effective_from="2026-12-01"))
    with pytest.raises(RulesetNotApproved, match="no earlier version is on this box"):
        load_approved(plain.parent, RID, on=date(2026, 11, 20))
    assert load_approved(plain.parent, RID, on=date(2026, 12, 2)).version == "2.0.0"


def test_in_force_without_a_date_is_from_approval() -> None:
    m = RulesetManifest.model_validate(yaml.safe_load(_manifest("1.0.0")))
    assert in_force(m, date(2000, 1, 1)) and m.effective_from is None


def test_the_approval_records_effective_date_and_irb_reference_never_carried_over() -> None:
    req = ApproveRequest(ruleset=RID, version="4.0.0", by="pi", decisions=[])
    assert amendment_record(req, TODAY) == {"effective_from": None, "irb_reference": None, "irb_approved_on": None}
    full = req.model_copy(update={"effective_from": date(2026, 12, 1), "irb_reference": " IRB-SYN-0004 ",
                                  "irb_approved_on": date(2026, 11, 5)})  # fmt: skip
    assert amendment_record(full, TODAY) == {
        "effective_from": "2026-12-01",
        "irb_reference": "IRB-SYN-0004",
        "irb_approved_on": "2026-11-05",
    }
    with pytest.raises(CompileFailed, match="before the approval"):
        amendment_record(req.model_copy(update={"effective_from": date(2026, 11, 1)}), TODAY)
    with pytest.raises(CompileFailed, match="after today"):
        amendment_record(req.model_copy(update={"irb_approved_on": date(2026, 11, 12)}), TODAY)


def test_the_approve_line_carries_the_record() -> None:
    s = parse_subject("APPROVE GZQO version=4.0.0 effective=2026-12-01 irb=IRB-SYN-0004 irbdate=2026-11-05")
    opts = amendment_options(s.options)
    assert opts == {
        "effective_from": date(2026, 12, 1),
        "irb_approved_on": date(2026, 11, 5),
        "irb_reference": "IRB-SYN-0004",
    }
    assert amendment_options({"version": "4.0.0"}) == {}
    with pytest.raises(StepFailed, match="effective= must be a date"):
        amendment_options({"effective": "2026-13-01"})


# ---------------------------------------------------------------------------------------------- schedule versions
AT = "2026-11-08T09:00:00+09:00"
RS = "GZQO"


@pytest.fixture
def life() -> Any:
    dc = DataCore()
    for q in builtin_questionnaires(RS):
        dc.put_form(RS, q, "builtin", AT)
    yield Lifecycle(dc)
    dc.close()


def _put(life: Lifecycle, rec: str, values: dict[str, str], event: str = "") -> None:
    for f, v in values.items():
        life.dc.write(RS, rec, event, f, v, "crc", AT, "trialbox")


def test_two_schedule_versions_judged_by_visit_date(life: Lifecycle) -> None:
    """LIFE-012 acceptance: an amendment narrows v1's window from 2026-12-01. A visit done before that day stays in
    the window of the schedule it was done under; a visit after it is judged by the new one."""
    old = [Visit("v1", 7, 3, 3), Visit("v2", 28, 3, 3)]
    new = [Visit("v1", 7, 1, 1), Visit("v2", 28, 1, 1)]
    assert life.set_schedule(RS, old, "trialbox", AT) == 1
    assert life.set_schedule(RS, new, "trialbox", AT, "2026-12-01") == 2
    vers = life.schedule_versions(RS)
    assert [(v["version"], v["effective_from"]) for v in vers] == [(1, ""), (2, "2026-12-01")]
    assert in_force_on(vers, date(2026, 11, 30))["version"] == 1 and life.schedule_on(RS, date(2026, 12, 1)) == new
    assert life.schedule(RS) == new  # the table holds the newest saved
    for rec, enrol in (("GZQO-0101", "2026-11-01"), ("GZQO-0102", "2026-11-20")):
        life.ensure(RS, rec, "", "crc", AT)
        _put(life, rec, {"ic_date": enrol, "en_date": enrol, "en_eligible": "1"})
        life.derive(RS, rec, by="crc", at=AT)
    # enrolled 11-01: v1 due 11-08, done 11-10 = 2 days late: inside v1's old window (3), outside the new one (1)
    _put(life, "GZQO-0101", {"vs_status": "1", "vs_date": "2026-11-10"}, "v1")
    # enrolled 11-20: v1 due 11-27, done 12-01 = 4 days late, on the effective day: judged by the new schedule
    _put(life, "GZQO-0102", {"vs_status": "1", "vs_date": "2026-12-01"}, "v1")
    early = life.visits(RS, "GZQO-0101", date(2026, 12, 10))[0]
    assert early["status"] == "done" and early["in_window"] is True and early["schedule_version"] == 1
    assert early["end"] == "2026-11-11"  # the old window, as it was on the visit day
    late = life.visits(RS, "GZQO-0102", date(2026, 12, 10))[0]
    assert late["status"] == "done" and late["schedule_version"] == 2 and late["end"] == "2026-11-28"
    assert late["in_window"] is False
    # a visit not yet done is judged by today's schedule: the old one before the effective day, the new one after
    assert life.visits(RS, "GZQO-0101", date(2026, 11, 30))[1]["end"] == "2026-12-02"
    assert life.visits(RS, "GZQO-0101", date(2026, 12, 10))[1]["end"] == "2026-11-30"
    with pytest.raises(LifeError):
        life.set_schedule(RS, new, "trialbox", AT, "next week")


def test_a_schedule_saved_before_versions_becomes_version_one(life: Lifecycle) -> None:
    old = [Visit("v1", 7, 2, 2)]
    with life.db.transaction() as tx:  # a schedule as the table held it before D-364
        tx.execute("INSERT INTO schedule (study, visit, seq, labels, anchor, day, win_before, win_after, origin, at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", (RS, "v1", 0, "{}", "enrolment", 7, 2, 2, "trialbox", AT))  # fmt: skip
    assert life.schedule_versions(RS) == [] and life.schedule_on(RS, date(2026, 11, 1)) == old
    life.set_schedule(RS, [Visit("v1", 7, 5, 5)], "trialbox", AT, "2027-01-01")
    vers = life.schedule_versions(RS)
    assert [(v["version"], v["effective_from"], v["origin"]) for v in vers] == [
        (1, "", "before"),
        (2, "2027-01-01", "trialbox"),
    ]
    assert vers[0]["visits"] == old


def test_the_compiler_writes_the_record_into_the_approved_manifest(env: dict[str, Any]) -> None:  # noqa: F811
    """End to end through the compiler: the approved manifest on disk holds the record; the run on the day before the
    effective date finds no version in force (the first version), the run on that day screens."""
    import datetime as dt

    res = _compile(env)
    today = dt.datetime.now(dt.UTC).date()
    eff = today + dt.timedelta(days=7)
    req = ApproveRequest(ruleset="GZQO", version="1.0.0", by="crc1@hospa.test",
                         decisions=_decisions(env["store"], res.review_xlsx_key), effective_from=eff,
                         irb_reference="IRB-SYN-0001", irb_approved_on=today - dt.timedelta(days=1))  # fmt: skip
    out = env["comp"].approve(req)
    assert out.status == "approved" and out.manifest is not None and out.manifest.effective_from == eff
    disk = yaml.safe_load((env["tmp"] / "repo" / "GZQO" / "manifest.yaml").read_text())
    assert str(disk["effective_from"]) == eff.isoformat() and disk["irb_reference"] == "IRB-SYN-0001"
    with pytest.raises(RulesetNotApproved, match="no earlier approved version"):
        load_approved(env["tmp"] / "repo", "GZQO", on=eff - dt.timedelta(days=1))
    assert load_approved(env["tmp"] / "repo", "GZQO", on=eff).version == "1.0.0"
