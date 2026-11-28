"""Lane G (HOLISTIC-2 G1, G2): the label tokens' log-probabilities through the gateway, and P(met) from them.

* G1: ``logprobs`` and ``top_logprobs`` go upstream, and a call that asks for them is never answered from a reply
  cached without them.
* G2: the slot reader, the temperature, P(met) and the calibration record (aggregates only).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from tb_common import label_p

from tests.unit.test_gateway import H, _gw, _ir_body, _judge_body


# ------------------------------------------------------------------------------------------------ G1: the gateway
def _capture(sent: list[dict[str, Any]]) -> httpx.Client:
    def capture(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        r = TestClient(stub).post("/v1/chat/completions", content=req.content, headers=dict(req.headers))
        return httpx.Response(r.status_code, json=r.json())

    return httpx.Client(transport=httpx.MockTransport(capture))


def test_logprobs_go_upstream(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []
    gw = _gw(tmp_path, http=_capture(sent))
    res = gw.chat(H(), {**_judge_body(), "logprobs": True, "top_logprobs": 20})
    assert res.status == 200 and sent[0]["logprobs"] is True and sent[0]["top_logprobs"] == 20


def test_a_call_asking_for_logprobs_is_not_answered_from_a_cache_without_them(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []
    gw = _gw(tmp_path, http=_capture(sent))
    h = H(Caller="criteria-compiler", Role="extract_criteria", Purpose="protocol_ingest", Prompt="ir_extract@2")
    a, b = gw.chat(h, _ir_body()), gw.chat(h, _ir_body())
    assert (a.body["tb"]["cache"], b.body["tb"]["cache"], len(sent)) == ("miss", "hit", 1)
    c = gw.chat(h, {**_ir_body(), "logprobs": True, "top_logprobs": 5})
    assert c.body["tb"]["cache"] == "miss" and len(sent) == 2 and sent[1]["logprobs"] is True


# ------------------------------------------------------------------------------------------------ G2: label P
def _tok(text: str, alts: dict[str, float] | None = None) -> dict[str, Any]:
    alts = alts or {text: 1.0}
    return {"token": text, "logprob": math.log(alts.get(text, 1e-6)),
            "top_logprobs": [{"token": t, "logprob": math.log(p)} for t, p in alts.items()]}  # fmt: skip


def test_each_verdict_slot_is_read_in_order_and_renormalised() -> None:
    tokens = [
        _tok('{"answers":[{"id":"A","verdict":"'),
        _tok("pass", {"pass": 0.6, "fail": 0.2, "un": 0.1, "Pass": 0.1}),  # "Pass" spells no label
        _tok('","quote":null},{"id":"B","verdict":'),
        _tok('"unknown', {'"unknown': 0.5, '"fail': 0.3, '"p': 0.2}),  # the opening quote inside the token
        _tok('"}]}'),
    ]
    a, b = label_p.slots(tokens)
    assert a == pytest.approx({"pass": 0.6 / 0.9, "fail": 0.2 / 0.9, "unknown": 0.1 / 0.9})
    assert b == pytest.approx({"pass": 0.2, "fail": 0.3, "unknown": 0.5})


def test_a_slot_with_no_label_alternative_is_none_and_no_logprobs_is_no_slot() -> None:
    assert label_p.slots([_tok('{"verdict":"'), _tok("maybe")]) == [None]
    assert label_p.slots([]) == []


def test_p_met_is_inside_zero_and_one_an_abstention_is_one_half_and_a_repeat_is_identical() -> None:
    sure = {"pass": 1.0, "fail": 0.0, "unknown": 0.0}
    assert 0.99 < label_p.p_met(sure) < 1 and 0 < label_p.p_met({"fail": 1.0}) < 0.01
    assert label_p.p_met({"unknown": 1.0}) == 0.5
    p3 = {"pass": 0.7, "fail": 0.2, "unknown": 0.1}
    assert json.dumps(label_p.p_met(p3, 3.0)) == json.dumps(label_p.p_met(dict(p3), 3.0))
    assert abs(label_p.p_met(p3, 5.0) - 0.5) < abs(label_p.p_met(p3) - 0.5)  # a higher temperature softens


def test_an_over_confident_judge_gets_a_temperature_above_one_and_a_smaller_ece() -> None:
    rows = [({"pass": 0.98, "fail": 0.01, "unknown": 0.01}, i % 10 < 7) for i in range(200)]  # right 70 % of the time
    t, _ = label_p.fit(rows)
    assert t > 1
    rec = label_p.record(name="synthetic", ids=[str(i) for i in range(200)], rows=rows, prompt="judge_chart@1",
                         pin="sha256:test", date="2026-11-28")  # fmt: skip
    assert rec["temperature"] == t and rec["ece"] < rec["ece_raw"] and rec["rows"] == 200
    assert set(rec) == {"kind", "set", "set_sha", "rows", "temperature", "unknown_weight", "ece_raw", "ece", "prompt",
                        "pin", "date"}  # fmt: skip
    assert label_p.set_sha(["b", "a"]) == label_p.set_sha(["a", "b"])
    assert label_p.record_id(rec) == label_p.record_id(dict(rec))


def test_where_the_labels_read_an_abstention_as_not_met_the_fitted_share_of_unknown_goes_to_zero() -> None:
    abstains = {"pass": 0.02, "fail": 0.03, "unknown": 0.95}
    says_yes = {"pass": 0.9, "fail": 0.05, "unknown": 0.05}
    rows = [(abstains, False)] * 60 + [(says_yes, True)] * 40
    t, u = label_p.fit(rows)
    assert u == 0.0 and label_p.p_met(abstains, t, u) < 0.1
    assert label_p.p_met(abstains) == pytest.approx(0.5, abs=0.05)  # with no fit an abstention says nothing either way
