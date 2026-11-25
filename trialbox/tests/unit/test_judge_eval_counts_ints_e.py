"""INT-S-E: the evaluation tool reads a judge reply the way the product path does, and counts what it sets aside.

A stand-in gateway (``httpx.MockTransport``, no model) answers each call with a scripted reply. Synthetic data only.

* a reply with the sentinel date is read by ``tb_common.llm.no_sentinel_date`` (the product's own function), then
  counted as a placeholder reply; it is not a reply outside the schema;
* a reply outside the schema is counted per criterion and per rule broken, never mapped silently;
* the exit code logic for agreement is unchanged;
* ``--gateway-url`` with no ``--model`` (``upstream_down``) or a name not on the route (``class_route_mismatch``)
  ends in one plain line each, which says what ``--model`` must be;
* the output file records per call the finish reason and the token counts the gateway returned.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tools import judge_eval

ROOT = Path(__file__).resolve().parents[2]
ALIAS = "build-x"

SENTINEL = {"verdict": "unknown", "certainty": None, "experiencer": None, "time": None, "reason": "none found",
            "quote": "unknown", "quote_date": "0000-01-01", "confidence": 1.0}  # fmt: skip
CLEAN_UNKNOWN = {**SENTINEL, "quote": None, "quote_date": None, "confidence": 0}
BAD_ENUM = {**SENTINEL, "verdict": "PASS!", "quote": None, "quote_date": None, "confidence": 0.9}


def _items(n: int) -> list[dict[str, Any]]:
    rows = (ROOT / "eval" / "qualification" / "judge_set.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in rows[:n]]


def _write_set(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    p = tmp_path / "set.jsonl"
    p.write_text("\n".join(json.dumps(i) for i in items) + "\n", encoding="utf-8")
    return p


def _gateway(
    replies: list[Any], *, finish: str = "stop", status: int = 200, error: dict[str, Any] | None = None
) -> tuple[httpx.MockTransport, list[dict[str, Any]]]:
    """A stand-in gateway: answers the i-th chat call with replies[i], or a refusal when ``error`` is given."""
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": ALIAS, "context_length": 8192}]})
        body = json.loads(req.content)
        seen.append(body)
        if error is not None:
            return httpx.Response(status, json={"error": {"type": "tb_refusal", **error}})
        reply = replies[len(seen) - 1]
        return httpx.Response(200, json={
            "model": "served-name",
            "choices": [{"message": {"content": json.dumps(reply)}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100 + len(seen), "completion_tokens": 7},
            "tb": {"alias": body.get("model") or ALIAS, "call_id": f"c{len(seen)}", "build_sha": "b"},
        })  # fmt: skip

    return httpx.MockTransport(handler), seen


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    import tb_llm

    real = tb_llm.GatewayClient
    monkeypatch.setattr(
        tb_llm,
        "GatewayClient",
        lambda url, caller, **kw: real(url, caller, http=httpx.Client(transport=transport), **kw),
    )


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replies: list[Any], capsys: Any, *extra: str
) -> dict[str, Any]:
    transport, _ = _gateway(replies)
    _patch_client(monkeypatch, transport)
    items = _items(len(replies))
    rc = judge_eval.main(["--set", str(_write_set(tmp_path, items)), "--gateway-url", "http://gw/v1",
                          "--model", ALIAS, "--min", "0", *extra])  # fmt: skip
    assert rc == 0
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return out


def test_the_sentinel_reply_is_read_like_the_product_and_counted_as_a_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    report = _run(tmp_path, monkeypatch, [SENTINEL, CLEAN_UNKNOWN], capsys)
    assert report["schema_invalid"] == 0  # the product turns the date into null before the schema reads it
    assert report["placeholder"] == 1  # only the first: an unknown with a quote, a sentinel date and a confidence
    assert report["placeholder_kinds"] == {"confidence": 1, "quote": 1, "sentinel_date": 1}


def test_a_reply_outside_the_schema_is_counted_per_criterion_and_per_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    items = _items(2)
    report = _run(tmp_path, monkeypatch, [BAD_ENUM, CLEAN_UNKNOWN], capsys)
    assert report["schema_invalid"] == 1 and report["placeholder"] == 0
    assert report["schema_invalid_rules"] == {"verdict: enum": 1}
    cid = items[0]["criterion_id"]
    assert report["per_criterion_counts"][cid]["schema_invalid"] >= 1


def test_a_reply_that_is_not_json_is_counted_as_outside_the_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    report = _run(tmp_path, monkeypatch, ["not an object"], capsys)
    assert report["schema_invalid"] == 1 and report["placeholder"] == 0


def test_the_agreement_exit_code_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transport, _ = _gateway([BAD_ENUM, BAD_ENUM, BAD_ENUM])
    _patch_client(monkeypatch, transport)
    p = _write_set(tmp_path, _items(3))
    args = ["--set", str(p), "--gateway-url", "http://gw/v1", "--model", ALIAS]
    assert judge_eval.main([*args, "--min", "1.0"]) == (0 if all(i["gold"] == "unknown" for i in _items(3)) else 1)


def test_the_output_file_records_finish_reason_and_tokens_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    out = tmp_path / "out.json"
    report = _run(tmp_path, monkeypatch, [CLEAN_UNKNOWN, SENTINEL], capsys, "--out", str(out))
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["schema_invalid"] == report["schema_invalid"] and saved["placeholder"] == report["placeholder"]
    assert [(c["finish_reason"], c["tokens_in"], c["tokens_out"]) for c in saved["calls"]] == [
        ("stop", 101, 7),
        ("stop", 102, 7),
    ]
    assert "calls" not in report  # the printed summary stays a summary


def test_a_stub_run_has_no_finish_reason_and_says_so(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    assert judge_eval.main(["--set", str(_write_set(tmp_path, _items(2))), "--gateway-url", "", "--out", str(out)]) == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert len(saved["calls"]) == 2 and all(c["finish_reason"] is None for c in saved["calls"])
    assert saved["schema_invalid"] == 0 and saved["placeholder"] == 0 and saved["mode"] == "stub wiring test"


def test_no_model_against_a_route_whose_first_build_is_down_says_what_to_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    transport, _ = _gateway([], status=502, error={"code": "upstream_down", "message": "the stub is down"})
    _patch_client(monkeypatch, transport)
    rc = judge_eval.main(["--set", str(_write_set(tmp_path, _items(1))), "--gateway-url", "http://gw/v1"])
    err = capsys.readouterr().err.strip().splitlines()
    assert rc == 2 and len(err) == 1
    assert "--model" in err[0] and "alias" in err[0] and "routing.yaml" in err[0] and "upstream_down" in err[0]


def test_the_served_name_against_the_route_says_it_must_be_the_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    transport, _ = _gateway([], status=403, error={"code": "class_route_mismatch", "message": "not on route"})
    _patch_client(monkeypatch, transport)
    rc = judge_eval.main(
        ["--set", str(_write_set(tmp_path, _items(1))), "--gateway-url", "http://gw/v1", "--model", "served-name"]
    )
    err = capsys.readouterr().err.strip().splitlines()
    assert rc == 2 and len(err) == 1
    assert "served-name" in err[0] and "alias" in err[0] and "class_route_mismatch" in err[0]


def test_another_refusal_is_not_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_llm import GatewayRefused

    transport, _ = _gateway([], status=403, error={"code": "no_route", "message": "x"})
    _patch_client(monkeypatch, transport)
    with pytest.raises(GatewayRefused):
        judge_eval.main(["--set", str(_write_set(tmp_path, _items(1))), "--gateway-url", "http://gw/v1"])


def test_the_help_says_what_model_must_be(capsys: Any) -> None:
    with pytest.raises(SystemExit):
        judge_eval.main(["--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "alias" in text and "routing.yaml" in text and "not the name the model server serves" in text
