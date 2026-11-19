"""Card 10G-35: the back-translation check of eval/criterion_ml ja and zh-TW.

The two record files are well formed, hold one record per sentence of the eval files with the same id, source and
translation, and the counts on the measurement page equal the counts in the files.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "eval" / "criterion_ml"
PAGE = ROOT / "docs" / "plan" / "measurements" / "back-translation-check-2026-11-18.md"
RECORDS = PAGE.with_suffix("")
LANGS = {"ja": "notes_ja.json", "zh-TW": "notes_zh-TW.json"}
KINDS = {
    "number_or_unit",
    "negation",
    "time_window",
    "dropped_condition",
    "wrong_term",
    "added_detail",
    "certainty",
    "register",
}


def _doc(lang: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((RECORDS / f"{lang}.json").read_text("utf-8"))
    return doc


def _row(cells_start: str) -> list[str]:
    for line in PAGE.read_text("utf-8").splitlines():
        if line.startswith(cells_start):
            return [c.strip() for c in line.strip().strip("|").split("|")]
    raise AssertionError(f"no row {cells_start!r} on the page")


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_records_are_well_formed_and_match_the_eval_files(lang: str) -> None:
    doc = _doc(lang)
    en = json.loads((EVAL / "notes_en.json").read_text("utf-8"))
    tr = json.loads((EVAL / LANGS[lang]).read_text("utf-8"))
    assert doc["language"] == lang and doc["card"] == "10G-35"
    assert "machine reader" in doc["reader"] and "not a clinician" in doc["reader"]
    assert "CC BY-SA 4.0" in doc["attribution"] and "CSIRO" in doc["attribution"]
    ids = [r["id"] for r in doc["records"]]
    assert len(ids) == len(set(ids)) == sum(len(s) for s in en.values())
    for r in doc["records"]:
        pid, idx = r["id"].rsplit("#", 1)
        assert pid == r["patient_id"] and int(idx) == r["sentence_index"]
        assert r["source"] == en[pid][int(idx)]
        assert r["translation"] == tr[pid][int(idx)]
        assert r["back_translation"].strip()
        assert r["verdict"] in {"equal", "differs"}
        if r["verdict"] == "differs":
            assert r["kinds"] and set(r["kinds"]) <= KINDS
            assert r["severity"] in {"low", "medium", "high"}
            assert r["what_differs"] and r["proposed_correction"]
        else:
            assert r["kinds"] == [] and r["severity"] is None and r["proposed_correction"] is None


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_page_counts_equal_the_files(lang: str) -> None:
    recs = _doc(lang)["records"]
    differs = [r for r in recs if r["verdict"] == "differs"]
    en = json.loads((EVAL / "notes_en.json").read_text("utf-8"))
    row = _row(f"| {lang} | ")
    assert row[1:] == [
        str(sum(len(s) for s in en.values())),
        str(len(recs)),
        str(len(recs) - len(differs)),
        str(len(differs)),
        str(sum(1 for r in differs if r["kinds"] == ["register"])),
    ]
    kinds = Counter(k for r in differs for k in r["kinds"])
    col = 1 if lang == "ja" else 2
    for kind in KINDS:
        assert _row(f"| `{kind}` |")[col] == str(kinds[kind]), kind


def test_page_says_the_reader_is_not_a_clinician_and_readme_unchanged() -> None:
    head = PAGE.read_text("utf-8")[:600]
    assert "machine reader" in head and "not a clinician" in head
    assert re.search(r"not\*\* clinician-verified", (EVAL / "README.md").read_text("utf-8"))
