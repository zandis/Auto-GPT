"""A shape check of an SS-MIX2 storage written only from the published documents' tables (plan 10 card 10B-1,
D-1262). It reads no TrialBox reader code and no exporter code: every rule below names the table it comes from.

Documents (JAMI, listed at https://www.jami.jp/jamistd/ss-mix2/; cited, not copied):

* **G** SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン Ver.1.2j (2026-08-14).
* **S** SS-MIX2 標準化ストレージ 仕様書 Ver.1.2j (2026-08-14).
* **C** SS-MIX2 標準化ストレージ 仕様書 別紙 コード表 Ver.1.2j (2026-08-14).
* **E** SS-MIX2 拡張ストレージ 構成の説明と構築ガイドライン Ver.1.2j (2026-08-14).

Page numbers are the documents' printed page numbers ("p.13" is the page that prints "- 13 -").

    python -m tools.ssmix2_shape_check <standardised root> [--extended <dir>] [--exclude <name> ...] [--list N]

It walks the storage and reports per data type the files, the messages and the rule failures; it exits 1 when any
rule fails.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ----------------------------------------------------------------------------------------------- the rules
RULES: dict[str, str] = {
    "T1": "G 2.2 (2) ③ to ⑤, 図2.2-1 (p.5, 6): <root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別>/<file>",
    "T2": "G 表2.3-1 No.1 (p.7): the patient ID is at least 6 alphanumeric characters",
    "T3": "G 表2.3-1 No.2 (p.7): the 診療日 folder is a real date YYYYMMDD or '-'",
    "T4": "G 表3.1-2 (p.11): the データ種別 folder is one of the 26 types",
    "N1": "G 3.1.2 (1) (p.12): the name is "
    "患者ID_診療日_データ種別_オーダNo_発生日時_診療科コード_コンディションフラグ, "
    "the first three equal to the folders, no part empty",
    "N2": "G 表3.1-3 No.5 (p.13): the 発生日時 is YYYYMMDDHHMMSSFFF, a real time",
    "N3": "G 表3.1-3 No.7 (p.14): the condition flag is 1, 0 or 2; G 3.1.2 (3) ① (p.15): no extension",
    "N4": "G 表3.1-3 No.4 (p.13), 図3.1-1 (p.16): ALL9 (or all nines) for 患者基本 (ADT-00), 病名 (PPR-01), アレルギー "
    "(ADT-61)",
    "N5": "G 表3.1-3 No.4 (p.13): the オーダNo of an order is its ORC-2",
    "N6": "G 表3.1-3 No.1 (p.13): the patient ID is PID-3's",
    "K1": "G 3.1.2 (3) ③ (p.15), 3.1.4 (2) ⑥ (p.18 to 20): per record (patient, 診療日, データ種別, オーダNo) at most "
    "one file of flag 1, and it is the newest",
    "K2": "G 3.1.4 (2) ⑥ 2) (p.19): when the newest file of a record is flag 0 (a deletion), every file of it is 0",
    "K3": "G 表3.1-3 No.5 (p.13): every file of a record has its own 発生日時",
    "D1": "G 表3.1-1 (p.9, 10): the 診療日 folder is the date of the field the table names for the message ('-' where "
    "it names none)",
    "M1": "G 表3.1-2 (p.11): MSH-9 is a message type and event of the データ種別",
    "M2": "S 3.4 to 3.20 (each message's 'メッセージ構造は'): MSH-9's third component is the message's structure",
    "M3": "S 表3-34 (p.30, 31): MSH-2 '^~\\&', MSH-7 YYYYMMDDHHMMSS[.S[S[S[S]]]], MSH-11 'P', MSH-12 '2.5', MSH-18 "
    "'~ISO IR87', MSH-20 'ISO 2022-1994' when set, MSH-21 an SS-MIX2 profile when set",
    "E1": "G 3.1.2 (3) ② (p.15), S 表3-34 MSH-18 and MSH-20: the file is JIS (ISO-2022-JP: 7-bit, JIS X 0208)",
    "E2": "S 2.1.4 (p.2): every segment ends with <CR> (no <LF>)",
    "G1": "S message tables 表3-13 to 表3-99: the segments outside every [ ] are present",
    "F1": "S segment tables (column SS-MIX2 'R', 表3-4 p.5): the field is set (or '\"\"')",
    "C1": "C 表2 to 表12 (p.1 to 4), HL7 table 0396: a coding-system name is one the code table lists, I10 (S 表3-47 "
    "PRB-10), YJ or MYAK (S 表3-57 RXE-31), or a local '99zzz' / 'L' name",
    "P1": "S 表3-47 PRB-1 (p.51): the action is in HL7 table 0287 (C 表35)",
    "P2": "S 表3-47 PRB-10 (p.52): '<ICD-10>^^I10^<診断種別>^<text>^JHSD0004', a WHO ICD-10 code without its dot "
    "(the table's example K297; I10 in HL7 table 0396), 診断種別 in C 表94",
    "P3": "S 表3-47 PRB-14 (p.52): 転帰 under HL70241 (C 表34) or JHSD0006 (C 表96)",
    "P4": "S 表3-47 PRB-15 (p.53): for death, recovery and full recovery PRB-9 and PRB-15 are the same",
    "P5": "S 表3-47 PRB-13, PRB-18 (p.52, 53): JHSD0005 (C 表95) and JHSD0007 (C 表97) values",
    "R1": "S 表3-57 RXE-31 (p.72): '<local code>^^<local system>^<code>^^YJ|MYAK', the local code also in RXE-2",
    "X1": "E 2.2 (3), 図2.2-2 (p.3): <root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別>/<コンテンツ>/<files>",
    "X2": "E 2.2 (3) ① to ③ (p.4): the 診療日 is YYYYMMDD, YYYYMM, YYYY or '-'",
    "X3": "E 2.2 (4) ③ (p.4, 5): the データ種別 folder is [local code]^local name^[local system]^LOINC^name^LN, the "
    "standard part set, a local code starting 'L', a local system 'L' or '99zzz', at most 180 characters of "
    "full-width or half-width alphanumeric and hyphen",
    "X4": "E 2.2 (5) ① (p.5): every document is in a content folder",
    "X5": "E 2.2 (5) ② ③ (p.5, 6): the content folder is named "
    "患者ID_診療日_データ種別コード_特定キー_発生日時_診療科コード_コンディションフラグ (flag 1, 0 or 2)",
    "X6": "E 2.2 (6) ⑤, 表2.2-1 (p.8, 9): every file carries an extension of the table",
    "X7": "E 2.2 (7), 表2.2-2 (p.9 to 11): _contents.xml has the root Contents (createDateTime, createVender) and "
    "Document elements (name, mime, relDir)",
}

# G 表3.1-2: データ種別 -> its HL7 message types and events
TYPES: dict[str, tuple[str, ...]] = {
    "ADT-00": ("ADT^A08", "ADT^A23"),
    "ADT-01": ("ADT^A54", "ADT^A55"),
    "ADT-12": ("ADT^A04",),
    "ADT-21": ("ADT^A14", "ADT^A27"),
    "ADT-22": ("ADT^A01", "ADT^A11"),
    "ADT-31": ("ADT^A21", "ADT^A52"),
    "ADT-32": ("ADT^A22", "ADT^A53"),
    "ADT-41": ("ADT^A15", "ADT^A26"),
    "ADT-42": ("ADT^A02", "ADT^A12"),
    "ADT-51": ("ADT^A16", "ADT^A25"),
    "ADT-52": ("ADT^A03", "ADT^A13"),
    "ADT-61": ("ADT^A60",),
    "PPR-01": ("PPR^ZD1",),
    "OMD": ("OMD^O03",),
    "OMP-01": ("RDE^O11",),
    "OMP-11": ("RAS^O17",),
    "OMP-02": ("RDE^O11",),
    "OMP-12": ("RAS^O17",),
    "OML-01": ("OML^O33",),
    "OML-11": ("OUL^R22",),
    "OMG-01": ("OMG^O19",),
    "OMG-11": ("OMI^Z23",),
    "OMG-02": ("OMG^O19",),
    "OMG-12": ("OMI^Z23",),
    "OMG-03": ("OMG^O19",),
    "OMG-13": ("ORU^R01",),
}
ORDER_TYPES = (
    "OMD",
    "OMP-01",
    "OMP-11",
    "OMP-02",
    "OMP-12",
    "OML-01",
    "OML-11",
    "OMG-01",
    "OMG-11",
    "OMG-02",
    "OMG-12",
    "OMG-03",
    "OMG-13",
)
ALL9_TYPES = ("ADT-00", "PPR-01", "ADT-61")

# S: the structure each message uses (MSH-9.3)
STRUCTURE = {
    "ADT^A01": "ADT_A01",
    "ADT^A02": "ADT_A02",
    "ADT^A03": "ADT_A03",
    "ADT^A04": "ADT_A01",
    "ADT^A08": "ADT_A01",
    "ADT^A11": "ADT_A09",
    "ADT^A12": "ADT_A09",
    "ADT^A13": "ADT_A01",
    "ADT^A14": "ADT_A05",
    "ADT^A15": "ADT_A15",
    "ADT^A16": "ADT_A16",
    "ADT^A21": "ADT_A21",
    "ADT^A22": "ADT_A21",
    "ADT^A23": "ADT_A21",
    "ADT^A25": "ADT_A21",
    "ADT^A26": "ADT_A21",
    "ADT^A27": "ADT_A21",
    "ADT^A52": "ADT_A52",
    "ADT^A53": "ADT_A52",
    "ADT^A54": "ADT_A54",
    "ADT^A55": "ADT_A52",
    "ADT^A60": "ADT_A60",
    "OMG^O19": "OMG_O19",
    "OMI^Z23": "OMI_Z23",
    "OML^O33": "OML_O33",
    "ORU^R01": "ORU_R01",
    "OUL^R22": "OUL_R22",
    "PPR^ZD1": "PPR_ZD1",
    "RAS^O17": "RAS_O17",
    "RDE^O11": "RDE_O11",
    "OMD^O03": "OMD_O03",
}

# G 表3.1-1: the field whose date is the 診療日 (None: "-")
DAY_FIELD: dict[str, tuple[str, int] | None] = {
    "ADT^A08": None,
    "ADT^A23": None,
    "ADT^A54": None,
    "ADT^A55": None,
    "ADT^A60": None,
    "PPR^ZD1": None,
    "ADT^A04": ("PV1", 44),
    "ADT^A14": ("PV2", 8),
    "ADT^A27": ("PV2", 8),
    "ADT^A01": ("PV1", 44),
    "ADT^A11": ("PV1", 44),
    "ADT^A21": ("EVN", 6),
    "ADT^A52": ("EVN", 6),
    "ADT^A22": ("EVN", 6),
    "ADT^A53": ("PV2", 47),
    "ADT^A15": ("PV2", 8),
    "ADT^A26": ("PV2", 8),
    "ADT^A02": ("EVN", 6),
    "ADT^A12": ("EVN", 6),
    "ADT^A16": ("PV2", 9),
    "ADT^A25": ("PV2", 9),
    "ADT^A03": ("PV1", 45),
    "ADT^A13": ("PV1", 45),
    "OMD^O03": ("ORC", 9),
    "RDE^O11": ("ORC", 9),
    "OML^O33": ("ORC", 9),
    "OUL^R22": ("SPM", 17),
    "OMG^O19": ("ORC", 9),
    "OMI^Z23": ("OBR", 7),
    "ORU^R01": ("OBR", 7),
}
RAS_DAY = ("RXA", 3)  # 表3.1-1 No.26, 28

# S message tables: the segments outside every [ ] (G1)
REQUIRED_SEGMENTS = {
    **{e: ("MSH", "EVN", "PID", "PV1") for e in STRUCTURE if e.startswith("ADT^") and e != "ADT^A60"},  # 表3-13 to 3-33
    "ADT^A60": ("MSH", "EVN", "PID"),  # 表3-44
    "PPR^ZD1": ("MSH", "PID", "PRB"),  # 表3-46
    "OMD^O03": ("MSH", "ORC"),  # 表3-51
    "RDE^O11": ("MSH", "ORC", "RXE", "TQ1", "RXR"),  # 表3-55, 表3-62
    "RAS^O17": ("MSH", "ORC", "RXA", "RXR"),  # 表3-60, 表3-70
    "OML^O33": ("MSH", "SPM", "ORC"),  # 表3-72
    "OUL^R22": ("MSH", "SPM", "OBR"),  # 表3-78
    "OMG^O19": ("MSH", "ORC", "OBR"),  # 表3-79, 3-88, 3-94
    "OMI^Z23": ("MSH", "ORC", "TQ1", "OBR", "IPC"),  # 表3-84, 3-92
    "ORU^R01": ("MSH", "OBR"),  # 表3-99
}

# S segment tables: SS-MIX2 column "R" (F1). Common to every message:
COMMON_R = {
    "MSH": (7, 9, 10, 11, 12, 18),
    "EVN": (2,),
    "PID": (3, 5, 7, 8),
    "PV1": (2,),
    "IAM": (1, 3, 6),
    "PRB": (1, 2, 3, 4),
    "ZPR": (2,),
}  # 表3-34 to 3-38, 3-45, 3-47, 3-48
# per データ種別 (the order's own tables)
TYPE_R: dict[str, dict[str, tuple[int, ...]]] = {
    "OMD": {"ORC": (1, 2), "ODS": (1, 3)},  # 表3-52, 3-54
    "OMP-01": {"ORC": (1, 2, 4), "RXE": (2, 3, 5, 10, 11), "RXR": (1,)},  # 表3-56, 3-57, 3-59
    "OMP-11": {"RXA": (1, 2, 4, 5, 6), "RXR": (1,)},  # 表3-61
    "OMP-02": {"ORC": (1, 2, 4, 17, 29), "RXE": (2, 3, 5), "RXR": (1,), "RXC": (1, 2, 4)},  # 表3-63, 3-64, 3-66, 3-67
    "OMP-12": {"RXA": (1, 2, 4, 5, 6), "RXR": (1,)},  # 表3-71
    "OML-01": {"ORC": (1, 2), "TQ1": (1,), "OBR": (2, 4), "SPM": (4,)},  # 表3-73 to 3-76
    "OML-11": {"OBR": (2, 4), "OBX": (3, 11), "SPM": (4,)},  # 表3-73, 3-76, 3-77
    "OMG-01": {"ORC": (1, 2, 9, 12), "TQ1": (1, 9), "OBR": (2, 4)},  # 表3-80 to 3-82
    "OMG-11": {"OBR": (2, 4), "ZE1": (2, 3), "IPC": (1, 3, 5)},  # 表3-82, 3-85, 3-86
    "OMG-02": {"ORC": (1,), "OBR": (2, 4)},  # 表3-89, 3-90
    "OMG-12": {"OBR": (2, 4), "ZE1": (1, 2, 3), "IPC": (1, 3, 5)},  # 表3-90, 3-85, 3-93
    "OMG-03": {"ORC": (1, 2, 9, 12, 17), "TQ1": (1, 9), "OBR": (1, 2, 4)},  # 表3-95 to 3-97
    "OMG-13": {"OBR": (1, 2, 4), "OBX": (2, 3, 11)},  # 表3-97, 3-98
}

# C 表2 to 表12: the coding-system names the code table lists (C1)
CODE_SYSTEMS = frozenset(
    {
        "MDCDX2",
        "JC10",
        "JC11",
        "JJ1017",
        "JHSP0001",
        "JHSP0002",
        "JSHR",
        "JHSD0001",
        "JHSD0002",
        "JHSD0004",
        "JHSD0005",
        "JHSD0006",
        "JHSD0007",
        "MR9P",
        "JAMISDP01",
        "SSMIXTF01",
        "I10",
        "YJ",
        "MYAK",
        "DCM",
    }
    | {
        f"HL7{n}"
        for n in [
            "0003",
            "0038",
            "0074",
            "0076",
            "0085",
            "0103",
            "0104",
            "0119",
            "0123",
            "0125",
            "0136",
            "0159",
            "0163",
            "0166",
            "0190",
            "0200",
            "0201",
            "0202",
            "0203",
            "0207",
            "0211",
            "0241",
            "0287",
            "0321",
            "0322",
            "0323",
            "0354",
            "0356",
            "0465",
            "0472",
            "0478",
            "0480",
            "0482",
            "0495",
            "0550",
            "0001",
            "0004",
            "0010",
            "0062",
            "0063",
            "0069",
            "0078",
            "0112",
            "0116",
            "0127",
            "0128",
            "0162",
            "0164",
            "0165",
            "0177",
            "0188",
            "0300",
            "0302",
            "0305",
            "0334",
            "0335",
            "0361",
            "0362",
            "0436",
            "0438",
            "0477",
            "0485",
        ]
    }
    | {f"99I0{n}" for n in range(1, 8)}
    | {f"JSHR00{n}" for n in range(1, 8)}
)
_HOT = re.compile(r"^HOT\d{1,2}$")  # C 表2: HOTnn
_LOCAL = re.compile(r"^(?:L|99[0-9A-Za-z]{3,})$")  # HL7 table 0396: 99zzz, L
CODED = {  # the coded fields whose coding-system names C1 checks (components 3 and 6)
    "PRB": (3, 10, 13, 14, 18),
    "ZPR": (1, 2, 3, 4, 5, 6),
    "RXE": (2, 5, 11, 31),
    "RXC": (2, 4),
    "RXR": (1,),
    "RXA": (5, 7),
    "OBX": (3,),
    "OBR": (4,),
    "SPM": (4,),
    "IAM": (2, 3, 4, 6),
    "ODS": (3,),
    "ZE1": (2, 3),
    "IPC": (5,),
    "ORC": (29,),
    "TQ1": (9,),
}
HL70287 = ("AD", "CO", "DE", "LI", "UC", "UN", "UP")  # C 表35
# S 表3-47 PRB-10 example K297; I10 is WHO ICD-10 (HL7 table 0396)
WHO_ICD10 = re.compile(r"^[A-Z][0-9]{2}[0-9]?$")
JHSD0004 = ("H", "L", "O", "B", "A", "F")  # C 表94
HL70241 = ("D", "R", "N", "W", "S", "F", "U")  # C 表34
JHSD0006 = ("I", "M", "C", "O")  # C 表96
SAME_END = ("D", "R", "F")  # S 表3-47 PRB-15: 死亡, 回復, 完全回復
EXTENSIONS = frozenset(
    [
        ".csv",
        ".hl7",
        ".er7",
        ".html",
        ".htm",
        ".json",
        ".latex",
        ".rtf",
        ".tab",
        ".tex",
        ".xml",
        ".dtd",
        ".css",
        ".js",
        ".xsl",
        ".xslt",
        ".rdf",
        ".doc",
        ".docx",
        ".docm",
        ".ppt",
        ".pptx",
        ".pptm",
        ".xls",
        ".xlsx",
        ".xlsm",
        ".vsd",
        ".odg",
        ".odp",
        ".ods",
        ".odt",
        ".txt",
        ".text",
        ".dvi",
        ".pdf",
        ".pict",
        ".pic",
        ".pct",
        ".ps",
        ".eps",
        ".svg",
        ".svgz",
        ".wmf",
        ".emf",
        ".bmp",
        ".dcm",
        ".dicom",
        ".gif",
        ".jp2",
        ".j2k",
        ".jpg",
        ".jpeg",
        ".jfif",
        ".png",
        ".tif",
        ".tiff",
        ".3gp",
        ".3g2",
        ".aac",
        ".m4a",
        ".mp3",
        ".rm",
        ".wav",
        ".wma",
        ".avi",
        ".mpeg",
        ".mpg",
        ".mp4",
        ".mov",
        ".mwf",
        ".gzip",
        ".tgz",
        ".gz",
        ".zip",
    ]
)  # E 表2.2-1 (.tar.gz is read by its last suffix)


# ----------------------------------------------------------------------------------------------- the report
@dataclass
class Report:
    files: Counter[str] = field(default_factory=Counter)
    messages: Counter[str] = field(default_factory=Counter)
    failures: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    examples: dict[tuple[str, str], list[str]] = field(default_factory=lambda: defaultdict(list))

    def fail(self, typ: str, rule: str, where: str) -> None:
        self.failures[typ][rule] += 1
        if len(self.examples[typ, rule]) < 3:
            self.examples[typ, rule].append(where)

    @property
    def total(self) -> int:
        return sum(sum(c.values()) for c in self.failures.values())

    def lines(self, examples: int = 0) -> list[str]:
        out = []
        for typ in sorted(set(self.files) | set(self.failures)):
            fails = self.failures.get(typ, Counter())
            what = ", ".join(f"{r} {n}" for r, n in sorted(fails.items())) or "no failure"
            out.append(f"{typ}: {self.files[typ]} files, {self.messages[typ]} messages; {what}")
            for rule in sorted(fails):
                out += [f"    {rule}: {e}" for e in self.examples[typ, rule][:examples]]
        out.append(f"total rule failures: {self.total}")
        return out


# ----------------------------------------------------------------------------------------------- HL7
def _real(day: str, fmt: str = "%Y%m%d") -> bool:
    try:
        datetime.strptime(day, fmt)
    except ValueError:
        return False
    return True


def segments(text: str) -> list[list[str]]:
    return [s.split("|") for s in text.split("\r") if s]


def field_of(seg: list[str], n: int) -> str:
    """Field ``n`` of a segment (MSH counts its field separator as MSH-1)."""
    i = n - 1 if seg[0] == "MSH" else n
    return seg[i] if 0 <= i < len(seg) else ""


def _systems(value: str) -> list[str]:
    out = []
    for rep in value.split("~"):
        comps = rep.split("^")
        out += [comps[i] for i in (2, 5) if len(comps) > i and comps[i]]
    return out


def check_message(typ: str, data: bytes, parts: list[str], rep: Report, where: str) -> str:
    """Rules E1 to R1 for one file; returns its message type and event (``ADT^A08``) or ''."""
    if any(b > 0x7F for b in data) or b"\x1b$(D" in data:
        rep.fail(typ, "E1", where)
    try:
        text = data.decode("iso2022_jp")
    except UnicodeDecodeError:
        rep.fail(typ, "E1", where)
        text = data.decode("utf-8", errors="replace")
    if "\n" in text or not text.endswith("\r"):
        rep.fail(typ, "E2", where)
    segs = segments(text)
    if not segs or segs[0][0] != "MSH":
        rep.fail(typ, "G1", where)
        return ""
    mshs = segs[0]
    kind = field_of(mshs, 9).split("^")
    event = "^".join(kind[:2])
    if event not in TYPES.get(typ, ()):
        rep.fail(typ, "M1", where)
    if len(kind) < 3 or STRUCTURE.get(event) != kind[2]:
        rep.fail(typ, "M2", where)
    if (
        field_of(mshs, 2) != "^~\\&"
        or not re.fullmatch(r"\d{14}(\.\d{1,4})?", field_of(mshs, 7))
        or field_of(mshs, 11) != "P"
        or field_of(mshs, 12) != "2.5"
        or field_of(mshs, 18) != "~ISO IR87"
        or field_of(mshs, 20) not in ("", "ISO 2022-1994")
        or (field_of(mshs, 21) and not field_of(mshs, 21).startswith("SS-MIX2_"))
    ):
        rep.fail(typ, "M3", where)
    ids = [s[0] for s in segs]
    if any(s not in ids for s in REQUIRED_SEGMENTS.get(event, ("MSH",))):
        rep.fail(typ, "G1", where)
    required = {**COMMON_R, **TYPE_R.get(typ, {})}
    for s in segs:
        for n in required.get(s[0], ()):
            if not field_of(s, n):
                rep.fail(typ, "F1", f"{where} {s[0]}-{n}")
        for n in CODED.get(s[0], ()):
            value = field_of(s, n)
            if s[0] == "TQ1":
                value = "^".join(value.split("^")[0].split("&"))
            for cs in _systems(value):
                if cs not in CODE_SYSTEMS and not _HOT.match(cs) and not _LOCAL.match(cs):
                    rep.fail(typ, "C1", f"{where} {s[0]}-{n} {cs}")
    tq1 = [s for s in segs if s[0] == "TQ1"]
    for t in tq1:
        for rep_ in field_of(t, 3).split("~"):
            sub = rep_.split("^")[0].split("&")
            for cs in (sub[i] for i in (2, 5) if len(sub) > i and sub[i]):
                if cs not in CODE_SYSTEMS and not _LOCAL.match(cs):
                    rep.fail(typ, "C1", f"{where} TQ1-3 {cs}")
    # file-name parts against the message (N5, N6, D1)
    pid = [s for s in segs if s[0] == "PID"]
    if pid and parts[0] not in [r.split("^")[0] for r in field_of(pid[0], 3).split("~")]:
        rep.fail(typ, "N6", where)
    orc = [s for s in segs if s[0] == "ORC"]
    if typ in ORDER_TYPES and orc and field_of(orc[0], 2).split("^")[0] != parts[3]:
        rep.fail(typ, "N5", where)
    ref = RAS_DAY if event == "RAS^O17" else DAY_FIELD.get(event)
    if event in DAY_FIELD or event == "RAS^O17":
        if ref is None:
            if parts[1] != "-":
                rep.fail(typ, "D1", where)
        else:
            found = [field_of(s, ref[1]) for s in segs if s[0] == ref[0]]
            if not found or found[0][:8] != parts[1]:
                rep.fail(typ, "D1", f"{where} {ref[0]}-{ref[1]}")
    for s in segs:
        if s[0] == "PRB":
            _check_prb(typ, s, rep, where)
        if s[0] == "RXE" and field_of(s, 31):
            locals_ = {c[0] for c in _cwe(field_of(s, 2)) if _LOCAL.match(c[2])}
            for rep_ in field_of(s, 31).split("~"):
                c = (rep_.split("^") + [""] * 6)[:6]
                if not c[0] or not _LOCAL.match(c[2]) or c[5] not in ("YJ", "MYAK") or c[0] not in locals_:
                    rep.fail(typ, "R1", where)
    return event


def _cwe(value: str) -> list[tuple[str, str, str]]:
    c = (value.split("^") + [""] * 6)[:6]
    return [(c[0], c[1], c[2]), (c[3], c[4], c[5])]


def _check_prb(typ: str, s: list[str], rep: Report, where: str) -> None:
    if field_of(s, 1) not in HL70287:
        rep.fail(typ, "P1", where)
    p10 = field_of(s, 10)
    if p10:
        c = (p10.split("^") + [""] * 6)[:6]
        if (
            not WHO_ICD10.match(c[0])
            or c[1]
            or c[2] != "I10"
            or (c[3] and (c[5] != "JHSD0004" or c[3] not in JHSD0004))
        ):
            rep.fail(typ, "P2", where)
    p14 = field_of(s, 14)
    if p14:
        c = (p14.split("^") + [""] * 3)[:3]
        if not ((c[2] == "HL70241" and c[0] in HL70241) or (c[2] == "JHSD0006" and c[0] in JHSD0006)):
            rep.fail(typ, "P3", where)
        elif c[2] == "HL70241" and c[0] in SAME_END and field_of(s, 9) != field_of(s, 15):
            rep.fail(typ, "P4", where)
    p13, p18 = field_of(s, 13), field_of(s, 18)
    if p13 and p13.split("^")[0] != "1":
        rep.fail(typ, "P5", where)
    if p18 and ([*p18.split("^"), "", "", ""][2] != "JHSD0007" or p18.split("^")[0] not in ("1", "2")):
        rep.fail(typ, "P5", where)


# ----------------------------------------------------------------------------------------------- the walk
_NAME = re.compile(r"^[0-9A-Za-z]+$")


def check_standard(root: Path, rep: Report, exclude: tuple[str, ...] = ()) -> None:
    records: dict[tuple[str, ...], list[tuple[str, str, str]]] = defaultdict(list)
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).parts
        if rel[0] in exclude:
            continue
        typ = rel[-2] if len(rel) >= 2 else "?"
        where = "/".join(rel)
        if len(rel) != 6 or rel[0] != rel[2][0:3] or rel[1] != rel[2][3:6]:
            rep.files[typ if len(rel) == 6 else "?"] += 1
            rep.fail(typ if len(rel) == 6 else "?", "T1", where)
            continue
        _a, _b, pid, day, typ, name = rel
        rep.files[typ] += 1
        if len(pid) < 6 or not _NAME.match(pid):
            rep.fail(typ, "T2", where)
        if day != "-" and not (len(day) == 8 and _real(day)):
            rep.fail(typ, "T3", where)
        if typ not in TYPES:
            rep.fail(typ, "T4", where)
        parts = name.split("_")
        if len(parts) != 7 or parts[:3] != [pid, day, typ] or not all(parts):
            rep.fail(typ, "N1", where)
            continue
        stamp, flag = parts[4], parts[6]
        if not (len(stamp) == 17 and stamp.isdigit() and _real(stamp[:14], "%Y%m%d%H%M%S")):
            rep.fail(typ, "N2", where)
        if flag not in ("0", "1", "2"):
            rep.fail(typ, "N3", where)
        if typ in ALL9_TYPES and parts[3] != "ALL9" and not re.fullmatch(r"9{4,}", parts[3]):
            rep.fail(typ, "N4", where)
        if check_message(typ, path.read_bytes(), parts, rep, where):
            rep.messages[typ] += 1
        records[pid, day, typ, parts[3]].append((stamp, flag, where))
    for key, files in records.items():
        files.sort()
        live = [f for f in files if f[1] == "1"]
        if len(live) > 1 or (live and live[0] != files[-1]):
            rep.fail(key[2], "K1", files[-1][2])
        if files[-1][1] == "0" and any(f[1] != "0" for f in files):
            rep.fail(key[2], "K2", files[-1][2])
        if len({f[0] for f in files}) != len(files):
            rep.fail(key[2], "K3", files[-1][2])


_KIND = re.compile(r"^[0-9A-Za-z\-　-ヿ㐀-鿿＀-￯]*$")
_LOINC = re.compile(r"^\d{1,7}-\d$")


def _loinc_check(code: str) -> bool:
    """LOINC's mod-10 check digit (the standard part of E 2.2 (4) ③ is a LOINC code)."""
    if not _LOINC.match(code):
        return False
    body, check = code.split("-")
    digits = [int(d) for d in body][::-1]
    total = sum(sum(divmod(d * 2, 10)) if i % 2 == 0 else d for i, d in enumerate(digits))
    return (10 - total % 10) % 10 == int(check)


def check_extended(root: Path, rep: Report) -> None:
    typ = "extended"
    seen: set[Path] = set()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).parts
        where = "/".join(rel)
        rep.files[typ] += 1
        if len(rel) < 7 or rel[0] != rel[2][0:3] or rel[1] != rel[2][3:6]:
            rep.fail(typ, "X1" if len(rel) != 6 else "X4", where)
            continue
        _a, _b, pid, day, kind, folder = rel[:6]
        fmt = {4: "%Y", 6: "%Y%m", 8: "%Y%m%d"}.get(len(day), "")
        if not (day == "-" or (fmt and day.isdigit() and _real(day, fmt))):
            rep.fail(typ, "X2", where)
        c = (kind.split("^") + [""] * 6)[:6]
        if (
            kind.count("^") != 5
            or not (c[3] and c[4])
            or c[5] != "LN"
            or not _loinc_check(c[3])
            or (c[0] and not c[0].startswith("L"))
            or (c[2] and not _LOCAL.match(c[2]))
            or len(kind) > 180
            or not all(_KIND.match(x) for x in c)
        ):
            rep.fail(typ, "X3", where)
        parts = folder.split("_")
        if (
            len(parts) != 7
            or parts[0] != pid
            or parts[1] != day
            or not all(parts)
            or parts[6] not in ("0", "1", "2")
            or not (len(parts[4]) == 17 and parts[4].isdigit())
        ):
            rep.fail(typ, "X5", where)
        if path.name == "_contents.xml":
            _check_contents(path, rep, where)
        elif path.suffix.lower() not in EXTENSIONS:
            rep.fail(typ, "X6", where)
        if path.parent not in seen:
            seen.add(path.parent)
            rep.messages[typ] += 1


def _xml_root(data: bytes) -> object:
    """The root element of ``_contents.xml``, refusing a document type or an entity declaration before anything is
    parsed (the pattern of ``tools/public_accuracy/sets.py``: no entity can then be declared, expand or load)."""
    from xml.etree import ElementTree as ET

    text = data.decode("utf-8", errors="replace")
    for decl in ("<!DOCTYPE", "<!ENTITY"):
        if decl in text:
            raise ValueError(decl)
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("start",))
    parser.feed(text)
    parser.close()
    for event in parser.read_events():
        if len(event) == 2 and isinstance(event[1], ET.Element):
            return event[1]
    raise ValueError("no element")


def _check_contents(path: Path, rep: Report, where: str) -> None:
    from xml.etree import ElementTree as ET

    try:
        doc = _xml_root(path.read_bytes())
    except (ValueError, ET.ParseError):
        rep.fail("extended", "X7", where)
        return
    assert isinstance(doc, ET.Element)
    docs = doc.findall("Document")
    vendor = doc.get("createVender") or doc.get("createVendor")  # 表2.2-2 spells it Vender, its example Vendor
    bad_doc = any(d.get("name") is None or not d.get("mime") or d.get("relDir") is None for d in docs)
    if doc.tag != "Contents" or not doc.get("createDateTime") or not vendor or not docs or bad_doc:
        rep.fail("extended", "X7", where)


def check(root: Path, extended: Path | None = None, exclude: tuple[str, ...] = ()) -> Report:
    rep = Report()
    skip = tuple(exclude) + ((extended.name,) if extended and extended.parent == root else ())
    check_standard(root, rep, skip)
    if extended and extended.is_dir():
        check_extended(extended, rep)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path, help="the standardised storage's root folder")
    ap.add_argument("--extended", type=Path, help="the extended storage's root folder")
    ap.add_argument("--exclude", nargs="*", default=[], help="folders under the root that are not SS-MIX2")
    ap.add_argument("--list", type=int, default=1, help="examples printed per type and rule")
    ap.add_argument("--rules", action="store_true", help="print the rules with their sources and stop")
    args = ap.parse_args(argv)
    if args.rules:
        print("\n".join(f"{k}  {v}" for k, v in RULES.items()))
        return 0
    rep = check(args.root, args.extended, tuple(args.exclude))
    print("\n".join(rep.lines(args.list)))
    return 1 if rep.total else 0


if __name__ == "__main__":
    raise SystemExit(main())
