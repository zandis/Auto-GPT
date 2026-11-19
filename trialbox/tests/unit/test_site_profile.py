"""10B-6 (commitment C-6, D-1233): the site profile, one folder of a hospital's habits as data.

What is held here: the two synthetic profiles load; a profile that fails a check is refused with its file, line and
reason (an unknown key included); every row carries its state and a ``verify`` row is never shown as verified;
loading a new version records who, when, the old and new version and the digest, in the record and the audit; a
night records which profile read it; the coverage lines and the work list; and the plan's proof, a second profile
with other local codes over the same patients reads the same coded facts with no code change. Synthetic data only.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter import site_profile as sp
from adapter.mapping.engine import BASIS, VERIFY_BASIS, Mapping, MappingError
from adapter.ndjson import snapshot_dir
from adapter.pipeline import AdapterConfig, make_source, run_ingest
from tb_common.audit import _day_files
from tb_common.site_profile import SHIPPED_ROOT, VERIFIED, VERIFY, Profile, ProfileError, check_code, load, state_of
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "services/adapter/mapping/profile"
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
LAB = SHIPPED_ROOT / "tw_core/lab_local_to_loinc.csv"
NIGHT = "2026-11-01"
TZ = "Asia/Taipei"
TABLES = ["patient", "practitioner", "encounter", "appointment", "diagnosis", "lab", "vital", "medication",
          "procedure", "report", "note", "claim", "registry"]  # fmt: skip


def _manifest(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "format": "tb-site-profile/1",
        "id": "test-site",
        "site_id": "T",
        "country": "tw",
        "version": "1.0.0",
        "door": "csv",
        "standards": {"tw_core": "1.0.0"},
        "data_types": TABLES,
        "tables": {
            "lab": {
                "file": "codes/lab.csv",
                "key": "local_code",
                "target": "code",
                "state": "verified",
                "source": "a synthetic test table",
                "used_by": ["mapping.lab"],
            },
        },
    }
    doc.update(over)
    return doc


def _profile(folder: Path, doc: dict[str, Any] | None = None, rename: dict[str, str] | None = None) -> Path:
    """A site's own profile in ``folder``: the shipped Taiwan lab table copied into codes/ (local codes renamed)."""
    (folder / "codes").mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(LAB.open(encoding="utf-8")))
    with (folder / "codes/lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "local_code": (rename or {}).get(r["local_code"], r["local_code"])})
    (folder / "profile.yaml").write_text(yaml.safe_dump(doc or _manifest(), allow_unicode=True), encoding="utf-8")
    return folder


# ------------------------------------------------------------------------------------------------------ the loader
def test_the_two_synthetic_profiles_load_with_every_row_in_a_state() -> None:
    jp, tw = load(PROFILES / "synthetic-jp-ss"), load(PROFILES / "synthetic-tw-a")
    assert (jp.site_id, jp.door, jp.country, jp.synthetic) == ("jp-ss", "ssmix2", "jp", True)
    assert (tw.site_id, tw.door, tw.country, tw.synthetic) == ("tw-a", "csv", "tw", True)
    # the shipped samples say verify (synthetic codes nobody checked), the Taiwan sample's yes reads as verified
    assert {n: t.states() for n, t in jp.tables.items()} == {
        "diagnosis": {VERIFIED: 0, VERIFY: 32},
        "drug": {VERIFIED: 0, VERIFY: 22},
        "lab": {VERIFIED: 0, VERIFY: 14},
    }
    assert tw.tables["lab"].states() == {VERIFIED: 8, VERIFY: 6}
    assert tw.tables["lab"].find("UA") is not None and tw.tables["lab"].find("UA").verified  # type: ignore[union-attr]
    assert not jp.tables["lab"].find("TJC28").verified  # type: ignore[union-attr]  # "local": the safe side
    assert jp.used_by("ssmix2.lab") is jp.used_by("mapping.lab") is jp.tables["lab"]
    assert load(PROFILES / "synthetic-jp-ss").digest == jp.digest and jp.digest != tw.digest


def test_a_state_word_reads_as_verified_only_when_it_says_so() -> None:
    assert [state_of(w) for w in ("verified", "yes", "Confirmed", "verify", "local", "", None, "maybe")] == [
        VERIFIED, VERIFIED, VERIFIED, VERIFY, VERIFY, VERIFY, VERIFY, VERIFY]  # fmt: skip


def _refused(folder: Path) -> ProfileError:
    with pytest.raises(ProfileError) as exc:
        load(folder)
    return exc.value


def test_an_unknown_key_is_refused_with_its_line(tmp_path: Path) -> None:
    f = _profile(tmp_path / "p")
    text = (f / "profile.yaml").read_text(encoding="utf-8") + "encoding: cp932\n"
    (f / "profile.yaml").write_text(text, encoding="utf-8")
    e = _refused(f)
    assert e.where == f"profile.yaml:{text.count(chr(10))}" and "unknown key" in e.why and "encoding" in e.why
    doc = _manifest()
    doc["tables"]["lab"]["colour"] = "red"
    e = _refused(_profile(tmp_path / "q", doc))
    assert "unknown key" in e.why and "colour" in e.why and e.where.startswith("profile.yaml:")
    line = int(e.where.split(":")[1])
    assert "colour" in (tmp_path / "q/profile.yaml").read_text(encoding="utf-8").splitlines()[line - 1]


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"version": "1.0"}, "version"),
        ({"country": "fr"}, "country"),
        ({"door": "fhir_bulk"}, "door"),
        ({"data_types": []}, "data_types"),
        ({"format": "tb-site-profile/2"}, "format"),
        ({"id": "synthetic-x"}, "synthetic exactly when"),
        ({"standards": {"Bad Name": "1"}}, "not a name"),
    ],
)
def test_a_manifest_that_does_not_match_the_schema_is_refused(
    tmp_path: Path, change: dict[str, Any], said: str
) -> None:
    e = _refused(_profile(tmp_path / "p", _manifest(**change)))
    assert said in str(e) and e.where.startswith("profile.yaml")


@pytest.mark.parametrize(
    ("line", "said"),
    [
        ("ALTX,loinc,1742-6,x,U/L,1,laboratory,quantity,,,maybe,", "state 'maybe'"),
        (",loinc,1742-6,x,U/L,1,laboratory,quantity,,,verify,", "local_code cell is empty"),
        ("ALTX,loinc,,x,U/L,1,laboratory,quantity,,,verify,", "code cell is empty"),
        ("UA,loinc,3084-1,x,mg/dL,1,laboratory,quantity,,,verify,", "is 'UA' of line 2 (one code)"),
        ("ua,loinc,3084-1,x,mg/dL,1,laboratory,quantity,,,verify,", "is 'UA' of line 2 (one code)"),
        ("ＵＡ,loinc,3084-1,x,mg/dL,1,laboratory,quantity,,,verify,", "is 'UA' of line 2 (one code)"),
        ("ALTX,loinc,2160-1,x,U/L,1,laboratory,quantity,,,verify,", "fails LOINC's check digit"),
        ("ALTX,loinc,E11.9,x,U/L,1,laboratory,quantity,,,verify,", "is not a loinc code"),
        ("ALTX,loinc,NOT-A-CODE!,x,U/L,1,laboratory,quantity,,,verify,", "is not a loinc code"),
        ("ALTX,loinc,４５４８-４,x,%,1,laboratory,quantity,,,verify,", "is not a loinc code"),
        ("ALTX,snomed,271649006,x,,1,laboratory,quantity,,,verify,", "code system 'snomed' is not one this product"),
        ("ALTX,http://snomed.info/sct,271649006,x,,1,laboratory,quantity,,,verify,", "is not one this product"),
        ("ALTX,loinc,1742-6,x,U/L,1,laboratory,quantity,,,verify,,extra", "more cells"),
    ],
)
def test_a_bad_row_is_refused_with_its_file_and_line(tmp_path: Path, line: str, said: str) -> None:
    f = _profile(tmp_path / "p")
    with (f / "codes/lab.csv").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    n = (f / "codes/lab.csv").read_text(encoding="utf-8").count("\n")
    e = _refused(f)
    assert e.where == f"codes/lab.csv:{n}" and said in e.why


def test_a_table_without_its_columns_or_with_patient_columns_is_refused(tmp_path: Path) -> None:
    f = _profile(tmp_path / "p")
    (f / "codes/lab.csv").write_text("local_code,code,verified,mrn\nUA,3084-1,verify,123\n", encoding="utf-8")
    assert "patient data" in _refused(f).why
    (f / "codes/lab.csv").write_text("local_code,code\nUA,3084-1\n", encoding="utf-8")
    e = _refused(f)
    assert e.where == "codes/lab.csv:1" and "no column 'verified'" in e.why


def test_a_table_stays_in_its_folder_and_only_a_synthetic_profile_names_a_shipped_one(tmp_path: Path) -> None:
    doc = _manifest()
    doc["tables"]["lab"]["file"] = "codes/../../x.csv"
    assert "does not match" in _refused(_profile(tmp_path / "a", doc)).why
    doc = _manifest(id="synthetic-x", synthetic=True)
    doc["tables"]["lab"]["file"] = "shipped:../../../libs/x.csv"
    assert "stays inside its folder" in _refused(_profile(tmp_path / "s", doc)).why
    doc = _manifest()
    doc["tables"]["lab"]["file"] = "shipped:tw_core/lab_local_to_loinc.csv"
    assert "only a synthetic profile" in _refused(_profile(tmp_path / "b", doc)).why
    doc = _manifest()
    doc["tables"]["lab"]["file"] = "codes/none.csv"
    assert "no such table file" in _refused(_profile(tmp_path / "c", doc)).why


def test_the_ssmix2_reader_reads_its_tables_by_its_own_columns(tmp_path: Path) -> None:
    doc = _manifest(door="ssmix2")
    doc["tables"]["lab"]["used_by"] = ["ssmix2.diagnosis"]
    assert "reads key code and target icd10" in _refused(_profile(tmp_path / "a", doc)).why
    doc = _manifest()
    doc["tables"]["lab2"] = {**doc["tables"]["lab"]}
    assert "mapping.lab is read from" in _refused(_profile(tmp_path / "b", doc)).why


def test_a_mapping_refuses_a_profile_table_for_a_look_up_it_does_not_declare(tmp_path: Path) -> None:
    with pytest.raises(MappingError, match="does not declare"):
        Mapping.load(MAPPING, {"drug": LAB})
    f = _profile(tmp_path / "p", rename={"UA": "K-0001"})
    m = Mapping.load(MAPPING, {"lab": f / "codes/lab.csv"})
    assert m.lookups["lab"].find("K-0001") is not None and m.lookups["lab"].find("UA") is None
    assert m.version == Mapping.load(MAPPING).version  # the mapping's own version: its YAML, unchanged


def test_the_ssmix2_reader_takes_the_profiles_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter import licensed

    monkeypatch.setattr(licensed, "tables", lambda *a, **k: {})
    (tmp_path / "storage").mkdir()
    (tmp_path / "p/codes").mkdir(parents=True)
    (tmp_path / "p/codes/dx.csv").write_text("code,name,icd10,verified\nX001,痛風,M10.9,verify\n", encoding="utf-8")
    doc = _manifest(
        door="ssmix2",
        country="jp",
        tables={
            "diagnosis": {
                "file": "codes/dx.csv",
                "key": "code",
                "target": "icd10",
                "state": "verified",
                "used_by": ["ssmix2.diagnosis"],
            }
        },
    )
    (tmp_path / "p/profile.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    files = sp.write_tables(load(tmp_path / "p"), tmp_path / "loaded")
    src: Any = make_source("ssmix2", str(tmp_path / "storage"), profile_files=files)
    assert src.byomei == {"X001": "M10.9"}
    shipped: Any = make_source("ssmix2", str(tmp_path / "storage"))
    assert "X001" not in shipped.byomei and len(shipped.byomei) == 32


# ------------------------------------------------------------------------------------------- versions and audit
def _events(audit: Path) -> list[dict[str, Any]]:
    out = []
    for f in _day_files(audit):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [e for e in out if e.get("event") == sp.EVENT]


def test_a_new_version_is_recorded_and_audited_and_a_rollback_too(tmp_path: Path) -> None:
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    v1 = load(_profile(tmp_path / "v1"))
    first = sp.activate(v1, lake, site_id="T", by="steward-a", audit_dir=audit)
    assert first and (first["old_version"], first["new_version"], first["direction"]) == (None, "1.0.0", "first")
    assert sp.activate(v1, lake, site_id="T", by="adapter", audit_dir=audit) is None  # the same: nothing new
    v2 = load(_profile(tmp_path / "v2", _manifest(version="1.1.0"), rename={"UA": "K-0001"}))
    ch = sp.activate(v2, lake, site_id="T", by="steward-b", audit_dir=audit)
    assert ch and (ch["old_version"], ch["new_version"], ch["old_digest"], ch["new_digest"]) == (
        "1.0.0", "1.1.0", v1.digest, v2.digest)  # fmt: skip
    back = sp.activate(v1, lake, site_id="T", by="steward-a", audit_dir=audit)
    assert back and back["direction"] == "back" and back["new_version"] == "1.0.0"
    ev = _events(audit)
    assert [(e["actor"], e["detail"]["new_version"], e["output_sha"]) for e in ev] == [
        ("steward-a", "1.0.0", v1.digest),
        ("steward-b", "1.1.0", v2.digest),
        ("steward-a", "1.0.0", v1.digest),
    ]
    hist = sp.read_record(lake)["history"]
    assert [(h["by"], h["version"], h["direction"]) for h in hist] == [
        ("steward-a", "1.0.0", "first"),
        ("steward-b", "1.1.0", "forward"),
        ("steward-a", "1.0.0", "back"),
    ]
    assert all(h["at"] for h in hist)


def test_changed_content_under_a_version_read_before_another_site_or_door_is_refused(tmp_path: Path) -> None:
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    sp.activate(load(_profile(tmp_path / "a")), lake, site_id="T", by="s", audit_dir=audit)
    changed = load(_profile(tmp_path / "b", rename={"UA": "K-0001"}))
    with pytest.raises(ProfileError, match="give the changed profile a new version"):
        sp.activate(changed, lake, site_id="T", by="s", audit_dir=audit)
    with pytest.raises(ProfileError, match="for site 'T', not 'U'"):
        sp.activate(changed, lake, site_id="U", by="s", audit_dir=audit)
    with pytest.raises(ProfileError, match="describes a csv source; the box reads ssmix2"):
        sp.activate(load(_profile(tmp_path / "c", _manifest(version="2.0.0"))), lake, site_id="T", by="s",
                    door="ssmix2", audit_dir=audit)  # fmt: skip
    # 1.0.0 -> 1.1.0 -> a changed 1.0.0: the whole history is asked, not only the active profile
    sp.activate(load(_profile(tmp_path / "d", _manifest(version="1.1.0"))), lake, site_id="T", by="s", audit_dir=audit)
    with pytest.raises(ProfileError, match="version 1.0.0 was read on .* with other content"):
        sp.activate(changed, lake, site_id="T", by="s", audit_dir=audit)


def test_nothing_is_activated_without_an_audit(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="only with its audit"):
        sp.activate(load(_profile(tmp_path / "a")), tmp_path / "lake", site_id="T", by="s", audit_dir=None)
    assert not (tmp_path / "lake" / sp.RECORD).exists()


def test_every_row_whose_state_changes_is_in_the_audit_event(tmp_path: Path) -> None:
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    sp.activate(load(_profile(tmp_path / "v1")), lake, site_id="T", by="steward-a", audit_dir=audit)
    first = _events(audit)[0]["detail"]
    assert first["rows_changed"] == 14 and {c["from"] for c in first["row_changes"]} == {None}
    f = _profile(tmp_path / "v2", _manifest(version="1.1.0"))
    text = (f / "codes/lab.csv").read_text(encoding="utf-8")
    (f / "codes/lab.csv").write_text(text.replace("AHBC,loinc", "AHBX,loinc"), encoding="utf-8")
    rows = list(csv.DictReader((f / "codes/lab.csv").open(encoding="utf-8")))
    for r in rows:
        if r["local_code"] == "IGRA":
            r["verified"] = "verified"
    with (f / "codes/lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    sp.activate(load(f), lake, site_id="T", by="steward-b", audit_dir=audit)
    ev = _events(audit)[1]
    assert ev["actor"] == "steward-b" and ev["ts"]
    assert ev["detail"]["row_changes"] == [
        {"table": "lab", "code": "AHBC", "from": VERIFY, "to": None},
        {"table": "lab", "code": "AHBX", "from": None, "to": VERIFY},
        {"table": "lab", "code": "IGRA", "from": VERIFY, "to": VERIFIED},
    ]


# --------------------------------------------------------------------------------- checks against the box
def test_a_table_a_mapping_reads_has_the_mappings_key_and_columns(tmp_path: Path) -> None:
    m = Mapping.load(MAPPING)
    sp.check_mapping(load(_profile(tmp_path / "ok")), m)
    f = _profile(tmp_path / "three")
    (f / "codes/lab.csv").write_text("local_code,system,code,verified\nUA,loinc,3084-1,verify\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="no column 'display' \\(the mapping reads it\\)"):
        sp.check_mapping(load(f), m)
    doc = _manifest()
    doc["tables"]["lab"]["key"] = "site_code"
    f = _profile(tmp_path / "renamed", doc)
    text = (f / "codes/lab.csv").read_text(encoding="utf-8")
    (f / "codes/lab.csv").write_text("site_code" + text[len("local_code") :], encoding="utf-8")
    with pytest.raises(ProfileError, match="looks lab up by 'local_code', not 'site_code'"):
        sp.check_mapping(load(f), m)
    f = _profile(tmp_path / "extra")
    rows = (f / "codes/lab.csv").read_text(encoding="utf-8").splitlines()
    (f / "codes/lab.csv").write_text("\n".join([rows[0] + ",chart_note", *(r + ",x" for r in rows[1:])]) + "\n",
                                     encoding="utf-8")  # fmt: skip
    with pytest.raises(ProfileError, match="column 'chart_note' is not one the mapping reads"):
        sp.check_mapping(load(f), m)


def test_an_empty_table_is_refused(tmp_path: Path) -> None:
    f = _profile(tmp_path / "p")
    header = (f / "codes/lab.csv").read_text(encoding="utf-8").splitlines()[0]
    (f / "codes/lab.csv").write_text(header + "\n", encoding="utf-8")
    assert "no rows" in _refused(f).why


def test_the_check_command_holds_a_mapping_table_to_its_mapping(tmp_path: Path) -> None:
    f = _profile(tmp_path / "p")
    assert sp.main(["check", str(f)]) == 2  # a mapping's look-up: --mapping is needed
    assert sp.main(["check", str(f), "--mapping", str(MAPPING)]) == 0
    (f / "codes/lab.csv").write_text("local_code,system,code,verified\nUA,loinc,3084-1,verify\n", encoding="utf-8")
    assert sp.main(["check", str(f), "--mapping", str(MAPPING)]) == 2


def test_the_country_and_the_standard_versions_agree_with_the_settings(tmp_path: Path) -> None:
    p = load(_profile(tmp_path / "p"))
    sp.check_settings(p, country="TW", standards={"tw_core": "1.0.0", "twpas_version": "1.2.5"})
    sp.check_settings(p, country=None)  # a country the settings cannot name: nothing to compare
    with pytest.raises(ProfileError, match="country tw is not the site's \\(jp, from settings\\)"):
        sp.check_settings(p, country="JP")
    with pytest.raises(ProfileError, match="standards.tw_core 1.0.0 is not settings.profiles.tw_core \\(1.1.0\\)"):
        sp.check_settings(p, country="TW", standards={"tw_core": "1.1.0"})


@pytest.mark.parametrize("source", ["from https://example.invalid/master", "ask steward@hospital", "x" * 40])
def test_a_manifest_holds_nothing_secret(tmp_path: Path, source: str) -> None:
    doc = _manifest()
    doc["tables"]["lab"]["source"] = source
    e = _refused(_profile(tmp_path / "p", doc))
    assert "nothing secret" in e.why and e.where.startswith("profile.yaml:")


def test_a_reader_table_has_only_the_columns_the_reader_reads(tmp_path: Path) -> None:
    (tmp_path / "p/codes").mkdir(parents=True)
    (tmp_path / "p/codes/dx.csv").write_text("code,name,icd10,verified,patient_no\nX001,痛風,M10.9,verify,12\n",
                                             encoding="utf-8")  # fmt: skip
    doc = _manifest(
        door="ssmix2",
        country="jp",
        tables={
            "diagnosis": {
                "file": "codes/dx.csv",
                "key": "code",
                "target": "icd10",
                "state": "verified",
                "used_by": ["ssmix2.diagnosis"],
            }
        },
    )
    (tmp_path / "p/profile.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert "column 'patient_no' is not one ssmix2.diagnosis reads" in _refused(tmp_path / "p").why


# ---------------------------------------------------------------------------------------- coverage and work list
def _night_files(d: Path) -> Path:
    d.mkdir(parents=True)
    (d / "completeness.json").write_text(json.dumps({"tables": {"patient": {"rows": 40}, "lab": {"rows": 300},
                                                                 "vital": {"rows": 0}, "extra": {"rows": 5}}}))  # fmt: skip
    (d / "unmapped_codes.json").write_text(json.dumps({"lab": {"lab": {"=CMD()": 3, "X9": 1}}}))
    return d


def test_coverage_lines_count_types_unmapped_codes_and_verify_rows(tmp_path: Path) -> None:
    p = load(_profile(tmp_path / "p", _manifest(data_types=["patient", "lab", "vital", "note", "allergy"])))
    cov = sp.coverage(p, _night_files(tmp_path / "night"), reads=TABLES, from_verify={"lab": 950, "vital": 0})
    assert cov["not_read"] == ["allergy"] and cov["facts_from_verify"] == {"lab": 950}
    assert sp.summary(cov)["facts_from_verify"] == 950
    text = "\n".join(sp.lines(cov))
    assert (
        "declared, not read by this version: allergy" in text
        and "facts resting on a row still to verify: lab 950" in text
    )
    p = load(_profile(tmp_path / "q", _manifest(data_types=["patient", "lab", "vital", "note"])))
    cov = sp.coverage(p, tmp_path / "night")
    assert cov["data_types"] == [{"type": "patient", "rows": 40}, {"type": "lab", "rows": 300},
                                 {"type": "vital", "rows": 0}, {"type": "note", "rows": 0}]  # fmt: skip
    assert cov["not_arrived"] == ["vital", "note"] and cov["not_declared"] == [{"type": "extra", "rows": 5}]
    assert cov["unmapped"] == {"lab": {"codes": 2, "rows": 4}}
    assert cov["tables"]["lab"] == {"rows": 14, VERIFIED: 8, VERIFY: 6}
    s = sp.summary(cov)
    assert (s["types_declared"], s["types_arrived"], s["unmapped_codes"], s["unmapped_rows"], s["verify_rows"]) == (
        4, 2, 2, 4, 6)  # fmt: skip
    text = "\n".join(sp.lines(cov))
    assert "2 of 4 declared arrived" in text and "lab: 2 codes, 4 rows" in text and "lab: 6 of 14" in text
    assert "=CMD()" not in text  # the lines are counts: a code is in the work list only


def test_the_work_list_is_a_csv_of_unmapped_codes_then_verify_rows(tmp_path: Path) -> None:
    p = load(_profile(tmp_path / "p"))
    rows = sp.worklist(p, _night_files(tmp_path / "night"))
    got = list(csv.DictReader(io.StringIO(sp.worklist_csv(rows))))
    assert [(r["kind"], r["code"], r["rows"]) for r in got[:2]] == [
        ("unmapped", "'=CMD()", "3"),
        ("unmapped", "X9", "1"),
    ]
    verify = [r for r in got if r["kind"] == "verify"]
    assert len(verify) == 6 and all(r["file"] == "codes/lab.csv" and r["line"] and r["target"] for r in verify)
    out = tmp_path / "w.csv"
    assert sp.main(["worklist", "--profile", str(tmp_path / "p"), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").count("\nverify,") == 6
    assert [sp._cell(v) for v in ("\tX", "\rX", "-1", "AB")] == ["'\tX", "'\rX", "'-1", "AB"]


def test_the_site_set_up_store_wins_and_each_disagreement_is_on_the_work_list(tmp_path: Path) -> None:
    """Coordinator's ruling on #1128: a lab code both homes map, the D-135 store (a named person's act) wins; every
    disagreement is a work-list row. Not applied at night yet: the adapter does not read that store (D-1233)."""
    p = load(_profile(tmp_path / "p"))
    lab = "urn:trialbox:local:lab-code"
    confirmed = {("observation", lab, "UA"): {"system": "http://loinc.org", "code": "14933-6"},
                 ("observation", lab, "CRE"): {"system": "http://loinc.org", "code": "2160-0"},  # the same: no row
                 ("observation", lab, "NEW1"): {"system": "http://loinc.org", "code": "1234-5"},
                 ("condition", "urn:trialbox:local:dx-code", "UA"): {"code": "M10.9"}}  # fmt: skip
    wins = sp.store_wins(p, confirmed)
    assert (wins["UA"], wins["CRE"], wins["NEW1"], wins["ALT"]) == ("14933-6", "2160-0", "1234-5", "1742-6")
    rows = sp.worklist(p, None, confirmed)
    disagree = [r for r in rows if r["kind"] == "disagree"]
    assert [(r["code"], r["target"]) for r in disagree] == [("UA", "profile 3084-1; site set-up 14933-6 (wins)")]


# --------------------------------------------------------------------------------- a night and the plan's proof
class _Rebuild:
    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)


def _cfg(tmp: Path, url: str, tag: str, profile: Path | None, *, loaded: bool = True) -> AdapterConfig:
    """A night's settings; with ``profile``, that folder loaded first by a person (``load --by``), unless not
    ``loaded``: the night applies only a version a person loaded."""
    sec = tmp / f"secrets-{tag}"
    sec.mkdir(exist_ok=True)
    if profile is not None and loaded:
        sp.activate(load(profile), tmp / f"lake-{tag}", site_id="T", by="steward-t", audit_dir=tmp / f"audit-{tag}",
                    tz=TZ, door="csv")  # fmt: skip
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    sep = "&" if "?" in url else "?"
    return AdapterConfig(lake_dir=tmp / f"lake-{tag}", secrets_dir=sec, mapping_path=MAPPING, site_id="T", tz=TZ,
                         rebuild=_Rebuild(), audit_dir=tmp / f"audit-{tag}", site_profile=profile,
                         db_url=f"{url}{sep}tb_prefix=sp{tag}{os.getpid()}_")  # fmt: skip


def _facts(nd: Path) -> list[tuple[Any, ...]]:
    """What the funnel reads of a lab result: who, when, the standard code, the value (never the local code)."""
    out = []
    for line in (nd / "Observation.ndjson").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        std = sorted(c["code"] for c in r.get("code", {}).get("coding", []) if c.get("system") == "http://loinc.org")
        val = r.get("valueQuantity") or r.get("valueCodeableConcept") or r.get("valueString")
        out.append((r["id"], r["subject"]["reference"], r.get("effectiveDateTime"), tuple(std), json.dumps(val)))
    return sorted(out)


def test_a_second_profile_with_other_local_codes_reads_the_same_facts_with_no_code_change(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    """The plan's proof (C-6), at the size of a unit test: the same synthetic patients, the hospital's lab codes
    renamed in its export, its own profile carrying the renamed table. No mapping file and no code is changed."""
    rename = {"CRE": "K-0021", "HBA1C": "K-0105", "ALT": "K-0007", "UA": "K-0030"}
    plain = tmp_path / "feed-a"
    shutil.copytree(SITE_A, plain, ignore=shutil.ignore_patterns("*.json"))
    other = tmp_path / "feed-b"
    shutil.copytree(plain, other)
    lab = list(csv.DictReader((plain / "lab.csv").open(encoding="utf-8")))
    with (other / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lab[0]), lineterminator="\n")
        w.writeheader()
        w.writerows({**r, "local_code": rename.get(r["local_code"], r["local_code"])} for r in lab)
    assert any(r["local_code"] in rename for r in lab)
    folder = _profile(tmp_path / "profile-b", rename=rename)
    a = run_ingest(_cfg(tmp_path, pg_cluster_url, "a", None), "csv", str(plain), snapshot=NIGHT, load_fhir=False,
                   validate=False)  # fmt: skip
    b = run_ingest(_cfg(tmp_path, pg_cluster_url, "b", folder), "csv", str(other), snapshot=NIGHT, load_fhir=False,
                   validate=False)  # fmt: skip
    assert a.passed and b.passed
    nda, ndb = snapshot_dir(tmp_path / "lake-a", NIGHT), snapshot_dir(tmp_path / "lake-b", NIGHT)
    assert _facts(nda) == _facts(ndb) and len(_facts(nda)) > 100
    for t in ("Patient", "Condition", "MedicationRequest", "Encounter"):  # nothing else the profile touches moves
        assert (nda / f"{t}.ndjson").read_bytes() == (ndb / f"{t}.ndjson").read_bytes(), t
    # which profile read each night: none for a, profile-b's version and digest for b, in the file and the audit
    assert sp.night_profile(nda) is None
    stamp = sp.night_profile(ndb)
    assert stamp == load(folder).stamp()
    assert sp.main(["which", "--lake", str(tmp_path / "lake-b"), "--snapshot", NIGHT]) == 0
    done = [json.loads(x) for f in _day_files(tmp_path / "audit-b") for x in f.read_text(encoding="utf-8").splitlines()]
    said = next(e["detail"]["site_profile"] for e in done if e["event"] == "ingest.done")
    assert (said["id"], said["version"], said["digest"]) == ("test-site", "1.0.0", stamp["digest"])
    assert said["types_arrived"] == len(TABLES) and said["unmapped_rows"] == 0
    assert [e["actor"] for e in done if e["event"] == sp.EVENT] == ["steward-t"]  # a person, never the night


def _untagged(line: str) -> tuple[str, bool]:
    """A resource without the basis tag ``verify`` (if it had one), and whether it had."""
    r = json.loads(line)
    tags = (r.get("meta") or {}).get("tag") or []
    kept = [t for t in tags if t != {"system": BASIS, "code": VERIFY_BASIS}]
    if len(kept) != len(tags):
        r["meta"]["tag"] = kept
    return json.dumps(r, ensure_ascii=False), len(kept) != len(tags)


def test_the_shipped_profile_reads_the_night_as_without_one_but_for_the_verify_tag(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    """No other change: the synthetic Taiwan profile names the very table the mapping reads. What changes is the
    review's ruling: each lab result whose code is a ``verify`` row carries D-135's basis tag ``verify``."""
    feed = tmp_path / "feed"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    doc = yaml.safe_load((PROFILES / "synthetic-tw-a/profile.yaml").read_text(encoding="utf-8"))
    doc["site_id"] = "T"
    (tmp_path / "synthetic-tw-t").mkdir()
    (tmp_path / "synthetic-tw-t/profile.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    run_ingest(_cfg(tmp_path, pg_cluster_url, "a", None), "csv", str(feed), snapshot=NIGHT, load_fhir=False,
               validate=False)  # fmt: skip
    run_ingest(_cfg(tmp_path, pg_cluster_url, "b", tmp_path / "synthetic-tw-t"), "csv", str(feed), snapshot=NIGHT,
               load_fhir=False, validate=False)  # fmt: skip
    nda, ndb = snapshot_dir(tmp_path / "lake-a", NIGHT), snapshot_dir(tmp_path / "lake-b", NIGHT)
    names = sorted(p.name for p in nda.glob("*.ndjson"))
    assert names and names == sorted(p.name for p in ndb.glob("*.ndjson"))
    for n in names:
        if n != "Observation.ndjson":
            assert (nda / n).read_bytes() == (ndb / n).read_bytes(), n
    plain = (nda / "Observation.ndjson").read_text(encoding="utf-8").splitlines()
    tagged = [_untagged(x) for x in (ndb / "Observation.ndjson").read_text(encoding="utf-8").splitlines()]
    assert [json.loads(x) for x in plain] == [json.loads(x) for x, _ in tagged]
    verify = {r.code for r in load(tmp_path / "synthetic-tw-t").tables["lab"].rows.values() if r.state == VERIFY}
    lab = list(csv.DictReader((feed / "lab.csv").open(encoding="utf-8")))
    want = sum(1 for r in lab if r["local_code"] in verify)
    assert sum(1 for _, had in tagged if had) == want > 900  # AHBC, IGRA and the local score codes
    said = json.loads((ndb / sp.RECORD).read_text(encoding="utf-8"))["coverage"]["facts_from_verify"]
    assert said == {"lab": want}


def test_a_fact_from_a_verify_row_stays_coded_and_is_listed_as_resting_on_one(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    """Today's behaviour, pinned (D-1233; open question in DATA §15): nothing decides whether an unverified mapping
    may exclude a patient. A fact from a ``verify`` row is coded like any record (so it can meet or exclude), and the
    lake lists it in ``site_fact`` with basis ``verify``; only ``proposed`` (D-135) keeps a fact out of the coded
    tables."""
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from lake.store import Lake

    feed = tmp_path / "feed"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    run_ingest(_cfg(tmp_path, pg_cluster_url, "b", _profile(tmp_path / "p")), "csv", str(feed), snapshot=NIGHT,
               load_fhir=False, validate=False)  # fmt: skip
    nd = snapshot_dir(tmp_path / "lake-b", NIGHT)
    ids = {json.loads(x)["id"] for x in (nd / "Observation.ndjson").read_text(encoding="utf-8").splitlines()
           if _untagged(x)[1]}  # fmt: skip
    assert len(ids) > 900
    Lake(tmp_path / "lake-built", TZ).rebuild(NIGHT, HashEmbedder(), nd)
    lake = LakeLocal(tmp_path / "lake-built", HashEmbedder())
    coded = {r["oid"] for r in lake.query("SELECT oid FROM observation").to_pylist()}
    listed = {r["fid"]: r["basis"] for r in lake.query("SELECT fid, basis FROM site_fact").to_pylist()}
    assert ids <= coded and {listed[i] for i in ids} == {VERIFY_BASIS}


def test_a_refused_profile_is_never_loaded_and_the_night_stops_rather_than_read_without_it(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    """D-1233 (the lane lead's point 4): a profile that cannot be applied ends the night, as before profiles had
    versions: the box keeps serving the night before, and no night screens silently without the site's codes."""
    folder = _profile(tmp_path / "p")
    (folder / "codes/lab.csv").write_text(
        "local_code,system,code,verified\nUA,loinc,3084-1,perhaps\n", encoding="utf-8"
    )
    with pytest.raises(ProfileError, match="codes/lab.csv:2"):
        load(folder)
    feed = _feed(tmp_path)
    with pytest.raises(ProfileError, match="no person has loaded it"):
        run_ingest(_cfg(tmp_path, pg_cluster_url, "x", folder, loaded=False), "csv", str(feed), snapshot=NIGHT,
                   load_fhir=False, validate=False)  # fmt: skip
    assert not snapshot_dir(tmp_path / "lake-x", NIGHT).joinpath("Observation.ndjson").exists()


def test_the_box_finds_its_profile_in_the_site_mapping_folder_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_MAPPING_DIR", str(tmp_path / "site"))
    assert sp.find() is None  # no folder: no profile, the box reads as before
    _profile(tmp_path / "site/profile")
    assert sp.find() == tmp_path / "site/profile"
    monkeypatch.setenv("TB_MAPPING_DIR", str(SHIPPED_ROOT))
    assert sp.find() is None  # the image's synthetic profiles are examples: never a box's own


def test_a_second_ssmix2_profile_with_other_diagnosis_codes_reads_the_same_diagnoses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plan's proof at the SS-MIX2 door: the same synthetic storage with the hospital's 病名 codes renamed in
    every PPR-01 message (they carry no ICD-10 of their own, so the reader takes it from the table), and a profile
    whose diagnosis table carries the renamed codes, give the same diagnoses (who, which visit, ICD-10, dates)."""
    from datetime import date

    from adapter import licensed

    from tools.ssmix2_export import export
    from tools.synth_hospital import run as synth_run

    monkeypatch.setattr(licensed, "tables", lambda *a, **k: {})
    synth_run(tmp_path / "synth", profile="ci", sites="jp-ss:JP:60", ref_date=date(2026, 11, 1), seed=42)
    export(tmp_path / "synth" / "jp-ss", tmp_path / "plain")
    shutil.copytree(tmp_path / "plain", tmp_path / "renamed")
    renamed = 0
    for f in (tmp_path / "renamed").rglob("*PPR-01*"):
        if f.is_file():
            data = f.read_bytes()
            renamed += data.count(b"|ZB")
            f.write_bytes(data.replace(b"|ZB", b"|XB"))
    assert renamed > 50
    (tmp_path / "p/codes").mkdir(parents=True)
    table = (SHIPPED_ROOT / "jp_core/byomei_to_icd10.csv").read_text(encoding="utf-8")
    (tmp_path / "p/codes/dx.csv").write_text(table.replace("\nZB", "\nXB"), encoding="utf-8")
    doc = _manifest(id="test-jp", site_id="J", country="jp", door="ssmix2", data_types=["PPR-01"], tables={
        "diagnosis": {"file": "codes/dx.csv", "key": "code", "target": "icd10", "state": "verified",
                      "used_by": ["ssmix2.diagnosis"]}})  # fmt: skip
    (tmp_path / "p/profile.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")

    def read(storage: Path, profile: Any) -> tuple[list[tuple[str, ...]], set[str]]:
        files = sp.write_tables(profile, tmp_path / "loaded") if profile is not None else None
        src: Any = make_source("ssmix2", str(storage), profile_files=files)
        rows = list(src.rows("diagnosis", "diagnosis", None, None))
        keep = ("diag_no", "enc_no", "mrn", "icd10", "icd10cm", "diag_date", "recorded_date", "status")
        return sorted(tuple(str(r.get(k) or "") for k in keep) for r in rows), {str(r["byomei_code"]) for r in rows}

    a, codes_a = read(tmp_path / "plain", None)
    b, codes_b = read(tmp_path / "renamed", load(tmp_path / "p"))
    assert a == b and len(a) > 50 and all(r[3] for r in a)
    assert {c[:2] for c in codes_a if c} == {"ZB"} and {c[:2] for c in codes_b if c} == {"XB"}


def test_the_load_command_takes_the_site_from_the_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    cfg = SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(id="T", locale="zh-TW"), profiles=None),
                          env=SimpleNamespace(tz=TZ))  # fmt: skip
    monkeypatch.setattr(sp, "_settings", lambda: cfg)
    monkeypatch.delenv("TB_AUDIT_DIR", raising=False)
    f = _profile(tmp_path / "p")
    base = ["load", str(f), "--lake", str(tmp_path / "lake"), "--by", "steward-a", "--mapping", str(MAPPING)]
    assert sp.main(base) == 2  # no audit destination: refused
    assert sp.main([*base, "--audit", str(tmp_path / "audit")]) == 0
    assert sp.read_record(tmp_path / "lake")["active"]["by"] == "steward-a"
    other = _profile(tmp_path / "u", _manifest(site_id="U", version="2.0.0"))
    assert sp.main(["load", str(other), "--lake", str(tmp_path / "lake"), "--by", "s", "--mapping", str(MAPPING),
                    "--audit", str(tmp_path / "audit")]) == 2  # fmt: skip
    assert sp.read_record(tmp_path / "lake")["active"]["site_id"] == "T"


# ------------------------------------------------------------------- the lane lead's check of 60632078 (one test each)
def _feed(tmp: Path, name: str = "feed") -> Path:
    feed = tmp / name
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    return feed


def _rewrite_lab(feed: Path, change: Any) -> list[dict[str, str]]:
    rows = list(csv.DictReader((feed / "lab.csv").open(encoding="utf-8")))
    out = [change(i, r) for i, r in enumerate(rows)]
    with (feed / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    return out


def _set_state(folder: Path, code: str, state: str, version: str | None = None) -> Path:
    rows = list(csv.DictReader((folder / "codes/lab.csv").open(encoding="utf-8")))
    with (folder / "codes/lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows({**r, "verified": state if r["local_code"] == code else r["verified"]} for r in rows)
    if version:
        doc = yaml.safe_load((folder / "profile.yaml").read_text(encoding="utf-8"))
        doc["version"] = version
        (folder / "profile.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return folder


def test_1_a_code_the_look_up_matches_by_its_folded_form_is_tagged_from_the_matched_row(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    """UA set to verify; the feed writes it UA, ' UA', 'ua', 'Ua ' and full-width: every UA result gets its LOINC
    code and every one is tagged and counted (60632078 tagged 135 of 337)."""
    forms = ["UA", " UA", "ua", "Ua ", "ＵＡ"]
    feed = _feed(tmp_path)
    lab = _rewrite_lab(feed, lambda i, r: {**r, "local_code": forms[i % 5]} if r["local_code"] == "UA" else r)
    folder = _set_state(_profile(tmp_path / "p"), "UA", "verify")
    run_ingest(_cfg(tmp_path, pg_cluster_url, "b", folder), "csv", str(feed), snapshot=NIGHT, load_fhir=False,
               validate=False)  # fmt: skip
    nd = snapshot_dir(tmp_path / "lake-b", NIGHT)
    n_ua = sum(1 for r in lab if r["local_code"].strip().upper() in ("UA", "ＵＡ"))
    obs = [json.loads(x) for x in (nd / "Observation.ndjson").read_text(encoding="utf-8").splitlines()]
    urate = [o for o in obs if any(c.get("code") == "3084-1" for c in o["code"]["coding"])]
    assert len(urate) == n_ua == 337
    assert all(any(t == {"system": BASIS, "code": VERIFY_BASIS} for t in o["meta"]["tag"]) for o in urate)
    said = json.loads((nd / sp.RECORD).read_text(encoding="utf-8"))["coverage"]["facts_from_verify"]["lab"]
    verify = {r.code for r in load(folder).tables["lab"].rows.values() if r.state == VERIFY}
    assert said == n_ua + sum(1 for r in lab if r["local_code"] in verify - {"UA"})


def test_2_the_night_reads_the_standard_code_as_loaded_never_the_raw_cell(tmp_path: Path, pg_cluster_url: str) -> None:
    folder = _profile(tmp_path / "p")
    text = (folder / "codes/lab.csv").read_text(encoding="utf-8")
    (folder / "codes/lab.csv").write_text(text.replace("CRE,loinc,2160-0,", "CRE,loinc, 2160-0 ,"), encoding="utf-8")
    assert load(folder).tables["lab"].rows["CRE"].target == "2160-0"
    run_ingest(_cfg(tmp_path, pg_cluster_url, "b", folder), "csv", str(_feed(tmp_path)), snapshot=NIGHT,
               load_fhir=False, validate=False)  # fmt: skip
    nd = snapshot_dir(tmp_path / "lake-b", NIGHT)
    codes = [c.get("code") for x in (nd / "Observation.ndjson").read_text(encoding="utf-8").splitlines()
             for c in json.loads(x)["code"]["coding"]]  # fmt: skip
    assert codes.count("2160-0") == 300 and " 2160-0 " not in codes


def test_4_a_changed_profile_makes_a_delta_night_read_whole_in_both_directions(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    """IGRA goes verify -> verified (its tags go) and back (they come again): each delta night after a new version
    reads whole, so no carried-over fact keeps the old state."""
    feed = _feed(tmp_path)
    folder = _profile(tmp_path / "p")
    cfg = _cfg(tmp_path, pg_cluster_url, "d", folder)

    def night(snap: str, since: str | None) -> tuple[dict[str, Any], int]:
        run_ingest(cfg, "csv", str(feed), snapshot=snap, since=since, load_fhir=False, validate=False)
        nd = snapshot_dir(tmp_path / "lake-d", snap)
        rec = json.loads((nd / sp.RECORD).read_text(encoding="utf-8"))
        return rec, rec["coverage"]["facts_from_verify"].get("lab", 0)

    first, n1 = night("2026-11-01", None)
    _set_state(folder, "IGRA", "verified", "1.1.0")
    sp.activate(load(folder), tmp_path / "lake-d", site_id="T", by="steward-t", audit_dir=tmp_path / "audit-d", tz=TZ)
    second, n2 = night("2026-11-02", "2026-11-01")
    assert second["read_whole_because_the_profile_changed"] and n2 == n1 - 95  # the 95 IGRA results lost their tag
    _set_state(folder, "IGRA", "verify", "1.2.0")
    sp.activate(load(folder), tmp_path / "lake-d", site_id="T", by="steward-t", audit_dir=tmp_path / "audit-d", tz=TZ)
    third, n3 = night("2026-11-03", "2026-11-02")
    assert third["read_whole_because_the_profile_changed"] and n3 == n1
    assert not first["read_whole_because_the_profile_changed"]


def test_5_taking_the_folder_away_is_audited_and_the_next_night_says_no_profile(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    feed = _feed(tmp_path)
    cfg = _cfg(tmp_path, pg_cluster_url, "r", _profile(tmp_path / "p"))
    run_ingest(cfg, "csv", str(feed), snapshot="2026-11-01", load_fhir=False, validate=False)
    cfg.site_profile = None
    run_ingest(cfg, "csv", str(feed), snapshot="2026-11-02", load_fhir=False, validate=False)
    assert sp.read_record(tmp_path / "lake-r")["active"] is None
    removed = [json.loads(x) for f in _day_files(tmp_path / "audit-r") for x in f.read_text(encoding="utf-8").splitlines()
               if '"site_profile.removed"' in x]  # fmt: skip
    assert len(removed) == 1 and removed[0]["detail"]["old_version"] == "1.0.0"
    nd = snapshot_dir(tmp_path / "lake-r", "2026-11-02")
    assert sp.night_profile(nd) is None
    assert json.loads((nd / sp.RECORD).read_text(encoding="utf-8"))["note"]["removed"]["version"] == "1.0.0"


def test_6_a_folder_nobody_loaded_is_not_applied_and_the_mismatch_is_said_and_audited(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    feed = _feed(tmp_path)
    folder = _profile(tmp_path / "p")
    cfg = _cfg(tmp_path, pg_cluster_url, "m", folder)
    v1 = load(folder)
    _set_state(folder, "IGRA", "verified", "1.1.0")  # dropped in, never loaded by a person
    for snap in ("2026-11-01", "2026-11-02"):
        run_ingest(cfg, "csv", str(feed), snapshot=snap, load_fhir=False, validate=False)
        nd = snapshot_dir(tmp_path / "lake-m", snap)
        rec = json.loads((nd / sp.RECORD).read_text(encoding="utf-8"))
        assert rec["profile"] == v1.stamp()  # the version a person loaded
        assert rec["note"]["pending"]["digest"] == load(folder).digest[:12]
    events = [
        json.loads(x) for f in _day_files(tmp_path / "audit-m") for x in f.read_text(encoding="utf-8").splitlines()
    ]
    assert sum(1 for e in events if e["event"] == sp.NOT_LOADED) == 1  # said every night, audited once
    assert [e["actor"] for e in events if e["event"] == sp.EVENT] == ["steward-t"]
    done = [e for e in events if e["event"] == "ingest.done"][-1]
    assert done["detail"]["site_profile"]["pending"] == load(folder).digest[:12]
    # a folder on a box where nobody ever loaded one is not applied: the night stops (D-1233, point 4)
    other = _cfg(tmp_path, pg_cluster_url, "n", _profile(tmp_path / "q"), loaded=False)
    with pytest.raises(ProfileError, match="no person has loaded it"):
        run_ingest(other, "csv", str(feed), snapshot=NIGHT, load_fhir=False, validate=False)


def test_8_a_result_in_a_unit_its_row_does_not_give_is_a_problem_line(tmp_path: Path, pg_cluster_url: str) -> None:
    feed = _feed(tmp_path)
    lab = _rewrite_lab(feed, lambda i, r: {**r, "unit": "umol/L"} if r["local_code"] == "CRE" and i % 2 else r)
    n = sum(1 for r in lab if r["unit"] == "umol/L")
    folder = _profile(tmp_path / "p")
    run_ingest(_cfg(tmp_path, pg_cluster_url, "u", folder), "csv", str(feed), snapshot=NIGHT, load_fhir=False,
               validate=False)  # fmt: skip
    nd = snapshot_dir(tmp_path / "lake-u", NIGHT)
    cov = json.loads((nd / sp.RECORD).read_text(encoding="utf-8"))["coverage"]
    assert cov["units_not_read"] == {"lab": {"codes": 1, "rows": n}} and n > 100
    assert any(line.startswith("problem: lab:") for line in sp.lines(cov))
    rows = sp.worklist(load(folder), nd)
    assert [(r["kind"], r["code"], r["rows"]) for r in rows if r["kind"] == "unit"] == [("unit", "CRE", str(n))]
    obs = [json.loads(x) for x in (nd / "Observation.ndjson").read_text(encoding="utf-8").splitlines()]
    cre = [o for o in obs if any(c.get("code") == "2160-0" for c in o["code"]["coding"])]
    assert len(cre) == 300 and sum(1 for o in cre if "valueQuantity" not in o) >= n  # kept, never converted


def test_minor_a_table_that_is_not_utf8_is_refused_with_its_line(tmp_path: Path) -> None:
    f = _profile(tmp_path / "p")
    data = (f / "codes/lab.csv").read_bytes()
    (f / "codes/lab.csv").write_bytes(
        data + "ZZ,loinc,2160-0,クレ,mg/dL,1,laboratory,quantity,,,verify,\n".encode("cp932")
    )
    e = _refused(f)
    assert e.where == f"codes/lab.csv:{data.count(b'\n') + 1}" and "not UTF-8" in e.why


def test_minor_a_header_with_blanks_around_a_name_reads(tmp_path: Path) -> None:
    f = _profile(tmp_path / "p")
    text = (f / "codes/lab.csv").read_text(encoding="utf-8")
    (f / "codes/lab.csv").write_text(text.replace("local_code,", " local_code ,", 1), encoding="utf-8")
    assert load(f).tables["lab"].rows["UA"].target == "3084-1"


# ------------------------------------------------------------------------- the lane lead's re-probe of a63d3582
@pytest.mark.parametrize("spelling", ["LOINC", "Loinc", "loinc"])
def test_r1_a_system_name_in_any_case_is_kept_in_the_one_spelling_the_mapping_reads(
    tmp_path: Path, pg_cluster_url: str, spelling: str
) -> None:
    folder = _profile(tmp_path / "p")
    text = (folder / "codes/lab.csv").read_text(encoding="utf-8")
    (folder / "codes/lab.csv").write_text(text.replace("HBA1C,loinc,", f"HBA1C,{spelling},"), encoding="utf-8")
    assert load(folder).tables["lab"].rows["HBA1C"].row["system"] == "loinc"
    run_ingest(_cfg(tmp_path, pg_cluster_url, "s", folder), "csv", str(_feed(tmp_path)), snapshot=NIGHT,
               load_fhir=False, validate=False)  # fmt: skip
    nd = snapshot_dir(tmp_path / "lake-s", NIGHT)
    codes = [c.get("code") for x in (nd / "Observation.ndjson").read_text(encoding="utf-8").splitlines()
             for c in json.loads(x)["code"]["coding"]]  # fmt: skip
    assert codes.count("4548-4") == 465


@pytest.mark.parametrize(("system", "code"), [("SCORE", "TJC28"), ("Score", "TJC28")])
def test_r1_other_systems_are_kept_in_one_spelling_too(tmp_path: Path, system: str, code: str) -> None:
    folder = _profile(tmp_path / "p")
    text = (folder / "codes/lab.csv").read_text(encoding="utf-8")
    (folder / "codes/lab.csv").write_text(text.replace(f"{code},score,", f"{code},{system},"), encoding="utf-8")
    assert load(folder).tables["lab"].rows[code].row["system"] == "score"


@pytest.mark.parametrize("damage", ["edit", "truncate", "garbage"])
def test_r2_a_kept_copy_changed_after_the_load_stops_the_night_and_is_audited(
    tmp_path: Path, pg_cluster_url: str, damage: str
) -> None:
    folder = _profile(tmp_path / "p")
    cfg = _cfg(tmp_path, pg_cluster_url, "k", folder)
    copy = tmp_path / "lake-k" / sp.KEPT / f"{load(folder).digest}.json"
    text = copy.read_text(encoding="utf-8")
    if damage == "edit":  # still valid JSON, still valid codes: UA made another LOINC
        doc = json.loads(text)
        for r in doc["tables"]["lab"]["rows"]:
            if r["row"]["local_code"] == "UA":
                r["row"]["code"] = "2160-0"
        copy.write_text(json.dumps(doc), encoding="utf-8")
    elif damage == "truncate":
        copy.write_text(text[: len(text) // 2], encoding="utf-8")
    else:
        copy.write_bytes(b"\xff\xfe not json")
    with pytest.raises(ProfileError, match="kept copy"):
        run_ingest(cfg, "csv", str(_feed(tmp_path)), snapshot=NIGHT, load_fhir=False, validate=False)
    events = [
        json.loads(x) for f in _day_files(tmp_path / "audit-k") for x in f.read_text(encoding="utf-8").splitlines()
    ]
    assert [e["event"] for e in events if e["event"] == sp.COPY_REFUSED] == [sp.COPY_REFUSED]
    assert not snapshot_dir(tmp_path / "lake-k", NIGHT).joinpath("Observation.ndjson").exists()


def test_r2_a_kept_copy_whose_code_is_no_longer_a_code_is_refused(tmp_path: Path) -> None:
    folder = _profile(tmp_path / "p")
    lake, audit = tmp_path / "lake", tmp_path / "audit"
    sp.activate(load(folder), lake, site_id="T", by="s", audit_dir=audit)
    copy = lake / sp.KEPT / f"{load(folder).digest}.json"
    doc = json.loads(copy.read_text(encoding="utf-8"))
    doc["tables"]["lab"]["rows"][0]["row"]["code"] = "NOT A CODE"
    doc["copy_sha"] = __import__("tb_common.site_profile", fromlist=["content_sha"]).content_sha(doc)
    copy.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProfileError, match="kept copy"):  # its hash is not the one the load recorded, either way
        sp.kept(lake, load(folder).digest, sp.read_record(lake)["active"]["copy_sha"])
    with pytest.raises(ProfileError, match="is not a loinc code"):  # and its rows are checked again
        Profile.from_json(doc, lake)


@pytest.mark.parametrize(("system", "code", "ok"), [("loinc", "03084-1", False), ("loinc", "3084-1", True),
                                                    ("icd10", "U07.1", True), ("icd10", "U09.9", True),
                                                    ("icd10", "E11.9", True), ("icd10", "11.9", False)])  # fmt: skip
def test_r3_loinc_has_no_leading_zero_and_icd10_has_u_codes(system: str, code: str, ok: bool) -> None:
    assert (check_code(system, code) is None) is ok
