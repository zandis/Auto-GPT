"""A small SS-MIX2 storage written from the published specification, not from TrialBox's exporter (plan 10 card
10B-1, the part cards 10B-2 to 10B-5 need; review 12, ``docs/reviews/2026-11-root/12-ssi-data.md`` §4).

Why it exists: every earlier SS-MIX2 test built its messages from ``tools/ssmix2_export.py`` or inline in the shapes
the reader expected, so the tests and the reader shared the same misreadings (review 12 §4.9). Every message and
folder here follows what review 12 records of the published documents; none is copied from the exporter or from
the reader. The documents (review 12 §4.1 and §16; the repository holds only the review's account of them):

* S20 SS-MIX2 標準化ストレージ仕様書 Ver.1.2i (2024-05-16): the segments and fields;
* S21 the same, コード表 Ver.1.2i: the code tables (JHSD0004 to JHSD0007);
* S22 標準化ストレージ 構成の説明と構築ガイドライン Ver.1.2h: the folder tree, the file name, the record key;
* S24 拡張ストレージ 構成の説明と構築ガイドライン Ver.1.2h and S25 its 標準文書コード表: the extended storage.

Where a detail is not recorded in review 12 and could not be confirmed from the repository's own documents, its
comment says "from review 12, not re-verified" or names what was chosen instead. The specification itself was not
opened for this work.

Everything is synthetic: two made-up patients (``10000001``, ``10000002``: the synthetic hospital's chart-number
range, ``tools/make_fixtures.py``), no names, made-up visit, order and document numbers, and placeholder codes where
a real master would be needed (each says so). The tree is written into a temporary folder by :func:`build`, so the
repository holds no HL7 file (the data-handling scan reads HL7 PID segments as identifiers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

P1, P2 = "10000001", "10000002"
DEPT = "01"  # 診療科 in the file name: a site-local code (S22 3.1, review 12 §4.2)

# The F1 probe (review 12 §4.10 F1, measurement M4): three outpatient visits of each patient on three days. Patient
# 1 files them under order number "ALL9", patient 2 under the per-day sequence "1"; both forms are the
# specification's (S22 3.1: "ALL9" for data no order manages; a number that tells the day's events apart for
# admissions and transfers that can happen more than once a day).
VISITS = {
    P1: [("20261001", "V1001"), ("20261008", "V1002"), ("20261015", "V1003")],
    P2: [("20261002", "V2001"), ("20261009", "V2002"), ("20261016", "V2003")],
}
VISIT_ORDER = {P1: "ALL9", P2: "1"}
# Two admissions of patient 2, each with its discharge, all under the per-day sequence "1" (card 12-1's proof:
# "ADT-52 discharges each admission"): (admission day, discharge day, visit number)
ADMISSIONS = [("20260901", "20260905", "V2101"), ("20260920", "20260925", "V2102")]


@dataclass
class Storage:
    """What :func:`build` wrote: the standardised root and the extended-storage root."""

    root: Path
    extended: Path
    files: list[Path] = field(default_factory=list)


def _stamp(day: str, hhmmss: str = "090000", ms: str = "000") -> str:
    """The 発生日時 of a file name: 17 digits, ``YYYYMMDDHHMMSSfff`` (S22 3.1, review 12 §4.2)."""
    return f"{day}{hhmmss}{ms}"


def _msh(when: str, kind: str, control: str) -> str:
    """MSH with MSH-18 ``~ISO IR87`` (JIS X 0208 as ISO-2022-JP, the specification's character set: review 12 §4.2,
    "JIS (ISO-2022-JP)"). MSH-21 (the message profile) is left out: its value is not recorded in review 12."""
    return f"MSH|^~\\&|HIS|SENDER|GW|RECEIVER|{when}||{kind}|{control}|P|2.5||||||~ISO IR87"


def _pid(patient: str) -> str:
    """PID-3 with identifier type ``PI`` (the reader's existing reading, T-615a). No name: none is needed here."""
    return f"PID|||{patient}^^^^PI||"


def _write(st: Storage, patient: str, day: str, typ: str, order: str, stamp: str, segments: list[str],
           flag: str = "1", dept: str = DEPT) -> Path:  # fmt: skip
    """One standardised-storage file (S22 2.2 and 3.1, review 12 §4.2):
    ``<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日 | ->/<データ種別>/<pid>_<診療日>_<データ種別>_<オーダNo>_<発生日時>_<診療科>_<flag>``,
    no extension, ISO-2022-JP, segments ended by CR. Flag 1 valid, 0 invalid or deleted, 2 past history (S22 3.1.2 to
    3.1.4, review 12 §4.4)."""
    d = st.root / patient[0:3] / patient[3:6] / patient / day / typ
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{patient}_{day}_{typ}_{order}_{stamp}_{dept}_{flag}"
    path.write_bytes(("\r".join(segments) + "\r").encode("iso2022_jp"))
    st.files.append(path)
    return path


def _pv1(cls: str, visit: str, start: str = "", end: str = "") -> str:
    """PV1: PV1-2 patient class (O outpatient, I inpatient), PV1-10 department, PV1-19 visit number, PV1-44 the
    admission or visit time, PV1-45 the discharge time (HL7 v2.5 PV1 as the reader already reads it)."""
    pv1 = ["PV1", "1", cls] + [""] * 43
    pv1[10], pv1[19], pv1[44], pv1[45] = DEPT, visit, start, end
    return "|".join(pv1)


# ------------------------------------------------------------------------------------------------ the patients
def _patients(st: Storage) -> None:
    """ADT-00 (ADT^A08) under the day "-" with order number "ALL9" (S22 table 3.1-1: the 診療日 of ADT-00 is "-";
    review 12 §4.2)."""
    for p in (P1, P2):
        segs = [_msh("20260801090000", "ADT^A08^ADT_A01", f"A00{p}"), "EVN||20260801090000", _pid(p) + "||19600101|F"]
        _write(st, p, "-", "ADT-00", "ALL9", _stamp("20260801"), segs)


# ------------------------------------------------------------------------------------------------ F1: visits
def _visits(st: Storage) -> None:
    """ADT-12 (ADT^A04, 外来診察の受付): the 診療日 is PV1-44 (S22 table 3.1-1, review 12 §4.2)."""
    for p, visits in VISITS.items():
        for day, visit in visits:
            when = f"{day}0930"
            segs = [_msh(f"{day}093000", "ADT^A04^ADT_A01", f"A12{visit}"), f"EVN||{day}093000", _pid(p),
                    _pv1("O", visit, when)]  # fmt: skip
            _write(st, p, day, "ADT-12", VISIT_ORDER[p], _stamp(day, "093000"), segs)


def _admissions(st: Storage) -> None:
    """ADT-22 (ADT^A01, 入院実施) on the admission day and ADT-52 (ADT^A03, 退院実施) on the discharge day, each
    under the per-day sequence "1". The 診療日 of ADT-22 and ADT-52 is taken as the event's day: review 12 records
    the rule for ADT-12 only (PV1-44), so this is from review 12's §4.2 by analogy, not re-verified."""
    for adm, dis, visit in ADMISSIONS:
        segs = [_msh(f"{adm}100000", "ADT^A01^ADT_A01", f"A22{visit}"), f"EVN||{adm}100000", _pid(P2),
                _pv1("I", visit, f"{adm}1000")]  # fmt: skip
        _write(st, P2, adm, "ADT-22", "1", _stamp(adm, "100000"), segs)
        segs = [_msh(f"{dis}110000", "ADT^A03^ADT_A03", f"A52{visit}"), f"EVN||{dis}110000", _pid(P2),
                _pv1("I", visit, f"{adm}1000", f"{dis}1100")]  # fmt: skip
        _write(st, P2, dis, "ADT-52", "1", _stamp(dis, "110000"), segs)


# ------------------------------------------------------------------------------------------------ F2: diagnoses
def _prb(action: str, number: str, name: str, *, icd10: str = "", established: str = "", end: str = "",
         outcome: str = "", outcome_date: str = "", onset: str = "", written: str = "", rank: str = "") -> str:  # fmt: skip
    """One PRB of PPR^ZD1 (S20 表 3-46 and 3-47, S21 表 95 to 97, as review 12 §3 row 4 and §4.10 F2 record them):

    * PRB-1 action (HL7 table 0287: AD add, UP update, DE delete), PRB-2 the action's time;
    * PRB-3 the 病名 as ``病名管理番号^病名^MDCDX2`` (MEDIS 標準病名). The 病名管理番号 here are placeholders of eight
      digits starting ``9999``, not real MEDIS numbers;
    * PRB-4 the diagnosis instance id;
    * PRB-7 診断日, PRB-9 終了日;
    * PRB-10 ICD-10 with the 入外区分 as its second triple: ``K297^^I10^O^外来時^JHSD0004`` (review 12 §4.10 F2 quotes
      this shape);
    * PRB-14 転帰 (HL7 table 0241, or JHSD0006: I 中止, M 寛解, C 継続, O その他), PRB-15 転帰日;
    * PRB-16 発生日 (onset), PRB-17 the written name (病名表記, with its 修飾語), PRB-18 主診断 / 副診断 (JHSD0007:
      1 主診断, 2 副診断).
    """
    prb = ["PRB", action, "20261001090000", f"{number}^{name}^MDCDX2", f"DX{number[-4:]}"] + [""] * 14
    prb[7], prb[9], prb[15], prb[16], prb[17] = established, end, outcome_date, onset, written
    prb[10] = f"{icd10}^^I10^O^外来時^JHSD0004" if icd10 else ""
    prb[14] = outcome
    prb[18] = {"1": "1^主診断^JHSD0007", "2": "2^副診断^JHSD0007"}.get(rank, "")
    return "|".join(prb)


# the ids PRB-4 gives the diagnoses below, for the tests
DX = {"gastritis": "DX0001", "diabetes": "DX0002", "uri": "DX0003", "ra": "DX0004", "pneumonia": "DX0005",
      "infarct": "DX0006", "stopped": "DX0007"}  # fmt: skip


def _diagnoses(st: Storage) -> None:
    """PPR-01 is a snapshot: one file per patient under the day "-" with order number "ALL9", holding all of the
    patient's diagnoses; every change writes a new whole file (S22 3.1.2 (2), table 3.1-1; review 12 §4.4). The
    older snapshot below holds a diabetes diagnosis the newer one deletes with PRB-1 ``DE``."""
    old = [_msh("20260601090000", "PPR^ZD1^PPR_ZD1", "PPR0001"), _pid(P1),
           _prb("AD", "99990002", "２型糖尿病", icd10="E119", established="20260601", rank="2")]  # fmt: skip
    _write(st, P1, "-", "PPR-01", "ALL9", _stamp("20260601"), old)
    segs = [
        _msh("20261001090000", "PPR^ZD1^PPR_ZD1", "PPR0002"),
        _pid(P1),
        # the review's reading of the specification's own sample (card 12-2's proof): ICD-10 K29.7 in PRB-10, onset
        # 2011-08-31 (PRB-16) before the diagnosis day (PRB-7), no 転帰 (still current), 主診断
        _prb("AD", "99990001", "胃炎", icd10="K297", established="20110910", onset="20110831", rank="1"),
        # deleted at the hospital: PRB-1 DE (HL7 table 0287)
        _prb("DE", "99990002", "２型糖尿病", icd10="E119", established="20260601", rank="2"),
        # cured: 転帰 F (HL7 table 0241, fully recovered: 治癒) on 2026-03-01, which is also its end day
        _prb(
            "UP",
            "99990003",
            "急性上気道炎",
            icd10="J069",
            established="20260220",
            end="20260301",
            outcome="F^治癒^HL70241",
            outcome_date="20260301",
            rank="2",
        ),
        # in remission: 転帰 M (JHSD0006 寛解)
        _prb(
            "AD",
            "99990004",
            "関節リウマチ",
            icd10="M069",
            established="20200501",
            outcome="M^寛解^JHSD0006",
            outcome_date="20260801",
            rank="2",
        ),
        # suspected only through its 修飾語: the base name in PRB-3 is 肺炎, the written name in PRB-17 carries
        # "の疑い", PRB-13 is empty; the ZPR segment after it holds the suffix 修飾語. ZPR's field layout is not
        # recorded in review 12 (it names "prefix and suffix 修飾語 (the 疑い suffix included)"): here field 1 is a
        # set id and field 2 the 修飾語 as a coded value with a placeholder code, from review 12, not re-verified
        _prb("AD", "99990005", "肺炎", icd10="J189", established="20261001", written="肺炎の疑い", rank="2"),
        "ZPR|1|9999^の疑い^99XYZ",
        # the patient died of it: 転帰 D (HL7 table 0241, dead)
        _prb(
            "UP",
            "99990006",
            "脳梗塞",
            icd10="I639",
            established="20250101",
            outcome="D^死亡^HL70241",
            outcome_date="20251201",
            rank="2",
        ),
        # follow-up stopped: 転帰 I (JHSD0006 中止): neither cured nor known to be current
        _prb(
            "UP",
            "99990007",
            "腰痛症",
            icd10="M545",
            established="20240101",
            outcome="I^中止^JHSD0006",
            outcome_date="20240401",
            rank="2",
        ),
    ]
    _write(st, P1, "-", "PPR-01", "ALL9", _stamp("20261001"), segs)


# ------------------------------------------------------------------------------------------------ F3: medicines
USAGE_TABLE = "code,doses_per_day\nU02,2\n"  # a site's usage table (review 12 §7 ``codes/usage.csv``), synthetic


def _order(st: Storage, number: str, day: str, drug: str, yj: str, dose: str, unit: str, usage: str) -> None:
    """OMP-01 (RDE^O11, 処方オーダ). The 診療日 is ORC-9, the day the order was entered (S22 table 3.1-1, review 12
    §4.2); the order number is ORC-2. RXE-2 the drug as HOT9 (``HOT9``), RXE-3 one dose ("一回分の投薬量", S20 as
    review 12 §4.10 F3 quotes it), RXE-5 the unit, RXE-31 the YJ code (S20 revision 1.2g, review 12 §4.6). TQ1-3 the
    用法 as the first component (a CWE, so its parts are subcomponents) of an HL7 RPT: JAMI 標準用法 (``JAMISDP01``)
    is recommended, local codes ``99XYZ`` allowed (review 12 §4.6). The codes are site-local placeholders: no JAMI
    code table is in the repository, so no JAMI code is written. The coding-system name ``YJ`` in RXE-31 is the
    reader's existing name for YJ (``_YJ_SYS``); the name the specification uses there is from review 12, not
    re-verified. The HOT9 codes are placeholders of nine digits starting ``999``."""
    orc = ["ORC", "NW", number, "", "1", "IP", "", "", "", f"{day}0900"]
    rxe = ["RXE", "", drug, dose, "", unit] + [""] * 26
    rxe[31] = yj
    tq1 = ["TQ1", "1", "", usage, "", "", "", day, ""]
    segs = [_msh(f"{day}090000", "RDE^O11^RDE_O11", f"RX{number}"), _pid(P1), "|".join(orc), "|".join(rxe),
            "|".join(tq1)]  # fmt: skip
    _write(st, P1, day, "OMP-01", number, _stamp(day), segs)


RX = {"tid": "RX0001", "prn": "RX0002", "coded": "RX0003", "none": "RX0004"}


def _medicines(st: Storage) -> None:
    day = "20261001"
    # "1回2錠 1日3回": two tablets a time, three times a day: six a day (card 12-3's proof)
    _order(st, RX["tid"], day, "999000001^アロプリノール錠１００ｍｇ^HOT9", "3943001F1020^アロプリノール錠１００ｍｇ^YJ",
           "2", "TAB^錠^MR9P", "U03&１日３回毎食後&99XYZ")  # fmt: skip
    # when needed (頓用): no number of doses a day, so no daily dose
    _order(st, RX["prn"], day, "999000002^プレドニゾロン錠５ｍｇ^HOT9", "2456001F1020^プレドニゾロン錠５ｍｇ^YJ",
           "1", "TAB^錠^MR9P", "U99&疼痛時&99XYZ")  # fmt: skip
    # a usage code with no text: the doses a day come from the site's usage table (U02: twice a day)
    _order(st, RX["coded"], day, "999000003^メトホルミン塩酸塩錠５００ｍｇ^HOT9",
           "3962002F1020^メトホルミン塩酸塩錠５００ｍｇ^YJ", "1", "TAB^錠^MR9P", "U02&&99XYZ")  # fmt: skip
    # no TQ1-3 at all: the frequency is missing, the daily dose stays unknown
    _order(st, RX["none"], day, "999000004^コルヒチン錠０．５ｍｇ^HOT9", "3941001F1020^コルヒチン錠０．５ｍｇ^YJ",
           "1", "TAB^錠^MR9P", "")  # fmt: skip


# ------------------------------------------------------------------------------------------------ F4: documents
@dataclass(frozen=True)
class Document:
    patient: str
    day: str  # YYYYMMDD, YYYYMM, YYYY or "-" (S24, review 12 §4.5)
    kind: str  # the データ種別 folder, named like a CWE
    folder: str  # the content folder, named like a standardised file
    files: dict[str, bytes]


DOCS = [
    # a discharge summary: a local code with the LOINC document code 18842-5 (退院時サマリ, S25 as review 12 §3 row 15
    # records it); the content folder holds the text and the index file ``_contents.xml`` (its schema is not
    # recorded in review 12, so it holds only a root element here and the reader does not read it)
    Document(
        P1,
        "20261015",
        "L000101^退院時サマリ^99XYZ^18842-5^退院時サマリー^LN",
        f"{P1}_20261015_18842-5_S0001_{_stamp('20261015', '170000')}_{DEPT}_1",
        {
            "summary.txt": "【入院経過】肺炎の疑いで入院し、抗菌薬で軽快した。".encode(),
            "_contents.xml": b'<?xml version="1.0" encoding="UTF-8"?><contents/>',
        },
    ),
    # a pathology report under a month day (YYYYMM), folder named with no local code: "^" first, the LOINC code
    # 11526-1 (病理検査報告書, S25 as review 12 §3 row 8 records it)
    Document(
        P1,
        "202610",
        "^^^11526-1^病理検査報告書^LN",
        f"{P1}_202610_11526-1_P0001_{_stamp('20261020', '120000')}_{DEPT}_1",
        {"report.txt": "病理診断：悪性所見を認めない。".encode()},
    ),
    # a local-only data-type folder (S24: readers must accept local-only names) under the day "-"
    Document(
        P2,
        "-",
        "L000301^看護記録^99XYZ",
        f"{P2}_-_L000301_N0001_{_stamp('20261002')}_{DEPT}_1",
        {"note.txt": "夜間良眠。".encode()},
    ),
    # a discharge summary written and then deleted: the newer content folder carries flag 0 (S24 2.2 (5)④: the flags
    # are on the content folder, review 12 §4.4)
    Document(
        P2,
        "20261002",
        "^^^18842-5^退院時サマリー^LN",
        f"{P2}_20261002_18842-5_S0002_{_stamp('20261002', '150000')}_{DEPT}_1",
        {"summary.txt": "記載誤り。".encode()},
    ),
    Document(
        P2,
        "20261002",
        "^^^18842-5^退院時サマリー^LN",
        f"{P2}_20261002_18842-5_S0002_{_stamp('20261002', '160000')}_{DEPT}_0",
        {},
    ),
]


def _documents(st: Storage) -> None:
    """拡張ストレージ (S24 2.2, review 12 §4.5):
    ``<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別 folder>/<content folder>/<files>``."""
    for doc in DOCS:
        d = st.extended / doc.patient[0:3] / doc.patient[3:6] / doc.patient / doc.day / doc.kind / doc.folder
        d.mkdir(parents=True, exist_ok=True)
        for name, data in doc.files.items():
            (d / name).write_bytes(data)
            st.files.append(d / name)


def build(base: Path, usage_table: bool = True) -> Storage:
    """Write the whole storage under ``base``: ``base/ss`` (standardised) and ``base/ss/extended_storage``
    (extended, where the reader looks by default); with ``usage_table`` also ``base/usage.csv``."""
    st = Storage(base / "ss", base / "ss" / "extended_storage")
    st.root.mkdir(parents=True, exist_ok=True)
    _patients(st)
    _visits(st)
    _admissions(st)
    _diagnoses(st)
    _medicines(st)
    _documents(st)
    if usage_table:
        (base / "usage.csv").write_text(USAGE_TABLE, encoding="utf-8")
    return st
