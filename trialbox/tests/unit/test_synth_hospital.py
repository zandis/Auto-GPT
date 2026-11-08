"""The synthetic hospital (TB-DS-21): JP/TW styles, JA/zh-TW/EN notes, gold offsets, PHI spans, rates and checks."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from tools.synth.generator import RATES, Generator, generate, tw_id_valid
from tools.synth.lang import Lang, roc_year, wareki
from tools.synth.reserved import is_reserved
from tools.synth_hospital import SLOTS, note_criteria, run

ROOT = Path(__file__).resolve().parents[2]
REF = date(2026, 11, 1)


def test_default_generator_still_writes_the_committed_fixture() -> None:
    """Moving the rates into rates.yaml and adding styles/languages keeps the default path byte-identical."""
    data = generate(42, "DEMO-A", date(2026, 10, 5), 600, "1")
    with (ROOT / "tests/fixtures/synthetic_patients/site-a/note.csv").open(encoding="utf-8", newline="") as fh:
        committed = list(csv.DictReader(fh))
    assert [r["text"] for r in committed] == [r["text"] for r in data.tables["note"]]
    states = json.loads((ROOT / "tests/fixtures/synthetic_patients/site-a/states.json").read_text(encoding="utf-8"))
    assert states == data.states


def test_rates_file_matches_the_spec_values() -> None:
    assert RATES["site"]["mix"] == {"gout": 0.3, "ra": 0.26, "onc": 0.04, "general": 0.4}
    assert RATES["gout"]["flare_12m"] == {"two_plus": 0.45, "single": 0.15, "none": 0.15, "no_info": 0.25}
    assert RATES["phi"]["note_rate"]["carries"] == 0.7


def test_jp_site_names_ids_and_notes() -> None:
    g = Generator(5, "JP-T", REF, 300, "2", style="JP", lang_mix={"ja": 0.8, "en": 0.2}, gold=True)
    data = g.run()
    p = data.tables["patient"][0]
    assert "　" in p["name"] or " " in p["name"]
    assert p["id_no"].startswith("00") and len(p["id_no"]) == 8  # 法別番号 00 is never issued
    assert p["phone"][:4] in ("070-", "080-", "090-")
    langs = set(g.note_lang.values())
    assert langs == {"ja", "en"}
    ja = next(n["text"] for n in data.tables["note"] if g.note_lang[n["mrn"]] == "ja")
    assert "。" in ja and "病人" not in ja and "診斷" not in ja  # Japanese templates, not the zh-TW ones
    assert len(data.needles) == 6  # the JA needle set, all planted


def test_gold_offsets_findings_and_phi_spans() -> None:
    g = Generator(9, "TW-T", REF, 400, "3", style="TW", lang_mix={"zh-TW": 0.7, "en": 0.3}, gold=True)
    data = g.run()
    text = {n["note_no"]: n["text"] for n in data.tables["note"]}
    assert len(g.gold_notes) == len(text)
    crits = set()
    phi_types = set()
    for gn in g.gold_notes:
        t = text[gn["note_no"]]
        for f in gn["findings"]:
            span = t[f["start"] : f["end"]]
            assert span and span[-1] in "。. ", span
            crits.add(f["criterion"])
        for s in gn["phi"]:
            span = t[s["start"] : s["end"]]
            assert span and span.strip() == span, (s, span)
            if s["type"] == "chart":
                assert span == gn["mrn"]
            phi_types.add(s["type"])
    assert crits == set(SLOTS)
    assert {"name", "date", "chart", "phone", "address"} <= phi_types
    # TW national IDs never carry a valid check digit in gold mode
    assert not any(tw_id_valid(r["id_no"]) for r in data.tables["patient"])


def test_date_forms() -> None:
    assert wareki(date(2026, 3, 5)) == "令和8年3月5日"
    assert wareki(date(2019, 5, 1)) == "令和元年5月1日"
    assert wareki(date(2019, 4, 30)) == "平成31年4月30日"
    assert roc_year(date(2026, 3, 5)) == "民國115年3月5日"
    assert Lang("en").fmt_date(date(2026, 3, 5)) == "5 Mar 2026"
    assert Lang("zh-TW").fmt_date(date(2026, 3, 5)) == "2026年3月5日"


def test_tw_id_check_digit_and_reserved_patterns() -> None:
    assert tw_id_valid("A123456789")  # the textbook example
    assert not tw_id_valid("A123456788")
    assert is_reserved("name", "蔡英文") and not is_reserved("name", "陳家明")
    assert is_reserved("insurer", "06123456") and not is_reserved("insurer", "00123456")
    assert is_reserved("phone", "119")


def test_every_ruleset_note_criterion_has_a_slot() -> None:
    studies = sorted(p.name for p in (ROOT / "rulesets").iterdir() if (p / "ir").is_dir())
    assert set(note_criteria(studies)) <= set(SLOTS)


def test_small_run_passes_checks_and_is_deterministic(tmp_path: Path) -> None:
    kw = {"sites": "jp-a:JP:700,tw-a:TW:700", "chunk": 300}  # chunked: 3 chunks per site
    a = run(tmp_path / "a", **kw)  # type: ignore[arg-type]
    b = run(tmp_path / "b", **kw)  # type: ignore[arg-type]
    assert a.passed, a.failures
    assert a.summary["digest"] == b.summary["digest"]
    site = tmp_path / "a" / "jp-a"
    with (site / "patient.csv").open(encoding="utf-8", newline="") as fh:
        mrns = [r["mrn"] for r in csv.DictReader(fh)]
    assert len(mrns) == len(set(mrns)) == 700 and all(len(m) == 8 for m in mrns)
    with (site / "note.csv").open(encoding="utf-8", newline="") as fh:
        notes = {r["note_no"]: r["text"] for r in csv.DictReader(fh)}
    gold = [json.loads(x) for x in (site / "gold" / "notes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {g["note_no"] for g in gold} == set(notes)
    for g in gold:  # offsets hold against the text as written to disk
        for f in g["findings"] + g["phi"]:
            assert 0 <= f["start"] < f["end"] <= len(notes[g["note_no"]])
    states = json.loads((site / "states.json").read_text(encoding="utf-8"))
    assert len(states) == 700
    assert json.loads((site / "needles.json").read_text(encoding="utf-8"))
    assert any(r["status"] == "ok" for r in a.rates)
