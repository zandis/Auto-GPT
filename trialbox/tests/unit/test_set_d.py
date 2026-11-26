"""Constructed evidence, checked without the generator's answer function."""

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from tools import set_d

pytestmark = pytest.mark.nodb
REF = date(2026, 11, 1)


def oracle(pair: dict[str, Any]) -> str:
    def value(e: dict[str, Any]) -> bool | float | None:
        if e["status"] in {"suspected", "r/o", "resolved", "pending", "prn", "refill", "missing"}:
            return None
        if pair["kind"] == "lab":
            if not e["date"] or not 0 <= (REF - date.fromisoformat(e["date"])).days <= 365:
                return None
            if e["unit"] not in {"mg/dL", "umol/L"}:
                return None
            return cast(bool | float, e["value"]) / (59.48 if e["unit"] == "umol/L" else 1) >= 7
        if pair["kind"] == "drug":
            if e.get("stop") and date.fromisoformat(e["stop"]) <= REF:
                return False
            end = date.fromisoformat(e["date"]) + timedelta(days=e["days_supply"] + 30)
            return cast(bool | float, e["value"]) and date.fromisoformat(e["date"]) <= REF <= end
        return cast(bool | float, e["value"])

    def select(events: list[dict[str, Any]]) -> bool | float | None:
        usable = [e for e in events if value(e) is not None]
        if pair["kind"] == "drug":
            ranks = {"administration": 4, "dispense": 3, "claim": 3, "order": 2, "statement": 1}
            usable.sort(key=lambda e: (ranks[e["source"]], e["date"]), reverse=True)
        else:
            usable.sort(key=lambda e: e["date"], reverse=True)
        return value(usable[0]) if usable else None

    coded_rows = pair["coded"]
    if pair["kind"] == "diagnosis":
        newer = [e["date"] for e in pair["notes"] if e["status"] == "active" and e["value"] is True]
        coded_rows = [e for e in coded_rows if not (e["status"] == "no_history" and newer and e["date"] < max(newer))]
    coded, note = select(coded_rows), select(pair["notes"])
    if coded is not None and note is not None and coded != note:
        return "unknown"
    answer = coded if coded is not None else note
    return "unknown" if answer is None else "met" if answer else "not_met"


def test_gold_counts_and_independent_oracle() -> None:
    data = set_d.generate(seed=19, anchor=REF)
    pairs = data["pairs"]
    assert len(data["tables"]["patient"]) == 600
    assert Counter(p["cell"] for p in pairs) == set_d.DEFAULT_COUNTS
    assert set(Counter(p["patient"] for p in pairs).values()) == {4}
    assert {p["language"] for p in pairs} == {"en", "ja", "zh-TW"}
    assert {e["status"] for p in pairs for e in p["coded"] + p["notes"]} >= {
        "suspected",
        "r/o",
        "resolved",
        "pending",
        "prn",
        "refill",
    }
    for p in pairs:
        assert p["expected"] == oracle(p), p
        assert p["truth"] in (True, False)
        assert p["evidence"] == sorted(p["coded"] + p["notes"], key=lambda e: e["date"] or "", reverse=True)
    assert {p["coded"][0]["value"] for p in pairs if p["cell"] == "conflicting"} == {True, False, 5.0, 9.0}


def test_seed_bytes_and_feed_reader(tmp_path: Path) -> None:
    from adapter.sources.csv.source import CsvSource

    outputs: list[dict[str, bytes]] = []
    for name, seed in [("a", 11), ("b", 11), ("c", 12)]:
        folder = tmp_path / name
        data = set_d.generate(seed=seed, anchor=REF)
        set_d.write(data, folder)
        outputs.append({p.name: p.read_bytes() for p in folder.iterdir()})
        reader = CsvSource(folder)
        for table, rows in data["tables"].items():
            assert list(reader.rows(table, table, None, None)) == rows
    assert outputs[0] == outputs[1]
    assert outputs[0] != outputs[2]


def test_configurable_counts() -> None:
    counts = dict.fromkeys(set_d.DEFAULT_COUNTS, 8)
    assert len(set_d.generate(seed=1, anchor=REF, counts=counts)["pairs"]) == 48
    with pytest.raises(ValueError):
        set_d.generate(seed=1, anchor=REF, counts={"agreeing": 3})


def test_exposure_ranks_stops_and_supply_boundaries() -> None:
    pairs = set_d.generate(seed=19, anchor=REF)["pairs"]
    drugs = [p for p in pairs if p["kind"] == "drug"]
    assert any(len(p["coded"]) > 1 for p in drugs)
    assert {e["source"] for p in drugs for e in p["coded"]} >= {"administration", "dispense", "claim", "order"}
    assert any(p["expected"] == "not_met" and any(e["stop"] == REF.isoformat() for e in p["coded"]) for p in drugs)
    assert any(
        p["expected"] == "met" and any(e["days_supply"] == 90 and e["date"] == "2026-07-04" for e in p["coded"])
        for p in drugs
    )
    for p in drugs:
        assert p["expected"] == oracle(p)


def test_hidden_history_and_patient_context() -> None:
    data = set_d.generate(seed=19, anchor=REF)
    assert len(data["patients"]) == 600
    for patient in data["patients"]:
        assert patient["allergies"] and patient["visits"]
    for pair in data["pairs"]:
        assert pair["hidden"]["value"] == pair["truth"] or pair["kind"] == "lab"
        if pair["cell"] == "agreeing":
            assert pair["coded"][0]["value"] == pair["notes"][0]["value"]
        if pair["cell"] == "note_only":
            assert not pair["coded"]
        if pair["cell"] == "missing":
            assert not pair["coded"] and pair["expected"] == "unknown"


def test_newer_diagnosis_supersedes_old_no_history() -> None:
    pairs = set_d.generate(seed=19, anchor=REF)["pairs"]
    cases = [
        p
        for p in pairs
        if p["kind"] == "diagnosis" and p["coded"] and all(e["status"] == "no_history" for e in p["coded"])
    ]
    assert cases
    assert all(p["expected"] == oracle(p) == "met" for p in cases)


def test_note_words_preserve_assertion_polarity() -> None:
    for pair in set_d.generate(seed=19, anchor=REF)["pairs"]:
        for note in pair["notes"]:
            if pair["kind"] != "lab" and note["status"] == "active":
                assert note["value"] is True
            if pair["kind"] != "lab" and note["status"] == "absent":
                assert note["value"] is False
            assert note["text"]
