"""M2 (DB-C2): the imaging list is a licensed system from the hospital's own copy (a stand-in file here), never in the
release or a backup; the department list covers every code of the two synthetic site profiles."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml
from criteria_compiler.terminology import installed

from tools import licence_register, terminology_load

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "services" / "criteria_compiler" / "terminology" / "src"
STANDIN = SRC / "imaging_standin.csv"


def test_the_imaging_list_needs_a_named_person_and_a_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="accepted the licence"):
        installed.install_imaging(STANDIN, tmp_path, accepted_by="yes", version="standin")
    with pytest.raises(ValueError, match="--version"):
        installed.install_imaging(STANDIN, tmp_path, accepted_by="Chen Mei-Ling")
    assert not list(tmp_path.glob("*.parquet"))


def test_the_loaded_list_has_its_line_and_reaches_the_vocabulary_reader(tmp_path: Path) -> None:
    got = installed.install_imaging(
        STANDIN, tmp_path, accepted_by="Chen Mei-Ling", accepted_on="2026-11-25", version="standin"
    )
    assert got == {"imaging_list": 3}
    line = installed.manifest(tmp_path)["tables"]["imaging_list"]
    assert line["licence_accepted_by"] == "Chen Mei-Ling" and line["version"] == "imaging standin"
    assert len(line["sha256"]) == 64
    system, version, pairs = terminology_load.code_lists(tmp_path)["imaging_list"]
    assert system.endswith("/CodeSystem/imaging") and version == "imaging standin"
    assert ("STAND-CT-HEAD", "Stand-in: CT of the head (synthetic)") in pairs


def test_the_imaging_list_is_never_in_the_release() -> None:
    from tools.build_terminology import FILES

    assert "imaging_standin" not in FILES and "imaging_list" not in FILES
    assert not list((ROOT / "services" / "criteria_compiler" / "terminology").glob("imaging*.parquet"))
    assert installed.is_licensed("imaging_list") and "imaging_list" not in installed.SHIPPED_FILES


def test_the_register_has_the_imaging_rows_and_jj1017_is_row_only() -> None:
    rows = {r.id: r for r in licence_register.load()}
    assert rows["imaging-list"].status == "synthetic" and rows["jj1017"].status == "permission-to-ask"


def test_the_department_list_covers_both_synthetic_site_profiles() -> None:
    have = {r["code"] for r in csv.DictReader((SRC / "department.csv").open(encoding="utf-8"))}
    for f in ("tests/fixtures/onboarding/site_c_answers.yaml", "tools/rehearse_box/site_answers.yaml"):
        assert set(yaml.safe_load((ROOT / f).read_text(encoding="utf-8"))["departments"]) <= have, f
