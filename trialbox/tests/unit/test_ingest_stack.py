"""D-370 (T-659), D-381 (T-659b): one ingest stack. The adapter is the compose ingest path and the only one in the
tree: ``services/dataplat`` is gone, no compose file, Makefile, package list or Python file names it, and the
controls it had (contracts, row quarantine, one gate record per night, the patient index as an alias table, lineage)
live in the adapter."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DECISION = ROOT / "docs/decisions/D-370-one-ingest-stack.md"
REMOVAL = ROOT / "docs/decisions/D-381-one-ingest-stack-removal.md"
IMPORTS_DATAPLAT = re.compile(r"^\s*(from|import)\s+dataplat\b", re.M)


def _compose_files() -> list[Path]:
    return sorted(DEPLOY.glob("docker-compose*.yml")) + sorted(DEPLOY.glob("*/docker-compose*.yml"))


def test_compose_runs_the_adapter_as_the_ingest_service() -> None:
    doc = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    adapter = doc["services"]["adapter"]
    assert "adapter.app:app" in adapter["command"]
    ingest = [name for name, svc in doc["services"].items() if "ingest" in str(svc.get("command", ""))]
    assert ingest in ([], ["adapter"])  # no second ingest service


def test_no_compose_file_names_dataplat() -> None:
    files = _compose_files()
    assert files
    for path in files:
        assert "dataplat" not in path.read_text(encoding="utf-8"), path


def test_the_dataplat_tree_is_gone_and_nothing_imports_it() -> None:
    assert not (ROOT / "services" / "dataplat").exists()
    offenders = [
        str(p.relative_to(ROOT))
        for top in ("services", "libs", "tools", "tests")
        for p in (ROOT / top).rglob("*.py")
        if IMPORTS_DATAPLAT.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert "dataplat" not in (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "dataplat" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_the_controls_live_in_the_adapter() -> None:
    from adapter import governance, pidmap

    assert governance.load_contracts(governance.DEMO_HIS) and governance.load_contracts(governance.MIMIC_FHIR)
    assert any("pid_alias" in m for m in pidmap.MIGRATIONS)
    text = (ROOT / "services/adapter/pipeline.py").read_text(encoding="utf-8")
    for needle in ("governance.check_table", "governance.write_gate", "governance.LINEAGE", "apply_aliases"):
        assert needle in text, needle


def test_the_decisions_name_the_compose_path_and_the_removal() -> None:
    text = DECISION.read_text(encoding="utf-8")
    assert "T-659" in text.splitlines()[2]
    assert "`adapter` (`deploy/docker-compose.yml`" in text
    assert "T-659b" in text
    removal = REMOVAL.read_text(encoding="utf-8")
    assert "T-659b" in removal and "D-370" in removal
