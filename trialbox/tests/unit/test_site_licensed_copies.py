"""V-18 (D-1182): SNOMED CT, the UMLS and the ATC/DDD index from the hospital's own licensed copy, in the format its
publisher ships, verified by its own manifest or checksum, after a named person accepted the licence (D-1114).

Every file here is synthetic, written by the test into a temporary folder: no release, code or name of the real
systems is committed (the licences forbid it; ``licence_register.snomed_problems``)."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from criteria_compiler.terminology import installed as inst

PERSON = "Synthetic Person"
FSN, SYN, ISA = inst.SNOMED_FSN, "900000000000013009", inst.SNOMED_IS_A
DAY = "20990131"


def _tsv(*rows: tuple[str, ...]) -> str:
    return "".join("\t".join(r) + "\n" for r in rows)


def rf2(root: Path) -> Path:
    """A synthetic RF2 Snapshot: three active concepts (one retired), their FSNs, two is-a links."""
    t = root / "SynRF2" / "Snapshot" / "Terminology"
    t.mkdir(parents=True)
    (t / f"sct2_Concept_Snapshot_INT_{DAY}.txt").write_text(_tsv(
        ("id", "effectiveTime", "active", "moduleId", "definitionStatusId"),
        ("1000001", DAY, "1", "9", "9"), ("1000002", DAY, "1", "9", "9"), ("1000003", DAY, "1", "9", "9"),
        ("1000004", DAY, "0", "9", "9"),
    ), encoding="utf-8")  # fmt: skip
    head = ("id", "effectiveTime", "active", "moduleId", "conceptId", "languageCode", "typeId", "term", "caseSig")
    (t / f"sct2_Description_Snapshot-en_INT_{DAY}.txt").write_text(_tsv(
        head, ("1", DAY, "1", "9", "1000001", "en", FSN, "Synthetic root (finding)", "x"),
        ("2", DAY, "1", "9", "1000002", "en", FSN, "Synthetic child (finding)", "x"),
        ("3", DAY, "1", "9", "1000002", "en", SYN, "a synonym, not the FSN", "x"),
        ("4", DAY, "1", "9", "1000003", "en", FSN, "Synthetic grandchild (finding)", "x"),
    ), encoding="utf-8")  # fmt: skip
    rhead = ("id", "effectiveTime", "active", "moduleId", "sourceId", "destinationId", "relationshipGroup", "typeId",
             "characteristicTypeId", "modifierId")  # fmt: skip
    (t / f"sct2_Relationship_Snapshot_INT_{DAY}.txt").write_text(_tsv(
        rhead, ("11", DAY, "1", "9", "1000002", "1000001", "0", ISA, "9", "9"),
        ("12", DAY, "1", "9", "1000003", "1000002", "0", ISA, "9", "9"),
        ("13", DAY, "0", "9", "1000003", "1000001", "0", ISA, "9", "9"),
    ), encoding="utf-8")  # fmt: skip
    return root / "SynRF2"


def rrf(root: Path, manifest: bool = True) -> Path:
    """A synthetic MetamorphoSys subset: two concepts from one invented source, one PAR link, its MRFILES."""
    meta = root / "META"
    meta.mkdir(parents=True)
    conso = ("C9000001|ENG|P|L1|PF|S1|Y|A1|||SY01|SYNSRC|PT|SY01|Synthetic parent concept|0|N||\n"
             "C9000001|ENG|S|L2|VO|S2|N|A2|||SY01|SYNSRC|SY|SY01|another name|0|N||\n"
             "C9000002|ENG|P|L3|PF|S3|Y|A3|||SY02|SYNSRC|PT|SY02|Synthetic child concept|0|N||\n"
             "C9000003|ENG|P|L4|PF|S4|Y|A4|||SY03|SYNSRC|PT|SY03|a suppressed name|0|O||\n")  # fmt: skip
    rel = "C9000002|A3|AUI|PAR|C9000001|A1|AUI||R1||SYNSRC|SYNSRC|||N||\n"
    (meta / "MRCONSO.RRF").write_text(conso, encoding="utf-8")
    (meta / "MRREL.RRF").write_text(rel, encoding="utf-8")
    if manifest:
        files = "".join(f"{n}|d|f|c|{t.count(chr(10))}|{len(t.encode())}|\n" for n, t in
                        (("MRCONSO.RRF", conso), ("MRREL.RRF", rel)))  # fmt: skip
        (meta / "MRFILES.RRF").write_text(files, encoding="utf-8")
    (meta / "release.dat").write_text("umls.release.name=2099AA\n", encoding="utf-8")
    return meta


def test_snomed_from_an_rf2_snapshot_folder(tmp_path: Path) -> None:
    got = inst.install_snomed(rf2(tmp_path), tmp_path / "t", PERSON, "2026-11-23")
    rows = {r["code"]: r for r in inst.read_table(tmp_path / "t", inst.SNOMED_CT) or []}
    assert got == {"snomed_ct": 3} and set(rows) == {"1000001", "1000002", "1000003"}  # the retired one is out
    assert rows["1000002"]["display"] == "Synthetic child (finding)" and rows["1000002"]["parents"] == "1000001"
    assert rows["1000003"]["parents"] == "1000002"  # the inactive is-a link is not read
    line = inst.manifest(tmp_path / "t")["tables"]["snomed_ct"]
    assert line["version"] == f"SNOMED CT {DAY}" and line["licence_accepted_by"] == PERSON
    assert line["verified"].startswith("its own headers only")


def test_snomed_is_verified_by_its_checksums_and_refused_when_one_differs(tmp_path: Path) -> None:
    rel = rf2(tmp_path)
    files = sorted(rel.rglob("*.txt"))
    (rel / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n"
                                            for f in files), encoding="utf-8")  # fmt: skip
    inst.install_snomed(rel, tmp_path / "t", PERSON)
    assert inst.manifest(tmp_path / "t")["tables"]["snomed_ct"]["verified"] == "SHA256SUMS: 3 files match"
    files[0].write_text(files[0].read_text("utf-8") + "1000009\t20990131\t1\t9\t9\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its sha256 in SHA256SUMS"):
        inst.install_snomed(rel, tmp_path / "t2", PERSON)


def test_snomed_from_the_release_zip_with_the_recorded_sha256(tmp_path: Path) -> None:
    rel = rf2(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in rel.rglob("*.txt"):
            z.write(f, str(f.relative_to(tmp_path)))
    archive = tmp_path / "SynRF2.zip"
    archive.write_bytes(buf.getvalue())
    sha = hashlib.sha256(buf.getvalue()).hexdigest()
    inst.install_snomed(archive, tmp_path / "t", PERSON, sha256=sha)
    assert inst.manifest(tmp_path / "t")["tables"]["snomed_ct"]["verified"] == "the sha256 the person recorded"
    with pytest.raises(ValueError, match="not the one recorded"):
        inst.install_snomed(archive, tmp_path / "t2", PERSON, sha256="0" * 64)


def test_a_licensed_copy_needs_a_named_person(tmp_path: Path) -> None:
    for who in ("", "yes", "admin"):
        with pytest.raises(ValueError, match="must name the person"):
            inst.install_snomed(rf2(tmp_path / who.replace("", "_")), tmp_path / "t", who)
    assert not (tmp_path / "t").exists()


def test_umls_from_a_metamorphosys_subset(tmp_path: Path) -> None:
    got = inst.install_umls(rrf(tmp_path), tmp_path / "t", PERSON)
    concepts = {r["code"]: r for r in inst.read_table(tmp_path / "t", inst.UMLS_CONCEPTS) or []}
    codes = inst.read_table(tmp_path / "t", inst.UMLS_CODES) or []
    assert got == {"umls_concepts": 2, "umls_codes": 2}  # the suppressed name is out
    assert concepts["C9000001"]["display"] == "Synthetic parent concept"  # the preferred English name
    assert concepts["C9000002"]["parents"] == "C9000001" and concepts["C9000002"]["sources"] == "SYNSRC"
    assert {(r["sab"], r["code"], r["cui"]) for r in codes} == {("SYNSRC", "SY01", "C9000001"),
                                                                ("SYNSRC", "SY02", "C9000002")}  # fmt: skip
    line = inst.manifest(tmp_path / "t")["tables"]["umls_concepts"]
    assert line["version"] == "UMLS 2099AA" and line["verified"] == "MRFILES.RRF: 2 files match"


def test_umls_refused_when_a_file_differs_from_its_mrfiles(tmp_path: Path) -> None:
    meta = rrf(tmp_path)
    (meta / "MRREL.RRF").write_text((meta / "MRREL.RRF").read_text("utf-8") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="MRREL.RRF does not match MRFILES.RRF"):
        inst.install_umls(meta, tmp_path / "t", PERSON)


def test_the_atc_ddd_index_as_an_excel_workbook(tmp_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in (("ATC code", "ATC level name", "DDD", "U"), ("V99", "synthetic group", None, None),
                ("V99SY01", "synthetic substance", 1, "g")):  # fmt: skip
        ws.append(row)
    book = tmp_path / "atc_ddd_index_2099.xlsx"
    wb.save(book)
    got = inst.install_atc_index(book, tmp_path / "t", PERSON, version="2099")
    rows = inst.read_table(tmp_path / "t", inst.ATC_INDEX) or []
    assert got == {"atc_index": 2} and {r["code"] for r in rows} == {"V99", "V99SY01"}


def test_the_hospitals_folder_loads_what_it_holds_and_says_what_it_lacks(tmp_path: Path) -> None:
    folder = tmp_path / "licensed"
    rf2(folder / "snomed")
    rrf(folder / "umls")
    (folder / "atc").mkdir()
    (folder / "atc" / "index.csv").write_text("ATC code,ATC level name\nV99SY01,synthetic substance\n", "utf-8")
    (folder / "atc" / "VERSION").write_text("2099\n", encoding="utf-8")
    nobody = inst.install_folder(folder, tmp_path / "t0")
    assert nobody["SNOMED CT"][0] == "missing" and "nobody named accepted" in nobody["SNOMED CT"][1]
    (folder / inst.ACCEPTANCE).write_text(json.dumps({"accepted_by": PERSON, "accepted_on": "2026-11-23",
                                                      "statement": "academic, non-commercial"}), "utf-8")  # fmt: skip
    got = inst.install_folder(folder, tmp_path / "t")
    assert {k: v[0] for k, v in got.items()} == {"SNOMED CT": "loaded", "UMLS": "loaded", "ATC": "loaded",
                                                  "LOINC": "missing", "WHO ICD-10": "missing"}  # fmt: skip
    assert got["LOINC"][1] == "no loinc/ in the hospital's folder"
    assert {t.name for t in inst.status(tmp_path / "t") if not t.problem} == {
        "snomed_ct", "umls_concepts", "umls_codes", "atc_index"}  # fmt: skip
