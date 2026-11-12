"""Trial-opportunity feed (D-449): only rounded aggregates, signed by the site, refused when anything else slips in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from opportunity_hub.dashboard import render
from tb_common import opportunity as opp
from tb_common.crypto import ed25519_generate

from tools import opportunity_feed as tool

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "open_data" / "ctgov_NCT04157751.json"


def _sim(eligible: int | str = 437, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "nct_id": "NCT00000001",
        "title": "A study",
        "phases": ["PHASE3"],
        "sponsor": "Sponsor",
        "last_update": "2026-11-01",
        "target_enrollment": 300,
        "criteria_total": 6,
        "criteria_applied": 4,
        "eligible_now": eligible,
        "new_per_month": 12.34,
        "enrol_12m_low": 20.4,
        "enrol_12m_mid": 40.6,
        "enrol_12m_high": 61.0,
        "steps": steps
        if steps is not None
        else [
            {"criterion_id": "a", "label": "pool", "applied": True, "remaining": 1000},
            {"criterion_id": "b", "label": "eGFR < 30", "applied": True, "remaining": 702},
            {"criterion_id": "c", "label": "not counted", "applied": False, "remaining": None},
            {"criterion_id": "d", "label": "prior anti-amyloid", "applied": True, "remaining": 698},
            {"criterion_id": "e", "label": "MRI exclusion", "applied": True, "remaining": 437},
        ],
        "note": "automatic compile",
    }


def _feed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return opp.build(
        site_id="tw",
        site_label="Taiwan",
        country="Taiwan",
        snapshot="2026-11-11",
        registry_source="cassette",
        registry_sha256=None,
        conditions=["Alzheimer Disease"],
        rows=rows,
    )


def test_counts_rounded_and_exclusions_ranked() -> None:
    row = opp.row_from_sim(_sim(), "Alzheimer Disease")
    assert row["eligible_now"] == 440
    assert row["new_per_month"] == 12.3
    assert row["enrol_12m"] == {"low": 20, "mid": 41, "high": 61}
    # drops after the pool: 298 (eGFR), 4 (anti-amyloid, rounds to "<10"), 261 (MRI); the pool itself is not listed
    assert row["top_exclusions"] == [
        {"criterion": "eGFR < 30", "removed": 300},
        {"criterion": "MRI exclusion", "removed": 260},
        {"criterion": "prior anti-amyloid", "removed": "<10"},
    ]
    assert "steps" not in row


def test_small_cell_drops_rates_and_exclusions() -> None:
    for eligible in (7, "<5"):
        row = opp.row_from_sim(_sim(eligible), "AD")
        assert row["eligible_now"] == "<10"
        assert row["new_per_month"] is None and row["enrol_12m"] is None and row["top_exclusions"] == []


def test_guard_refuses_patient_level_or_unrounded() -> None:
    good = opp.row_from_sim(_sim(), "AD")
    _feed([good])
    with pytest.raises(opp.FeedRefused, match="row keys"):
        _feed([{**good, "patients": ["P1"]}])
    with pytest.raises(opp.FeedRefused, match="not rounded"):
        _feed([{**good, "eligible_now": 437}])
    with pytest.raises(opp.FeedRefused, match="small cell"):
        _feed([{**good, "eligible_now": "<10"}])
    with pytest.raises(opp.FeedRefused, match="feed keys"):
        opp.guard({**_feed([good]), "mrn": "1"})


def test_sign_and_verify() -> None:
    priv, pub = ed25519_generate()
    _, other = ed25519_generate()
    signed = opp.sign(_feed([opp.row_from_sim(_sim(), "AD")]), priv, pub)
    assert opp.verify(signed, pub)
    assert not opp.verify(signed, other)
    tampered = json.loads(json.dumps(signed))
    tampered["rows"][0]["eligible_now"] = 990
    assert not opp.verify(tampered, pub)


def test_dashboard_holds_only_feed_values() -> None:
    priv, pub = ed25519_generate()
    signed = opp.sign(_feed([opp.row_from_sim(_sim(), "AD")]), priv, pub)
    page = render([(signed, True)], lang="ja")
    assert page.startswith("<!doctype html>") and "治験機会ボード" in page
    assert "NCT00000001" in page and "</script>" in page
    assert '"verified": true' in page
    frag = render([(signed, False)], standalone=False)
    assert "<html" not in frag and '"verified": false' in frag


def test_sample_from_a_registry_record(tmp_path: Path) -> None:
    rec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    study = rec.get("study") or rec
    cache = {f"{c}|{s['country']}": [study] for s in tool.SAMPLE_SITES for c in s["conditions"]}
    off = tmp_path / "cache.json"
    off.write_text(json.dumps(cache), encoding="utf-8")
    page = tool.sample(tmp_path / "out", off)
    assert page.exists()
    for site in tool.SAMPLE_SITES:
        feed = json.loads((tmp_path / "out" / f"feed-{site['site_id']}.json").read_text(encoding="utf-8"))
        assert feed["synthetic"] is True and feed["signature"]["alg"] == "ed25519"
        opp.guard(feed)
