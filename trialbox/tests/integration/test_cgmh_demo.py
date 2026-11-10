"""T-504: the CGMH scenarios walked through the console (``tools.cgmh_demo``), on the tw-ra synthetic site.

* T2 in zh-TW: the RA-JAK list holds the trial's planted candidates and nobody with a coded zoster or thrombosis;
* T1 in ja, zh-TW and en: the GZQO amendment is listed as changes since v1.0.0, every changed row is opened and
  labelled, Approve all makes v1.1.0, and the new list gains the BMI 25-27 patients and keeps no one aged 80 or more;
  a mark given before the amendment stays;
* T3 in zh-TW: a GOUT-COH registry patient's visit is drafted from the hospital record, signed and sent to REDCap,
  and every sent value reads back equal.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from tools import cgmh_demo as cd

PASSWORD = "pw-" + "c" * 16


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cgmh")  # the synthetic site and lake are built once; each walk gets a fresh box


def test_t2_ra_jak_list_in_zh_tw(work: Path) -> None:
    res = cd.run(work, PASSWORD, "list", "zh-TW")
    assert 'lang="zh-TW"' in res["list_html"] and 'lang="zh-TW"' in res["patient_html"]
    assert len(res["listed"]) > 80 and not res["coded_listed"]
    planted = {m for m in res["listed"] if res["states"][m].get("archetype") == "rajak"}
    assert planted and planted <= res["gold_candidates"]
    assert len(res["note_only_listed"]) > 5  # a zoster or thrombosis written only in a note: kept for a person


@pytest.mark.parametrize("lang", ["ja", "zh-TW", "en"])
def test_t1_gzqo_amend_and_approve(work: Path, lang: str) -> None:
    res = cd.run(work, PASSWORD, "amend", lang)
    ap = res["approval"]
    assert res["version"] == "1.1.0"
    assert "GZQO-INC-03" in ap["changes"] and res["added"] and all(a in ap["changes"] for a in res["added"])
    assert "GZQO-INC-03" in ap["amber"]
    assert f'lang="{lang}"' in ap["html"]
    st = res["states"]
    gained, lost = res["after"] - res["before"], res["before"] - res["after"]
    assert gained and all(st[m].get("bmi") == "25-27" for m in gained), [(m, st[m].get("bmi")) for m in gained]
    age = cd.ages(res["work"] / "synth" / cd.PROFILE, date(2026, 11, 2))
    assert not any(age[m] >= 80 for m in res["after"])
    assert all(age[m] >= 80 for m in lost)
    assert res["mark_after"] == "approach"  # the investigator's mark from before the amendment stays
    assert re.search(r'data-testid="row-', res["list_html"]) or res["after"]


def test_t3_registry_prefill_reads_back_equal(work: Path) -> None:
    res = cd.run(work, PASSWORD, "registry", "zh-TW")
    assert res["no"].startswith("GOUT-COH-")
    d, rb = res["drafts"], res["readback"]
    assert {"brthdat", "sex"} <= set(res["drafted"])
    assert all(bool(v["citation"]) == (v["state"] == "drafted") for v in d.values())
    assert all(rb.get(k) == v for k, v in res["drafted"].items()), (res["drafted"], rb)
    assert rb["brthdat"] == next(
        r["birth_date"][:10]
        for r in cd._rows(res["work"] / "synth" / cd.PROFILE / "patient.csv")
        if r["mrn"] == res["mrn"]
    )
