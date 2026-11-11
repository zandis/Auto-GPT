"""The privacy documents and the incident plan of T-318 (D-411).

The incident plan carries the four severities, the six cases and the clock rows in each of its three languages;
the opt-out notice describes every function of REG-009 in Japanese and Traditional Chinese; every privacy document
the card names exists; the legal-basis memo is a slot, marked as dropped by D-311.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITES = ROOT / "docs" / "plan" / "sites"
PLAN = SITES / "incident-response.md"
PRIVACY = SITES / "privacy"

LANG_PARTS = {"en": "## A. English", "ja": "## B. 日本語", "zh-TW": "## C. 繁體中文"}
CASES = tuple(f"IC-{n}" for n in range(1, 7))
SEVERITIES = ("S1", "S2", "S3", "S4")
CLOCKS = tuple(f"C{n}" for n in range(1, 10))
KANA = re.compile(r"[぀-ヿ]")


def parts(path: Path, heads: dict[str, str]) -> dict[str, str]:
    """language -> the text of its part (from its heading to the next part's)."""
    text = path.read_text(encoding="utf-8")
    starts = {lang: text.index(head) for lang, head in heads.items()}
    order = sorted(starts, key=starts.__getitem__)
    out = {}
    for i, lang in enumerate(order):
        end = starts[order[i + 1]] if i + 1 < len(order) else len(text)
        out[lang] = text[starts[lang] : end]
    return out


def table_rows(text: str, key: str) -> list[str]:
    """Table rows whose first cell starts with ``key`` (e.g. ``IC-1`` or ``C2``)."""
    return re.findall(rf"^\| {re.escape(key)}\b[^\n]*\|$", text, re.M)


@pytest.mark.parametrize("lang", LANG_PARTS)
def test_six_cases_in_each_language(lang: str) -> None:
    part = parts(PLAN, LANG_PARTS)[lang]
    for case in CASES:
        assert len(table_rows(part, case)) == 1, f"{lang}: case {case} is not one table row"
    assert not table_rows(part, "IC-7")


@pytest.mark.parametrize("lang", LANG_PARTS)
def test_clocks_and_severities_in_each_language(lang: str) -> None:
    part = parts(PLAN, LANG_PARTS)[lang]
    for clock in CLOCKS:
        assert len(table_rows(part, clock)) == 1, f"{lang}: clock {clock} is not one table row"
    for sev in SEVERITIES:
        assert len(table_rows(part, sev)) == 1, f"{lang}: severity {sev} is not one table row"
    for role in (f"R{n}" for n in range(1, 8)):
        assert len(table_rows(part, role)) == 1, f"{lang}: role {role} is not one table row"


def test_the_legal_clocks_are_named() -> None:
    """The deadlines OPS-041 names: APPI 速報 3 to 5 days and 確報 30 or 60, Taiwan 72 hours, 資安法 1 hour,
    the vendor's 1 hour and 24 hours; each in all three languages."""
    p = parts(PLAN, LANG_PARTS)
    en = p["en"]
    assert "3 to 5 days" in table_rows(en, "C2")[0]
    assert "30 days" in table_rows(en, "C3")[0] and "60 days" in table_rows(en, "C3")[0]
    assert "72 hours" in table_rows(en, "C6")[0]
    assert "1 hour" in table_rows(en, "C8")[0]
    assert "1 hour" in table_rows(en, "C1")[0] and "24 hours" in table_rows(en, "C1")[0]
    assert "3〜5" in table_rows(p["ja"], "C2")[0]
    assert "60" in table_rows(p["ja"], "C3")[0]
    assert "72" in table_rows(p["zh-TW"], "C6")[0]
    assert "1 小時" in table_rows(p["zh-TW"], "C8")[0]
    assert "counsel confirms" in en.lower()


def test_language_parts_are_in_their_language() -> None:
    p = parts(PLAN, LANG_PARTS)
    assert KANA.search(p["ja"])
    body = re.sub(r"`[^`]*`", "", p["zh-TW"])  # code is shared
    assert not KANA.search(body), "the zh-TW part holds Japanese kana"
    for lang in ("ja", "zh-TW"):
        assert "INC-YYYYMMDD-n" in p[lang], f"{lang}: no notice template"


def test_first_hour_list_names_real_commands() -> None:
    text = PLAN.read_text(encoding="utf-8")
    for needed in ("support-bundle", "audit_verify", "tools.trialbox exports", "console.cli disable", "mail-gateway"):
        assert needed in text
    assert (ROOT / "tools" / "audit_verify.py").exists()
    assert (ROOT / "tools" / "support_bundle.py").exists()


DOCS = (
    "index.md",
    "record-of-processing.md",
    "dpia.md",
    "legal-basis-memo.md",
    "irb-pack.md",
    "opt-out-notice.md",
    "one-pager.md",
    "appi-pdpa-mapping.md",
    "data-destruction.md",
)


def test_every_privacy_document_exists_and_is_indexed() -> None:
    index = (PRIVACY / "index.md").read_text(encoding="utf-8")
    for name in DOCS:
        text = (PRIVACY / name).read_text(encoding="utf-8")
        assert text.startswith("# "), name
        if name != "index.md":
            assert f"]({name})" in index, f"index.md does not link {name}"
    assert "](../incident-response.md)" in index


def test_record_and_dpia_cover_both_sites_and_the_four_items() -> None:
    for name in ("record-of-processing.md", "dpia.md"):
        text = (PRIVACY / name).read_text(encoding="utf-8")
        assert "## 3. Japan head hospital" in text and "## 4. CGMH" in text, name
    ropa = (PRIVACY / "record-of-processing.md").read_text(encoding="utf-8")
    for cls in ("D0", "D1", "D2", "D3", "D4"):
        assert f"| {cls} " in ropa
    dpia = (PRIVACY / "dpia.md").read_text(encoding="utf-8")
    for item in ("Patient profiles", "The vector store", "The clinician role", "The steward's access"):
        assert f"| {item}" in dpia


NOTICE_PARTS = {"en": "## 1. English", "ja": "## 2. 日本語", "zh-TW": "## 3. 繁體中文"}


@pytest.mark.parametrize("lang", NOTICE_PARTS)
def test_opt_out_notice_covers_every_function(lang: str) -> None:
    part = parts(PRIVACY / "opt-out-notice.md", NOTICE_PARTS)[lang]
    for n in range(1, 9):
        assert len(re.findall(rf"^> - \*\*N{n} ", part, re.M)) == 1, f"{lang}: N{n} missing or repeated"
    assert "お申し出の後は利用しません" not in part  # the old promise REG-009 found


def test_legal_basis_memo_is_a_slot_dropped_by_d311() -> None:
    text = (PRIVACY / "legal-basis-memo.md").read_text(encoding="utf-8")
    assert "D-311 B26" in text and "T-646" in text
    assert "## 2. Filed memos" in text


def test_destruction_names_nist_and_a_certificate() -> None:
    text = (PRIVACY / "data-destruction.md").read_text(encoding="utf-8")
    assert "NIST SP 800-88" in text
    for method in ("Clear", "Purge", "Destroy"):
        assert f"**{method}**" in text or f"{method} " in text
    assert "Certificate of sanitization" in text
