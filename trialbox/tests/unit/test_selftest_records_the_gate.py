"""Lane G's hand-over, F35 (#639, 2026-11-16), D-916: an operator at the box's command line could not run the gate's
canary. ``POST /models/canary`` is the console's alone (``route_callers.yaml``) and ``GET /models`` a protected read,
both by design; the supported command, ``trialbox selftest`` (RUNBOOK §4), ran ``orchestrator.selftest`` in the
container, which printed the report and recorded nothing, so the gate never saw a pass.

* ``python -m orchestrator.selftest`` records its report as the night's canary does: ``selftest.json`` (written whole),
  the audit (``by: trialbox selftest``), D-915's not-run rule (exit 2, nothing written).
* The running orchestrator's gate takes a newer ``selftest.json``: a pass at the command line opens it, no restart.
* An older result never replaces a newer one, and a pass older than a failed wake check does not clear it.

The 54 shipped canary cases; scripted models; no gateway, no container.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import selftest
from orchestrator.canary_gate import GATE, Gate

from tests.unit.test_canary_gate import CASES, Oracle, _orch
from tests.unit.test_canary_waits_for_models import Loading


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, detail: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
        self.events.append((event, detail or {}))
        return {}


@pytest.fixture
def box(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """What ``main`` reads in the orchestrator's container: its config, audit and model clients."""
    monkeypatch.setenv("TB_CANARY_GATE", "on")
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.delenv("TB_MODEL_SWAP", raising=False)
    monkeypatch.delenv("TB_GATEWAY_URL", raising=False)
    monkeypatch.setenv("TB_ORCH_DIR", str(tmp_path / "orch"))
    GATE.path = None
    audit = _Audit()
    models: dict[str, Any] = {"judge": Oracle("J"), "verifier": Oracle("V")}
    import orchestrator.app as orch_app
    import tb_common.audit_writer as aw
    import tb_common.config as config

    cfg = SimpleNamespace(env=SimpleNamespace(audit_path=str(tmp_path / "audit"), tz="UTC", data_dir=str(tmp_path)))
    monkeypatch.setattr(config, "get_config", lambda: cfg)
    monkeypatch.setattr(aw, "open_audit", lambda *a, **k: audit)
    monkeypatch.setattr(selftest, "LlmClient", SimpleNamespace(from_config=lambda a: models["judge"]))
    monkeypatch.setattr(orch_app, "verifier_client", lambda a: models["verifier"])
    return {"audit": audit, "models": models, "dir": tmp_path / "orch"}


def test_the_command_line_canary_is_the_gates_result_and_the_running_gate_takes_it(box: dict[str, Any]) -> None:
    running = Gate()  # the orchestrator's gate, in its own process
    box["dir"].mkdir(parents=True)
    running.configure(box["dir"])
    assert running.check()[1] == "none"
    assert selftest.main([]) == 0
    rep = json.loads((box["dir"] / "selftest.json").read_text(encoding="utf-8"))
    assert rep["ok"] and rep["pair"]["correct"] == 54
    [(event, detail)] = box["audit"].events
    assert event == "selftest.passed" and detail["by"] == "trialbox selftest"
    assert running.check()[:2] == (True, "ok")  # no restart, no console
    assert not list(box["dir"].glob(".selftest.json.*"))  # written whole, then moved into place


def test_a_command_line_canary_that_cannot_reach_a_model_is_not_run(box: dict[str, Any]) -> None:
    box["models"]["judge"], box["models"]["verifier"] = Loading("J"), Loading("V")
    assert selftest.main([]) == 2
    assert not (box["dir"] / "selftest.json").exists()
    assert [e for e, _ in box["audit"].events] == ["selftest.unreached"]


def test_a_failed_command_line_canary_closes_the_running_gate(box: dict[str, Any], tmp_path: Path) -> None:
    running = Gate()
    assert selftest.preflight(_orch(box["dir"], Oracle("J"), Oracle("V")), force=True)
    running.configure(box["dir"])
    assert running.check()[1] == "ok"
    one = next(c["id"] for c in CASES if c["expected"] == "pass")
    box["models"]["judge"], box["models"]["verifier"] = Oracle("J", {one}), Oracle("V", {one})
    assert selftest.main([]) == 1
    assert running.check()[:2] == (False, "failed")


def test_an_older_result_never_replaces_a_newer_one(box: dict[str, Any]) -> None:
    running = Gate()
    box["dir"].mkdir(parents=True)
    running.configure(box["dir"])
    assert selftest.main([]) == 0
    assert running.check()[1] == "ok"
    path = box["dir"] / "selftest.json"
    old = json.loads(path.read_text(encoding="utf-8")) | {"ok": False, "problems": ["old"]}
    old["at_epoch"] -= 3600
    path.write_text(json.dumps(old), encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert running.check()[1] == "ok"  # an older canary written later is not taken


def test_a_pass_older_than_a_failed_wake_check_does_not_reopen_the_gate(box: dict[str, Any]) -> None:
    running = Gate()
    box["dir"].mkdir(parents=True)
    running.configure(box["dir"])
    assert selftest.main([]) == 0
    path = box["dir"] / "selftest.json"
    rep = json.loads(path.read_text(encoding="utf-8"))
    running.record_wake("serving", "wake check 3/6 correct")
    assert running.check()[1] == "wake"
    rep["at_epoch"] = float(running.wake_failure["at_epoch"]) - 10  # type: ignore[index]
    running.at = rep["at_epoch"] - 10  # what this process last held is older still
    path.write_text(json.dumps(rep), encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert running.check()[1] == "wake"
    rep["at_epoch"] = float(running.wake_failure["at_epoch"]) + 10  # type: ignore[index]
    path.write_text(json.dumps(rep), encoding="utf-8")
    os.utime(path, (st.st_atime, st.st_mtime + 10))
    assert running.check()[:2] == (True, "ok")  # a pass after it does


def test_the_box_command_says_not_run_on_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tools.trialbox import selftest as box_selftest

    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    assert box_selftest.main(tmp_path, run=lambda cmd: 2) == 2
    assert "not run" in capsys.readouterr().out
