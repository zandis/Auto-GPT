"""H-47's optional stage (H-49's verifier flag): ``tools/ballast48.py verifier-flag`` recreates only the verifier of a
kept run with ``--structured-outputs-config`` (``disable_any_whitespace``) from a one-off compose file in the run's
folder, and ``canary-diff`` compares the verifier's canary answers and speed in two reports. No server, no card, no
Docker: a stand-in runner and stand-in canary reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import ballast48 as b48
from tools import dgpu48

pytestmark = pytest.mark.nodb


def test_the_flag_override_restates_the_overlays_verifier_command(tmp_path: Path) -> None:
    f = b48.flag_override(tmp_path)
    assert f.parent == tmp_path  # never under deploy/
    cmd = yaml.safe_load(f.read_text())["services"]["llm-verifier"]["command"]
    overlay = yaml.safe_load((dgpu48.ROOT / dgpu48.OVERLAY).read_text())["services"]["llm-verifier"]["command"]
    assert cmd == [*overlay, b48.FLAG]
    assert json.loads(b48.FLAG.split("=", 1)[1]) == {"backend": "xgrammar", "disable_any_whitespace": True}
    assert "llm-service" not in yaml.safe_load(f.read_text())["services"]  # the judge is never touched


def test_verifier_flag_recreates_only_the_verifier_at_the_kept_settings(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Any]] = []

    def run(cmd: list[str], timeout: int, env: Any = None, stream: bool = False) -> tuple[int, str, str]:
        calls.append((list(cmd), env))
        return 0, "", ""

    base = ["docker", "compose", "--project-directory", "deploy", "-f", "a.yml", "--profile", "gpu"]
    env = {"VERIFIER_GPU_MEM_UTIL": "0.135"}
    down = {"cmd": [*base, "rm", "-sf", "llm-service", "llm-verifier"], "env": env}
    (tmp_path / "down.json").write_text(json.dumps(down))
    assert b48.verifier_flag(tmp_path, run) == 0
    cmd, sent = calls[-1]
    assert cmd[: len(base)] == base and cmd[len(base)] == "-f" and cmd[len(base) + 1].endswith("verifier-flag.yml")
    assert cmd[-3:] == ["--no-deps", "--force-recreate", "llm-verifier"] and sent == env
    assert b48.verifier_flag(tmp_path, run, on=False) == 0
    assert "-f" not in calls[-1][0][len(base) :] and calls[-1][0][-1] == "llm-verifier"
    assert b48.verifier_flag(tmp_path / "none", run) == 2


def _canary(path: Path, seconds: float, wrong: list[dict[str, str]], answered: int = 54) -> Path:
    models = [
        {"role": "judge", "cases": 54, "answered": 54, "correct": 53, "seconds": 100.0, "wrong": []},
        {"role": "verifier", "cases": 54, "answered": answered, "correct": answered - len(wrong), "flips": 0,
         "seconds": seconds, "wrong": wrong},
    ]  # fmt: skip
    path.write_text(json.dumps({"ok": True, "models": models}))
    return path


def test_canary_diff_counts_differing_verdicts_and_seconds_per_call(tmp_path: Path) -> None:
    off = _canary(tmp_path / "off.json", 54.0, [{"id": "c1", "expected": "pass", "got": "fail"},
                                                 {"id": "c2", "expected": "fail", "got": "unknown"}])  # fmt: skip
    on = _canary(tmp_path / "on.json", 27.0, [{"id": "c2", "expected": "fail", "got": "pass"},
                                               {"id": "c3", "expected": "pass", "got": "unknown"}])  # fmt: skip
    res = b48.canary_diff(off, on)
    assert res["verdicts_differ"] == 3 and res["differ_ids"] == ["c1", "c2", "c3"] and res["exact"] is True
    assert res["runs"]["a"]["seconds_per_call"] == 1.0 and res["runs"]["b"]["seconds_per_call"] == 0.5
    assert b48.canary_diff(off, off)["verdicts_differ"] == 0
    short = _canary(tmp_path / "short.json", 10.0, [], answered=50)
    assert b48.canary_diff(off, short)["exact"] is False  # an unanswered case's verdict is not in the report
    (tmp_path / "judge-only.json").write_text(json.dumps({"models": [{"role": "judge"}]}))
    with pytest.raises(b48.Refused, match="no verifier"):
        b48.canary_diff(off, tmp_path / "judge-only.json")
