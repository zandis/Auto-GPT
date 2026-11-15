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

import pytest
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology

from tests.unit.test_gateway import JUDGE_VARS, H, _judge_body, _mock, _records

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
    gw = _gw(tmp_path, Environment.DEV, phi_tripwire=False, http=_mock("echo"))
    res = gw.chat(H(), {**_judge_body(PHI), "model": "j-workhorse"})
    assert res.body.get("error", {}).get("code") != "phi_tripwire"


@pytest.mark.parametrize(
    "value,on", [(None, True), ("on", True), ("off", False), ("OFF", False), ("0", False), ("false", False)]
)
def test_the_setting_is_read_and_on_by_default(value: str | None, on: bool) -> None:
    env = {} if value is None else {"TB_GATEWAY_PHI_TRIPWIRE": value}
    assert GatewayConfig.from_env(env).phi_tripwire is on


def test_the_setting_is_declared() -> None:
    from tb_common.config import DECLARED

    d = DECLARED["TB_GATEWAY_PHI_TRIPWIRE"]
    assert d.default == "on"


def test_a_public_protocols_compound_code_is_not_refused_on_the_box(tmp_path: Path) -> None:
    """Lane G's case: "RO7507062" in a public protocol, on a route that stays on the box."""
    gw = _gw(tmp_path, Environment.TEST)
    v = {**JUDGE_VARS, "excerpts": [{"date": "2026-10-01", "note_type": "x", "text": "Prior treatment with RO7507062"}]}
    assert gw.chat(H(), _judge_body(v)).status == 200
