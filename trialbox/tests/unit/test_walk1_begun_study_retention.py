"""WALK-1 (the review of D-1153): a study only begun is no running study for RETENTION.

The console records start-up when a protocol is sent for a study it does not know (F-14). Before that row existed, a
feasibility of a trial the site then declined had no recorded state, and RETENTION let its files age out (D-765:
"no row" is not a running study). A study whose one row is that start-up is read the same way; once it moves (opened,
paused) or was set up before, it is held as a running study. Synthetic data only."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_per_study_retention_after_close import JID, RECENT, _box, _job, _put, _retention


def _begin(rid: str) -> None:
    from console.sitestore import SiteStore

    assert SiteStore().begin_study(rid, "console:crc", RECENT) is not None


def test_a_study_only_begun_ages_out_like_one_never_set_up(tmp_path: Path) -> None:
    ob = _box(tmp_path)
    _job(ob, JID, "DECLINED")
    _begin("DECLINED")
    _put(ob, f"attachments/{JID}/protocol.pdf", 400)
    report = _retention(ob)
    assert not ob.store.exists(f"attachments/{JID}/protocol.pdf")
    assert report["held_for_running_studies"] == 0


def test_a_begun_study_that_opened_is_held(tmp_path: Path) -> None:
    from console.sitestore import SiteStore

    ob = _box(tmp_path)
    _job(ob, JID, "OPENED")
    _begin("OPENED")
    SiteStore().set_study_state("OPENED", "open", "", "console:crc", RECENT)
    _put(ob, f"attachments/{JID}/protocol.pdf", 400)
    report = _retention(ob)
    assert ob.store.exists(f"attachments/{JID}/protocol.pdf") and report["held_for_running_studies"] == 1
