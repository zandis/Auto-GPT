"""T-609 (review OPS-042): the model misbehaviour procedure of RUNBOOK §19.

One switch (the audited flag ``notes.reading``) turns note reading off: the next note-stage call asks no model, a run
whose note stage ends under the hold uses no note answer, and nothing excludes on a note. ``trialbox model report``
lists the runs and the patients one build touched; ``release`` needs a passing pair canary that ran after the hold.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from orchestrator.db import JobDB
from orchestrator.scenarios import evaluate
from orchestrator.scenarios.evaluate import NOTES_HELD, NoteJudge, effective_note_block, evaluate_patients
from tb_common import flags as fl
from tb_common.audit import AuditLog
from tb_common.reasons import Reason
from tb_contracts import Job

from tests.judge_kit import ScriptedModel, note_criterion, ruleset, says
from tools.trialbox import model_report as mr

IDX = date(2026, 10, 5)
FLARE = "Acute gout flare of the right toe"
INC = note_criterion("T-INC-02", "inclusion", "Gout flare in the past year", "Did the patient have a gout flare?")
EXC = note_criterion("T-EXC-02", "exclusion", "Gout flare in the past year", "Did the patient have a gout flare?")
TZ = ZoneInfo("Asia/Taipei")


@pytest.fixture(autouse=True)
def _policy(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    monkeypatch.delenv("TB_MODEL_SWAP", raising=False)
    fl.clear_cache()
    yield
    fl.clear_cache()


class _Chunks:
    """A lake whose search returns one note holding the flare sentence."""

    def chunks_search(self, pid: str, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
        return [{"date": "2026-09-20", "type": "progress", "text": f"{FLARE}. Seen in clinic.", "did": f"{pid}-d1"}]

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        rows = [{"did": "d1", "d": date(2026, 9, 20), "type": "progress", "text": f"{FLARE}. Seen in clinic."}]
        return SimpleNamespace(to_pylist=lambda: rows)


class _NoStructured:
    name = "sql"

    def evaluate(self, rs: Any, pids: list[str], index_date: date, ids: list[str]) -> dict[str, Any]:
        raise AssertionError("no structured criterion was asked for")


def _flags(tmp_path: Path) -> fl.Flags:
    return fl.Flags(audit=AuditLog(tmp_path / "audit"))


def _pair(answer: Any, second: Any = None) -> tuple[ScriptedModel, ScriptedModel]:
    return ScriptedModel("judge-a", answer), ScriptedModel("verifier-b", second or says("pass", FLARE))


# ------------------------------------------------------------------------------------------------ the switch
def test_the_flag_is_declared_on_by_default_and_never_seeded_from_the_environment() -> None:
    d = fl.DECLARED[evaluate.NOTES_FLAG]
    assert d.values == ("on", "off") and d.default == "on" and d.seed_env is None
    assert evaluate.notes_held() is False  # no row yet: note reading runs


def test_a_hold_during_the_note_stage_stops_the_calls_within_one_step(tmp_path: Path) -> None:
    """The acceptance test: the hold is set while the first note question is with the model. The verifier of that
    question and every later question ask no model; the run ends under the hold, so no note answer is used and every
    patient goes to review."""
    flags = _flags(tmp_path)
    flare = says("pass", FLARE)  # "yes, a flare": with the verifier's yes, the exclusion would exclude

    def answer_then_hold(variables: dict[str, Any]) -> dict[str, Any]:
        if flags.row(evaluate.NOTES_FLAG) != "off":
            flags.set(evaluate.NOTES_FLAG, "off", actor="cli:ops", reason="drill: wrong quotes")
        return flare(variables)

    llm, verifier = _pair(answer_then_hold)
    nj = NoteJudge(lake=_Chunks(), llm=llm, verifier=verifier)  # type: ignore[arg-type]
    pids = [f"P{n}" for n in range(6)]
    out = evaluate_patients(ruleset([EXC]), pids, IDX, _NoStructured(), nj, 0.75, only={EXC.id},
                            all_candidates=True, workers=1, note_block=True)  # fmt: skip
    assert llm.calls == 1 and verifier.calls == 0  # one step: the call in flight; none after
    assert nj.held >= len(pids)  # the first one's verifier question, then every later question (and its full read)
    for pid in pids:
        pv = out[pid]
        v = next(v for v in pv.verdicts if v.id == EXC.id)
        assert v.verdict == "unknown" and v.evidence is not None and v.evidence.reason == Reason.NOT_EVALUATED.value
        assert pv.tier == "review"  # never excluded, even the patient the model answered before the hold


def test_under_a_hold_a_run_asks_no_model_and_says_why(tmp_path: Path) -> None:
    _flags(tmp_path).set(evaluate.NOTES_FLAG, "off", actor="cli:ops", reason="drill")
    llm, verifier = _pair(says("fail", FLARE))
    nj = NoteJudge(lake=_Chunks(), llm=llm, verifier=verifier)  # type: ignore[arg-type]
    assert effective_note_block(nj) == (False, "never", NOTES_HELD)
    out = evaluate_patients(ruleset([INC]), ["P1", "P2"], IDX, _NoStructured(), nj, 0.75, only={INC.id},
                            all_candidates=True, workers=1)  # fmt: skip
    assert llm.calls == 0 and verifier.calls == 0 and nj.failures == 0  # a hold is not a model outage
    assert {pv.tier for pv in out.values()} == {"review"}
    from orchestrator.scenarios.screen import judging_info

    info = judging_info(nj)
    assert info["may_block"] is False and info["note_block_reason"] == NOTES_HELD


def test_released_note_reading_asks_the_models_again(tmp_path: Path) -> None:
    flags = _flags(tmp_path)
    flags.set(evaluate.NOTES_FLAG, "off", actor="cli:ops", reason="drill")
    flags.set(evaluate.NOTES_FLAG, "on", actor="cli:ops", reason="drill over")
    llm, verifier = _pair(says("pass", FLARE))
    nj = NoteJudge(lake=_Chunks(), llm=llm, verifier=verifier)  # type: ignore[arg-type]
    out = evaluate_patients(ruleset([EXC]), ["P1"], IDX, _NoStructured(), nj, 0.75, only={EXC.id},
                            all_candidates=True, workers=1, note_block=True)  # fmt: skip
    # D-1072 (ring 0): the pair's stated exclusion is review, no longer excluded
    assert llm.calls == 1 and verifier.calls == 1 and out["P1"].tier == "review"


# ------------------------------------------------------------------------------------------------ hold and release
def _canary(data_dir: Path, ok: bool = True, pair: bool = True, at: float | None = None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    rep = {"ok": ok, "pair": {"correct": 54} if pair else {}, "problems": [] if ok else ["judge 30/54"],
           "at_epoch": time.time() if at is None else at}  # fmt: skip
    (data_dir / "selftest.json").write_text(json.dumps(rep), encoding="utf-8")


def test_release_needs_a_passing_pair_canary_after_the_hold(tmp_path: Path) -> None:
    audit, data = tmp_path / "audit", tmp_path / "data"
    with pytest.raises(mr.ModelError, match="not held"):
        mr.release("nothing to release", "cli:ops", audit, data)
    _canary(data)  # a pass from before the hold proves nothing about the fix
    time.sleep(0.05)
    res = mr.hold("wrong quotes", "cli:ops", audit)
    assert res["new"] == "off" and mr.status(audit)["held"] is True
    with pytest.raises(mr.ModelError, match="already held"):
        mr.hold("again", "cli:ops", audit)
    with pytest.raises(mr.ModelError, match="ran before the hold"):
        mr.release("fixed", "cli:ops", audit, data)
    _canary(data, ok=False)
    with pytest.raises(mr.ModelError, match="failed"):
        mr.release("fixed", "cli:ops", audit, data)
    _canary(data, pair=False)
    with pytest.raises(mr.ModelError, match="one model"):
        mr.release("fixed", "cli:ops", audit, data)
    _canary(data, at=time.time() + 3600 - 40 * 3600)
    with pytest.raises(mr.ModelError, match="old"):
        mr.release("fixed", "cli:ops", audit, data)
    (data / "selftest.json").unlink()
    with pytest.raises(mr.ModelError, match="no canary result"):
        mr.release("fixed", "cli:ops", audit, data)
    assert evaluate.notes_held() is True  # every refusal left the hold in place
    _canary(data)
    assert mr.release("previous build re-pinned, canary passed", "cli:ops", audit, data)["new"] == "on"
    assert evaluate.notes_held() is False
    events = [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines() if x]
    sets = [(e["detail"]["new"], e["actor"]) for e in events if e["event"] == "flag.set"]
    assert sets == [("off", "cli:ops"), ("on", "cli:ops")]


# ------------------------------------------------------------------------------------------------ the report (drill)
BUILD_A = "a1" * 32
BUILD_B = "b2" * 32
J1, J2, J3, J4 = (f"01JC00000000000000000000{n:02d}" for n in (1, 2, 3, 4))


def _job(db: JobDB, job_id: str, ruleset_id: str, at: datetime, minutes: int, type_: str = "SCREEN") -> None:
    db.put(Job.model_validate({"job_id": job_id, "type": type_, "ruleset": ruleset_id, "ruleset_version": "1.0.0",
                               "requested_by": "crc@hospa.test", "received_at": at.isoformat(),
                               "updated_at": (at + timedelta(minutes=minutes)).isoformat(), "state": "done"}))  # fmt: skip


def _call(log: AuditLog, at: datetime, build: str, study: str, decision: str = "allow") -> None:
    log.append("llm.gateway.call", ts=at, actor="orchestrator", model="judge", prompt_version="judge@4",
               detail={"decision": decision, "study": study, "model_sha": build, "build_id": f"judge-{build[:4]}"})  # fmt: skip


def _verdicts(note: bool) -> list[dict[str, Any]]:
    ev = {"reason": "note", "quote": FLARE} if note else {"reason": "coded"}
    return [{"id": "T-EXC-02" if note else "T-INC-01", "verdict": "fail" if note else "pass", "evidence": ev}]


def test_runbook_19_model_hold(tmp_path: Path, db_url: str) -> None:
    """The drill's report half: build A answered for SCREEN J1 (calls labelled with the job), for J2 through the
    cascade (calls labelled with the ruleset, inside J2's window) and for the canary; build B answered J3; J4 ran on
    build A outside the dates asked. The report lists exactly J1 and J2 with their patients."""
    audit = tmp_path / "audit"
    log = AuditLog(audit, tz="Asia/Taipei")
    db = JobDB(db_url)
    day = datetime(2026, 11, 10, 8, 0, tzinfo=TZ)
    _job(db, J1, "GZQO", day, 30)
    _job(db, J2, "GOUT-COH", day + timedelta(hours=2), 30)
    _job(db, J3, "GZQO", day + timedelta(hours=4), 30)
    _job(db, J4, "GZQO", day - timedelta(days=5), 30)
    _call(log, day - timedelta(days=5, minutes=-5), BUILD_A, J4)  # outside --from/--to
    _call(log, day + timedelta(minutes=5), BUILD_A, J1)
    _call(log, day + timedelta(minutes=6), BUILD_A, J1)
    _call(log, day + timedelta(minutes=7), BUILD_A, J1, decision="refuse")  # refused: no answer, not counted
    _call(log, day + timedelta(hours=2, minutes=10), BUILD_A, "GOUT-COH")  # the cascade: the ruleset's open job
    _call(log, day + timedelta(hours=3), BUILD_A, "none")  # the canary
    _call(log, day + timedelta(hours=4, minutes=5), BUILD_B, J3)
    db.pool_upsert("GZQO", "1.0.0", [{"pid": "aa11bb22", "tier": "review", "verdicts": _verdicts(True)},
                                     {"pid": "cc33dd44", "tier": "high", "verdicts": _verdicts(False)}],
                   J1, day.isoformat())  # fmt: skip
    db.pool_upsert("GOUT-COH", "1.0.0", [{"pid": "ee55ff66", "tier": "review", "verdicts": _verdicts(True)}],
                   J2, day.isoformat())  # fmt: skip
    db.pool_upsert("GZQO", "1.0.0", [{"pid": "0099aabb", "tier": "high", "verdicts": _verdicts(True)}], J3,
                   day.isoformat())  # fmt: skip
    db.candidate_set("GZQO", "aa11bb22", "contacted", None, "crc", day.isoformat(), "screen", J1, "review")
    db.candidate_set("GZQO", "77778888", "screen_fail", None, "crc", day.isoformat(), "screen", J1, "review")
    db.close()

    rep = mr.report(BUILD_A[:12], date(2026, 11, 10), date(2026, 11, 11), [audit], db_url)
    assert [r["job_id"] for r in rep["runs"]] == [J1, J2]
    j1, j2 = rep["runs"]
    assert j1["calls"] == 2 and j1["prompts"] == ["judge@4"] and j2["calls"] == 1 and j2["ruleset"] == "GOUT-COH"
    assert [(p["pid"], p["note_criteria"], p["registry_status"]) for p in j1["patients"]] == [
        ("aa11bb22", ["T-EXC-02"], "contacted"),
        ("cc33dd44", [], None),
        ("77778888", [], "screen_fail"),  # in the registry from J1, no longer in the pool
    ]
    assert [p["pid"] for p in j2["patients"]] == ["ee55ff66"]
    assert rep["patients"] == 4 and rep["calls"] == 4 and rep["calls_not_tied_to_a_run"] == {"none": 1}
    # by build id too; a sha prefix shorter than 8 matches nothing
    assert [r["job_id"] for r in mr.report(f"judge-{BUILD_A[:4]}", date(2026, 11, 10), date(2026, 11, 10),
                                           [audit], db_url)["runs"]] == [J1, J2]  # fmt: skip
    assert mr.report(BUILD_A[:6], date(2026, 11, 10), date(2026, 11, 10), [audit], db_url)["runs"] == []
    assert [r["job_id"] for r in mr.report(BUILD_B, date(2026, 11, 10), date(2026, 11, 10), [audit],
                                           db_url)["runs"]] == [J3]  # fmt: skip

    out = tmp_path / "report.md"
    rc = mr.main(["report", "--build", BUILD_A[:12], "--from", "2026-11-10", "--to", "2026-11-11", "--audit-dir",
                  str(audit), "--out", str(out)])  # fmt: skip
    text = out.read_text(encoding="utf-8")
    assert rc == 0 and J1 in text and J2 in text and J3 not in text and "aa11bb22" in text
    assert mr.main(["report", "--build", BUILD_A, "--from", "2026-11-11", "--to", "2026-11-10",
                    "--audit-dir", str(audit)]) == 1  # fmt: skip
