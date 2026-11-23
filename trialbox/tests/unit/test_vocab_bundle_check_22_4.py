"""Card 22-4 (root review 22): the build-time check that fails when a row of a must-not-ship vocabulary (licence
class c in ``docs/licences/register.csv``) reaches an artefact going into a bundle, or when an artefact cannot be
checked.

Every artefact is a tiny synthetic file written here; concept names are invented and the codes of must-not-ship
vocabularies are impossible ones (``NOT-A-CODE-*``).
"""

from __future__ import annotations

import gzip
import io
import json
import re
import sqlite3
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tools import licence_register as lr
from tools import vocab_bundle_check as vbc

ROOT = Path(__file__).resolve().parents[2]
CONCEPT_HEADER = "concept_id,concept_name,domain_id,vocabulary_id,concept_class_id,standard_concept,concept_code\n"
CLEAN_ROW = "1545958,Invented ingredient one,Drug,RxNorm,Ingredient,S,NOT-A-CODE-0\n"


def _write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _problems(*paths: Path, **kw: Any) -> list[str]:
    return vbc.check(paths, **kw).problems


# ------------------------------------------------------------------------------------------------ the rules
def test_the_forbidden_names_are_the_registers_class_c_with_their_aliases() -> None:
    r = vbc.rules()
    from tb_common.vocabfold import fold

    def name(n: str) -> tuple[str, str] | None:
        return r.names.get(fold(n))

    assert name("SNOMED") == ("SNOMED", "snomed-ct") and name("snomed ct") == ("SNOMED", "snomed-ct")
    assert name("SNOMEDCT_US") == ("SNOMED", "snomed-ct") and name("urn:oid:2.16.840.1.113883.6.96") == (
        "SNOMED",
        "snomed-ct",
    )
    assert name("CPT4") == ("CPT4", "athena-licensed") and name("ICD10") == ("ICD10", "icd10-who")
    assert name("http://snomed.info/sct")[0] == "SNOMED" and "http://snomed.info/sct" in r.needles  # type: ignore[index]
    for open_ in ("RxNorm", "LOINC", "UCUM", "ATC", "http://www.whocc.no/atc", "http://loinc.org", "Gender"):
        assert name(open_) is None, open_


# ------------------------------------------------------------------------------------------------ tables
def test_a_clean_table_passes(tmp_path: Path) -> None:
    assert _problems(_write(tmp_path / "b/rxnorm_candidates.csv", CONCEPT_HEADER + CLEAN_ROW)) == []


def test_a_row_of_a_forbidden_vocabulary_fails_naming_file_and_vocabulary(tmp_path: Path) -> None:
    dirty = _write(tmp_path / "b/open_subset.csv", CONCEPT_HEADER + CLEAN_ROW +
                   "4000001,Invented disorder alpha,Condition,SNOMED,Clinical Finding,S,NOT-A-CODE-1\n")  # fmt: skip
    assert _problems(tmp_path / "b") == [
        f"{dirty}: 1 row(s) of vocabulary 'SNOMED', licence class c, must not ship (register row snomed-ct)"
    ]


def test_labels_are_folded_and_aliases_count(tmp_path: Path) -> None:
    f = _write(tmp_path / "b/c.tsv", "code\tvocab\tcodeSystem\n"
               "NOT-A-CODE-1\t snomed ct \t\nNOT-A-CODE-2\t\tSNOMEDCT_US\nNOT-A-CODE-3\tcpt-4\t\n")  # fmt: skip
    assert _problems(f) == [
        f"{f}: 1 row(s) of vocabulary 'CPT4', licence class c, must not ship (register row athena-licensed)",
        f"{f}: 2 row(s) of vocabulary 'SNOMED', licence class c, must not ship (register row snomed-ct)",
    ]


def test_a_derived_mapping_whose_source_is_forbidden_fails(tmp_path: Path) -> None:
    m = tmp_path / "maps/regimen_to_rxnorm.tsv.gz"
    m.parent.mkdir(parents=True)
    with gzip.open(m, "wt", encoding="utf-8") as fh:  # the source_to_concept_map shape, tab-separated
        fh.write("source_code\tsource_vocabulary_id\ttarget_concept_id\ttarget_vocabulary_id\n"
                 "NOT-A-CODE-1\tHemOnc\t1545958\tRxNorm\nNOT-A-CODE-2\tHemOnc\t1503297\tRxNorm\n"
                 "X-1\tRxNorm\t1545958\tRxNorm\n")  # fmt: skip
    assert _problems(m) == [
        f"{m.with_suffix('')}: 2 row(s) of vocabulary 'HemOnc', licence class c, must not ship "
        "(register row athena-licensed)"
    ]


def test_a_parquet_table_is_read_by_its_vocabulary_and_system_columns(tmp_path: Path) -> None:
    f = tmp_path / "t/candidates.parquet"
    f.parent.mkdir(parents=True)
    pq.write_table(pa.table({"code": ["A", "B", "C"], "vocabulary_id": ["RxNorm", "CPT4", "RxNorm"],
                             "name": ["Invented a", "Invented b", "Invented c"]}), f)  # fmt: skip
    assert _problems(f) == [
        f"{f}: 1 row(s) of vocabulary 'CPT4', licence class c, must not ship (register row athena-licensed)"
    ]
    clean = tmp_path / "t/clean.parquet"
    pq.write_table(pa.table({"system": ["http://loinc.org"], "code": ["2160-0"]}), clean)
    assert _problems(clean) == []


def test_a_table_with_no_vocabulary_column_cannot_be_checked_in_a_bundle_input(tmp_path: Path) -> None:
    f = _write(tmp_path / "b/codes.csv", "code,display\nNOT-A-CODE-1,Invented\n")
    assert _problems(f) == [f"{f}: cannot be checked: a table with no vocabulary or system column"]


# ------------------------------------------------------------------------------------------------ JSON and text
def test_a_value_set_naming_a_forbidden_system_fails(tmp_path: Path) -> None:
    vs = _write(tmp_path / "r/valuesets/VS_INVENTED.json", json.dumps({
        "resourceType": "ValueSet", "compose": {"include": [
            {"system": "http://www.whocc.no/atc", "concept": [{"code": "Z99ZZ99"}]},
            {"system": "http://snomed.info/sct", "concept": [{"code": "NOT-A-CODE-1"}]}]}}))  # fmt: skip
    assert _problems(tmp_path / "r") == [
        f"{vs}: 1 row(s) of vocabulary 'SNOMED', licence class c, must not ship (register row snomed-ct)",
    ]


def test_who_icd10_codes_as_identifiers_pass_as_the_register_ships_them(tmp_path: Path) -> None:
    """Register row icd10-who-cm-bridge (own-work) ships WHO ICD-10 codes; only the Athena ICD10 vocabulary (codes
    with WHO's titles) is class c. The refdata pack's bridge map and the rule sets' WHO-only path (D-130) pass."""
    bridge = _write(tmp_path / "r/map.jsonl", json.dumps({
        "source_system": "http://hl7.org/fhir/sid/icd-10", "source_code": "NOT-A-CODE-1", "source_display": "",
        "target_system": "http://hl7.org/fhir/sid/icd-10-cm", "target_code": "NOT-A-CODE-1"}) + "\n")  # fmt: skip
    cm = _write(tmp_path / "r/CM.json", json.dumps({"resourceType": "ConceptMap", "group": [
        {"source": "http://hl7.org/fhir/sid/icd-10", "target": "http://hl7.org/fhir/sid/icd-10-cm"}]}))  # fmt: skip
    assert _problems(bridge, cm) == []
    athena = _write(
        tmp_path / "r/athena_rows.csv", CONCEPT_HEADER + "4000009,Invented,Condition,ICD10,ICD10 code,,N-9\n"
    )
    assert _problems(athena) == [
        f"{athena}: 1 row(s) of vocabulary 'ICD10', licence class c, must not ship (register row icd10-who)"
    ]
    assert any("icd10-who-cm-bridge" in r.id and r.status == "own-work" for r in lr.load())


def test_text_is_searched_for_whole_uris_and_oids(tmp_path: Path) -> None:
    sql = _write(tmp_path / "r/q.sql", "SELECT 1 WHERE system = 'urn:oid:2.16.840.1.113883.6.12' -- invented\n"
                 "AND other = 'http://hl7.org/fhir/sid/icd-10-cm';\n")  # fmt: skip
    assert _problems(sql) == [
        f"{sql}: 1 row(s) of vocabulary 'CPT4', licence class c, must not ship (register row athena-licensed)"
    ]
    assert _problems(_write(tmp_path / "r/ok.cql", "Cd.system.value = 'http://hl7.org/fhir/sid/icd-10-cm'\n")) == []


def test_bad_json_and_a_bad_ndjson_line_are_problems(tmp_path: Path) -> None:
    j = _write(tmp_path / "b/x.json", "{not json")
    n = _write(tmp_path / "b/y.ndjson", '{"system": "http://loinc.org"}\n{oops\n')
    got = _problems(j, n)
    assert len(got) == 2 and got[0].startswith(f"{j}: JSON does not parse") and got[1].startswith(f"{n}: line 2 ")


# ------------------------------------------------------------------------------------------------ containers
def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)
    return buf.getvalue()


def _tgz(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for k, v in entries.items():
            ti = tarfile.TarInfo(k)
            ti.size = len(v)
            tf.addfile(ti, io.BytesIO(v))
    return buf.getvalue()


def test_nested_containers_are_opened(tmp_path: Path) -> None:
    inner = _tgz({"pack/terms.jsonl.gz": gzip.compress(b'{"system": "SNOMED", "code": "NOT-A-CODE-1"}\n')})
    z = _write(tmp_path / "dist/RS-1.0.0.zip", _zip({"manifest.json": b"{}", "data/pack.tar.gz": inner}))
    assert _problems(z) == [
        f"{z}!data/pack.tar.gz!pack/terms.jsonl: 1 row(s) of vocabulary 'SNOMED', licence class c, must not ship "
        "(register row snomed-ct)"
    ]


def test_what_cannot_be_read_fails(tmp_path: Path) -> None:
    db = tmp_path / "b/codes.sqlite"
    db.parent.mkdir(parents=True)
    sqlite3.connect(db).close()
    image = _write(tmp_path / "b/image.tar", b"")
    with tarfile.open(image, "w") as tf:
        for name in ("manifest.json", "repositories", "abc/layer.tar"):
            ti = tarfile.TarInfo(name)
            tf.addfile(ti, io.BytesIO(b""))
    blob = _write(tmp_path / "b/thing.dat", bytes(range(256)) * 4)
    xz = _write(tmp_path / "b/old.csv.xz", b"\xfd7zXZ\x00")
    got = _problems(db, image, blob, xz)
    assert [g.split(": cannot be checked: ")[0] for g in got] == [str(db), str(image), str(blob), str(xz)]
    assert "container image tar" in got[1]


def test_a_missing_path_or_nothing_to_check_is_a_problem(tmp_path: Path) -> None:
    assert _problems(tmp_path / "absent") == [f"{tmp_path / 'absent'}: no such path"]
    (tmp_path / "empty").mkdir()
    assert _problems(tmp_path / "empty") == [f"{tmp_path / 'empty'}: no artefact to check"]


def test_a_models_folder_lists_weights_and_reads_the_rest(tmp_path: Path) -> None:
    # H-90 (the integrator's ruling): a folder a measured record covers (embedder/) is checked by its recorded hashes
    # (tests/unit/test_vocab_bundle_measured_h90.py); a folder no record covers is read as before
    m = tmp_path / "models/invented-model"
    _write(m / "config.json", '{"model_type": "invented"}')
    _write(m / "model.safetensors", b"\x00not a model")
    _write(m / "README.md", "an invented embedder\n")
    rep = vbc.check(models=[tmp_path / "models"])
    assert rep.problems == [] and any("model.safetensors: not terminology" in n for n in rep.notes)
    _write(m / "vocab_notes.md", "concepts from http://snomed.info/sct\n")
    assert len(vbc.check(models=[tmp_path / "models"]).problems) == 1


# ------------------------------------------------------------------------------------------------ exceptions
def test_a_reviewed_exception_row_turns_its_files_into_warnings_only(tmp_path: Path) -> None:
    reg = tmp_path / "docs/licences/register.csv"
    reg.parent.mkdir(parents=True)
    text = (ROOT / "docs/licences/register.csv").read_text(encoding="utf-8")
    row = {c: "x" for c in lr.COLUMNS}
    row.update(id="pending-file", kind=lr.EXCEPTION_KIND, status=lr.PENDING, checked="2026-11-18", text_sha256="",
               athena="", athena_never="", paths="data/excepted.csv")  # fmt: skip
    row["class"] = row["excepts"] = ""
    reg.write_text(text + ",".join(row[c] for c in lr.COLUMNS) + "\n", encoding="utf-8")
    bad = "code,vocabulary_id\nNOT-A-CODE-1,SNOMED\n"
    excepted, other = _write(tmp_path / "data/excepted.csv", bad), _write(tmp_path / "data/other.csv", bad)
    rep = vbc.check([excepted, other], register=reg, root=tmp_path)
    assert [p.split(":")[0] for p in rep.problems] == [str(other)]
    assert len(rep.warnings) == 1 and rep.warnings[0].startswith(f"WARNING {excepted}: 1 row(s) of vocabulary 'SNOMED'")
    assert "register row pending-file (owner decision pending)" in rep.warnings[0]


def _approved(tmp_path: Path, excepts: str, paths: str) -> Path:
    reg = tmp_path / "docs/licences/register.csv"
    reg.parent.mkdir(parents=True, exist_ok=True)
    text = (ROOT / "docs/licences/register.csv").read_text(encoding="utf-8")
    text = "".join(ln for ln in text.splitlines(keepends=True) if not ln.startswith("catalogue-"))
    row = {c: "x" for c in lr.COLUMNS}
    row.update(id="approved-file", kind=lr.EXCEPTION_KIND, status=lr.APPROVED, checked="2026-11-19", text_sha256="",
               athena="", athena_never="", paths=paths, excepts=excepts)  # fmt: skip
    row["class"] = ""
    reg.write_text(text + ",".join(row[c] for c in lr.COLUMNS) + "\n", encoding="utf-8")
    return reg


def test_an_owner_approved_exception_lets_through_the_ids_of_its_vocabularies_only(tmp_path: Path) -> None:
    reg = _approved(tmp_path, "SNOMED;CPT4", "data/*.json;data/*.csv")
    ids = {"c": [{"concept_id": 900001, "vocabulary": "SNOMED", "set": "Invented set", "domain": "Condition"},
                 {"concept_id": 900002, "vocabulary": "cpt4"}]}  # fmt: skip
    ok = _write(tmp_path / "data/ids.json", json.dumps(ids))
    rep = vbc.check([ok], register=reg, root=tmp_path)
    assert rep.problems == [] and rep.warnings == []
    assert [n for n in rep.notes if "ids only, allowed by register row approved-file (owner-approved)" in n]
    other = _write(tmp_path / "data/other.json", json.dumps({"c": [{"concept_id": 3, "vocabulary": "ICDO3"}]}))
    assert [p for p in vbc.check([other], register=reg, root=tmp_path).problems if "'ICDO3'" in p]
    table = _write(tmp_path / "data/ids.csv", "concept_id,vocabulary_id\n900001,SNOMED\n")
    assert [p for p in vbc.check([table], register=reg, root=tmp_path).problems if "'SNOMED'" in p]


def test_an_exception_naming_ids_lets_through_those_ids_only_in_tables_and_objects(tmp_path: Path) -> None:
    reg = _approved(tmp_path, "ICDO3:C99|900007", "data/codes.csv;data/ids.json")
    table = _write(tmp_path / "data/codes.csv", "row,system,code,name_in_source\nph.x,ICD-O-3,C99,\n")
    rep = vbc.check([table], register=reg, root=tmp_path)
    assert rep.problems == [] and [n for n in rep.notes if "1 concept id(s) of vocabulary 'ICDO3'" in n]
    _write(table, "row,system,code,name_in_source\nph.x,ICD-O-3,C99,\nph.y,ICD-O-3,C98,\n")
    got = vbc.check([table], register=reg, root=tmp_path).problems
    assert [p for p in got if "line 3 of vocabulary 'ICDO3' has id 'C98', which the register row does not list" in p]
    assert [p for p in got if "2 row(s) of vocabulary 'ICDO3'" in p]
    _write(table, "row,system,code,name_in_source\nph.x,ICD-O-3,C99,Invented site name\n")
    got = vbc.check([table], register=reg, root=tmp_path).problems
    assert [p for p in got if "carries text in 'name_in_source'" in p]
    doc = {"c": [{"concept_id": 900007, "vocabulary": "ICDO3"}, {"concept_id": 900008, "vocabulary": "ICDO3"}]}
    ids = _write(tmp_path / "data/ids.json", json.dumps(doc))
    got = vbc.check([ids], register=reg, root=tmp_path).problems
    assert [p for p in got if "has id 900008, which the register row does not list" in p]


def test_two_exception_rows_naming_one_file_let_through_both_vocabularies(tmp_path: Path) -> None:
    reg = _approved(tmp_path, "SNOMED", "data/ids.json")
    row = {c: "x" for c in lr.COLUMNS}
    row.update(id="second-row", kind=lr.EXCEPTION_KIND, status=lr.APPROVED, checked="2026-11-19", text_sha256="",
               athena="", athena_never="", paths="data/ids.json", excepts="ICDO3:5")  # fmt: skip
    row["class"] = ""
    reg.write_text(reg.read_text(encoding="utf-8") + ",".join(row[c] for c in lr.COLUMNS) + "\n", encoding="utf-8")
    doc = {"c": [{"concept_id": 1, "vocabulary": "SNOMED"}, {"concept_id": 5, "vocabulary": "ICDO3"}]}
    rep = vbc.check([_write(tmp_path / "data/ids.json", json.dumps(doc))], register=reg, root=tmp_path)
    assert rep.problems == []
    assert [n for n in rep.notes if "'SNOMED', ids only, allowed by register row approved-file" in n]
    assert [n for n in rep.notes if "'ICDO3', ids only, allowed by register row second-row" in n]


def test_an_owner_approved_exception_fails_a_labelled_object_that_carries_text(tmp_path: Path) -> None:
    reg = _approved(tmp_path, "SNOMED;CPT4", "data/*.json")
    for key in ("name", "concept_name", "display", "description", "synonyms"):
        doc = {"c": [{"concept_id": 900001, "vocabulary": "SNOMED", key: "Invented finding"}]}
        f = _write(tmp_path / f"data/{key}.json", json.dumps(doc))
        got = vbc.check([f], register=reg, root=tmp_path).problems
        assert [p for p in got if f"an object of vocabulary 'SNOMED' carries text in {key!r}" in p], key
    empty = _write(
        tmp_path / "data/empty.json", json.dumps({"c": [{"concept_id": 1, "vocabulary": "CPT4", "name": ""}]})
    )
    assert vbc.check([empty], register=reg, root=tmp_path).problems == []


def test_excepts_belongs_to_an_approved_exception_and_names_must_not_ship_vocabularies(tmp_path: Path) -> None:
    raw = {c: "x" for c in lr.COLUMNS}
    raw.update(checked="2026-11-19", text_sha256="", athena="", athena_never="", excepts="")
    approved = lr.Row("e1", lr.EXCEPTION_KIND, lr.APPROVED, "s", "x", (), ("data/a.json",), raw, excepts=("SNOMED",))
    bare = lr.Row("e2", lr.EXCEPTION_KIND, lr.APPROVED, "s", "x", (), ("data/a.json",), raw)
    pending = lr.Row("e3", lr.EXCEPTION_KIND, lr.PENDING, "s", "x", (), ("data/a.json",), raw, excepts=("SNOMED",))
    loadable = lr.Row("e4", lr.EXCEPTION_KIND, lr.APPROVED, "s", "x", (), ("data/a.json",), raw, excepts=("LOINC",))
    never = lr.Row("n", "code-system", "removed", "s", "x", (), (), {**raw, "athena_never": "SNOMED"}, "c", ("SNOMED",))
    got = lr.row_problems([approved, bare, pending, loadable, never])
    assert not [p for p in got if "e1" in p]
    assert any("e2: a owner-approved row names the vocabularies" in p for p in got)
    assert any("e3: excepts only on a bundle-exception row with status owner-approved" in p for p in got)
    assert any("row e4: excepts 'LOINC', which no row names in athena_never" in p for p in got)


def test_an_exception_row_must_be_pending_and_name_its_files() -> None:
    raw = {c: "x" for c in lr.COLUMNS}
    ok = lr.Row("e1", lr.EXCEPTION_KIND, lr.PENDING, "s", "x", (), ("data/a.csv",), raw)
    assert not [p for p in lr.row_problems([ok]) if "e1" in p and "go together" in p + "paths"]
    no_paths = lr.Row("e2", lr.EXCEPTION_KIND, lr.PENDING, "s", "x", (), (), raw)
    wrong = lr.Row("e3", "code-system", lr.PENDING, "s", "x", (), (), raw)
    got = lr.row_problems([no_paths, wrong])
    assert any("e2: a bundle-exception row names the files" in p for p in got)
    assert any("e3: kind bundle-exception and status decision-pending or owner-approved go together" in p
               for p in got)  # fmt: skip


# ------------------------------------------------------------------------------------------------ the wiring
def test_the_bundle_build_and_the_make_targets_call_the_check() -> None:
    lines = [ln for ln in (ROOT / "tools/make_bundle.sh").read_text(encoding="utf-8").splitlines()
             if not ln.lstrip().startswith("#")]  # fmt: skip

    def first(text: str) -> int:
        return next(i for i, ln in enumerate(lines) if text in ln)

    assert first("-m tools.vocab_bundle_check") < first("docker save") < first("tools.host_tree pack")
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("release-bundle", "demo-bundle"):
        rule = re.search(rf"^{target}:([^\n]*)$", make, re.M)
        assert rule is not None and "vocab-bundle-check" in rule.group(1).split(), target
    assert re.search(r"^vocab-bundle-check:\n\t[^\n]*-m tools\.vocab_bundle_check --tree", make, re.M)


def test_the_command_fails_and_names_the_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = _write(tmp_path / "ok/a.csv", CONCEPT_HEADER + CLEAN_ROW)
    assert vbc.main([str(clean)]) == 0
    assert "checked by label" in capsys.readouterr().out
    bad = _write(tmp_path / "bad/b.csv", CONCEPT_HEADER + "4000003,Invented regimen,Regimen,HemOnc,Regimen,S,N-1\n")
    assert vbc.main([str(clean), str(bad)]) == 1
    err = capsys.readouterr().err
    assert str(bad) in err and "'HemOnc'" in err and str(clean) not in err


def test_make_bundle_stops_on_a_forbidden_rule_set_before_any_image_is_saved(tmp_path: Path) -> None:
    """The real tools/make_bundle.sh against the stand-in docker of test_release_bundle; removing its call fails here."""
    import shutil

    if shutil.which("bash") is None:
        pytest.skip("needs bash")
    from tests.unit import test_release_bundle as trb

    mp = pytest.MonkeyPatch()
    try:
        kit = trb.kit.__wrapped__(tmp_path, mp)  # type: ignore[attr-defined]
        gates, sbom = trb._gate_record(kit["tmp"], [*trb.OWN, trb.BACKUP, trb.HAPI, trb.VLLM])
        rs = tmp_path / "rulesets"
        _write(
            rs / "RS-1.0.0.zip",
            _zip(
                {
                    "valuesets/VS_X.json": json.dumps(
                        {"resourceType": "ValueSet", "compose": {"include": [{"system": "http://snomed.info/sct"}]}}
                    ).encode()
                }
            ),
        )
        res = trb._make(
            kit, "--release-seq", "1", "--gates", str(gates), "--sbom-dir", str(sbom), "--rulesets", str(rs)
        )
        assert res.returncode == 1, res.stderr
        assert "must-not-ship vocabulary" in res.stderr and "RS-1.0.0.zip!valuesets/VS_X.json" in res.stderr
        log = kit["log"].read_text(encoding="utf-8") if kit["log"].exists() else ""
        assert not [ln for ln in log.splitlines() if ln.startswith("save ")]
        _write(
            rs / "RS-1.0.0.zip",
            _zip(
                {
                    "valuesets/VS_X.json": json.dumps(
                        {"resourceType": "ValueSet", "compose": {"include": [{"system": "http://loinc.org"}]}}
                    ).encode()
                }
            ),
        )
        ok = trb._make(kit, "--release-seq", "1", "--gates", str(gates), "--sbom-dir", str(sbom), "--rulesets", str(rs))
        assert re.search(r"vocabulary bundle check: \d+ artefacts, 0 problems", ok.stdout), ok.stdout + ok.stderr
    finally:
        mp.undo()


# ------------------------------------------------------------------------------------------------ second review
def test_a_sql_dump_and_a_csv_under_an_unknown_extension_are_read_field_by_field(tmp_path: Path) -> None:
    dump = _write(tmp_path / "b/d.sql", "COPY concept (concept_id, vocabulary_id, concept_code) FROM stdin;\n"
                  "4000001\tSNOMED\tNOT-A-CODE-1\n4000002\tRxNorm\tNOT-A-CODE-2\n\\.\n")  # fmt: skip
    odd = _write(tmp_path / "b/codes.export", "id,vocab,code\n1,cpt4,NOT-A-CODE-3\n")
    assert _problems(dump, odd) == [
        f"{dump}: 1 row(s) of vocabulary 'SNOMED', licence class c, must not ship (register row snomed-ct)",
        f"{odd}: 1 row(s) of vocabulary 'CPT4', licence class c, must not ship (register row athena-licensed)",
    ]
    prose = _write(tmp_path / "b/q.sql", "-- Read the table and keep it\nSELECT 1;\n")  # 'Read' only inside prose
    notice = _write(tmp_path / "b/NOTICE.md", "## WHO ICD-10\nAttribution text.\n")  # a heading, not a row
    assert _problems(prose, notice) == []


def test_https_bare_oid_and_edition_uris_are_caught(tmp_path: Path) -> None:
    txt = _write(tmp_path / "r/a.cql", "codesystem \"S\": 'https://snomed.info/sct'\n"
                 "codesystem \"E\": 'http://snomed.info/sct/900000000000207008/version/20250101'\n"
                 "-- oid 2.16.840.1.113883.6.96 and urn:oid:2.16.840.1.113883.6.12\n")  # fmt: skip
    vs = _write(tmp_path / "r/vs.json", json.dumps({"resourceType": "ValueSet", "compose": {"include": [
        {"system": "http://snomed.info/sct/900000000000207008/version/20250101"}]}}))  # fmt: skip
    got = _problems(txt, vs)
    assert f"{txt}: 1 row(s) of vocabulary 'CPT4', licence class c, must not ship (register row athena-licensed)" in got
    assert any(g.startswith(f"{txt}: ") and "'SNOMED'" in g for g in got)
    assert f"{vs}: 1 row(s) of vocabulary 'SNOMED', licence class c, must not ship (register row snomed-ct)" in got


def test_terminology_coding_scheme_cs_keys_and_yaml_are_read(tmp_path: Path) -> None:
    t = _write(tmp_path / "b/t.csv", "code,terminology,coding_scheme,cs\nN-1,SNOMED,,\nN-2,,CPT4,\nN-3,,,HemOnc\n")
    y = _write(tmp_path / "b/map.yaml", "rows:\n  - code: NOT-A-CODE-1\n    vocabulary_id: snomed\n")
    got = _problems(t, y)
    assert len([g for g in got if g.startswith(f"{t}: ")]) == 3
    assert got[-1] == f"{y}: 1 row(s) of vocabulary 'SNOMED', licence class c, must not ship (register row snomed-ct)"
    bad = _write(tmp_path / "b/bad.yaml", "a: [unclosed\n")
    assert _problems(bad) == [f"{bad}: YAML does not parse"]


def test_the_help_says_which_check_guards_what(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        vbc.main(["--help"])
    out = capsys.readouterr().out
    assert "--tree guards make vocab-bundle-check, release-bundle and demo-bundle" in " ".join(out.split())
    assert "make_bundle.sh" in out and "checks only what it stages" in " ".join(out.split())
