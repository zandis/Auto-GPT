"""The owner's three vocabulary rulings of 2026-11-19 (card 22-2/22-4 restored, replacing PR #1093).

The ruling, verbatim (integrator's comment on PR #639, issue comment 7001109992): "the SNOMED and CPT4 concept ids
stay as a named exception in the licence register; the 60 ICD-O-3 names are removed and their ids kept; the ICD-10
bridge file's notes are reworded so they carry no WHO wording."

The removed ICD-O-3 names and the bridge file's former notes are pinned here as sha256 prefixes of their case-folded
text, never as text, so this file does not bring the removed wording back into the repository.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools import catalogue_verify as cv
from tools import licence_register as lr
from tools import vocab_bundle_check as vbc

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT / "catalogue/verification/evidence.json",
    ROOT / "tests/fixtures/catalogue_verify/verification/evidence.json",
)
BRIDGE = ROOT / "libs/tb_common/refdata_src/icd10_who_cm_checked.csv"
RULING_DATE = "2026-11-19"
# what an entry concept of a licensed vocabulary may carry: its OMOP id, its vocabulary tag, the concept-set label of
# the OHDSI cohort (Apache-2.0), its domain and the set flags; never a code, name, description or synonym
ID_ONLY_KEYS = frozenset({"set", "concept_id", "vocabulary", "domain", "descendants", "excluded"})

# fmt: off
# ruling 2: the 60 ICD-O-3 concept ids of catalogue/verification/evidence.json, all kept
ICDO3_IDS = frozenset({
    36518315, 36518465, 36522002, 36522964, 36524507, 36524553, 36528383, 36529078,
    36529455, 36529793, 36532893, 36534051, 36534614, 36535150, 36536908, 36539611,
    36541062, 36541764, 36542645, 36546337, 36546447, 36547074, 36547484, 36548040,
    36549328, 36549710, 36550422, 36551689, 36552724, 36552772, 36553700, 36553857,
    36554231, 36555420, 36555551, 36555908, 36556262, 36556767, 36557132, 36557152,
    36558447, 36563434, 36565190, 36566260, 44499436, 44499501, 44500019, 44500059,
    44500060, 44500245, 44500353, 44500410, 44500411, 44500863, 44500874, 44501009,
    44501634, 44502529, 44502935, 44503086,
})
# ruling 2: (length, sha256 first 16 hex) of each removed ICD-O-3 name, case-folded
ICDO3_NAME_LEN_SHA = frozenset({
    (30, "c683d4788a5258ec"), (33, "5749a2fe40c2e407"), (35, "ed77dc3369934b37"), (36, "4db88436de90792b"),
    (38, "ffad8d4466565dbb"), (39, "adef34f95c5debb9"), (40, "3a0cd3e80fcec3a2"), (41, "853de55197022bb1"),
    (41, "cf0e695da4072de8"), (42, "34fd44361ded5098"), (44, "53929983d21974a0"), (44, "901a80e07371cfd8"),
    (45, "a377d89d04d4bdab"), (46, "46f97fcc55f4f592"), (47, "99381742388e49e2"), (47, "dd9e1b38181d151a"),
    (49, "54f2ed24e383f1ab"), (49, "6c32c805fa4b3dca"), (49, "a1e08bcb4baa2b8b"), (49, "cf726aee694be7c7"),
    (50, "3427dc5345e51710"), (50, "6f31c641ca8df21a"), (50, "d082768344bcff87"), (52, "4fea141c55b27359"),
    (52, "756c6d82770e3b1a"), (53, "c08680db2eaff018"), (54, "3dbc6d7424f86efc"), (54, "877d0a709514e89b"),
    (55, "5e2670047430e8e4"), (55, "73d941e8a8a536ad"), (55, "7d45dd250bd4bd9b"), (56, "d7e1bde74a518d1a"),
    (57, "57b883aa44432479"), (58, "47b985fb396ccc68"), (58, "b985d1aee6f13ce5"), (58, "ed88e17d4898c366"),
    (59, "a85ccf0385e5f55d"), (59, "b2ea536fee321d49"), (60, "cbea4fb9ee5271dd"), (60, "f0233c5e8f330723"),
    (61, "8ca128010ff994b7"), (61, "b343856679e3d7f1"), (62, "e9900e031fff9880"), (63, "5298c4529dc826c6"),
    (63, "68461032131a029f"), (63, "8fadfac91267d10a"), (64, "1b34a3a3162af7b9"), (64, "996d665d111663af"),
    (64, "9e226b0f7a10a212"), (65, "7593455b37418ceb"), (66, "50070694997f2f85"), (67, "c61009afd3407556"),
    (69, "c773c2eea6b94255"), (70, "b000e85ece48a630"), (72, "5427d24da950f377"), (72, "d64ac766501576ae"),
    (73, "4e6e9c63faa18b3e"), (73, "f3aaf6d7b870969f"), (75, "21700860e05204ae"), (76, "0ac8ef03c1ca645e"),
})
# ruling 3: (length, sha256 first 16 hex) of each former note of the bridge file, its leading title and its
# bracketed parts, case-folded (fragments of 6 characters or more)
BRIDGE_OLD = frozenset({
    (6, "695b2ea90ecaa863"), (7, "9eff371434e50f99"), (7, "a3cca0ced5ece765"), (7, "eb12bbf58347d272"),
    (8, "0f647821be81480c"), (9, "95b6cf097c3d557a"), (11, "e9d911fff723c36e"), (13, "671d63b4d61ba496"),
    (13, "883fc6ece7b0a4b1"), (14, "aae7a21390860538"), (15, "04aa3169faf94218"), (15, "34e061a9bf4465fe"),
    (15, "949d7dc420db0a74"), (18, "550385ec610685ad"), (18, "6f07c84a40ceee5b"), (18, "a36a1a2f7dc42c2c"),
    (18, "d6e6552779bed85e"), (18, "d72a7bf0b3a744c9"), (19, "15581d84f6abaaf6"), (19, "382874a0feaf1617"),
    (19, "b9566b8dae0c1abd"), (19, "d964cdda1b484912"), (20, "43425945d5e28ffc"), (21, "383ba8802f581414"),
    (22, "2804b19205fb6e90"), (22, "5d6308ddf61518ad"), (22, "9131e02305689e2b"), (23, "5bb001cf0e8495a1"),
    (25, "68f597f5f187997b"), (25, "aad56b719492f905"), (26, "0f0f0c4575a4598b"), (26, "2afa822149890305"),
    (26, "4bc96c8f759a7989"), (27, "1b1955527b58e8c0"), (27, "dd339f0d66559fa3"), (28, "572d78bf412e5d18"),
    (29, "e088f9377d19b45e"), (30, "47bce8e684a8aa6a"), (30, "643f43e2c9aa4efd"), (30, "9aae8c49238c81bb"),
    (30, "ca418f8ca4c78618"), (30, "fbb480af4b0b19f7"), (31, "9e8940ee04b291a8"), (31, "a439c17f3571c4ef"),
    (31, "a8b7ed39960f9dba"), (31, "aa3abec647de2d52"), (31, "bf9d3cabaff2f7a1"), (32, "90e613cf76e4a8d1"),
    (32, "da1e9417afbda6d8"), (33, "5dc66456f03d0dde"), (34, "7a2655b40a3c02c9"), (34, "9cf68b9097b4304e"),
    (34, "c090c1fb097bce54"), (35, "192979952badd6a8"), (35, "b8f511fdc8c847cd"), (37, "1baaca4991eb4d4a"),
    (38, "5d2059f8fc0e211b"), (38, "6ee171fc22d4aa52"), (39, "1f02964194951b00"), (40, "578353b2922dde31"),
    (43, "313eb7c7fa1f4b30"), (43, "5791fd6c3373c8f0"), (43, "cf7c7f3fad6551ef"), (43, "d888a616d201419b"),
    (44, "4ed8196edfd48443"), (44, "bc0e0515270a902f"), (45, "79f539eae73a8ee7"), (47, "e9e4657ac85b2abc"),
    (49, "d4b4bc82c78276c9"), (55, "cf845cd7eeab284f"), (59, "0df95c6eca510964"), (59, "dc483d7fcb25ef86"),
    (63, "403fddd52c1c3db4"), (80, "90fd4382fa46d336"), (82, "2fffe182129a4533"), (89, "00b2015dedda5335"),
    (89, "c0d555b11810c9f0"), (118, "1c544adeb4d2bfb6"),
})
# fmt: on


def _sha(text: str) -> str:
    return hashlib.sha256(text.casefold().encode()).hexdigest()[:16]


def _entries(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [e for co in doc["cohorts"].values() for e in co.get("entry_concepts", [])]


def _strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in (k, *_strings(v))]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return [node] if isinstance(node, str) else []


# ------------------------------------------------------------------------------------------------ ruling 1
def test_snomed_and_cpt4_ship_as_concept_ids_only() -> None:
    """No SNOMED CT or CPT4 name, description, code or other text in the files the exception covers."""
    for path in EVIDENCE:
        doc = json.loads(path.read_text(encoding="utf-8"))
        licensed = [e for e in _entries(path) if e.get("vocabulary") in ("SNOMED", "CPT4")]
        assert licensed, path
        for e in licensed:
            assert set(e) <= ID_ONLY_KEYS, (path.name, e)
            assert isinstance(e["concept_id"], int) and e["concept_id"] > 0, e
        assert not [s for s in _strings(doc) if "snomed.info" in s.lower() or "2.16.840.1.113883.6.96" in s]
    assert {"CPT4", "SNOMED"} <= cv.NAMELESS_VOCABULARIES


def test_the_register_holds_the_owners_named_exception_and_no_other() -> None:
    rows = [r for r in lr.load() if r.kind == lr.EXCEPTION_KIND]
    assert [r.id for r in rows] == ["catalogue-evidence-concept-ids"]
    (row,) = rows
    assert row.status == lr.APPROVED
    assert set(row.excepts) == {"SNOMED", "CPT4"}
    assert set(row.paths) == {str(p.relative_to(ROOT)) for p in EVIDENCE}
    assert row.raw["checked"] == RULING_DATE
    assert RULING_DATE in row.raw["evidence"] and "named exception in the licence register" in row.raw["evidence"]


def test_the_shipped_tree_carries_no_text_of_an_excepted_vocabulary() -> None:
    rep = vbc.check(tree=True)
    assert not [p for p in rep.problems if "carries text" in p]
    assert not [p for p in rep.problems if "'SNOMED'" in p or "'CPT4'" in p]


# ------------------------------------------------------------------------------------------------ ruling 2
def test_the_icdo3_names_are_removed_and_the_same_60_ids_kept() -> None:
    path = EVIDENCE[0]
    icdo3 = [e for e in _entries(path) if e.get("vocabulary") == "ICDO3"]
    assert len(icdo3) == 60
    assert {e["concept_id"] for e in icdo3} == ICDO3_IDS
    assert not [e for e in icdo3 if "name" in e]
    assert all(set(e) <= ID_ONLY_KEYS for e in icdo3)
    strings = {(len(s), _sha(s)) for p in EVIDENCE for s in _strings(json.loads(p.read_text(encoding="utf-8")))}
    assert not strings & ICDO3_NAME_LEN_SHA


def test_no_icdo3_name_remains_in_the_catalogue() -> None:
    """The names also stood in catalogue/phenotype_icd10cm.csv (built from the evidence); every text file of the
    catalogue and its test fixtures is searched at each word that starts with a capital letter."""
    lengths = {n for n, _ in ICDO3_NAME_LEN_SHA}
    found = []
    for folder in (ROOT / "catalogue", ROOT / "tests/fixtures/catalogue_verify"):
        for f in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix in (".csv", ".json", ".md", ".yaml")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"(?<![A-Za-z])[A-Z]", text):
                i = m.start()
                found += [(f.name, i) for n in lengths if (n, _sha(text[i : i + n])) in ICDO3_NAME_LEN_SHA]
    assert not found


def test_a_refresh_of_the_evidence_keeps_icdo3_nameless() -> None:
    assert "ICDO3" in cv.NAMELESS_VOCABULARIES
    concepts = [
        {"concept_id": 1, "vocabulary": "ICDO3", "name": "Invented neoplasm name", "domain": "Condition"},
        {"concept_id": 2, "vocabulary": "LOINC", "name": "Invented test name", "domain": "Measurement"},
    ]
    got = cv.nameless(concepts)
    assert "name" not in got[0] and got[1]["name"] == "Invented test name"


# ------------------------------------------------------------------------------------------------ ruling 3
def test_the_bridge_notes_carry_none_of_the_former_wording() -> None:
    with BRIDGE.open(encoding="utf-8", newline="") as fh:
        notes = [r["note"].casefold() for r in csv.DictReader(fh)]
    assert len(notes) == 36
    lengths = {n for n, _ in BRIDGE_OLD}
    found = [(note, n) for note in notes for n in lengths for i in range(len(note) - n + 1)
             if (n, _sha(note[i:i + n])) in BRIDGE_OLD]  # fmt: skip
    assert not found
