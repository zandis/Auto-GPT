"""H-114e (the review of #1472, 1472-2; the integrator's ruling 7139911468): when the console's time limit stops an
update, the result says what the update said last. Before, the result was ``TimeoutExpired: ... timed out after N
seconds`` with no lines, whether the rollback the limit's SIGTERM started had put the box back ("rolled back") or not
("ROLLBACK FAILED"). Now the summary is "the update's time limit (N s) was reached; it was stopped. Its last
output:", and the result's lines are the update's last 20, each scrubbed. Every other failure is as before.

Each case runs the console's runner (``run_one``) through the real ``procgroup`` path, on a stand-in
``tools/apply_update.sh`` that rolls back on the limit's SIGTERM and says how that went."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import ops as tb_ops

SECRET = "Zq8vXk2mPw7rLs4n"  # a made-up value, secret-shaped by its setting's name
SUMMARY = "_LimitReached: the update's time limit (1 s) was reached; it was stopped. Its last output:"
OUTCOMES = {
    "rolled back": "the box is back on the release before B2",
    "ROLLBACK FAILED (the marker stays: tools/apply_update.sh status)": "the box may be between the two releases: do "
    "not use it",
}


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> dict[str, Any]:
    root, deploy = tmp_path / "root", tmp_path / "deploy"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "apply_update.sh").write_text(script, encoding="utf-8")
    incoming = deploy / "updates" / "incoming"
    incoming.mkdir(parents=True)
    (incoming / "trialbox-2026.11-2.tar").write_bytes(b"stand-in bundle")
    monkeypatch.setattr(tb_ops, "ROOT", root)
    monkeypatch.setattr(tb_ops.OpsRunner, "apply_limit", lambda self: 1)
    runner = tb_ops.OpsRunner(tb_ops.Box("compose", deploy), tb_ops.OpsDir(tmp_path / "ops"))
    req = {"id": "20261124T180000Z-a1b2c3", "action": "update_apply", "by": "admin",
           "args": {"bundle": "trialbox-2026.11-2.tar"}}  # fmt: skip
    return runner.run_one(req)


def _rollback_on_term(outcome: str, state: str, reason: str) -> str:
    """The update's rollback on the TERM: 30 lines of progress and a secret-shaped line on stderr, then its last
    word on stdout, as ``tools/trialbox/update.py`` prints them."""
    said = f"update FAILED: update B2 failed ({reason}); {outcome}; {state}"
    return (f"trap 'i=0; while [ $i -lt 30 ]; do echo \"update: put back, step $i\" >&2; i=$((i+1)); done; "
            f"echo \"update: TB_DB_PASSWORD={SECRET}\" >&2; echo \"{said}\"; exit 1' TERM\n"
            "echo \"update B2: started\"\nwhile :; do sleep 0.1; done\n")  # fmt: skip


@pytest.mark.parametrize("outcome", list(OUTCOMES))
@pytest.mark.parametrize("reason", ["a check failed", "the health check said: " + "the service did not answer; " * 24])
def test_the_rollback_s_outcome_reaches_the_console_s_result_after_the_limit(tmp_path: Path,
                                                                             monkeypatch: pytest.MonkeyPatch,
                                                                             outcome: str, reason: str) -> None:  # fmt: skip
    """THE INVARIANT of H-114e: after the limit, the result's summary names the limit, and its lines end with what
    the rollback said: "rolled back" or "ROLLBACK FAILED" and the box's state. It holds when the update's last
    line is far over the 300 characters a summary or a result's line keeps (the long reason)."""
    res = _run(tmp_path, monkeypatch, _rollback_on_term(outcome, OUTCOMES[outcome], reason))
    assert not res["ok"] and res["state"] == "failed", res
    assert res["summary"] == SUMMARY, res["summary"]
    lines = res["lines"]
    assert 0 < len(lines) <= tb_ops.LIMIT_LINES and all(len(ln) <= 300 for ln in lines), lines
    assert lines[-1].startswith("update FAILED: update B2 failed ("), lines[-1]
    assert lines[-1].endswith(f"; {outcome}; {OUTCOMES[outcome]}"), lines[-1]
    if len(reason) > 300:
        assert len(f"update FAILED: update B2 failed ({reason}); {outcome}") > 300  # the case the cut is for
    assert "update: put back, step 29" in lines, lines  # the progress before it, the newest kept


def test_a_secret_shaped_value_in_the_update_s_output_does_not_reach_the_result(tmp_path: Path,
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """Each line kept goes through ``tb_common.logging.redact`` (the integrator's ruling): the planted value of a
    password setting is not in the result's file, and its line says ``[SECRET]`` in its place."""
    res = _run(tmp_path, monkeypatch, _rollback_on_term("rolled back", OUTCOMES["rolled back"], "a check failed"))
    stored = (tmp_path / "ops" / "results" / "20261124T180000Z-a1b2c3.json").read_text(encoding="utf-8")
    assert SECRET not in stored and SECRET not in json.dumps(res)
    assert "update: TB_DB_PASSWORD=[SECRET]" in res["lines"], res["lines"]


def test_every_other_failure_is_as_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An update that ends with an error inside its limit: ``OpsFailed`` with the exit code and its output in the
    summary, no lines (the result of before, unchanged)."""
    res = _run(tmp_path, monkeypatch, 'echo "update REFUSED: a stand-in reason"\nexit 3\n')
    assert not res["ok"] and res["lines"] == [], res
    assert res["summary"] == "OpsFailed: exit 3: update REFUSED: a stand-in reason", res["summary"]
