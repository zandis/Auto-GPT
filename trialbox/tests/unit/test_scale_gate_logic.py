"""The scale gate's own logic on every pull request (T-687, D-471). The 50,000-patient run is nightly
(`tests/perf/test_scale_gate.py`, job `scale-50k` of trialbox-e2e.yml); here the same gate runs at 200 patients, and
its parts are checked one by one: the caps come from the compose file, a process over its cap is killed, the model
stand-in is slow, fails for a while and restarts, and today's failures are strict expected failures by card.
Synthetic patients only."""

from __future__ import annotations

import sys
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
    m = scale.SlowModel(tmp_path, latency_s=0.3, outage_after=2, outage_s=1.5)
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
    # the owner's three blockers are there (G1 BUGS.md B2): F-01, F-02, F-05
    assert {f for e in sg.EXPECTED.values() for f in e.findings} >= {"F-01", "F-02", "F-05"}


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
        "restart_after": 4,
        "publish_poll_s": 0.5,
        "publish_wait_s": 300.0,
    }
    base.update(kw)
    return sg.Params(**base)


def test_the_gate_at_200_patients(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every part runs; under 50,000 the size-bound checks pass, and the size-free known failures (F-02's pause, F-04's
    lost calls) are reported as known-open with their cards; the gate is green."""
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
        "backup.ends",
    ):
        assert rows[cid]["state"] == scale.PASS, rows[cid]
    assert rows["backup.no_pause"]["state"] == scale.KNOWN and rows["backup.no_pause"]["expected"] == "F-02 (T-691)"
    assert rows["screen.outage_no_unknown"]["state"] == scale.KNOWN
    assert rep.ok()
    md = (tmp_path / "gate" / "scale_gate.md").read_text(encoding="utf-8")
    assert "known-open | F-02 (T-691)" in md and "enforcement: measure" in md and "Gate: green" in md
    assert rep.numbers["publish"]["rebuilds_started"] == 1 and rep.numbers["screen"]["stand_in_restarts"] == 1


def test_the_gate_catches_a_publish_slower_than_its_client(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-01's shape at a small size: a lake client whose limit is shorter than the rebuild. The publish is never
    recorded and the next tick rebuilds again; the gate says so (FAIL, since the F-01 line applies from 50,000)."""
    monkeypatch.setenv("TB_DB_URL", db_url)
    rep = sg.run(_params(tmp_path, lake_timeout_s=0.2, outage_s=0.0, restart_after=0))
    row = next(r for r in rep.rows() if r["check"] == "publish.recorded_once")
    assert row["state"] == scale.FAIL and "recorded=False" in row["detail"], row
    assert rep.numbers["publish"]["rebuilds_started"] >= 2 and not rep.ok()


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
    assert rows["backup.no_pause"]["state"] == scale.KNOWN


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
