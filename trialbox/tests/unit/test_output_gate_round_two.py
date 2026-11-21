"""Second-round regressions at the model, clinical and inventory boundaries."""

from __future__ import annotations

import http.client
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from model_guard import CHAT_COMPLETIONS, Guard, make_handler
from tb_common.llm import LlmClient
from tb_common.output_gate import OutputRefused, prepare_output

from tests.unit.test_model_guard import KEY, _call, _start

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]


def test_negated_eligibility_survives_the_gate() -> None:
    note = "Pt: No history of seizures."
    assert prepare_output("chart_text", "model", {"text": note})["text"] == note


def test_mail_transport_is_in_both_inventory_and_open_findings() -> None:
    from tools.output_sinks import inspect_source

    path = "services/mail_gateway/gateway.py"
    sites = inspect_source(path, (ROOT / path).read_text())
    assert any((s.function, s.area, s.sink) == ("Gateway._attempt", "mail", "transport") for s in sites)
    later = (ROOT / "docs/plan/gates/gate-5.md").read_text().partition("Open for later slices")[2]
    assert "Gateway._attempt" in later and "aggregate" in later


def test_identifying_prompt_header_stops_dispatch(tmp_path: Path) -> None:
    from tests.unit.test_gateway import H, _gw, _judge_body, _mock

    sent: list[str] = []
    gw = _gw(tmp_path, http=_mock("echo", sent))
    result = gw.chat(H(Prompt="43219876@1"), _judge_body())
    assert (result.status, sent) == (422, [])
    assert result.body["error"]["code"] == "output_identifier_refused"


def test_assist_variables_are_checked_before_json_escaping() -> None:
    def reply(req: httpx.Request) -> httpx.Response:
        assert "43219876" not in json.loads(req.content)["messages"][-1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    llm = LlmClient("https://example.invalid/v1", "synthetic")
    llm.http = httpx.Client(transport=httpx.MockTransport(reply))
    llm.chat_json(
        "assist",
        {
            "question": "Study question\n43219876",
            "language": "en",
            "language_name": "English",
            "draft": "",
            "points": [],
        },
    )


def test_overlap_cannot_separate_name_from_label() -> None:
    from vec.index import Note, note_chunks

    note = "x" * 395 + " Pt: Robin Example " + "x" * 130
    try:
        rows = note_chunks(Note("p", "n", note))
    except OutputRefused as exc:
        assert exc.reason == "output_identifier_refused"
        return
    assert any(row.start == 400 for row in rows)
    assert all("Robin" not in row.text for row in rows)


def test_dense_query_fallback_masks_before_slicing() -> None:
    from matching.registry_match.pipeline import run_patient

    note = "x " * 98 + " " + "陳美華女士，關節疼痛。"
    index = Mock(docs={})
    index.search.return_value = []
    run_patient(note, client=Mock(), index=index, keywords={"conditions": []})
    assert index.search.call_args.args[0] == [prepare_output("chart_text", "model", {"text": note})["text"][:200]]


def test_settings_failure_closes_even_a_clean_embedding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.config import get_config

    monkeypatch.setenv("TB_SETTINGS", str(tmp_path / "absent.yaml"))
    get_config.cache_clear()
    try:
        with pytest.raises(OutputRefused, match="analysis_unavailable"):
            prepare_output("embedding", "model", {"texts": ["Follow-up for 43219876"]})
    finally:
        get_config.cache_clear()


def test_unaudited_proxy_refusal_reports_service_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_model_guard import _Upstream

    path = tmp_path / "file"
    path.touch()
    monkeypatch.setenv("TB_AUDIT_DIR", str(path / "unwritable"))
    upstream = _start(_Upstream)
    proxy = _start(make_handler(Guard(KEY, {"llm-service": (str(upstream.server_address[0]), upstream.server_port)})))
    try:
        assert _call(proxy.server_port, "POST", "/tokenize", body=b'{"prompt":42}') == 503
    finally:
        for srv in (proxy, upstream):
            srv.shutdown()
            srv.server_close()


def test_family_dob_is_never_proposed_for_patient() -> None:
    from sitesetup.charts import extract

    llm = Mock()
    llm.chat_json.return_value = {"facts": []}
    facts, _ = extract(llm, "Family history\nDaughter\nDOB: 2018-04-05", "en")
    assert facts == []


def test_proxy_forwards_registered_handler_id() -> None:
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            seen.append(self.headers.get("X-TB-Prompt-Id"))
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    upstream = _start(Handler)
    proxy = _start(make_handler(Guard(KEY, {"llm-service": (str(upstream.server_address[0]), upstream.server_port)})))
    try:
        conn = http.client.HTTPConnection(*proxy.server_address)
        conn.request(
            "POST",
            CHAT_COMPLETIONS,
            b"{}",
            {"Host": "llm-service", "Authorization": f"Bearer {KEY}", "X-TB-Prompt-Id": "judge"},
        )
        assert conn.getresponse().status == 200
        conn.close()
        assert seen == ["judge"]
    finally:
        for srv in (proxy, upstream):
            srv.shutdown()
            srv.server_close()


def test_shallow_checkout_cannot_supply_its_own_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import output_sinks

    monkeypatch.delenv("TB_OUTPUT_SINK_BASE", raising=False)

    def shallow(args: list[str], **kw: Any) -> bytes:
        if "rev-parse" in args:
            return b"true\n"
        if "show" in args:
            return b"[]"
        return b"HEAD\n"

    monkeypatch.setattr("subprocess.check_output", shallow)
    with pytest.raises(ValueError, match="shallow"):
        output_sinks.inventory_ceiling()


@pytest.mark.parametrize(
    "mutation",
    [
        'approved["messages"].append(raw)',
        'child = approved["messages"]\n    child.append(raw)',
        'approved["messages"][0]["content"] = raw',
    ],
)
def test_nested_mutation_revokes_container_approval(mutation: str) -> None:
    from tools.output_sinks import inspect_source

    src = f"""from tb_common.output_gate import prepare_output
def send(req, raw):
    approved = prepare_output("chat", "model", req)
    {mutation}
    model.complete(approved)
"""
    assert [s.area for s in inspect_source("libs/example.py", src)] == ["model"]


def test_shipped_proxy_records_refusal_through_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml
    from fastapi.testclient import TestClient
    from gateway.app import create_app
    from tb_common.audit import verify

    from tests.unit.test_gateway import _gw, _records
    from tests.unit.test_model_guard import _Upstream

    compose = yaml.safe_load((ROOT / "deploy/docker-compose.yml").read_text())["services"]["model-guard"]
    assert compose["read_only"] and any("/etc/trialbox/settings.yaml:ro" in v for v in compose["volumes"])
    env = compose["environment"]
    monkeypatch.setenv("TB_SERVICE_NAME", env["TB_SERVICE_NAME"])
    monkeypatch.setenv("TB_GATEWAY_URL", env["TB_GATEWAY_URL"])
    monkeypatch.setenv("TB_LLM_API_KEY", KEY)
    gw = _gw(tmp_path)
    gw.env = {"TB_LLM_API_KEY": KEY}
    receiver = TestClient(create_app(gw))
    from tb_common.output_gate import REFUSAL_PATH

    path = f"{REFUSAL_PATH}/tokenize/output_invalid"
    assert receiver.post(path).status_code == 401
    assert receiver.post(f"{path}/raw", headers={"Authorization": f"Bearer {KEY}"}).status_code == 404
    client = httpx.Client

    def forward(request: httpx.Request) -> httpx.Response:
        result = receiver.post(request.url.path, headers=dict(request.headers))
        return httpx.Response(result.status_code, content=result.content)

    monkeypatch.setattr(httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(forward)))
    upstream = _start(_Upstream)
    proxy = _start(make_handler(Guard(KEY, {"llm-service": (str(upstream.server_address[0]), upstream.server_port)})))
    try:
        assert _call(proxy.server_port, "POST", "/tokenize", body=b'{"prompt":42}') == 422
        (record,) = _records(tmp_path)
        assert record["event"] == "llm.output_refused"
        assert record["detail"] == {"purpose": "tokenize", "reason": "output_invalid"}
        assert verify(tmp_path / "audit").ok
    finally:
        receiver.close()
        for srv in (proxy, upstream):
            srv.shutdown()
            srv.server_close()


def test_g4_judge_uses_standin_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit import test_vllm_standin as standin

    monkeypatch.setenv("JUDGE_MODEL", standin.NAME)
    upstream, _ = standin._serve([f"--served-model-name={standin.NAME}", "--api-key", KEY])
    proxy = _start(make_handler(Guard(KEY, {"llm-service": (str(upstream.server_address[0]), upstream.server_port)})))
    try:
        conn = http.client.HTTPConnection(*proxy.server_address)
        conn.request(
            "POST",
            CHAT_COMPLETIONS,
            json.dumps(standin._chat(standin.NAME)),
            {"Host": "llm-service", "Authorization": f"Bearer {KEY}", "X-TB-Prompt-Id": "judge"},
        )
        response = conn.getresponse()
        assert response.status == 200
        assert "verdict" in json.loads(json.loads(response.read())["choices"][0]["message"]["content"])
        conn.close()
    finally:
        for srv in (proxy, upstream):
            srv.shutdown()
            srv.server_close()


def test_public_provider_never_receives_identifying_prompt_header(tmp_path: Path) -> None:
    from tests.unit.test_provider_pin import Upstream, _body, _gateway, _headers, _registry

    up = Upstream()
    gw = _gateway(tmp_path, up, _registry())
    assert gw.chat({**_headers(), "X-TB-Prompt": "43219876@1"}, _body()).status == 422
    assert up.requests == []


def test_gate_checks_sdk_rendered_json() -> None:
    data = {"messages": [{"role": "user", "content": json.dumps({"note": "Study question\n43219876"})}]}
    shown = prepare_output("chat", "model", data)["messages"][0]["content"]
    assert json.loads(shown)["note"] == "Study question\n" + "○" * 8


def test_ci_checks_ratchet_against_target_revision() -> None:
    import yaml

    workflow = yaml.safe_load((ROOT.parent / ".github/workflows/trialbox-ci.yml").read_text())
    assert "github.event.pull_request.base.sha" in workflow["env"]["TB_OUTPUT_SINK_BASE"]
    for name in ("checks", "unit-shard"):
        checkout = next(s for s in workflow["jobs"][name]["steps"] if s.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["fetch-depth"] == 0


def test_index_refuses_to_rekey_a_note_or_send_its_overlap() -> None:
    from vec.index import Note, index_notes

    from tests.unit.test_vec import FakeStore, SpyEmbedder

    note = "x" * 395 + " Pt: Robin Example " + "x" * 130
    store, embedder = FakeStore(), SpyEmbedder()
    with pytest.raises(OutputRefused, match="output_identifier_refused"):
        index_notes(store, [Note("p", "n", note)], embedder)
    assert not store.rows and not store.vectors and not embedder.inputs


def test_projection_through_get_cannot_keep_approval_after_mutation() -> None:
    from tools.output_sinks import inspect_source

    source = """from tb_common.output_gate import prepare_output
def send(req, raw):
    approved = prepare_output("chat", "model", req)
    nested = approved.get("messages")
    nested.append(raw)
    model.complete(approved)
"""
    assert [s.area for s in inspect_source("libs/example.py", source)] == ["model"]


def test_supplemental_chart_number_does_not_replace_site_recogniser() -> None:
    out = prepare_output("embedding", "model", {"texts": ["43219876 and SYN123"]}, mrn_regex=r"^SYN\d{3}$")
    assert out["texts"] == ["○○○○○○○○ and ○○○○○○"]


@pytest.mark.parametrize("note", ["Patient: No history of seizures.", "Pt: No History of seizures.", "Pt: No COPD."])
def test_both_name_analysers_preserve_clinical_negation(note: str) -> None:
    assert prepare_output("chart_text", "model", {"text": note})["text"] == note


def test_correcting_old_patient_label_does_not_rekey_stored_vectors() -> None:
    with pytest.raises(OutputRefused, match="output_identifier_refused"):
        prepare_output("indexed_note", "model", {"text": "Patient: No history of seizures."})


def test_local_dob_is_bound_to_the_intake_patient() -> None:
    from sitesetup import charts, help

    number, note = help.PRACTICE_CHARTS[0]
    llm = Mock()
    llm.chat_json.return_value = {"facts": []}
    own, _ = charts.extract(llm, note, "ja", patient_numbers=(number,))
    other, _ = charts.extract(llm, note, "ja", patient_numbers=("other",))
    assert [(f["code"], f["value"]) for f in own] == [("birth_date", "1961-04-03")]
    assert other == []


@pytest.mark.parametrize("purpose", ["completion", "tokenize"])
def test_rendered_prompts_use_the_same_projection_as_messages(purpose: str) -> None:
    prompt = json.dumps({"note": "Study question\n43219876"})
    shown = prepare_output(purpose, "model", {"prompt": [prompt]})["prompt"]
    assert json.loads(shown[0])["note"] == "Study question\n" + "○" * 8
