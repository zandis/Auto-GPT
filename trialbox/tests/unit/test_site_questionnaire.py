"""10B-19 (D-1249): the site questionnaire as a form that fills a site profile (docs/data/15-the-site-profile.md).

The questionnaire is review 12 section 9 (``docs/reviews/2026-11-root/12-ssi-data.md``, 9.1 and 9.2). Its answers,
in one answers file, become a profile folder in D-1233's format through ``python -m adapter.site_profile fill``. The
form writes; it never loads. Loading stays ``load --by``, and the folder the form writes passes the real loader.
"""

from __future__ import annotations

import copy
import csv
import io
import os
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter import site_profile as sp
from adapter import site_questionnaire as sq
from adapter.mapping.engine import Mapping
from tb_common.site_profile import SHIPPED_ROOT, VERIFIED, VERIFY, load

ROOT = Path(__file__).resolve().parents[2]
ANSWERS = ROOT / "tests" / "fixtures" / "site_questionnaire" / "synthetic-jp-ss.answers.yaml"
SHIPPED_PROFILE = SHIPPED_ROOT / "profile" / "synthetic-jp-ss"
JP_MAPPING = SHIPPED_ROOT / "jp_core" / "ssmix2_site.yaml"
LANGS = ("en", "ja", "zh-TW")
#: lab rows of the fixture, by what they are
LAB_SAME, LAB_CONVERTED, LAB_CODED = 0, 5, 6


def _answers() -> dict[str, Any]:
    doc, _ = sq.read_answers(ANSWERS.read_bytes())
    assert isinstance(doc, dict)
    return doc


def _codes(problems: list[sq.Problem]) -> list[str]:
    return [p.code for p in problems]


def _form(doc: dict[str, Any]) -> sq.Form:
    form = sq.parse(doc)
    assert isinstance(form, sq.Form), [(p.code, p.where) for p in form]
    return form


def _refused(doc: dict[str, Any]) -> list[sq.Problem]:
    got = sq.parse(doc)
    assert not isinstance(got, sq.Form), "accepted"
    return got


def _fill(tmp_path: Path, doc: dict[str, Any] | None = None) -> Path:
    out = tmp_path / "out"
    sq.write(_form(doc if doc is not None else _answers()), out)
    return out


def _set(doc: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    node = out
    for step in path[:-1]:
        node = node[step]
    if value is _DROP:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


def _lab(doc: dict[str, Any], i: int, **cells: Any) -> dict[str, Any]:
    for k, v in cells.items():
        doc = _set(doc, ("tables", "lab", "rows", i, k), v)
    return doc


_DROP = object()


# ------------------------------------------------------------------ the exit: a profile for the synthetic hospital
def test_the_form_fills_a_profile_for_the_synthetic_hospital_that_the_real_loader_loads(tmp_path: Path) -> None:
    out = _fill(tmp_path)
    p = load(out)  # the real loader, every check of D-1233
    sp.check_mapping(p, Mapping.load(JP_MAPPING))  # the lab table holds the mapping's look-up columns
    sp.check_settings(p, country="JP", standards={"jp_core": "1.1.0"})
    assert (p.id, p.site_id, p.country, p.version, p.door, p.synthetic) == (
        "synthetic-jp-ss", "jp-ss", "jp", "1.1.0", "ssmix2", True)  # fmt: skip
    shipped = load(SHIPPED_PROFILE)
    assert p.data_types == shipped.data_types and p.standards == shipped.standards
    # every code reads to the same standard code as the shipped sample tables do, and every row is still `verify`
    for name, t in shipped.tables.items():
        mine = p.tables[name]
        assert mine.used_by == t.used_by
        assert {c: r.target for c, r in mine.rows.items()} == {c: r.target for c, r in t.rows.items()}
        assert {r.state for r in mine.rows.values()} == {VERIFY}
    # every lab cell as shipped, but for the two joint counts: a quantity needs its unit, and theirs is 1 ({count})
    lab_shipped, lab_mine = shipped.tables["lab"], p.tables["lab"]
    for code, r in lab_shipped.rows.items():
        cells = {k: v for k, v in r.row.items() if k != "verified"}
        if code in ("TJC28", "SJC28"):
            assert (cells["ucum"], lab_mine.rows[code].row["ucum"]) == ("", "1")
            cells["ucum"] = "1"
        assert {k: v for k, v in lab_mine.rows[code].row.items() if k != "state"} == cells
    # D-1233's path takes it as it takes a hand-written folder: loaded by a person, recorded and audited
    ch = sp.activate(p, tmp_path / "lake", site_id="jp-ss", by="steward-q", audit_dir=tmp_path / "audit", door="ssmix2")
    assert ch is not None and (ch["new_version"], ch["direction"]) == ("1.1.0", "first")


def test_the_form_writes_and_never_loads(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    rc = sp.main(["fill", "--answers", str(ANSWERS), "--out", str(tmp_path / "out")])
    assert rc == 0
    assert sorted(p.name for p in lake.iterdir()) == []  # nothing recorded, nothing activated
    files = sorted(str(f.relative_to(tmp_path / "out")) for f in (tmp_path / "out").rglob("*") if f.is_file())
    assert files == ["codes/diagnosis.csv", "codes/drug.csv", "codes/lab.csv", "profile.yaml"]
    assert sp.main(["check", str(tmp_path / "out"), "--mapping", str(JP_MAPPING)]) == 0


# ------------------------------------------------------------------ the questionnaire mapped to the profile
def test_every_question_maps_to_a_profile_field_or_is_listed_as_filling_none() -> None:
    nums = {q.number for q in sq.QUESTIONS}
    assert nums == {f"9.1.{n}" for n in range(1, 31)} | {f"9.2.{n}" for n in range(1, 8)}
    for q in sq.QUESTIONS:
        assert q.fills or q.no_field_because, q.number
        for f in q.fills:
            assert f.split(".")[0] in sq.PROFILE_FIELDS, (q.number, f)
    filled = {f.split(".")[0] for q in sq.QUESTIONS for f in q.fills}
    # a manifest field no question fills is asked of the steward in the form's own header, and says why
    assert set(sq.PROFILE_FIELDS) - filled == set(sq.NOT_FROM_THE_QUESTIONNAIRE)


# ------------------------------------------------------------------ validation by allow-list
BAD = [
    (("profile", "id"), "Synthetic JP", "id"),
    (("profile", "site_id"), "jp ss/..", "site_id"),
    (("profile", "country"), "japan", "country"),
    (("profile", "version"), "1.1", "version"),
    (("profile", "version"), ["1"], "not_text"),
    (("profile", "version"), "", "missing"),
    (("profile", "synthetic"), "yes", "synthetic"),
    (("profile", "synthetic"), "false", "synthetic_id"),
    (("door",), "ssmix", "door"),
    (("door",), "csv", "table_door"),  # jp may have a csv door, but 病名 and YJ tables are the SS-MIX2 reader's
    (("data_types",), ["ADT-00", "ADT-99"], "data_type"),
    (("data_types",), [], "missing"),
    (("standards", "ssmix2"), "version 1.2", "std_value"),
    (("standards", "hl7"), "2.5", "std_name"),
    (("standards", "medis_byomei"), "2026-02-30", "std_value"),
    (("tables", "regimen"), {"source": {"master": "synthetic"}, "rows": []}, "table_name"),
    (("tables", "../codes/x"), {"source": {"master": "synthetic"}, "rows": []}, "table_name"),
    (("tables", "diagnosis", "source", "master"), "/etc/passwd", "master"),
    (("tables", "diagnosis", "source", "date"), "yesterday", "date"),
    (("tables", "diagnosis", "rows"), [], "rows_empty"),
    (("tables", "diagnosis", "rows", 0, "code"), "../../etc", "code_shape"),
    (("tables", "diagnosis", "rows", 0, "code"), ["Z"], "not_text"),
    (("tables", "diagnosis", "rows", 0, "code"), "zb02", "code_repeat"),
    (("tables", "diagnosis", "rows", 0, "icd10"), "A1", "target_code"),
    (("tables", "diagnosis", "rows", 0, "icd10"), "Ａ15.0", "target_code"),
    (("tables", "diagnosis", "rows", 0, "name"), "=HYPERLINK(1)", "text"),
    (("tables", "diagnosis", "rows", 0, "name"), "肺結核\u202e", "text"),
    (("tables", "diagnosis", "rows", 0, "name"), "two\nlines", "text"),
    (("tables", "diagnosis", "rows", 0, "name"), "see https://steward:@example.org/x", "text_url"),
    (("tables", "diagnosis", "rows", 0, "state"), "confirmed", "state"),
    (("tables", "diagnosis", "rows", 0, "state"), "", "state"),
    (("tables", "diagnosis", "rows", 0, "extra"), "x", "unknown_key"),
    (("tables", "drug", "rows", 0, "code"), "39430", "yj_shape"),
    (("tables", "drug", "rows", 0, "atc"), "M04AA", "target_code"),
    (("tables", "lab", "rows", 0, "loinc"), "3084-2", "target_code"),
    (("tables", "lab", "rows", 0, "score"), "TJC28", "system_one"),
    (("tables", "lab", "rows", 0, "unit"), "milligrams", "unit"),
    (("tables", "lab", "rows", 0, "unit"), _DROP, "unit_missing"),
    (("tables", "lab", "rows", 0, "factor"), "0", "factor"),
    (("tables", "lab", "rows", 0, "factor"), "1e9", "factor"),
    (("tables", "lab", "rows", LAB_CONVERTED, "factor"), "5000", "factor"),  # a plain decimal above 1000
    (("tables", "lab", "rows", 0, "factor"), "10", "factor_same"),
    (("tables", "lab", "rows", 0, "source_unit"), "g/L", "factor_wrong"),
    (("tables", "lab", "rows", LAB_CONVERTED, "factor"), "100", "factor_wrong"),
    (("tables", "lab", "rows", LAB_CONVERTED, "factor"), _DROP, "factor_needed"),
    (("tables", "lab", "rows", LAB_CODED, "unit"), "mg/dL", "unit_coded"),
    (("tables", "lab", "rows", 0, "category"), "imaging", "category"),
    (("tables", "lab", "rows", 0, "kind"), "text", "kind"),
    (("tables", "lab", "rows", 0, "answers"), [{"word": "POS", "code": "LA6576-8", "display": "Positive"}], "answers"),
    (("tables", "lab", "rows", LAB_CODED, "answers"), _DROP, "answers"),
    (("tables", "lab", "rows", LAB_CODED, "answers", 0, "code"), "LA6576", "answer_code"),
    (("tables", "lab", "rows", LAB_CODED, "answers", 0, "word"), "pos itive", "answer_word"),
    (("format",), "tb-site-questionnaire/2", "format"),
    (("hospital_name",), "x", "unknown_key"),
    (("profile",), _DROP, "missing"),
]


@pytest.mark.parametrize(("path", "value", "code"), BAD, ids=[f"{c}:{'.'.join(map(str, p))}" for p, _, c in BAD])
def test_an_answer_is_accepted_only_when_it_is_recognised(path: tuple[Any, ...], value: Any, code: str) -> None:
    got = _refused(_set(_answers(), path, value))
    assert code in _codes(got), [(p.code, p.where) for p in got]
    for p in got:
        for lang in LANGS:
            said = sq.message(p, lang)
            assert said and not said.startswith("profileform."), (lang, p.code)
            assert p.where in said  # the message names the answer it is about


def test_every_refusal_says_what_is_expected_in_three_languages() -> None:
    from console.i18n import lookup

    for code in sq.CODES:
        texts = [lookup(lang, f"profileform.err.{code}") for lang in LANGS]
        assert all(texts), code
        assert len(set(texts)) == 3, code  # three languages, not one text copied


def test_a_refusal_never_repeats_what_the_answer_said() -> None:
    # a patient's name typed into the wrong field is not shown back: the key, the line and the length only
    name = "記入見本 QX77 ZZ"  # stands for anything a person should not see repeated (synthetic marker)
    fields = [("profile", "id"), ("profile", "site_id"), ("profile", "version"), ("profile", "synthetic"),
              ("tables", "diagnosis", "rows", 0, "code"), ("tables", "diagnosis", "rows", 0, "icd10"),
              ("tables", "diagnosis", "rows", 0, "state"), ("tables", "diagnosis", "source", "date"),
              ("tables", "lab", "rows", 0, "unit"), ("tables", "lab", "rows", 0, "factor"),
              ("tables", "lab", "rows", 0, "kind"), ("tables", "lab", "rows", LAB_CODED, "answers", 0, "word"),
              ("standards", "jp_core"), ("door",)]  # fmt: skip
    doc = _answers()
    for f in fields:
        doc = _set(doc, f, name)
    doc = _set(doc, ("tables", "diagnosis", "rows", 1, "name"), name + "\n")
    doc["tables"]["drug"]["rows"][0][name] = "x"  # as a key, too
    got = _refused(doc)
    assert len(got) >= len(fields) + 2
    for p in got:
        for lang in LANGS:
            said = sq.message(p, lang)
            assert "記入見本" not in said and "QX77" not in said, said
    assert {p.values.get("length") for p in got if p.where == "profile.id"} == {str(len(name))}


# ------------------------------------------------------------------ every answer is text: no YAML number building
def _yaml_number_forms(n: int) -> set[str]:
    """The ways YAML 1.1 lets ``n`` be written so that a typing reader builds a number other than the text (or the
    same number from text that is not a plain decimal): another base, a sign, a _, base 60, an exponent, a dot."""
    forms = {f"0{n:o}", f"0o{n:o}", f"0x{n:x}", f"0X{n:X}", f"0b{n:b}", f"+{n}", f"{n}.", f"{n}e0", f"{n}E+0",
             f"{n // 60}:{n % 60:02d}", f"{n:,}".replace(",", "_"), f"0{n}", f"{n}.0e0", f"00{n}", f"{n}_"}  # fmt: skip
    if n >= 10:
        s = str(n)
        forms |= {f"{s[0]}_{s[1:]}", f"{s[:-1]}_{s[-1]}"}
    return {f for f in forms if f != str(n)}


@pytest.mark.parametrize("n", [1, 8, 10, 16, 90, 100, 1000])
def test_a_factor_is_read_as_the_text_written_and_only_a_plain_decimal_is_accepted(tmp_path: Path, n: int) -> None:
    text = ANSWERS.read_text(encoding="utf-8")
    row = "        factor: 10\n"  # the one converted row of the fixture (mg/dL to mg/L)
    assert text.count(row) == 1
    for form in [*sorted(_yaml_number_forms(n)), ".5", "-1", "inf", ".inf", "nan", "1,0", "0.", "1e1", "0x0A"]:
        got = sq.parse_text(text.replace(row, f"        factor: {form}\n"))
        assert not isinstance(got, sq.Form), f"factor {form!r} was accepted"
        assert {p.code for p in got} <= {"factor", "factor_wrong"} and got, (form, _codes(got))
        assert any(p.where.endswith(f"rows[{LAB_CONVERTED}].factor") and p.line for p in got)
    # a plain decimal is the text written, to the cell; 10 is the one this conversion accepts
    plain = sq.parse_text(text.replace(row, "        factor: 10.0\n"))
    assert isinstance(plain, sq.Form)
    assert plain.tables["lab"][LAB_CONVERTED]["factor"] == "10.0"


@pytest.mark.parametrize(
    ("line", "forms", "accepted"),
    [
        ("  synthetic: true\n", ["yes", "Yes", "on", "y", "Y", "True", "TRUE", "1", "no", "off", "False", "~", "null"],
         ["true"]),
        ('  version: "1.1.0"\n', ["1.10", "01.1.0", "1.1.0_0", "1.1.00", "1.1", "1:1.0", "0x1.1.0", "1.1.0.0"],
         ["1.1.0", "10.0.1"]),
        ('  jp_core: "1.1.0"\n', ["1.1", "1.01.0", "1.1.0e0"], ["1.1.0", "2.0.0"]),
        ("    source: {master: synthetic}\n", ["{master: synthetic, date: 2026-1-1}",
         "{master: synthetic, date: 20260101}", "{master: synthetic, date: 2026-01-01T00:00:00}",
         "{master: synthetic, date: 2026-01-01 00:00}", "{master: synthetic, date: 2026-02-30}"],
         ["{master: synthetic, date: 2026-01-01}"]),
    ],
)  # fmt: skip
def test_every_typed_answer_is_its_text_accepted_by_one_pattern(
    line: str, forms: list[str], accepted: list[str]
) -> None:
    text = ANSWERS.read_text(encoding="utf-8")
    assert line in text
    key, _, _ = line.partition(":")
    for form in forms:
        got = sq.parse_text(text.replace(line, f"{key}: {form}\n", 1))
        assert not isinstance(got, sq.Form), f"{key.strip()}: {form!r} was accepted"
    for form in accepted:
        got = sq.parse_text(text.replace(line, f"{key}: {form}\n", 1))
        assert isinstance(got, sq.Form), (form, got)
        written = sq.manifest_text(got)
        value = form.split("date: ")[-1].rstrip("}") if "date" in form else form
        assert value in written  # the text written, never a number or a date the reader built


# ------------------------------------------------------------------ units: the factor is said, checked or flagged
def test_a_factor_is_1_only_for_one_unit_and_otherwise_given_and_checked(tmp_path: Path) -> None:
    doc = _answers()
    form = _form(doc)
    lab = form.tables["lab"]
    assert (lab[LAB_SAME]["ucum"], lab[LAB_SAME]["factor"], lab[LAB_SAME]["source_unit"]) == ("mg/dL", "1", "")
    assert (lab[LAB_CONVERTED]["source_unit"], lab[LAB_CONVERTED]["ucum"], lab[LAB_CONVERTED]["factor"]) == (
        "mg/dL", "mg/L", "10")  # fmt: skip
    # g/L from mg/dL: no factor is refused; 0.01 is the product's own conversion, 100 is refused
    g_l = _lab(doc, LAB_SAME, unit="g/L", source_unit="mg/dL", factor=_DROP)
    assert "factor_needed" in _codes(_refused(g_l))
    assert _form(_lab(g_l, LAB_SAME, factor="0.01")).tables["lab"][LAB_SAME]["factor"] == "0.01"
    wrong = _refused(_lab(g_l, LAB_SAME, factor="100"))
    assert [(p.code, p.values.get("expected")) for p in wrong] == [("factor_wrong", "0.01")]
    # a spelling of the unit is the same unit: factor 1, nothing to give
    same = _form(_lab(doc, LAB_SAME, source_unit="mg/dl", factor=_DROP))
    assert same.tables["lab"][LAB_SAME]["factor"] == "1"


def test_a_conversion_the_product_does_not_know_is_stored_as_verify_and_the_summary_says_so() -> None:
    doc = _lab(_answers(), LAB_SAME, unit="mg/dL", source_unit="mmol/L", factor="1000", state="verified")
    form = _form(doc)
    assert form.tables["lab"][LAB_SAME]["state"] == VERIFY  # whatever the answer said
    for lang in LANGS:
        lines = form.summary(lang)
        from console.i18n import translate

        said = translate(lang, "profileform.sum.forced_verify", count=1, rows=f"tables.lab.rows[{LAB_SAME}]")
        assert said in [x.strip() for x in lines], lines


def test_every_default_the_form_applies_is_said_in_the_template_and_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from console.i18n import lookup

    doc = _set(_answers(), ("tables", "diagnosis", "rows", 0, "state"), _DROP)
    out_text = tmp_path / "answers.yaml"
    out_text.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert sp.main(["fill", "--answers", str(out_text), "--out", str(tmp_path / "out"), "--check-only"]) == 0
    said = capsys.readouterr().out
    assert "state verify (no state given): 1 rows (tables.diagnosis.rows[0])" in said
    assert "factor 1 (same unit, or no source unit)" in said
    assert "no source unit given" in said
    assert "factor checked against the product's conversion: 1 rows" in said
    assert "version 1.1.0, synthetic true" in said and "none of them has a default" in said
    for lang in LANGS:
        assert sp.main(["fill", "--template", "--lang", lang]) == 0
        tpl = capsys.readouterr().out
        assert str(lookup(lang, "profileform.tpl.defaults")).splitlines()[0] in tpl
        assert 'version: "1.0.0"' not in tpl and "synthetic: false" not in tpl  # no answer filled for the steward


# ------------------------------------------------------------------ what goes together
APART = [
    ("tw with the SS-MIX2 door and Japanese tables", {("profile", "country"): "tw"}, {"door", "standards.ssmix2"}),
    ("jp with the CGRD door", {("door",): "cgrd_sql"}, {"door"}),
    ("jp with tw_core", {("standards", "tw_core"): "1.0.0"}, {"standards.tw_core"}),
    ("jp with ICD-10-CM", {("standards", "icd10cm"): "2023"}, {"standards.icd10cm"}),
    ("a lab table from the MEDIS disease master", {("tables", "lab", "source", "master"): "medis_byomei"},
     {"tables.lab.source.master"}),
    ("a drug table from JLAC10", {("tables", "drug", "source", "master"): "jlac10"}, {"tables.drug.source.master"}),
    ("the SS-MIX2 version with a csv door", {("door",): "csv", ("tables",): {"lab": "keep"}}, {"standards.ssmix2"}),
]  # fmt: skip


@pytest.mark.parametrize(("why", "changes", "where"), APART, ids=[a[0] for a in APART])
def test_answers_that_do_not_go_together_are_refused_with_both_named(
    why: str, changes: dict[tuple[str, ...], Any], where: set[str]
) -> None:
    doc = _answers()
    for path, value in changes.items():
        if value == {"lab": "keep"}:
            value = {"lab": doc["tables"]["lab"]}
        doc = _set(doc, path, value)
    got = _refused(doc)
    apart = {p.where: p for p in got if p.code == "apart"}
    assert where <= set(apart), (why, [(p.code, p.where) for p in got])
    for p in apart.values():
        for lang in LANGS:
            said = sq.message(p, lang)
            assert p.values["name"] in said and p.values["other"] in said and p.values["other_value"] in said


def test_every_shipped_profile_goes_together() -> None:
    for folder in sorted((SHIPPED_ROOT / "profile").iterdir()):
        p = load(folder)
        row = sq.GOES_WITH[p.country]
        assert p.door in row["doors"], folder
        assert set(p.standards) <= set(row["standards"]), folder
        assert all(sq.STANDARD_DOOR.get(s, p.door) == p.door for s in p.standards), folder


@pytest.mark.parametrize("country", ["us", "other"])
def test_a_country_the_form_cannot_make_a_profile_for_is_told_why(country: str) -> None:
    got = _refused(_set(_set(_answers(), ("profile", "country"), country), ("door",), "csv"))
    p = next(p for p in got if p.code == "country_none")
    assert p.values["name"] == country
    for lang in LANGS:
        said = sq.message(p, lang)
        assert country in said and "FHIR" in said and "jp, tw" in said


def test_a_synthetic_master_is_refused_in_a_hospitals_profile() -> None:
    doc = _set(_answers(), ("profile", "id"), "jp-ss-hospital")
    doc = _set(doc, ("profile", "synthetic"), "false")
    assert "master_synthetic" in _codes(_refused(doc))


# ------------------------------------------------------------------ every refusal at once, with its line
def test_every_refusal_is_reported_at_once_with_its_line_even_inside_coded_answers() -> None:
    text = ANSWERS.read_text(encoding="utf-8")
    first = "answers: [{word: POS, code: LA6576-8, display: Positive}, {word: NEG, code: LA6577-6, display: Negative}]"
    assert first in text
    bad = 'answers: [{word: pos, code: LA6576, display: Positive}, {word: NEG, code: LA6577-6, display: "a|b"}]'
    text = text.replace(first, bad, 1).replace("  site_id: jp-ss\n", "  site_id: jp ss\n")
    got = sq.parse_text(text)
    assert not isinstance(got, sq.Form)
    where = {p.where: p for p in got}
    prefix = f"tables.lab.rows[{LAB_CODED}].answers"
    assert {f"{prefix}[0].word", f"{prefix}[0].code", f"{prefix}[1].display", "profile.site_id"} <= set(where)
    lines = text.splitlines()
    assert "site_id: jp ss" in lines[where["profile.site_id"].line - 1]
    assert bad in lines[where[f"{prefix}[0].code"].line - 1]
    assert "(line " in sq.message(where["profile.site_id"], "en")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("a: &x [1, 2]\nb: *x\n", "alias"),  # an alias (a document that grows when read)
        ("format: tb-site-questionnaire/1\nformat: tb-site-questionnaire/1\n", "doubled_key"),
        ("- a list\n", "unreadable"),
        ("format: [unclosed\n", "unreadable"),
    ],
)
def test_an_answers_file_that_is_not_one_plain_mapping_is_refused(text: str, code: str) -> None:
    got = sq.parse_text(text)
    assert not isinstance(got, sq.Form) and _codes(got) == [code]
    assert got[0].line > 0


def test_the_answers_file_is_parsed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counted(name: str) -> Any:
        real = getattr(yaml, name)

        def call(*a: Any, **k: Any) -> Any:
            calls.append(name)
            return real(*a, **k)

        return call

    for name in ("compose", "parse", "load", "safe_load", "full_load"):
        monkeypatch.setattr(yaml, name, counted(name))
    assert isinstance(sq.parse_text(ANSWERS.read_bytes()), sq.Form)
    assert calls == ["compose"]


# ------------------------------------------------------------------ no free text unescaped, no path from an answer
def test_text_with_commas_and_quotes_reaches_the_table_quoted_and_reads_back_as_written(tmp_path: Path) -> None:
    name = '関節リウマチ, "血清反応陽性"'
    out = _fill(tmp_path, _set(_answers(), ("tables", "diagnosis", "rows", 0, "name"), name))
    raw = (out / "codes" / "diagnosis.csv").read_text(encoding="utf-8")
    first = next(iter(csv.DictReader(io.StringIO(raw))))
    assert first["name"] == name
    assert load(out).tables["diagnosis"].rows["ZB01"].row["name"] == name


def test_no_answer_becomes_a_path_a_file_name_or_free_text_in_the_manifest(tmp_path: Path) -> None:
    out = _fill(tmp_path)
    manifest = yaml.safe_load((out / "profile.yaml").read_text(encoding="utf-8"))
    assert {t["file"] for t in manifest["tables"].values()} == {f"codes/{n}.csv" for n in ("diagnosis", "drug", "lab")}
    # a table's source is composed of the form's own words, a master from the list and a checked date
    assert {t["source"] for t in manifest["tables"].values()} == {sq.SOURCE_WORDS["synthetic"]}
    dated = _set(_answers(), ("profile", "id"), "jp-ss-site")
    dated = _set(dated, ("profile", "synthetic"), "false")
    for name in ("diagnosis", "drug", "lab"):
        dated = _set(dated, ("tables", name, "source"), {"master": "hospital", "date": "2026-10-01"})
    sq.write(_form(dated), tmp_path / "site")
    sources = {t.source for t in load(tmp_path / "site").tables.values()}
    assert sources == {f"{sq.SOURCE_WORDS['hospital']} 2026-10-01"}


# ------------------------------------------------------------------ an unverified mapping stays unverified
def test_a_row_without_a_state_is_stored_as_verify_and_only_verified_says_verified(tmp_path: Path) -> None:
    doc = _set(_answers(), ("tables", "diagnosis", "rows", 0, "state"), _DROP)
    doc = _set(doc, ("tables", "diagnosis", "rows", 1, "state"), "verified")
    p = load(_fill(tmp_path, doc))
    rows = p.tables["diagnosis"].rows
    assert rows["ZB01"].state == VERIFY and rows["ZB02"].state == VERIFIED
    raw = (tmp_path / "out" / "codes" / "diagnosis.csv").read_text(encoding="utf-8")
    assert "ZB01,肺結核,A15.0,verify" in raw


# ------------------------------------------------------------------ the command and the disk
def _run(*args: str) -> int:
    return sp.main(["fill", "--answers", str(ANSWERS), *args])


def test_the_command_refuses_an_existing_folder_and_the_live_mapping_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "there").mkdir()
    assert _run("--out", str(tmp_path / "there")) == 2
    assert _run("--out", str(tmp_path / "there"), "--check-only") == 2  # said before anything is written
    assert "profileform" not in capsys.readouterr().err
    live = tmp_path / "site-mapping"
    live.mkdir()
    monkeypatch.setenv("TB_MAPPING_DIR", str(live))
    assert _run("--out", str(live / "profile"), "--lang", "ja") == 2
    err = capsys.readouterr().err
    assert str(live / "profile") in err and "TB_MAPPING_DIR" in err
    assert not (live / "profile").exists()
    # the known live folders are refused whatever this shell's TB_MAPPING_DIR says
    monkeypatch.delenv("TB_MAPPING_DIR")
    from adapter.mapping.site import SITE_MOUNT

    known = sp.live_folders()
    assert SITE_MOUNT in known and ROOT / "deploy" / "site" / "mapping" in known
    for folder in (SHIPPED_ROOT / "profile", ROOT / "deploy" / "site" / "mapping"):
        assert _run("--out", str(folder / "x-form-test")) == 2
        assert not (folder / "x-form-test").exists()


def test_check_only_prints_what_is_refused_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "answers.yaml"
    bad.write_text(ANSWERS.read_text(encoding="utf-8").replace("country: jp", "country: japan"), "utf-8")
    out = tmp_path / "out"
    assert sp.main(["fill", "--answers", str(bad), "--out", str(out), "--check-only", "--lang", "zh-TW"]) == 2
    err = capsys.readouterr().err
    assert "profile.country" in err and "jp" in err and "japan" not in err
    assert not out.exists()
    assert _run("--out", str(out), "--check-only") == 0
    assert not out.exists()
    assert "68" in capsys.readouterr().out  # the rows it would write, counted


def test_the_folder_is_readable_by_the_box_and_missing_parents_are_said(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = os.umask(0o077)
    try:
        assert _run("--out", str(tmp_path / "new" / "deeper" / "out")) == 0
    finally:
        os.umask(old)
    out = tmp_path / "new" / "deeper" / "out"
    assert stat.S_IMODE(out.stat().st_mode) == sq.DIR_MODE
    assert stat.S_IMODE((out / "codes").stat().st_mode) == sq.DIR_MODE
    assert {stat.S_IMODE(f.stat().st_mode) for f in out.rglob("*") if f.is_file()} == {sq.FILE_MODE}
    printed = capsys.readouterr().out
    assert f"was made: {out.parent}" in printed and "0755" in printed
    assert [p.name for p in out.parent.iterdir()] == ["out"]  # nothing of the build left beside it


def test_the_disk_refusing_is_one_line_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # the folder above is a file
    (tmp_path / "file").write_text("x", encoding="utf-8")
    assert _run("--out", str(tmp_path / "file" / "out")) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and len(err.strip().splitlines()) == 2
    assert sq.message(sq.Problem("out_parent", str(tmp_path / "file" / "out")), "en") in err
    # the disk refuses half-way: one line, the OS's reason, nothing left
    calls = {"n": 0}
    real = sq._new_file

    def full(path: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(28, "No space left on device")
        real(path, data)

    monkeypatch.setattr(sq, "_new_file", full)
    assert _run("--out", str(tmp_path / "out")) == 2
    err = capsys.readouterr().err
    assert "No space left on device" in err and "Traceback" not in err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["file"]


def test_a_folder_that_appears_meanwhile_is_never_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    real_load = load

    def appear(folder: Path) -> Any:
        out.mkdir()  # another hand makes the folder while the form checks its build
        (out / "theirs.txt").write_text("kept", encoding="utf-8")
        return real_load(folder)

    monkeypatch.setattr(sq, "load", appear)
    assert _run("--out", str(out)) == 2
    assert sorted(p.name for p in out.iterdir()) == ["theirs.txt"]
    assert (out / "theirs.txt").read_text(encoding="utf-8") == "kept"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"]


def test_ctrl_c_is_one_line_exit_130_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = {"n": 0}
    real = sq._new_file

    def stop(path: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        real(path, data)

    monkeypatch.setattr(sq, "_new_file", stop)
    assert _run("--out", str(tmp_path / "out")) == 130
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1 and "Traceback" not in err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("lang", LANGS)
def test_the_template_is_in_three_languages_and_an_empty_one_is_refused_answer_by_answer(
    lang: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sp.main(["fill", "--template", "--lang", lang]) == 0
    text = capsys.readouterr().out
    assert text.startswith("#")
    from console.i18n import lookup

    assert str(lookup(lang, "profileform.tpl.head")).splitlines()[0] in text
    got = sq.parse_text(text)
    assert not isinstance(got, sq.Form)
    assert {"profile.id", "profile.version", "profile.synthetic", "door", "data_types"} <= {p.where for p in got}


def test_a_folder_the_loader_refuses_is_never_put_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.site_profile import ProfileError

    def refuse(folder: Path) -> None:
        raise ProfileError("profile.yaml", "refused for the test")

    monkeypatch.setattr(sq, "load", refuse)
    with pytest.raises(ProfileError):
        sq.write(_form(_answers()), tmp_path / "out")
    assert sorted(tmp_path.iterdir()) == []  # neither the folder nor half of one beside it
    assert _run("--out", str(tmp_path / "out")) == 2
    assert not (tmp_path / "out").exists()
