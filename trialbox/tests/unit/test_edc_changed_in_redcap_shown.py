"""NEW-EDC-5b (D-686, the follow-up of D-695): a value that changed in REDCap after TrialBox sent it is shown where
a person decides it.

D-695 listed such a value on each send and in the trail; the review page went on showing TrialBox's value alone.
The drafts the review page reads now carry what REDCap holds (`redcap_now`) while the change is open, and the page
shows it beside the value with what to do. Synthetic data only."""

from __future__ import annotations

from pathlib import Path

from edc.service import EdcService
from fastapi import FastAPI
from orchestrator.edc_api import router

from tests import edc_kit as k
from tests.actor3 import SignedClient
from tests.unit.test_edc_t302b import SCREEN1, _edit_in_redcap, _enter, _service


def _drafts_api(svc: EdcService, record: str) -> dict[str, dict[str, object]]:
    app = FastAPI()
    app.include_router(router(lambda: svc))
    r = SignedClient(app).get(f"/studies/{k.STUDY}/edc/drafts", params={"record": record})
    assert r.status_code == 200, r.text
    rows = r.json()
    return {str(d["item"]): d for d in rows}


def test_a_value_changed_in_redcap_carries_what_redcap_holds_until_it_is_equal_again(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    svc.send_redcap(k.STUDY, "crc")
    assert _drafts_api(svc, "S-001")["weight"]["redcap_now"] is None
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "70.1"})
    svc.reconcile(k.STUDY, "crc")
    d = _drafts_api(svc, "S-001")
    assert d["weight"]["redcap_now"] == "70.1" and d["urate"]["redcap_now"] is None
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "72.5"})
    svc.reconcile(k.STUDY, "crc")
    assert _drafts_api(svc, "S-001")["weight"]["redcap_now"] is None


def test_a_long_redcap_value_is_shown_cut_and_says_so(tmp_path: Path) -> None:
    """The ledger's detail is cut at 300 characters: the page shows the start and says the rest is in REDCap."""
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {"tophus": "1", "tophus_site": "right ear"})
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "tophus_site": "y" * 280})
    svc.reconcile(k.STUDY, "crc")
    got = str(_drafts_api(svc, "S-001")["tophus_site"]["redcap_now"])
    assert got.startswith("y" * 100) and got.endswith("…") and len(got) < 280


def test_the_review_page_shows_it_in_three_languages() -> None:
    from console.i18n_edc import EN, JA, ZH

    page = (Path(__file__).resolve().parents[2] / "services/console/templates/edc_review.html").read_text("utf-8")
    assert "redcap_now" in page and "changed-in-redcap-" in page
    for lang in (EN, JA, ZH):
        assert "edc.review.changed_in_redcap" in lang
