"""DEMO-SEED-2 (D-758): the seeded CASE sheet reads what its synthetic chart says, the demo's people receive it, and
the reworded exclusion's English label is a whole phrase."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from tools import demo
from tools import feas_demo as fd
from tools import list_demo as ld


def test_the_english_label_of_the_reworded_exclusion_is_whole() -> None:
    assert len(ld.EXTRA_EXCLUSION) <= 40  # a draft's short label takes the first 40 characters in English


@pytest.mark.parametrize(
    ("question", "text", "verdict"),
    [
        ("Body mass index (BMI) ≥27 kg/m² at screening.", "2026年11月6日門診紀錄。BMI 31.4 kg/m2。", "pass"),
        ("Body mass index (BMI) ≥27 kg/m² at screening.", "2026年11月6日門診紀錄。BMI 24.0 kg/m2。", "fail"),
        ("HbA1c >10% at screening.", "2026年11月6日門診紀錄。HbA1c 7.6%。", "fail"),
        ("HbA1c >10% at screening.", "2026年11月6日門診紀錄。HbA1c 11.2%。", "pass"),
    ],
)
def test_the_stub_reads_a_number_the_chart_states(question: str, text: str, verdict: str) -> None:
    from llm_stub.handlers import judge

    out = judge({"note_question": question, "index_date": "2026-11-16",
                 "excerpts": [{"date": "2026-11-06", "text": text}]})  # fmt: skip
    assert out["verdict"] == verdict and out["quote"] in text


@pytest.mark.parametrize("lang", ["zh-TW", "ja", "en"])
def test_the_chart_is_dated_from_the_demo_day_in_its_language(lang: str) -> None:
    chart = demo.case_chart(lang, date(2026, 11, 17))
    assert "BMI 31.4" in chart and "HbA1c 7.6%" in chart
    visit = "2026年11月7日" if lang != "en" else "2026-11-07"  # ten days before the demo day
    assert visit in chart and chart.count("2026") >= 3  # the visit and two flares within the year before


def test_the_people_who_read_patient_data_are_named_recipients(tmp_path: Path) -> None:
    from tests.inproc_box import _add_list_to

    env = {"TB_DEMO_PEOPLE": "ana:investigator, ben:coordinator, cy:viewer"}
    assert fd.people_mailboxes(env) == ("ana@hospa.test", "ben@hospa.test")
    assert fd.people_mailboxes({}) == ()
    (tmp_path / "GZQO").mkdir()
    (tmp_path / "GZQO" / "manifest.yaml").write_text(
        yaml.safe_dump({"id": "GZQO", "routing": {"list_to": ["pi@hospa.test"]}}), encoding="utf-8"
    )
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "GZQO.yaml").write_text(
        yaml.safe_dump({"routing": {"list_to": ["crc1@hospa.test"]}}), encoding="utf-8"
    )
    _add_list_to(tmp_path, fd.people_mailboxes(env))
    doc = yaml.safe_load((tmp_path / "GZQO" / "manifest.yaml").read_text(encoding="utf-8"))
    assert doc["routing"]["list_to"] == ["pi@hospa.test", "ana@hospa.test", "ben@hospa.test"]
    profile = yaml.safe_load((tmp_path / "profiles" / "GZQO.yaml").read_text(encoding="utf-8"))
    assert profile["routing"]["list_to"] == ["crc1@hospa.test", "ana@hospa.test", "ben@hospa.test"]  # a draft's


def test_the_boot_passes_the_people_to_the_seed() -> None:
    root = Path(__file__).resolve().parents[2]
    assert "TB_DEMO_PEOPLE=$PEOPLE" in (root / "deploy" / "gcp" / "demo-vm-boot.sh").read_text(encoding="utf-8")
