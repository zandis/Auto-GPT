"""Card 9g-14 (D-1348; review 01 section 7.2): the REDCap host on the egress allow-list by name.

A box configured with a REDCap URL opens exactly that host and port to the orchestrator, and nothing wider; no URL
opens nothing; a URL egress cannot open is refused with a line naming the setting. Host names only (example.org and
.test names): no REDCap source, SQL or text.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _egress() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_egress_redcap", ROOT / "deploy" / "egress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_egress_redcap"] = mod
    spec.loader.exec_module(mod)
    return mod


def rows(env: dict[str, str]) -> list[tuple[str, str, int]]:
    return [(a.service, a.host, a.port) for a in _egress().allowlist(env, routing=None)]


@pytest.mark.parametrize(
    ("url", "want"),
    [
        ("https://redcap.hosp.test/", ("redcap.hosp.test", 443)),
        ("https://redcap.hosp.test/api/", ("redcap.hosp.test", 443)),
        ("https://REDCap.Hosp.test./redcap/api/", ("redcap.hosp.test", 443)),
        ("https://redcap.hosp.test:8443/api/", ("redcap.hosp.test", 8443)),
        ("https://10.20.0.7/api/", ("10.20.0.7", 443)),
        (" https://redcap.hosp.test/ ", ("redcap.hosp.test", 443)),
    ],
)
def test_the_redcap_url_opens_exactly_its_host_and_port_to_the_orchestrator(url: str, want: tuple[str, int]) -> None:
    assert rows({"TB_REDCAP_API_URL": url}) == [("orchestrator", *want)]


def test_the_short_name_is_read_when_the_tb_name_is_empty() -> None:
    # the connector's own rule (services/edc_backend/config.py): REDCAP_API_URL when TB_REDCAP_API_URL is empty
    assert rows({"TB_REDCAP_API_URL": "", "REDCAP_API_URL": "https://rc.hosp.test/"}) == [
        ("orchestrator", "rc.hosp.test", 443)
    ]
    both = {"TB_REDCAP_API_URL": "https://a.hosp.test/", "REDCAP_API_URL": "https://b.hosp.test/"}
    assert rows(both) == [("orchestrator", "a.hosp.test", 443)]


@pytest.mark.parametrize("env", [{}, {"TB_REDCAP_API_URL": ""}, {"TB_REDCAP_API_URL": "   "}])
def test_no_redcap_configured_adds_nothing(env: dict[str, str]) -> None:
    assert rows(env) == []


def test_the_in_process_simulator_opens_nothing() -> None:
    assert rows({"TB_REDCAP_API_URL": "inproc://rc-sim"}) == []


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://redcap.hosp.test/api/", "only https"),
        ("redcap.hosp.test", "only https"),
        ("ftp://redcap.hosp.test/", "only https"),
        ("https:///api/", "no host"),
        ("https://user:pw@redcap.hosp.test/", "a user or password"),
        ("https://redcap.hosp.test:https/", "the port is not a number"),
        ("https://redcap.hosp.test:99999/", "the port is not a number"),
    ],
)
def test_a_malformed_url_is_refused_with_a_plain_line(url: str, why: str) -> None:
    with pytest.raises(SystemExit) as exc:
        rows({"TB_REDCAP_API_URL": url})
    line = str(exc.value)
    assert line.startswith("TB_REDCAP_API_URL is not") and why in line  # the line names the setting it read
    assert "pw" not in line  # never the URL itself: it may carry a password


def test_the_short_name_is_named_when_it_is_the_one_refused() -> None:
    with pytest.raises(SystemExit, match="^REDCAP_API_URL is not"):
        rows({"REDCAP_API_URL": "http://rc.hosp.test/"})


def test_the_redcap_host_is_never_a_model_host() -> None:
    eg = _egress()
    env = {"CLOUD_LLM_BASE_URL": "https://llm.example.org/v1", "TB_REDCAP_API_URL": "https://llm.example.org/"}
    with pytest.raises(SystemExit, match="model host"):
        eg.allowlist(env, routing=None)


def test_egress_extra_keeps_working_beside_it() -> None:
    env = {
        "TB_REDCAP_API_URL": "https://redcap.hosp.test/api/",
        "EGRESS_EXTRA": "orchestrator=redcap2.hosp.test:443,authelia=ldap.hosp.test:636",
    }
    assert rows(env) == [
        ("orchestrator", "redcap.hosp.test", 443),
        ("orchestrator", "redcap2.hosp.test", 443),
        ("authelia", "ldap.hosp.test", 636),
    ]
    # the site's old hand-written line for the same host still applies (the rule is the same pair twice)
    same = {"TB_REDCAP_API_URL": "https://redcap.hosp.test/", "EGRESS_EXTRA": "orchestrator=redcap.hosp.test:443"}
    assert set(rows(same)) == {("orchestrator", "redcap.hosp.test", 443)}


def test_read_env_takes_the_redcap_url_from_the_file_and_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eg = _egress()
    monkeypatch.delenv("TB_REDCAP_API_URL", raising=False)
    monkeypatch.delenv("REDCAP_API_URL", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("TB_REDCAP_API_URL=https://redcap.hosp.test/api/\n", encoding="utf-8")
    assert eg.read_env(dotenv)["TB_REDCAP_API_URL"] == "https://redcap.hosp.test/api/"
    monkeypatch.setenv("REDCAP_API_URL", "https://rc.hosp.test/")
    assert eg.read_env(None)["REDCAP_API_URL"] == "https://rc.hosp.test/"


def test_the_rendered_rule_is_one_host_one_port() -> None:
    eg = _egress()
    allows = eg.allowlist({"TB_REDCAP_API_URL": "https://redcap.hosp.test:8443/api/"}, routing=None)
    box = eg.Box(subnets=["172.30.0.0/24"], addresses={"orchestrator": ["172.30.0.5"]})
    script, warnings = eg.render(box, allows, resolver=lambda h: ["192.0.2.10"] if h == "redcap.hosp.test" else [])
    rules = [ln for ln in script.splitlines() if "redcap.hosp.test" in ln]
    assert warnings == []
    assert len(rules) == 2  # the forward chain and the input chain (an allowed destination on the host)
    for ln in rules:
        assert "saddr { 172.30.0.5 }" in ln and "daddr { 192.0.2.10 }" in ln and "tcp dport 8443 accept" in ln
