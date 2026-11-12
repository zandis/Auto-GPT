"""NEW-DIN-5 (DIN-005): SS-MIX2 PPR-01, PRB-3: the ICD-10 code is read from whichever triple names ICD-10.

Before: only the alternate triple (components 4 to 6) was read. A vendor that sends ICD-10 first
(``E11.9^糖尿病^I10``) gave every diagnosis no code. All data is synthetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.mapping.engine import Mapper, Mapping
from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir

ROOT = Path(__file__).resolve().parents[2]
JP_MAPPING = ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml"


def _store(root: Path, order: str, prb3: str) -> None:
    d = storage_dir(root, "P0001", "20261001", "PPR-01")
    d.mkdir(parents=True, exist_ok=True)
    segs = ["PID|1||P0001^^^^PI", "PV1|1|O||||||||||||||||E1",
            f"PRB|AD|20261001|{prb3}|{order}||||||||||A||20260930"]  # fmt: skip
    body = "\r".join(["MSH|^~\\&|HIS||TB||20261001||PPR^ZD1|1|P|2.5||||||~ISO IR87", *segs]) + "\r"
    (d / f"P0001_20261001_PPR-01_{order}_20261001000000000_-_1").write_bytes(body.encode("iso2022_jp"))


def _rows(tmp_path: Path, prb3: str) -> tuple[list[dict[str, str]], Ssmix2Source]:
    root = tmp_path / "storage"
    _store(root, "D1", prb3)
    src = Ssmix2Source(root, licensed={})
    return [dict(r) for r in src.rows("diagnosis", "PPR-01", None, None)], src


@pytest.mark.parametrize(("prb3", "icd", "byomei"), [
    ("E11.9^2型糖尿病^I10", "E11.9", ""),                      # ICD-10 first: the finding
    ("E11.9^2型糖尿病^ICD10", "E11.9", ""),
    ("20054174^2型糖尿病^MDCDX2^E11.9^2型糖尿病^I10", "E11.9", "20054174"),  # the standard's order, as before
    ("E11.9^2型糖尿病^I10^20054174^2型糖尿病^MDCDX2", "E11.9", ""),  # ICD-10 first, the name code second
    ("e119^2型糖尿病^I10", "E11.9", ""),                       # written the site's way: read as the code it is
    ("E11.9^x^I10^M06.9^y^I10", "E11.9", ""),                 # both name ICD-10: the first
])  # fmt: skip
def test_the_icd10_code_is_read_from_the_triple_that_names_icd10(
    tmp_path: Path, prb3: str, icd: str, byomei: str
) -> None:
    (row,), src = _rows(tmp_path, prb3)
    assert row["icd10"] == icd and row["byomei_code"] == byomei
    assert not [k for k in src.missed if k.startswith("diagnosis:")]


@pytest.mark.parametrize(
    "prb3", ["E11.9^2型糖尿病^99XYZ", "E11.9^2型糖尿病", "ZZ999^なにか^MDCDX2", "E11.9^x^LOCAL^M06.9^y^LN"]
)
def test_a_code_no_triple_calls_icd10_is_not_taken_for_one(tmp_path: Path, prb3: str) -> None:
    (row,), src = _rows(tmp_path, prb3)
    assert row["icd10"] == "" and [k for k in src.missed if k.startswith("diagnosis:")]


def test_the_condition_carries_the_code(tmp_path: Path) -> None:
    (row,), _ = _rows(tmp_path, "M06.9^関節リウマチ^I10")
    m = Mapping.load(JP_MAPPING)
    (res,) = Mapper(m, b"k" * 32, "s").map_table("diagnosis", iter([m.normalize("diagnosis", row)]))
    assert "M06.9" in {c.get("code") for c in res["code"]["coding"]}


@pytest.mark.parametrize(("prb3", "icd"), [
    ("ZZZ^n^I10^E11.9^n^I10", "E11.9"),      # a first triple that is no ICD-10 code does not hide a good second one
    ("E11.9^n^i10", "E11.9"), ("E11.9^n^ I10 ", "E11.9"),  # the system's name in another case or with blanks
    ("ZB01^n^MDCDX2^E11.9^n^i10", "E11.9"),  # ... in the second triple too
])  # fmt: skip
def test_the_review_cases_that_must_read_a_code(tmp_path: Path, prb3: str, icd: str) -> None:
    (row,), _ = _rows(tmp_path, prb3)
    assert row["icd10"] == icd


@pytest.mark.parametrize("prb3", ["ZZZ^n^I10", "E11.9&X^n^I10", "E1190X^n^I10", "^n^I10"])
def test_what_is_called_icd10_and_is_not_one_gives_no_code_and_is_counted(tmp_path: Path, prb3: str) -> None:
    (row,), src = _rows(tmp_path, prb3)
    assert row["icd10"] == "" and row["byomei_code"] == ""  # never passed on as a code of either kind
    assert sum(n for k, n in src.missed.items() if k.startswith("diagnosis:")) == 1
