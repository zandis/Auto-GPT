"""NEW-LIFE-10 / T-305c (D-779): a closed study's files are kept for its own period after the close.

D-765 held a study's files while it ran and, after the close, let the configured ages apply at once: the candidate
lists, the evidence, the review workbook and the protocol file went the night after the close (GCP keeps the study
file for a period after the trial). Now:

* the close records how many years the study's files are kept after it (the trial office gives the number on the
  close form; prefilled with the default, ``tb_common.retention.STUDY_YEARS_AFTER_CLOSE``; 1 to 30);
* RETENTION holds a closed study's attachments, outputs, pool and marks until the close day plus that period; a close
  recorded before this change (no number) is kept for the default period; after the period, the configured ages
  apply;
* the state page says until when the files are kept; the night's report counts what was held after a close.

On the test's own trial database (the console's real state table) and the console's real state page. Synthetic data
only."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common.retention import STUDY_YEARS_AFTER_CLOSE, held_after_close, kept_until
from tb_contracts import JobCreate

from tests.console.test_close_only_an_empty_study import clock  # noqa: F401 - the fixture is used by name
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_sdv import PW, sb  # noqa: F401 - the fixture is used by name
from tests.inproc_box import make_box

JID = "01JSTVDYSCREEN0000000000AA"  # a SCREEN of study GZQO
RECENT = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")  # closed a month ago
LONG_AGO = "2015-01-02T00:00:00+00:00"


# ---------------------------------------------------------------------------------------------- the rule
def test_the_period_counts_from_the_close_day() -> None:
    assert kept_until("2026-01-02T00:00:00+00:00", 3) == date(2029, 1, 2)
    assert kept_until("2026-01-02T00:00:00+00:00", None) == date(2026 + STUDY_YEARS_AFTER_CLOSE, 1, 2)
    assert kept_until("2024-02-29T10:00:00+00:00", 1) == date(2025, 2, 28)  # a leap day closes on the month's last
    now = datetime(2029, 1, 1, tzinfo=UTC)
    assert held_after_close("2026-01-02T00:00:00+00:00", 3, now)
    assert not held_after_close("2026-01-02T00:00:00+00:00", 3, now + timedelta(days=1))


# ---------------------------------------------------------------------------------------------- RETENTION
def _box(tmp_path: Path) -> Any:
    sec = tmp_path / "sec"
    sec.mkdir()
    return make_box(tmp_path / "ob", tmp_path / "lake", sec, date(2026, 10, 5))


def _put(ob: Any, key: str, age_days: int) -> None:
    ob.store.put(key, key.encode())
    t = (datetime.now(UTC) - timedelta(days=age_days)).timestamp()
    os.utime(ob.store.root / key, (t, t))


def _job(ob: Any, jid: str, ruleset: str) -> None:
    from tb_contracts import Job

    ob.orch.db.put(Job(job_id=jid, type="SCREEN", ruleset=ruleset, requested_by="crc@hospa.test",
                        received_at=datetime(2026, 1, 5, tzinfo=UTC), state="done"), queued=False)  # fmt: skip


def _close(rid: str, at: str, years: int | None) -> None:
    from console.sitestore import SiteStore

    SiteStore().set_study_state(rid, "closed", "last patient out", "crc", at, keep_years=years)


def _retention(ob: Any) -> dict[str, Any]:
    created = ob.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    ob.orch.drain()
    job = ob.orch.db.get(created.job_id)
    assert job is not None and job.state == "done", job.error if job else None
    out = next(o for o in job.outputs if o.filename.startswith("retention_"))
    report: dict[str, Any] = json.loads(ob.store.get(out.minio_key))
    return report


def test_a_closed_study_keeps_its_files_for_its_period(tmp_path: Path) -> None:
    ob = _box(tmp_path)
    _job(ob, JID, "GZQO")
    _close("GZQO", RECENT, 3)
    _put(ob, f"attachments/{JID}/protocol.pdf", 120)
    _put(ob, f"outputs/{JID}/candidate_list.xlsx", 400)
    report = _retention(ob)
    assert ob.store.exists(f"attachments/{JID}/protocol.pdf")
    assert ob.store.exists(f"outputs/{JID}/candidate_list.xlsx")
    assert report["held_after_close"] == 2 and report["held_for_running_studies"] == 0


def test_after_the_period_the_ages_apply(tmp_path: Path) -> None:
    ob = _box(tmp_path)
    _job(ob, JID, "GZQO")
    _close("GZQO", LONG_AGO, 3)
    _put(ob, f"attachments/{JID}/protocol.pdf", 120)
    report = _retention(ob)
    assert not ob.store.exists(f"attachments/{JID}/protocol.pdf") and report["held_after_close"] == 0


def test_a_close_recorded_without_a_period_keeps_the_default(tmp_path: Path) -> None:
    ob = _box(tmp_path)
    _job(ob, JID, "GZQO")
    _close("GZQO", RECENT, None)  # a close made before the period was asked
    _put(ob, f"attachments/{JID}/protocol.pdf", 120)
    assert _retention(ob)["held_after_close"] == 1 and ob.store.exists(f"attachments/{JID}/protocol.pdf")


def test_a_closed_studys_pool_is_kept_for_its_period(tmp_path: Path) -> None:
    ob = _box(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=900)).isoformat()
    ob.orch.db.pool_upsert("CLOSED1", "1.0.0", [{"pid": "p1", "tier": "high", "verdicts": {}}], "J0", old)
    ob.orch.db.pool_upsert("CLOSED2", "1.0.0", [{"pid": "p2", "tier": "high", "verdicts": {}}], "J0", old)
    _close("CLOSED1", RECENT, 3)
    _close("CLOSED2", LONG_AGO, 3)
    _retention(ob)
    assert "CLOSED1" in ob.orch.db.pool_rulesets() and "CLOSED2" not in ob.orch.db.pool_rulesets()


def test_a_bad_period_is_refused_by_the_store() -> None:
    from console.sitestore import SiteStore

    store = SiteStore()
    for bad in (0, 31, -1):
        with pytest.raises(ValueError):
            store.set_study_state("BADYRS", "closed", "r", "crc", RECENT, keep_years=bad)
    with pytest.raises(ValueError):  # only a close takes a period
        store.set_study_state("BADYRS", "paused", "r", "crc", RECENT, keep_years=3)
    assert store.study_state("BADYRS").by == ""  # nothing recorded


# ---------------------------------------------------------------------------------------------- the close form
def test_the_close_form_asks_for_the_period_and_the_page_says_until_when(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    from tests.console.test_close_only_an_empty_study import _empty, _events, _post, _state
    from tests.console.test_console_app import login

    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 0
    crc, _ = login(sb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/state").text
    assert f'name="keep_years" type="number" min="1" max="30" value="{STUDY_YEARS_AFTER_CLOSE}"' in page
    for bad in ("0", "31", "abc", "2.5"):
        r = _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out", keep_years=bad)
        assert r.status_code == 400 and _state(sb) == "open" and 'data-testid="state-error"' in r.text, bad
    r = _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out", keep_years="15", confirm="yes")
    assert r.status_code == 303 and _state(sb) == "closed"
    cur = sb["app"].state.helpers.store.study_state("GZQO")
    assert cur.keep_years == 15
    page = crc.get("/studies/GZQO/state").text
    line = page[page.index('data-testid="state-kept-until"') :][:300]
    assert "2041-11-05" in line and "15" in line  # closed 2026-11-05 (the site's day), kept 15 years
    ev = [e for e in _events(sb, "console.study_state") if e["detail"].get("state") == "closed"]
    assert ev[-1]["detail"]["keep_years"] == 15


def test_a_close_without_the_field_takes_the_default(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    from tests.console.test_close_only_an_empty_study import _empty, _post
    from tests.console.test_console_app import login

    _empty(sb)
    sb["app"].state.helpers.sae_open = lambda rid: 0
    crc, _ = login(sb["app"], "crc", PW)
    assert (
        _post(crc, "/studies/GZQO/state", state="closed", reason="last patient out", confirm="yes").status_code == 303
    )
    assert sb["app"].state.helpers.store.study_state("GZQO").keep_years == STUDY_YEARS_AFTER_CLOSE


def test_the_period_is_worded_in_every_language() -> None:
    from console.i18n import CATALOGUES

    for lang in ("en", "ja", "zh-TW"):
        for key in ("sstate.keep_years", "sstate.keep_years_help", "sstate.kept_until", "sstate.bad_keep_years"):
            assert CATALOGUES[lang].get(key), (lang, key)
