from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from threading import Lock
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from orchestrator.scenarios.evaluate import NoteJudge
from tb_common.policy.classes import Environment
from tb_llm import CallLabels, GatewayClient

from tests.unit.test_gateway import H, _gw, _judge_body, _pinned_registry, _records
from tools.japanese_context import Arm, Counts, ObservedGateway, Provenance, call_scope, compare
from tools.japanese_context_rehearsal import RUN_DATE, fixture, ingest, screen
from tools.japanese_context_text import TEXT, render

PROVENANCE = Provenance(42, 2500, "a" * 64, "b" * 64)


def pair(total: int, low: int, high: int) -> tuple[Arm, Arm]:
    return (
        Arm("ballast", PROVENANCE, True, Counts(total, low, 5, 4), True),
        Arm("head-box", PROVENANCE, True, Counts(total, high, 5, 4), True),
    )


@pytest.mark.parametrize(
    ("total", "low", "high", "gap", "passes"),
    [(100, 12, 10, Fraction(2), True), (1000, 121, 100, Fraction(21, 10), False)],
)
def test_a6_boundary(total, low, high, gap, passes):
    arms = pair(total, low, high)
    assert compare(*arms) == (gap, passes)
    for locale, text in TEXT.items():
        report = render(*arms, locale)
        assert report == render(*arms, locale)
        assert f"{text['difference']} — {float(gap):+g}" in report
        assert text["pass" if passes else "fail"] in report
        assert f"{text['judge_calls']} — {total}" in report
        assert f"{text['truncated_calls']} — {low}" in report
        assert f"{text['share']} — {100 * high / total:g}%" in report


@pytest.mark.parametrize("problem", ["empty", "interrupted", "fixture", "rules", "context"])
def test_incomplete_pair(problem):
    low, high = pair(100, 12, 10)
    if problem == "empty":
        high.counts = Counts()
    elif problem == "interrupted":
        high.finished = False
    elif problem == "fixture":
        high.provenance = replace(PROVENANCE, fixture_sha256="c" * 64)
    elif problem == "rules":
        high.provenance = replace(PROVENANCE, rules_sha256="c" * 64)
    else:
        high.contexts_verified = False
    assert compare(low, high) == (None, None)
    assert render(low, high, "en").endswith("## A6\n\nIncomplete\n")


def test_three_calls_use_calls_as_denominator_and_sum_both_directions():
    counts = Counts()
    for left_out in (0, 1, 3):
        counts.observe(left_out, {"prompt_tokens": 128, "completion_tokens": left_out})
    assert counts == Counts(3, 2, 384, 4)
    assert counts.share == Fraction(2, 3)


def test_aggregate_missing_token_total_cannot_supply_a_fallback(tmp_path):
    low, _ = pair(100, 12, 10)
    path = tmp_path / "ballast.json"
    low.write(path)
    raw = json.loads(path.read_text())
    del raw["counts"]["output_tokens"]
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        Arm.read(path, "ballast")


def test_raw_gateway_usage_and_verifier_are_separate(tmp_path):
    def reply(request):
        model = json.loads(request.content)["model"]
        usage = {"prompt_tokens": 100}
        if next(outgoing):
            usage["completion_tokens"] = 7
        return httpx.Response(
            200,
            json={
                "model": model,
                "usage": usage,
                "choices": [{"message": {"content": '{"verdict":"unknown","confidence":0.0}'}}],
            },
        )

    outgoing = iter((True, True, True, False))
    upstream = httpx.Client(transport=httpx.MockTransport(reply))
    gateway = _gw(
        tmp_path, env=Environment.VALIDATION, registry=_pinned_registry(), http=upstream, confirm=lambda *_: True
    )
    client = TestClient(create_app(gateway))
    arm = Arm("ballast", PROVENANCE, True, contexts_verified=True)
    lock = Lock()
    judge, verifier = [
        ObservedGateway(
            GatewayClient(str(client.base_url) + "/v1", "orchestrator", http=client, model=alias),
            arm,
            role,
            "STUDY-1",
            lock,
        )
        for role, alias in (("judge", "j-workhorse"), ("verifier", "v-verifier"))
    ]
    # D3 keeps repeated bodies out of the gateway cache.
    labels = CallLabels(
        "D3",
        "screening",
        "STUDY-1",
        "s3_note_judgement",
        "judge",
        "judge@4",
        "step-1",
        prompt_sha=H()["X-TB-Prompt-Sha"],
    )
    with call_scope("judge", 1):
        judge.complete(_judge_body(), replace(labels, study_id="selftest"))
        judge.complete(_judge_body(), labels)
        verifier.complete(_judge_body(), labels)
        payload = judge.complete(_judge_body(), labels)
    assert "completion_tokens" not in payload["usage"]
    assert _records(tmp_path)[-1]["detail"]["tokens_out"] == 0
    assert arm.counts == Counts(1, 1, 100, 7, 1, 1)
    assert not arm.complete
    assert compare(arm, pair(100, 12, 10)[1]) == (None, None)


def test_over_budget_early_return_has_no_call(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("issued a judge call")

    arm = Arm("ballast")
    gateway = ObservedGateway(SimpleNamespace(complete=unexpected), arm, "judge", "STUDY-1", Lock())
    client = SimpleNamespace(chat_json=gateway.complete)
    judge = NoteJudge(None, client)
    monkeypatch.setattr(judge, "window", lambda *args, **kwargs: SimpleNamespace(shown=[], left_out=3))
    with call_scope("judge", 3):
        result = judge.judge_patient("synthetic", None, RUN_DATE)
    assert result.left_out == 3
    assert arm.counts == Counts()


def test_seeded_japanese_fixture_runs_through_both_screen_arms(tmp_path, db_url, monkeypatch):
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    arms = []
    install = tmp_path / "installation"
    install.write_bytes(b"existing configuration\n")
    for profile, context in (("ballast", 8192), ("head-box", 32768)):
        work = tmp_path / profile
        provenance, feed, rules = fixture(work, 42, 500)
        summary = json.loads((feed.parent / "summary.json").read_text())
        assert set(summary["sites"][0]["note_languages"]) == {"ja"}
        lake = ingest(work, feed)
        arm = Arm(profile, provenance)
        sent = []

        def gateway(role, sent=sent, context=context):
            def complete(body, labels):
                sent.append(role)
                return {
                    "model": role,
                    "tb": {"build_sha": role},
                    "choices": [{"message": {"content": '{"verdict":"unknown","confidence":0.0}'}}],
                    "usage": {"prompt_tokens": 123, "completion_tokens": 4},
                }

            return SimpleNamespace(base_url="in-process", model=role, context=lambda: context, complete=complete)

        screen(work, lake, rules, arm, gateway("judge"), gateway("verifier"))
        assert arm.complete
        assert arm.counts.judge_calls == sent.count("judge") > 0
        assert arm.counts.input_tokens == 123 * arm.counts.judge_calls
        assert arm.counts.output_tokens == 4 * arm.counts.judge_calls
        path = tmp_path / f"{profile}.json"
        arm.write(path)
        arms.append(Arm.read(path, profile))
    assert arms[0].provenance == arms[1].provenance
    assert compare(*arms)[1] is not None
    for locale, labels in TEXT.items():
        output = render(*arms, locale)
        assert "8,192" in output and "32,768" in output
        assert labels["ballast"] in output and labels["head-box"] in output
        assert "JP=ja:1.0" in output
        for private in ("synthetic-patient", "JP-A", "o6-synthetic", "verdict", "confidence", "measured"):
            assert private not in output
    assert install.read_bytes() == b"existing configuration\n"
