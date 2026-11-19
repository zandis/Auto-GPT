"""Card 10B-2b (D-1252) part B: the disease-name modifier codes (修飾語コード).

ZPR is read by its fields (SS-MIX2 標準化ストレージ仕様書 Ver.1.2j 3.7.4, 表3-48, JAMI 2026-08-14), and a modifier by
its class in the site's licensed MEDIS master (ICD10対応標準病名マスター Ver.5.18 仕様書 (2) 修飾語テーブル, MEDIS-DC
2026-06), loaded through ``adapter.licensed``. Nothing of the master is in the repository: the tables below are
synthetic, with the master's column names and made-up codes (``9999xxxx`` 病名管理番号, ``9998xxxx`` 修飾語管理番号).
Each test fails on #1095's head unless it says it is a guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter import licensed as lic
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_probes as pb
from tests.ssmix2_probes import DAY_A, P1, F, ppr, prb, stamp, zpr

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
#: M (1) 病名基本テーブル, in file order (no header row in the release)
DISEASE_COLUMNS = "変更区分,病名管理番号,病名表記,病名表記カナ,採択区分,病名交換用コード,ICD10-2013"
#: M (2) 修飾語テーブル, in file order
MODIFIER_COLUMNS = (
    "変更区分,修飾語管理番号,修飾語表記,修飾語表記カナ,修飾語交換用コード,接続位置区分,修飾語区分,排他グループコード,"
    "レセ電算修飾語コード,修飾語説明用ラベル"
)


def _synthetic_release() -> dict[str, dict[str, dict[str, str]]]:
    """The synthetic master written as the vendor files are (CSV, quoted, Shift_JIS, no header) and read by the
    loader's own parser, so the reader sees exactly what ``adapter.licensed.tables()`` gives a site."""
    diseases = "\r\n".join(
        f'"0","{no}","{name}","ｶﾅ","1","{ex}","{icd}"' for no, (name, ex, icd) in pb.DISEASES.items()
    ).encode("cp932")
    mods = "\r\n".join(
        f'"{chg}","{no}","{word}","ｶﾅ","{ex}","{pos}","{cls}","","",""'
        for no, (chg, word, ex, pos, cls) in pb.MODIFIERS.items()
    ).encode("cp932")
    out: dict[str, dict[str, dict[str, str]]] = {"jlac10": {}, "yj": {}}
    for kind, data, cols in (("medis", diseases, DISEASE_COLUMNS), ("medis_modifier", mods, MODIFIER_COLUMNS)):
        parsed = lic.parse(kind, data, cols.split(","))
        out[kind] = {c["code"]: {k: c[k] for k in ("display", "target_system", "target_code", "extra")}
                     for c in parsed.concepts}  # fmt: skip
    return out


def _row(tmp_path: Path, name: str, zprs: list[str], *, master: bool, code: str = "99990001", written: str = "") -> Any:
    system = "MDCDX2" if code.isdigit() or code.startswith("ZA") else "99XYZ"
    body = [prb(code, name, "DX001", system=system, written=written), *zprs]
    F(P1, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(P1, body)).write(tmp_path)
    src = Ssmix2Source(tmp_path, licensed=_synthetic_release() if master else EMPTY)
    (row,) = list(src.rows("diagnosis", "diagnosis", None, None))
    return row


# ------------------------------------------------------------------------------------------------ the licensed kind
def test_the_modifier_table_loads_through_the_licensed_path_with_its_class_and_position() -> None:
    rel = _synthetic_release()
    left = rel["medis_modifier"]["99980002"]
    assert left["display"] == "左"
    assert '"modifier_class": "22000000"' in left["extra"] and '"position": "60"' in left["extra"]
    assert '"exchange_code": "ZM02"' in left["extra"] and '"change": "0"' in left["extra"]
    assert "medis_modifier" in lic.KINDS


# ------------------------------------------------------------------------------------------------ with the master
@pytest.mark.parametrize(
    ("name", "zprs"),
    [
        ("左肺炎", [zpr(pre=["99980002"], dis="99990001", pre_ex=["ZM02"])]),  # class 2 位置
        ("下葉肺炎", [zpr(pre=["99980001"], dis="99990001")]),  # class 1 部位
        ("左下葉肺炎", [zpr(pre=["99980002", "99980001"], dis="99990001", pre_ex=["ZM02", "ZM01"])]),
        ("第１大臼歯肺炎", [zpr(pre=["99980012"], dis="99990001")]),  # class 9 歯科
        ("細菌性胃炎", [zpr(pre=["99980004"], dis="99990002")]),  # class 3, no code of its own for the name
    ],
)
def test_a_modifier_of_a_recognised_class_with_the_display_name_exact_stays_confirmed(
    tmp_path: Path, name: str, zprs: list[str]
) -> None:
    row = _row(tmp_path, name, zprs, master=True, code="99990002" if "胃炎" in name else "99990001")
    assert (row["status"], row["suspected"]) == ("A", "")


@pytest.mark.parametrize(
    ("what", "name", "zprs"),
    [
        ("class 4 経過表現", "急性肺炎", [zpr(pre=["99980005"], dis="99990001")]),
        ("class 5 状態表現", "重症肺炎", [zpr(pre=["99980007"], dis="99990001")]),
        ("class 6 患者帰属", "老人性肺炎", [zpr(pre=["99980008"], dis="99990001")]),
        ("class 7 その他", "高度肺炎", [zpr(pre=["99980009"], dis="99990001")]),
        ("class 8 接尾語", "肺炎術後", [zpr(dis="99990001", suf=["99980011"])]),
        ("a class outside 1 to 9", "不明区分肺炎", [zpr(pre=["99980014"], dis="99990001")]),
        ("retired (変更区分 1)", "旧左肺炎", [zpr(pre=["99980013"], dis="99990001")]),
        ("not in the master", "左肺炎", [zpr(pre=["99989999"], dis="99990001")]),
        ("a prefix in the suffix field", "肺炎左", [zpr(dis="99990001", suf=["99980002"])]),
        ("another modifier's exchange code", "左肺炎", [zpr(pre=["99980002"], dis="99990001", pre_ex=["ZM03"])]),
        ("ZPR-5 another disease", "肺炎", [zpr(dis="99990001", dis_ex="ZA02")]),
        ("the modified name has its own code", "細菌性肺炎", [zpr(pre=["99980004"], dis="99990001")]),
        ("text added to the coded name", "肺炎（未確定）", []),
        ("text added to the coded name and modifier", "左肺炎 provisional", [zpr(pre=["99980002"], dis="99990001")]),
        ("a family-history word", "肺炎家族歴", []),
        ("a ZPR comment", "肺炎", [zpr(dis="99990001", comment="経過観察")]),
    ],
)
def test_with_the_master_anything_not_positively_recognised_is_unknown(
    tmp_path: Path, what: str, name: str, zprs: list[str]
) -> None:
    row = _row(tmp_path, name, zprs, master=True)
    assert row["suspected"] in ("U", "Y"), what  # never confirmed
    assert row["suspected"] == "U" or "疑" in name


def test_with_the_master_a_local_code_is_not_recognised(tmp_path: Path) -> None:
    assert _row(tmp_path, "肺炎", [], master=True, code="L123")["suspected"] == "U"


# ------------------------------------------------------------------------------------------------ without it
def test_without_the_master_the_specifications_own_zpr_shape_is_confirmed(tmp_path: Path) -> None:
    """The one move toward confirmed (lane J's ruling): ZPR-2 and ZPR-5 naming PRB-3's own disease, nothing else
    (仕様書 Ver.1.2j appendix example). #1095 read every ZPR value as a modifier and gave U."""
    row = _row(tmp_path, "胃炎", [zpr(dis="99990002", dis_ex="ZA02")], master=False, code="99990002")
    assert (row["status"], row["suspected"], row["modifiers"]) == ("A", "", "")


@pytest.mark.parametrize(
    "zprs",
    [
        [zpr(pre=["99980002"], dis="99990001")],
        [zpr(dis="99990001", suf=["99980011"])],
        [zpr(dis="99990001", comment="経過観察")],
        [zpr(dis="99990002")],
        [zpr(dis="99990001"), zpr(dis="99990001")],
        ["ZPR|99980002|99990001^肺炎^MDCDX2"],
    ],
)
def test_without_the_master_any_modifier_or_comment_is_unknown(tmp_path: Path, zprs: list[str]) -> None:
    """Guards: #1095 already gave U (or Y) for these; the ZPR fields are now read by position."""
    assert _row(tmp_path, "肺炎", zprs, master=False)["suspected"] in ("U", "Y")


# ------------------------------------------------------------------------------------------------ the probe set
def test_the_modifier_probe_set_has_no_wrong_reading_outside_the_stated_limit() -> None:
    report = pb.measure({"modifiers": pb.modifier_cases()})
    bad = [(r["name"], r["expect"], r["got"]) for r in report["modifiers"] if r["wrong"] and not r["limit"]]
    assert bad == []


# ------------------------------------------------------------------------------------------------ which tables
def test_the_disease_table_alone_never_turns_a_locally_coded_diagnosis_unknown(tmp_path: Path) -> None:
    """Guard (passes on both heads): a site loads the disease table for the ICD-10 look-up (D-137); the display-name
    and modifier rules apply only once it has loaded the modifier table too (the e2e GOUT-COH funnel)."""
    rel = _synthetic_release()
    rel["medis_modifier"] = {}
    body = [prb("L123", "肺炎", "DX001", system="99XYZ")]
    F(P1, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(P1, body)).write(tmp_path)
    (row,) = list(Ssmix2Source(tmp_path, licensed=rel).rows("diagnosis", "diagnosis", None, None))
    assert (row["status"], row["suspected"]) == ("A", "")


def test_with_the_master_an_mdcdx2_exchange_code_in_prb3_is_recognised(tmp_path: Path) -> None:
    """S 3.7.4 names MDCDX2 for the 病名管理番号 and the 病名交換用コード alike."""
    assert _row(tmp_path, "肺炎", [], master=True, code="ZA01")["suspected"] == ""
