"""PHI recognisers for Taiwan and Japan (spec v4 §7.14, PRIV-29; S1-08)."""

from __future__ import annotations

import pytest
from guard.app import create_app
from guard.guard import Guard
from guard.recognisers import my_number_check_digit, my_number_valid, tw_id_check_digit, tw_id_valid
from starlette.testclient import TestClient

G = Guard("^\\d{8}$")


def _kinds(text: str) -> set[str]:
    return {f.kind for f in G.detect(text)}


@pytest.mark.req("PRIV-29")
def test_check_digits() -> None:
    assert tw_id_valid("A123456789")  # the widely published example number
    assert not tw_id_valid("A123456788")
    assert tw_id_valid("A1" + "2345678" + tw_id_check_digit("A12345678")[-1])
    new_arc = "F8" + "0000001"
    new_arc = new_arc + tw_id_check_digit(new_arc)
    old_arc = "AB" + "1234567"
    old_arc = old_arc + tw_id_check_digit(old_arc)
    assert tw_id_valid(new_arc) and tw_id_valid(old_arc)
    assert not tw_id_valid(old_arc[:-1] + str((int(old_arc[-1]) + 1) % 10))
    n = "12345678901"
    full = n + str(my_number_check_digit(n))
    assert my_number_valid(full) and my_number_valid(f"{full[:4]} {full[4:8]} {full[8:]}")
    assert not my_number_valid(n + str((my_number_check_digit(n) + 1) % 10))


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("身分證字號 A123456789 已核對", "TW_NATIONAL_ID"),
        ("居留證 FC12345678 號", "ID_NUMBER"),  # right shape, wrong check digit: still redacted
        ("護照號碼 312345678", "PASSPORT"),
        ("旅券番号 TK1234567", "PASSPORT"),
        ("passport no. 212345678", "PASSPORT"),
        ("手機 0912-345-678", "PHONE"),
        ("請撥 +886 2 2345 6789", "PHONE"),
        ("(02) 2345-6789 分機", "PHONE"),
        ("携帯 090-1234-5678 に連絡", "PHONE"),
        ("+81-3-1234-5678", "PHONE"),
        ("住址：台北市大安區復興南路二段100巷5號3樓", "ADDRESS"),
        ("東京都新宿区西新宿2丁目8番1号在住", "ADDRESS"),
        ("大阪府大阪市北区梅田1-2-3", "ADDRESS"),
        ("lives at 350 Oak Avenue, Apt 4, Riverside", "ADDRESS"),
        ("病歷號 20481234", "MRN"),
        ("chart no. A-7731", "MRN"),
        ("患者陳志明先生今日回診", "NAME"),
        ("氏名：鈴木 花子", "NAME"),
        ("山田健一さんは発熱", "NAME"),
        ("Patient: Mary Chen presented", "NAME"),
        ("生年月日 昭和31年3月14日", "DOB"),
        ("出生日期：民國45年3月14日", "DOB"),
        ("DOB: 03/14/1956", "DOB"),
        ("mail a.b@example.org", "EMAIL"),
    ],
)
def test_recognisers(text: str, kind: str) -> None:
    assert kind in _kinds(text), (text, G.detect(text))


@pytest.mark.req("PRIV-29")
def test_my_number_and_arc_kinds() -> None:
    n = "98765432101"
    full = n + str(my_number_check_digit(n))
    assert "JP_MY_NUMBER" in _kinds(f"マイナンバー {full}")
    arc = "A9" + "1234567"
    arc += tw_id_check_digit(arc)
    assert "TW_ARC" in _kinds(f"居留證號 {arc}")


@pytest.mark.req("PRIV-29")
def test_clinical_text_without_identifiers_is_left_alone() -> None:
    for text in (
        "HbA1c 7.2%，eGFR 45 mL/min/1.73m²，血壓 132/84 mmHg。",
        "Screened for NCT04157751; metformin 500 mg twice daily, BP 130/82.",
        "メトホルミン 500 mg を継続。次回は 4 週間後。",
        "2026-10-05 胸部 X 光未見明顯浸潤。",
    ):
        assert G.detect(text) == [], text
        assert G.redact(text) == text


@pytest.mark.req("PRIV-29", "S1-08")
def test_redaction_and_v1_guard_fold_in() -> None:
    red = G.redact("患者陳志明先生，身分證 A123456789，電話 0912-345-678。")
    assert "陳志明" not in red and "A123456789" not in red and "0912-345-678" not in red
    assert "[TW_NATIONAL_ID]" in red and "[PHONE]" in red
    nested = G.redact_obj({"messages": [{"role": "user", "content": "MRN 20481234"}], "n": 3})
    assert nested == {"messages": [{"role": "user", "content": "MRN [MRN]"}], "n": 3}
    # the v1 guard (tb_common.phi_guard.scan) still runs inside the tripwire: a bare field keyword is a hit
    v = G.tripwire("請填寫姓名欄位")
    assert v.hit and "KEYWORD" in v.kinds
    assert not G.tripwire("eGFR 45, HbA1c 7.2%").hit


def test_guard_http_surface() -> None:
    http = TestClient(create_app(G))
    body = http.post("/v1/scan", json={"text": "身分證 A123456789"}).json()
    assert body["hit"] and "A123456789" not in str(body)
    assert http.post("/v1/redact", json={"text": "身分證 A123456789"}).json()["text"] == "身分證 [TW_NATIONAL_ID]"
