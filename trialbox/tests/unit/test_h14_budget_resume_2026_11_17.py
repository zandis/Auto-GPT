"""Card H-14 (D-1129): a set that ends on its own budget is resumable. ``--resume`` with a new ``--acc-deadline`` runs
only the protocols the budget cut (or never started), in a new attempt of the set; a finished protocol is never sent to
FEAS, APPROVE or SCREEN again; answers, logs and the score read the attempts as one. Synthetic data only; no VM, no
network, no cloud call.

The VM script's side (the retry opening the step again, the TB-RESUME-PLAN lines, the audit and traces added per
attempt) is rehearsed end to end by tests/unit/test_g1_box_install_run.py's case acc-cut-resume
(tests/rehearsal/box-run); the text checks here pin what that case cannot see."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
import types
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_g1_box_accuracy import FakeBox, _built, box_vm
from tools import box_run
from tools.public_accuracy import score

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
VM_SCRIPT = (ROOT / "deploy" / "gcp" / "box-install-run.sh").read_text(encoding="utf-8")
DRIVER = (ROOT / "deploy" / "gcp" / "box-run.sh").read_text(encoding="utf-8")
KW: dict[str, Any] = {"sender": "c@x", "reviewer": "pi@x", "run_id": "r1", "compile_only": False, "job_s": 3600}
P1, P2, P3 = "NCT90000001", "NCT90000002", "NCT90000003"


class Clock:
    """The set's clock, moved by the box's waits only."""

    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t


class TimedBox(FakeBox):
    """FakeBox whose every wait takes 10 s of the set's clock; a FEAS of a ruleset in ``slow`` runs out its wait (the
    set's budget cuts it). Every call is recorded, by command and ruleset."""

    def __init__(self, clock: Clock, slow: set[str] | None = None) -> None:
        super().__init__()
        self.clock, self.slow = clock, set(slow or ())
        self.calls: list[tuple[str, str, str]] = []

    def call(self, svc: str, cmd: str, a: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        a = a or {}
        rs = a["subject"].split()[1] if cmd == "send" else self.jobs.get(a.get("job", ""), {}).get("rs", "")
        kind = a["subject"].split()[0] if cmd == "send" else self.jobs.get(a.get("job", ""), {}).get("kind", "")
        self.calls.append((cmd, kind, rs))
        r = super().call(svc, cmd, a, timeout)
        if cmd == "wait":
            self.clock.t += 10.0
            if kind == "FEAS" and rs in self.slow:
                r["state"], r["waited"] = "running", "timeout"
        return r


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    fake = types.SimpleNamespace(**{k: getattr(time, k) for k in ("strftime", "gmtime", "sleep", "time")})
    fake.monotonic = c.monotonic
    monkeypatch.setattr(box_vm, "time", fake)
    return c


def _two_attempts(tmp_path: Path, clock: Clock) -> tuple[Path, Path, TimedBox, dict[str, Any]]:
    """Attempt 1 on a 45 s budget: P1's FEAS runs out its wait (cut, its job kept), P2 goes through (30 s), P3 is
    not started (5 s left, a protocol takes 30). Attempt 2 (a resume's tag) on its own 200 s: P1 and P3 only."""
    built, work = _built(tmp_path, trials=3), tmp_path / "work"
    box = TimedBox(clock, slow={P1})
    r1 = box_vm.acc_set("sigir", built, work, box, deadline_s=45, min_start_s=10, **KW)
    box.slow = set()
    return built, work, box, r1


def test_attempt_one_ends_on_its_budget_with_what_a_resume_takes_up(tmp_path: Path, clock: Clock) -> None:
    _, work, _, r1 = _two_attempts(tmp_path, clock)
    prog = json.loads((work / "progress.json").read_text())
    assert prog[P1]["outcome"] == "not_run_time_budget" and "feas_job" in prog[P1]  # started: its job is kept
    assert prog[P3]["outcome"] == "not_run_time_budget" and "feas_job" not in prog[P3]  # never started
    assert prog[P2]["outcome"] == "screened" and prog[P2]["attempt"] == 1
    assert r1["budget_cut"] == 2 and r1["counts"]["screened"] == 1
    assert r1["attempts_line"] == "attempts: 1; protocols finished in attempt 1: 1; still cut: 2"
    assert json.loads((work / "set-clock.json").read_text())["used_s"] == 40.0


def test_attempt_two_runs_only_the_cut_protocols_and_never_sends_a_done_one_again(tmp_path: Path, clock: Clock) -> None:
    built, work, box, _ = _two_attempts(tmp_path, clock)
    a1 = json.loads((work / "answers.json").read_text())
    screen_p2 = (work / "screen" / f"{P2}.json").read_bytes()
    (work / "services.log").write_text("attempt 1's services lines\n")
    n1 = len(box.calls)
    r2 = box_vm.acc_set("sigir", built, work, box, deadline_s=200, min_start_s=10, new_attempt="retry-1", **KW)
    later = box.calls[n1:]
    # no done protocol is sent to FEAS, APPROVE or SCREEN again, nor waited for or fetched (calls counted)
    assert not [c for c in later if c[2] == P2]
    sends = [(k, rs) for cmd, k, rs in box.calls if cmd == "send"]
    for rs in (P1, P2, P3):
        assert [k for k, r in sends if r == rs] == ["FEAS", "APPROVE", "SCREEN"], rs  # each once over both attempts
    assert ("send", "FEAS", P1) not in later  # the cut protocol's FEAS job of attempt 1 is waited for, not re-sent
    assert ("wait", "FEAS", P1) in later
    assert r2["counts"]["screened"] == 3 and r2["budget_cut"] == 0 and r2["pass"] is True
    assert r2["attempts_line"] == "attempts: 2; protocols finished in attempt 1: 1; in attempt 2: 2; still cut: 0"
    # one record: each protocol once, the attempt that answered it; attempt 1's answer untouched
    a2 = json.loads((work / "answers.json").read_text())
    assert {rs: a["attempt"] for rs, a in a2.items()} == {P1: 2, P2: 1, P3: 2}
    assert a2[P2] == a1[P2] and (work / "screen" / f"{P2}.json").read_bytes() == screen_p2
    # the set's clock: attempt 2 on its own budget from 0; attempt 1's seconds and budget kept
    c = json.loads((work / "set-clock.json").read_text())
    assert c["attempt"] == 2 and c["attempt_tag"] == "retry-1" and c["deadline_s"] == 200 and c["used_s"] == 60.0
    assert c["attempts"] == [{"attempt": 1, "tag": "", "used_s": 40.0, "deadline_s": 45}] and c["earlier_s"] == 40.0
    assert c["attempt_started"] and box_vm.acc_attempt(work) == (2, c["attempt_started"])
    # the services' lines of attempt 1 kept ahead of attempt 2's; box-calls.log says where attempt 2 began
    assert "attempt 1's services lines" in (work / "services.earlier.log").read_text()
    assert not (work / "services.log").exists()
    assert "== attempt 2 of the set (retry-1)" in (work / "box-calls.log").read_text()
    # a reboot within attempt 2 (the same tag): no new attempt, nothing sent again
    n2 = len(box.calls)
    r3 = box_vm.acc_set("sigir", built, work, box, deadline_s=200, min_start_s=10, new_attempt="retry-1", **KW)
    assert json.loads((work / "set-clock.json").read_text())["attempt"] == 2 and r3["attempts"]["attempts"] == 2
    assert not [c for c in box.calls[n2:] if c[0] in ("send", "wait")]


def test_a_set_with_nothing_cut_has_nothing_for_a_resume(tmp_path: Path, clock: Clock) -> None:
    built, work = _built(tmp_path, trials=2), tmp_path / "work"
    res = box_vm.acc_set("sigir", built, work, TimedBox(clock), **KW)
    assert res["budget_cut"] == 0 and res["attempts"] == {"attempts": 1, "finished_in": {"1": 2}, "still_cut": 0,
                                                          "line": "attempts: 1; protocols finished in attempt 1: 2; "
                                                          "still cut: 0"}  # fmt: skip
    assert box_vm.acc_attempt(work) == (1, "")


def test_the_audit_and_traces_of_an_attempt_are_added_once(tmp_path: Path) -> None:
    au, new = tmp_path / "gateway-audit.json", tmp_path / "new.json"
    au.write_text(json.dumps({"since": "2026-11-17T01:00:00", "calls_by_prompt": {"judge@5": 4},
                              "refusals": {"phi_tripwire": 1}, "refusals_by_job": {"j1": {"phi_tripwire": 1}},
                              "time_unreadable": 0}))  # fmt: skip
    new.write_text(json.dumps({"since": "2026-11-17T05:00:00", "calls_by_prompt": {"judge@5": 3, "ir_extract@3": 1},
                               "refusals": {}, "refusals_by_job": {}, "time_unreadable": 1}))  # fmt: skip
    for _ in range(2):  # merged twice (a reboot after the merge): attempt 2 is still counted once
        box_vm.merge_attempt("audit", au, new, 2)
    d = json.loads(au.read_text())
    assert d["calls_by_prompt"] == {"judge@5": 7, "ir_extract@3": 1} and d["refusals"] == {"phi_tripwire": 1}
    assert d["since"] == "2026-11-17T01:00:00" and sorted(d["attempts"]) == ["1", "2"] and d["time_unreadable"] == 1
    tr = tmp_path / "raw-traces.json"
    rows = [{"call_id": "c1", "output": "a"}, {"call_id": "c2", "output": "b"}]
    tr.write_text(json.dumps({"since": "s1", "calls": 2, "traces": rows}))
    new.write_text(json.dumps({"since": "s2", "calls": 2, "traces": [rows[1], {"call_id": "c3", "output": "c"}]}))
    box_vm.merge_attempt("traces", tr, new, 2)
    t = json.loads(tr.read_text())
    assert [r["call_id"] for r in t["traces"]] == ["c1", "c2", "c3"] and t["calls"] == 3


def _scored(tmp_path: Path, built: Path, work: Path, name: str) -> dict[str, Any]:
    d = tmp_path / name / "acc" / "sigir"
    shutil.copytree(built, d / "built")
    shutil.copytree(work, d / "work")
    box_run.acc_score(tmp_path / name)
    out: dict[str, Any] = json.loads((d / "score.json").read_text())
    return out


def test_the_scorer_reads_two_attempts_as_the_same_protocols_run_in_one(tmp_path: Path, clock: Clock) -> None:
    built, work, box, _ = _two_attempts(tmp_path / "a", clock)
    box_vm.acc_set("sigir", built, work, box, deadline_s=200, min_start_s=10, new_attempt="retry-1", **KW)
    one = tmp_path / "one"
    box_vm.acc_set("sigir", built, one, TimedBox(clock), **KW)  # the same protocols, one attempt, no budget
    two, single = _scored(tmp_path, built, work, "two"), _scored(tmp_path, built, one, "single")
    assert two["schema_version"] == score.SCHEMA_VERSION == 4
    a2, a1 = two["protocols"].pop("attempts"), single["protocols"].pop("attempts")
    for sc in (two, single):  # the summary carries the same block
        sc["summary"]["protocols"].pop("attempts")
    assert two == single  # every figure and denominator equal: each protocol counted once
    assert two["protocols"]["screened"] == 3 and two["protocols"]["not_run_time_budget"] == 0
    assert a2["line"] == "attempts: 2; protocols finished in attempt 1: 1; in attempt 2: 2; still cut: 0"
    assert a1 == {"attempts": 1, "finished_in": {"1": 3}, "still_cut": 0,
                  "line": "attempts: 1; protocols finished in attempt 1: 3; still cut: 0"}  # fmt: skip


def test_the_scorer_counts_a_protocol_still_cut_and_reads_answers_with_no_attempt_as_attempt_one() -> None:
    answers = {"A": {"outcome": "screened", "screen": "done"}, "B": {"outcome": "not_run_time_budget", "attempt": 2},
               "C": {"outcome": "screened", "screen": "done", "attempt": 2}}  # fmt: skip
    a = score.attempts(answers, {"attempt": 3})
    assert a == {"attempts": 3, "finished_in": {"1": 1, "2": 1, "3": 0}, "still_cut": 1,
                 "line": "attempts: 3; protocols finished in attempt 1: 1; in attempt 2: 1; in attempt 3: 0; "
                 "still cut: 1"}  # fmt: skip
    pr = score.score_protocols({"rulesets": {"x": "A", "y": "B", "z": "C"}}, answers)
    assert pr["screened"] == 2 and pr["not_run_time_budget"] == 1 and pr["attempted"] == 2
    assert pr["attempts"]["attempts"] == 2  # no clock: the highest attempt an answer carries


def test_the_replay_reads_a_two_attempt_folder(tmp_path: Path, clock: Clock) -> None:
    from tools.public_accuracy import replay

    built, work, box, _ = _two_attempts(tmp_path / "a", clock)
    box_vm.acc_set("sigir", built, work, box, deadline_s=200, min_start_s=10, new_attempt="retry-1", **KW)
    where = tmp_path / "scored"
    sc = replay.score_all({"sigir": (built, work, work)}, where)
    pf = replay.protocols_figure("a", sc)
    assert pf["per_set"]["sigir"]["screened"] == 3 and pf["denominator"] == 3
    assert pf["per_set"]["sigir"]["attempts"].startswith("attempts: 2; protocols finished in attempt 1: 1;")


# ---------------------------------------------------------------- the free look: what a resume would take up
def _results(d: Path, parts: dict[str, dict[str, Any]]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    with tarfile.open(d / "results.tgz", "w:gz") as t:
        for name, obj in parts.items():
            raw = json.dumps(obj).encode()
            info = tarfile.TarInfo(f"parts/{name}.json")
            info.size = len(raw)
            t.addfile(info, io.BytesIO(raw))


def _parts() -> dict[str, dict[str, Any]]:
    return {
        "60-acc-jmed": {"status": "done", "detail": {"budget_cut": 2, "counts": {"not_run_time_budget": 2}}},
        "61-acc-sigir": {"status": "done", "detail": {"budget_cut": 0, "counts": {"screened": 3}}},
        "62-acc-tfda": {"status": "done", "detail": {"counts": {"not_run_time_budget": 1}}},  # a part before D-1129
        "53-acc-data": {"status": "done", "detail": {}},
        "79-acc-result": {"status": "done", "detail": {}},
    }


def test_the_resume_plan_says_what_a_resume_takes_up_from_the_last_collect(tmp_path: Path) -> None:
    d = tmp_path / "run"
    _results(d, _parts())
    (d / "acc" / "jmed" / "work").mkdir(parents=True)
    (d / "acc" / "jmed" / "work" / "progress.json").write_text(json.dumps(
        {"MNCT1": {"finished": True, "outcome": "screened"}, "MNCT2": {"finished": True, "outcome": "not_run_time_budget"},
         "MNCT3": {"finished": True, "outcome": "not_run_time_budget"}}))  # fmt: skip
    p = box_run.resume_plan(d, "jmed:900")
    rows = {r["set"]: r for r in p["sets"]}
    assert sorted(rows) == ["jmed", "sigir", "tfda"] and p["state"] == "the last collect" and p["refused"] == []
    assert rows["jmed"]["budget_s"] == 900 and rows["jmed"]["cut_protocols"] == ["MNCT2", "MNCT3"]
    assert "runs only its 2 cut protocols, in a new attempt with 900 s" in rows["jmed"]["what"]
    assert rows["sigir"]["what"] == "nothing cut: stays done, not run again"
    assert "stays done unless --acc-deadline gives tfda a budget" in rows["tfda"]["what"]
    assert p["needs_deadline"] == ["tfda"] and any('--acc-deadline "tfda:SECONDS"' in x for x in p["lines"])
    assert box_run.resume_plan(d, "600")["needs_deadline"] == []  # one number: every set's budget
    assert "run again from no work" in {r["set"]: r for r in box_run.resume_plan(d, "", "60-acc-jmed")["sets"]}[
        "jmed"]["what"]  # fmt: skip
    bad = box_run.resume_plan(d, "chia:60 abc")["refused"]
    assert len(bad) == 2 and "set chia is not a set of this run" in bad[0] and "seconds" in bad[1]


def test_the_resume_plan_says_when_the_state_is_only_in_the_bucket(tmp_path: Path) -> None:
    p = box_run.resume_plan(tmp_path / "nothing", "jmed:60")
    assert p["state"] == "not here" and p["sets"] == [] and "only in the bucket" in p["lines"][0]
    assert "TB-RESUME-PLAN" in p["lines"][0]


def test_the_driver_preflight_of_a_resume_is_free_and_refuses_a_budget_that_cannot_hold(tmp_path: Path) -> None:
    d = tmp_path / "run"
    _results(d, _parts())
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PY": sys.executable, "TB_BOXRUN_DIR": str(d)}

    def run(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(ROOT / "deploy" / "gcp" / "box-run.sh"), "--preflight", "--resume", "box-r1", *a],
                              env=env, capture_output=True, text=True, check=False)  # fmt: skip

    r = run("--acc-deadline", "jmed:900")
    assert r.returncode == 0, r.stderr
    assert "60-acc-jmed (done): runs only its 2 cut protocols" in r.stderr and "tfda:SECONDS" in r.stderr
    assert "nothing was read from the bucket" in r.stdout and "gcloud" not in r.stdout + r.stderr
    r = run("--acc-deadline", "chia:900")
    assert r.returncode == 6 and "refused (no VM started)" in r.stderr
    assert sorted(p.name for p in d.iterdir()) == ["results.tgz"]  # a preflight leaves nothing behind


# ---------------------------------------------------------------- the VM script: what the rehearsal cannot see
def test_the_vm_opens_a_budget_cut_set_only_with_a_budget_and_redo_keeps_its_meaning() -> None:
    retry = VM_SCRIPT[VM_SCRIPT.index("RETRY=$(md tb-retry || true)") : VM_SCRIPT.index('rm -f "$RUN/cap-used-s"')]
    assert 'TB_ACC_DEADLINE="$(md tb-acc-deadline || true)"' in retry and '| tee -a "$LOG"' in retry
    assert retry.index("D-1129, before the stopped steps are cleared") < retry.index('if s.get("status") == "stop"')
    assert "name in redo" in retry and 'kv.pop(f"acc_reopen_{setname}", None)' in retry
    assert 'f"{name}.budget-{retry}.json"' in retry and '"79-acc-result"' in retry
    step = VM_SCRIPT[VM_SCRIPT.index("step_acc_set() {") : VM_SCRIPT.index("step_acc_result() {")]
    assert 'only+=(--new-attempt "$ro")' in step and "note budget_cut" in step and "note attempts_line" in step
    assert (
        'acc_box_read "$name" audit gateway-audit.json' in step
        and 'acc_box_read "$name" traces raw-traces.json' in step
    )
    assert '"more than one attempt"' in step  # F22: a set run in two attempts measures no slowdown
    # the reads of the gateway an attempt makes are the same calls as before (the caller table, H-13)
    read = VM_SCRIPT[VM_SCRIPT.index("acc_box_read() {") : VM_SCRIPT.index("step_acc_set() {")]
    assert read.count('acc_call gateway "$kind"') == 2


def test_the_driver_says_how_a_budget_resume_is_asked_for() -> None:
    head = DRIVER[: DRIVER.index("set -euo pipefail")]
    assert '--resume <run id> --acc-deadline "set:SECONDS ..."' in head and "--preflight --resume <run id>" in head
    body = DRIVER[DRIVER.index('if [ -n "$RESUME" ]; then') :]
    assert body.index("br resume-plan") < body.index('[ "$(status)" = TERMINATED ]')


# ---------------------------------------------------------------- the site's zone in the set's record (lead, H-14)
def test_the_set_records_the_zone_the_box_reports_and_the_replay_reads_it(tmp_path: Path, clock: Clock) -> None:
    from tools.public_accuracy import onbox, replay

    zone = "Pacific/Auckland"  # any zone the box could report: the code holds none of its own
    built, d = _built(tmp_path, trials=1), tmp_path / "set"
    box_vm.acc_set("sigir", built, d / "work", TimedBox(clock), site_tz=zone, **KW)
    assert json.loads((d / "work" / "set-clock.json").read_text())["tz"] == zone
    box_vm.acc_set("sigir", built, d / "work", TimedBox(clock), **KW)  # a boot that could not read it keeps it
    assert replay.zone_of_record(d)["tz"] == zone
    assert replay.zone_of_record(d)["from"] == "work/set-clock.json: tz"
    import inspect

    src = inspect.getsource(onbox.cmd_env)  # the env answer names the box's own zone, as its config reads it
    assert '"tz": str(getattr(cfg.env, "tz", "") or os.environ.get("TB_TZ") or "")' in src
    step = VM_SCRIPT[VM_SCRIPT.index("step_acc_set() {") : VM_SCRIPT.index("step_acc_result() {")]
    assert 'tz=$(jget "$RUN/logs/acc-env-$name.json" tz)' in step and 'only+=(--site-tz "$tz")' in step
