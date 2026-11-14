"""NEW-WIN-10 (D-613; owner ruling D-503): the host check on a Windows 10 workstation.

The facts are written as host_facts.ps1 prints them; nothing ran on Windows (P-0 Part 9)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
FACTS_PS1 = (ROOT / "deploy/windows/host_facts.ps1").read_text(encoding="utf-8")
PS1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")


def _policy() -> Any:
    spec = importlib.util.spec_from_file_location("wsl2_policy_w10", ROOT / "deploy/windows/wsl2_policy.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lines(facts: dict[str, str], strict: bool = True) -> list[str]:
    policy = _policy()
    v = policy.Verdicts(strict)
    policy.check_network_form(facts, v)
    return list(v.lines)


WIN10_OK = {"windows_build": "19045", "console_proxy_to": "172.28.14.5", "console_proxy_task": "Ready"}


def test_a_windows_10_box_with_its_forwarding_passes_and_is_told_its_support_has_ended() -> None:
    lines = _lines(WIN10_OK)
    assert lines[0].startswith("WARN  Windows 10 (build 19045): Microsoft's standard support ended in October 2025")
    assert "Extended Security Updates (ESU)" in lines[0]
    assert (
        lines[1]
        == "PASS  console forwarding: port 443 to WSL2 at 172.28.14.5, kept pointed by TrialBox-Console-Proxy (Ready)"
    )


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"console_proxy_to": ""}, "no port-proxy row passes port 443 to WSL2"),
        ({"console_proxy_task": "missing"}, "the task TrialBox-Console-Proxy is missing"),
        ({"console_proxy_task": "Disabled"}, "the task TrialBox-Console-Proxy is Disabled"),
    ],
)
def test_a_windows_10_box_without_its_forwarding_fails_on_a_production_box(change: dict[str, str], says: str) -> None:
    lines = _lines({**WIN10_OK, **change})
    assert any(ln.startswith("FAIL") and says in ln for ln in lines), lines
    assert any(ln.startswith("WARN") and says in ln for ln in _lines({**WIN10_OK, **change}, strict=False))


def test_windows_11_with_mirrored_networking_has_no_forwarding_to_check_and_no_support_warning() -> None:
    assert _lines({"windows_build": "26100", "console_proxy_to": "", "console_proxy_task": "missing"}) == []


def test_a_windows_11_build_before_22h2_needs_the_forwarding_too_but_is_not_windows_10() -> None:
    lines = _lines({"windows_build": "22000", "console_proxy_to": "", "console_proxy_task": "missing"})
    assert len(lines) == 1 and lines[0].startswith("FAIL  console forwarding (build 22000")


def test_facts_of_an_earlier_release_add_no_line() -> None:
    assert _lines({"facts_version": "1"}) == []


def test_the_facts_and_the_installer_name_the_same_build_task_and_port() -> None:
    policy = _policy()
    assert f"$script:TbMirroredBuild = {policy.MIRRORED_BUILD}" in PS1
    for fact in ("windows_build", "console_proxy_to", "console_proxy_task"):
        assert f'Fact "{fact}"' in FACTS_PS1, fact
    assert '"TrialBox-Console-Proxy"' in FACTS_PS1 and '$script:TbProxyTask = "TrialBox-Console-Proxy"' in PS1
    assert "interface portproxy show v4tov4" in FACTS_PS1  # read only: show, never add or set
    assert "portproxy add" not in FACTS_PS1 and "portproxy set" not in FACTS_PS1
