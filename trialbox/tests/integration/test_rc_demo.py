"""Step 3 end to end, in process (D-109): after the step-2 run, S36 connects the REDCap simulator, S21 links project
A on ``tb_screening_no``, a record is created and then changed in the simulator, and Run now shows each status in the
screening log. Stub model, no network."""

from __future__ import annotations

from pathlib import Path

from tools import rc_demo


def test_link_change_run_now_and_see_it_in_the_log(tmp_path: Path) -> None:
    res = rc_demo.run(tmp_path, "pw-" + "x" * 16, "ja")
    assert res["s36_ok"]
    assert res["screening_no"] == "GZQO-0001"
    assert res["before"] == "連絡予定"  # D-1221: approved, not reached on the first call: to contact
    assert res["after_consent"].startswith("同意取得")
    assert res["after_enrol"].startswith("登録")
    assert res["subject_shown"] and res["unmatched_shown"]
    log = res["log_html"]
    assert "REDCap レコード" in log and "被験者番号" in log
    events = [r.event for r in res["app"].state.helpers.bk.audit(None, 3000)]
    assert events.count("redcap.read") == 2 and "redcap.link" in events and "redcap.test" in events
