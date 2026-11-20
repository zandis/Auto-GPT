"""Offline checks for the three independently readable sections of the site version note."""

import json
import re
from pathlib import Path

import pytest

from tools import doclint

ROOT = Path(__file__).resolve().parents[2]
NOTE = ROOT / "docs/data/16-site-standard-versions.md"
OMOP_PIN = Path("services/omop/ddl/pin.json")
JP_RULES = Path("services/adapter/validate/jp_core_rules.json")
OHDSI_RELEASE = "https://github.com/OHDSI/CommonDataModel/releases/tag/v5.5.0"
JAMI_GUIDE = "https://jpfhir.jp/fhir/core/1.2.0/"


def sections(markdown: str, level: int) -> dict[str, str]:
    parts = re.split(rf"^{'#' * level} (.+)$", markdown, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


@pytest.fixture(params=["en", "zh-TW", "ja"])
def language_section(request: pytest.FixtureRequest) -> str:
    return sections(NOTE.read_text(encoding="utf-8"), 2)[request.param]


@pytest.fixture
def current_versions(language_section: str) -> dict[str, str]:
    # Each heading starts with the full build version, followed by a localized label.
    return {heading.partition(" — ")[0]: body for heading, body in sections(language_section, 3).items()}


def test_data_index_lists_the_note_as_section_16() -> None:
    title = NOTE.read_text(encoding="utf-8").splitlines()[0]
    assert title.startswith("# 16. ")
    index = sections((ROOT / "docs/DATA.md").read_text(encoding="utf-8"), 2)
    assert f"](data/{NOTE.name})" in index[title.removeprefix("# ")]


def test_note_heading_anchors_are_unique() -> None:
    anchors = [doclint.slug(title) for _, _, title in doclint.headings(NOTE.read_text(encoding="utf-8"))]
    assert len(set(anchors)) == len(anchors)


def test_site_version_evidence(language_section: str) -> None:
    introduction = language_section.split("### ", 1)[0]
    for evidence in ("CDM_SOURCE.cdm_version", "FHIR R4", "meta.profile"):
        assert evidence in introduction


def test_omop_build_and_comparison(current_versions: dict[str, str]) -> None:
    pin = json.loads((ROOT / OMOP_PIN).read_text(encoding="utf-8"))
    cdm_version = Path(pin["path"]).parent.name  # inst/ddl/<CDM version>/postgresql/
    omop = current_versions[f"OMOP CDM {cdm_version} (DDL `{pin['tag']}`)"]
    assert f"](../../{OMOP_PIN.as_posix()})" in omop
    comparison = next(p for p in omop.split("\n\n") if p.startswith("**OMOP CDM 5.5**"))
    assert f"]({OHDSI_RELEASE})" in comparison and "2026-08-25" in comparison
    assert "`OBSERVATION.value_as_date`" in comparison and "`observation_date`" in comparison


def test_jp_core_build_and_comparison(current_versions: dict[str, str]) -> None:
    package = json.loads((ROOT / JP_RULES).read_text(encoding="utf-8"))["package"]
    jp = current_versions[f"JP Core (`{package['id']}#{package['version']}`)"]
    assert f"](../../{JP_RULES.as_posix()})" in jp
    comparison = next(p for p in jp.split("\n\n") if p.startswith("**JP Core 1.2.0**"))
    assert f"]({JAMI_GUIDE})" in comparison and "2025-07-30" in comparison
    for field in ("rpNumber", "Coverage", "insuranceIdentifier", "insuranceCsvIdentifier"):
        assert field in comparison
    terminology = next(p for p in jp.split("\n\n") if p.startswith("D-417"))
    assert f"]({JAMI_GUIDE}jp-core.r4-1.2.0.tgz)" in terminology
    assert "](../decisions/D-417-standards-conformance-ci.md)" in terminology
