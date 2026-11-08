"""Build step 2 (D-108), unit level: the site store's marks, screening numbers and outcomes, the S20 diff and amber
rules, and the N1 / N2 builders. The end-to-end run is tests/integration/test_list_demo.py."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from console import notify
from console import studies as st
from console.auth import User
from console.i18n import CATALOGUES
from console.sitestore import MARKS, Mark, NotifyPerson, Outcome, SiteStore, StudySettings

PID = "a" * 16
AT = "2026-11-02T07:00:00+00:00"


def store(tmp_path: Path) -> SiteStore:
    return SiteStore()  # schema site of the test's own TB_DB_URL (conftest)


def test_console_stores_live_in_the_trial_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-126: schemas ``site`` and ``auth`` of TB_DB_URL; no URL is a clear error, never a local file."""
    from console.auth import UserStore
    from tb_common.db import DatabaseError

    s, u = SiteStore(), UserStore()
    assert s.db.schema.endswith("site") and u.db.schema.endswith("auth")
    s.close()
    u.close()
    monkeypatch.delenv("TB_DB_URL")
    for make in (SiteStore, UserStore):
        with pytest.raises(DatabaseError, match="TB_DB_URL is not set"):
            make()


def test_one_mark_vocabulary_replace_and_withdraw(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert MARKS == ("approach", "need_info", "not_suitable", "not_now")
    s.mark("GZQO", Mark(PID, "need_info", None, "HbA1c", "pi", AT, "J1"))
    s.mark("GZQO", Mark(PID, "approach", None, None, "pi", "2026-11-02T08:00:00+00:00", "J1"))  # replaces
    assert s.latest_marks("GZQO")[PID].mark == "approach"
    s.mark("GZQO", Mark(PID, "withdrawn", None, None, "pi", "2026-11-02T09:00:00+00:00", "J1"))
    assert PID not in s.latest_marks("GZQO")
    assert [m.mark for m in s.mark_history("GZQO", PID)] == ["need_info", "approach", "withdrawn"]
    with pytest.raises(ValueError):
        s.mark("GZQO", Mark(PID, "not_eligible", None, None, "pi", AT, "J1"))


def test_labels_never_say_not_eligible() -> None:
    # FR-SCR-07f: a PI's mark is never "not eligible", "excluded" or "ineligible"
    for lang, cat in CATALOGUES.items():
        for m in (*MARKS, "withdrawn"):
            label = cat[f"mark.{m}"].lower()
            assert not any(w in label for w in ("eligible", "excluded", "対象外", "不符合", "不適")), (lang, m, label)
    assert CATALOGUES["ja"]["mark.approach"] == "声をかける" and CATALOGUES["zh-TW"]["mark.not_now"] == "稍後再評估"


def test_not_now_hides_until_the_recheck_date() -> None:
    mk = Mark(PID, "not_now", "2026-11-30", None, "pi", AT, "J1")
    cl = {"rows": [{"pid": PID, "tier": "high", "criteria": []}]}
    before = st.weekly_rows(cl, {}, {}, {PID: mk}, {}, "J1", today=date(2026, 11, 29))
    after = st.weekly_rows(cl, {}, {}, {PID: mk}, {}, "J1", today=date(2026, 11, 30))
    assert before == [] and [r["pid"] for r in after] == [PID]
    assert st.in_worklist(after[0], "review", date(2026, 11, 30))


def test_screening_numbers_are_sequential_and_never_move(tmp_path: Path) -> None:
    s = store(tmp_path)
    conf = StudySettings(first_no=41)
    assert s.assign_screening_no("GZQO", PID, conf, AT) == "GZQO-0041"
    assert s.assign_screening_no("GZQO", "b" * 16, conf, AT) == "GZQO-0042"
    assert s.assign_screening_no("GZQO", PID, conf, AT) == "GZQO-0041"
    assert s.assign_screening_no("RA-BIO", PID, StudySettings(screening_prefix="RB"), AT) == "RB0001"
    assert [n for _p, n, _a in s.screening_rows("GZQO")] == ["GZQO-0041", "GZQO-0042"]


def test_outcomes_and_study_defaults(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.add_outcome("GZQO", Outcome(PID, "not_reached", "2026-11-04", None, "crc", AT))
    assert s.outcomes("GZQO", PID)[0].retry == "2026-11-04"
    with pytest.raises(ValueError):
        s.add_outcome("GZQO", Outcome(PID, "phoned", None, None, "crc", AT))
    assert st.study_defaults("RA-BIO", "nhi").study_type == "registry"
    assert st.study_defaults("RA-BIO", "nhi").reasons[:2] == ("activity", "biologic")
    assert st.study_defaults("GZQO", "trial").reasons == ("comorbidity", "unlikely", "other")
    s.save_study_settings("GZQO", StudySettings(reasons=("comorbidity", "other")), "crc", AT)
    assert s.study_settings("GZQO").reasons == ("comorbidity", "other")


def test_changes_since_and_amber_rows() -> None:
    approved: list[dict[str, Any]] = [
        {"id": "A-1", "text": "Age 18+", "class": "structured"},
        {"id": "A-2", "text": "Gout", "class": "note"},
        {"id": "A-3", "text": "Old", "class": "structured"},
    ]
    draft: list[dict[str, Any]] = [
        {"id": "A-1", "text": "Age 20+", "class": "structured", "equivalence_pct": 100},
        {"id": "A-2", "text": "Gout", "class": "structured", "equivalence_pct": 97},
        {"id": "A-4", "text": "New", "class": "human"},
    ]
    d = st.diff_since(draft, approved)
    assert d == {"added": ["A-4"], "text": ["A-1"], "class": ["A-2"], "removed": ["A-3"]}
    changed = set(d["added"]) | set(d["text"]) | set(d["class"])
    assert st.amber(draft[0], changed) == ["changed"]
    assert st.amber(draft[1], changed) == ["equivalence", "changed"]
    assert st.amber(draft[2], changed) == ["person", "changed"]
    assert st.amber({"id": "A-9", "class": "structured", "equivalence_pct": 100}, changed) == []


def _row(pid: str, when: str | None, prac: str = "P1", status: str = "new", mark: Any = None) -> dict[str, Any]:
    return {
        "pid": pid,
        "short": pid[:8],
        "visit": datetime.fromisoformat(when) if when else None,
        "practitioner_id": prac,
        "status": status,
        "mark": mark,
        "fit": st.Fit(inc_met=3, inc_total=4, exc_clear=2, exc_total=2, open=["x"]),
        "first_at": AT,
    }


PI = User("pi", "investigator", "pi@hospa.test")
CRC = User("crc", "coordinator", "crc1@hospa.test")


def test_n1_on_clinic_days_with_the_week_folded_below() -> None:
    rows = [
        _row("1" * 16, "2026-11-03T09:00:00+09:00"),
        _row("2" * 16, "2026-11-05T10:00:00+09:00"),
        _row("3" * 16, "2026-11-03T11:00:00+09:00", prac="P2"),
    ]
    person = NotifyPerson("pi", "P1", lang="en")
    assert notify.build_n1(PI, person, date(2026, 11, 4), [("GZQO", rows)]) is None  # no clinic that day
    n = notify.build_n1(PI, person, date(2026, 11, 3), [("GZQO", rows)])
    assert n is not None and n.to == "pi@hospa.test" and n.counts == {"today": 1, "week": 1}
    assert n.body.index("Today 2026-11-03") < n.body.index("Rest of the week") < n.body.index("22222222")
    assert "33333333" not in n.body  # another doctor's patient
    assert "Why you got this" in n.body and "/settings/notices" in n.body
    assert "5/6 criteria met" in n.body


def test_n1_monday_fallback_without_a_practitioner_id() -> None:
    rows = [_row("1" * 16, "2026-11-03T09:00:00+09:00"), _row("2" * 16, "2026-11-12T10:00:00+09:00")]
    person = NotifyPerson("pi", None, lang="ja")
    assert notify.build_n1(PI, person, date(2026, 11, 3), [("GZQO", rows)]) is None  # not Monday
    n = notify.build_n1(PI, person, date(2026, 11, 2), [("GZQO", rows)])
    assert n is not None and n.counts == {"today": 0, "week": 1} and "月曜日" in n.body


def test_n2_digest_on_working_days() -> None:
    mk = Mark("1" * 16, "approach", None, None, "pi", "2026-11-02T08:00:00+00:00", "J1")
    rows = [_row("1" * 16, "2026-11-02T09:00:00+09:00", mark=mk), _row("2" * 16, None)]
    extra = {"marks": [mk], "retry": {}, "registry": {}}
    person = NotifyPerson("crc", None, lang="en")
    assert notify.build_n2(CRC, person, date(2026, 11, 7), [("GZQO", rows, extra)], None) is None  # Saturday
    n = notify.build_n2(CRC, person, date(2026, 11, 2), [("GZQO", rows, extra)], None)
    assert n is not None and n.counts == {"visits": 1, "steps": 1, "new": 2, "marks": 1}
    assert "contact patient 11111111" in n.body and "Approach" in n.body
    later = notify.build_n2(CRC, person, date(2026, 11, 3), [("GZQO", rows, extra)], "2026-11-02T23:00:00+00:00")
    assert later is not None and later.counts["marks"] == 0 and later.counts["new"] == 0
    retry = {"marks": [], "retry": {"1" * 16: "2026-11-04"}, "registry": {}}
    quiet = notify.build_n2(CRC, person, date(2026, 11, 3), [("GZQO", [rows[0]], retry)], "2026-11-02T23:00:00+00:00")
    assert quiet is None  # the retry is not due yet and nothing else happened


def test_notice_log_once_per_day(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert not s.notice_sent("N1", "pi", "2026-11-02")
    s.log_notice("N1", "pi", "2026-11-02", datetime(2026, 11, 2, tzinfo=UTC).isoformat(), "x")
    assert s.notice_sent("N1", "pi", "2026-11-02") and s.last_notice("N1", "pi")
    s.save_notify_person(NotifyPerson("pi", "P12345", "07:30", True, "ja"))
    assert s.notify_person("pi").practitioner_id == "P12345" and s.notify_person("pi").lang == "ja"


def test_exclusion_results_say_present_or_not() -> None:
    """A passed exclusion means the condition is absent: it must not reuse the inclusion's "met" / 該当 / 符合."""
    for lang, cat in CATALOGUES.items():
        assert cat["verdict.exclusion.pass"] not in (cat["verdict.pass"], cat["verdict.fail"]), lang
        assert cat["verdict.exclusion.fail"] != cat["verdict.pass"], lang
