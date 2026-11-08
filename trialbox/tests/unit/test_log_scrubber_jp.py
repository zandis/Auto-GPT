"""Japanese PHI in the log scrubber (TB-PLAN-03 step 6, D-121): My Number, insurance numbers, postcodes, phones."""

from __future__ import annotations

import pytest
from tb_common.logging import redact


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("個人番号: 1234 5678 9012", "[MYNUMBER]"),
        ("マイナンバー１２３４－５６７８－９０１２", "[MYNUMBER]"),
        ("id 1234-5678-9012 seen", "[MYNUMBER]"),
        ("保険者番号 06130012", "[INSURANCE]"),
        ("被保険者番号：１２３４５６７８", "[INSURANCE]"),
        ("〒100-0001 東京都千代田区", "[POSTCODE]"),
        ("〒１００－０００１", "[POSTCODE]"),
        ("+81-3-1234-5678", "[PHONE]"),
        ("+81 90 1234 5678", "[PHONE]"),
        ("090-1234-5678", "[PHONE]"),
        ("０９０－１２３４－５６７８", "[PHONE]"),
        ("03-1234-5678", "[PHONE]"),
        ("0466-12-3456", "[PHONE]"),
    ],
)
def test_japanese_identifiers_are_scrubbed(text: str, token: str) -> None:
    out = redact(text)
    assert token in out
    assert not any(ch.isdigit() for ch in out.replace(token, "")), out


@pytest.mark.parametrize(
    "text",
    ["2026-11-08 07:00", "job 01JITCOMPILE00000000000000", "P0156 lookback=36m", "count 1234 rows", "GZQO v1.0.0"],
)
def test_ordinary_log_text_is_kept(text: str) -> None:
    assert redact(text) == text
