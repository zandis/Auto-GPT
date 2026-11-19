"""10G-4 (review 16 item 16-16, D-1327): the threat model is reviewed per release and cites only what exists.

``docs/security/11-threat-model.md`` names the release it was reviewed for; the version is written in one place
(``[project] version`` in ``pyproject.toml``, ``tools.release.version``), so the pull request that sets a new version
fails here until the threat model is reviewed and names it, as ``test_changelog_has_the_current_version`` holds the
changelog. Every path, test and finding the page cites must exist: a control is never claimed by a test that is gone.
The last test is a control the page cites that no other test held: the base compose's networks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import release

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "security" / "11-threat-model.md"
REGISTER = ROOT / "docs" / "handover" / "findings-register.md"
OWN_FINDINGS = (
    ROOT / "docs" / "handover" / "threat-model-2026-11-19" / "findings.json",
    ROOT / "docs" / "handover" / "tls-policy-2026-11-19" / "findings.json",
)
REVIEWED = re.compile(r"\*\*Reviewed for release:\*\*\s+(\S+)\s+\((\d{4}-\d{2}-\d{2}),")
FINDING_ID = re.compile(r"\b(V\d+-\d{2}|H10G48?-\d{2})\b")
CODE = re.compile(r"`([^`\s]+)`")
TOP = ("deploy", "docs", "services", "tools", "tests", "libs")

pytestmark = pytest.mark.nodb


def _text() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_threat_model_names_the_current_release() -> None:
    m = REVIEWED.search(_text().replace("\n", " "))
    assert m, "the threat model has no '**Reviewed for release:** <version> (<date>, ...' line"
    assert m.group(1) == release.version(), (
        f"the version moved to {release.version()}; the threat model was reviewed for {m.group(1)}: review "
        "docs/security/11-threat-model.md for this release and move its 'Reviewed for release' line"
    )


def _rows() -> list[str]:
    return [line for line in _text().splitlines() if line.startswith("| ") and not line.startswith("| ---")]


def test_every_path_and_test_the_threat_model_cites_exists() -> None:
    problems = []
    for line in _text().splitlines():
        for span in CODE.findall(line):
            cited = "/" in span and not any(c in span for c in "<>{}$*") and span.split("/")[0] in TOP
            if cited and not (ROOT / span.rstrip(".,;:")).exists():
                problems.append(f"no such path: {span}")
    for row in _rows():
        files = [ROOT / s for s in CODE.findall(row) if s.startswith("tests/") and s.endswith(".py")]
        names = [s for s in CODE.findall(row) if re.fullmatch(r"test_\w+", s)]
        bodies = "\n".join(f.read_text(encoding="utf-8") for f in files if f.is_file())
        for name in names:
            if not re.search(rf"^def {name}\(", bodies, re.M):
                problems.append(f"{name}: not a test of {[str(f.relative_to(ROOT)) for f in files]}")
    assert not problems, problems


def test_every_finding_the_threat_model_cites_is_on_record() -> None:
    known = set(re.findall(r"^\| ([A-Za-z0-9-]+) \|", REGISTER.read_text(encoding="utf-8"), re.M))
    own: dict[str, Any] = {}
    for f in OWN_FINDINGS:
        for item in json.loads(f.read_text(encoding="utf-8"))["findings"]:
            own[item["id"]] = item
    cited = set(FINDING_ID.findall(_text()))
    assert cited, "no finding cited"
    missing = sorted(i for i in cited if i not in known and i not in own)
    assert not missing, f"cited but in neither the register nor a card's findings.json: {missing}"
    # this page's own findings are in its findings.json and in its table, with the same severity
    for fid, item in own.items():
        if fid.startswith("H10G4-"):
            assert re.search(rf"^\| {fid} \| {item['severity']} \|", _text(), re.M), fid


def test_a_moved_version_or_a_gone_test_fails_the_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    text = _text()
    monkeypatch.setattr(release, "version", lambda *a, **k: "99.0.0")
    with pytest.raises(AssertionError, match="reviewed for"):
        test_threat_model_names_the_current_release()
    gone = text.replace("`test_tampered_bundles_are_rejected`", "`test_tampered_bundles_are_rejected_gone`", 1)
    monkeypatch.setattr(sys.modules[__name__], "_text", lambda: gone)
    with pytest.raises(AssertionError, match="test_tampered_bundles_are_rejected_gone"):
        test_every_path_and_test_the_threat_model_cites_exists()
    monkeypatch.setattr(sys.modules[__name__], "_text", lambda: text + "\n| x | `tools/no_such_tool.py` | V3-99 |\n")
    with pytest.raises(AssertionError, match="no_such_tool"):
        test_every_path_and_test_the_threat_model_cites_exists()
    with pytest.raises(AssertionError, match="V3-99"):
        test_every_finding_the_threat_model_cites_is_on_record()


def test_the_base_networks_are_internal_and_four_services_reach_out() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    nets = compose["networks"]
    for key in ("trialbox-net", "model-net", "model-backend-net"):
        assert nets[key].get("internal") is True, key
    assert not nets["egress-net"].get("internal")
    out = {name for name, svc in compose["services"].items() if "egress-net" in (svc.get("networks") or {})}
    assert out == {"gateway", "orchestrator", "criteria-compiler", "mail-gateway"}
    on_model = {name for name, svc in compose["services"].items()
                if {"model-net", "model-backend-net"} & set(svc.get("networks") or {})}  # fmt: skip
    assert on_model == {"gateway", "llm-stub", "llm-service", "model-guard"}
    for name in on_model - {"gateway"}:
        assert set(compose["services"][name].get("networks") or {}) <= {"model-net", "model-backend-net"}, name
    published = {name for name, svc in compose["services"].items() if svc.get("ports")}
    assert published == {"console"}
    assert compose["services"]["console"]["ports"] == [
        "${TB_CONSOLE_BIND:-127.0.0.1}:${TB_HOST_CONSOLE_PORT:-8090}:8090"
    ]
