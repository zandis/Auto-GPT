"""Probe inputs for card 10B-2b (D-1252): supersession across files and days, and the disease-name modifier codes.

Written before the implementation, each case labelled with the reading the published documents give (D-1252 cites
them; nothing of them is copied here):

* G: SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン Ver.1.2j (JAMI, 2026-08-14), 3.1.2 and 3.1.4;
* S: SS-MIX2 標準化ストレージ 仕様書 Ver.1.2j (JAMI, 2026-08-14), 3.7.3 (PRB) and 3.7.4 (ZPR);
* M: ICD10対応標準病名マスター Ver.5.18 仕様書 (MEDIS-DC, 2026-06), the 修飾語テーブル.

Every storage is synthetic: made-up patients (the kit's ``10000001`` range), made-up order, diagnosis and master
codes (eight-digit numbers starting ``9999`` for 病名管理番号, ``9998`` for 修飾語管理番号, four characters starting
``Z`` for exchange codes). The modifier master below is a synthetic table with M's column names and made-up rows;
no row of the licensed master is in the repository.

A case is run as nights over one lake: each night writes the files that arrive that night, reads the whole storage
with a fresh reader, then applies the night as the adapter does (``ndjson.write_snapshot``): the night's live rows
over the lake, and the ids the reader tombstones removed unless sent again live that night. The label says what the
lake must hold at the end, per id:

* ``CA``: confirmed and active (a diagnosis with status ``A`` and an empty ``suspected``; an order line with status
  ``active``);
* ``NC``: present but not confirmed and active (unknown, ended, suspected, cancelled, ...);
* ``GONE``: not in the lake.

A reading is wrong when the lake differs from the label; it is dangerous when an id is ``CA`` where the label is
not, or when the lake holds a ``CA`` id the case does not name at all. ``python -m tests.ssmix2_probes`` prints the
counts and, with ``--json``, every id's reading, so two heads can be compared.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

P1, P2 = "10000001", "10000002"
DAY_A, DAY_B, DAY_C = "20261001", "20261002", "20261003"
DEPT = "01"


# ------------------------------------------------------------------------------------------------ messages
def msh(kind: str, control: str = "C1", when: str = "20261001090000") -> str:
    return f"MSH|^~\\&|HIS|SENDER|GW|RECEIVER|{when}||{kind}|{control}|P|2.5||||||~ISO IR87"


def pid(patient: str) -> str:
    return f"PID|||{patient}^^^^PI||"


def omp(patient: str, number: str, day: str, lines: list[tuple[str, str, str]], *, orc5: str = "IP") -> list[str]:
    """OMP-01 (RDE^O11): one ORC / RXE / TQ1 group per line ``(ORC-1, Rp number, drug code)``; ORC-2 the order
    number, ORC-9 the day, RXE-3 one dose, TQ1-3 "1日1回"."""
    segs = [msh("RDE^O11^RDE_O11", f"RX{number}", f"{day}090000"), pid(patient)]
    for orc1, rp, drug in lines:
        segs.append("|".join(["ORC", orc1, number, "", rp, orc5, "", "", "", f"{day}0900"]))
        rxe = ["RXE", "", f"{drug}^薬剤{drug[-2:]}^HOT9", "1", "", "TAB^錠^MR9P"] + [""] * 26
        segs.append("|".join(rxe))
        segs.append("|".join(["TQ1", "1", "", "U01&1日1回朝食後&99XYZ", "", "", "", day, ""]))
    return segs


def prb(
    number: str,
    name: str,
    dx: str,
    *,
    action: str = "AD",
    system: str = "MDCDX2",
    icd10: str | None = None,
    outcome: str = "",
    end: str = "",
    written: str = "",
    flag13: str = "",
) -> str:
    """One PRB (S 3.7.3, 表3-47): PRB-3 ``病名管理番号^表示病名^MDCDX2``, PRB-4 the diagnosis id, PRB-10 ICD-10."""
    f = ["PRB", action, "20260901090000", f"{number}^{name}^{system}" if number or name else "", dx] + [""] * 14
    f[7] = "20260901"
    f[9] = end
    if icd10 is None:  # the disease's own ICD-10 in the synthetic master; J18.9 for a code it does not hold
        icd10 = DISEASES.get(number, ("", "", "J189"))[2].replace(".", "")
    f[10] = f"{icd10}^^I10^O^外来時^JHSD0004" if icd10 else ""
    f[13] = flag13
    f[14] = outcome
    f[17] = written
    return "|".join(f)


def ppr(patient: str, body: list[str], when: str = "20261001090000") -> list[str]:
    return [msh("PPR^ZD1^PPR_ZD1", "PPR1", when), pid(patient), *body]


# ------------------------------------------------------------------------------------------------ files and cases
@dataclass
class F:
    """One standardised-storage file. ``raw`` replaces the message bytes (an unreadable file); ``folder_patient``
    files it under another patient's folders than its name says."""

    patient: str
    day: str
    typ: str
    order: str
    stamp: str
    flag: str
    segs: list[str] = field(default_factory=list)
    night: int = 0
    dept: str = DEPT
    raw: bytes | None = None
    folder_patient: str = ""
    name: str = ""  # the file's name exactly, when it is not built from the parts (a malformed name)

    def write(self, root: Path) -> None:
        fp = self.folder_patient or self.patient
        d = root / fp[0:3] / fp[3:6] / fp / self.day / self.typ
        d.mkdir(parents=True, exist_ok=True)
        data = self.raw if self.raw is not None else ("\r".join(self.segs) + "\r").encode("iso2022_jp")
        name = self.name or f"{self.patient}_{self.day}_{self.typ}_{self.order}_{self.stamp}_{self.dept}_{self.flag}"
        (d / name).write_bytes(data)


@dataclass
class Case:
    name: str
    family: str
    table: str
    files: list[F]
    expect: dict[str, str]  # "<mrn>/<key>" -> CA, NC or GONE
    order_key: str = "per_day"
    licensed: str = ""  # "" no master, "master" the synthetic modifier master
    limit: bool = False  # a case of the stated limit (display text only, no licensed master)


def stamp(day: str, n: int) -> str:
    """The n-th 発生日時 of a day: 09:00:00.000 plus n minutes."""
    return f"{day}09{n:02d}00000"


# ------------------------------------------------------------------------------------------------ the master
#: a synthetic 病名基本テーブル (M (1)): 病名管理番号 -> (病名表記, 病名交換用コード, ICD10)
DISEASES = {
    "99990001": ("肺炎", "ZA01", "J189"),
    "99990002": ("胃炎", "ZA02", "K297"),
    "99990003": ("関節リウマチ", "ZA03", "M069"),
    "99990004": ("高血圧症", "ZA04", "I10"),
    "99990005": ("糖尿病", "ZA05", "E149"),
    "99990006": ("気管支炎", "ZA06", "J40"),
    "99990007": ("細菌性肺炎", "ZA07", "J159"),  # a modified name the master codes on its own (class 3 case)
    "99990008": ("咽頭炎", "ZA08", "J029"),  # retired in this release (変更区分 1)
    "99990009": ("喉頭炎", "ZA09", "J040"),  # a 変更区分 the specification does not define
}
DISEASE_CHANGE = {"99990008": "1", "99990009": "X"}
#: a synthetic 修飾語テーブル (M (2)): 修飾語管理番号 -> (変更区分, 修飾語表記, 修飾語交換用コード, 接続位置区分,
#: 修飾語区分). The class is the second character of 修飾語区分 (M (2)⑦). Words are ordinary Japanese; codes made up.
MODIFIERS = {
    "99980001": ("0", "下葉", "ZM01", "50", "21000000"),  # 部位 (class 1), before the name
    "99980002": ("0", "左", "ZM02", "60", "22000000"),  # 位置 (2)
    "99980003": ("0", "右", "ZM03", "60", "22000001"),  # 位置 (2)
    "99980004": ("0", "細菌性", "ZM04", "40", "23000000"),  # 病因 (3)
    "99980005": ("0", "急性", "ZM05", "30", "24000000"),  # 経過表現 (4)
    "99980006": ("0", "慢性", "ZM06", "30", "24000001"),  # 経過表現 (4)
    "99980007": ("0", "重症", "ZM07", "20", "25000000"),  # 状態表現 (5)
    "99980008": ("0", "老人性", "ZM08", "20", "26000000"),  # 患者帰属 (6)
    "99980009": ("0", "高度", "ZM09", "20", "27000000"),  # その他 (7)
    "99980010": ("0", "の疑い", "ZM10", "1", "28000000"),  # 接尾語 (8), after the name
    "99980011": ("0", "術後", "ZM11", "1", "28000001"),  # 接尾語 (8)
    "99980012": ("0", "第１大臼歯", "ZM12", "10", "29000000"),  # 歯科 (9)
    "99980013": ("1", "旧左", "ZM13", "60", "22000002"),  # retired in this version (変更区分 1)
    "99980014": ("0", "不明区分", "ZM14", "20", "20000000"),  # a class character outside 1 to 9
    "99980015": ("0", "の後遺症", "ZM15", "1", "28000002"),  # 接尾語 (8)
    "99980016": ("3", "上", "ZM16", "60", "22000003"),  # 位置 (2), added in this release: current
    "99980017": ("5", "下", "ZM17", "60", "22000004"),  # 位置 (2), changed in this release: current
    "99980018": ("D", "前", "ZM18", "60", "22000005"),  # a 変更区分 the specification does not define
    "99980019": ("9", "後", "ZM19", "60", "22000006"),  # a 変更区分 the specification does not define
    "99980020": ("", "外", "ZM20", "60", "22000007"),  # no 変更区分
    "99980021": ("0", "左", "ZM21", "60", "022000000"),  # a 修飾語区分 of nine characters
    "99980022": ("0", "右", "ZM22", "60", "2200000"),  # a 修飾語区分 of seven characters
}


def licensed_tables(kind: str) -> dict[str, dict[str, dict[str, str]]]:
    """The ``licensed=`` argument: nothing, or the synthetic master shaped as ``adapter.licensed.tables()`` gives a
    loaded release (``code -> {display, target_system, target_code, extra}``)."""
    if kind != "master":
        return {"medis": {}, "jlac10": {}, "yj": {}, "medis_modifier": {}}
    medis = {
        ex: {
            "display": name,
            "target_system": "http://hl7.org/fhir/sid/icd-10",
            "target_code": icd,
            "extra": json.dumps({"management_no": no, "change": DISEASE_CHANGE.get(no, "0")}, ensure_ascii=False),
        }
        for no, (name, ex, icd) in DISEASES.items()
    }
    mods = {
        no: {
            "display": word,
            "target_system": "",
            "target_code": "",
            "extra": json.dumps(
                {"change": chg, "exchange_code": ex, "position": pos, "modifier_class": cls}, ensure_ascii=False
            ),
        }
        for no, (chg, word, ex, pos, cls) in MODIFIERS.items()
    }
    return {"medis": medis, "jlac10": {}, "yj": {}, "medis_modifier": mods}


# ------------------------------------------------------------------------------------------------ supersession
def _rx(i: int) -> str:
    return f"RX{i:04d}"


def _expect_versions(versions: list[tuple[int, str, str]]) -> str:
    """The reading of one key's versions ``(stamp rank, flag, content)`` (content ``A`` an active order, ``C`` a
    cancelled one) by G 3.1.4 and D-1252's rules for what G does not say."""
    top = max(r for r, _f, _c in versions)
    newest = [(f, c) for r, f, c in versions if r == top]
    if any(f == "0" for f, _c in newest):
        return "GONE"  # a deletion wins a tie (G ⑥2): every file of the key is 0)
    if len(newest) > 1:
        return "NC"  # two versions with one 発生日時: which is in force cannot be told (D-1252 P5)
    f, c = newest[0]
    if f == "2":
        return "NC"  # no version in force (D-1252 P3)
    return "CA" if c == "A" else "NC"


def supersession_cases() -> list[Case]:
    cases: list[Case] = []
    n = 0

    # A. one key, one to three versions, every flag, one night and two arrival orders (G 3.1.4(2)⑥, (3)①)
    for size in (1, 2, 3):
        for flags in itertools.product("120", repeat=size):
            for arrival in ("one night", "newest last", "newest first") if size > 1 else ("one night",):
                n += 1
                no = _rx(n)
                vers = [(i, fl, "A") for i, fl in enumerate(flags)]
                files = []
                for i, fl in enumerate(flags):
                    night = 0
                    if arrival == "newest last" and i == size - 1:
                        night = 1
                    if arrival == "newest first" and i != size - 1:
                        night = 1
                    lines = [("NW", "1", f"9990000{i:02d}")]
                    files.append(F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, i), fl, omp(P1, no, DAY_A, lines),
                                   night=night))  # fmt: skip
                want = _expect_versions(vers)
                cases.append(Case(f"versions {''.join(flags)} {arrival}", "A versions", "medication", files,
                                  {f"{P1}/{no}": want}))  # fmt: skip

    # A2. the in-force version cancels the order (ORC-1 CA): not active, whatever the older version said
    for flags in (("1", "1"), ("2", "1"), ("0", "1")):
        n += 1
        no = _rx(n)
        files = [
            F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 0), flags[0], omp(P1, no, DAY_A, [("NW", "1", "999000001")])),
            F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 1), flags[1], omp(P1, no, DAY_A, [("CA", "1", "999000001")]),
              night=1),
        ]  # fmt: skip
        cases.append(Case(f"newest version cancels ({''.join(flags)})", "A versions", "medication", files,
                          {f"{P1}/{no}": "NC"}))  # fmt: skip

    # B. the newest version cannot be read: the older is never read as in force (D-1252 P4)
    bad: dict[str, Callable[[str], F]] = {
        "garbage bytes": lambda no: F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 5), "1", raw=b"\x00\xff not hl7"),
        "another patient in PID-3": lambda no: F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 5), "1",
                                                 omp(P2, no, DAY_A, [("NW", "1", "999000002")])),
        "no PID": lambda no: F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 5), "1",
                               [s for s in omp(P1, no, DAY_A, [("NW", "1", "999000002")]) if not s.startswith("PID")]),
        "filed in another patient's folder": lambda no: F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 5), "1",
                                                          omp(P1, no, DAY_A, [("NW", "1", "999000002")]),
                                                          folder_patient=P2),
        "an undeclared ambiguous encoding": lambda no: F(
            P1, DAY_A, "OMP-01", no, stamp(DAY_A, 5), "1",
            raw=("\r".join(omp(P1, no, DAY_A, [("NW", "1", "999000002")])).replace("~ISO IR87", "")
                 + "\rNTE|1||ｱｲｳ\r").encode("euc_jp")),
    }  # fmt: skip
    for why, make in bad.items():
        for same_night in (True, False):
            n += 1
            no = _rx(n)
            newest = make(no)
            newest.night = 0 if same_night else 1
            files = [F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 0), "1", omp(P1, no, DAY_A, [("NW", "1", "999000001")])),
                     newest]  # fmt: skip
            label = "NC"
            if why == "filed in another patient's folder":
                # the misfiled file is a newer version of P1's key that cannot be read as P1's
                label = "NC"
            cases.append(Case(f"newest unreadable: {why} ({'one night' if same_night else 'later night'})",
                              "B unreadable newest", "medication", files, {f"{P1}/{no}": label}))  # fmt: skip

    # C. ties: two files with one 発生日時 (told apart by the 診療科 part of the name)
    for pair in (("1", "1"), ("1", "0"), ("0", "1"), ("2", "1"), ("2", "0"), ("2", "2")):
        for night in (0, 1):
            n += 1
            no = _rx(n)
            files = [
                F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 3), pair[0], omp(P1, no, DAY_A, [("NW", "1", "999000001")]),
                  dept="01"),
                F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 3), pair[1], omp(P1, no, DAY_A, [("NW", "1", "999000002")]),
                  dept="02", night=night),
            ]  # fmt: skip
            want = "GONE" if "0" in pair else "NC"
            cases.append(Case(f"tie {''.join(pair)} night {night}", "C ties", "medication", files,
                              {f"{P1}/{no}": want}))  # fmt: skip

    # D. across days under the per_day key (G: 診療日 is in the key; D-1252 P6 for an order number on two days)
    def day_files(no: str, b_flag: str, b_rank: int, b_night: int, b_raw: bool = False) -> list[F]:
        a = F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 0), "1", omp(P1, no, DAY_A, [("NW", "1", "999000001")]))
        b = F(P1, DAY_B, "OMP-01", no, stamp(DAY_B, 0), b_flag,
              omp(P1, no, DAY_B, [("NW", "1", "999000001")]), night=b_night)  # fmt: skip
        if b_rank < 0:  # the day-B file written before the day-A one (older 発生日時)
            a.stamp = stamp(DAY_A, 5)
            b.stamp = stamp(DAY_A, 1)
        if b_raw:
            b.raw = b"\x00\xff not hl7"
        return [a, b]

    cross = [
        # (what day B holds, B flag, B newer(1)/older(-1), raw, label A, label B)
        ("a delete", "0", 1, False, "NC", "GONE"),
        ("a newer live version", "1", 1, False, "NC", "CA"),
        ("an older live version", "1", -1, False, "CA", "NC"),
        ("a past-history file only", "2", 1, False, "NC", "NC"),
        # day B's only file cannot be read: it names nothing (no row of day B), and day A is not in force
        ("an unreadable newer file", "1", 1, True, "NC", "GONE"),
    ]
    for what, bflag, rank, raw, la, lb in cross:
        for b_night, arrival in ((0, "one night"), (1, "day B later"), (2, "day B much later")):
            n += 1
            no = _rx(n)
            files = day_files(no, bflag, rank, b_night, raw)
            exp = {f"{P1}/{no}@{DAY_A}": la, f"{P1}/{no}": "GONE"}
            exp[f"{P1}/{no}@{DAY_B}"] = lb
            cases.append(Case(f"day B holds {what} ({arrival})", "D across days", "medication", files, exp))
        # the same storage read under the site's declared ``unique`` key: one record, the newest version decides
        n += 1
        no = _rx(n)
        files = day_files(no, bflag, rank, 1, raw)
        want = _expect_versions([(0 if rank > 0 else 1, "1", "A"), (1 if rank > 0 else 0, bflag, "A")])
        if raw:
            want = "NC"
        cases.append(Case(f"day B holds {what} (unique key)", "D across days", "medication", files,
                          {f"{P1}/{no}": want}, order_key="unique"))  # fmt: skip
    # three days: a delete on day C reaches neither A nor B, which both become unknown
    for night in (0, 1):
        n += 1
        no = _rx(n)
        files = [
            F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 0), "1", omp(P1, no, DAY_A, [("NW", "1", "999000001")])),
            F(P1, DAY_B, "OMP-01", no, stamp(DAY_B, 0), "1", omp(P1, no, DAY_B, [("NW", "1", "999000001")])),
            F(P1, DAY_C, "OMP-01", no, stamp(DAY_C, 0), "0", omp(P1, no, DAY_C, [("CA", "1", "999000001")]),
              night=night),
        ]  # fmt: skip
        exp = {
            f"{P1}/{no}": "GONE",
            f"{P1}/{no}@{DAY_A}": "NC",
            f"{P1}/{no}@{DAY_B}": "NC",
            f"{P1}/{no}@{DAY_C}": "GONE",
        }
        cases.append(Case(f"three days, delete on the last (night {night})", "D across days", "medication", files, exp))
    # an order number on two days of two different patients is no link
    for night in (0, 1):
        n += 1
        no = _rx(n)
        files = [
            F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 0), "1", omp(P1, no, DAY_A, [("NW", "1", "999000001")])),
            F(P2, DAY_B, "OMP-01", no, stamp(DAY_B, 0), "0", omp(P2, no, DAY_B, [("CA", "1", "999000001")]),
              night=night),
        ]  # fmt: skip
        cases.append(Case(f"same number, other patient deletes (night {night})", "D across days", "medication",
                          files, {f"{P1}/{no}": "CA", f"{P2}/{no}": "GONE"}))  # fmt: skip

    # E. one order, several lines: a newer version replaces the whole order (G 3.1.2(2): one file, one order)
    two = [("NW", "1", "999000001"), ("NW", "2", "999000002")]
    line_cases = [
        ("drops line 2", [("NW", "1", "999000001")], "1", {"1": "CA", "2": "GONE"}),
        ("cancels line 1, keeps line 2", [("CA", "1", "999000001"), ("NW", "2", "999000002")], "1",
         {"1": "NC", "2": "CA"}),
        ("cancels line 2, keeps line 1", [("NW", "1", "999000001"), ("CA", "2", "999000002")], "1",
         {"1": "CA", "2": "NC"}),
        ("holds only cancelled line 1", [("CA", "1", "999000001")], "1", {"1": "NC", "2": "GONE"}),
        ("is a deletion", two, "0", {"1": "GONE", "2": "GONE"}),
        ("adds line 3", [*two, ("NW", "3", "999000003")], "1", {"1": "CA", "2": "CA", "3": "CA"}),
        ("is past history only", two, "2", {"1": "NC", "2": "NC"}),
    ]  # fmt: skip
    for what, newer, flag, labels in line_cases:
        for night in (0, 1):
            n += 1
            no = _rx(n)
            files = [
                F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 0), "1", omp(P1, no, DAY_A, two)),
                F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 1), flag, omp(P1, no, DAY_A, newer), night=night),
            ]
            drug = {"1": "999000001", "2": "999000002", "3": "999000003"}
            exp = {f"{P1}/{no}#{rp}:{drug[rp]}": want for rp, want in labels.items()}
            if len(newer) == 1 and flag == "1":
                # a version of one line keys it by the plain order number (#1095): the old line keys are gone
                exp = {f"{P1}/{no}#{rp}:{drug[rp]}": "GONE" for rp in labels}
                exp[f"{P1}/{no}"] = "CA" if newer[0][0] == "NW" else "NC"
            cases.append(Case(f"newer version {what} (night {night})", "E order lines", "medication", files, exp))

    # F. the same key written in other widths or with a blank (D-1252 P8): one key
    variants = [("full-width digits", "RX{:04d}", "RX{}"), ("full-width letters", "RX{:04d}", "ＲＸ{}")]
    for what, plain, other in variants:
        for flag in ("0", "1", "2"):
            for night in (0, 1):
                n += 1
                no = plain.format(n)
                digits = f"{n:04d}"
                wide = other.format(digits.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
                                    if what == "full-width digits" else digits)  # fmt: skip
                files = [
                    F(P1, DAY_A, "OMP-01", no, stamp(DAY_A, 0), "1", omp(P1, no, DAY_A, [("NW", "1", "999000001")])),
                    F(P1, DAY_A, "OMP-01", wide, stamp(DAY_A, 1), flag, omp(P1, no, DAY_A, [("NW", "1", "999000002")]),
                      night=night),
                ]  # fmt: skip
                want = {"0": "GONE", "1": "CA", "2": "NC"}[flag]
                cases.append(Case(f"{what} in the newer name, flag {flag} (night {night})", "F key widths",
                                  "medication", files, {f"{P1}/{no}": want}))  # fmt: skip

    # G. PPR-01 snapshots (G 3.1.2(2): one file per patient, all diagnoses, 診療日 "-", ALL9)
    cases += snapshot_cases()
    return cases


def _dx(i: int) -> str:
    return f"DX{i:03d}"


def snapshot_cases() -> list[Case]:
    cases: list[Case] = []
    a, b = prb("99990001", "肺炎", "DX001"), prb("99990002", "胃炎", "DX002", icd10="K297")
    a_end = prb("99990001", "肺炎", "DX001", end="20260920")
    p = P1

    def snap(day: str, n: int, flag: str, body: list[str], night: int = 0, raw: bytes | None = None) -> F:
        return F(p, day, "PPR-01", "ALL9", stamp(DAY_A, n), flag, ppr(p, body), night=night, raw=raw)

    def k(dx: str) -> str:
        return f"{p}/{dx}"

    plans: list[tuple[str, list[Callable[[int], F]], dict[str, str]]] = [
        ("newer drops DX002", [lambda nt: snap("-", 0, "1", [a, b]), lambda nt: snap("-", 1, "1", [a], nt)],
         {k("DX001"): "CA", k("DX002"): "GONE"}),
        ("newer ends DX001", [lambda nt: snap("-", 0, "1", [a, b]), lambda nt: snap("-", 1, "1", [a_end, b], nt)],
         {k("DX001"): "NC", k("DX002"): "CA"}),
        ("newer deletes the snapshot", [lambda nt: snap("-", 0, "1", [a, b]), lambda nt: snap("-", 1, "0", [a, b], nt)],
         {k("DX001"): "GONE", k("DX002"): "GONE"}),
        ("older renamed to 2, newer in force", [lambda nt: snap("-", 0, "2", [a, b]),
                                                lambda nt: snap("-", 1, "1", [a], nt)],
         {k("DX001"): "CA", k("DX002"): "GONE"}),
        ("newest is past history only", [lambda nt: snap("-", 0, "1", [a, b]), lambda nt: snap("-", 1, "2", [a, b], nt)],
         {k("DX001"): "NC", k("DX002"): "NC"}),
        ("newest unreadable", [lambda nt: snap("-", 0, "1", [a, b]),
                               lambda nt: snap("-", 1, "1", [], nt, raw=b"\x00\xff not hl7")],
         {k("DX001"): "NC", k("DX002"): "NC"}),
        ("newest names another patient", [lambda nt: snap("-", 0, "1", [a, b]),
                                          lambda nt: F(p, "-", "PPR-01", "ALL9", stamp(DAY_A, 1), "1",
                                                       ppr(P2, [a, b]), night=nt)],
         {k("DX001"): "NC", k("DX002"): "NC"}),
        ("newest holds a duplicate number", [lambda nt: snap("-", 0, "1", [a, b]),
                                             lambda nt: snap("-", 1, "1", [a, prb("99990002", "胃炎", "DX001")], nt)],
         {k("DX001"): "NC", k("DX002"): "NC"}),
        ("tie live and live", [lambda nt: snap("-", 1, "1", [a, b]),
                               lambda nt: F(p, "-", "PPR-01", "ALL9", stamp(DAY_A, 1), "1", ppr(p, [a]), night=nt,
                                            dept="02")],
         {k("DX001"): "NC", k("DX002"): "NC"}),
        ("tie live and deleted", [lambda nt: snap("-", 1, "1", [a, b]),
                                  lambda nt: F(p, "-", "PPR-01", "ALL9", stamp(DAY_A, 1), "0", ppr(p, [a, b]), night=nt,
                                               dept="02")],
         {k("DX001"): "GONE", k("DX002"): "GONE"}),
        ("a snapshot in a day folder supersedes one under -", [lambda nt: snap("-", 0, "1", [a, b]),
                                                               lambda nt: snap(DAY_B, 1, "1", [b], nt)],
         {k("DX001"): "GONE", k("DX002"): "CA"}),
        ("an older snapshot in a day folder is superseded", [lambda nt: snap(DAY_B, 0, "1", [a, b]),
                                                             lambda nt: snap("-", 1, "1", [b], nt)],
         {k("DX001"): "GONE", k("DX002"): "CA"}),
        ("DE in the newest", [lambda nt: snap("-", 0, "1", [a, b]),
                              lambda nt: snap("-", 1, "1", [a, prb("99990002", "胃炎", "DX002", action="DE")], nt)],
         {k("DX001"): "CA", k("DX002"): "GONE"}),
        ("DE in the older, added again in the newest", [
            lambda nt: snap("-", 0, "1", [a, prb("99990002", "胃炎", "DX002", action="DE")]),
            lambda nt: snap("-", 1, "1", [a, b], nt)],
         {k("DX001"): "CA", k("DX002"): "CA"}),
        ("three snapshots, the middle one deleted", [lambda nt: snap("-", 0, "1", [a, b]),
                                                     lambda nt: snap("-", 1, "0", [a, b]),
                                                     lambda nt: snap("-", 2, "1", [b], nt)],
         {k("DX001"): "GONE", k("DX002"): "CA"}),
        ("an older snapshot arrives after the newest", [lambda nt: snap("-", 1, "1", [b]),
                                                        lambda nt: snap("-", 0, "1", [a, b], nt)],
         {k("DX001"): "GONE", k("DX002"): "CA"}),
    ]  # fmt: skip
    for what, makers, exp in plans:
        for night in (0, 1):
            files = [m(night if i == len(makers) - 1 else 0) for i, m in enumerate(makers)]
            cases.append(Case(f"snapshot: {what} (night {night})", "G snapshots", "diagnosis", files, dict(exp)))

    # the per-diagnosis layout (TrialBox's exporter; not G's): versions per key, and beside a snapshot (D-1252 P9)
    def per(dx: str, day: str, n: int, flag: str, body: list[str], night: int = 0) -> F:
        return F(p, day, "PPR-01", dx, stamp(DAY_A, n), flag, ppr(p, body), night=night)

    per_plans: list[tuple[str, list[Callable[[int], F]], dict[str, str]]] = [
        ("per-diagnosis file, newer version ends it", [lambda nt: per("DX001", DAY_A, 0, "1", [a]),
                                                      lambda nt: per("DX001", DAY_A, 1, "1", [a_end], nt)],
         {k("DX001"): "NC"}),
        ("per-diagnosis file deleted", [lambda nt: per("DX001", DAY_A, 0, "1", [a]),
                                        lambda nt: per("DX001", DAY_A, 1, "0", [a], nt)],
         {k("DX001"): "GONE"}),
        ("per-diagnosis file older than a snapshot that lacks it", [
            lambda nt: per("DX001", DAY_A, 0, "1", [a]), lambda nt: snap("-", 1, "1", [b], nt)],
         {k("DX001"): "GONE", k("DX002"): "CA"}),
        ("per-diagnosis file older than a snapshot that holds it", [
            lambda nt: per("DX001", DAY_A, 0, "1", [a_end]), lambda nt: snap("-", 1, "1", [a, b], nt)],
         {k("DX001"): "CA", k("DX002"): "CA"}),
        ("per-diagnosis file newer than the snapshot", [
            lambda nt: snap("-", 0, "1", [a, b]), lambda nt: per("DX001", DAY_A, 1, "1", [a], nt)],
         {k("DX001"): "NC", k("DX002"): "CA"}),
        ("one diagnosis number in two per-diagnosis files of two days", [
            lambda nt: per("DX001", DAY_A, 0, "1", [a]), lambda nt: per("DX001", DAY_B, 1, "1", [a], nt)],
         {k("DX001"): "NC"}),
        ("one diagnosis number under two order numbers", [
            lambda nt: per("DX001", DAY_A, 0, "1", [a]), lambda nt: per("DX009", DAY_A, 1, "1", [a], nt)],
         {k("DX001"): "NC"}),
    ]  # fmt: skip
    for what, makers, exp in per_plans:
        for night in (0, 1):
            files = [m(night if i == len(makers) - 1 else 0) for i, m in enumerate(makers)]
            cases.append(Case(f"{what} (night {night})", "G per-diagnosis files", "diagnosis", files, dict(exp)))
    return cases


# ------------------------------------------------------------------------------------------------ modifiers
def zpr(pre: Sequence[str] = (), dis: str = "", suf: Sequence[str] = (), pre_ex: Sequence[str] = (), dis_ex: str = "",
        suf_ex: Sequence[str] = (), comment: str = "") -> str:  # fmt: skip
    """ZPR (S 3.7.4, 表3-48): ZPR-1 prefix 修飾語管理番号 (repeating), ZPR-2 病名管理番号, ZPR-3 suffix 修飾語管理番号,
    ZPR-4 / ZPR-6 their 修飾語交換用コード, ZPR-5 病名交換用コード, ZPR-7 a comment. Codes as ``code^text^MDCDX2``."""

    def coded(code: str, table: dict[str, Any], idx: int) -> str:
        if not code:
            return ""
        word = table[code][idx] if code in table else "不明"
        return f"{code}^{word}^MDCDX2"

    def mod_ex(code: str) -> str:
        hit = next(((no, v) for no, v in MODIFIERS.items() if v[2] == code), None)
        return f"{code}^{hit[1][1]}^MDCDX2" if hit else (f"{code}^不明^MDCDX2" if code else "")

    def dis_exc(code: str) -> str:
        hit = next(((no, v) for no, v in DISEASES.items() if v[1] == code), None)
        return f"{code}^{hit[1][0]}^MDCDX2" if hit else (f"{code}^不明^MDCDX2" if code else "")

    return "|".join([
        "ZPR",
        "~".join(coded(c, MODIFIERS, 1) for c in pre),
        coded(dis, DISEASES, 0),
        "~".join(coded(c, MODIFIERS, 1) for c in suf),
        "~".join(mod_ex(c) for c in pre_ex),
        dis_exc(dis_ex),
        "~".join(mod_ex(c) for c in suf_ex),
        comment,
    ])  # fmt: skip


def _mword(no: str) -> str:
    return MODIFIERS[no][1]


def _mex(no: str) -> str:
    return MODIFIERS[no][2]


def modifier_cases() -> list[Case]:
    """At least 100 diagnoses, one patient folder each (a quarantine never hides another case), each read without
    and with the synthetic licensed master."""
    specs: list[tuple[str, str, str, list[str], str, str, str]] = []
    # (what, PRB-3 code, PRB-3 display text, ZPR segments, label without master, label with master, PRB-17)
    pneu, gas = "99990001", "99990002"

    # 1. controls: a coded name exactly as the master writes it, no qualifier
    for no, (name, ex, _icd) in DISEASES.items():
        # a disease row that is not current in the master (変更区分 1, or a value M does not define) is not recognised
        current = "CA" if DISEASE_CHANGE.get(no, "0") in ("0", "3", "5") else "NC"
        specs.append((f"control {name}", no, name, [], "CA", current, ""))
        specs.append((f"control {name}, ZPR names the same disease", no, name, [zpr(dis=no, dis_ex=ex)], "CA", current,
                      ""))  # fmt: skip
    # S's own example shape: ZPR-2 and ZPR-5 the same disease, nothing else
    specs.append(("S example ZPR (ZPR-2, ZPR-5 only)", gas, "胃炎", [zpr(dis=gas, dis_ex="ZA02")], "CA", "CA", ""))

    # 2. qualifiers written only in the display text (the #1095 limit): unknown with the master, the limit without
    for q in ("（未確定）", "の可能性あり", " provisional", "既往", "家族歴", "の既往", "疑い", "?", "の疑い", "（疑）",
              "様", "後遺症", "術後", "再発", "の除外", " r/o", "(probable)", "なし", "（済）", "母体"):  # fmt: skip
        for no in (pneu, gas):
            base = DISEASES[no][0]
            text = base + q
            # a 疑 or a question mark is read as suspected without a master already (#1095): never confirmed
            known = any(c in q for c in ("疑", "?")) or "r/o" in q
            specs.append((f"display only: {text}", no, text, [], "NC" if known else "NC*", "NC", ""))
        # the qualifier in front
    for q in ("疑い", "陳旧性", "既往の", "家族の", "推定"):
        text = q + DISEASES[pneu][0]
        known = "疑" in q
        specs.append((f"display only, in front: {text}", pneu, text, [], "NC" if known else "NC*", "NC", ""))

    # 3. coded modifiers by class (M (2)⑦): 1, 2, 3, 4, 5, 9 recognised; 6, 7, 8 unknown
    for mno, (_chg, word, ex, pos, cls) in MODIFIERS.items():
        prefix = int(pos) >= 10
        for no in (pneu, gas):
            base = DISEASES[no][0]
            text = word + base if prefix else base + word
            z = zpr(pre=[mno], dis=no, pre_ex=[ex]) if prefix else zpr(dis=no, suf=[mno], suf_ex=[ex])
            # D-1252 (lane J's ruling): 1 部位, 2 位置, 9 歯科 recognised; 3 病因 recognised unless the master gives
            # the modified name a code of its own (then the coded concept would silently be the unmodified one);
            # 4 経過表現 and 5 状態表現 can say "old", "after", "in remission": unknown, as 6, 7 and 8 are
            own_code = any(name == text for name, _e, _i in DISEASES.values())
            eight = len(cls) == 8 and cls.isdigit()  # M (2)⑦: 修飾語区分 is 8 characters
            ok = eight and (cls[1] in "129" or (cls[1] == "3" and not own_code)) and _chg in ("0", "3", "5")
            specs.append((f"modifier class {cls[1]} {word} on {base}", no, text, [z], "NC", "CA" if ok else "NC", ""))

    # 4. two modifiers, display text in the master's order
    specs.append(
        (
            "two prefixes 左 + 下葉",
            pneu,
            "左下葉肺炎",
            [zpr(pre=["99980002", "99980001"], dis=pneu, pre_ex=["ZM02", "ZM01"])],
            "NC",
            "CA",
            "",
        )
    )
    specs.append(("prefix 急性 + suffix の疑い", pneu, "急性肺炎の疑い",
                  [zpr(pre=["99980005"], dis=pneu, suf=["99980010"], pre_ex=["ZM05"], suf_ex=["ZM10"])], "NC", "NC",
                  ""))  # fmt: skip
    specs.append(
        (
            "prefix 慢性 + 細菌性",
            gas,
            "慢性細菌性胃炎",
            [zpr(pre=["99980006", "99980004"], dis=gas, pre_ex=["ZM06", "ZM04"])],
            "NC",
            "NC",
            "",
        )
    )

    # 5. the codes and the text disagree
    bad = [
        ("modifier not in the master", pneu, "左肺炎", [zpr(pre=["99989999"], dis=pneu)]),
        (
            "display text adds to the coded name",
            pneu,
            "左肺炎（未確定）",
            [zpr(pre=["99980002"], dis=pneu, pre_ex=["ZM02"])],
        ),
        ("display text leaves the modifier out", pneu, "肺炎", [zpr(pre=["99980002"], dis=pneu, pre_ex=["ZM02"])]),
        (
            "modifiers in another order than the text",
            pneu,
            "下葉左肺炎",
            [zpr(pre=["99980002", "99980001"], dis=pneu, pre_ex=["ZM02", "ZM01"])],
        ),
        ("a prefix code in the suffix field", pneu, "肺炎左", [zpr(dis=pneu, suf=["99980002"], suf_ex=["ZM02"])]),
        ("a suffix code in the prefix field", pneu, "の疑い肺炎", [zpr(pre=["99980010"], dis=pneu, pre_ex=["ZM10"])]),
        ("exchange code of another modifier", pneu, "左肺炎", [zpr(pre=["99980002"], dis=pneu, pre_ex=["ZM03"])]),
        ("ZPR-2 names another disease", pneu, "肺炎", [zpr(dis=gas)]),
        ("ZPR-5 names another disease", pneu, "肺炎", [zpr(dis=pneu, dis_ex="ZA02")]),
        ("a comment in ZPR-7", pneu, "肺炎", [zpr(dis=pneu, comment="経過観察")]),
        ("two ZPR segments", pneu, "肺炎", [zpr(dis=pneu), zpr(dis=pneu)]),
        ("a retired modifier", pneu, "旧左肺炎", [zpr(pre=["99980013"], dis=pneu, pre_ex=["ZM13"])]),
        ("the old loose ZPR of #1095's kit", pneu, "肺炎", ["ZPR|1|9999^の疑い^99XYZ"]),
        ("a modifier with only an exchange code, in the master", pneu, "左肺炎", [zpr(dis=pneu, pre_ex=["ZM02"])]),
    ]
    for what, no, text, zs in bad:
        specs.append((what, no, text, zs, "NC", "NC", ""))
    # a modifier code with no text: the master gives its word (左, class 2, before the name), and the display is
    # exactly that word and the coded name; without the master nothing reads it
    specs.append(
        ("a modifier code with no text", pneu, "左肺炎", ["ZPR|99980002|99990001^肺炎^MDCDX2"], "NC", "CA", "")
    )
    # without the master a code it does not hold, or a local code, cannot be told from a known one (as #1095 reads
    # them); with it, a name the reader cannot find in the master is not positively recognised
    specs.append(("PRB-3 code not in the master", "99991234", "肺炎", [], "CA", "NC", ""))
    # a diagnosis coded only locally keeps the reading without the master even when it is loaded (lane J's ruling:
    # the master rule is chosen per diagnosis, never per site)
    specs.append(("PRB-3 a local code", "L123", "肺炎", [], "CA", "CA", ""))
    # the mixed site (both tables loaded): local only, MDCDX2 only, both, and a local PRB-3 whose ZPR names MDCDX2
    for q in ("", "（未確定）", "家族歴"):
        doubt = "NC*" if q else "CA"
        # coded only locally: the reading without the master, so doubt only in the text is the stated limit here too
        specs.append((f"mixed site: local code only, {('肺炎' + q)}", "L123", "肺炎" + q, [], doubt, doubt, ""))
        specs.append((f"mixed site: MDCDX2 only, {('肺炎' + q)}", pneu, "肺炎" + q, [], doubt, "NC" if q else "CA", ""))
        specs.append((f"mixed site: local and MDCDX2, {('肺炎' + q)}", f"L123+{pneu}", "肺炎" + q, [], doubt,
                      "NC" if q else "CA", ""))  # fmt: skip
    specs.append(("mixed site: local PRB-3, ZPR names the same MDCDX2 disease", "L123", "左肺炎",
                  [zpr(pre=["99980002"], dis=pneu)], "NC", "CA", ""))  # fmt: skip
    specs.append(("mixed site: local PRB-3, ZPR names another MDCDX2 disease", "L123", "肺炎", [zpr(dis=gas)], "NC",
                  "NC", ""))  # fmt: skip
    # the code says one disease, the text another: only the master can tell (the stated limit without it)
    specs.append(("display text of another disease", pneu, "胃炎", [], "NC*", "NC", ""))
    # a modifier with only an exchange code and its 管理番号 is fine (both given, consistent)
    specs.append(
        (
            "management number and exchange code agree",
            pneu,
            "右肺炎",
            [zpr(pre=["99980003"], dis=pneu, pre_ex=["ZM03"])],
            "NC",
            "CA",
            "",
        )
    )
    # 6. PRB-17 written name
    specs.append(("PRB-17 the same name", pneu, "肺炎", [], "CA", "CA", "肺炎"))
    specs.append(("PRB-17 with a qualifier", pneu, "肺炎", [], "NC", "NC", "肺炎（未確定）"))
    specs.append(("PRB-17 with a modifier the codes give", pneu, "左肺炎", [zpr(pre=["99980002"], dis=pneu, pre_ex=["ZM02"])],
                  "NC", "NC", "左肺炎（両側）"))  # fmt: skip

    cases: list[Case] = []
    for i, (what, no, text, zs, plain, with_master, written) in enumerate(specs):
        pt = f"2{i:07d}"
        if "+" in no:  # a local code and an MDCDX2 one: two triples of PRB-3
            local, number = no.split("+")
            first = prb(local, text, "DX001", system=f"99XYZ^{number}^{text}^MDCDX2", written=written)
        else:
            first = prb(no, text, "DX001", system="MDCDX2" if no.isdigit() else "99XYZ", written=written)
        body = [first, *zs]
        f = F(pt, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(pt, body))
        limit = plain == "NC*"
        cases.append(Case(f"{what} (no master)", "M modifiers", "diagnosis", [f], {f"{pt}/DX001": "NC" if limit else plain},
                          limit=limit))  # fmt: skip
        f2 = F(pt, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(pt, body))
        limit2 = with_master == "NC*"
        cases.append(Case(f"{what} (licensed master)", "M modifiers", "diagnosis", [f2],
                          {f"{pt}/DX001": "NC" if limit2 else with_master}, licensed="master", limit=limit2))  # fmt: skip
    # PRB-13: the code table (C 表95) lists only "1 疑いあり"; a "0" is not a value of it (D-1252, lane J's ruling)
    flags = ["0^^JHSD0005", "0^疑いなし^JHSD0005", "0^なし^JHSD0005", "0^^99JHSD0005", "0", "1^疑いあり^JHSD0005"]
    for j, flag in enumerate(flags):
        for kind in ("", "master"):
            pt = f"3{j:03d}{1 if kind else 0}000"
            f = F(pt, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(pt, [prb(pneu, "肺炎", "DX001", flag13=flag)]))
            cases.append(Case(f"PRB-13 {flag} ({'licensed master' if kind else 'no master'})", "M flag", "diagnosis",
                              [f], {f"{pt}/DX001": "NC"}, licensed=kind))  # fmt: skip
    return cases


# ------------------------------------------------------------------------------------------------ running
def _ca(table: str, row: dict[str, Any]) -> bool:
    if table == "diagnosis":
        return str(row.get("status") or "") == "A" and not str(row.get("suspected") or "")
    return str(row.get("status") or "") == "active"


def _key(table: str) -> str:
    return {"diagnosis": "diag_no", "medication": "rx_no"}[table]


def run_case(case: Case, base: Path) -> dict[str, str]:
    """The lake's reading of every id after the case's nights: CA, NC or GONE; ids the case does not name are added
    as ``+<id>`` when the lake holds them."""
    from adapter.sources.ssmix2.source import Ssmix2Source

    root = base / "ss"
    root.mkdir(parents=True, exist_ok=True)
    lake: dict[str, dict[str, Any]] = {}
    nights = max(f.night for f in case.files) + 1
    for night in range(nights):
        for f in case.files:
            if f.night == night:
                f.write(root)
        src = Ssmix2Source(root, licensed=licensed_tables(case.licensed), order_key=case.order_key)
        live = list(src.rows(case.table, case.table, None, None))
        dead = list(src.deleted_rows(case.table, case.table, None, None))
        sent = set()
        for row in live:
            rid = f"{row['mrn']}/{row[_key(case.table)]}"
            lake[rid] = row  # the last row of a key decides (DATA-017)
            sent.add(rid)
        for row in dead:
            rid = f"{row['mrn']}/{row[_key(case.table)]}"
            if rid not in sent:  # a record sent again in the same run wins over its tombstone
                lake.pop(rid, None)
    out = {}
    for rid in case.expect:
        got = lake.get(rid)
        out[rid] = "GONE" if got is None else ("CA" if _ca(case.table, got) else "NC")
    for rid, row in lake.items():
        if rid not in case.expect:
            out[f"+{rid}"] = "CA" if _ca(case.table, row) else "NC"
    return out


def judge(case: Case, got: dict[str, str]) -> tuple[bool, bool]:
    """(wrong, dangerous)."""
    wrong = any(got.get(rid) != want for rid, want in case.expect.items()) or any(k.startswith("+") for k in got)
    dangerous = any(got.get(rid) == "CA" and want != "CA" for rid, want in case.expect.items()) or any(
        k.startswith("+") and v == "CA" for k, v in got.items()
    )
    return wrong, dangerous


# ------------------------------------------------------------------------------------------------ independent set 1
def independent_cases() -> list[Case]:
    """Independent set 1: the classes an independent tester found dangerous on this card's head 2bc79278 (lane J,
    2026-11-19), written here from lane J's description of them; the tester's own inputs were not seen. Each case is
    labelled by D-1252's rules as amended for them."""
    cases: list[Case] = []
    pneu, gas = "99990001", "99990002"
    serial = iter(range(10_000))

    def one(what: str, cls: int, body: list[str], want: str, master: str = "both") -> None:
        for kind in ("", "master") if master == "both" else (master,):
            pt = f"4{next(serial):07d}"
            text = "\r".join(ppr(pt, body))
            f = F(pt, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", text.split("\r"))
            cases.append(Case(f"class {cls}: {what} ({'licensed master' if kind else 'no master'})",
                              f"I independent class {cls}", "diagnosis", [f], {f"{pt}/DX05": want},
                              licensed=kind))  # fmt: skip

    def dx(name: str = "肺炎", code: str = pneu, system: str = "MDCDX2", written: str = "") -> str:
        return prb(code, name, "DX05", system=system, written=written)

    # 1. a modifier given as text with no code
    one("ZPR-1 text with no code", 1, [dx(), "ZPR|^慢性^MDCDX2|99990001|||ZA01"], "NC")
    one("ZPR-3 text with no code", 1, [dx(), "ZPR|||^の再燃^MDCDX2"], "NC")
    one("ZPR-4 text with no code", 1, [dx(), "ZPR||99990001||^慢性^MDCDX2"], "NC")
    one("ZPR-6 text with no code", 1, [dx(), "ZPR||99990001|||||^再燃^MDCDX2"], "NC")
    # 2. code and text disagree inside a component
    one("ZPR-1 左's code, 慢性's text", 2, [dx("左肺炎"), "ZPR|99980002^慢性^MDCDX2|99990001"], "NC")
    one(
        "ZPR-4 慢性's text under 左's exchange code", 2, [dx("左肺炎"), "ZPR|99980002|99990001||ZM02^慢性^MDCDX2"], "NC"
    )
    one("ZPR-2 the disease code with another name", 2, [dx(), "ZPR||99990001^慢性肺炎^MDCDX2"], "NC")
    one("ZPR-5 the exchange code with another name", 2, [dx(), "ZPR||99990001|||ZA01^慢性肺炎^MDCDX2"], "NC")
    # 3. PRB-3's alternate triple disagrees with the first
    one("PRB-3 alternate name disagrees", 3, [dx(system="MDCDX2^L9^慢性肺炎^99XYZ")], "NC")
    one("PRB-3 alternate local name agrees", 3, [dx(system="MDCDX2^L9^肺炎^99XYZ")], "CA")
    # 4. 変更区分
    for no, word, want in (("99980016", "上", "CA"), ("99980017", "下", "CA"), ("99980018", "前", "NC"),
                           ("99980019", "後", "NC"), ("99980020", "外", "NC"), ("99980013", "旧左", "NC")):  # fmt: skip
        one(f"modifier 変更区分 of {word}", 4, [dx(word + "肺炎"), zpr(pre=[no], dis=pneu)], want, master="master")
    one("disease 変更区分 1", 4, [dx("咽頭炎", "99990008")], "NC", master="master")
    one("disease 変更区分 X", 4, [dx("喉頭炎", "99990009")], "NC", master="master")
    # 7. segments the reader does not read
    for what, segs, where in (("NTE saying 疑い after the PRB", ["NTE|1||疑い"], "after"),
                              ("NTE with a plain remark", ["NTE|1||経過観察"], "after"),
                              ("an unknown Z segment", ["ZXY|1|x"], "after"),
                              ("an OBX after the PRB", ["OBX|1|ST|x||y"], "after"),
                              ("a ZPR before the first PRB", ["ZPR||99990001"], "before"),
                              ("an NTE before the first PRB", ["NTE|1||x"], "before")):  # fmt: skip
        body = [*segs, dx()] if where == "before" else [dx(), *segs]
        one(what, 7, body, "NC")
    one("guard: ZI1 and ZPD after the PRB are read as before", 7, [dx(), "ZPD|1|101801^x^JHSD0010", "ZI1|1"], "CA")
    # 10. where the full name is written (表3-47): PRB-3 the full name, or PRB-3 the 病名表記 and PRB-17 the full name
    one("PRB-3 the full name", 10, [dx("左肺炎"), zpr(pre=["99980002"], dis=pneu)], "CA", master="master")
    one("PRB-3 the base name, PRB-17 the full name", 10, [dx("肺炎", written="左肺炎"),
                                                          zpr(pre=["99980002"], dis=pneu)], "CA", master="master")  # fmt: skip
    one("PRB-3 the base name, PRB-17 another full name", 10, [dx("肺炎", written="右肺炎"),
                                                              zpr(pre=["99980002"], dis=pneu)], "NC")  # fmt: skip
    one("PRB-3 the base name, no PRB-17", 10, [dx("肺炎"), zpr(pre=["99980002"], dis=pneu)], "NC")
    one("PRB-3 the base name, PRB-17 the full name, no master", 10, [dx("肺炎", written="左肺炎"),
                                                                     zpr(pre=["99980002"], dis=pneu)], "NC", master="")  # fmt: skip
    one("no modifier, PRB-17 the same name", 10, [dx("胃炎", gas, written="胃炎")], "CA")

    # 5. the snapshot's order number written in another form (G 図3.1-1: a run of nines; 表3.1-3: "ALL9")
    a, b = prb(pneu, "肺炎", "DX001"), prb(gas, "胃炎", "DX002", icd10="K297")
    for form in ("ＡＬＬ９", "all9", "ALL9 ", "9999999999999999", "99999999", "-"):
        for night in (0, 1):
            pt = f"5{next(serial):07d}"
            files = [F(pt, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(pt, [a, b])),
                     F(pt, "-", "PPR-01", form, stamp(DAY_A, 1), "1", ppr(pt, [a]), night=night)]  # fmt: skip
            cases.append(Case(f"class 5: a newer snapshot under {form!r} (night {night})", "I independent class 5",
                              "diagnosis", files, {f"{pt}/DX001": "CA", f"{pt}/DX002": "GONE"}))  # fmt: skip

    # 6. a newer or delete file whose name is not in the guideline's form; the older version left at flag 1
    for kind in ("PPR-01", "OMP-01"):
        # {p} patient, {k} type, {n} order number, {s} 発生日時, {f} flag
        templates = (
            ("type part in lower case", "{p}_{d}_" + kind.lower() + "_{n}_{s}_01_{f}"),
            ("type part in full width", "{p}_{d}_" + kind.translate(_WIDE) + "_{n}_{s}_01_{f}"),
            ("patient id in full width", "{wp}_{d}_{k}_{n}_{s}_01_{f}"),
            ("patient id with a blank", "{p} _{d}_{k}_{n}_{s}_01_{f}"),
            ("flag in full width", "{p}_{d}_{k}_{n}_{s}_01_{wf}"),
            ("flag with a blank", "{p}_{d}_{k}_{n}_{s}_01_{f} "),
            ("an extension", "{p}_{d}_{k}_{n}_{s}_01_{f}.hl7"),
            ("eight parts", "{p}_{d}_{k}_{n}_{s}_01_x_{f}"),
        )
        for what, template in templates:
            for flag in ("0", "1"):
                pt = f"6{next(serial):07d}"
                no = "RX0001" if kind == "OMP-01" else "DX001"
                if kind == "OMP-01":
                    older = F(pt, DAY_A, kind, no, stamp(DAY_A, 0), "1", omp(pt, no, DAY_A, [("NW", "1", "999000001")]))
                    newer_segs = omp(pt, no, DAY_A, [("CA" if flag == "0" else "NW", "1", "999000001")])
                    day = DAY_A
                else:
                    older = F(pt, "-", kind, "ALL9", stamp(DAY_A, 0), "1", ppr(pt, [a]))
                    newer_segs = ppr(pt, [a])
                    day = "-"
                order = no if kind == "OMP-01" else "ALL9"
                name = template.format(p=pt, wp=pt.translate(_WIDE), d=day, k=kind, n=order, s=stamp(DAY_A, 1), f=flag,
                                       wf=flag.translate(_WIDE))  # fmt: skip
                newer = F(pt, day, kind, order, stamp(DAY_A, 1), flag, newer_segs, night=1, name=name)
                cases.append(Case(f"class 6: {kind} newer {'delete' if flag == '0' else 'version'}: {what}",
                                  "I independent class 6", "diagnosis" if kind == "PPR-01" else "medication",
                                  [older, newer], {f"{pt}/{no}": "NC"}))  # fmt: skip

    # 8. a name and ORC-2 that disagree; a future 発生日時; the same Rp and drug twice, one cancelled
    for named in ("rx01", "RX001"):
        for flag in ("0", "1"):
            pt = f"7{next(serial):07d}"
            older = F(
                pt, DAY_A, "OMP-01", "RX01", stamp(DAY_A, 0), "1", omp(pt, "RX01", DAY_A, [("NW", "1", "999000001")])
            )
            newer = F(pt, DAY_A, "OMP-01", named, stamp(DAY_A, 1), flag,
                      omp(pt, "RX01", DAY_A, [("CA" if flag == "0" else "NW", "1", "999000001")]), night=1)  # fmt: skip
            exp = {f"{pt}/RX01": "NC"}
            if flag == "1":
                exp[f"{pt}/{key_part_like(named)}:RX01"] = "NC"
            cases.append(Case(f"class 8: file named {named} with ORC-2 RX01, flag {flag}", "I independent class 8",
                              "medication", [older, newer], exp))  # fmt: skip
    for kind in ("OMP-01", "PPR-01"):
        pt = f"7{next(serial):07d}"
        if kind == "OMP-01":
            files = [F(pt, DAY_A, kind, "RX01", stamp(DAY_A, 0), "1", omp(pt, "RX01", DAY_A, [("NW", "1", "999000001")])),
                     F(pt, DAY_A, kind, "RX01", "20990101090000000", "0",
                       omp(pt, "RX01", DAY_A, [("CA", "1", "999000001")]), night=1)]  # fmt: skip
            exp = {f"{pt}/RX01": "NC"}
        else:
            files = [F(pt, "-", kind, "ALL9", stamp(DAY_A, 0), "1", ppr(pt, [a, b])),
                     F(pt, "-", kind, "ALL9", "20990101090000000", "1", ppr(pt, [a]), night=1)]  # fmt: skip
            exp = {f"{pt}/DX001": "NC", f"{pt}/DX002": "NC"}
        cases.append(Case(f"class 8: a {kind} file stamped 2099", "I independent class 8",
                          "medication" if kind == "OMP-01" else "diagnosis", files, exp))  # fmt: skip
    pt = f"7{next(serial):07d}"
    twice = [("NW", "1", "999000001"), ("CA", "1", "999000001")]
    files = [F(pt, DAY_A, "OMP-01", "RX01", stamp(DAY_A, 0), "1", omp(pt, "RX01", DAY_A, twice))]
    cases.append(Case("class 8: the same Rp and drug twice, one cancelled", "I independent class 8", "medication",
                      files, {f"{pt}/RX01#1:999000001": "NC", f"{pt}/RX01#1:999000001~2": "NC"}))  # fmt: skip
    return cases


_WIDE = str.maketrans("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-",
                      "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ－")  # fmt: skip


def key_part_like(value: str) -> str:
    """The reader's one normalisation, for writing an expected key (NFKC, blanks removed; case kept)."""
    import unicodedata

    return "".join(unicodedata.normalize("NFKC", value).split())


# ------------------------------------------------------------------------------------------------ independent set 2
def _set_field(segment: str, n: int, value: str) -> str:
    """``segment`` with field ``n`` set to ``value`` (the segment's fields extended as needed)."""
    parts = segment.split("|")
    parts += [""] * (n + 1 - len(parts))
    parts[n] = value
    return "|".join(parts)


def independent_cases_2() -> list[Case]:
    """Independent set 2: the classes a second tester found at 5ae5593f (lane J, 2026-11-19), written here from lane
    J's description (B to F; the delta nights, class A, are ``tests/unit/test_ssmix2_10b2b_delta.py``), and the
    correct-site shapes that must stay confirmed with the master."""
    cases: list[Case] = []
    pneu, gas = "99990001", "99990002"
    serial = iter(range(10_000))

    def one(
        what: str, cls: str, body: list[str], want: str, master: str = "both", head: list[str] | None = None
    ) -> None:
        for kind in ("", "master") if master == "both" else (master,):
            pt = f"8{next(serial):07d}"
            segs = (head or [msh("PPR^ZD1^PPR_ZD1", "P", "20261001090000"), pid(pt)]) + body
            segs = [s.replace("{pt}", pt) for s in segs]
            f = F(pt, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", segs)
            cases.append(Case(f"class {cls}: {what} ({'licensed master' if kind else 'no master'})",
                              f"J independent class {cls}", "diagnosis", [f], {f"{pt}/DX05": want},
                              licensed=kind))  # fmt: skip

    base = prb(pneu, "肺炎", "DX05")
    # B. fields and components the reader does not read
    for what, seg in (("PRB-19 certainty L^低い", _set_field(base, 19, "L^低い^99XYZ")),
                      ("PRB-20 probability 0.2", _set_field(base, 20, "0.2")),
                      ("PRB-11 management discipline", _set_field(base, 11, "01^内科^99XYZ")),
                      ("PRB-12 persistence", _set_field(base, 12, "C^慢性^99XYZ")),
                      ("PRB-3 original text (component 9)", _set_field(base, 3, f"{pneu}^肺炎^MDCDX2^^^^^^肺炎の疑い")),
                      ("PRB-17 with a second component", _set_field(base, 17, "肺炎^疑い")),
                      ("PRB-14 with an alternate triple", _set_field(base, 14, "A^^^C^継続^JHSD0006"))):  # fmt: skip
        one(what, "B", [seg], "NC")
    one("ZPR-8 holding の疑い", "B", [base, f"ZPR||{pneu}^肺炎^MDCDX2||||||の疑い"], "NC")
    one("an ORC with ORC-1 DC after the PRB", "B", [base, "ORC|DC|X1"], "NC")
    one("guard: an ORC NW as in the specification's example", "B", [base, "ORC|NW|X1||||||||||110^医師|||||01^内科"],
        "CA")  # fmt: skip
    one("a second MSH before the first PRB", "B", [base],
        "NC", head=[msh("PPR^ZD1^PPR_ZD1", "P", "20261001090000"), msh("PPR^ZD1^PPR_ZD1", "Q", "20261001090000"),
                    pid("{pt}")])  # fmt: skip
    one("MSH-9 ADT^A08 in a PPR-01 folder", "B", [base], "GONE",
        head=[msh("ADT^A08^ADT_A01", "P", "20261001090000"), pid("{pt}")])  # fmt: skip
    one("guard: PRB-25 confidentiality, as in the specification's example", "B", [_set_field(base, 25, "V^非常に限定^HL70177")],
        "CA")  # fmt: skip
    # C. a ZPR under the wrong PRB
    for kind in ("", "master"):
        pt = f"8{next(serial):07d}"
        body = [prb(pneu, "肺炎", "DX05"), zpr(dis=gas, suf=["99980010"]), prb(gas, "胃炎", "DX06")]
        f = F(pt, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", [msh("PPR^ZD1^PPR_ZD1", "P"), pid(pt), *body])
        cases.append(Case(f"class C: a ZPR naming 胃炎 after 肺炎's PRB ({'licensed master' if kind else 'no master'})",
                          "J independent class C", "diagnosis", [f], {f"{pt}/DX05": "NC", f"{pt}/DX06": "NC"},
                          licensed=kind))  # fmt: skip
    # D. master edges (reader side; the loader's duplicates: tests/unit/test_ssmix2_10b2b_modifiers.py)
    one(
        "a 9-character 修飾語区分",
        "D",
        [prb(pneu, "左肺炎", "DX05"), zpr(pre=["99980021"], dis=pneu)],
        "NC",
        master="master",
    )
    one(
        "a 7-character 修飾語区分",
        "D",
        [prb(pneu, "右肺炎", "DX05"), zpr(pre=["99980022"], dis=pneu)],
        "NC",
        master="master",
    )
    one("PRB-10's ICD-10 not the master's", "D", [prb(pneu, "肺炎", "DX05", icd10="C349")], "NC", master="master")
    one("guard: PRB-10's ICD-10 the master's", "D", [prb(pneu, "肺炎", "DX05", icd10="J189")], "CA", master="master")
    # F. no master: PRB-3 the 病名交換用コード, ZPR-2 the 病名管理番号
    one("PRB-3 exchange code, ZPR-2 管理番号, ZPR-5 the same exchange code", "F",
        [prb("ZA01", "肺炎", "DX05"), "ZPR||99990001^肺炎^MDCDX2|||ZA01^肺炎^MDCDX2"], "CA")  # fmt: skip
    one("PRB-3 exchange code, ZPR-2 管理番号, no ZPR-5", "F", [prb("ZA01", "肺炎", "DX05"), "ZPR||99990001^肺炎^MDCDX2"],
        "NC", master="")  # fmt: skip
    # correct-site shapes that must stay confirmed with the master (lane J: 100 %)
    one("correct site: the specification's example shape", "OK",
        [_set_field(prb(gas, "胃炎", "DX05"), 25, "V^非常に限定^HL70177"), f"ZPR||{gas}^胃炎^MDCDX2|||ZA02^胃炎^MDCDX2"], "CA")  # fmt: skip
    one("correct site: a class 2 prefix", "OK", [prb(pneu, "左肺炎", "DX05"), zpr(pre=["99980002"], dis=pneu, pre_ex=["ZM02"])],
        "CA", master="master")  # fmt: skip
    one("correct site: base name in PRB-3, full in PRB-17", "OK",
        [prb(pneu, "肺炎", "DX05", written="左下葉肺炎"), zpr(pre=["99980002", "99980001"], dis=pneu)], "CA", master="master")  # fmt: skip
    one("correct site: no ZPR, display the master's name", "OK", [prb(gas, "胃炎", "DX05")], "CA")
    one("correct site: PRB-3 by exchange code", "OK", [prb("ZA02", "胃炎", "DX05", icd10="K297")], "CA")

    # E. one patient's DE never stands for another patient's dropped diagnosis
    for night in (0, 1):
        p1, p2 = f"8{next(serial):07d}", f"8{next(serial):07d}"
        a = prb(pneu, "肺炎", "DX01")
        files = [
            F(p1, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(p1, [prb(pneu, "肺炎", "DX01", action="DE")])),
            F(p2, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(p2, [a, prb(gas, "胃炎", "DX02")])),
            F(p2, "-", "PPR-01", "ALL9", stamp(DAY_A, 1), "1", ppr(p2, [prb(gas, "胃炎", "DX02")]), night=night),
        ]
        cases.append(Case(f"class E: one patient's DE and another's dropped DX01 (night {night})",
                          "J independent class E", "diagnosis", files,
                          {f"{p1}/DX01": "GONE", f"{p2}/DX01": "GONE", f"{p2}/DX02": "CA"}))  # fmt: skip
    return cases


def all_cases() -> dict[str, list[Case]]:
    return {
        "supersession": supersession_cases(),
        "modifiers": modifier_cases(),
        "independent set 1": independent_cases(),
        "independent set 2": independent_cases_2(),
    }


def measure(sets: dict[str, list[Case]] | None = None) -> dict[str, Any]:
    sets = sets or all_cases()
    report: dict[str, Any] = {}
    os.environ.pop("TB_SSMIX2_ORDER_NUMBERS", None)
    for name, cases in sets.items():
        rows = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, case in enumerate(cases):
                got = run_case(case, Path(tmp) / str(i))
                wrong, dangerous = judge(case, got)
                rows.append({"name": case.name, "family": case.family, "limit": case.limit, "expect": case.expect,
                             "got": got, "wrong": wrong, "dangerous": dangerous})  # fmt: skip
        report[name] = rows
    return report


def summary(report: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, rows in report.items():
        ids = sum(len(r["expect"]) for r in rows)
        out[name] = {
            "cases": len(rows),
            "ids": ids,
            "wrong cases": sum(r["wrong"] for r in rows),
            "dangerous cases": sum(r["dangerous"] for r in rows),
            "dangerous cases outside the stated limit": sum(r["dangerous"] and not r["limit"] for r in rows),
            "limit cases": sum(r["limit"] for r in rows),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", type=Path, help="write every case's reading here")
    a = ap.parse_args(argv)
    report = measure()
    if a.json:
        a.json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary(report), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services"))
    raise SystemExit(main())
