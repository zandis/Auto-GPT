"""H-17 (D-1127, D-1128): the NHI open data as NHIA publishes it, imported, built into the shipped table and checked;
and a made-up site list of 50 lines over launch P1b's unmapped concepts, measured.

Every NHI row here is SYNTHETIC: made-up codes (``ZZ...``), made-up ATC codes (``Z99...``, a group ATC does not have)
and names marked SYNTHETIC or 合成, in the publisher's real column layout (``tests/fixtures/terminology``, licence
register row ``term-synthetic-fixtures``). A few ingredient and procedure words are ordinary English words chosen to
equal words P1b drafted, to show the path; they say nothing about the real lists. The public NHI sample rows of
``tests/fixtures/refdata`` (OGDL 1.0, row ``nhi-codes``) are used where they exist. The site list is no hospital's:
its ICD-10-CM codes are real (public domain, checked against the shipped full list), its LOINC-, ATC- and NHI-shaped
codes are made up. The concept list is the distinct concepts the compiler drafted from P1b's public
ClinicalTrials.gov protocols (row ``p1b-concept-names``), so the measure runs in CI without the archive."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.terminology import installed
from criteria_compiler.terminology.mapper import SYSTEMS, Terminology
from tb_common.refdata_tw import latest_nhi_rows, parse_nhi_services

from tools import licence_register, terminology_coverage, terminology_install

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/fixtures/terminology"
REFDATA = ROOT / "tests/fixtures/refdata"
DRUGS, SERVICES = FIX / "nhi_drugs_synthetic.csv", FIX / "nhi_services_synthetic.csv"
SITE, CONCEPTS = FIX / "site_list_synthetic.csv", FIX / "p1b_concepts.csv"
NOTHING = Path("/nonexistent/terminology-none")


@pytest.fixture(autouse=True)
def _no_shipped_tables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Each test sees an empty shipped folder unless it builds one (the repository's own is checked apart)."""
    monkeypatch.setattr(installed, "SHIPPED_DIR", tmp_path / "shipped-none")


def _measure(where: Path) -> dict[str, Any]:
    return terminology_coverage.measure_concepts(CONCEPTS.read_text(encoding="utf-8"), Terminology(installed=where))


def _resolved(result: dict[str, Any]) -> dict[str, int]:
    return {d: v[1] for d, v in result["by_domain"].items()}


# -------------------------------------------------------------------------------- the publisher's files, read
def test_the_loaders_read_the_public_samples_as_lane_es_readers_do() -> None:
    """The committed public rows give the same table as before H-17 (``tb_common.refdata_tw``'s readers)."""
    drugs = installed.nhi_drug_rows((REFDATA / "nhi_drugs_sample.csv").read_bytes())
    old = latest_nhi_rows(REFDATA / "nhi_drugs_sample.csv")
    assert [(r["nhi_code"], r["name_zh"], r["ingredient"], r["atc"], r["valid_to"]) for r in drugs] == [
        (c, r["藥品中文名稱"], r["成分"], r["ATC代碼"], r["有效迄日"]) for c, r in sorted(old.items())
    ]
    services = installed.nhi_service_rows((REFDATA / "nhi_services_sample.csv").read_bytes())
    assert [(r["code"], r["display"], r["display_en"], r["valid_to"]) for r in services] == [
        (t["code"], t["display"], t["extra"]["en"], t["extra"]["valid_to"])
        for t in parse_nhi_services(REFDATA / "nhi_services_sample.csv")
    ]


def test_utf8_and_big5_give_the_same_table(tmp_path: Path) -> None:
    for src, reader in ((DRUGS, installed.nhi_drug_rows), (SERVICES, installed.nhi_service_rows)):
        text = src.read_text(encoding="utf-8").lstrip("﻿")
        big5 = tmp_path / f"big5-{src.name}"
        big5.write_bytes(text.encode("cp950"))
        assert reader(big5.read_bytes()) == reader(src.read_bytes())
    assert len(installed.nhi_drug_rows(DRUGS.read_bytes())) == 31  # 32 rows, one code with two periods
    assert len(installed.nhi_service_rows(SERVICES.read_bytes())) == 19


def test_the_header_is_read_as_published_with_its_variants() -> None:
    text = SERVICES.read_text(encoding="utf-8")
    head, rest = text.split("\n", 1)
    want = installed.nhi_service_rows(text.encode("utf-8"))
    variants = [
        "﻿" + head,  # a BOM
        head.replace("診療項目代碼", " 診療項目代碼 ").replace("中文項目名稱", '"中文項目名稱"'),  # spaces, quotes
        head.replace("英文項目名稱", "英文 項目名稱"),
    ]
    for h in variants:
        assert installed.nhi_service_rows(f"{h}\n{rest}".encode()) == want
    drugs = DRUGS.read_text(encoding="utf-8").replace("ATC代碼", "ＡＴＣ代碼", 1)  # full-width Latin letters
    assert installed.nhi_drug_rows(drugs.encode()) == installed.nhi_drug_rows(DRUGS.read_bytes())
    renamed = DRUGS.read_text(encoding="utf-8").replace("ATC代碼", "ATC CODE (WHO)", 1)
    with pytest.raises(ValueError, match="no column ATC代碼 .*give --column ATC代碼=<its header>"):
        installed.nhi_drug_rows(renamed.encode())
    assert installed.nhi_drug_rows(renamed.encode(), columns={"ATC代碼": "ATC CODE (WHO)"}) == installed.nhi_drug_rows(
        DRUGS.read_bytes()
    )


def _swap(text: str, old: str, new: str) -> bytes:
    assert old in text
    return text.replace(old, new, 1).encode("utf-8")


@pytest.mark.parametrize(("which", "old", "new", "error"), [
    ("drugs", ",ZZ00001300,", ",ZZ0013,", r"row 4 \(line 4\): 藥品代號 'ZZ0013' is not a 10-character NHI drug code"),
    ("drugs", "1080701", "1081301", r"row 4 \(line 4\): 有效起日 '1081301' is not a date"),
    ("drugs", ",Z99XB04,,,", ",Z99XB04,,,,", r"row 5 \(line 5\): 21 fields, the header has 20"),
    ("services", "ZZ905C,10,", "ZZ905C,", r"row 7 \(line 8\): 6 fields, the header has 7"),  # after a two-line note
    ("services", "ZZ906B", "ZZ-906", r"row 8 \(line 9\): 診療項目代碼 'ZZ-906' is not an NHI service or order code"),
    ("services", "20201231", "2020-13-31", r"row 6 \(line 7\): 生效迄日 '2020-13-31' is not a date"),
    ("services", "健保支付點數", "點數", r"no column 健保支付點數"),
    ("services", "英文項目名稱", "中文項目名稱", r"the header has column 中文項目名稱 2 times"),
])  # fmt: skip
def test_a_malformed_row_refuses_the_whole_file_naming_it(which: str, old: str, new: str, error: str) -> None:
    src, reader = (DRUGS, installed.nhi_drug_rows) if which == "drugs" else (SERVICES, installed.nhi_service_rows)
    with pytest.raises(ValueError, match=error):
        reader(_swap(src.read_text(encoding="utf-8"), old, new))


def test_the_cli_refuses_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_bytes(_swap(DRUGS.read_text(encoding="utf-8"), ",ZZ00001300,", ",ZZ0013,"))
    assert terminology_install.main(["nhi-drugs", str(bad), "--dir", str(tmp_path / "t")]) == 2
    assert "refused: bad.csv, row 4 (line 4)" in capsys.readouterr().err
    assert not (tmp_path / "t" / "manifest.json").exists()
    assert terminology_install.main(["nhi-drugs", str(DRUGS), "--dir", str(tmp_path / "t"), "--column", "x"]) == 2
    assert "--column 'x': write it OURS=THEIRS" in capsys.readouterr().err
    assert (
        terminology_install.main(["nhi-drugs", str(DRUGS), "--dir", str(tmp_path / "t"), "--column", "規格量=x"]) == 2
    )
    assert "not a column this loader reads" in capsys.readouterr().err
    for empty in (b"", "﻿診療項目代碼,健保支付點數,生效起日,生效迄日,中文項目名稱\n".encode()):
        with pytest.raises(ValueError, match="empty, no header|no rows under the header"):
            installed.nhi_service_rows(empty)


# ----------------------------------------------------------------------------- what the extract answers, and moves
@pytest.fixture(scope="module")
def nhi(tmp_path_factory: pytest.TempPathFactory) -> Path:
    where = tmp_path_factory.mktemp("h17") / "terminology"
    assert terminology_install.main(["nhi-drugs", str(DRUGS), "--dir", str(where), "--version", "SYNTHETIC"]) == 0
    assert terminology_install.main(["nhi-services", str(SERVICES), "--dir", str(where)]) == 0
    return where


def test_the_extract_answers_newest_periods_ended_codes_and_shared_names(nhi: Path) -> None:
    t = Terminology(installed=nhi)
    hd = t.map("procedure", "Hemodialysis")  # two items share the name: both, for review (D-1114 point 3)
    assert hd.method == "loaded" and hd.needs_review and {c.code for c in hd.concepts} == {"ZZ901C", "ZZ902B"}
    br = t.map("procedure", "bronchoscopy")  # two periods of one code: one answer (a billing item: for review)
    assert br.needs_review and [(c.system, c.code) for c in br.concepts] == [(SYSTEMS["nhi_order"], "ZZ903C")]
    assert t.map("procedure", "Colonoscopy").method == "none"  # ended 2020-12-31
    assert t.map("procedure", "合成項目民國日期").concepts[0].code == "ZZ907C"  # 民國 dates read
    hep = t.map("medication", "heparin")  # one ingredient, two drugs, two ATC codes: both, for review
    assert hep.needs_review and {c.code for c in hep.concepts} == {"Z99XB01", "Z99XB02"}
    assert [c.code for c in t.map("medication", "acetazolamide").concepts] == ["Z99XB05"]  # its newest period
    assert t.map("medication", "nicorandil").method == "none"  # ended 2014-06-30
    assert t.map("medication", "synthetamide").method == "none"  # a combination gives no ingredient
    rows = installed.read_table(nhi, installed.NHI_DRUGS) or []
    assert sum(1 for r in rows if r["atc"] == "") == 5  # "N/A" is no ATC code: kept as no code


def test_the_extract_moves_only_what_its_made_up_names_happen_to_match(nhi: Path) -> None:
    """A mechanism test, not a coverage figure (D-1127): 261 of 1,273 with committed data only, 276 with the extract
    (266 and 281 before V-18b: five drug names were WHOCC's, which no longer ship, D-1183)."""
    before, after = _measure(NOTHING), _measure(nhi)
    assert _resolved(before) == {"claim": 0, "condition": 255, "encounter": 0, "medication": 1, "observation": 5,
                                 "procedure": 0}  # fmt: skip
    assert _resolved(after) == {**_resolved(before), "medication": 8, "procedure": 8}
    assert after["methods"]["loaded"] == 15
    assert after["for_review"]["medication"] == 7 and after["for_review"]["procedure"] == 8  # every service answer


# --------------------------------------------------------------------------------------- the shipped NHI table
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _build(where: Path, kind: str = "drugs", src: Path = DRUGS, sha: str = "") -> int:
    return terminology_install.main(["nhi-build", kind, str(src), "--version", "2099-01-01 SYNTHETIC",
                                     "--fetched-on", "2099-01-02", "--sha256", sha or _sha(src), "--out", str(where)])  # fmt: skip


def test_the_build_writes_the_shipped_table_with_its_manifest_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    where = tmp_path / "shipped"
    assert _build(where, sha="0" * 64) == 2
    assert "its sha256 is" in capsys.readouterr().err and not where.exists()
    assert _build(where) == 0 and _build(where, "services", SERVICES) == 0
    out = capsys.readouterr().out
    assert "nhi_drug_list: 31 rows built into" in out and "政府資料開放授權條款" in out
    assert sorted(p.name for p in where.iterdir()) == ["manifest.json", "nhi_drug_list.parquet",
                                                      "nhi_service_list.parquet"]  # fmt: skip
    line = installed.manifest(where)["tables"][installed.NHI_DRUGS]
    assert line["source_sha256"] == _sha(DRUGS) and line["fetched_on"] == "2099-01-02"
    assert line["loaded_at"] == "2099-01-02T00:00:00+00:00"  # no clock: the day of the fetch
    assert (
        line["attribution"] == installed.NHI_DRUG_ATTRIBUTION
        and "https://data.gov.tw/license" in line["ogdl_statement"]
    )
    assert "衛生福利部中央健康保險署 健保用藥品項查詢項目檔 2099-01-01 SYNTHETIC" in line["ogdl_statement"]
    first = {p.name: p.read_bytes() for p in where.iterdir()}
    assert _build(where) == 0 and _build(where, "services", SERVICES) == 0  # a rebuild writes the same bytes
    assert {p.name: p.read_bytes() for p in where.iterdir()} == first
    assert installed.shipped_problems(where) == []


def test_the_check_finds_a_changed_or_unattributed_shipped_table(tmp_path: Path) -> None:
    where = tmp_path / "shipped"
    assert _build(where) == 0
    m = json.loads((where / "manifest.json").read_text(encoding="utf-8"))
    m["tables"][installed.NHI_DRUGS]["attribution"] = ""
    (where / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert installed.shipped_problems(where) == [
        "nhi_drug_list: its manifest line lacks the OGDL licence or the provider's attribution"
    ]
    (where / "nhi_drug_list.parquet").write_bytes(b"PAR1 changed")
    (where / "loinc_table.parquet").write_bytes(b"PAR1")
    got = installed.shipped_problems(where)
    assert got[0].startswith("loinc_table: not NHI open data") and "its sha256 differs" in got[1]


def test_the_check_needs_a_cleared_register_row_for_a_shipped_table() -> None:
    where = ROOT / "services/criteria_compiler/terminology/shipped"
    lines: dict[str, Any] = {installed.NHI_DRUGS: {}}
    rows = licence_register.load()
    assert terminology_install.register_problems(where, lines, rows) == [
        f"services/criteria_compiler/terminology/shipped/{f}: no cleared OGDL row in docs/licences/register.csv names "
        "it (row nhi-open-data-full)"
        for f in ("nhi_drug_list.parquet", "manifest.json")
    ]
    raw = dict(rows[0].raw)
    ok = licence_register.Row("nhi-open-data-full", "code-system", "cleared", "x", "LicenseRef-OGDL-Taiwan-1.0", (),
                              ("services/criteria_compiler/terminology/shipped/*",), raw)  # fmt: skip
    assert terminology_install.register_problems(where, lines, [ok]) == []


def test_the_repositorys_shipped_nhi_tables_pass_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """What ships is checked in CI: nothing (the integrator has not fetched the files yet) or a table that passes."""
    monkeypatch.setattr(installed, "SHIPPED_DIR", ROOT / "services/criteria_compiler/terminology/shipped")
    assert terminology_install.main(["nhi-check"]) == 0


def test_the_mapper_reads_a_shipped_table_and_a_loaded_one_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # fmt: skip
    shipped = tmp_path / "shipped"
    assert _build(shipped, "services", SERVICES) == 0
    monkeypatch.setattr(installed, "SHIPPED_DIR", shipped)
    t = Terminology(installed=tmp_path / "empty")
    assert t.map("procedure", "acupuncture").concepts[0].code == "ZZ905C"
    assert t.loaded_sources == {installed.NHI_SERVICES: "2099-01-01 SYNTHETIC"}
    assert "NHI service codes" not in installed.not_loaded(tmp_path / "empty")
    own = tmp_path / "loaded"
    svc = "診療項目代碼,健保支付點數,生效起日,生效迄日,英文項目名稱,中文項目名稱,備註\nZZ999C,1,20200101,29101231,Acupuncture,合成,\n"
    (tmp_path / "own.csv").write_text(svc, encoding="utf-8")
    installed.install_nhi_services(tmp_path / "own.csv", own)
    assert [c.code for c in Terminology(installed=own).map("procedure", "acupuncture").concepts] == ["ZZ999C"]
    (shipped / "nhi_service_list.parquet").write_bytes(b"PAR1 changed")  # a changed shipped table is refused
    t = Terminology(installed=tmp_path / "empty")
    assert t.map("procedure", "acupuncture").method == "none" and "sha256 differs" in t.installed_problems[0]


# ---------------------------------------------------------------------------- the made-up site list (D-1128)
def test_the_site_list_is_fifty_synthetic_lines_with_checked_codes() -> None:
    rows = list(csv.DictReader(io.StringIO(SITE.read_text(encoding="utf-8"))))
    assert len(rows) == 50 and all(r["display"].startswith("SYNTHETIC list row (no hospital's)") for r in rows)
    full = {r["code"] for r in Terminology(installed=NOTHING).full["icd10cm"]}
    by = {s: [r["code"] for r in rows if r["system"] == s] for s in {r["system"] for r in rows}}
    assert {s: len(c) for s, c in by.items()} == {"icd10cm": 20, "loinc": 15, "atc": 9, "nhi_order": 6}
    assert set(by["icd10cm"]) <= full  # real ICD-10-CM codes (public domain), each in the shipped full list
    assert all(c.startswith("99000") and len(c) == 9 for c in by["loinc"])  # 7 digits: beyond any issued LOINC code
    assert all(c.startswith("Z99") for c in by["atc"])  # ATC has no group Z
    assert all(c.startswith("ZZ") for c in by["nhi_order"])


def test_a_fifty_line_site_list_moves_the_share_by_its_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    """Measured through the real ``site-list`` subcommand and the coverage tool (D-1128): 261 of 1,273 before, 391
    after (266 and 396 before V-18b, D-1183: five drug names were WHOCC's). Every newly mapped concept comes from the list (method ``site``); those whose code no table holds (the
    made-up LOINC, ATC and NHI codes) answer for review."""
    where = tmp_path / "terminology"
    assert terminology_install.main(["site-list", str(SITE), "--name", "synthetic", "--dir", str(where)]) == 0
    assert "site_synthetic: 50 rows loaded" in capsys.readouterr().out
    before, after = _measure(NOTHING), _measure(where)
    assert sum(_resolved(before).values()) == 261 and sum(_resolved(after).values()) == 391
    assert _resolved(after) == {"claim": 0, "condition": 302, "encounter": 0, "medication": 23, "observation": 50,
                                "procedure": 16}  # fmt: skip
    assert after["methods"] == {**before["methods"], "site": 130}
    new_review = {d: after["for_review"].get(d, 0) - before["for_review"].get(d, 0) for d in after["by_domain"]}
    assert new_review == {"claim": 0, "condition": 0, "encounter": 0, "medication": 22, "observation": 45,
                          "procedure": 16}  # fmt: skip
    lines = installed.manifest(where)["tables"]["site_synthetic"]
    assert lines["rows"] == 50 and lines["licence"] == installed.SITE_LICENCE


def test_the_concept_list_reproduces_the_launch_figures() -> None:
    """The committed concept list (derived by ``--write-concepts`` from P1b's raw-traces.json, archive sha256
    667d92f5...) gives the archive's own figures: 1,273 concepts, 266 resolved with committed data only then; 261
    since V-18b (D-1183): six drug names matched WHOCC's names, which no longer ship, and one of them (methotrexate)
    resolves through TrialBox's own grouper instead."""
    rows = list(csv.DictReader(io.StringIO(CONCEPTS.read_text(encoding="utf-8"))))
    assert len(rows) == 1045 and sum(int(r["count"]) for r in rows) == 1273
    result = _measure(NOTHING)
    assert {d: v[0] for d, v in result["by_domain"].items()} == {"claim": 4, "condition": 588, "encounter": 51,
                                                                 "medication": 177, "observation": 308,
                                                                 "procedure": 145}  # fmt: skip
    assert result["methods"] == {"exact": 3, "icd10cm": 208, "synonym": 50}
    assert terminology_coverage.write_concepts(rows) == CONCEPTS.read_text(encoding="utf-8")


# ------------------------------------------------------------------- after the class B review (D-1127, same PR)
def test_review_1_a_refused_shipped_table_is_not_counted_and_the_doctor_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tools.trialbox import doctor

    shipped = tmp_path / "shipped"
    assert _build(shipped, "services", SERVICES) == 0
    monkeypatch.setattr(installed, "SHIPPED_DIR", shipped)
    env = {"TB_TERMINOLOGY_DIR": str(tmp_path / "empty")}
    good = doctor.check_terminology(doctor.DoctorInputs(env=env))
    assert good.status == "PASS" and "shipped: nhi_service_list 19 rows (2099-01-01 SYNTHETIC)" in good.detail
    assert "NHI service codes" not in installed.not_loaded(tmp_path / "empty")
    (shipped / "nhi_service_list.parquet").write_bytes(b"PAR1 changed")
    assert "NHI service codes" in installed.not_loaded(tmp_path / "empty")
    bad = doctor.check_terminology(doctor.DoctorInputs(env=env))
    assert bad.status == "FAIL" and "shipped" in bad.detail and "sha256 differs" in bad.detail


def test_review_2_a_combination_product_never_answers_for_its_one_named_ingredient(nhi: Path) -> None:
    """NHIA writes one ingredient in 成分 for some 複方 products: such a row stays out of the ingredient index."""
    rows = {r["nhi_code"]: r for r in installed.read_table(nhi, installed.NHI_DRUGS) or []}
    assert rows["ZZ00001900"]["kind"] == "複方" and rows["ZZ00001800"]["kind"] == "單方"
    r = Terminology(installed=nhi).map("medication", "synthetidine")
    assert [c.code for c in r.concepts] == ["Z99XD01"]


@pytest.mark.parametrize(("old", "new", "error"), [
    ("1080701", "01080701", r"row 4 \(line 4\): 有效起日 '01080701' is not a date"),  # a zero-padded 民國 date
    ("1080701", "1900-07-01", r"row 4 \(line 4\): 有效起日 '1900-07-01' is not a date"),  # before 1911
])  # fmt: skip
def test_review_3_a_date_before_1911_or_zero_padded_is_refused(old: str, new: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        installed.nhi_drug_rows(_swap(DRUGS.read_text(encoding="utf-8"), old, new))


def test_review_4_conflicting_periods_of_one_code_refuse_the_file() -> None:
    text = SERVICES.read_text(encoding="utf-8")
    twin = text.replace("ZZ903C,60,20200101,29101231,Bronchoscopy", "ZZ903C,60,20150101,29101231,Bronchoscopy B", 1)
    with pytest.raises(ValueError, match=r"rows 4 and 5: code ZZ903C has two periods with the same start 2015-01-01"):
        installed.nhi_service_rows(twin.encode())
    row = next(line for line in text.splitlines() if line.startswith("ZZ903C,50,"))
    same = text.replace(row, f"{row}\n{row}", 1)  # a row repeated as it is: one row
    assert installed.nhi_service_rows(same.encode()) == installed.nhi_service_rows(text.encode())
    with pytest.raises(ValueError, match=r"row 6 \(line 7\): 生效迄日 2010-01-01 is before 生效起日 2010-12-31"):
        installed.nhi_service_rows(_swap(text, "20100101,20201231", "20101231,20100101"))


def test_review_5_two_of_our_columns_never_read_one_header() -> None:
    with pytest.raises(ValueError, match="中文項目名稱 and 英文項目名稱 both read the header 中文項目名稱"):
        installed.nhi_service_rows(SERVICES.read_bytes(), columns={"英文項目名稱": "中文項目名稱"})


def test_review_6_the_build_hashes_the_bytes_it_parses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reads: list[Path] = []
    real, sha = Path.read_bytes, _sha(DRUGS)

    def counted(self: Path) -> bytes:
        if self.name == DRUGS.name:
            reads.append(self)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", counted)
    assert _build(tmp_path / "shipped", sha=sha) == 0
    assert len(reads) == 1


def test_review_7_nhi_check_names_the_notice_lines_a_shipped_table_needs() -> None:
    lines: dict[str, Any] = {installed.NHI_DRUGS: {}, installed.NHI_SERVICES: {}}
    got = terminology_install.notice_problems(lines, (ROOT / "NOTICE").read_text(encoding="utf-8"))
    assert got == ["NOTICE section 8 lacks the line: " + terminology_install.NOTICE_FOLDER_LINE.strip()]
    # both attributions are in NOTICE already (the samples of data sets 23715 and 174450 ship today)
    assert terminology_install.notice_problems(lines, "") == [
        "NOTICE section 8 lacks the line: " + terminology_install.NOTICE_FOLDER_LINE.strip(),
        f"NOTICE lacks the attribution of nhi_drug_list: {installed.NHI_DRUG_ATTRIBUTION}",
        f"NOTICE lacks the attribution of nhi_service_list: {installed.NHI_SERVICE_ATTRIBUTION}",
    ]
    assert terminology_install.notice_problems({}, "") == []


def test_review_8_and_the_rule_an_answer_from_the_shipped_table_says_so_and_a_service_goes_for_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shipped = tmp_path / "shipped"
    assert _build(shipped, "services", SERVICES) == 0
    monkeypatch.setattr(installed, "SHIPPED_DIR", shipped)
    r = Terminology(installed=tmp_path / "empty").map("procedure", "acupuncture")
    assert r.method == "loaded" and r.needs_review  # one billing item may be narrower than the word (D-1127)
    assert r.notes == ["shipped NHI table 2099-01-01 SYNTHETIC: nhi_service_list"]


def test_review_11_the_shipped_folder_holds_only_its_three_files_and_a_well_formed_line(tmp_path: Path) -> None:
    where = tmp_path / "shipped"
    assert _build(where) == 0
    (where / "site_list.csv").write_text("local_name,code\nx,I10\n", encoding="utf-8")
    assert installed.shipped_problems(where) == ["site_list.csv: not a file the shipped folder may hold"]
    (where / "site_list.csv").unlink()
    m = json.loads((where / "manifest.json").read_text(encoding="utf-8"))
    m["tables"][installed.NHI_DRUGS]["fetched_on"] = "yesterday"
    (where / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert installed.shipped_problems(where) == [
        "nhi_drug_list: its manifest line's fetched_on 'yesterday' is not a day"
    ]


def test_review_13_the_build_refuses_a_live_install_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live = tmp_path / "terminology"
    installed.install_site_list(SITE, live, "synthetic")
    assert _build(live) == 2  # a folder with another table: never written, its lock never touched
    assert installed.read_table(live, installed.NHI_DRUGS) is None and (live / ".manifest.lock").exists()
    monkeypatch.setenv("TB_TERMINOLOGY_DIR", str(tmp_path / "box"))
    assert _build(tmp_path / "box") == 2
