"""Plan 10 criterion F1's four probes as fixtures written from the SS-MIX2 documents (card 10B-1, D-1262), with the
``spec`` exporter's writer (``tools/ssmix2_spec_export.py``), never from the reader:

1. three outpatient visits on three days (G 表3.1-1 No.5: the 診療日 is PV1-44; 表3.1-3 No.4: the day's sequence);
2. the specification's diagnosis sample in its shape (S 表3-47 and the PPR^ZD1 example of 付録1): ICD-10 K29.7 in
   PRB-10, onset (PRB-16) before the diagnosis day (PRB-7), no 転帰, 主診断 (PRB-18), with a ZPR naming the disease;
3. "1回2錠 1日3回": RXE-3 one dose of 2 tablets (S 表3-57), TQ1-3 a usage of three times a day (S 表3-58);
4. a guideline-layout extended storage with 2 documents (E 2.2 (3) to (7)): a discharge summary and a pathology
   report, each in a content folder under a CWE+LOINC data-type folder, with ``_contents.xml``.

Codes a licensed master would hold are invented in its shape: the 病名管理番号 ``99990297`` (8 digits), the exchange
code ``Z9Q1`` (4 characters A-Z0-9), the HOT9 code ``999000101``. The YJ code is the shipped sample lookup's. No row
of a master is copied. Patients and numbers are made up.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.ssmix2_spec_export import (
    ALL9,
    Patients,
    SpecStorage,
    adt,
    contents_xml,
    evn,
    msh,
    prb,
    pv1,
    seg,
    zpr,
)

PATIENT = "30000001"
VISITS = [("20261001093000", "V3001"), ("20261008093000", "V3002"), ("20261015093000", "V3003")]
DIAGNOSIS = "DX3001"
ORDER = "RX3001"
DOCS = {
    "18842-5": ("L0101^退院時サマリー^99DOC^18842-5^退院時サマリ^LN", "summary.txt", "【入院経過】軽快退院。"),
    "11526-1": ("L0301^病理報告書^99DOC^11526-1^病理検査報告書^LN", "report.txt", "病理診断：悪性所見なし。"),
}


@dataclass
class Fixture:
    root: Path
    extended: Path


def build(base: Path) -> Fixture:
    st = SpecStorage(base / "ss")
    people = Patients([{"mrn": PATIENT, "name": "試験　花子", "birth_date": "1960-01-01", "sex": "F"}])
    when = "20260901090000"
    st.put(PATIENT, "-", "ADT-00", ALL9, "-", when, adt(when, "A08", "F1P", people.pid(PATIENT), evn(when), pv1("O")))
    # 1. three visits on three days, each the first of its day
    for when, visit in VISITS:
        segs = adt(when, "A04", visit, people.pid(PATIENT), evn(when), pv1("O", dept="01", visit=visit, start=when))
        st.put(PATIENT, when[:8], "ADT-12", st.sequence(PATIENT, when[:8], "ADT-12"), "01", when, segs)
    # 2. the diagnosis sample's shape
    when = "20110915120000"
    line = prb(
        "AD", when, "99990297", "胃炎", DIAGNOSIS, icd10="K29.7", diagnosed="20110915", onset="20110831", rank="1"
    )
    segs = [msh(when, "PPR^ZD1^PPR_ZD1", "F1D"), people.pid(PATIENT), line, zpr("99990297", "胃炎", "Z9Q1")]
    st.put(PATIENT, "-", "PPR-01", ALL9, "-", when, segs)
    # 3. "1回2錠 1日3回" (the YJ code is jp_core/yj_to_atc.csv's allopurinol row)
    when = "20261001090000"
    drug = "999000101^アロプリノール錠１００ｍｇ^HOT9^L0001^アロプリノール錠１００ｍｇ^99DRG"
    segs = [
        msh(when, "RDE^O11^RDE_O11", "F1R"),
        people.pid(PATIENT),
        pv1("O", dept="01"),
        seg("ORC", {1: "NW", 2: ORDER, 4: ORDER, 5: "IP", 9: when, 17: "01^^99ORD"}),
        seg(
            "RXE", {2: drug, 3: "2", 5: "TAB^錠^MR9P", 10: "42", 11: "TAB^錠^MR9P", 31: "L0001^^99DRG^3943001F1020^^YJ"}
        ),
        seg("TQ1", {1: "1", 3: "U03&１日３回毎食後&99USG", 6: "7^d", 7: "20261001"}),
        "RXR|PO^口^HL70162",
    ]
    st.put(PATIENT, "20261001", "OMP-01", ORDER, "01", when, segs)
    # 4. the guideline layout: two documents, each in its content folder
    ext = base / "ss" / "extended_storage"
    for n, (code, (kind, name, text)) in enumerate(DOCS.items()):
        when = f"2026101517000{n}"
        folder = ext / PATIENT[0:3] / PATIENT[3:6] / PATIENT / "20261015" / kind
        folder = folder / f"{PATIENT}_20261015_{code}_K{n}_{when}000_01_1"
        folder.mkdir(parents=True)
        (folder / name).write_bytes(text.encode())
        (folder / "_contents.xml").write_bytes(contents_xml(when, name, "text/plain"))
    return Fixture(base / "ss", ext)
