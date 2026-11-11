"""D-370 (T-659): one ingest stack. The adapter is the compose ingest path; dataplat has no service and no runtime
caller in ``services/``; the adapter never imports dataplat. T-659b deletes ``services/dataplat``."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DECISION = ROOT / "docs/decisions/D-370-one-ingest-stack.md"
IMPORTS_DATAPLAT = re.compile(r"^\s*(from|import)\s+dataplat\b", re.M)


def _compose_files() -> list[Path]:
    return sorted(DEPLOY.glob("docker-compose*.yml")) + sorted(DEPLOY.glob("*/docker-compose*.yml"))


def test_compose_runs_the_adapter_as_the_ingest_service() -> None:
    doc = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    adapter = doc["services"]["adapter"]
    assert "adapter.app:app" in adapter["command"]


def test_no_compose_file_names_dataplat() -> None:
    files = _compose_files()
    assert files
    for path in files:
        assert "dataplat" not in path.read_text(encoding="utf-8"), path


def test_no_service_outside_dataplat_imports_it() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "services").rglob("*.py")
        if "dataplat" not in p.relative_to(ROOT / "services").parts[:1]
        and IMPORTS_DATAPLAT.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_decision_names_the_compose_path_and_the_removal_card() -> None:
    text = DECISION.read_text(encoding="utf-8")
    assert "T-659" in text.splitlines()[2]
    assert "`adapter` (`deploy/docker-compose.yml`" in text
    assert "T-659b" in text
