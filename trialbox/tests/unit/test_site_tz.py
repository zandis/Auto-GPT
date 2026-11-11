"""T-656 (D-315; STD-016, OPS-036, OPS-056): the site's time zone is one setting, with no code default.

``site.tz`` in settings.yaml is the source and ``TB_TZ`` carries it to the containers. Code takes the zone from the
caller or from ``TB_TZ`` and stops when neither is there (``tb_common.config.site_tz``). ``trialbox doctor`` fails when
site.tz, TB_TZ, the mapping's tz and the host's zone differ (tests/unit/test_trialbox_doctor.py). This file holds the
lint: no ``Asia/Taipei`` literal in code outside settings and tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml
from tb_common.config import ConfigError, load_env, site_tz, site_zone

ROOT = Path(__file__).resolve().parents[2]
LITERAL = "Asia/Taipei"

# Code that may still hold the literal, with the reason. Settings files (deploy/*settings*.yaml, deploy/platform/base/
# site.env, .env.example, the mapping YAML files, tools/rehearse_box/site_answers.yaml) are settings, not code.
ALLOWED = {
    "libs/tb_common/derived.py": "country_of() recognises Taiwan's zone; it is not a default",
    "tools/goldens.py": "test harness: builds the synthetic Taiwan demo site's goldens",
    "tools/omop_parity.py": "test harness: the synthetic Taiwan and Japan demo sites",
    "tools/cascade_e2e.py": "test harness: the synthetic Taiwan demo site",
    "tools/cgmh_demo.py": "test harness: the synthetic Taiwan rheumatology site's settings (T-504)",
    "tools/build_scenario_ruleset.py": "build tool: the synthetic Taiwan rheumatology site (T-504)",
    "tools/testbench/e2e_adapter.py": "test harness: the synthetic Taiwan demo site",
    "tools/ingest_local.py": "local ingest harness: the synthetic Taiwan demo CSV site (T-659b)",
    # owned by open fix groups (worker rules): their defaults go when those groups close (T-656 Remains)
    "libs/tb_common/audit.py": "AuditLog default zone; fix-group file",
    "services/adapter/pipeline.py": "AdapterConfig default zone; fix-group file",
    "tools/trialbox/backup_schedule.py": "backup schedule fallback zone; fix-group file",
}


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _literals(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstrings(tree)
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and LITERAL in n.value and id(n) not in docs
    ]


def test_no_taipei_literal_in_code_outside_settings_and_tests() -> None:
    found = []
    for base in ("libs", "services", "tools"):
        for f in sorted((ROOT / base).rglob("*.py")):
            rel = f.relative_to(ROOT).as_posix()
            if "/tests/" in rel or rel in ALLOWED:
                continue
            found += [f"{rel}:{n}" for n in _literals(f)]
    assert not found, f"a site zone in code (set it in settings: site.tz / TB_TZ, D-315): {found}"
    for name in ("deploy/docker-compose.yml", "deploy/docker-compose.gb10.yml", "deploy/platform/base/fhir-store.yaml"):
        assert LITERAL not in (ROOT / name).read_text(encoding="utf-8"), name


def test_the_allowlist_is_not_stale() -> None:
    for rel in ALLOWED:
        assert _literals(ROOT / rel), f"{rel} no longer holds the literal: take it off ALLOWED"


def test_compose_refuses_to_start_hapi_without_tb_tz() -> None:
    for name in ("deploy/docker-compose.yml", "deploy/docker-compose.gb10.yml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "-Duser.timezone=${TB_TZ:?" in text, name


def test_site_tz_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_TZ", raising=False)
    with pytest.raises(ConfigError, match="time zone is not set"):
        site_tz()
    with pytest.raises(ConfigError, match="not a valid IANA"):
        site_tz("Asia/Nowhere")
    assert site_tz("Asia/Tokyo") == "Asia/Tokyo"
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    assert site_tz() == "Asia/Tokyo" and str(site_zone()) == "Asia/Tokyo"
    assert site_tz(None, {"TB_TZ": "Asia/Taipei"}) == "Asia/Taipei"


def test_env_without_tb_tz_has_no_zone_until_settings_give_one(tmp_path: Path) -> None:
    env = load_env(tmp_path / "none", environ={})
    assert env.tz == ""
    with pytest.raises(ConfigError, match="time zone is not set"):
        _ = env.zone


def test_the_callers_take_the_site_zone_and_stop_without_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lake.flatten import Flattener
    from lake.store import Lake
    from tb_common import timeutil

    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    assert Lake(tmp_path / "lake").tz == "Asia/Tokyo"
    assert str(Flattener().zone) == "Asia/Tokyo"
    assert str(timeutil.now().tzinfo) == "Asia/Tokyo"
    monkeypatch.delenv("TB_TZ")
    for make in (lambda: Lake(tmp_path / "lake2"), Flattener, timeutil.today):
        with pytest.raises(ConfigError):
            make()


def test_a_mapping_without_tz_is_refused(tmp_path: Path) -> None:
    from adapter.mapping.engine import Mapping, MappingError

    src = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
    doc = yaml.safe_load(src.read_text(encoding="utf-8"))
    doc.pop("tz")
    for lookup in src.parent.glob("*.csv"):
        (tmp_path / lookup.name).write_bytes(lookup.read_bytes())
    f = tmp_path / "m.yaml"
    f.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(MappingError, match="no tz"):
        Mapping.load(f)


def test_the_wizard_asks_for_the_zone_and_checks_it_against_the_mapping() -> None:
    from tools.settings_wizard import WizardError, build

    answers = yaml.safe_load((ROOT / "tests/fixtures/onboarding/site_c_answers.yaml").read_text(encoding="utf-8"))
    answers["mapping"] = "mapping/tw_core/demo_his.yaml"
    settings, env, _ = build(answers)
    assert settings["site"]["tz"] == env["TB_TZ"] == "Asia/Taipei"
    with pytest.raises(WizardError, match="tz is required"):
        build({k: v for k, v in answers.items() if k != "tz"})
    with pytest.raises(WizardError, match="differs from the mapping"):
        build({**answers, "tz": "Asia/Tokyo"})
