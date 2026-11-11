"""The vocabulary schema (WS-03.3, D-301): OMOP's vocabulary tables as the one home of the codes, the release pin
and the recompile flag, the one-million site block, the chart-number normaliser (R-48), the NHIA edition map and the
JP masters' WHO-only codes. Synthetic and public data only."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology import resolver
from criteria_compiler.terminology.mapper import TERM_DIR, Terminology, ValueSets
from tb_common import chartno
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import RecompileNeeded, Ruleset, list_rulesets, load_approved

from tests.rulesets_guard import copy_rulesets

ROOT = Path(__file__).resolve().parents[2]
RULESETS = ROOT / "rulesets"
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "vocab"
KEY = b"k" * 32


# ------------------------------------------------------------------------------------------------ chart numbers
@pytest.mark.parametrize(
    ("rule", "value", "want"),
    [
        ("asis", " 00123456 ", "00123456"),
        ("asis", "００１２３", "00123"),  # full width to half width, nothing else
        ("digits", "00123456", "123456"),
        ("digits", "123456", "123456"),
        ("digits", "0", "0"),
        ("digits:8", "123456", "00123456"),
        ("digits:8", "00123456", "00123456"),
        ("digits:8", "１２３４５６", "00123456"),
        ("digits:4", "123456", "123456"),  # never cut: two numbers must not become one
        ("digits:8", "A12345", "A12345"),  # not all digits: left as written, never guessed
        ("hex", "00ab12", "AB12"),
        ("hex:6:lower", "AB12", "00ab12"),
        ("hex:6", "ab12", "00AB12"),
    ],
)
def test_chartno_normalise(rule: str, value: str, want: str) -> None:
    assert chartno.normalise(rule, value) == want
    assert chartno.normalise(rule, want) == want  # idempotent: a normalised number is unchanged


def test_chartno_rule_is_read_and_refused_when_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in ("zeros", "digits:x", "digits:0", "asis:8", "digits:8:lower"):
        with pytest.raises(chartno.ChartNoError):
            chartno.parse_rule(bad)
    assert str(chartno.parse_rule("HEX:8:lower")) == "hex:8:lower"
    monkeypatch.setenv(chartno.ENV, "digits:8")
    assert chartno.normalise(None, "42") == "00000042"
    monkeypatch.delenv(chartno.ENV)
    assert chartno.normalise(None, "42") == "42"


IDS = ["10000001", "00012345", "A0001", "ab12f", "P-77", "２００１", " 123 ", "ﾃｽﾄ1"]


def test_default_rule_keeps_every_pseudonym_the_box_has_made(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pid of an already-normalised chart number is the HMAC of D-09 exactly as before D-301."""
    monkeypatch.delenv(chartno.ENV, raising=False)

    def old(mrn: str) -> str:
        return hmac.new(KEY, mrn.strip().encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    for mrn in IDS:
        if mrn.isascii():
            assert pid_for_mrn(KEY, mrn) == old(mrn), mrn
    # site set-up half-widthed before D-301 too: its pseudonym of a full-width number is unchanged
    assert pid_for_mrn(KEY, "２００１") == old("2001")


def test_a_zero_padded_number_is_one_patient_under_the_site_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter.pidmap import pseudonym

    monkeypatch.setenv(chartno.ENV, "digits:8")
    assert pid_for_mrn(KEY, "123456") == pid_for_mrn(KEY, "00123456") == pid_for_mrn(KEY, "１２３４５６")
    assert pseudonym(KEY, "123456") == (pid_for_mrn(KEY, "00123456"), "00123456")
    monkeypatch.setenv(chartno.ENV, "hex")
    assert pid_for_mrn(KEY, "ab12") == pid_for_mrn(KEY, "00AB12")


def test_pidmap_unchanged_for_normalised_ids_and_stores_the_site_form(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.pidmap import PidMap

    monkeypatch.delenv(chartno.ENV, raising=False)
    pm = PidMap(tmp_path / "pid_map.key", db_url)
    try:
        pairs = [(pid_for_mrn(pm.key, m), m) for m in IDS if m.isascii() and m == m.strip()]
        assert pm.upsert_many(pairs) == len(pairs)
        assert pm.resolve_many([p for p, _ in pairs]) == dict(pairs)  # stored and read back exactly as given
        assert pm.upsert_many(pairs) == 0
        monkeypatch.setenv(chartno.ENV, "digits:8")
        pid = pid_for_mrn(pm.key, "4242")
        assert pm.upsert_many([(pid, "4242"), (pid_for_mrn(pm.key, "00004242"), "00004242")]) == 1
        assert pm.resolve(pid) == "00004242"
    finally:
        pm.close()


def test_site_setup_pseudonym_goes_through_the_normaliser(monkeypatch: pytest.MonkeyPatch) -> None:
    from sitesetup.service import SiteSetup

    monkeypatch.setenv(chartno.ENV, "digits:8")
    svc = SiteSetup.__new__(SiteSetup)
    svc.site_key = lambda: KEY
    assert svc.pseudonym("１２３") == svc.pseudonym("00000123") == pid_for_mrn(KEY, "123")


# ------------------------------------------------------------------------------------------------ the site block
def test_block_is_one_million_and_overflow_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from omop import schema

    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    assert schema.concept_block() == (2_100_000_000, 2_100_999_999)
    last_first = schema.INT4_MAX - schema.BLOCK_SIZE + 1
    monkeypatch.setenv("TB_OMOP_CONCEPT_BLOCK", str(last_first))
    assert schema.concept_block() == (last_first, 2_147_483_647)  # the last block ends exactly at the maximum
    for first in (last_first + 1, 2_147_000_000, 2_147_483_646):
        monkeypatch.setenv("TB_OMOP_CONCEPT_BLOCK", str(first))
        with pytest.raises(schema.OmopError, match="2,147,483,647"):
            schema.concept_block()
        with pytest.raises(schema.OmopError):
            schema.migrations()  # a box with an overflowing block does not start
    # migration 2 keeps the text it was applied with (D-204): the ten-million block of D-151
    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK")
    assert "MAXVALUE 2109999999" in schema.tb_ddl() and "MAXVALUE 2100999999" in schema.vocab_ddl()


@pytest.fixture
def omop(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    from omop import schema

    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    monkeypatch.delenv("TB_OMOP_DB_URL", raising=False)
    db = schema.connect(db_url)
    yield db
    db.close()


def test_minting_past_the_block_end_is_refused(omop: Any) -> None:
    from omop.vocab import Code, Concepts

    omop.execute("SELECT setval('tb_local_concept_seq', 2100999999)")
    with pytest.raises(Exception, match="maximum value"), omop.transaction() as tx:
        Concepts(tx).prepare([Code("urn:site:lab", "X1", "x", "Measurement")])


# ------------------------------------------------------------------------------------------------ loads and releases
def _counts(db: Any) -> dict[str, Any]:
    tables = ("concept", "vocabulary", "concept_synonym", "concept_relationship", "source_to_concept_map",
              "tb_concept_attr", "tb_term_grouper", "tb_vocab_release", "tb_map_relation", "tb_ruleset_release")  # fmt: skip
    out: dict[str, Any] = {t: db.fetchval(f"SELECT count(*) FROM {t}") for t in tables}
    out["release_rows"] = db.fetchall("SELECT release_name, sha256, active, loaded_at FROM tb_vocab_release ORDER BY 1")
    out["marks"] = db.fetchall("SELECT ruleset_id, recompile_needed, marked_at FROM tb_ruleset_release ORDER BY 1")
    return out


def _rulesets(tmp_path: Path, pin: str | None = None) -> Path:
    out = tmp_path / "rulesets"
    for rid in list_rulesets(RULESETS):
        copy_rulesets(out / rid, src=RULESETS / rid)
        if pin:
            _pin(out / rid, pin)
    return out


def _pin(directory: Path, release: str) -> None:
    m = directory / "manifest.yaml"
    lines = [ln for ln in m.read_text(encoding="utf-8").splitlines() if not ln.startswith("terminology_release:")]
    m.write_text("\n".join([*lines, f"terminology_release: {release}"]) + "\n", encoding="utf-8")


FY2027 = [("M10.9", "Gout, unspecified"), ("M10.00", "Idiopathic gout, unspecified site"),
          ("E11.9", "Type 2 diabetes mellitus without complications"), ("Z99.9", "Synthetic FY2027 code")]  # fmt: skip


def test_a_release_loaded_twice_changes_nothing(omop: Any, tmp_path: Path) -> None:
    from omop import vocab_load

    first = vocab_load.load_terminology(omop, TERM_DIR)
    assert first.new and first.concepts > 98_000
    rel = vocab_load.terminology_release(omop)
    assert rel == resolver.parquet_release(TERM_DIR)  # the Parquet's release and the vocabulary's are one id
    before = _counts(omop)
    again = vocab_load.load_terminology(omop, TERM_DIR)
    assert not again.new and again.changed == 0 and _counts(omop) == before
    cl = vocab_load.load_code_list(omop, vocab_load.ICD10CM_URI, "FY2027", FY2027, source="fy2027.csv")
    assert cl.new
    before = _counts(omop)
    assert not vocab_load.load_code_list(omop, vocab_load.ICD10CM_URI, "FY2027", FY2027, source="again").new
    assert _counts(omop) == before


def test_a_local_code_never_becomes_standard(omop: Any) -> None:
    from omop import vocab_load
    from omop.schema import OmopError

    vocab_load.load_terminology(omop, TERM_DIR)
    n = vocab_load.load_local_codes(omop, [
        {"domain": "condition", "system": "urn:trialbox:local:dx", "code": "痛風9", "display": "痛風（院内）",
         "mapped_system": vocab_load.ICD10CM_URI, "mapped_code": "M10.9", "mapped_display": "Gout"},
        {"domain": "observation", "system": "urn:trialbox:local:lab", "code": "UA", "display": "尿酸",
         "mapped_system": "http://loinc.org", "mapped_code": "3084-1", "mapped_display": ""},
        {"domain": "condition", "system": "urn:trialbox:local:dx", "code": "X", "display": "unmapped"},
    ])  # fmt: skip
    assert n == 2
    stcm = omop.fetchdicts("SELECT s.source_code, s.source_concept_id, c.concept_code, c.vocabulary_id FROM "
                           "source_to_concept_map s JOIN concept c ON c.concept_id = s.target_concept_id "
                           "ORDER BY 1")  # fmt: skip
    assert [(r["source_code"], r["concept_code"], r["vocabulary_id"]) for r in stcm] == [
        ("UA", "3084-1", "LOINC"), ("痛風9", "M10.9", "ICD10CM")]  # fmt: skip
    first, last = 2_100_000_000, 2_100_999_999
    assert all(first <= r["source_concept_id"] <= last for r in stcm)  # the site block
    assert omop.fetchval("SELECT count(*) FROM concept WHERE concept_id >= 2000000000 AND standard_concept = 'S'") == 0
    # a remap replaces the row, never a second map
    vocab_load.load_local_codes(omop, [{"domain": "condition", "system": "urn:trialbox:local:dx", "code": "痛風9",
                                        "mapped_system": vocab_load.ICD10CM_URI, "mapped_code": "M10.00"}])  # fmt: skip
    assert omop.fetchval("SELECT count(*) FROM source_to_concept_map WHERE source_code = '痛風9'") == 1
    # a custom concept made standard by hand is refused by the next load, which changes nothing
    omop.execute("UPDATE concept SET standard_concept = 'S' WHERE concept_id = ?", (stcm[0]["source_concept_id"],))
    with pytest.raises(OmopError, match="never standard"):
        vocab_load.load_local_codes(omop, [{"domain": "condition", "system": "urn:x", "code": "Y",
                                            "mapped_system": vocab_load.ICD10CM_URI, "mapped_code": "M10.9"}])  # fmt: skip
    assert omop.fetchval("SELECT count(*) FROM concept WHERE vocabulary_id <> 'None' AND concept_code = 'Y'") == 0


def test_icd10cm_fy2027_marks_every_approved_ruleset(omop: Any, tmp_path: Path) -> None:
    from omop import vocab_load

    rs_dir = _rulesets(tmp_path)
    res = vocab_load.load_terminology(omop, TERM_DIR, rulesets_dir=rs_dir)
    approved = sorted(r for r in list_rulesets(rs_dir) if Ruleset.load(rs_dir / r).manifest.status == "approved")
    assert len(approved) == 8  # unpinned rulesets: recompile needed; RA-JAK (T-504) is pinned to this very release
    assert sorted(res.marked) == [r for r in approved if r != "RA-JAK"]
    rel_a = vocab_load.terminology_release(omop)
    for rid in approved:  # recompiled against release A
        _pin(rs_dir / rid, rel_a)
    assert vocab_load.mark_rulesets(omop, rs_dir, rel_a) == [] and vocab_load.recompile_needed(omop) == []
    path = tmp_path / "icd10cm_fy2027.csv"
    path.write_text("code,display\n" + "\n".join(f"{c},{d}" for c, d in FY2027) + "\n", encoding="utf-8")
    res = vocab_load.load_code_list(omop, vocab_load.ICD10CM_URI, "FY2027", vocab_load.read_code_list(path),
                                    source=path.name, rulesets_dir=rs_dir)  # fmt: skip
    rel_b = vocab_load.terminology_release(omop)
    assert rel_b != rel_a and sorted(res.marked) == approved
    assert {(r["ruleset_id"], r["compiled_release"], r["marked_for"]) for r in vocab_load.recompile_needed(omop)} == {
        (rid, rel_a, rel_b) for rid in approved}  # fmt: skip
    # codes the release no longer lists are deleted, not removed: the compiler's full list follows the release
    assert omop.fetchval("SELECT invalid_reason FROM concept WHERE vocabulary_id = 'ICD10CM' AND concept_code = "
                         "'C50.911'") == "D"  # fmt: skip
    # a release that is not one the compiler reads (a refdata source, a JP master) marks nothing
    other = vocab_load.load_refdata_terms(omop, "tw_icd10_zh", [{"system": "urn:tw:nhi:icd-10-cm-2023",
                                          "code": "M10.9", "display": "痛風"}], version="2026-11")  # fmt: skip
    assert other.new and other.marked == [] and vocab_load.terminology_release(omop) == rel_b


def test_a_ruleset_compiled_against_a_is_refused_against_b_until_recompiled(
    omop: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omop import vocab_load

    monkeypatch.setenv(resolver.SOURCE_ENV, "vocab")
    rs_dir = _rulesets(tmp_path)
    vocab_load.load_terminology(omop, TERM_DIR, rulesets_dir=rs_dir)
    rel_a = vocab_load.terminology_release(omop)
    _pin(rs_dir / "GOUT-COH", rel_a)
    vocab_load.mark_rulesets(omop, rs_dir, rel_a)
    assert load_approved(rs_dir, "GOUT-COH", terminology=resolver.guard()).id == "GOUT-COH"
    with pytest.raises(RecompileNeeded, match="recompile"):  # unpinned and listed: refused
        load_approved(rs_dir, "RA-COH", terminology=resolver.guard())
    vocab_load.load_code_list(omop, vocab_load.ICD10CM_URI, "FY2027", FY2027, source="fy", rulesets_dir=rs_dir)
    rel_b = vocab_load.terminology_release(omop)
    with pytest.raises(RecompileNeeded, match=rel_a):
        load_approved(rs_dir, "GOUT-COH", terminology=resolver.guard())
    _pin(rs_dir / "GOUT-COH", rel_b)  # recompiled against B
    vocab_load.mark_rulesets(omop, rs_dir, rel_b)
    assert load_approved(rs_dir, "GOUT-COH", terminology=resolver.guard()).id == "GOUT-COH"
    # the parquet source compares the pin with the Parquet's own release (A here)
    monkeypatch.setenv(resolver.SOURCE_ENV, "parquet")
    assert resolver.current_release() == rel_a
    with pytest.raises(RecompileNeeded, match=rel_b):
        load_approved(rs_dir, "GOUT-COH", terminology=resolver.guard())
    monkeypatch.setenv(resolver.SOURCE_ENV, "vocab")
    # without the guard (retention, listings) an approved ruleset is still approved
    assert load_approved(rs_dir, "RA-COH").id == "RA-COH"


# ------------------------------------------------------------------------------------------------ same codes, new home
def test_valuesets_resolve_through_the_vocabulary_identically(omop: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Goldens identical: the compiler's tables read back from the vocabulary are the Parquet's, and every committed
    ruleset's ValueSet names map to the same codes and render the same SQL through either home."""
    from omop import vocab_load

    vocab_load.load_terminology(omop, TERM_DIR)
    parquet = vocab_load.read_parquet_tables(TERM_DIR)
    back = vocab_load.term_tables(omop)
    assert set(back) == set(parquet)
    for name, rows in parquet.items():
        assert back[name] == rows, name
    monkeypatch.setenv(resolver.SOURCE_ENV, "vocab")
    tv = resolver.terminology()
    tp = Terminology()
    assert tv.release == tp.release == vocab_load.terminology_release(omop)
    assert tv.rows == tp.rows and tv.full == tp.full and tv.synonyms == tp.synonyms and tv._by_code == tp._by_code
    for rid in list_rulesets(RULESETS):
        rs = Ruleset.load(RULESETS / rid)
        for vs_name, vs in rs.valuesets.items():
            for domain in ("condition", "medication", "observation", "procedure", "encounter", "claim", "report"):
                a, b = tp.map(domain, str(vs.get("title") or vs_name)), tv.map(domain, str(vs.get("title") or vs_name))
                assert (a.concepts, a.families, a.method) == (b.concepts, b.families, b.method), (rid, vs_name)
        sql_p = SqlGenerator(rs.id, rs.version, ValueSets(rs.id, rs.valuesets, tp)).render(rs.active())
        sql_v = SqlGenerator(rs.id, rs.version, ValueSets(rs.id, rs.valuesets, tv)).render(rs.active())
        assert sql_p == sql_v, rid
        for system, code in (c for name in rs.valuesets for c in ValueSets(rs.id, rs.valuesets).codes(name)):
            assert tp.concept(system, code) == tv.concept(system, code), (rid, system, code)


# ------------------------------------------------------------------------------------------------ JP masters, WHO
def test_jp_masters_link_who_only_codes_to_their_icd10cm_family(omop: Any) -> None:
    from adapter.licensed import ICD10_WHO
    from omop import vocab_load

    vocab_load.load_terminology(omop, TERM_DIR)
    tables = {"medis": {
        "ABC1": {"display": "痛風", "target_system": ICD10_WHO, "target_code": "M10.9"},  # also ICD-10-CM
        "ABC2": {"display": "痛風（足）", "target_system": ICD10_WHO, "target_code": "M10.97"},  # WHO-only
        "ABC3": {"display": "合成", "target_system": ICD10_WHO, "target_code": "U82.0"},  # no ICD-10-CM category
    }}  # fmt: skip
    res = vocab_load.load_licensed(omop, tables, versions={"medis": "5.12-synthetic"})
    assert [r.new for r in res] == [True]
    links = {
        (r["code"], r["relationship_id"]): r["target"]
        for r in omop.fetchdicts(
            "SELECT a.concept_code AS code, cr.relationship_id, b.concept_code AS target FROM concept_relationship cr "
            "JOIN concept a ON a.concept_id = cr.concept_id_1 JOIN concept b ON b.concept_id = cr.concept_id_2 "
            "WHERE a.vocabulary_id = 'MEDIS'"
        )
    }
    assert links == {("ABC1", "Maps to"): "M10.9", ("ABC2", "TB in CM family"): "M10"}
    assert not vocab_load.load_licensed(omop, tables)[0].new  # the same release again: nothing


# ------------------------------------------------------------------------------------------------ NHIA edition map
def test_nhia_map_gives_a_2016_record_the_2023_code_with_provenance(omop: Any) -> None:
    from omop import vocab_load

    spec = json.loads((FIX / "nhia_icd_2014_2023_synthetic.json").read_text(encoding="utf-8"))
    res = vocab_load.load_concept_map(omop, "tw_icd_2014_2023", spec["rows"], version=spec["version"])
    assert res.new
    old, new = "urn:tw:nhi:icd-10-cm-2014", "urn:tw:nhi:icd-10-cm-2023"

    def ed(code: str, day: date) -> Any:
        return vocab_load.edition_code(omop, old, code, day, target_system=new, name="tw_icd_2014_2023")

    got = ed("E78.0", date(2016, 5, 1))
    assert got == vocab_load.EditionCode(new, "E78.00", f"map:tw_icd_2014_2023@{spec['version']}:inexact:E78.0")
    assert ed("M10.9", date(2016, 5, 1)) == vocab_load.EditionCode(
        new, "M10.9", f"map:tw_icd_2014_2023@{spec['version']}:equivalent:M10.9"
    )
    assert ed("E78.0", date(2025, 3, 1)) == vocab_load.EditionCode(old, "E78.0", None)  # coded in the 2023 edition
    assert ed("K21.0", date(2016, 5, 1)) is None  # split into two 2023 codes: never a guess
    assert ed("Z22.51", date(2016, 5, 1)) is None  # a candidate (relatedto) only
    assert ed("A00.0", date(2016, 5, 1)) is None  # not in the map
    assert not vocab_load.load_concept_map(omop, "tw_icd_2014_2023", spec["rows"], version=spec["version"]).new


def test_nhia_map_rows_from_the_refdata_parser_load_and_apply(omop: Any) -> None:
    """The seam with PR #65 (D-171): rows ``refdata_tw.icd_map_rows`` yields from a file in the NHIA columns load as
    the edition map unchanged. Synthetic CSV, not the NHIA file."""
    from omop import vocab_load
    from tb_common import refdata_tw as tw

    head = ",".join(tw.ICD_COLS)
    csv = "\n".join([
        head,
        "M10.9,Gout,痛風,M10.9,Gout,痛風,有效,有效,",
        "E78.0,Pure hypercholesterolemia,高膽固醇血症,E78.00,Pure hypercholesterolemia unspecified,高膽固醇血症,有效,有效,",
        "K21.0,GERD with esophagitis,胃食道逆流,K21.00,GERD without bleeding,胃食道逆流,有效,有效,",
        "K21.0,GERD with esophagitis,胃食道逆流,K21.01,GERD with bleeding,胃食道逆流,有效,有效,",
    ]) + "\n"  # fmt: skip
    rows = list(tw.icd_map_rows(csv.encode("utf-8"), pcs=False))
    assert {r["relation"] for r in rows} == {"equivalent", "inexact", "narrower"}
    vocab_load.load_concept_map(omop, "tw_icd_2014_2023", rows, version="synthetic-parser")
    got = vocab_load.edition_code(omop, tw.ICD_CM_2014, "E78.0", date(2016, 5, 1), target_system=tw.ICD_CM_2023,
                                  name="tw_icd_2014_2023")  # fmt: skip
    assert got == vocab_load.EditionCode(
        tw.ICD_CM_2023, "E78.00", "map:tw_icd_2014_2023@synthetic-parser:inexact:E78.0"
    )
    assert vocab_load.edition_code(omop, tw.ICD_CM_2014, "K21.0", date(2016, 5, 1), target_system=tw.ICD_CM_2023,
                                   name="tw_icd_2014_2023") is None  # fmt: skip
