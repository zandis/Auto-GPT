"""D-1235. Exercise note-bearing boundaries with synthetic charts and capture what actually leaves."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from datacore.forms import Field
from doc_parser import parser
from edc.mapping import ItemMap
from edc.prefill import gateway_drafter
from embed_service import app as embed_app
from guard.guard import Guard
from matching.cascade.judge import GatewayJudge
from matching.cascade.s2b_semantic import Threshold, screen
from matching.registry_match import core
from matching.registry_match.llm import LLMClient
from orchestrator.scenarios import case
from orchestrator.scenarios.evaluate import NoteJudge
from orchestrator.scenarios.screen_cascade import OrchestratorJudge
from sitesetup import charts
from sitesetup.service import SiteSetup
from tb_common import ja_names, phi_guard
from tb_common.logging import JsonFormatter, redact
from tb_contracts import EmbedRequest
from vec.index import Note, index_notes

from tests.registry_match_mock import MockChat, trial
from tests.unit import test_gateway as gateway
from tests.unit.test_site_setup import WS, svc  # noqa: F401 (pytest fixture)
from tests.unit.test_vec import FakeStore, SpyEmbedder
from tools import ja_name_eval

NOTE = "68歳男性 ミホン タロウ"
DAY = date(2026, 1, 1)
EX = {"date": DAY.isoformat(), "text": NOTE, "note_type": "chart"}
PARAMS = dict(
    criterion_text="fever",
    note_question="fever?",
    index_date=DAY,
    study_id="study",
    data_class="D3",
    step_id="review",
    purpose="screening",
)


@pytest.fixture(autouse=True)
def at_japanese_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(phi_guard, "_site_reading", lambda: ("auto", "Asia/Tokyo", "ja-JP"))


def safe_calls(calls: object, caplog: pytest.LogCaptureFixture) -> None:
    sent = str(calls)
    assert "68歳男性" in sent
    for part in ("ミホン", "タロウ"):
        assert part not in sent and part not in caplog.text


def model() -> Mock:
    spy = Mock(spec=["chat_json", "chat"])
    result = SimpleNamespace(
        data={},
        model="stub",
        prompt_id="judge",
        prompt_version=1,
        call_id="call",
        build_sha="build",
        tokens_in=1,
        tokens_out=1,
    )
    spy.chat_json.return_value = spy.chat.return_value = result
    return spy


@pytest.mark.nodb
@pytest.mark.parametrize("route", ["case", "cascade-judge", "cascade-verifier", "gateway-judge", "edc", "chart-reader"])
def test_model_input(route: str, caplog: pytest.LogCaptureFixture) -> None:
    spy = model()
    if route == "case":
        ctx = Mock()
        ctx.job.inputs = [SimpleNamespace(filename="chart.txt")]
        ctx.input_bytes.return_value = (NOTE + "\n\nタロウ").encode()
        ctx.today.return_value = DAY
        excerpts, _ = case.read_charts(ctx)
        NoteJudge(None, spy).judge_excerpts("fever", "fever?", DAY, excerpts)
    elif route == "gateway-judge":
        GatewayJudge(spy).judge(role="judge", excerpts=[EX], **PARAMS)  # type: ignore[arg-type]
    elif route.startswith("cascade"):
        OrchestratorJudge(None, spy).judge(role=route.split("-")[1], excerpts=[EX], **PARAMS)  # type: ignore[arg-type]
    elif route == "edc":
        gateway_drafter(spy)(ItemMap("fever"), Field("fever", "visit", "text", "Fever"), [EX])
    else:
        charts.extract(spy, NOTE, "ja")
    safe_calls(spy.method_calls, caplog)


def test_site_upload(svc: SiteSetup, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:  # noqa: F811
    spy = model()
    svc.llm = spy
    svc.add_chart(WS, "10000007", "chart.txt", NOTE.encode(), "crc")
    safe_calls(spy.method_calls, caplog)
    rows = gateway._records(tmp_path)
    assert any(row["event"] == "setup.chart" for row in rows)
    assert all("ミホン" not in str(row) and "タロウ" not in str(row) for row in gateway._records(tmp_path))


@pytest.mark.nodb
@pytest.mark.parametrize("route", ["keywords", "match", "aggregate"])
def test_registry_model_input(route: str, caplog: pytest.LogCaptureFixture) -> None:
    spy = MockChat()
    client = LLMClient(spy)
    t = trial("NCT1", ["Fever today"], ["No fever"])
    if route == "keywords":
        core.generate_keywords(client, NOTE)
    elif route == "match":
        core.match_trial(client, t, NOTE)
    else:
        core.aggregate(client, core.TrialMatch("NCT1", {"inclusion": {}, "exclusion": {}}), t, NOTE)
    safe_calls(spy.calls, caplog)


@pytest.mark.nodb
@pytest.mark.parametrize("route", ["cascade", "vectors", "embed-service"])
def test_embedding_input(route: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    spy = SpyEmbedder()
    if route == "cascade":
        screen(spy, "fever", [NOTE], Threshold(0.1, "prior", "ja"))
    elif route == "vectors":
        index_notes(FakeStore(), [Note("p", "d", NOTE)], spy)
    else:
        monkeypatch.setattr(embed_app, "_embedder", spy)
        embed_app.embed(EmbedRequest(texts=[NOTE]))
    safe_calls(spy.inputs, caplog)


@pytest.mark.nodb
def test_chart_locator(caplog: pytest.LogCaptureFixture) -> None:
    locate = Mock(return_value={})
    parser.parse((NOTE + "\nタロウ").encode(), "chart.txt", locate)
    safe_calls(locate.call_args, caplog)


@pytest.mark.nodb
@pytest.mark.parametrize("excerpts", [[EX], [EX, NOTE], NOTE], ids=["objects", "mixed", "text"])
def test_gateway_model_input(excerpts: object, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    sent: list[Any] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"model": "trialbox-stub", "choices": [{"message": {"content": "{}"}}]})

    gw = gateway._gw(tmp_path, http=httpx.Client(transport=httpx.MockTransport(upstream)))
    gw.chat(gateway.H(), gateway._judge_body({**gateway.JUDGE_VARS, "excerpts": excerpts}))
    safe_calls(sent, caplog)


@pytest.mark.nodb
@pytest.mark.parametrize("failure", [ModuleNotFoundError, OSError, RuntimeError])
@pytest.mark.parametrize("route", ["gateway", "case"])
def test_audited_refusal(route: str, failure: type[Exception], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A loader can include its input in an exception. It must never reach the audit or log.
    monkeypatch.delattr(phi_guard._JA_ANALYSER, "an", raising=False)
    monkeypatch.setattr(ja_names, "analyser", Mock(side_effect=failure(NOTE)))
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    sent: list[str] = []
    if route == "gateway":
        gw = gateway._gw(tmp_path, http=gateway._mock("echo", sent))
        result = gw.chat(gateway.H(), gateway._judge_body({**gateway.JUDGE_VARS, "excerpts": [EX]}))
        assert result.status >= 400
    else:
        spy = model()
        with pytest.raises(RuntimeError):
            NoteJudge(None, spy).judge_excerpts("fever", "fever?", DAY, [EX])
        assert not spy.method_calls
    rows = gateway._records(tmp_path)
    assert not sent and any("refus" in str(r["event"]) for r in rows)
    assert "ミホン" not in str(rows) and "タロウ" not in str(rows)
    assert "ミホン" not in redact(NOTE)


@pytest.mark.nodb
@pytest.mark.parametrize(
    ("line", "parts", "lang"),
    [
        ("森本裕子", ["森本", "裕子"], "ja"),
        (NOTE, ["ミホン", "タロウ"], "ja"),
        ("森本\n裕子", ["森本", "裕子"], "ja"),
        ("外来\n森本\n裕子", ["森本", "裕子"], "ja"),
        ("Taro\n    Yamada", ["Taro", "Yamada"], "en"),
        ("Tarō Satō called Sato.", ["Tarō", "Satō", "Sato"], "en"),
        ("68歳男性 ミホン\nタロウ", ["ミホン", "タロウ"], "ja"),
        ("Taro Yamada", ["Taro", "Yamada"], "en"),
        ("Tarō Satō", ["Tarō", "Satō"], "en"),
        ("Ｙａｍａｄａ\nＴａｒｏ", ["Ｙａｍａｄａ", "Ｔａｒｏ"], "ja"),
        ("担当PT：浅野", ["浅野"], "en"),
        ("担当PT：浅野", ["浅野"], None),
        ("Dr.Kimura", ["Kimura"], "ja"),
        ("Dr.Kimura", ["Kimura"], None),
        ("Go Sato", ["Go", "Sato"], "en"),
        ("Taro Yamada called Yamada.", ["Taro", "Yamada"], "en"),
    ],
    ids=[
        "kanji",
        "kana",
        "kanji-newline",
        "wrapped-after-heading",
        "indented-romaji",
        "repeat-macron",
        "kana-newline",
        "romaji",
        "macrons",
        "width-newline",
        "en-role",
        "auto-role",
        "ja-title",
        "auto-title",
        "english-given",
        "repeat",
    ],
)
def test_name_forms(line: str, parts: list[str], lang: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(phi_guard, "site_notes_language", lambda: lang)
    record = logging.LogRecord("clinical", logging.INFO, "", 1, line, (), None)
    logged = json.loads(JsonFormatter("test").format(record))["msg"]
    guard = Guard(None)
    assert guard.tripwire(line).hit
    for part in parts:
        assert part not in logged and part not in phi_guard.mask_note(line)
        start = line.find(part)
        while start >= 0:
            assert any(f.start <= start and start + len(part) <= f.end for f in guard.detect(line))
            start = line.find(part, start + 1)


@pytest.mark.nodb
def test_evaluation_checks_every_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    line = "Taro Yamada called Yamada."
    monkeypatch.setattr(ja_name_eval, "mask_note", lambda text: "○○○○ ○○○○○○ called Yamada.")
    assert ja_name_eval.unmasked(line, ["Yamada"], Guard(None)) == ["Yamada"]


@pytest.mark.nodb
@pytest.mark.parametrize(
    "line",
    [
        "CRC",
        "PT",
        "Dr",
        "ECOG PS 2",
        "担当医：CRC",
        "患者：PT",
        "患者：ECOG PS 2",
        "患者：Blood Pressure",
        "Dr. CRC",
        "CRC先生",
        "PT 様",
        "氏名：ECOG PS",
        "担当医：Heart Failure",
        "患者：Rheumatoid Arthritis",
    ],
    ids=[
        "crc",
        "pt",
        "dr",
        "ecog",
        "label-crc",
        "label-pt",
        "label-ecog",
        "label-clinical",
        "dr-crc",
        "crc-title",
        "pt-title",
        "name-label-ecog",
        "staff-label-clinical",
        "patient-label-clinical",
    ],
)
def test_no_name(line: str) -> None:
    assert phi_guard.mask_note(line) == redact(line) == line
    if line.startswith("氏名"):
        # The existing PHI keyword policy flags a name field even when no name is present.
        assert Guard(None).tripwire(line).kinds == ("KEYWORD",)
    else:
        assert not Guard(None).tripwire(line).hit


@pytest.mark.nodb
def test_bounded_log_keeps_no_partial_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_LOG_SCRUB_MAX_CHARS", "1024")
    # Only the second, bare mention survives the existing first/last log budget.
    line = "x " * 500 + "Taro Yamada called. " + "x " * 500 + "Yamada."
    assert "Yamada" not in redact(line)


@pytest.mark.nodb
def test_direct_model_client(caplog: pytest.LogCaptureFixture) -> None:
    from tb_common.llm import LlmClient

    calls: list[Any] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"facts":[]}'}}]})

    client = LlmClient("", "stub")
    with httpx.Client(transport=httpx.MockTransport(upstream), base_url="https://stub.invalid") as http:
        client.http = http
        client.chat_json("chart_facts", {"text": NOTE, "language": "ja", "language_name": "Japanese"})
    safe_calls(calls, caplog)


@pytest.mark.nodb
@pytest.mark.parametrize("route", ["benchmark", "trialgpt", "profile", "judge-evaluation", "accuracy", "canary"])
def test_evaluation_input(route: str, caplog: pytest.LogCaptureFixture) -> None:
    from orchestrator import selftest

    from tools import accuracy_set, bakeoff_live, bench_profile, judge_eval, mlbench

    spy = model()
    item = dict(gateway.JUDGE_VARS, excerpts=[EX], id="one", criterion_id="one", gold="unknown", expected="unknown")
    if route == "benchmark":
        pair = mlbench.Pair("1", "p", "t", "inclusion", "Fever", "included", (), "included", False)
        spy.chat.return_value = {"_error": "stub"}
        mlbench.judge(spy, "stub", "ja", pair, [NOTE])
    elif route == "trialgpt":
        spy.chat(bakeoff_live.trialgpt_messages("inclusion", "Fever", [NOTE]))
    elif route == "profile":
        spy.chat(bench_profile.messages({"language": "Japanese", "facts": [{"id": "F1", "text": NOTE}]}))
    elif route == "judge-evaluation":
        judge_eval.evaluate([item], spy)
    elif route == "accuracy":
        accuracy_set.run_model(spy, [item])
    else:
        selftest.check_model("judge", spy, [item])
    safe_calls(spy.method_calls, caplog)


def test_lake_embeddings(tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    from lake.store import Lake

    from tests.unit import test_phi_note_mask as lake_fixture

    monkeypatch.setattr(lake_fixture, "NOTES", {"d1": NOTE})
    spy = SpyEmbedder()
    Lake(tmp_path / "lake", "Asia/Tokyo").rebuild("2026-01-02", spy, lake_fixture._ndjson(tmp_path / "nd"))
    safe_calls(spy.inputs, caplog)


@pytest.mark.nodb
@pytest.mark.parametrize("name", ["Stone", "James Wong", "Mihon Taro"])
def test_staff_label_keeps_name_coverage(name: str) -> None:
    line = "担当医：" + name
    for word in name.split():
        assert word not in phi_guard.mask_note(line)
        assert word not in redact(line)


@pytest.mark.nodb
@pytest.mark.parametrize("route", ["facts", "vectors", "embed-service"])
def test_latin_note_also_refuses_on_load_failure(route: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delattr(phi_guard._JA_ANALYSER, "an", raising=False)
    monkeypatch.setattr(ja_names, "analyser", Mock(side_effect=OSError("dictionary")))
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    spy = model()
    vectors = SpyEmbedder()
    with pytest.raises(RuntimeError):
        if route == "facts":
            charts.extract(spy, "Tarō Satō", "en")
        elif route == "vectors":
            index_notes(FakeStore(), [Note("p", "d", "Tarō Satō")], vectors)
        else:
            monkeypatch.setattr(embed_app, "_embedder", vectors)
            embed_app.embed(EmbedRequest(texts=["Tarō Satō"]))
    assert not vectors.inputs
    assert not spy.method_calls and any("refus" in r["event"] for r in gateway._records(tmp_path))


def test_site_refusal_uses_upload_ledger(
    svc: SiteSetup,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delattr(phi_guard._JA_ANALYSER, "an", raising=False)
    monkeypatch.setattr(ja_names, "analyser", Mock(side_effect=OSError(NOTE)))
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "other"))
    spy = model()
    svc.llm = spy
    with pytest.raises((OSError, RuntimeError)):
        svc.add_chart(WS, "10000007", "chart.txt", NOTE.encode(), "crc")
    rows = gateway._records(tmp_path)
    assert not spy.method_calls and any("refus" in row["event"] for row in rows)
    assert "ミホン" not in str(rows) and "タロウ" not in str(rows)


@pytest.mark.nodb
def test_patient_label_keeps_name_coverage() -> None:
    line = "患者：Laura Green"
    assert "Laura" not in phi_guard.mask_note(line)
    assert "Green" not in redact(line)
