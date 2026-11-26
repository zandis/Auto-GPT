"""Blocker 4 of lane G's first real-model accuracy run (the owner's ruling D-506, relayed by the integrator on #639,
2026-11-15): the gateway's PHI tripwire guards only a route that leaves the box, and a declared setting turns it off.

The tripwire refused every D0-D2 call whose text looked like an identifier, whatever the route: 2 of 16 public
protocols were refused at compile (a sponsor compound code "RO7507062" read as a passport number; a zh-Hant protocol
as a name), though the call would have stayed on the box. Now:

* a hit drops the candidates outside the box (zones other than ``perimeter``); the call goes on to an on-box model;
* it is refused (``phi_tripwire``) only when no candidate on the box is left;
* ``TB_GATEWAY_PHI_TRIPWIRE=off`` turns the check off; it is on by default, for every route that leaves the box;
* the audit line says what happened (``hit:<kinds>:on_box``, ``hit:<kinds>`` with the refusal, ``off``).

Synthetic text, the stub upstream, no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology

from tests.unit.test_gateway import JUDGE_VARS, H, _judge_body, _records

PHI = {**JUDGE_VARS, "excerpts": [{"date": "2026-10-01", "note_type": "x", "text": "身分證 A123456789"}]}


def _gw(tmp_path: Path, env: Environment, phi_tripwire: bool = True, http: Any = None) -> Gateway:
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub

    return Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(topology=Topology.A, environment=env, phi_tripwire=phi_tripwire),
        http=http or TestClient(stub),
        guard=Guard("^\\d{8}$"),
        env={},
    )


def _last(tmp_path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        r["detail"] for r in _records(tmp_path) if isinstance(r.get("detail"), dict) and r["detail"].get("guard")
    ]
    return rows[-1]


def test_a_hit_on_a_route_that_stays_on_the_box_is_answered(tmp_path: Path) -> None:
    gw = _gw(tmp_path, Environment.TEST)  # every TEST candidate is on the box
    res = gw.chat(H(), _judge_body(PHI))
    assert res.status == 200, res.body
    rec = _last(tmp_path)
    assert rec["guard"].startswith("hit:") and rec["guard"].endswith(":on_box") and rec["zone"] == "perimeter"


def test_a_hit_drops_the_candidates_outside_the_box(tmp_path: Path) -> None:
    """DEV routes D0 to the stub on the box and to a public endpoint: a hit keeps the call on the box."""
    gw = _gw(tmp_path, Environment.DEV)
    res = gw.chat(H(), _judge_body(PHI))
    assert res.status == 200, res.body
    assert _last(tmp_path)["zone"] == "perimeter"


def test_a_hit_on_a_route_that_only_leaves_the_box_is_refused(tmp_path: Path) -> None:
    gw = _gw(tmp_path, Environment.DEV)
    res = gw.chat(H(), {**_judge_body(PHI), "model": "j-workhorse"})  # a public endpoint only
    assert res.status == 403 and res.body["error"]["code"] == "phi_tripwire"


def test_the_setting_turns_it_off(tmp_path: Path) -> None:
    """Review: the first version of this test passed on a refusal of another kind. The audit line now says ``off``
    and the call is answered."""
    gw = _gw(tmp_path, Environment.TEST, phi_tripwire=False)
    res = gw.chat(H(), _judge_body(PHI))
    assert res.status == 200, res.body
    assert _last(tmp_path)["guard"] == "off"


def test_a_tripwire_turned_off_is_logged_when_the_gateway_starts(tmp_path: Path, caplog: Any) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        _gw(tmp_path, Environment.TEST, phi_tripwire=False)
    assert any("PHI tripwire is off" in r.getMessage() for r in caplog.records)


def _protocol_call(policy: Any, topology: Topology, tmp_path: Path) -> tuple[Any, list[str]]:
    """A D1 protocol call holding an identifier; the registry is stubbed to say which endpoints were tried."""
    from registry.registry import RegistryError
    from tb_common.llm import load_prompt, render
    from tb_contracts import inline_schema
    from tb_llm import json_schema_format

    gw = Gateway(
        policy, Registry.load(), AuditLog(tmp_path / "audit"),
        GatewayConfig(topology=topology, environment=Environment.PRODUCTION, cloud_opt_in=True),
        guard=Guard("^\\d{8}$"), env={},
    )  # fmt: skip
    tried: list[str] = []

    def resolve(alias: str, ep: str, **kw: Any) -> Any:
        tried.append(f"{alias}@{ep}")
        raise RegistryError("stop", "test")

    gw.registry.resolve = resolve  # type: ignore[method-assign,assignment]
    pp = load_prompt("ir_extract_v2")
    h = {"X-TB-Caller": "criteria-compiler", "X-TB-Role": "extract_criteria", "X-TB-Data-Class": "D1",
         "X-TB-Purpose": "protocol_ingest", "X-TB-Prompt": "ir_extract@2", "X-TB-Flags": "sponsor_consent",
         "X-TB-Study": "S-1", "X-TB-Context-Of-Use": "protocol_ir"}  # fmt: skip
    h["X-TB-Prompt-Sha"] = gw.prompts.get("ir_extract", 2, environment="PRODUCTION", patient=False).sha256
    body = {
        "messages": render(pp, {"ruleset": "GZQO", "language": "en",
                                "criteria": [{"text": "Age >= 18, contact 身分證 A123456789", "kind": "inclusion"}]}),
        "response_format": json_schema_format("ir", inline_schema(pp.meta.output_schema)),
    }  # fmt: skip
    return gw.chat(h, body), tried


def test_on_topology_b_the_tenant_is_not_the_box(tmp_path: Path) -> None:
    """Review: on topology B the perimeter is the tenant's serving router, off the box (D-142): a hit is refused."""
    res, tried = _protocol_call(RoutingPolicy.load(), Topology.B, tmp_path)
    assert res.body["error"]["code"] == "phi_tripwire" and tried == []


def test_on_topology_c_a_hit_is_refused(tmp_path: Path) -> None:
    """Only topology A's perimeter is the box (D-142)."""
    res, tried = _protocol_call(RoutingPolicy.load(), Topology.C, tmp_path)
    assert res.body["error"]["code"] == "phi_tripwire" and tried == []


@pytest.mark.parametrize(
    "value,on",
    [(None, True), ("on", True), ("off", False), ("OFF", False), ("0", False), ("false", False), ("disabled", True)],
)
def test_the_setting_is_read_and_on_by_default(value: str | None, on: bool) -> None:
    env = {} if value is None else {"TB_GATEWAY_PHI_TRIPWIRE": value}
    assert GatewayConfig.from_env(env).phi_tripwire is on


def test_a_value_it_does_not_know_keeps_it_on_and_says_so(caplog: Any) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        assert GatewayConfig.from_env({"TB_GATEWAY_PHI_TRIPWIRE": "disabled"}).phi_tripwire is True
    assert any("TB_GATEWAY_PHI_TRIPWIRE" in r.getMessage() for r in caplog.records)


def test_the_setting_is_declared() -> None:
    from tb_common.config import DECLARED

    d = DECLARED["TB_GATEWAY_PHI_TRIPWIRE"]
    assert d.default == "on"


def test_a_public_protocols_compound_code_is_not_refused_on_the_box(tmp_path: Path) -> None:
    """Lane G's case: "RO7507062" in a public protocol, on a route that stays on the box."""
    gw = _gw(tmp_path, Environment.TEST)
    v = {**JUDGE_VARS, "excerpts": [{"date": "2026-10-01", "note_type": "x", "text": "Prior treatment with RO7507062"}]}
    assert gw.chat(H(), _judge_body(v)).status == 200


@pytest.mark.parametrize("what", ["", "schema", "tool_call", "picture"])
def test_every_part_of_a_call_that_would_leave_is_read(tmp_path: Path, what: str) -> None:
    """OCR 1523-13: the edge read the messages' text only. A hosted build pinned to its provider, so the call gets as
    far as the door; a prompt of no registry (DEV), so its parts are the caller's own."""
    from tests.unit.test_provider_pin import _registry

    sent: list[dict[str, Any]] = []

    class Http:
        def post(self, _url: str, **kw: Any) -> Any:
            sent.append(kw)
            raise httpx.ConnectError("no network in a test")

    gw = _gw(tmp_path, Environment.DEV, http=Http())
    gw.registry = _registry()
    body: dict[str, Any] = {"messages": [{"role": "user", "content": "How many of 85?"}], "model": "j-workhorse",
                            "response_format": {"type": "json_schema", "json_schema": {
                                "name": "a", "schema": {"type": "object"}}}}  # fmt: skip
    if what == "schema":
        body["response_format"]["json_schema"]["schema"]["description"] = "身分證 A123456789"
    elif what == "tool_call":
        body["messages"][0]["tool_calls"] = [{"function": {"name": "f", "arguments": "身分證 A123456789"}}]
    elif what == "picture":
        picture = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
        body["messages"][0]["content"] = [{"type": "text", "text": "How many?"}, picture]
    res = gw.chat(H(Prompt="own@1"), body)
    assert bool(sent) == (what == ""), res.body  # the clean call goes out
    assert (res.body["error"]["code"] == "phi_tripwire") == (what != ""), res.body
