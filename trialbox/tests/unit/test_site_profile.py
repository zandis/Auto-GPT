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
from adapter.mapping.engine import Mapping, MappingError
from adapter.ndjson import snapshot_dir
from adapter.pipeline import AdapterConfig, make_source, run_ingest
from tb_common.audit import _day_files
from tb_common.site_profile import SHIPPED_ROOT, VERIFIED, VERIFY, ProfileError, load, state_of
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "services/adapter/mapping/profile"
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
LAB = SHIPPED_ROOT / "tw_core/lab_local_to_loinc.csv"
NIGHT = "2026-11-01"
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
            },  # fmt: skip
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
        ("UA,loinc,3084-1,x,mg/dL,1,laboratory,quantity,,,verify,", "already on line 2"),
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
    src: Any = make_source("ssmix2", str(tmp_path / "storage"), profile=load(tmp_path / "p"))
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


def test_changed_content_under_the_same_version_another_site_or_door_is_refused(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    sp.activate(load(_profile(tmp_path / "a")), lake, site_id="T", by="s")
    changed = load(_profile(tmp_path / "b", rename={"UA": "K-0001"}))
    with pytest.raises(ProfileError, match="give the changed profile a new version"):
        sp.activate(changed, lake, site_id="T", by="s")
    with pytest.raises(ProfileError, match="for site 'T', not 'U'"):
        sp.activate(changed, lake, site_id="U", by="s")
    with pytest.raises(ProfileError, match="describes a csv source; the box reads ssmix2"):
        sp.activate(load(_profile(tmp_path / "c", _manifest(version="2.0.0"))), lake, site_id="T", by="s",
                    door="ssmix2")  # fmt: skip


# ---------------------------------------------------------------------------------------- coverage and work list
def _night_files(d: Path) -> Path:
    d.mkdir(parents=True)
    (d / "completeness.json").write_text(json.dumps({"tables": {"patient": {"rows": 40}, "lab": {"rows": 300},
                                                                 "vital": {"rows": 0}, "extra": {"rows": 5}}}))  # fmt: skip
    (d / "unmapped_codes.json").write_text(json.dumps({"lab": {"lab": {"=CMD()": 3, "X9": 1}}}))
    return d


def test_coverage_lines_count_types_unmapped_codes_and_verify_rows(tmp_path: Path) -> None:
    p = load(_profile(tmp_path / "p", _manifest(data_types=["patient", "lab", "vital", "note"])))
    cov = sp.coverage(p, _night_files(tmp_path / "night"))
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


# --------------------------------------------------------------------------------- a night and the plan's proof
class _Rebuild:
    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)


def _cfg(tmp: Path, url: str, tag: str, profile: Path | None) -> AdapterConfig:
    sec = tmp / f"secrets-{tag}"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    sep = "&" if "?" in url else "?"
    return AdapterConfig(lake_dir=tmp / f"lake-{tag}", secrets_dir=sec, mapping_path=MAPPING, site_id="T",
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
    assert (said["id"], said["version"], said["digest"]) == ("test-site", "1.0.0", stamp["digest"])  # type: ignore[index]
    assert said["types_arrived"] == len(TABLES) and said["unmapped_rows"] == 0
    assert [e["actor"] for e in done if e["event"] == sp.EVENT] == ["adapter"]


def test_the_shipped_profile_reads_the_night_byte_for_byte_as_without_one(tmp_path: Path, pg_cluster_url: str) -> None:
    """No behaviour change: the synthetic Taiwan profile names the very table the mapping reads."""
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
        assert (nda / n).read_bytes() == (ndb / n).read_bytes(), n


def test_a_refused_profile_ends_the_night_before_anything_is_read(tmp_path: Path, pg_cluster_url: str) -> None:
    folder = _profile(tmp_path / "p")
    (folder / "codes/lab.csv").write_text("local_code,code,verified\nUA,3084-1,perhaps\n", encoding="utf-8")
    feed = tmp_path / "feed"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    with pytest.raises(ProfileError, match="codes/lab.csv:2"):
        run_ingest(_cfg(tmp_path, pg_cluster_url, "x", folder), "csv", str(feed), snapshot=NIGHT, load_fhir=False,
                   validate=False)  # fmt: skip
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
