"""The scale gate's own logic on every pull request (T-687, D-471). The 50,000-patient run is nightly
(`tests/perf/test_scale_gate.py`, job `scale-50k` of trialbox-e2e.yml); here the same gate runs at 200 patients, and
its parts are checked one by one: the caps come from the compose file, a process over its cap is killed, the model
stand-in is slow, fails for a while and restarts, and today's failures are strict expected failures by card.
Synthetic patients only."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from tb_testkit import scale

from tools import scale_gate as sg

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------------ the caps
def test_the_caps_are_the_compose_files_own() -> None:
    caps = scale.compose_caps(environ={})
    doc = yaml.safe_load((ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))
    for svc in ("adapter", "lake", "orchestrator", "db"):  # the services the gate runs under
        raw = str(doc["services"][svc]["mem_limit"])
        default = raw.split(":-", 1)[1].rstrip("}") if ":-" in raw else raw
        assert caps[svc] == scale.parse_size(default), svc
    assert scale.compose_caps(environ={"TB_MEM_ADAPTER": "16g"})["adapter"] == 16 * 2**30  # deploy/.env moves it
    assert scale.compose_setting("adapter", "TB_VALIDATOR_XMX") == "3g"  # the validator's heap inside that cap
    assert scale.compose_setting("adapter", "TB_DB_URL") is None and scale.compose_setting("nope", "X") is None


def test_parse_size() -> None:
    assert scale.parse_size("6g") == 6 * 2**30
    assert scale.parse_size("256m") == 256 * 2**20
    assert scale.parse_size("1.5G") == int(1.5 * 2**30)
    assert scale.parse_size("512") == 512
    with pytest.raises(ValueError):
        scale.parse_size("lots")


def test_a_mem_limit_without_a_value_is_refused(tmp_path: Path) -> None:
    f = tmp_path / "c.yml"
    f.write_text("services:\n  a: {mem_limit: '${TB_MEM_A}'}\n  b: {image: x}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no value"):
        scale.compose_caps(f, environ={})
    assert scale.compose_caps(f, environ={"TB_MEM_A": "1g"}) == {"a": 2**30}


# ------------------------------------------------------------------------------------------------ enforcement
HOG = "import time\nx = bytearray({n})\nfor i in range(0, len(x), 4096): x[i] = 1\ntime.sleep({s})\n"


def test_measure_mode_kills_a_process_over_its_cap_and_passes_one_under_it(tmp_path: Path) -> None:
    enf = scale.Enforcer("measure")
    over = enf.run(
        "hog",
        "adapter",
        64 * 2**20,
        [sys.executable, "-c", HOG.format(n=256 * 2**20, s=5)],
        {},
        tmp_path,
        tmp_path / "hog.log",
    )
    assert over.oom and not over.ok and over.peak > 64 * 2**20 and over.seconds < 5
    under = enf.run(
        "small",
        "adapter",
        512 * 2**20,
        [sys.executable, "-c", HOG.format(n=8 * 2**20, s=0.5)],
        {},
        tmp_path,
        tmp_path / "small.log",
    )
    assert under.ok and under.rc == 0 and 8 * 2**20 < under.peak < 512 * 2**20
    assert "killed at the cap" in over.summary() and "ok" in under.summary()


def test_a_service_runs_under_its_cap_until_the_block_ends(tmp_path: Path) -> None:
    enf = scale.Enforcer("measure")
    with enf.start(
        "svc", "lake", 2**30, [sys.executable, "-c", "import time; time.sleep(60)"], {}, tmp_path, tmp_path / "svc.log"
    ) as (proc, run):
        assert proc.poll() is None
    assert run.rc == 0 and not run.oom and proc.poll() is not None


def test_cgroup_is_refused_where_there_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scale, "cgroup_available", lambda: False)
    assert scale.Enforcer.detect("").mode == "measure"
    assert scale.Enforcer.detect("measure").mode == "measure"
    with pytest.raises(RuntimeError, match="cannot make a memory cgroup"):
        scale.Enforcer.detect("cgroup")
    with pytest.raises(ValueError):
        scale.Enforcer.detect("ulimit")
    monkeypatch.setattr(scale, "cgroup_available", lambda: True)
    enf = scale.Enforcer.detect("cgroup")
    argv = enf.argv(["python", "x.py"], 6 * 2**30)
    assert "systemd-run" in argv and f"MemoryMax={6 * 2**30}" in argv and "MemorySwapMax=0" in argv
    assert argv[-3:] == ["--", "python", "x.py"]


# ------------------------------------------------------------------------------------------------ the stand-in
def test_the_stand_in_is_slow_fails_for_a_while_and_restarts(tmp_path: Path) -> None:
    m = scale.SlowModel(tmp_path, latency_s=0.3, outage_after=2, outage_s=1.5, restart_gap_s=0.2)
    m.start()
    try:
        body = {"model": "stub", "messages": [{"role": "user", "content": "x"}]}
        codes, times = [], []
        for _ in range(4):
            t0 = time.monotonic()
            r = httpx.post(f"{m.url}/chat/completions", json=body, timeout=10)
            times.append(time.monotonic() - t0)
            codes.append(r.status_code)
        assert codes[0] == 400 and codes[1:] == [502, 502, 502]  # no prompt id: 400; then the outage from call 2
        assert min(times) >= 0.3  # seconds per call, the outage's answers too
        assert httpx.get(f"{m.url}/models", timeout=5).status_code == 200  # the server itself answers
        time.sleep(1.6)
        assert httpx.post(f"{m.url}/chat/completions", json=body, timeout=10).status_code == 400  # over
        m.restart()
        assert m.restarts == 1 and httpx.post(f"{m.url}/chat/completions", json=body, timeout=10).status_code == 400
        time.sleep(0.5)
        assert m.calls() == 6 and m.refused() == 3
    finally:
        m.stop()


def test_the_stub_outage_counts_calls_and_ends() -> None:
    from llm_stub import app as stub

    o = stub._Outage()
    env = {"TB_STUB_OUTAGE_AFTER": "3", "TB_STUB_OUTAGE_S": "0.2"}
    assert [o.tick(env) for _ in range(4)] == [False, False, True, True]
    time.sleep(0.25)
    assert o.tick(env) is False and o.tick(env) is False  # one outage per process
    assert stub._Outage().tick({}) is False and stub._float("x") is None and stub._float("-1") is None


# ------------------------------------------------------------------------------------------------ the ledger
def test_expected_failures_are_strict_and_bound_to_their_size() -> None:
    exp = {"a": scale.Expected(("F-01",), "T-690", 50_000), "b": scale.Expected(("F-02",), "T-691")}
    checks = [
        scale.Check("a", False, ""),
        scale.Check("b", False, ""),
        scale.Check("c", True, ""),
        scale.Check("d", None, "", blocked_by="ingest"),
    ]
    big = {r["check"]: r["state"] for r in scale.verdict(checks, exp, 50_000)}
    assert big == {"a": scale.KNOWN, "b": scale.KNOWN, "c": scale.PASS, "d": scale.BLOCKED}
    small = {r["check"]: r["state"] for r in scale.verdict(checks, exp, 200)}
    assert small["a"] == scale.FAIL  # below its size the check must pass
    fixed = scale.verdict([scale.Check("b", True, "")], exp, 200)
    assert fixed[0]["state"] == scale.FIXED and not scale.gate_ok(fixed)  # a pass of a known failure is red
    assert scale.gate_ok(scale.verdict(checks, exp, 50_000))


def test_the_ledger_names_a_finding_and_a_card_for_each_known_failure() -> None:
    assert set(sg.EXPECTED) <= set(sg.CHECKS)
    for cid, e in sg.EXPECTED.items():
        assert e.findings and all(f.startswith("F-") for f in e.findings) and e.card.startswith("T-"), cid
    # G1 BUGS.md B2's three blockers F-01 (T-690), F-02 (T-691), F-05 (T-692), and F-04 (T-689): fixed on master, they
    # pass the gate and their lines are gone; the gate's tests below still catch each shape
    found = {f for e in sg.EXPECTED.values() for f in e.findings}
    assert not found & {"F-01", "F-02", "F-04", "F-05"}
    # the faults the gate counts include the product's own list (T-689: the batch roles wait through these)
    from tb_llm.outage import MODEL_FAULTS

    assert MODEL_FAULTS <= sg.FAULT_REFUSALS and "upstream_down" in sg.FAULT_REFUSALS


# ------------------------------------------------------------------------------------------------ the gate, small
def _params(tmp_path: Path, **kw: Any) -> sg.Params:
    base: dict[str, Any] = {
        "patients": 200,
        "out": tmp_path / "gate",
        "enforce": "measure",
        "validate": False,
        "latency_s": 0.05,
        "outage_after": 2,
        "outage_s": 1.0,
        # the restart after the THIRD call: calls 2 and 3 are the outage's 502 answers, so the restart falls into the
        # outage's own second, while the screen waits, and not into the 0.15 s its last three calls take (train 5)
        "restart_after": 3,
        "publish_poll_s": 0.5,
        "publish_wait_s": 300.0,
    }
    base.update(kw)
    return sg.Params(**base)


def test_the_gate_at_200_patients(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every part runs; under 50,000 the size-bound checks pass, the publish (T-690) and the backup without a pause
    (T-691) pass, and the screen waits through the outage and the restart (T-689): no judge call lost, green."""
    monkeypatch.setenv("TB_DB_URL", db_url)
    rep = sg.run(_params(tmp_path))
    rows = {r["check"]: r for r in rep.rows()}
    assert set(rows) == set(sg.CHECKS), rows
    for cid in (
        "ingest.night_under_cap",
        "rebuild.under_cap",
        "publish.recorded_once",
        "screen.ends_under_cap",
        "screen.model_faults_seen",
        "screen.outage_no_unknown",
        "backup.ends",
        "backup.no_pause",
    ):
        assert rows[cid]["state"] == scale.PASS, rows[cid]
    assert (
        rep.ok() and rep.numbers["screen"]["stand_in_outage_answers"] > 0
    )  # the outage happened and was waited through
    md = (tmp_path / "gate" / "scale_gate.md").read_text(encoding="utf-8")
    assert "enforcement: measure" in md and "Gate: green" in md
    assert rep.numbers["publish"]["rebuilds_started"] == 1 and rep.numbers["screen"]["stand_in_restarts"] == 1


def test_the_gate_catches_f01_and_f02_shapes(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate still sees what T-690 and T-691 fixed. F-01's shape: a site publish that loses its publish in progress
    (the record of the job it started), so it is never recorded and a later tick starts a second rebuild of the
    snapshot. F-02's shape: the backup with D-274's pause (``TB_BACKUP_QUIESCE=pause``). Both FAIL (no EXPECTED line
    covers them any more), and the gate is red."""
    from sitesetup.service import SiteSetup

    monkeypatch.setenv("TB_DB_URL", db_url)
    monkeypatch.setattr(SiteSetup, "_record", lambda self, ws: None)  # the publish forgets the job it started
    rep = sg.run(_params(tmp_path, outage_s=0.0, restart_after=0, backup_quiesce="pause"))
    rows = {r["check"]: r for r in rep.rows()}
    pub = rows["publish.recorded_once"]
    assert pub["state"] == scale.FAIL and "recorded=False" in pub["detail"], pub
    assert rep.numbers["publish"]["rebuilds_started"] >= 2
    pause = rows["backup.no_pause"]
    assert pause["state"] == scale.FAIL and "services paused" in pause["detail"], pause
    assert rep.numbers["backup"]["paused"] and not rep.ok()
    # no fault reached the stand-in in this run: the outage check was not exercised, so it is blocked, never a pass
    # (nor a "FIXED" of F-04's line)
    assert rows["screen.outage_no_unknown"]["state"] == scale.BLOCKED


def test_a_night_killed_at_its_cap_blocks_nothing_it_can_feed(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The night killed at the adapter's cap (F-05's shape): the check fails, the back-fill feeds the later parts,
    the report says so. A cap below what the night needs at this size stands in for 6 GB at 50,000."""
    monkeypatch.setenv("TB_DB_URL", db_url)
    caps = {**scale.compose_caps(environ={}), "adapter": 40 * 2**20}
    rep = sg.run(_params(tmp_path, caps=caps, outage_s=0.0, restart_after=0))
    rows = {r["check"]: r for r in rep.rows()}
    assert (
        rows["ingest.night_under_cap"]["state"] == scale.FAIL
        and "killed at the adapter cap" in rows["ingest.night_under_cap"]["detail"]
    )
    if any("back-fill" in n for n in rep.notes) and rows["rebuild.under_cap"]["state"] != scale.BLOCKED:
        assert rows["publish.recorded_once"]["state"] in (scale.PASS, scale.FAIL)
    else:  # the back-fill did not fit 40 MB either: everything that needs the snapshot is blocked by the ingest
        assert rows["rebuild.under_cap"]["blocked_by"] == "ingest"
    assert rows["backup.no_pause"]["state"] == scale.PASS


def test_a_lake_over_its_cap_fails_the_rebuild(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """F-05's other half: the lake killed at its cap. A cap below what the lake needs at this size stands in for 8 GB
    at 50,000; the rebuild fails, and what needs the lake is blocked by it (never a pass)."""
    monkeypatch.setenv("TB_DB_URL", db_url)
    caps = {**scale.compose_caps(environ={}), "lake": 120 * 2**20}
    rep = sg.run(_params(tmp_path, caps=caps, outage_s=0.0, restart_after=0))
    rows = {r["check"]: r for r in rep.rows()}
    assert rows["ingest.night_under_cap"]["state"] == scale.PASS
    assert rows["rebuild.under_cap"]["state"] == scale.FAIL, rows["rebuild.under_cap"]
    for cid in ("screen.ends_under_cap", "screen.outage_no_unknown"):
        assert rows[cid]["state"] == scale.BLOCKED and rows[cid]["blocked_by"] == "rebuild", rows[cid]
    assert not rep.ok()


def test_the_gate_catches_a_screen_that_loses_calls_in_an_outage(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-04's shape after T-689: an outage the product does not wait through. The stand-in answers its outage with 400
    (a configuration fault to the gateway, ``upstream_failed``: not sent again), so the screen loses those calls and
    the gate says FAIL (no EXPECTED line covers it any more)."""
    monkeypatch.setenv("TB_DB_URL", db_url)
    rep = sg.run(_params(tmp_path, outage_status=400, restart_after=0))
    row = next(r for r in rep.rows() if r["check"] == "screen.outage_no_unknown")
    assert row["state"] == scale.FAIL and "lost to the model's faults" in row["detail"], row
    assert rep.numbers["screen"]["stand_in_outage_answers"] > 0 and not rep.ok()


# ------------------------------------------------------------------------------------------------ the nightly job
def test_the_nightly_job_runs_the_gate_at_50000_under_a_cgroup() -> None:
    wf = yaml.safe_load((ROOT.parent / ".github/workflows/trialbox-e2e.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on") or wf.get(True)
    assert "schedule" in triggers and "pull_request" not in triggers
    job = wf["jobs"]["scale-50k"]
    env = {k: str(v) for k, v in job["env"].items()}
    assert env["TB_SCALE_PATIENTS"] == "50000" and env["TB_SCALE_ENFORCE"] == "cgroup"
    assert float(env["TB_SCALE_OUTAGE_S"]) == 40 and float(env["TB_SCALE_LATENCY_S"]) >= 1  # the row: seconds, 40 s
    assert int(env["TB_SCALE_RESTART_AFTER"]) > int(env["TB_SCALE_OUTAGE_AFTER"]) > 0
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert "tests/perf/test_scale_gate.py" in steps and "GITHUB_STEP_SUMMARY" in steps


def test_the_lint_runs_on_every_pull_request() -> None:
    wf = (ROOT.parent / ".github/workflows/trialbox-ci.yml").read_text(encoding="utf-8")
    assert "python -m tools.limits_lint" in wf


# ------------------------------------------------------------------------------------------------ the edges of the parts
def test_compose_setting_reads_a_list_environment(tmp_path: Path) -> None:
    f = tmp_path / "c.yml"
    f.write_text('services:\n  a:\n    environment: [X=1, Y, "Z=${V:-2}"]\n', encoding="utf-8")
    assert scale.compose_setting("a", "X", f) == "1"
    assert scale.compose_setting("a", "Y", f) is None and scale.compose_setting("a", "Z", f) is None


def test_the_cgroup_prefix_and_its_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    pre = scale._cgroup_prefix(2**30)
    assert pre[:3] == ["sudo", "-n", "-E"] and "--uid=" + str(os.getuid()) in pre  # the runner keeps its user
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert scale.cgroup_available() is False  # no systemd-run
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    class Done:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    for answer, want in ((Done(0), True), (Done(1), False), (OSError("no sudo"), False)):

        def run(*a: Any, answer: Any = answer, **k: Any) -> Any:
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(subprocess, "run", run)
        assert scale.cgroup_available() is want


def test_a_service_that_ignores_the_stop_is_killed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scale, "STOP_GRACE_S", 0.5)
    code = (
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('up', flush=True)\ntime.sleep(60)\n"
    )
    enf = scale.Enforcer("measure")
    t0 = time.monotonic()
    with enf.start("stubborn", "lake", 2**30, [sys.executable, "-c", code], {}, tmp_path, tmp_path / "s.log") as (
        proc,
        run,
    ):
        end = time.monotonic() + 10
        while "up" not in (tmp_path / "s.log").read_text() and time.monotonic() < end:
            time.sleep(0.05)
    assert proc.returncode == -9 and run.rc == 0 and time.monotonic() - t0 < 10
    assert scale._tail(tmp_path / "missing.log") == ""


def test_a_stand_in_that_never_answers_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert scale.wait_http(f"http://127.0.0.1:{scale.free_port()}/v1/models", 0.3) is False
    monkeypatch.setattr(scale, "wait_http", lambda *a, **k: False)
    m = scale.SlowModel(tmp_path)
    with pytest.raises(RuntimeError, match="did not start"):
        m.start()
    m.stop()


def test_the_gate_with_the_dense_profile(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-687, the dense profile: the same night on a hospital whose charts are about 500 records and 40 notes
    thick. Small here (the nightly job runs 50,000); every part runs and the report says what was measured."""
    monkeypatch.setenv("TB_DB_URL", db_url)
    rep = sg.run(_params(tmp_path, patients=30, profile="dense", outage_s=0.0, restart_after=0))
    facts = rep.profile_facts
    assert facts["patients"] == 30
    assert scale.DENSE_RECORDS <= facts["records_per_patient"] < scale.DENSE_RECORDS * 1.1
    assert scale.DENSE_NOTES <= facts["notes_per_patient"] < scale.DENSE_NOTES * 1.1
    rows = {r["check"]: r for r in rep.rows()}
    assert set(rows) == set(sg.CHECKS), rows
    for cid in ("ingest.night_under_cap", "rebuild.under_cap", "publish.recorded_once", "screen.ends_under_cap",
                "backup.ends"):  # fmt: skip
        assert rows[cid]["state"] == scale.PASS, rows[cid]
    assert rep.numbers["ingest"]["records"] >= facts["records"]  # the night took the whole thick feed
    md = (tmp_path / "gate" / "scale_gate.md").read_text(encoding="utf-8")
    assert "(dense profile)" in md and "dense profile: " in md
    assert rep.to_json()["profile"] == "dense"


def test_the_restart_watcher_sees_the_call_before_a_short_screen_ends(tmp_path: Path) -> None:
    """Train 5's CI (unit shard 4/6): "2 outage answers (502), 0 restart(s) in 7 calls". The screen makes the same
    7 calls on every run; the restart "after call 4" was a thread that looked at the stand-in's call count every
    half second, and the three calls left take 0.15 s at 0.05 s a call: when the screen ended inside one look,
    the restart never happened. The watcher looks twice per call of the stand-in (its interval is the stand-in's
    own seconds per call, halved), so the call is seen while at least one more is still being answered."""
    m = scale.SlowModel(tmp_path, latency_s=0.05)
    seen = {"calls": 0, "restarts": 0}
    m.calls = lambda: seen["calls"]  # type: ignore[method-assign]
    m.restart = lambda: seen.__setitem__("restarts", seen["restarts"] + 1)  # type: ignore[method-assign]
    done = threading.Event()
    watcher = m.restart_after(4, done)
    time.sleep(0.1)  # the watcher has looked, and waits
    seen["calls"] = 4  # the fourth call is answered ...
    time.sleep(3 * 0.05)  # ... and the screen's last three calls take three times the stand-in's latency
    done.set()
    watcher.join(5)
    assert seen["restarts"] == 1
