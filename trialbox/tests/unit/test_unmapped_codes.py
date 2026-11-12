"""NEW-DIN-6 (DIN-006, D-580): a code the look-up does not know is counted every night, and the look-up key is read
without its blanks, case and width.

Before: a lab row whose local code is not in the look-up was dropped by the resource's ``where`` with no count
anywhere, and the look-up was exact, so ``" CRE "`` (a fixed-width column), ``cre`` and ``ＣＲＥ`` gave no record.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import CODE_MAX, Lookup, Mapper, Mapping
from adapter.ndjson import snapshot_dir
from adapter.pipeline import COMPLETENESS, AdapterConfig, run_ingest
from datacore.dataops import DataOps
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
CRE = "2160-0"


def _lab(code: str, n: int = 1) -> dict[str, str]:
    return {"lab_no": f"L{n}", "mrn": "P1", "local_code": code, "item_name": "x", "result_value": "1.1",
            "unit": "mg/dL", "sample_datetime": "2026-05-30 10:30:00"}  # fmt: skip


@pytest.fixture(scope="module")
def mapping() -> Mapping:
    return Mapping.load(MAPPING)


@pytest.mark.parametrize("code", ["CRE", " CRE ", "CRE   ", "\tCRE", "cre", "Cre", "ＣＲＥ", " ｃｒｅ　"])
def test_a_code_with_blanks_another_case_or_width_is_the_same_code(mapping: Mapping, code: str) -> None:
    mapper = Mapper(mapping, b"k" * 32, "s")
    out = list(mapper.map_table("lab", iter([_lab(code)])))
    assert len(out) == 1, f"{code!r} gave no Observation"
    assert out[0]["code"]["coding"][0]["code"] == CRE
    assert out[0]["valueQuantity"]["value"] == 1.1 and out[0]["valueQuantity"]["code"] == "mg/dL"
    assert not mapper.unmapped


def test_two_rows_that_differ_only_by_case_are_two_codes_and_folding_matches_neither() -> None:
    lk = Lookup("t", "k", {"Na": {"k": "Na", "v": "sodium"}, "NA": {"k": "NA", "v": "not applicable"}, "K": {"k": "K", "v": "potassium"}})  # fmt: skip
    assert lk.find("Na") == {"k": "Na", "v": "sodium"} and lk.find("NA") == {"k": "NA", "v": "not applicable"}
    assert lk.find("na") is None and lk.find(" NA ") is None  # which of the two? neither: never a guess
    assert lk.find(" k ") == {"k": "K", "v": "potassium"}
    assert lk.find("") is None and lk.find("   ") is None and lk.find(None) is None


def test_a_look_up_file_with_a_padded_key_is_found_by_the_plain_code(tmp_path: Path) -> None:
    (tmp_path / "t.csv").write_text("k,v\n CRE ,1\n", encoding="utf-8")
    lk = Lookup.load("t", tmp_path / "t.csv", "k")
    assert (lk.find("CRE") or {}).get("v") == "1" and (lk.find("cre") or {}).get("v") == "1"


def test_the_mapper_counts_every_row_dropped_for_an_unknown_code(mapping: Mapping) -> None:
    mapper = Mapper(mapping, b"k" * 32, "s")
    rows = [_lab("GLU-AC", 1), _lab("GLU-AC", 2), _lab(" GLU-AC ", 3), _lab("ZZZ", 4), _lab("", 5), _lab("CRE", 6)]
    out = list(mapper.map_table("lab", iter(rows)))
    assert len(out) == 1
    assert dict(mapper.unmapped) == {("lab", "lab", "GLU-AC"): 3, ("lab", "lab", "ZZZ"): 1, ("lab", "lab", ""): 1}
    assert mapper.unmapped_summary() == {"lab": {"lab": {"rows": 5, "codes": 3}}}
    assert mapper.unmapped_by_code() == {"lab": {"lab": {"GLU-AC": 3, "(no code)": 1, "ZZZ": 1}}}


# ------------------------------------------------------------------------------------------------- the whole night
class _Rebuild:
    def __init__(self, lake_dir: Path) -> None:
        self.lake_dir = lake_dir

    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        (self.lake_dir / "db").mkdir(parents=True, exist_ok=True)
        (self.lake_dir / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)


def _events(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted((tmp / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]


def test_the_night_reports_unknown_codes_and_loads_padded_ones(tmp_path: Path, pg_cluster_url: str) -> None:
    feed = tmp_path / "feed"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    with (feed / "lab.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    n_cre = sum(1 for r in rows if r["local_code"] == "CRE")
    assert n_cre > 10
    flip = 0
    for r in rows:  # a fixed-width export pads the code; another system lower-cases it
        if r["local_code"] == "CRE":
            r["local_code"] = (" CRE ", "cre", "CRE")[flip % 3]
            flip += 1
    extra = [{**rows[0], "lab_no": f"LX{i}", "local_code": code} for i, code in enumerate(["GLU-AC"] * 3 + ["ZZZ"])]
    with (feed / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows + extra)
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    sep = "&" if "?" in pg_cluster_url else "?"
    db_url = f"{pg_cluster_url}{sep}tb_prefix=unmapped{os.getpid()}_"
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T",
                        audit_dir=tmp_path / "audit", rebuild=_Rebuild(tmp_path / "lake"), db_url=db_url)  # fmt: skip
    rep = run_ingest(cfg, "csv", str(feed), snapshot="2026-11-01", load_fhir=False, validate=False)
    assert rep.passed and not rep.held  # an unknown code never holds the night (D-580, 3)
    out = snapshot_dir(cfg.lake_dir, "2026-11-01")
    obs = [json.loads(x) for x in (out / "Observation.ndjson").read_text(encoding="utf-8").splitlines()]
    got_cre = sum(1 for o in obs if any(c.get("code") == CRE for c in o["code"]["coding"]))
    assert got_cre == n_cre  # every padded or lower-case creatinine is a record
    comp = json.loads((out / COMPLETENESS).read_text(encoding="utf-8"))
    assert comp["tables"]["lab"]["unmapped"] == {"lab": {"rows": 4, "codes": 2}}
    assert "unmapped" not in comp["tables"]["patient"]
    by_code = json.loads((out / "unmapped_codes.json").read_text(encoding="utf-8"))
    assert by_code == {"lab": {"lab": {"GLU-AC": 3, "ZZZ": 1}}}
    done = [e for e in _events(tmp_path) if e["event"] == "ingest.done"]
    assert done[-1]["detail"]["unmapped"] == {"lab": 4}
    ops = DataOps(db_url)
    try:
        assert ops.batches()[-1].detail["unmapped"] == {"lab": 4}  # the data-operations row keeps the count
    finally:
        ops.close()


def test_mapping_check_reads_the_look_up_as_the_night_does(tmp_path: Path) -> None:
    from tools.mapping_check import check

    feed = tmp_path / "feed"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    with (feed / "lab.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["local_code"], rows[1]["local_code"] = " CRE ", "GLU-AC"
    with (feed / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    rep = check(MAPPING, "csv", str(feed), 5000)
    lab = rep["tables"]["lab"]
    assert [k for k in lab["unmapped_codes"] if "not in lookup" in k] == ["lab local_code=GLU-AC (not in lookup)"]


# ---------------------------------------------------------------- the adversarial review of PR #345 (2026-11-12)
@pytest.mark.parametrize(("fed", "key"), [("㎎", "MG"), ("①", "1"), ("Ⅳ", "IV"), ("ß", "SS"), ("ﬁ", "FI"),
                                          ("µg", "μg"), ("ｶﾞ", "ガ"), ("C R E", "CRE"), ("1.0", "1")])  # fmt: skip
def test_folding_is_blanks_width_and_case_and_nothing_else(fed: str, key: str) -> None:
    """M1: Unicode NFKC and full case folding made ``㎎`` the code ``MG`` and ``ß`` the code ``SS``: another sign is
    another code, and a result must never be stored under another analyte."""
    lk = Lookup("t", "k", {key: {"k": key, "v": "x"}})
    assert lk.find(fed) is None
    assert lk.find(f" {key.lower()} ") == {"k": key, "v": "x"}


def test_a_look_up_saved_with_a_byte_order_mark_reads(tmp_path: Path) -> None:
    (tmp_path / "t.csv").write_bytes("k,v\nCRE,1\n".encode("utf-8-sig"))
    assert (Lookup.load("t", tmp_path / "t.csv", "k").find("cre") or {}).get("v") == "1"


def test_only_what_looks_like_a_code_is_written_out(mapping: Mapping) -> None:
    """H1: a mis-mapped column can put a chart number or a name where the code belongs. It is counted, never
    written into the night's reports."""
    mapper = Mapper(mapping, b"k" * 32, "s")
    chart = "1" + "0" * 6 + "2"  # eight digits, as the site's chart numbers are
    fed = [f"{chart} 王小明", "王小明", chart, "see note: repeat in 2 weeks", "X" * (CODE_MAX + 1), "GLU-AC",
           "X" * CODE_MAX, "ｇｌｕ", "\u3000", ""]  # fmt: skip
    list(mapper.map_table("lab", iter([_lab(c, i) for i, c in enumerate(fed)])))
    assert mapper.unmapped_by_code(r"^\d{8}$") == {"lab": {"lab": {
        "(not a code)": 6, "(no code)": 2, "GLU-AC": 1, "X" * CODE_MAX: 1}}}  # fmt: skip
    assert mapper.unmapped_by_code() == {"lab": {"lab": {
        "(not a code)": 5, "(no code)": 2, chart: 1, "GLU-AC": 1, "X" * CODE_MAX: 1}}}  # fmt: skip
    assert mapper.unmapped_summary() == {"lab": {"lab": {"rows": 10, "codes": 9}}}


def test_the_night_writes_no_chart_number_or_name_into_its_reports(tmp_path: Path, pg_cluster_url: str) -> None:
    feed = tmp_path / "feed"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    with (feed / "lab.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for i, r in enumerate(rows[:40]):  # the code column carries the chart number and a name
        r["local_code"] = f"{r['mrn']} 王小明{i}" if i % 2 else r["mrn"]
    with (feed / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    sep = "&" if "?" in pg_cluster_url else "?"
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T",
                        audit_dir=tmp_path / "audit", rebuild=_Rebuild(tmp_path / "lake"), mrn_regex=r"^\d{8}$",
                        db_url=f"{pg_cluster_url}{sep}tb_prefix=unmappedpii{os.getpid()}_")  # fmt: skip
    run_ingest(cfg, "csv", str(feed), snapshot="2026-11-01", load_fhir=False, validate=False)
    out = snapshot_dir(cfg.lake_dir, "2026-11-01")
    assert json.loads((out / "unmapped_codes.json").read_text(encoding="utf-8")) == {
        "lab": {"lab": {"(not a code)": 40}}
    }
    said = (out / COMPLETENESS).read_text(encoding="utf-8") + json.dumps(_events(tmp_path), ensure_ascii=False)
    assert "王小明" not in said and not any(r["mrn"] in said for r in rows[:40])
