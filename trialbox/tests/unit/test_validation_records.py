"""The validation records of ``docs/validation/`` keep their layout (card T-215, D-344).

Checks: the files of the layout exist; every FS id the traceability matrix uses has one row in the functional
specification index; each change class CC1 to CC6 is defined once and matches TB-DS-04 §9.3; the VMP v1.1 has the
sections of deep review REG-027 and no signature table (D-311); every repository path the records name exists.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
VAL = ROOT / "docs" / "validation"
VMP = ROOT / "docs" / "plan" / "25-vmp.md"
MATRIX = ROOT / "docs" / "plan" / "25-traceability.csv"
DS04 = ROOT / "docs" / "plan" / "design" / "04-verification-operations.md"

T215_FILES = [
    "README.md",
    "qms-lite.md",
    "standards-position.md",
    "change-control.md",
    "functional-spec.md",
    "supplier-assessments.md",
    "release-records/README.md",
]
# Card T-654's records (PR #142): all four are in the folder now, so a link to one must resolve like any other.
T654_FILES = {"software-safety-classification.md", "development-plan.md", "soup.csv", "problems.csv"}
# Named in the layout as planned by other cards and not in the folder yet (record-inventory.md has landed).
PLANNED = {"protocols/"}
# Made by a build or on the box, not committed.
MADE = {"release.json"}
# Named in the README as struck by D-311; they must not exist.
STRUCK = {"gates/", "risk-register.md", "part11-ers.md", "source-and-copies.md", "e6r3-section4.md"}

FS_ROW = re.compile(r"^\| (FS-\d{2}) \|", re.M)
CC_ROW = re.compile(r"^\| \*\*(CC\d) [^|]*\*\* \|", re.M)
DS04_CC = re.compile(r"^\| (CC\d) [A-Z]", re.M)
TICKED = re.compile(r"`([^`\s]+)`")


def fs_rows(text: str) -> list[str]:
    return FS_ROW.findall(text)


def fs_missing(matrix_ids: set[str], index_text: str) -> set[str]:
    """FS ids the matrix uses that the index has no row for."""
    return matrix_ids - set(fs_rows(index_text))


def matrix_fs_ids() -> set[str]:
    with MATRIX.open(newline="", encoding="utf-8") as fh:
        return {row["fs"] for row in csv.DictReader(fh) if row["fs"]}


def looks_like_path(token: str) -> bool:
    if any(ch in token for ch in "<>*{}$=") or token.startswith(("-", "http")):
        return False
    return "/" in token or token.endswith((".md", ".csv", ".py", ".sh", ".yaml", ".yml", ".json", ".lock"))


def resolves(token: str, here: Path = VAL) -> bool:
    name = token.split("#", maxsplit=1)[0].split("::", maxsplit=1)[0].rstrip("/")
    short = name.removeprefix("docs/validation/").removeprefix("../")
    if short in {p.rstrip("/") for p in PLANNED | MADE | STRUCK}:
        return True
    return any((base / name).exists() for base in (here, ROOT, REPO, VAL))


def test_layout_files_exist() -> None:
    missing = [f for f in T215_FILES if not (VAL / f).is_file()]
    assert not missing, missing


def test_readme_lists_every_record_in_the_folder() -> None:
    readme = (VAL / "README.md").read_text(encoding="utf-8")
    for f in T215_FILES[1:] + sorted(T654_FILES):
        assert f.split("/")[0] in readme, f
    present = {p.name for p in VAL.iterdir()} - {"README.md"}
    unlisted = {p for p in present if p not in readme}
    assert not unlisted, f"files in docs/validation/ not listed in its README: {sorted(unlisted)}"


def test_struck_records_stay_out() -> None:
    present = sorted(f for f in STRUCK if (VAL / f.rstrip("/")).exists())
    assert not present, f"D-311 struck these records: {present}"


def test_every_fs_id_of_the_matrix_has_one_row() -> None:
    index = (VAL / "functional-spec.md").read_text(encoding="utf-8")
    rows = fs_rows(index)
    assert rows == [f"FS-{n:02d}" for n in range(1, 18)], "one row per workstream FS-01 to FS-17, in order"
    assert not fs_missing(matrix_fs_ids(), index)


def test_a_planted_fs_id_without_a_row_is_found() -> None:
    index = (VAL / "functional-spec.md").read_text(encoding="utf-8")
    assert fs_missing({"FS-01", "FS-99"}, index) == {"FS-99"}


def test_change_classes_defined_once_and_match_the_design() -> None:
    text = (VAL / "change-control.md").read_text(encoding="utf-8")
    ours = CC_ROW.findall(text)
    assert ours == [f"CC{n}" for n in range(1, 7)], ours
    ds04 = DS04_CC.findall(DS04.read_text(encoding="utf-8"))
    assert sorted(set(ds04)) == ours


def test_staged_rollout_names_three_stages_and_the_on_site_rule() -> None:
    text = (VAL / "change-control.md").read_text(encoding="utf-8")
    section = text.split("## 4. Staged roll-out", 1)[1].split("\n## ", 1)[0]
    assert re.findall(r"^\| ([123]) \|", section, re.M) == ["1", "2", "3"]
    assert "three working days" in section
    assert "Who applies an update on site" in section
    assert "sign-off" in section and "D-311" in section


def test_vmp_v11_has_the_reg027_sections_and_no_signatures() -> None:
    text = VMP.read_text(encoding="utf-8")
    heads = [h.lower() for h in re.findall(r"^## (.+)$", text, re.M)]
    for want in ("regulated user", "gxp assessment", "model sub-system", "deviations", "retirement"):
        assert any(want in h for h in heads), want
    assert "| Version | 1.1" in text
    assert "Second Edition" in text
    assert not re.search(r"^\| Role \| Name \| Date \| Signature \|", text, re.M), "D-311 removed the signature table"
    assert not re.search(r"^## \d+\. Signatures", text, re.M)


def test_standards_position_covers_the_three_standards() -> None:
    text = (VAL / "standards-position.md").read_text(encoding="utf-8")
    for std in ("IEC 62304", "IEC 82304-1", "ISO 13485"):
        assert std in text
    assert "## 3. ISO 13485 trigger" in text
    for rec in sorted(T654_FILES):
        assert rec in text, f"links T-654's {rec}"


@pytest.mark.parametrize("doc", [*T215_FILES, "../plan/25-vmp.md"])
def test_paths_named_in_the_records_exist(doc: str) -> None:
    path = (VAL / doc).resolve()
    text = path.read_text(encoding="utf-8")
    bad = sorted({t for t in TICKED.findall(text) if looks_like_path(t) and not resolves(t, path.parent)})
    assert not bad, f"{doc}: paths that do not exist: {bad}"


def test_the_path_check_finds_a_planted_missing_path() -> None:
    assert looks_like_path("services/no_such_service/x.py")
    assert not resolves("services/no_such_service/x.py")
    assert resolves("services/console/app.py")
