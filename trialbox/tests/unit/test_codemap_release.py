"""The code-map registry and its releases (T-316b, WS-09.1, D-419; CR-031 code-map part).

The registry is built here, in each test's own folder, from synthetic local codes and a few public LOINC and
ICD-10-CM codes; nothing is shipped. The two boxes are two OMOP schemas with two site blocks (a synthetic TW site and
a synthetic JP site) in the test PostgreSQL."""

from __future__ import annotations

import csv
import json
import os
import shutil
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from tb_common import crypto, refdata

from tools import codemap_release as cm

TW_LAB = "urn:trialbox:synthetic:tw-lab"
JP_LAB = "urn:trialbox:synthetic:jp-lab"
SHARED = "urn:trialbox:codemap:shared"
LOINC = "http://loinc.org"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
DAY = date(2026, 11, 11)
REGISTER = {"loinc": "cleared", "icd10cm": "cleared", "snomed-ct": "removed", "atc": "permission-to-ask",
            "icd10-who": "site-loaded"}  # fmt: skip

MAP_TW = [
    (TW_LAB, "TWL-001", "Synthetic serum creatinine", LOINC, "2160-0", "Creatinine [Mass/volume] in Serum or Plasma",
     "equivalent"),
    (TW_LAB, "TWL-002", "Synthetic HbA1c", LOINC, "4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "equivalent"),
    (TW_LAB, "TWL-003", "Synthetic frailty score", SHARED, "frailty-5", "", "equivalent"),
    (TW_LAB, "TWL-099", "Synthetic retired panel", LOINC, "", "", "unmatched"),
]  # fmt: skip
MAP_JP = [
    (JP_LAB, "JPL-101", "Synthetic creatinine (JP)", LOINC, "2160-0", "", "equivalent"),
    (JP_LAB, "JPL-102", "Synthetic frailty (JP)", SHARED, "frailty-5", "", "wider"),
    (JP_LAB, "JPL-103", "Synthetic gout code (JP)", ICD10CM, "M10.9", "Gout, unspecified", "equivalent"),
]  # fmt: skip


def _write_csv(path: Path, cols: tuple[str, ...], rows: list[tuple[Any, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def make_registry(root: Path, *, concepts: list[tuple[Any, ...]] | None = None,
                  maps: dict[str, list[tuple[Any, ...]]] | None = None, meta: dict[str, Any] | None = None) -> Path:  # fmt: skip
    m = {
        "format": cm.FORMAT,
        "name": "synthetic-consortium",
        "url": "https://registry.example.invalid/codemap.git",
        "ranges": [{"owner": "consortium", "first": 2_005_000_000, "last": 2_005_099_999},
                   {"owner": "site-tw", "first": 2_005_100_000, "last": 2_005_199_999},
                   {"owner": "site-jp", "first": 2_005_200_000, "last": 2_005_299_999}],
        "systems": [{"system": SHARED, "owner": "consortium", "kind": "shared"},
                    {"system": TW_LAB, "owner": "site-tw", "kind": "local"},
                    {"system": JP_LAB, "owner": "site-jp", "kind": "local"}],
        "maps": [{"id": "tw-lab", "name": "Synthetic TW lab codes", "owner": "site-tw"},
                 {"id": "jp-lab", "name": "Synthetic JP lab codes", "owner": "site-jp"}],
    }  # fmt: skip
    m.update(meta or {})
    root.mkdir(parents=True, exist_ok=True)
    (root / "registry.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    _write_csv(root / "concepts.csv", cm.CONCEPT_COLS, concepts if concepts is not None else [
        (2_005_000_001, SHARED, "frailty-5", "Synthetic five-item frailty score", "Measurement", "consortium"),
        (2_005_100_001, SHARED, "tw-pain-0-10", "Synthetic pain scale (TW)", "Measurement", "site-tw"),
    ])  # fmt: skip
    for mid, rows in (maps if maps is not None else {"tw-lab": MAP_TW, "jp-lab": MAP_JP}).items():
        _write_csv(root / "maps" / f"{mid}.csv", cm.MAP_COLS, rows)
    return root


def _release(reg_root: Path, out: Path, version: str = "2026.1", key: bytes | None = None, **kw: Any) -> Path:
    return cm.build_release(cm.read_registry(reg_root), version=version, author="steward-a", approver="steward-b",
                            out=out, private_key=key, register=REGISTER, today=DAY, **kw)  # fmt: skip


# ------------------------------------------------------------------------------------------------ the registry
def test_a_good_registry_has_no_problem(tmp_path: Path) -> None:
    assert cm.check(cm.read_registry(make_registry(tmp_path / "reg")), REGISTER) == []


def test_the_repository_licence_register_lets_loinc_and_icd10cm_ship(tmp_path: Path) -> None:
    """The real register (docs/licences/register.csv) is what a release is held against by default."""
    assert cm.check(cm.read_registry(make_registry(tmp_path / "reg"))) == []


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({"concepts": [(1_999_999_999, SHARED, "x", "x", "Measurement", "consortium")]}, "not in a range"),
        ({"concepts": [(2_005_100_005, SHARED, "x", "x", "Measurement", "consortium")]}, "not in a range of its owner"),
        ({"concepts": [(2_005_000_001, SHARED, "a", "a", "Measurement", "consortium"),
                       (2_005_000_001, SHARED, "b", "b", "Measurement", "consortium")]}, "twice"),
        ({"concepts": [(2_005_000_001, TW_LAB, "a", "a", "Measurement", "consortium")]}, "not one of the registry's shared"),
        ({"meta": {"ranges": [{"owner": "consortium", "first": 2_004_999_000, "last": 2_005_000_100}]}},
         "not inside the registry band"),
        ({"meta": {"ranges": [{"owner": "consortium", "first": 2_005_000_000, "last": 2_005_099_999},
                              {"owner": "site-tw", "first": 2_005_050_000, "last": 2_005_199_999}]}}, "overlaps"),
        ({"maps": {"tw-lab": [(TW_LAB, "T1", "", LOINC, "2160-0", "", "same-ish")], "jp-lab": MAP_JP}}, "relation"),
        ({"maps": {"tw-lab": [(TW_LAB, "T1", "", SHARED, "no-such", "", "equivalent")], "jp-lab": MAP_JP}},
         "not a concept in concepts.csv"),
        ({"maps": {"tw-lab": MAP_TW, "jp-lab": [(TW_LAB, "T9", "", LOINC, "2160-0", "", "equivalent")]}},
         "already mapped by"),
        ({"maps": {"tw-lab": MAP_TW}}, "no file maps/jp-lab.csv"),
        ({"maps": {"tw-lab": [(TW_LAB, "T1", "", LOINC, "", "", "equivalent")], "jp-lab": MAP_JP}}, "needs a target"),
    ],
)  # fmt: skip
def test_a_registry_that_breaks_a_rule_is_refused(tmp_path: Path, change: dict[str, Any], want: str) -> None:
    reg = cm.read_registry(make_registry(tmp_path / "reg", **change))
    problems = cm.check(reg, REGISTER)
    assert any(want in p for p in problems), problems
    with pytest.raises(cm.CodemapError):
        cm.build_release(reg, version="2026.1", author="a", approver="b", out=tmp_path / "out", register=REGISTER)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("system", "code", "want"),
    [
        ("http://snomed.info/sct", "73211009", "snomed-ct is removed"),  # SNOMED CT: removed (D-342)
        ("http://www.whocc.no/atc", "A10BA02", "atc is permission-to-ask"),
        ("http://hl7.org/fhir/sid/icd-10", "E11", "icd10-who is site-loaded"),
        ("urn:example:unknown", "X", "no row in the licence register"),
    ],
)
def test_a_code_system_the_licence_register_does_not_let_ship_is_refused(
    tmp_path: Path, system: str, code: str, want: str
) -> None:
    maps = {"tw-lab": [*MAP_TW, (TW_LAB, "TWL-050", "", system, code, "", "equivalent")], "jp-lab": MAP_JP}
    problems = cm.check(cm.read_registry(make_registry(tmp_path / "reg", maps=maps)), REGISTER)
    assert any(want in p for p in problems), problems


def test_author_and_approver_are_two_people_and_a_version_is_released_once(tmp_path: Path) -> None:
    reg = cm.read_registry(make_registry(tmp_path / "reg"))
    with pytest.raises(cm.CodemapError, match="not its author"):
        cm.build_release(reg, version="2026.1", author="Steward-A", approver="steward-a ", out=tmp_path / "o",
                         register=REGISTER)  # fmt: skip
    _release(tmp_path / "reg", tmp_path / "out", record=True)
    assert (tmp_path / "reg" / "releases" / "2026.1.json").is_file()
    with pytest.raises(cm.CodemapError, match="released before"):
        _release(tmp_path / "reg", tmp_path / "out2")


def test_a_released_id_is_never_renumbered_nor_reused(tmp_path: Path) -> None:
    root = make_registry(tmp_path / "reg")
    _release(root, tmp_path / "out", record=True)
    make_registry(root, concepts=[  # frailty-5 moved; its old id given to another code
        (2_005_000_002, SHARED, "frailty-5", "Synthetic five-item frailty score", "Measurement", "consortium"),
        (2_005_000_001, SHARED, "new-score", "Synthetic new score", "Measurement", "consortium"),
        (2_005_100_001, SHARED, "tw-pain-0-10", "Synthetic pain scale (TW)", "Measurement", "site-tw"),
    ])  # fmt: skip
    problems = cm.check(cm.read_registry(root), REGISTER)
    assert any("never renumbered" in p for p in problems), problems
    assert any("never reused" in p for p in problems), problems


# ------------------------------------------------------------------------------------------------ the release
def test_a_release_is_a_refdata_pack_part_with_its_record(tmp_path: Path) -> None:
    priv, pub = crypto.ed25519_generate()
    pack = _release(make_registry(tmp_path / "reg"), tmp_path / "out", key=priv)
    assert pack.name == "trialbox-refdata-20261111-codemap-2026-1"
    m = refdata.verify(pack)  # the pack format's own check (D-140, D-170)
    assert [s["id"] for s in m["sources"]] == ["codemap-jp-lab", "codemap-tw-lab"]
    assert {s["kind"] for s in m["sources"]} == {"map"} and {s["version"] for s in m["sources"]} == {"2026.1"}
    tw = next(s for s in m["sources"] if s["id"] == "codemap-tw-lab")
    assert "register:loinc" in tw["terms"] and "steward-b" in tw["attribution"]
    rel = cm.read_release(pack, pub)
    assert rel.signed and rel.record["author"] == "steward-a" and rel.record["approver"] == "steward-b"
    assert rel.record["licences"] == {ICD10CM: "register:icd10cm", JP_LAB: "registry:site-jp", LOINC: "register:loinc",
                                      SHARED: "registry:consortium", TW_LAB: "registry:site-tw"}  # fmt: skip
    frail = next(r for r in rel.maps["tw-lab"] if r["source_code"] == "TWL-003")
    assert frail["target_display"] == "Synthetic five-item frailty score"  # a shared target takes its concept's name
    # the tar the update bundle carries reads the same
    tar = refdata.pack_tar(pack, tmp_path / f"{pack.name}.tar")
    assert cm.read_release(tar, pub).record == rel.record
    # the refdata store reads the maps as any pack's (the part goes through the update bundle unchanged)
    with refdata.opened(tar) as d:
        rows = list(refdata.rows(d, "codemap-tw-lab/map.jsonl.gz"))
    assert len(rows) == len(MAP_TW)


def _rewrite_gz(path: Path, change: Any) -> None:
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as fh:
        recs = [json.loads(line) for line in fh if line.strip()]
    change(recs)
    refdata.write_jsonl_gz(path, recs)


def test_a_tampered_release_is_refused(tmp_path: Path) -> None:
    priv, pub = crypto.ed25519_generate()
    good = _release(make_registry(tmp_path / "reg"), tmp_path / "out", key=priv)

    def fresh(name: str) -> Path:
        d = tmp_path / name / good.name
        shutil.copytree(good, d)
        return d

    def retarget(recs: list[dict[str, Any]]) -> None:
        recs[0]["target_code"] = "2345-7"

    # a map file changed: its sha256 no longer matches the manifest
    p = fresh("a")
    _rewrite_gz(p / "codemap-tw-lab/map.jsonl.gz", retarget)
    with pytest.raises(cm.CodemapError, match="does not verify"):
        cm.read_release(p)
    # the map file and the manifest changed together: the release record still holds the old sha256
    p = fresh("b")
    _rewrite_gz(p / "codemap-tw-lab/map.jsonl.gz", retarget)
    man = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
    src = next(s for s in man["sources"] if s["id"] == "codemap-tw-lab")
    src["files"] = [refdata.file_entry(p, "codemap-tw-lab/map.jsonl.gz", len(MAP_TW))]
    (p / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    refdata.verify(p)  # the pack alone looks whole
    with pytest.raises(cm.CodemapError, match="differs from the release record"):
        cm.read_release(p)
    # ... and the record changed too: the signature no longer verifies
    rec = json.loads((p / cm.RELEASE_FILE).read_text(encoding="utf-8"))
    tw = next(x for x in rec["maps"] if x["id"] == "tw-lab")
    tw["sha256"] = src["files"][0]["sha256"]
    rec["content_sha256"] = cm._content_sha(rec["concepts"]["sha256"], rec["maps"], rec["version"])
    (p / cm.RELEASE_FILE).write_text(json.dumps(rec), encoding="utf-8")
    assert cm.read_release(p).record["maps"]  # unsigned reading: consistent
    with pytest.raises(cm.CodemapError, match="signature does not verify"):
        cm.read_release(p, pub)
    # a concept moved in the concepts file
    p = fresh("c")

    def move(recs: list[dict[str, Any]]) -> None:
        recs[0]["concept_id"] = 2_005_000_009

    _rewrite_gz(p / cm.CONCEPTS_FILE, move)
    with pytest.raises(cm.CodemapError, match="differs from the release record"):
        cm.read_release(p)
    # a box that requires a signature refuses an unsigned release, and another key
    p = fresh("d")
    (p / cm.SIGNATURE_FILE).unlink()
    with pytest.raises(cm.CodemapError, match="not signed"):
        cm.read_release(p, pub)
    _, other = crypto.ed25519_generate()
    with pytest.raises(cm.CodemapError, match="signature does not verify"):
        cm.read_release(good, other)


def test_the_command_checks_releases_and_verifies(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(cm, "register_status", lambda path=cm.REGISTER: REGISTER)
    root = make_registry(tmp_path / "reg")
    assert cm.main(["check", str(root)]) == 0
    priv, pub = crypto.ed25519_generate()
    (tmp_path / "k.pem").write_bytes(priv)
    (tmp_path / "k.pub").write_bytes(pub)
    assert cm.main(["release", str(root), "--version", "2026.1", "--author", "a", "--approver", "b", "--out",
                    str(tmp_path / "out"), "--key", str(tmp_path / "k.pem"), "--tar", "--record"]) == 0  # fmt: skip
    tar = next((tmp_path / "out").glob("*.tar"))
    assert cm.main(["verify", str(tar), "--public-key", str(tmp_path / "k.pub")]) == 0
    assert '"signed": true' in capsys.readouterr().out
    assert cm.main(["release", str(root), "--version", "2026.2", "--author", "a", "--approver", "A", "--out",
                    str(tmp_path / "out")]) == 1  # fmt: skip
    assert "not its author" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ two boxes
@pytest.fixture
def boxes(pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Two synthetic boxes: a TW site (first block) and a JP site (the next block), each its own OMOP schema."""
    from omop import schema

    monkeypatch.delenv("TB_OMOP_DB_URL", raising=False)
    sep = "&" if "?" in pg_cluster_url else "?"
    out: dict[str, Any] = {}
    for site, block in (("tw", 2_100_000_000), ("jp", 2_101_000_000)):
        monkeypatch.setenv("TB_OMOP_CONCEPT_BLOCK", str(block))
        out[site] = schema.connect(f"{pg_cluster_url}{sep}tb_prefix=t{os.getpid()}cm{site}{id(out) % 10_000}_")
    yield out
    for db in out.values():
        db.close()


def _map_targets(db: Any) -> list[tuple[str, ...]]:
    return [tuple(map(str, r)) for r in db.fetchall(
        "SELECT r.source_code, r.relation, c.vocabulary_id, c.concept_code FROM tb_map_relation r JOIN concept c ON "
        "c.concept_id = r.target_concept_id WHERE r.map_release LIKE 'map:codemap-%' ORDER BY 1")]  # fmt: skip


def test_a_release_loads_on_both_boxes_and_vocab_release_names_it(boxes: dict[str, Any], tmp_path: Path) -> None:
    from omop import vocab

    priv, pub = crypto.ed25519_generate()
    root = make_registry(tmp_path / "reg")
    tar = refdata.pack_tar(p := _release(root, tmp_path / "out", key=priv, record=True), tmp_path / f"{p.name}.tar")
    for db in boxes.values():
        assert vocab.release(db)["codemap"] is None
        res = cm.load(db, tar, public_key=pub, by="steward-tw")
        assert res["new"] and res["signed"] and set(res["maps"]) == {"tw-lab", "jp-lab"}
    names = {site: vocab.release(db) for site, db in boxes.items()}
    for site, r in names.items():
        c = r["codemap"]
        assert c["name"] == "synthetic-consortium 2026.1" and c["version"] == "2026.1", site
        assert set(c["maps"]) == {"tw-lab", "jp-lab"} and c["maps"]["tw-lab"]["version"] == "2026.1"
    assert names["tw"]["codemap"]["sha256"] == names["jp"]["codemap"]["sha256"]
    # the shared concepts sit at the same ids on both boxes; the maps reach the same targets
    shared = (
        "SELECT concept_id, concept_code, standard_concept FROM concept WHERE concept_id BETWEEN ? AND ? ORDER BY 1"
    )
    tw_shared = boxes["tw"].fetchall(shared, (vocab.CODEMAP_MIN, vocab.CODEMAP_MAX))
    assert [tuple(r) for r in tw_shared] == [(2_005_000_001, "frailty-5", None), (2_005_100_001, "tw-pain-0-10", None)]
    assert tw_shared == boxes["jp"].fetchall(shared, (vocab.CODEMAP_MIN, vocab.CODEMAP_MAX))
    assert _map_targets(boxes["tw"]) == _map_targets(boxes["jp"])
    frail = boxes["tw"].fetchval("SELECT r.target_concept_id FROM tb_map_relation r WHERE r.source_code = 'TWL-003'")
    assert frail == 2_005_000_001
    assert boxes["jp"].fetchval("SELECT count(*) FROM source_to_concept_map WHERE target_concept_id = 2005000001") == 2
    # loading it again changes nothing
    before = boxes["tw"].fetchall("SELECT release_name, sha256, active, loaded_at FROM tb_vocab_release ORDER BY 1, 2")
    again = cm.load(boxes["tw"], tar, public_key=pub)
    assert not again["new"] and not any(m["new"] for m in again["maps"].values())
    assert boxes["tw"].fetchall("SELECT release_name, sha256, active, loaded_at FROM tb_vocab_release "
                                "ORDER BY 1, 2") == before  # fmt: skip


def test_a_new_release_replaces_the_old_and_a_refused_one_changes_nothing(
    boxes: dict[str, Any], tmp_path: Path
) -> None:
    from omop import vocab

    db = boxes["tw"]
    root = make_registry(tmp_path / "reg")
    cm.load(db, _release(root, tmp_path / "out1", record=True))
    # release 2026.2 drops the JP map and remaps one TW code
    tw2 = [r if r[1] != "TWL-002" else (TW_LAB, "TWL-002", "Synthetic HbA1c", LOINC, "17856-6", "", "equivalent")
           for r in MAP_TW]  # fmt: skip
    shutil.rmtree(root / "maps")
    make_registry(root, maps={"tw-lab": tw2}, meta={"maps": [{"id": "tw-lab", "name": "TW", "owner": "site-tw"}]})
    p2 = _release(root, tmp_path / "out2", version="2026.2", record=True)
    res = cm.load(db, p2)
    assert res["removed"] == ["jp-lab"]
    r = vocab.release(db)["codemap"]
    assert r["version"] == "2026.2" and set(r["maps"]) == {"tw-lab"}
    assert ("TWL-002", "equivalent", "LOINC", "17856-6") in _map_targets(db)
    assert not [t for t in _map_targets(db) if t[0].startswith("JPL-")]
    assert db.fetchval("SELECT count(*) FROM tb_vocab_release WHERE release_name = ? AND active", (vocab.CODEMAP,)) == 1
    # a release whose concept id is held on this box by another code is refused whole: nothing changes
    db.execute("UPDATE concept SET concept_code = 'held-by-other' WHERE concept_id = 2005100001")
    before = (db.fetchall("SELECT * FROM tb_vocab_release ORDER BY 1, 2"), _map_targets(db))
    make_registry(root, maps={"tw-lab": MAP_TW}, meta={"maps": [{"id": "tw-lab", "name": "TW", "owner": "site-tw"}]})
    p3 = _release(root, tmp_path / "out3", version="2026.3")
    with pytest.raises(Exception, match="holds"):
        cm.load(db, p3)
    assert (db.fetchall("SELECT * FROM tb_vocab_release ORDER BY 1, 2"), _map_targets(db)) == before
    assert vocab.release(db)["codemap"]["version"] == "2026.2"
