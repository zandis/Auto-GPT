"""The failure drill's logic on stand-ins (card H-31, D-1109): the three checks, the plan of targets and the report.
No box, no Docker: the live run is ``make failure-drill`` (tools/failure_drill_box.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import failure_drill as fd

pytestmark = [pytest.mark.nodb]


def job(jtype: str, state: str, rs: str | None = None, mail: bool = False, by: str = "scheduler", err: str = "",
        jid: str = "J1") -> dict[str, object]:  # fmt: skip
    return {"job_id": jid, "type": jtype, "ruleset": rs, "state": state, "message_id": "<m@x>" if mail else None,
            "requested_by": "crc1@hospa.test" if mail else by, "error": {"message": err} if err else None}  # fmt: skip


CONTROL = [
    job("FEAS", "done", "GZQO", mail=True),
    job("SCREEN", "done", "GZQO", mail=True),
    job("INGEST", "done"),
    job("RETENTION", "done"),
]


def test_the_plan_names_each_service_then_the_database_then_the_disk() -> None:
    names = [t.name for t in fd.TARGETS]
    assert names[-2:] == ["db", "disk"]
    assert {"adapter", "lake", "criteria-compiler", "orchestrator", "gateway", "mail-gateway", "console"} <= set(names)
    assert all(t.stage in fd.STAGES for t in fd.TARGETS)
    assert len(set(names)) == len(names)
    with pytest.raises(KeyError):
        fd.target("nope")


def test_compose_services_are_all_targets() -> None:
    """Every long-running service of the base compose file is a target (or said here why not)."""
    import yaml

    base = yaml.safe_load((fd.ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    not_in_test_stack = {"llm-service", "model-guard", "build"}  # the real model's pair and the build-only entry
    want = set(base["services"]) - not_in_test_stack
    assert want <= {t.service for t in fd.TARGETS}, want - {t.service for t in fd.TARGETS}


def test_a_night_like_the_control_passes() -> None:
    drilled = [{**j, "job_id": f"D{i}"} for i, j in enumerate(CONTROL)]
    c = fd.check_jobs(CONTROL, drilled)
    assert c.ok and c.counts["lost"] == 0 and c.counts["done_once"] == 4


def test_a_unit_with_no_job_is_lost() -> None:
    c = fd.check_jobs(CONTROL, CONTROL[:3])
    assert not c.ok and c.counts["missing"] == 1 and "RETENTION:-:timer: no job" in c.lines


def test_a_job_left_running_is_stuck_and_lost() -> None:
    c = fd.check_jobs(CONTROL, [*CONTROL[:3], job("RETENTION", "running")])
    assert not c.ok and c.counts["stuck"] == 1 and c.counts["lost"] == 1


def test_a_failure_with_a_reason_is_visible_not_lost() -> None:
    c = fd.check_jobs(CONTROL, [*CONTROL[:3], job("RETENTION", "failed", err="the lake was down")])
    assert c.ok and c.counts["visibly_failed"] == 1 and c.counts["lost"] == 0


def test_a_failure_with_no_reason_is_lost() -> None:
    c = fd.check_jobs(CONTROL, [*CONTROL[:3], job("RETENTION", "failed")])
    assert not c.ok and c.counts["failed_no_reason"] == 1


def test_a_unit_done_twice_fails() -> None:
    c = fd.check_jobs(CONTROL, [*CONTROL, job("INGEST", "done", jid="J2")])
    assert not c.ok and c.counts["done_twice"] == 1


def test_a_requeued_job_done_once_is_once() -> None:
    """A requeue keeps the job's id; a failed first try and a done retry are one unit done once."""
    c = fd.check_jobs(CONTROL, [*CONTROL[:3], job("RETENTION", "failed", err="x", jid="a"), job("RETENTION", "done")])
    assert c.ok and c.counts["done_once"] == 4


def test_awaiting_approval_is_settled() -> None:
    ctl = [job("FEAS", "awaiting_approval", "GZQO", mail=True)]
    assert fd.check_jobs(ctl, ctl).ok


def m(to: str, subject: str) -> dict[str, object]:
    return {"to": [to], "subject": subject}


def test_mail_once_passes_and_ids_do_not_matter() -> None:
    ctl = [m("crc1@hospa.test", "[TrialBox] 01KA0000000000000000000000 FEAS done")]
    got = [m("crc1@hospa.test", "[TrialBox] 01KB1111111111111111111111 FEAS done")]
    c = fd.check_mail(ctl, got, [{"key": "k", "state": "sent"}])
    assert c.ok and c.counts == {"messages": 1, "double": 0, "missing": 0, "held": 0, "sending": 0, "queued": 0}


def test_the_same_mail_twice_to_one_recipient_is_double() -> None:
    got = [m("pi@hospa.test", "N1 list"), m("pi@hospa.test", "N1 list"), m("crc1@hospa.test", "N1 list")]
    c = fd.check_mail(got[:1], got, [])
    assert not c.ok and c.counts["double"] == 1 and c.lines[0].startswith("pi@hospa.test")


def test_a_key_left_sending_fails_and_held_keys_are_listed() -> None:
    c = fd.check_mail([], [], [{"key": "a", "state": "sending"}, {"key": "b", "state": "uncertain"}])
    assert not c.ok and c.counts["sending"] == 1 and c.counts["held"] == 1
    assert "outbox key b: uncertain" in c.lines


def test_a_mail_the_control_sent_and_the_drill_did_not_is_missing() -> None:
    c = fd.check_mail([m("crc1@hospa.test", "FEAS done")], [], [])
    assert c.ok and c.counts["missing"] == 1  # missing is reported; it is not a double


def test_audit_intact_needs_the_verifier_a_drained_journal_and_growth() -> None:
    assert fd.check_audit(0, "", 10, 20, 0).ok
    assert not fd.check_audit(1, "chain broken at line 5", 10, 20, 0).ok
    assert not fd.check_audit(0, "", 10, 20, 3).ok
    bad = fd.check_audit(0, "", 10, 10, 0)
    assert not bad.ok and "no event was added" in bad.lines[0]
    assert fd.check_audit(0, "", 10, 10, 0, work_after=False).ok  # nothing ended after the kill: nothing to audit


def test_records_round_trip_and_render(tmp_path: Path) -> None:
    r = fd.Record("adapter", "service", "adapter", "ingest", "w", killed="kill -9", recovered_by="Docker's restart "
                  "policy (restarts: 1)", recover_s=12.4, finished=True, jobs=fd.check_jobs(CONTROL, CONTROL),
                  mail=fd.check_mail([], [], []), audit=fd.check_audit(0, "", 1, 2, 0))  # fmt: skip
    (tmp_path / "adapter.json").write_text(json.dumps(r.to_json()), encoding="utf-8")
    (tmp_path / "db.json").write_text(json.dumps(fd.Record("db", "db", "db", "mailed", "w").to_json()), "utf-8")
    recs = fd.load(tmp_path)
    assert [x.target for x in recs] == ["adapter", "db"]
    table = fd.render(recs)
    assert "| adapter | kill -9 | ingest, w | Docker's restart policy (restarts: 1) | 12 | yes | pass: 0 lost" in table
    assert "| db | not killed |" in table and "not run" in table
    assert not fd.needs_person(recs[0])
    assert fd.needs_person(fd.Record("x", "", "", "", "", recovered_by="a person: docker compose up -d"))


def test_cli_plan_and_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fd.main(["plan"]) == 0
    assert "orchestrator" in capsys.readouterr().out
    assert fd.main(["report", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("| Target |")


def test_the_chain_behind_a_visibly_failed_ingest_is_not_lost() -> None:
    """The chain never follows an ingest that failed (orchestrator/night.py); its steps wait for the retry."""
    ctl = [job("INGEST", "done"), {**job("RETENTION", "done"), "options": {"step": "retention"}}]
    c = fd.check_jobs(ctl, [job("INGEST", "failed", err="the ingest's process ended without an answer")])
    assert c.ok and c.counts["behind_failed_ingest"] == 1 and c.counts["visibly_failed"] == 1
    c = fd.check_jobs(ctl, [job("INGEST", "failed")])  # no reason: the ingest is lost and so is its chain
    assert not c.ok and c.counts["failed_no_reason"] == 1 and c.counts["missing"] == 1
