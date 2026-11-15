"""BOX-QUALIFY (D-737), lane G's blocker 5: ``qualify`` on a box needs ``--model-dir``, ``--server-log`` and
``--audit-dir``, and nothing on the box supplied them.

``trialbox eval qualify --box`` asks the running box, through ``docker compose ps -q`` and ``docker inspect``, for
what it really serves: each model server's weight folder (its ``/models`` mount and its ``--model=`` argument), its
log file (the json-file log, ``.LogPath``) and the gateway's audit folder (the source of its ``/data/audit`` mount).
An option the operator gave is kept; what the box cannot say is named, never guessed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import box_qualify as bq

pytestmark = pytest.mark.nodb


def _server(model: str, log: str) -> dict[str, Any]:
    return {"Args": ["--model=/models/" + model, "--served-model-name=x"], "LogPath": log,
            "Mounts": [{"Source": "/opt/trialbox/deploy/models", "Destination": "/models"}]}  # fmt: skip


GATEWAY = {"Args": [], "LogPath": "/var/lib/docker/containers/g/g-json.log",
           "Mounts": [{"Source": "/var/lib/docker/volumes/trialbox_audit-data/_data", "Destination": "/data/audit"},
                      {"Source": "/x", "Destination": "/data/traces"}]}  # fmt: skip


class FakeBox:
    def __init__(self, containers: dict[str, dict[str, Any]]) -> None:
        self.containers = containers
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], **_: Any) -> str:
        self.calls.append(cmd)
        if cmd[-3:-1] == ["ps", "-q"]:
            return f"cid-{cmd[-1]}\n" if cmd[-1] in self.containers else ""
        if cmd[-2] == "inspect":
            return json.dumps([self.containers[cmd[-1].removeprefix("cid-")]])
        raise AssertionError(cmd)


PAIR = {
    "llm-service": _server("gemma-4-26b-a4b-it-4bit", "/var/lib/docker/containers/j/j-json.log"),
    "llm-verifier": _server("qwen3.5-9b-4bit", "/var/lib/docker/containers/v/v-json.log"),
    "gateway": GATEWAY,
}


def test_a_pair_box_gives_both_weight_folders_both_logs_and_the_audit_folder(tmp_path: Path) -> None:
    args, problems = bq.discover(FakeBox(PAIR).run, ["docker", "compose"], ["docker"])
    assert problems == []
    assert args == [
        "--model-dir", "judge=/opt/trialbox/deploy/models/gemma-4-26b-a4b-it-4bit",
        "--server-log", "/var/lib/docker/containers/j/j-json.log",
        "--model-dir", "verifier=/opt/trialbox/deploy/models/qwen3.5-9b-4bit",
        "--server-log", "/var/lib/docker/containers/v/v-json.log",
        "--audit-dir", "/var/lib/docker/volumes/trialbox_audit-data/_data",
    ]  # fmt: skip


def test_a_one_model_box_gives_the_judge_only_and_says_so() -> None:
    one = {k: v for k, v in PAIR.items() if k != "llm-verifier"}
    args, problems = bq.discover(FakeBox(one).run, ["docker", "compose"], ["docker"])
    assert "judge=/opt/trialbox/deploy/models/gemma-4-26b-a4b-it-4bit" in args and "verifier=" not in " ".join(args)
    assert problems == ["llm-verifier is not running: no verifier weight folder or log"]


def test_a_box_whose_gateway_is_down_names_the_missing_audit_folder() -> None:
    args, problems = bq.discover(FakeBox({k: v for k, v in PAIR.items() if k != "gateway"}).run, ["dc"], ["d"])
    assert "--audit-dir" not in args and any("gateway is not running" in p for p in problems)


def test_a_server_without_a_models_mount_is_named_not_guessed() -> None:
    odd = {**PAIR, "llm-service": {**PAIR["llm-service"], "Mounts": []}}
    args, problems = bq.discover(FakeBox(odd).run, ["dc"], ["d"])
    assert not any(a.startswith("judge=") for a in args)
    assert any("llm-service" in p and "/models" in p for p in problems)


def test_options_the_operator_gave_are_kept_and_the_rest_filled() -> None:
    filled = bq.fill(["--profile", "rtxpro6000", "--model-dir", "judge=/mine"], PAIR_ARGS)
    assert filled.count("--model-dir") == 2 and "judge=/mine" in filled and "verifier=/v" in filled
    assert "judge=/j" not in filled and filled[:2] == ["--profile", "rtxpro6000"]
    assert "--audit-dir" in filled and "--server-log" in filled
    given = bq.fill(["--server-log", "/my.log", "--audit-dir", "/a"], PAIR_ARGS)
    assert given.count("--server-log") == 1 and given.count("--audit-dir") == 1


PAIR_ARGS = ["--model-dir", "judge=/j", "--server-log", "/jl", "--model-dir", "verifier=/v", "--server-log", "/vl",
             "--audit-dir", "/au"]  # fmt: skip


def test_the_cli_takes_box_and_hands_the_filled_options_to_qualify(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import qualify
    from tools.trialbox.__main__ import main as cli

    seen: list[list[str]] = []

    def fake(argv: list[str] | None = None) -> int:
        seen.append(list(argv or []))
        return 0

    monkeypatch.setattr(qualify, "main", fake)
    monkeypatch.setattr(bq, "discover", lambda run, compose, docker: (PAIR_ARGS, []))
    assert cli(["eval", "qualify", "--box", "--profile", "rtxpro6000"]) == 0
    assert seen == [["--profile", "rtxpro6000", *PAIR_ARGS]]


def test_what_the_box_cannot_say_is_printed_and_qualify_still_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools import qualify

    monkeypatch.setattr(qualify, "main", lambda argv=None: 0)
    monkeypatch.setattr(bq, "discover", lambda run, compose, docker: ([], ["gateway is not running: no audit folder"]))
    assert bq.main(["--profile", "rtxpro6000"]) == 0
    assert "gateway is not running" in capsys.readouterr().err
