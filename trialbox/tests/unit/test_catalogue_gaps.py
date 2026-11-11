"""T-307 (WS-04.2, WS-04.5, D-375): what PR #80 and T-107 left of the catalogue gaps.

* The seven first phenotype definitions run on the synthetic hospital (``tools.synth.generator``, two small sites:
  the default mix and the Japanese memory clinic) and find exactly the planted patients; the other 157 load with the
  status "not validated here".
* The instrument copyright register: every instrument the card names is listed with its terms; a site switch needs a
  licence reference; an item answer of a score-only instrument is never extracted unless the site switched it.
* An Athena load records one licence acknowledgement per licensed vocabulary of the bundle.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from tb_common import catalogue, instruments, phenotypes

from tests.unit.test_omop_core import db  # noqa: F401 - the fixture is used by name
from tools.synth.catalog import AD_DX, DX
from tools.synth.generator import Generator

SEVEN = ("ph.ra", "ph.gout", "ph.dementia", "ph.epilepsy", "ph.lung_cancer", "ph.ckd", "ph.t2dm")
# the generator's diagnosis keys that are each phenotype, read from the clinical meaning of the key, not the code
PLANTED_KEYS: dict[str, tuple[str, ...]] = {
    "ph.ra": ("ra_seropos", "ra_other"),
    "ph.gout": ("gout", "gout_foot", "gout_chronic"),
    "ph.dementia": ("ad_late", "ad_unspecified"),
    "ph.epilepsy": (),  # the generator has no epilepsy: planted below
    "ph.lung_cancer": ("lung_ca", "nsclc_egfr"),
    "ph.ckd": ("ckd3",),
    "ph.t2dm": ("t2dm",),
}
# rows planted by the test: patients that must count, and near misses that must not
PLANTED_ROWS = [
    ("EPI-1", "G40.909"), ("EPI-2", "G40.019"), ("EPI-3", "G40.A09"),  # epilepsy: three patients
    ("NEAR-1", "R56.9"),  # a single seizure, not epilepsy
    ("NEAR-2", "M06.1"),  # adult-onset Still's disease, left out of RA
    ("NEAR-3", "N17.9"),  # acute kidney injury, not CKD
    ("NEAR-4", "E10.9"),  # type 1 diabetes, not type 2
    ("NEAR-5", "G31.84"),  # mild cognitive impairment, not dementia
    ("NEAR-6", "C44.91"),  # skin cancer, not lung
]  # fmt: skip
NEAR_MISSES = {pid for pid, _ in PLANTED_ROWS if pid.startswith("NEAR-")}


@pytest.fixture(scope="module")
def hospital() -> list[tuple[str, str]]:
    """``(patient, ICD-10 code)`` of every diagnosis row of a two-site synthetic hospital, plus the planted rows."""
    rows: list[tuple[str, str]] = []
    for seed, n, mix, style, langs, prefix in ((11, 400, "mix", "TW", {"zh-TW": 1.0}, "1"),
                                               (12, 300, "mix_jp_ad", "JP", {"ja": 1.0}, "2")):  # fmt: skip
        g = Generator(seed, f"SYN-{prefix}", date(2026, 10, 5), n, prefix, style=style, lang_mix=langs, mix=mix)
        g.run()
        rows += [(r["mrn"], r["icd10"]) for r in g.t["diagnosis"]]
    return rows + PLANTED_ROWS


def _planted(rows: list[tuple[str, str]], ph_id: str) -> set[str]:
    codes = {({**DX, **AD_DX})[k][0] for k in PLANTED_KEYS[ph_id]}
    out = {pid for pid, code in rows if code in codes}
    if ph_id == "ph.epilepsy":
        out |= {"EPI-1", "EPI-2", "EPI-3"}
    return out


@pytest.mark.nodb
@pytest.mark.parametrize("ph_id", SEVEN)
def test_each_first_definition_finds_the_planted_patients(hospital: list[tuple[str, str]], ph_id: str) -> None:
    ph = {p.id: p for p in phenotypes.phenotypes()}[ph_id]
    assert ph.status == phenotypes.SYNTHETIC and ph.runnable
    got = phenotypes.run(ph, hospital)
    want = _planted(hospital, ph_id)
    assert want, f"{ph_id}: nothing planted"  # the synthetic hospital has these patients
    assert got == want
    assert not got & NEAR_MISSES


@pytest.mark.nodb
def test_the_other_157_load_as_not_validated_here() -> None:
    allp = phenotypes.phenotypes()
    assert len(allp) == 164
    assert sorted(p.id for p in allp if p.status == phenotypes.SYNTHETIC) == sorted(SEVEN)
    rest = [p for p in allp if p.status != phenotypes.SYNTHETIC]
    assert len(rest) == 157 and {p.status for p in rest} == {phenotypes.NOT_VALIDATED}
    assert not any(p.may_exclude for p in allp)  # the status never makes a phenotype exclude (unknown never excludes)
    local = [p for p in allp if not p.runnable]
    assert local and phenotypes.run(local[0], [("X", "M10.9")]) == set()  # a local phenotype never runs


@pytest.mark.nodb
def test_a_status_for_an_unknown_phenotype_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "cat"
    shutil.copytree(catalogue.CATALOGUE_DIR, folder)
    with (folder / "phenotype_status.csv").open("a", encoding="utf-8") as f:
        f.write("ph.nope,synthetic,2026-11-11,x\n")
    with pytest.raises(catalogue.CatalogueError, match=r"ph\.nope"):
        phenotypes.phenotypes(folder)


# ------------------------------------------------------------------------------------------------ the register
CARD = ("mmse", "moca", "cdr", "mds_updrs", "adas_cog", "eq5d", "sf36", "dlqi", "cat", "panss", "fact", "eortc",
        "promis", "pedsql", "bvas_vdi", "bilag", "frax", "ajcc")  # fmt: skip


@pytest.mark.nodb
def test_the_register_lists_each_instrument_of_the_card_with_its_terms() -> None:
    reg = {i.id: i for i in instruments.register()}
    assert set(CARD) <= set(reg)
    for i in reg.values():
        assert i.terms and i.source and i.checked and i.licence in instruments.LICENCES
    by_id = {i.id: i for i in catalogue.items()}
    assert reg["mmse"].items == ("neuro.mmse_total",) and by_id["neuro.mmse_total"].storable == "score"
    for gone in ("eq5d", "sf36", "fact", "eortc", "promis"):
        assert reg[gone].items == ()  # not in the catalogue: nothing of it can be stored
    for i in reg.values():  # an instrument whose licence is needed or unclear never keeps text by default
        if i.licence != "free-with-terms" and i.items and i.id != "ajcc":
            assert instruments.default_storable(i) != "score+items+text", i.id


@pytest.mark.nodb
def test_a_register_row_naming_an_unknown_item_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "cat"
    shutil.copytree(catalogue.CATALOGUE_DIR, folder)
    with (folder / "instruments.csv").open("a", encoding="utf-8") as f:
        f.write("x,X,h,needed,t,s,2026-11-11,neuro.nope\n")
    with pytest.raises(catalogue.CatalogueError, match="neuro.nope"):
        instruments.register(folder)


@pytest.mark.nodb
@pytest.mark.parametrize("ref", ["", "   ", "\t\n"])
def test_a_switch_with_an_empty_reference_is_refused(ref: str) -> None:
    with pytest.raises(instruments.SwitchRefused) as e:
        instruments.switch({}, "mmse", "score+items", ref, "console:admin", "2026-11-11T00:00:00+00:00")
    assert e.value.code == "no_ref"


@pytest.mark.nodb
def test_switch_rules() -> None:
    at = "2026-11-11T00:00:00+00:00"
    sw = instruments.switch({}, "mmse", "score+items", " LIC-SYN-0001 ", "console:admin", at)
    assert sw["mmse"].licence_ref == "LIC-SYN-0001"
    assert instruments.item_storable("neuro.mmse_total", sw) == "score+items"
    assert instruments.switch(sw, "mmse", "score", "", "console:admin", at) == {}  # back to the catalogue: no ref
    for iid, level, code in (("eq5d", "score", "no_items"), ("nope", "score", "unknown"),
                             ("mmse", "all", "storable"), ("cdr", "score+items+text", "no_ref")):  # fmt: skip
        with pytest.raises(instruments.SwitchRefused) as e:
            instruments.switch({}, iid, level, "", "console:admin", at)
        assert e.value.code == code
    with pytest.raises(instruments.SwitchRefused, match="longer"):
        instruments.switch({}, "mmse", "score+items", "x" * 201, "console:admin", at)
    # a switch written without a reference (by hand, in the store) is never honoured
    raw = json.dumps({"mmse": {"storable": "score+items", "licence_ref": "", "by": "x", "at": at}})
    assert instruments.switches(raw) == {} and instruments.switches("not json") == {}


class _Llm:
    def __init__(self, facts: list[dict[str, Any]]) -> None:
        self.facts = facts

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        return {"facts": self.facts}


CHART = "2026-10-01 外来。MMSE 24/30、見当識 4/5。"


def _facts() -> list[dict[str, Any]]:
    return [
        {"domain": "condition", "term": "MMSE", "value": "24", "date": "2026-10-01", "quote": "MMSE 24/30"},
        {"domain": "condition", "term": "MMSE orientation", "value": "4", "date": "2026-10-01", "quote": "見当識 4/5"},
    ]  # fmt: skip


@pytest.mark.nodb
def test_a_score_only_instruments_item_answer_is_never_extracted_without_a_switch() -> None:
    from sitesetup import charts

    kept, dropped = charts.extract(_Llm(_facts()), CHART, "ja")
    assert dropped == 1 and [f["term"] for f in kept] == ["MMSE"]
    sw = {"mmse": instruments.Switch("mmse", "score", "LIC-SYN-0001", "x", "y")}  # a switch that keeps no items
    kept, dropped = charts.extract(_Llm(_facts()), CHART, "ja", switches=sw)
    assert dropped == 1
    sw = instruments.switch({}, "mmse", "score+items", "LIC-SYN-0001", "console:admin", "2026-11-11")
    kept, dropped = charts.extract(_Llm(_facts()), CHART, "ja", switches=sw)
    assert dropped == 0 and sorted(f["term"] for f in kept) == ["MMSE", "MMSE orientation"]


# ------------------------------------------------------------------------------------------------ Athena
ATHENA = Path(__file__).resolve().parents[1] / "fixtures" / "vocab" / "athena-test"


def test_the_athena_load_records_the_licence_acknowledgements(db: Any) -> None:  # noqa: F811
    from omop import vocab_load

    vocab_load.load_athena(db, ATHENA, by="steward:test")
    acks = {a["vocabulary"]: a for a in vocab_load.licence_acks(db)}
    assert set(acks) == {"LOINC", "UCUM", "RxNorm", "ATC"}  # the licensed vocabularies the bundle holds
    assert acks["LOINC"]["version"] == "TEST-SYNTHETIC 2.82" and "LOINC notice" in acks["LOINC"]["terms"]
    assert {a["acknowledged_by"] for a in acks.values()} == {"steward:test"}
    vocab_load.load_athena(db, ATHENA, by="someone-else")  # the same bundle again changes nothing
    assert {a["acknowledged_by"] for a in vocab_load.licence_acks(db)} == {"steward:test"}
    names = {r["release_name"] for r in vocab_load.releases(db) if r["compile"]}
    assert not any(n.startswith(vocab_load.LICENCE) for n in names)
