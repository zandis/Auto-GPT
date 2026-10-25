"""Provider pins for hosted builds (spec v4 §8.4, §8.10; S1-07, S1-14, MOD-6, MOD-7, LLM-33).

A hosted build (OpenRouter) is pinned by a dated provider descriptor whose SHA-256 is the build's ``sha256``; the
gateway asks for that provider only and refuses a response from another model or provider. All HTTP is mocked: no
test reaches a model host, and no test uses a real key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from registry.registry import (
    Registry,
    RegistryError,
    apply_override,
    check_served,
    provider_pin_sha,
    provider_routing,
)
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology
from tb_llm import CallLabels, GatewayError, GatewayRefused
from tb_testkit.req import spec_requirement_ids

from tools import bakeoff_live, pin_provider
from tools.pin_model import PinError

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
FAKE_KEY = "test-key-not-real-0000"
DESC: dict[str, Any] = {
    "endpoint": "openrouter",
    "model": "acme/model-7b",
    "canonical_slug": "acme/model-7b-20260401",
    "created": 1775000000,
    "provider": "AcmeCloud",
    "provider_tag": "acmecloud/fp8",
    "quantization": "fp8",
    "pinned_at": "2026-10-25",
}
REQ = ("S1-07", "S1-14", "MOD-6", "MOD-7", "LLM-33")


def _override(build: str = "or-gpt-oss-120b", desc: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    d = desc or DESC
    entry: dict[str, Any] = {"sha256": provider_pin_sha(d), "served": {"openrouter": d["model"]}, "provider_pin": d}
    entry.update(fields)
    return {"kind": "registry-site-override", "builds": {build: entry}}


def _registry(build: str = "or-gpt-oss-120b", **fields: Any) -> Registry:
    return Registry(apply_override(COMMITTED, _override(build, **fields)))


def test_requirement_ids_exist() -> None:
    assert set(REQ) <= spec_requirement_ids()


# ------------------------------------------------------------------------------------------------ registry
@pytest.mark.req("S1-14", "S1-07")
def test_descriptor_digest_is_canonical_and_complete() -> None:
    sha = provider_pin_sha(DESC)
    assert sha == provider_pin_sha(dict(reversed(list(DESC.items()))))  # key order does not matter
    assert sha != provider_pin_sha({**DESC, "provider_tag": "acmecloud/fp4"})  # another provider is another build
    assert sha != provider_pin_sha({**DESC, "canonical_slug": "acme/model-7b-20261001"})  # another dated version
    for bad in ({k: v for k, v in DESC.items() if k != "provider"}, {**DESC, "extra": 1}, {**DESC, "created": "x"}):
        with pytest.raises(ValueError, match="provider pin"):
            provider_pin_sha(bad)


@pytest.mark.req("S1-14", "S1-07", "MOD-7")
def test_hosted_build_resolves_only_with_a_matching_descriptor() -> None:
    reg = _registry()
    res = reg.resolve("j-workhorse", "openrouter", role="bakeoff", env=Environment.DEV)
    assert res.build.build_id == "or-gpt-oss-120b" and res.served_name == "acme/model-7b"
    assert res.build.sha256 == provider_pin_sha(DESC) and reg.version.startswith(Registry.load().version + "+site.")
    with pytest.raises(RegistryError) as e:  # candidate status: never in production
        reg.resolve("j-workhorse", "openrouter", role="judge", env=Environment.PRODUCTION)
    assert e.value.reason in ("build_unpinned", "no_eligible_build")
    with pytest.raises(ValueError, match="digest of its provider_pin"):
        _registry(sha256="cd" * 32)
    with pytest.raises(ValueError, match="served\\[openrouter\\]"):
        _registry(served={"openrouter": "acme/other"})
    with pytest.raises(ValueError, match="own endpoint only"):
        _registry(served={"openrouter": "acme/model-7b", "serving": "local-name"})
    bare = {"kind": "registry-site-override", "builds": {"or-gpt-oss-120b": {"sha256": "cd" * 32}}}
    with pytest.raises(ValueError, match="pinned by a provider_pin descriptor"):
        Registry(apply_override(COMMITTED, bare))
    with pytest.raises(ValueError, match="only for serving: hosted"):
        _registry(build="gpt-oss-120b-candidate")  # a local (vllm) build is pinned by weights only


@pytest.mark.req("S1-14", "S1-07")
def test_unpinned_hosted_builds_stay_refused() -> None:
    reg = Registry.load(ROOT / "models" / "registry.yaml")
    hosted = [b for b in reg.builds if b.serving == "hosted"]
    assert len(hosted) >= 4 and all(b.sha256 is None and b.provider_pin is None for b in hosted)
    with pytest.raises(RegistryError) as e:
        reg.resolve("j-workhorse", "openrouter", role="bakeoff", env=Environment.DEV)
    assert e.value.reason == "build_unpinned"


@pytest.mark.req("MOD-6", "S1-14")
def test_served_echo_checks_model_and_provider() -> None:
    res = _registry().resolve("j-workhorse", "openrouter", role="bakeoff", env=Environment.DEV)
    check_served(res, "acme/model-7b", "AcmeCloud")
    with pytest.raises(RegistryError) as e:
        check_served(res, "acme/model-7b", "OtherCloud")
    assert e.value.reason == "served_provider_mismatch"
    with pytest.raises(RegistryError) as e:
        check_served(res, "acme/model-7b-v2", "AcmeCloud")
    assert e.value.reason == "served_model_mismatch"
    route = provider_routing(DESC)
    assert route == {
        "order": ["acmecloud/fp8"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
        "quantizations": ["fp8"],
    }
    assert "quantizations" not in provider_routing({**DESC, "quantization": "unknown"})


# ------------------------------------------------------------------------------------------------ gateway
class Upstream:
    def __init__(self, provider: str = "AcmeCloud", model: str = "acme/model-7b") -> None:
        self.provider, self.model = provider, model
        self.requests: list[tuple[dict[str, Any], dict[str, str]]] = []

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            self.requests.append((json.loads(req.content), dict(req.headers)))
            return httpx.Response(
                200,
                json={
                    "model": self.model,
                    "provider": self.provider,
                    "choices": [{"message": {"content": '{"label": "included", "evidence": [1]}'}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.00042},
                },
            )

        return httpx.Client(transport=httpx.MockTransport(handler))


def _gateway(tmp_path: Path, upstream: Upstream, reg: Registry) -> Gateway:
    return Gateway(
        RoutingPolicy.load(),
        reg,
        AuditLog(tmp_path / "audit"),
        GatewayConfig(topology=Topology.A, environment=Environment.DEV),
        http=upstream.client(),
        guard=Guard(None),
        env={"OPENROUTER_API_KEY": FAKE_KEY},
    )


def _headers(data_class: str = "D0") -> dict[str, str]:
    return CallLabels(
        data_class=data_class,
        purpose="evaluation",
        study_id="none",
        context_of_use="bakeoff_judge_ml",
        role="bakeoff",
        prompt="mlbench_judge@1",
    ).headers("eval")


def _body(**extra: Any) -> dict[str, Any]:
    fmt = {"type": "json_schema", "json_schema": {"name": "judge", "schema": bakeoff_live.bounded_schema()}}
    return {"model": "j-workhorse", "messages": [{"role": "user", "content": "criterion x"}], "response_format": fmt}


def _audit(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted((tmp_path / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]


@pytest.mark.req("S1-14", "MOD-6", "LLM-33")
def test_gateway_holds_the_call_to_the_pinned_provider(tmp_path: Path) -> None:
    up = Upstream()
    gw = _gateway(tmp_path, up, _registry())
    body = {**_body(), "provider": {"order": ["somewhere-else"], "allow_fallbacks": True}}  # caller tries to steer
    res = gw.chat(_headers(), body)
    assert res.status == 200 and res.body["tb"]["build_id"] == "or-gpt-oss-120b"
    assert res.body["tb"]["build_sha"] == provider_pin_sha(DESC)
    sent, headers = up.requests[0]
    assert sent["model"] == "acme/model-7b" and sent["provider"] == provider_routing(DESC)
    assert sent["temperature"] == 0 and sent["seed"] == 20261025  # forced sampling (MOD-4)
    assert headers["authorization"] == f"Bearer {FAKE_KEY}"  # the key goes upstream only
    records = _audit(tmp_path)
    assert records[-1]["detail"]["cost"] == pytest.approx(0.00042)  # the provider's reported cost
    assert FAKE_KEY not in json.dumps(records) and "authorization" not in json.dumps(records).lower()
    refused = gw.chat(_headers("D1"), _body())  # LLM-33: OpenRouter takes D0 only, pinned or not
    assert refused.status == 403 and up.requests.__len__() == 1


@pytest.mark.req("S1-14", "MOD-6")
def test_gateway_refuses_a_response_from_another_provider_or_model(tmp_path: Path) -> None:
    for up, code in ((Upstream(provider="OtherCloud"), "served_provider_mismatch"), (Upstream(model="x/y"), None)):
        gw = _gateway(tmp_path / code if code else tmp_path / "model", up, _registry())
        res = gw.chat(_headers(), _body())
        assert res.status == 502
        assert res.body["error"]["code"] == (code or "served_model_mismatch")


@pytest.mark.req("S1-14", "S1-07")
def test_weight_pin_alone_cannot_reach_a_hosted_endpoint(tmp_path: Path) -> None:
    doc = json.loads(json.dumps(COMMITTED))
    for b in doc["builds"]:
        if b["build_id"] == "nemotron-3-nano-candidate":  # a local build, weight-pinned, with an openrouter name
            b.update(sha256="ab" * 32, served={"openrouter": "acme/model-7b"})
    up = Upstream()
    res = _gateway(tmp_path, up, Registry(doc)).chat(_headers(), _body())
    assert res.status == 403 and res.body["error"]["code"] == "provider_unpinned" and not up.requests


# ------------------------------------------------------------------------------------------------ pin tool
def _catalogue(slug: str = "acme/model-7b-20260401") -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        assert "authorization" not in req.headers  # the public model list needs no key
        if req.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"data": [{"id": "acme/model-7b", "canonical_slug": slug, "created": 1775000000}]}
            )
        if req.url.path.endswith("/models/acme/model-7b/endpoints"):
            full = ["response_format", "structured_outputs", "seed", "temperature"]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "endpoints": [
                            {
                                "provider_name": "Cheap",
                                "tag": "cheap",
                                "quantization": "fp4",
                                "pricing": {"prompt": "0.00000001", "completion": "0.00000002"},
                                "supported_parameters": ["temperature"],
                            },
                            {
                                "provider_name": "AcmeCloud",
                                "tag": "acmecloud/fp8",
                                "quantization": "fp8",
                                "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
                                "supported_parameters": full,
                            },
                            {
                                "provider_name": "Dear",
                                "tag": "dear",
                                "quantization": "bf16",
                                "pricing": {"prompt": "0.000001", "completion": "0.000004"},
                                "supported_parameters": full,
                            },
                        ]
                    }
                },
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.req("S1-14", "S1-07")
def test_pin_provider_writes_a_valid_override_and_verifies_it(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    out = tmp_path / "site" / "registry.site.yaml"
    desc, sha, offer, path = pin_provider.pin(
        "or-gpt-oss-120b", "acme/model-7b", http=_catalogue(), out=out, now=datetime(2026, 10, 25, tzinfo=UTC)
    )
    assert offer.tag == "acmecloud/fp8"  # cheapest endpoint that honours structured output and seed
    assert desc == DESC and sha == provider_pin_sha(DESC)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["builds"]["or-gpt-oss-120b"]["provider_pin"] == DESC and FAKE_KEY not in path.read_text()
    reg = Registry.load(ROOT / "models" / "registry.yaml", out)
    assert reg.build("or-gpt-oss-120b").pinned
    assert pin_provider.verify("or-gpt-oss-120b", http=_catalogue(), out=out)[0]
    ok, msg = pin_provider.verify("or-gpt-oss-120b", http=_catalogue("acme/model-7b-20261020"), out=out)
    assert not ok and "now points at" in msg  # the provider moved the id to a new dated version
    with pytest.raises(PinError, match="does not serve"):
        pin_provider.pin("or-gpt-oss-120b", "acme/model-7b", http=_catalogue(), provider="nobody", out=out)
    with pytest.raises(PinError, match="not a hosted build"):
        pin_provider.pin("gpt-oss-120b-candidate", "acme/model-7b", http=_catalogue(), out=out)


# ------------------------------------------------------------------------------------------------ live client
class FlakyClient:
    """GatewayClient stand-in: fails ``fails`` times with ``exc``, then answers."""

    def __init__(self, exc: Exception, fails: int) -> None:
        self.exc, self.fails, self.calls = exc, fails, 0

    def chat(self, *_: Any, **__: Any) -> Any:
        from tb_llm import ChatResult

        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc
        payload = {
            "model": "acme/model-7b",
            "provider": "AcmeCloud",
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"cost": 0.001, "completion_tokens_details": {"reasoning_tokens": 7}},
        }
        return ChatResult(
            "x", payload, "acme/model-7b", "c1", "j-workhorse", "ab" * 32, "miss", 10, 3, {"label": "Excluded."}
        )


@pytest.mark.req("S1-14")
def test_live_judge_retries_upstream_failures_but_not_refusals() -> None:
    sleeps: list[float] = []
    row = bakeoff_live.Row("b", "en", "1", "exclusion", "excluded", "excluded")
    client = FlakyClient(GatewayRefused("upstream_failed", 502, "HTTP 503"), 2)
    out = bakeoff_live.judge_once(client, row, [], max_tokens=64, sleep=sleeps.append)
    assert out.pred == "excluded" and out.valid and out.attempts == 3 and sleeps == [2.0, 4.0]
    assert out.cost_usd == 0.001 and out.provider == "AcmeCloud" and out.reasoning_tokens == 7 and out.done
    row2 = bakeoff_live.Row("b", "en", "2", "exclusion", "excluded", "excluded")
    out2 = bakeoff_live.judge_once(
        FlakyClient(GatewayRefused("phi_tripwire", 403, "x"), 9), row2, [], max_tokens=64, sleep=sleeps.append
    )
    assert out2.refused == "phi_tripwire" and out2.attempts == 1 and out2.done  # a policy refusal is final
    row3 = bakeoff_live.Row("b", "en", "3", "exclusion", "excluded", "excluded")
    out3 = bakeoff_live.judge_once(FlakyClient(GatewayError("down"), 99), row3, [], max_tokens=64, sleep=lambda s: None)
    assert out3.error == "GatewayError" and out3.attempts == 5 and not out3.done  # re-run on resume


@pytest.mark.req("S1-14")
def test_live_metrics_and_csv_round_trip(tmp_path: Path) -> None:
    from tools import mlbench

    pairs = mlbench.load_pairs()[:4]
    rows = []
    for i, p in enumerate(pairs):
        r = bakeoff_live.Row("b", "en", p.annotation_id, p.criterion_type, p.expert_label, p.gpt4_label)
        r.call_id, r.valid, r.pred, r.latency_s, r.cost_usd = (
            f"c{i}",
            i != 3,
            p.expert_label if i != 3 else "",
            1.0 + i,
            0.01,
        )
        rows.append(r)
    path = tmp_path / "predictions_b.csv"
    bakeoff_live.write_rows(path, rows)
    back = bakeoff_live.read_rows(path)
    assert [asdict_row(r) for r in back] == [asdict_row(r) for r in sorted(rows, key=lambda r: int(r.annotation_id))]
    m = bakeoff_live.metrics(back)["en"]
    assert m["n"] == 4 and m["invalid_rate"] == 0.25 and m["cost_usd"] == pytest.approx(0.04)
    assert m["latency_p50_s"] in (2.0, 3.0) and m["latency_p95_s"] == 4.0
    total = sum(sum(v.values()) for t in m["confusion"].values() for v in t.values())
    assert total == 4
    assert "sk-" not in path.read_text()


def asdict_row(r: bakeoff_live.Row) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(r)
