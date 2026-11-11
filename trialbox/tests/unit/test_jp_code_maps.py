"""T-610: Japan and Taiwan code maps at scale (STD-042, STD-043, STD-024).

All data is synthetic. The site-shaped drug master is generated here (2,500 ingredients, products under YJ, HOT and
local codes, order lines by volume); no real master is read or shipped (CR-015).
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from adapter.sources.ssmix2.source import Ssmix2Source, reader_summary, storage_dir
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import (
    SYSTEMS,
    YJ_STEM,
    Concept,
    ValueSets,
    valueset,
    yj_ingredients,
)
from sitesetup import mapping as sm
from tb_common import refdata_jp as jp
from tb_contracts import CriterionIR

# 薬効分類 (4 digits) used to make synthetic stems; the 3 digits after them are made up
YAKKO = ("1124", "1141", "1149", "1169", "1179", "2129", "2149", "2171", "2189", "2325", "2329", "2391", "2399",
         "2454", "2456", "2590", "3112", "3253", "3329", "3399", "3943", "3962", "3969", "3999", "4291", "4490",
         "6132", "6149", "6241", "6250")  # fmt: skip
FORMS = "FMACGT"  # 剤形 letters (tablet, capsule, ...)
N_INGREDIENTS = 2500


def synthetic_master(seed: int = 610) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    """A site-shaped synthetic drug master: 2,500 ingredients (stems), 1 to 4 products each under a local code, a
    YJ code and a HOT13 code; about 1 % of products are 院内製剤 with no YJ code. And the site's ingredient table: an ATC
    code for 90 % of the stems (synthetic ATC-shaped codes)."""
    rnd = random.Random(seed)
    master, table = [], {}
    n = 0
    for i in range(N_INGREDIENTS):
        stem = f"{YAKKO[i % len(YAKKO)]}{i // len(YAKKO) + 100:03d}"
        if rnd.random() < 0.9:
            table[stem] = {"atc": f"Z{i % 90 + 10:02d}{chr(65 + i % 26)}{chr(65 + i // 26 % 26)}{i % 97:02d}",
                           "ingredient": f"合成成分{i}", "route": "内用", "source": "site"}  # fmt: skip
        for p in range(rnd.randint(1, 4)):
            n += 1
            house = p > 0 and rnd.random() < 0.015  # never the first product: every ingredient has a YJ code
            master.append({
                "local": f"L{n:06d}",
                "yj": "" if house else f"{stem}{FORMS[p % len(FORMS)]}{p + 1}{n % 1000:03d}",
                "price": "",
                "hot": f"{1000000 + n:07d}{n % 100:02d}0101",
                "name": f"合成薬{n}錠",
                "ingredient": f"合成成分{i}",
                "atc": "",
            })  # fmt: skip
    return master, table


def synthetic_order_lines(master: list[dict[str, str]], lines: int = 40_000, seed: int = 611) -> Counter[str]:
    """Order lines by volume (a long tail: a few products make most lines). Each line carries the code a vendor
    would send: the YJ code (60 %, some printed with a dash or in full width), HOT9 or HOT13 (20 %), the local code
    (17 %), or a local code the master does not hold (院内 code typed by hand, 3 %)."""
    rnd = random.Random(seed)
    weights = [1.0 / (k + 1) ** 0.9 for k in range(len(master))]
    picks = rnd.choices(master, weights=weights, k=lines)
    out: Counter[str] = Counter()
    for k, m in enumerate(picks):
        r = rnd.random()
        if r < 0.03:
            out[f"X{k % 300:05d}"] += 1
        elif r < 0.63 and m["yj"]:
            yj = m["yj"]
            out[yj if k % 10 else f"{yj[:4]}-{yj[4:]}" if k % 20 else yj.translate(_FULL)] += 1
        elif r < 0.83:
            out[m["hot"] if k % 2 else m["hot"][:9]] += 1
        else:
            out[m["local"]] += 1
    return out


_FULL = str.maketrans("0123456789", "０１２３４５６７８９")


def _write_master(path: Path, rows: list[dict[str, str]]) -> None:
    """The master as a hospital exports it: Japanese headers, Shift_JIS."""
    head = ["院内コード", "YJコード", "HOTコード", "医薬品名", "一般名"]
    with path.open("w", encoding="cp932", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for r in rows:
            w.writerow([r["local"], r["yj"], r["hot"], r["name"], r["ingredient"]])


def _write_table(path: Path, table: dict[str, dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(jp.YJ_COLS)
        for stem, r in sorted(table.items()):
            w.writerow([stem, r["ingredient"], r["route"], r["atc"], ""])


# ------------------------------------------------------------------------------------------------ STD-042 at scale
def test_95_percent_of_order_lines_resolve_on_a_2500_ingredient_master(tmp_path: Path) -> None:
    """Acceptance: on a site-shaped synthetic master of 2,500 ingredients, at least 95 % of order lines resolve to an
    ingredient; the codes that do not are listed by volume."""
    master, table = synthetic_master()
    assert len({m["yj"][:7] for m in master if m["yj"]}) == N_INGREDIENTS
    _write_master(tmp_path / "drug_master.csv", master)
    _write_table(tmp_path / "ingredient_atc.csv", table)
    resolver = jp.DrugResolver(
        jp.ingredient_atc(tmp_path / "ingredient_atc.csv"), jp.parse_drug_master(tmp_path / "drug_master.csv")
    )
    lines = synthetic_order_lines(master)
    rep = resolver.report(sorted(lines.items()))
    assert rep["lines"] == 40_000
    assert rep["ingredient_pct"] >= 95.0, rep["ingredient_pct"]
    assert 80.0 <= rep["atc_pct"] < rep["ingredient_pct"]  # 90 % of stems have ATC in the site table
    vols = [u["lines"] for u in rep["unresolved"]]
    assert vols == sorted(vols, reverse=True) and len(vols) == 50
    # the unresolved are the hand-typed codes and the 院内製剤 (a local code whose master row has no YJ)
    house = {m["local"] for m in master if not m["yj"]} | {m["hot"] for m in master if not m["yj"]}
    assert all(u["code"].startswith("X") or u["code"] in house or u["code"][:9] in {h[:9] for h in house}
               for u in rep["unresolved"])  # fmt: skip


def test_resolver_reads_each_code_form() -> None:
    master = [{"local": "L000001", "yj": "3962002F1020", "price": "", "hot": "1234567010101", "name": "x",
               "ingredient": "", "atc": ""}]  # fmt: skip
    r = jp.DrugResolver(None, master)
    for code in ("3962002F1020", "3962-002F1020", "３９６２００２Ｆ１０２０", "L000001", "1234567010101", "123456701",
                 "1234567"):  # fmt: skip
        got = r.resolve(code)
        assert got["stem"] == "3962002" and got["atc"] == "A10BA02", code  # metformin: a shipped stem
    assert r.resolve("L000001")["via"] == "master" and r.resolve("3962002F1020")["via"] == "yj"
    assert r.resolve("9999999")["stem"] == "" and r.resolve("")["via"] == ""
    # a site table's row replaces the shipped one; a master row's own ATC wins over both
    r2 = jp.DrugResolver({"3962002": {"atc": "A10BA99"}}, [{**master[0], "atc": "A10BA02"}])
    assert r2.resolve("L000001")["atc"] == "A10BA02" and r2.resolve("3962002F2020")["atc"] == "A10BA99"


def test_licensed_yj_release_gives_hot_to_yj() -> None:
    lic = {"2171022F1020": {"display": "x", "target_code": "", "extra": '{"hot13": "1111111020202"}'}}
    r = jp.DrugResolver(None, (), lic)
    assert r.resolve("111111102")["yj"] == "2171022F1020"
    assert r.resolve("111111102")["atc"] == "C08CA01"  # amlodipine: a shipped stem


def test_master_needs_a_code_column(tmp_path: Path) -> None:
    p = tmp_path / "m.csv"
    p.write_text("医薬品名,一般名\nx,y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs a local"):
        jp.parse_drug_master(p)


# ------------------------------------------------------------------------------------------------ the reader
def _omp01(root: Path, mrn: str, order: str, drug: str) -> None:
    msg = "\r".join([
        "MSH|^~\\&|HIS||TRIALBOX||20261101090000||RDE^O11|" + order + "|P|2.5||||||UNICODE UTF-8",
        f"ORC|NW|{order}||1|IP||||20261101",
        f"RXE||{drug}|1||TAB",
    ]) + "\r"  # fmt: skip
    d = storage_dir(root, mrn, "20261101", "OMP-01")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{mrn}_20261101_OMP-01_{order}_20261101090000000_-_1").write_bytes(msg.encode("utf-8"))


def _oml11(root: Path, mrn: str, order: str, jlac: str, spm4: str = "") -> None:
    msg = "\r".join([
        "MSH|^~\\&|HIS||TRIALBOX||20261101090000||OUL^R22|" + order + "|P|2.5||||||UNICODE UTF-8",
        f"SPM|1|||{spm4}" + "|" * 13 + "20261101080000",
        f"OBR|1|{order}|{order}",
        f"OBX|1|NM|{jlac}^検査^JC10||5.0|mg/dL|||||F|||20261101080000",
    ]) + "\r"  # fmt: skip
    d = storage_dir(root, mrn, "20261101", "OML-11")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{mrn}_20261101_OML-11_{order}_20261101090000000_-_1").write_bytes(msg.encode("utf-8"))


def test_reader_resolves_lines_and_lists_unmapped_by_volume(tmp_path: Path) -> None:
    """Acceptance: the ingest report (``reader.json``) lists the unmapped codes by volume; a HOT or local code the
    site's master knows reaches its YJ code, its ingredient and ATC."""
    root = tmp_path / "storage"
    master = tmp_path / "drug_master.csv"
    _write_master(master, [
        {"local": "L000001", "yj": "3962002F1020", "hot": "1234567010101", "name": "合成薬", "ingredient": "x"},
        {"local": "L000002", "yj": "", "hot": "", "name": "院内製剤", "ingredient": "y"},
    ])  # fmt: skip
    _omp01(root, "99100001", "R1", "3962002F2021^メトホルミン^99YJ")  # not in yj_to_atc.csv: the stem gives ATC
    _omp01(root, "99100001", "R2", "123456701^合成薬^HOT")
    _omp01(root, "99100001", "R3", "L000001^合成薬^99XYZ")
    for k in range(3):
        _omp01(root, "99100002", f"R4{k}", "L000002^院内製剤^99XYZ")
    _omp01(root, "99100002", "R50", "X00001^手入力^99XYZ")
    _oml11(root, "99100001", "L1", "3C015000002327101")  # in jlac10_to_loinc.csv
    _oml11(root, "99100001", "L2", "3C015000002399901")  # same analyte and material, another method: unmapped
    _oml11(root, "99100002", "L3", "3C015000002399901", spm4="023^血清^JC10")
    src = Ssmix2Source(root, licensed={}, drug_master=master)
    meds = {r["rx_no"]: r for r in src.rows("medication", "medication", None, None)}
    assert {k: (r["yj_stem"], r["atc"], r["nhi_drug_code"]) for k, r in meds.items() if k in ("R1", "R2", "R3")} == {
        "R1": ("3962002", "A10BA02", "3962002F2021"),
        "R2": ("3962002", "A10BA02", "3962002F1020"),
        "R3": ("3962002", "A10BA02", "3962002F1020"),
    }
    assert meds["R3"]["source_drug_code"] == "L000001" and meds["R40"]["yj_stem"] == ""
    labs = {r["lab_no"]: r for r in src.rows("lab", "lab", None, None)}
    specimens = sorted(r["specimen"] for r in labs.values())
    assert specimens == ["血清", "血清", "血清"]  # material 023, and SPM-4 for L3
    assert src.stats["OML-11:specimen from SPM-4"] == 1
    rep = reader_summary(src)
    assert rep["unmapped"]["medication"][:2] == [{"code": "L000002", "count": 3}, {"code": "X00001", "count": 1}]
    assert rep["unmapped"]["lab"] == [{"code": "3C015000002399901", "count": 2}]
    dr = rep["drug_resolution"]
    assert (dr["lines"], dr["ingredient"], dr["atc"]) == (7, 3, 3)
    assert dr["unresolved"][0] == {"code": "L000002", "lines": 3}


def test_specimen_from_the_licensed_material_name(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    _oml11(root, "99100003", "L9", "3C015000002999901")
    lic = {"jlac10": {"3C015000002999901": {"display": "", "target_code": "", "extra": '{"material": "合成材料"}'}}}
    src = Ssmix2Source(root, licensed=lic)
    (row,) = list(src.rows("lab", "lab", None, None))
    assert row["specimen"] == "合成材料"


# ------------------------------------------------------------------------------------------------ value sets
ATC = SYSTEMS["atc"]


def _drug_vs(families: list[tuple[str, str]] | None = None) -> ValueSets:
    concepts = [Concept(ATC, "A10BA02", "metformin")]
    vs = valueset("JPV", "VS_MET", "metformin", concepts, "1.0.0", families=families,
                  ingredients=jp.ingredient_atc())  # fmt: skip
    return ValueSets("JPV", {"VS_MET": vs})


def _crit() -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": "JPV-INC-01", "ruleset": "JPV", "text": "metformin", "kind": "inclusion", "class": "structured",
         "logic": {"domain": "medication", "valueset": "VS_MET"}}
    )  # fmt: skip


def test_a_drug_valueset_carries_the_yj_stems_of_its_atc_codes() -> None:
    vs = _drug_vs()
    assert vs.yj_stems("VS_MET") == ["3962002"]
    assert (YJ_STEM, "3962002") in vs.codes("VS_MET")
    # a grouper's ATC family brings every stem under it
    fam = yj_ingredients([], [(ATC, "A10B")], jp.ingredient_atc())
    assert {c.code for c in fam} >= {"3962002", "3969010", "3969019"}
    # without the table (every non-Japanese site, the shipped rulesets) nothing changes
    plain = valueset("JPV", "VS_MET", "metformin", [Concept(ATC, "A10BA02", "metformin")], "1.0.0")
    assert ValueSets("JPV", {"VS_MET": plain}).yj_stems("VS_MET") == []
    sql = SqlGenerator("JPV", "1.0.0", ValueSets("JPV", {"VS_MET": plain})).render([_crit()])
    assert "regexp_full_match" not in sql


def _run(sql: str, meds: dict[str, list[tuple[str | None, str | None]]]) -> dict[str, Any]:
    con = duckdb.connect()
    con.execute("CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)")
    con.execute('CREATE TABLE medication (mid VARCHAR, pid VARCHAR, nhi_code VARCHAR, atc VARCHAR, authored DATE, '
                'start DATE, "end" DATE, status VARCHAR, name VARCHAR, dose VARCHAR)')  # fmt: skip
    for i, (pid, rows) in enumerate(meds.items()):
        con.execute("INSERT INTO patient VALUES (?, DATE '1960-01-01', 'female', NULL, NULL)", [pid])
        for j, (nhi, atc) in enumerate(rows):
            con.execute("INSERT INTO medication VALUES (?, ?, ?, ?, DATE '2025-06-01', DATE '2025-06-01', NULL, "
                        "'active', 'x', NULL)", [f"m{i}{j}", pid, nhi, atc])  # fmt: skip
    rows = con.execute(sql, [[date(2026, 1, 1).isoformat()], list(meds)]).fetchall()
    cols = [d[0] for d in con.description]
    return {str(r[0]): dict(zip(cols, r, strict=True))["C_JPV-INC-01"] for r in rows}


def test_sql_matches_an_order_by_its_ingredient_without_atc() -> None:
    """STD-042: an order line with a YJ code and no ATC is read by an ATC drug criterion through its stem."""
    sql = SqlGenerator("JPV", "1.0.0", _drug_vs()).render([_crit()])
    got = _run(sql, {
        "yj_only": [("3962002F1020", None)],
        "atc_only": [(None, "A10BA02")],
        "other_drug": [("2171022F1020", None)],
        "tw_code": [("AC39620021", None)],  # a Taiwan NHI code: never read as a stem
        "none": [],
    })  # fmt: skip
    assert got == {"yj_only": True, "atc_only": True, "other_drug": False, "tw_code": False, "none": False}


def test_cql_matches_the_stem_too() -> None:
    cql = CqlGenerator("JPV", "1.0.0", _drug_vs()).render([_crit()])
    assert "Substring(Cd.code.value, 0, 7) in {'3962002'}" in cql
    assert "Matches(Cd.code.value, '[0-9]{7}[A-Z][0-9A-Z]{4}')" in cql


# ------------------------------------------------------------------------------------------------ STD-043 site set-up
def test_jlac10_analyte_and_material_suggestion() -> None:
    """A JLAC10 code with no row: the LOINC of the known codes of the same analyte and material is suggested at
    0.80 (a person confirms); another material gets none."""
    got = sm.suggest("observation", sm.local_system("lab-code"), "3C015000002399901")
    assert (got["code"], got["method"], got["confidence"]) == ("2160-0", "analyte", "0.80")
    assert got["basis"] == "3C015000002327101"
    assert sm.suggest("observation", sm.local_system("lab-code"), "3C015000000199901").get("method") != "analyte"


def test_ingredient_suggestion_without_the_reference_database() -> None:
    got = sm._yj_ingredient("3962002F9999")
    assert (got["code"], got["method"]) == ("A10BA02", "refdata")
    assert sm._yj_ingredient("1234") == {}


def test_confirmed_maps_go_into_the_adapter_lookup(tmp_path: Path) -> None:
    """NHI maps into the adapter look-up: a confirmed NHI or JLAC10 code becomes a row of the site's lab look-up
    file, read like the site's row for the same LOINC; with no such row the unit stays empty (no value is read)."""
    path = tmp_path / "lab_local_to_loinc.csv"
    head = ",".join(sm.LOOKUP_COLS)
    path.write_text(f"{head}\nCRE,loinc,2160-0,Creatinine,mg/dL,1,laboratory,quantity,,p,yes,\n", encoding="utf-8")
    with path.open(encoding="utf-8") as fh:
        templates = list(csv.DictReader(fh))
    lab = sm.local_system("lab-code")
    confirmed = {
        ("observation", lab, "09015C"): {"system": sm.LOINC, "code": "2160-0", "display": ""},
        ("observation", lab, "09999C"): {"system": sm.LOINC, "code": "1234-5", "display": "synthetic"},
        ("observation", lab, "CRE"): {"system": sm.LOINC, "code": "2160-0", "display": ""},  # the file's row wins
        ("medication", sm.local_system("drug-code"), "X1"): {"system": sm.ATC, "code": "A10BA02", "display": ""},
        ("observation", lab, "BAD"): {"system": sm.LOINC, "code": "not-loinc", "display": ""},
    }
    rows = sm.lab_lookup_rows(confirmed, templates)
    assert [r["local_code"] for r in rows] == ["09015C", "09999C", "CRE"]
    assert (rows[0]["ucum"], rows[0]["profile"], rows[0]["verified"]) == ("mg/dL", "p", "confirmed")
    assert (rows[1]["ucum"], rows[1]["factor"], rows[1]["display"]) == ("", "1", "synthetic")
    assert sm.merge_lookup(path, rows) == 2
    with path.open(encoding="utf-8") as fh:
        got = {r["local_code"]: r for r in csv.DictReader(fh)}
    assert got["CRE"]["verified"] == "yes" and got["09015C"]["code"] == "2160-0"
    assert sm.merge_lookup(path, rows) == 0
