"""H-47's optional stage: the verifier's stored calls sent again with and without H-49's server flag
(tools/verifier_replay.py), and the one-off override that recreates only the verifier with the flag
(tools/ballast48.py verifier-flag). No server, no card, no Docker: a stand-in post and a stand-in runner, and a
stand-in stored set of made-up public-style text."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import ballast48 as b48
from tools import dgpu48
from tools import verifier_replay as vr
from tools.public_accuracy import waste
from tools.public_accuracy.replay import Refused

pytestmark = pytest.mark.nodb

GOOD = json.dumps({"verdict": "pass", "reason": "r", "quote": "q", "quote_date": None, "confidence": 0.9})
LOOP = '{"verdict": "fail", "reason": "x"' + " " * 300 + "\n" * 300


def _trace(alias: str, prompt: str, output: Any, span: str = "chat") -> dict[str, Any]:
    return {"span": span, "attributes": {"tb.model_alias": alias, "tb.prompt": prompt},
            "prompt": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], "output": output}  # fmt: skip


def _stored(tmp: Path) -> Path:
    d = tmp / "run"
    (d / "built" / "gold").mkdir(parents=True)
    (d / "work").mkdir()
    (d / "built" / "gold" / "ids.json").write_text(json.dumps({"set": "tcga"}))
    traces = [_trace("v-verifier", "judge@5", GOOD), _trace("v-verifier", "judge@5", LOOP),
              _trace("v-verifier", "judge@5", GOOD), _trace("j-workhorse", "judge@5", GOOD),
              _trace("v-verifier", "judge@4", GOOD), _trace("v-verifier", "judge@5", None, span="refusal")]  # fmt: skip
    (d / "work" / "raw-traces.json").write_text(json.dumps({"traces": traces}))
    return d


def test_only_the_verifiers_answered_judge5_calls_are_sent(tmp_path: Path) -> None:
    calls = vr.load_calls(_stored(tmp_path), tmp_path / "scratch")
    assert len(calls) == 3
    assert sum(vr._flagged(c) for c in calls) == 1
    with pytest.raises(Refused, match="no set 'trec'"):
        vr.load_calls(_stored(tmp_path / "b"), tmp_path / "s2", "trec")


def test_the_body_is_the_box_clients(tmp_path: Path) -> None:
    schema, cap = waste.schema_of("judge@5")
    assert schema is not None and cap == 1024
    b = vr.body(vr.load_calls(_stored(tmp_path), tmp_path / "s")[0], schema, cap, vr.temperature_of("judge@5"))
    assert b["model"] == vr.SERVED == dgpu48.PIN_BUILD["verifier"][2]
    assert b["temperature"] == 0.0 and b["max_tokens"] == 1024
    assert b["response_format"]["type"] == "json_schema" and b["response_format"]["json_schema"]["strict"] is True
    assert [m["role"] for m in b["messages"]] == ["system", "user"]


def _server(answers: list[str]) -> Any:
    seen: list[dict[str, Any]] = []

    def post(url: str, payload: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
        seen.append({"url": url, "key": key, "payload": payload})
        text = answers[len(seen) - 1]
        if text == "ERR":
            raise TimeoutError("stand-in")
        return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"completion_tokens": 9}}

    post.seen = seen  # type: ignore[attr-defined]
    return post


def test_run_writes_a_stored_set_waste_reads_and_no_key(tmp_path: Path) -> None:
    calls = vr.load_calls(_stored(tmp_path), tmp_path / "s")
    post = _server([GOOD, LOOP, "ERR"])
    rep = vr.replay(calls, "http://v:8000/v1", "secret-key", tmp_path / "out", "off", post=post, say=lambda _: None)
    assert rep["calls"] == 3 and rep["errors"] == 1
    assert post.seen[0]["key"] == "secret-key"
    for f in (tmp_path / "out").rglob("*.json"):
        assert "secret-key" not in f.read_text()
    res = waste.waste([tmp_path / "out" / "off"], tmp_path / "w")
    v = res["sets"]["tcga-off"]["by_model"]["v-verifier"]
    assert v["calls"] == 3 and v["refused"] == 1 and v["flagged"] == 1


def test_compare_counts_flagged_seconds_and_differing_verdicts(tmp_path: Path) -> None:
    calls = vr.load_calls(_stored(tmp_path), tmp_path / "s")
    fail = GOOD.replace('"pass"', '"fail"')
    vr.replay(calls, "u", "k", tmp_path / "o", "off", post=_server([GOOD, LOOP, GOOD]), say=lambda _: None)
    vr.replay(calls, "u", "k", tmp_path / "o", "on", post=_server([GOOD, fail, fail]), say=lambda _: None)
    res = vr.compare(tmp_path / "o" / "off", tmp_path / "o" / "on")
    assert res["labels"]["off"]["flagged"] == 1 and res["labels"]["on"]["flagged"] == 0
    assert res["unflagged_in_both"] == 2 and res["verdicts_differ"] == 1 and res["differ_at"] == [2]
    assert res["labels"]["on"]["seconds_mean"] is not None
    vr.replay(calls[:2], "u", "k", tmp_path / "o", "short", post=_server([GOOD, GOOD]), say=lambda _: None)
    with pytest.raises(Refused, match="not the same call set"):
        vr.compare(tmp_path / "o" / "off", tmp_path / "o" / "short")


def test_the_flag_override_restates_the_overlays_verifier_command(tmp_path: Path) -> None:
    f = b48.flag_override(tmp_path)
    assert f.parent == tmp_path  # never under deploy/
    cmd = yaml.safe_load(f.read_text())["services"]["llm-verifier"]["command"]
    overlay = yaml.safe_load((dgpu48.ROOT / dgpu48.OVERLAY).read_text())["services"]["llm-verifier"]["command"]
    assert cmd == [*overlay, b48.FLAG] and b48.FLAG == vr.FLAG
    assert json.loads(b48.FLAG.split("=", 1)[1]) == {"backend": "xgrammar", "disable_any_whitespace": True}


def test_verifier_flag_recreates_only_the_verifier_at_the_kept_settings(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Any]] = []

    def run(cmd: list[str], timeout: int, env: Any = None, stream: bool = False) -> tuple[int, str, str]:
        calls.append((list(cmd), env))
        return 0, "", ""

    base = ["docker", "compose", "--project-directory", "deploy", "-f", "a.yml", "--profile", "gpu"]
    env = {"VERIFIER_GPU_MEM_UTIL": "0.135"}
    (tmp_path / "down.json").write_text(json.dumps({"cmd": [*base, "rm", "-sf", "llm-service", "llm-verifier"],
                                                    "env": env}))  # fmt: skip
    assert b48.verifier_flag(tmp_path, run) == 0
    cmd, sent = calls[-1]
    assert cmd[: len(base)] == base and cmd[len(base)] == "-f" and cmd[len(base) + 1].endswith("verifier-flag.yml")
    assert cmd[-3:] == ["--no-deps", "--force-recreate", "llm-verifier"] and sent == env
    assert b48.verifier_flag(tmp_path, run, on=False) == 0
    assert "-f" not in calls[-1][0][len(base) :] and calls[-1][0][-1] == "llm-verifier"
    assert b48.verifier_flag(tmp_path / "none", run) == 2
