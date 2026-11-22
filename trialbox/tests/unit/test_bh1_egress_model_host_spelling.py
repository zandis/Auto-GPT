"""Bug-hunt probes BH1-10 and BH1-11: the egress table's "only the gateway reaches a model host" rule.

Entry point: ``deploy/egress.py`` ``allowlist`` (rendered into the host's firewall table and the platform's
NetworkPolicy). The values are the operator's settings: ``EGRESS_EXTRA`` rows and ``NHI_TWPAS_BASE_URL``.

* BH1-10: an ``EGRESS_EXTRA`` row is compared with the model hosts by exact string, so a model host written
  with another letter case or a trailing dot passes the check and the row gives a non-gateway container the model
  host (DNS answers the same addresses for either spelling).
* BH1-11: the NHI host opens a rule for the orchestrator without the model-host check the EDC host gets.

No network: the resolver is a dict.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]

ENV = {
    "TB_ENV": "DEV",
    "CLOUD_LLM_BASE_URL": "https://llm.example.org/v1",
}


def _egress() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_egress_bh1", ROOT / "deploy" / "egress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_egress_bh1"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_exact_spelling_is_refused_today() -> None:
    """The control: the rule holds for the host written as the routing settings write it."""
    eg = _egress()
    assert "llm.example.org" in eg.model_hosts(ENV)
    with pytest.raises(SystemExit, match="model host"):
        eg.allowlist({**ENV, "EGRESS_EXTRA": "orchestrator=llm.example.org:443"})


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-10: EGRESS_EXTRA's model-host check is case and trailing-dot sensitive",
)
@pytest.mark.parametrize("spelling", ["LLM.example.org", "llm.example.org."])
def test_another_spelling_of_a_model_host_is_refused(spelling: str) -> None:
    eg = _egress()
    allows = eg.allowlist({**ENV, "EGRESS_EXTRA": f"orchestrator={spelling}:443"})  # safe: SystemExit
    box = eg.Box(subnets=["172.18.0.0/16"], addresses={"orchestrator": ["172.18.0.3"]})
    dns = {"llm.example.org": ["127.0.0.1"], "LLM.example.org": ["127.0.0.1"], "llm.example.org.": ["127.0.0.1"]}
    script, _ = eg.render(box, allows, lambda h: dns.get(h, []))
    opened = [ln for ln in script.splitlines() if "127.0.0.1" in ln and "orchestrator ->" in ln]
    assert opened == [], f"the orchestrator is given the model host: {opened}"


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-11: NHI_TWPAS_BASE_URL on a model host opens it to the orchestrator unchecked",
)
def test_the_nhi_host_is_not_a_model_host() -> None:
    eg = _egress()
    allows = eg.allowlist({**ENV, "NHI_TWPAS_BASE_URL": "https://llm.example.org/fhir"})  # safe: SystemExit
    hosts = eg.model_hosts(ENV)
    given = [(a.service, a.host) for a in allows if a.host in hosts and a.service != eg.GATEWAY]
    assert given == []
