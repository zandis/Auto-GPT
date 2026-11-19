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


@pytest.mark.parametrize("plant_omissions", [False, True])
def test_seeded_japanese_fixture_runs_through_both_screen_arms(tmp_path, db_url, monkeypatch, plant_omissions):
    from matching.cascade.engine import _Run

    excerpt_set = _Run.excerpt_set
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

        if plant_omissions:

            def planted(*args, omitted=(4 if profile == "ballast" else 0), **kwargs):
                shown, _ = excerpt_set(*args, **kwargs)
                return [{**note, "text": "合成カルテのテスト印"} for note in shown], omitted

            monkeypatch.setattr(_Run, "excerpt_set", staticmethod(planted))

        def gateway(role, sent=sent, context=context):
            def complete(body, labels):
                sent.append(role)
                if plant_omissions:
                    assert "合成カルテのテスト印" in str(body["messages"])
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
        if plant_omissions:
            assert arm.counts.truncated_calls == (sent.count("judge") if profile == "ballast" else 0)
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
        assert "合成カルテのテスト印" not in output
        for private in ("synthetic-patient", "JP-A", "o6-synthetic", "verdict", "confidence", "measured"):
            assert private not in output
    assert install.read_bytes() == b"existing configuration\n"


@pytest.mark.parametrize(
    ("total", "low", "high", "gap", "passes"),
    [(100, 5, 3, Fraction(2), True), (10000, 501, 300, Fraction(201, 100), False), (100, 0, 4, Fraction(-4), True)],
)
def test_paired_percentages(total, low, high, gap, passes):
    arms = pair(total, low, high)
    assert compare(*arms) == (gap, passes)
    for locale, labels in TEXT.items():
        report = render(*arms, locale)
        for count in (low, high):
            assert f"{labels['share']} — {100 * count / total:g}%" in report
        assert f"{labels['difference']} — {float(gap):+g}" in report


def test_measured_usage_only():
    counts = Counts()
    for omitted in (0, 1, 4):
        counts.observe(omitted, {"prompt_tokens": 900, "completion_tokens": 20})
    counts.observe(4, {"completion_tokens": 0})
    counts.observe(4, {"prompt_tokens": 900, "completion_tokens": 20, "estimated": True})
    assert counts == Counts(3, 2, 2700, 60, 2)


def test_capture_preserves_completed_arm_on_refusal(tmp_path, monkeypatch):
    from tools.japanese_context_rehearsal import capture

    path = tmp_path / "ballast.json"
    pair(100, 5, 3)[0].write(path)
    previous = path.read_bytes()
    monkeypatch.delenv("TB_ENV", raising=False)
    assert not capture(tmp_path, "ballast", 42).complete
    assert path.read_bytes() == previous
    attempt = tmp_path / "ballast.incomplete.json"
    assert attempt.exists() and not Arm.read(attempt, "ballast").complete


def test_offline_cli_replays_only_aggregate_figures(tmp_path, monkeypatch, capsys):
    import sys

    from tools.japanese_context import main

    labels = SimpleNamespace(study_id="synthetic-marker")
    raw = {"usage": {"prompt_tokens": 900, "completion_tokens": 20}, "text": "synthetic-marker"}
    for arm in pair(1, 0, 0):
        arm.counts = Counts()
        for role in ("judge", "verifier"):
            gateway = ObservedGateway(SimpleNamespace(complete=lambda *_: raw), arm, role, labels.study_id, Lock())
            with call_scope(role, 1):
                gateway.complete({"prompt": "synthetic-marker"}, labels)
        assert arm.counts == Counts(1, 1, 900, 20, verifier_calls=1)
        arm.write(tmp_path / f"{arm.profile}.json")
    monkeypatch.setattr(sys, "argv", ["o6", "report", str(tmp_path)])
    for locale, text in TEXT.items():
        monkeypatch.setenv("TB_REPORT_LANG", locale)
        assert main() == 0
        first = capsys.readouterr().out
        assert main() == 0
        assert capsys.readouterr().out == first
        assert text["pass"] in first
        assert "synthetic-marker" not in first
        for field, count in vars(Counts(1, 1, 900, 20, verifier_calls=1)).items():
            assert first.count(f"{text[field]} — {count}\n") == 2


def test_gateway_reported_retry_has_one_unobserved_attempt():
    arm, _ = pair(1, 0, 0)
    arm.counts = Counts()
    payload = {"tb": {"retries": 1}, "usage": {"prompt_tokens": 900, "completion_tokens": 20}}
    labels = SimpleNamespace(study_id="synthetic")
    gateway = ObservedGateway(SimpleNamespace(complete=lambda *_: payload), arm, "judge", labels.study_id, Lock())
    with call_scope("judge", 4):
        gateway.complete({}, labels)
    assert arm.counts == Counts(1, 1, 900, 20, missing_judge_calls=1)
    assert not arm.complete


def test_absent_capture_files_have_no_verdict(tmp_path):
    low, high = [Arm.read(tmp_path / f"{profile}.json", profile) for profile in ("ballast", "head-box")]
    assert compare(low, high) == (None, None)
    assert compare(pair(1, 0, 0)[0], high) == (None, None)
    for locale, labels in TEXT.items():
        assert render(low, high, locale).endswith(f"## A6\n\n{labels['incomplete']}\n")
