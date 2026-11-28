"""SAFE-1 A1: an unqualified pinned pair runs, labelled; the shipped record (D-569) stays the normal case.

* In PRODUCTION a local build whose pin is the release's weights (``expected.manifest_sha256``) routes with no
  qualification record, as candidate, qualified or champion (thinking-only too), and the resolution says
  ``qualification="unqualified"``. A build that holds a record is tried first and answers unlabelled.
* What stays refused: other weights (``weights_unexpected``), no context (``context_unknown``), a rehearsal
  placeholder, and a pin with nothing expected (trust on first use, a hand pin).
* The label travels: the gateway's call record, the answer's ``tb`` block and a header; the client's result; the
  judge reply of the pair; the cascade's evidence and the candidate-list row. Doctor WARNs in PRODUCTION; the
  installer says it at the start and does not end on a FAIL for it.

Synthetic builds and bytes only.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from matching.cascade.judge import AgreementJudge, JudgeReply
from matching.cascade.model import Outcome
from orchestrator.scenarios.screen_cascade import verdict_of
from registry.registry import Registry, RegistryError
from tb_common.policy.classes import Environment
from tb_llm import GatewayClient
from tb_llm.client import CallLabels
from tb_llm.prompt_registry import default_registry

from tests.model_pins import qualified
from tests.unit.test_gateway import H, _gw, _judge_body, _mock, _records
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
SHA = "ab" * 32
OTHER = "cd" * 32
ok = lambda caller, study, step: True  # noqa: E731


def _b(build_id: str = "j-1", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "build_id": build_id,
        "alias": "j-workhorse",
        "status": "candidate",
        "serving": "vllm",
        "context_length": 32768,
        "served": {"serving": "j-test"},
        "sha256": SHA,
        "expected": {"manifest_sha256": SHA},
        "licence": {"name": "test"},
        "origin": {"developer": "test"},
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _reg(*builds: dict[str, Any]) -> Registry:
    aliases = {a: {"class": "J"} for a in ("trialbox-stub", "j-workhorse", "v-verifier", "x-external")}
    return Registry({"version": "registry-test", "aliases": aliases, "builds": list(builds)})


def _resolve(reg: Registry, env: Environment = Environment.PRODUCTION, role: str = "judge") -> Any:
    return reg.resolve("j-workhorse", "serving", role=role, env=env)


# ------------------------------------------------------------------------------------------------ the registry
@pytest.mark.parametrize("status", ["candidate", "qualified", "champion"])
def test_the_release_weights_route_in_production_labelled(status: str) -> None:
    res = _resolve(_reg(_b(status=status)))
    assert res.build.build_id == "j-1" and res.served_name == "j-test"
    assert res.qualification == "unqualified"


def test_a_thinking_only_release_build_routes_labelled() -> None:
    res = _resolve(_reg(_b(thinking_control="thinking_only")))
    assert res.qualification == "unqualified"


def test_validation_labels_its_candidate_and_test_does_not() -> None:
    reg = _reg(_b())
    assert _resolve(reg, Environment.VALIDATION).qualification == "unqualified"
    assert _resolve(reg, Environment.TEST).qualification == ""


def test_a_build_holding_a_record_is_tried_first_and_is_not_labelled() -> None:
    held = _b("j-2", status="champion", sha256=OTHER, expected={"manifest_sha256": OTHER}, qualification=qualified(OTHER))
    res = _resolve(_reg(_b("j-1"), held))
    assert res.build.build_id == "j-2" and res.qualification == ""


@pytest.mark.parametrize(
    ("build", "code"),
    [
        (_b(sha256=OTHER), "weights_unexpected"),
        (_b(context_length=None), "context_unknown"),
        (_b(sha256=OTHER, weights={"trust": "rehearsal_placeholder"}), "weights_unexpected"),
        (_b(status="champion", expected=None), "champion_unqualified"),
        (_b(expected=None), "no_eligible_build"),
    ],
    ids=["other-weights", "no-context", "placeholder", "hand-champion-nothing-expected", "first-use-candidate"],
)
def test_what_stays_refused(build: dict[str, Any], code: str) -> None:
    with pytest.raises(RegistryError) as e:
        _resolve(_reg(build))
    assert e.value.reason == code


def test_a_shadow_role_still_needs_its_status() -> None:
    with pytest.raises(RegistryError):
        _resolve(_reg(_b()), role="shadow:judge")


# ------------------------------------------------------------------------------------------------ the gateway
def test_the_gateway_answers_and_writes_the_label(tmp_path: Path) -> None:
    gw = _gw(tmp_path, env=Environment.PRODUCTION, registry=_reg(_b()), http=_mock("j-test"), confirm=ok)
    r = gw.chat(H(Data_Class="D3", Step="s"), _judge_body())
    assert r.status == 200, r.body
    assert r.body["tb"]["qualification"] == "unqualified" and r.headers["X-TB-Qualification"] == "unqualified"
    (rec,) = [x for x in _records(tmp_path) if x["event"] == "llm.gateway.call"]
    assert rec["detail"]["qualification"] == "unqualified"


def test_a_qualified_build_carries_no_label(tmp_path: Path) -> None:
    reg = _reg(_b(status="champion", qualification=qualified(SHA)))
    gw = _gw(tmp_path, env=Environment.PRODUCTION, registry=reg, http=_mock("j-test"), confirm=ok)
    r = gw.chat(H(Data_Class="D3", Step="s"), _judge_body())
    assert r.status == 200 and "qualification" not in r.body["tb"] and "X-TB-Qualification" not in r.headers
    (rec,) = [x for x in _records(tmp_path) if x["event"] == "llm.gateway.call"]
    assert "qualification" not in rec["detail"]


def test_the_client_result_carries_the_label(tmp_path: Path) -> None:
    gw = _gw(tmp_path, env=Environment.PRODUCTION, registry=_reg(_b()), http=_mock("j-test"), confirm=ok)

    def through(req: httpx.Request) -> httpx.Response:
        res = gw.chat(dict(req.headers), json.loads(req.content))
        return httpx.Response(res.status, json=res.body, headers=res.headers)

    client = GatewayClient("http://gateway", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(through)))
    body = _judge_body()
    labels = CallLabels("D3", "screening", "STUDY-1", "s3_note_judgement", "judge", prompt="judge@4", step_id="s",
                        prompt_sha=default_registry().entry("judge", 4).sha256)  # fmt: skip
    res = client.chat(body["messages"], labels, response_format=body["response_format"], max_tokens=512)
    assert res.qualification == "unqualified"


# ------------------------------------------------------------------------------------------------ the answer
def _reply(build: str, qualification: str = "") -> JudgeReply:
    return JudgeReply("pass", 0.9, "two flares this spring", "2026-04-02", "-", call_id=f"c-{build}",
                      build_sha=build, prompt="judge@4", prompt_sha="p", qualification=qualification)  # fmt: skip


class _Fixed:
    def __init__(self, reply: JudgeReply) -> None:
        self.reply = reply

    def judge(self, **_: Any) -> JudgeReply:
        return self.reply


@pytest.mark.parametrize("which", ["judge", "verifier"])
def test_the_pair_says_unqualified_when_either_model_is(which: str) -> None:
    first = _reply("a", "unqualified" if which == "judge" else "")
    second = _reply("b", "unqualified" if which == "verifier" else "")
    got = AgreementJudge(_Fixed(first), _Fixed(second)).judge(
        role="judge", excerpts=[{"text": "She had two flares this spring."}]
    )
    assert got.verdict == "pass" and got.qualification == "unqualified"


def test_the_candidate_list_row_carries_the_label() -> None:
    meta = {"call_id": "c-a", "build_sha": "a", "confidence": 0.9, "qualification": "unqualified"}
    span = {"did": "d1", "quote": "two flares this spring", "date": "2026-04-02"}
    row = verdict_of(Outcome("C-1", "pass", "S3", evidence=[span, meta]), pair=True)
    assert row.evidence is not None and row.evidence.qualification == "unqualified"
    assert row.model_dump(exclude_none=True)["evidence"]["qualification"] == "unqualified"
    plain = verdict_of(Outcome("C-1", "pass", "S3", evidence=[span, {**meta, "qualification": None}]), pair=True)
    assert plain.evidence is not None and "qualification" not in plain.model_dump(exclude_none=True)["evidence"]


# ------------------------------------------------------------------------------------------------ doctor, install
def _site(tmp_path: Path, **pin: Any) -> Path:
    import yaml
    from registry.registry import DEFAULT_PATH

    doc = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    row = next(b for b in doc["builds"] if (b.get("expected") or {}).get("manifest_sha256"))
    out = tmp_path / "registry.site.yaml"
    entry = {"sha256": row["expected"]["manifest_sha256"], "served": {"serving": "j"}, "context_length": 32768, **pin}
    out.write_text(yaml.safe_dump({"builds": {row["build_id"]: entry}}), encoding="utf-8")
    return out


def test_doctor_warns_that_the_pair_runs_unqualified_in_production(tmp_path: Path) -> None:
    out = _site(tmp_path)
    c = doctor.check_registry_pins(
        doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_REGISTRY_OVERRIDE": str(out)}, deploy=tmp_path / "d")
    )
    assert c.status == "WARN" and "labelled unqualified" in c.detail, c.detail
    assert "route nothing" not in c.detail


def test_doctor_says_nothing_of_it_once_a_record_is_promoted(tmp_path: Path) -> None:
    import yaml

    out = _site(tmp_path)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    (entry,) = doc["builds"].values()
    entry.update(status="champion", qualification=qualified(entry["sha256"]))
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    c = doctor.check_registry_pins(
        doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_REGISTRY_OVERRIDE": str(out)}, deploy=tmp_path / "d")
    )
    assert c.status == "PASS", c.detail


def test_the_installer_says_it_at_the_start(tmp_path: Path) -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    start = text.index("# SAFE-1 A1: said at the start")
    assert start < text.index("# HW-003 (D-569): the shipped qualification record")
    block = text[start : text.index("\nfi\n", start) + 4]
    (tmp_path / "deploy" / "qualification" / "gb10").mkdir(parents=True)
    (tmp_path / "deploy" / "qualification" / "gb10" / "r.json").write_text("{}", encoding="utf-8")
    for gpu, said in (("rtxpro6000", True), ("gb10", False)):
        script = f'say() {{ echo "==> $*"; }}\nROOT={tmp_path}; MODE=gpu; GPU={gpu}\n{block}'
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
        assert ("will run labelled unqualified" in r.stdout) is said, (gpu, r.stdout)
