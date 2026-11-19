"""10B-19 (D-1249): the site questionnaire as a form that fills a site profile (docs/data/15-the-site-profile.md).

The questionnaire is review 12 section 9 (``docs/reviews/2026-11-root/12-ssi-data.md``, 9.1 and 9.2). Its answers,
in one answers file, become a profile folder in D-1233's format through ``python -m adapter.site_profile fill``. The
form writes; it never loads. Loading stays ``load --by``, and the folder the form writes passes the real loader.
"""

from __future__ import annotations

import copy
import csv
import io
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


def _answers() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(ANSWERS.read_text(encoding="utf-8"))
    return doc


def _codes(problems: list[sq.Problem]) -> list[str]:
    return [p.code for p in problems]


def _fill(tmp_path: Path, doc: dict[str, Any] | None = None) -> Path:
    out = tmp_path / "out"
    form = sq.parse(doc if doc is not None else _answers())
    assert isinstance(form, sq.Form), [(p.code, p.where) for p in form]
    sq.write(form, out)
    return out


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
    lab_shipped, lab_mine = shipped.tables["lab"], p.tables["lab"]
    for code, r in lab_shipped.rows.items():
        cells = {k: v for k, v in r.row.items() if k != "verified"}
        assert {k: v for k, v in lab_mine.rows[code].row.items() if k != "state"} == cells
    # D-1233's path takes it as it takes a hand-written folder: loaded by a person, recorded and audited
    ch = sp.activate(p, tmp_path / "lake", site_id="jp-ss", by="steward-q", audit_dir=tmp_path / "audit", door="ssmix2")
    assert ch is not None and ch["version"] == "1.1.0"


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


_DROP = object()
BAD = [
    (("profile", "id"), "Synthetic JP", "id"),
    (("profile", "site_id"), "jp ss/..", "site_id"),
    (("profile", "country"), "japan", "country"),
    (("profile", "version"), "1.1", "version"),
    (("profile", "version"), 1.1, "not_text"),
    (("profile", "synthetic"), "yes", "synthetic"),
    (("profile", "synthetic"), False, "synthetic_id"),
    (("door",), "ssmix", "door"),
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
    (("tables", "diagnosis", "rows", 0, "code"), 20056456, "not_text"),
    (("tables", "diagnosis", "rows", 0, "code"), "zb02", "code_repeat"),
    (("tables", "diagnosis", "rows", 0, "icd10"), "A1", "target_code"),
    (("tables", "diagnosis", "rows", 0, "icd10"), "Ａ15.0", "target_code"),
    (("tables", "diagnosis", "rows", 0, "name"), "=HYPERLINK(1)", "text"),
    (("tables", "diagnosis", "rows", 0, "name"), "肺結核‮", "text"),
    (("tables", "diagnosis", "rows", 0, "name"), "two\nlines", "text"),
    (("tables", "diagnosis", "rows", 0, "state"), "confirmed", "state"),
    (("tables", "diagnosis", "rows", 0, "extra"), "x", "unknown_key"),
    (("tables", "drug", "rows", 0, "code"), "39430", "yj_shape"),
    (("tables", "drug", "rows", 0, "atc"), "M04AA", "target_code"),
    (("tables", "lab", "rows", 0, "loinc"), "3084-2", "target_code"),
    (("tables", "lab", "rows", 0, "score"), "TJC28", "system_one"),
    (("tables", "lab", "rows", 0, "unit"), "milligrams", "unit"),
    (("tables", "lab", "rows", 0, "factor"), 0, "factor"),
    (("tables", "lab", "rows", 0, "factor"), "1e9", "factor"),
    (("tables", "lab", "rows", 0, "category"), "imaging", "category"),
    (("tables", "lab", "rows", 0, "kind"), "text", "kind"),
    (("tables", "lab", "rows", 0, "answers"), [{"word": "POS", "code": "LA6576-8", "display": "Positive"}], "answers"),
    (("tables", "lab", "rows", 6, "answers"), _DROP, "answers"),
    (("tables", "lab", "rows", 6, "answers", 0, "code"), "LA6576-9", "answer_code"),
    (("tables", "lab", "rows", 6, "answers", 0, "word"), "pos itive", "answer_word"),
    (("format",), "tb-site-questionnaire/2", "format"),
    (("hospital_name",), "x", "unknown_key"),
    (("profile",), _DROP, "missing"),
]


@pytest.mark.parametrize(("path", "value", "code"), BAD, ids=[f"{c}:{'.'.join(map(str, p))}" for p, _, c in BAD])
def test_an_answer_is_accepted_only_when_it_is_recognised(path: tuple[Any, ...], value: Any, code: str) -> None:
    got = sq.parse(_set(_answers(), path, value))
    assert not isinstance(got, sq.Form), f"{path} = {value!r} was accepted"
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
        assert all("{where}" in t for t in texts), code


def test_the_survey_rows_and_a_lab_table_need_a_country_the_form_knows() -> None:
    doc = _set(_answers(), ("profile", "country"), "us")
    got = sq.parse(doc)
    assert not isinstance(got, sq.Form) and "lab_country" in _codes(got)
    got = sq.parse(_set(_answers(), ("door",), "csv"))  # the SS-MIX2 reader's tables need the SS-MIX2 door
    assert not isinstance(got, sq.Form) and "table_door" in _codes(got)


def test_a_synthetic_master_is_refused_in_a_hospitals_profile() -> None:
    doc = _set(_answers(), ("profile", "id"), "jp-ss-hospital")
    doc = _set(doc, ("profile", "synthetic"), False)
    got = sq.parse(doc)
    assert not isinstance(got, sq.Form) and "master_synthetic" in _codes(got)


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
    dated = _set(dated, ("profile", "synthetic"), False)
    for name in ("diagnosis", "drug", "lab"):
        dated = _set(dated, ("tables", name, "source"), {"master": "hospital", "date": "2026-10-01"})
    form = sq.parse(dated)
    assert isinstance(form, sq.Form)
    sq.write(form, tmp_path / "site")
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


# ------------------------------------------------------------------ the answers file itself
@pytest.mark.parametrize(
    "text",
    [
        "a: &x [1, 2]\nb: *x\n",  # an alias (a document that grows when read)
        "format: tb-site-questionnaire/1\nformat: tb-site-questionnaire/1\n",  # a key twice
        "- a list\n",
        "format: [unclosed\n",
    ],
)
def test_an_answers_file_that_is_not_one_plain_mapping_is_refused(text: str) -> None:
    got = sq.parse_text(text)
    assert not isinstance(got, sq.Form) and _codes(got) == ["unreadable"]


# ------------------------------------------------------------------ the command
def test_the_command_refuses_an_existing_folder_and_the_live_mapping_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "there").mkdir()
    assert sp.main(["fill", "--answers", str(ANSWERS), "--out", str(tmp_path / "there")]) == 2
    assert "profileform" not in capsys.readouterr().err
    live = tmp_path / "site-mapping"
    live.mkdir()
    monkeypatch.setenv("TB_MAPPING_DIR", str(live))
    assert sp.main(["fill", "--answers", str(ANSWERS), "--out", str(live / "profile"), "--lang", "ja"]) == 2
    err = capsys.readouterr().err
    assert str(live / "profile") in err and "施設プロファイル" in err
    assert not (live / "profile").exists()
    assert sp.main(["fill", "--answers", str(ANSWERS), "--out", str(SHIPPED_ROOT / "profile" / "x")]) == 2
    assert not (SHIPPED_ROOT / "profile" / "x").exists()


def test_check_only_prints_what_is_refused_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "answers.yaml"
    bad.write_text(yaml.safe_dump(_set(_answers(), ("profile", "country"), "japan"), allow_unicode=True), "utf-8")
    out = tmp_path / "out"
    assert sp.main(["fill", "--answers", str(bad), "--out", str(out), "--check-only", "--lang", "zh-TW"]) == 2
    err = capsys.readouterr().err
    assert "profile.country" in err and "jp" in err
    assert not out.exists()
    assert sp.main(["fill", "--answers", str(ANSWERS), "--out", str(out), "--check-only"]) == 0
    assert not out.exists()
    assert "68" in capsys.readouterr().out  # the rows it would write, counted


@pytest.mark.parametrize("lang", LANGS)
def test_the_template_is_in_three_languages_and_an_empty_one_is_refused_answer_by_answer(
    lang: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sp.main(["fill", "--template", "--lang", lang]) == 0
    text = capsys.readouterr().out
    assert text.startswith("#")
    from console.i18n import lookup

    assert str(lookup(lang, "profileform.tpl.head")).splitlines()[0] in text
    got = sq.parse_text(text)
    assert not isinstance(got, sq.Form)
    assert {"profile.id", "door", "data_types"} <= {p.where for p in got}
