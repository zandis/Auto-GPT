"""The strict vLLM stand-in of the box-install rehearsal (D-177, ``tools/vllm_standin.py``)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from tools import vllm_standin as vs

KEY = "rehearsal-key-0123456789"
NAME = "gemma-4-26b-a4b-it"
JUDGE_INPUT = {
    "criterion_text": "Age >= 18 years",
    "note_question": "Is the patient an adult?",
    "index_date": "2026-10-05",
    "excerpts": [{"date": "2026-10-01", "note_type": "progress", "text": "Synthetic note: 54-year-old outpatient."}],
}


def _serve(argv: list[str], env: dict[str, str] | None = None) -> tuple[ThreadingHTTPServer, str]:
    s, _, _ = vs.build(argv, env or {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), vs.make_handler(s))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture()
def base() -> Iterator[str]:
    srv, url = _serve(["--model=/models/gemma-4-26b-a4b-it-4bit", f"--served-model-name={NAME}", "--api-key", KEY,
                       "--max-model-len=32768", "--enforce-eager", "--max-num-seqs", "16",
                       '--limit-mm-per-prompt={"image":0,"audio":0,"video":0}'])  # fmt: skip
    yield url
    srv.shutdown()


def _call(url: str, body: dict[str, Any] | None = None, key: str | None = KEY, **headers: str) -> tuple[int, Any]:
    h = {"Content-Type": "application/json", **headers}
    if key is not None:
        h["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _chat(model: str) -> dict[str, Any]:
    user = f"Judge this.\n```json\n{json.dumps(JUDGE_INPUT)}\n```"
    return {"model": model, "messages": [{"role": "user", "content": user}], "temperature": 0}


def test_health_is_open_and_models_need_the_key(base: str) -> None:
    assert _call(f"{base}/health", key=None)[0] == 200
    assert _call(f"{base}/v1/models", key=None)[0] == 401
    assert _call(f"{base}/v1/models", key="wrong")[0] == 401
    status, doc = _call(f"{base}/v1/models")
    assert status == 200 and [m["id"] for m in doc["data"]] == [NAME]


def test_exact_served_name_only(base: str) -> None:
    for wrong in ("gemma-4-26b-a4b-it-4bit", "GEMMA-4-26B-A4B-IT", "j-workhorse", "", "gemma-4-26b-a4b-it "):
        status, doc = _call(f"{base}/v1/chat/completions", _chat(wrong), **{"X-TB-Prompt-Id": "judge"})
        assert status == 404 and doc["type"] == "NotFoundError" and "does not exist" in doc["message"]
    status, doc = _call(f"{base}/v1/completions", {"model": "other", "prompt": "x"})
    assert status == 404


def test_answers_the_served_name_with_the_stub_answer(base: str) -> None:
    status, doc = _call(f"{base}/v1/chat/completions", _chat(NAME), **{"X-TB-Prompt-Id": "judge"})
    assert status == 200 and doc["model"] == NAME
    answer = json.loads(doc["choices"][0]["message"]["content"])
    assert "verdict" in answer


def test_calls_without_the_key_are_refused_before_the_name(base: str) -> None:
    assert _call(f"{base}/v1/chat/completions", _chat(NAME), key=None, **{"X-TB-Prompt-Id": "judge"})[0] == 401
    assert _call(f"{base}/v1/chat/completions", _chat("other"), key=None)[0] == 401


def test_unknown_prompt_and_bad_body_are_400(base: str) -> None:
    assert _call(f"{base}/v1/chat/completions", _chat(NAME), **{"X-TB-Prompt-Id": "nope"})[0] == 400
    body = {"model": NAME, "messages": [{"role": "user", "content": "no block"}]}
    assert _call(f"{base}/v1/chat/completions", body, **{"X-TB-Prompt-Id": "judge"})[0] == 400


def test_stats_count_every_answer(base: str) -> None:
    _call(f"{base}/v1/models", key=None)
    _call(f"{base}/v1/chat/completions", _chat("other"), **{"X-TB-Prompt-Id": "judge"})
    _call(f"{base}/v1/chat/completions", _chat(NAME), **{"X-TB-Prompt-Id": "judge"})
    assert _call(f"{base}/standin/stats", key=None)[0] == 401
    status, doc = _call(f"{base}/standin/stats")
    assert status == 200 and doc["served"] == [NAME]
    assert doc["counts"]["401"] == 2 and doc["counts"]["404"] == 1 and doc["counts"]["200"] == 1


def test_refuses_to_start_without_a_key(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    assert vs.main([f"--served-model-name={NAME}"]) == 2
    assert "no API key" in capsys.readouterr().err
    with pytest.raises(ValueError, match="no API key"):
        vs.build([f"--served-model-name={NAME}", "--api-key="], {})


def test_key_from_vllm_env_and_name_from_model_path() -> None:
    s, _, ignored = vs.build(["--model=/models/qwen3.5-9b-4bit/", "--enforce-eager", "--max-model-len=8192"],
                             {"VLLM_API_KEY": "k"})  # fmt: skip
    assert s.served == ["qwen3.5-9b-4bit"] and s.key == "k" and "--enforce-eager" in ignored
    s, _, _ = vs.build(["--served-model-name", "a", "b", "--api-key", "x"], {"VLLM_API_KEY": "ignored"})
    assert s.served == ["a", "b"] and s.key == "x"


def test_no_abbreviated_flags() -> None:
    a, ignored = vs.parse(["--served", "x", "--api-key", KEY])  # --served is not --served-model-name
    assert a.served_model_name == [] and "--served" in ignored
    with pytest.raises(ValueError, match="no served model name"):
        vs.build(["--served", "x", "--api-key", KEY], {})


def test_loading_delay_answers_503_until_ready() -> None:
    srv, url = _serve([f"--served-model-name={NAME}", "--api-key", KEY, "--load-delay", "60"])
    try:
        assert _call(f"{url}/health", key=None)[0] == 503
        assert _call(f"{url}/v1/models")[0] == 503
    finally:
        srv.shutdown()
