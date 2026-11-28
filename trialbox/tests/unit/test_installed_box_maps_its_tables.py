"""E2E P-09: the site mapping the installer writes must map the shipped tables.

Before: ``tools/box/plan.py`` wrote ``box_site.yaml`` as ``extends: ../tw_core/demo_his.yaml`` with no ``tables:``,
and the engine kept only the site's tables, so a freshly installed box mapped no table: runbook 01's mapping check
printed ``FAILED: 0 missing columns, 0 invalid resources, 0 rows refused`` with no reason and every night was held
("holds no patient or clinical record"). The journey here: plan the box from the owner's answers, then run the
runbook's mapping check over a demo_his export.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from adapter.mapping.engine import Mapping
from tb_common.box_answers import parse

from tests.unit.test_site_country import HW, OWNER
from tools import mapping_check
from tools.box import plan as bp

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"

pytestmark = pytest.mark.nodb


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The box's site mapping as the installer writes it, in the box's site folder; the base is the image's."""
    a, problems = parse(OWNER)
    assert a is not None, problems
    p = bp.plan(a, HW)
    path = tmp_path / "site" / bp.BOX_MAPPING
    path.parent.mkdir(parents=True)
    path.write_text(p.files[f"site/{bp.BOX_MAPPING}"], encoding="utf-8")
    monkeypatch.setenv("TB_MAPPING_DIR", str(tmp_path / "site" / "mapping"))
    return path


def test_the_installed_site_mapping_maps_every_shipped_table(installed: Path) -> None:
    m = Mapping.load(installed)
    shipped = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    assert set(m.tables) == set(shipped["tables"]) and m.tables
    assert {r.table for r in m.resources} == {r["table"] for r in shipped["resources"]}


def test_runbook_mapping_check_passes_on_a_fresh_box(installed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = mapping_check.main(["--mapping", str(installed), "--source", "csv", "--path", str(SITE_A)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PASSED" in out and "patient" in out


def test_a_site_mapping_that_declares_no_table_says_so(installed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    installed.write_text(installed.read_text(encoding="utf-8") + "tables: {}\n", encoding="utf-8")  # declared, empty
    rc = mapping_check.main(["--mapping", str(installed), "--source", "csv", "--path", str(SITE_A)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "NO TABLES" in out and "declares no table" in out
