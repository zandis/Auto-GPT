"""Deep review 2026-11-13 (operations): a call let through a half-open breaker (the one probe) that ends in an error
the gateway does not expect (not an ``httpx`` error: a body the client cannot encode, a bug) reported nothing to the
breaker. Its probe flag stayed set, so every later call to that endpoint was refused until the gateway restarted:
the stall sweep needs calls in flight and ``/readyz`` lists only open breakers. The probe is given back."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard as PhiGuard
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment

from tests.unit.test_gateway import H, _judge_body


def _raising(request: httpx.Request) -> httpx.Response:
    raise RuntimeError("not a transport error")


def test_a_half_open_probe_that_raises_gives_the_probe_back(tmp_path: Path) -> None:
    gw = Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(environment=Environment.TEST),
        http=httpx.Client(transport=httpx.MockTransport(_raising)),
        guard=PhiGuard("^\\d{8}$"),
        env={"TB_GATEWAY_RETRY_DELAY_S": "0"},
    )
    lane = gw.load.endpoints["stub"]
    lane.breaker.trip("test")
    lane.breaker.opened_at -= 3600  # the open window is over: the next call is the half-open probe
    with pytest.raises(RuntimeError):
        gw.chat(H(), _judge_body())
    assert lane.breaker.state == "half_open" and lane.breaker.allow(), lane.breaker.snapshot()
    assert lane.snapshot()["in_flight"] == 0  # and its slot was given back
