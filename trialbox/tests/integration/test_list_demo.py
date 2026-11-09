"""Step 2 end to end, in process (D-108): S20 approval of a registry (GOUT-COH) and a trial (GZQO) ruleset, the
patient list, three marks, a contact outcome, the cohort list and the N1 / N2 mail in the sink. Stub model, no
network."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from tools import list_demo


def test_approve_list_mark_and_mail(tmp_path: Path) -> None:
    res = list_demo.run(tmp_path, "pw-" + "x" * 16, "ja")
    box, h = res["box"], res["app"].state.helpers
    # S20: both drafts were approved by the investigator on one page; the trial's new exclusion was amber
    assert res["versions"] == {"GOUT-COH": "1.1.0", "GZQO": "1.1.0"}
    assert "GZQO-EXC-15" in res["approvals"]["GZQO"]["amber"]
    assert res["approvals"]["GOUT-COH"]["amber"] == ["GOUT-COH-INC-01"]
    assert all(v["feas_state"] == "done" for v in res["approvals"].values())
    html = res["approvals"]["GOUT-COH"]["html"]
    assert "v1.0.0 からの変更点" in html and "文言の変更" in html
    events = [r.event for r in h.bk.audit(None, 2000)]
    assert events.count("console.approve_all") == 2 and "console.code_tick" in events
    approvals = [r for r in h.bk.audit(None, 2000) if r.event == "console.approve_all"]
    assert {r.actor for r in approvals} == {"console:pi"}
    crc = res["crc"]
    assert not box.orch.db.find(state="awaiting_approval")  # nothing left waiting
    # the list: one mark vocabulary, nothing called "not eligible"
    lst = res["list_html"]
    assert "対象外" not in lst and "not eligible" not in lst
    assert "声をかける" in lst and "今回は見合わせる" in lst and "後日再確認" in lst
    # FR-UI-17: no model name or confidence on S5
    s5 = res["patient_html"]
    models = h.bk.models() or {}
    assert models.get("judge_model") is None or models["judge_model"] not in s5
    assert "confidence" not in s5
    # found by the public-data e2e: an exclusion the patient does not have was labelled "該当" (met), which reads
    # as "the patient has it"; exclusion rows now say whether the condition is present
    exc = re.findall(r'data-testid="verdict-GZQO-EXC-\d+">([^<]+)<', s5)
    assert exc and "該当" not in exc and set(exc) <= {"該当なし", "該当（除外）", "不明", "人の確認"}, exc
    inc = re.findall(r'data-testid="verdict-GZQO-INC-\d+">([^<]+)<', s5)
    assert "該当" in inc, inc
    # the approached patient has a screening number; the set-aside one left the list until its date
    assert res["screening_no"] == "GZQO-0001"
    marks = h.store.latest_marks("GZQO")
    assert [marks[p["pid"]].mark for p in res["picks"]] == ["approach", "need_info", "not_now"]
    rows = h.week_bundle(None, "GZQO")["rows"]
    assert res["picks"][2]["pid"] not in {r["pid"] for r in rows}
    log = crc.get("/studies/GZQO/screening-log")
    assert log.status_code == 200 and "GZQO-0001" in log.text
    # the cohort list: new members only, no mark buttons
    assert res["cohort_new"] > 0 and 'name="mark"' not in res["cohort_html"]
    # N1 to the investigator, N2 to the coordinator: pseudonym and screening number (D-136, D-143), no chart number
    with (tmp_path / "hospital" / "patient.csv").open(encoding="utf-8") as fh:
        mrns = {r["mrn"] for r in csv.DictReader(fh)}
    to = sorted(m.to[0] for m in res["mails"])
    assert to == ["crc1@hospa.test", "pi@hospa.test"]
    for m in res["mails"]:
        body = m.text()
        assert "/settings/notices" in body and "送信理由" in body
        assert not set(re.findall(r"\d{6,}", body)) & mrns  # no chart numbers
        assert not m.attachments()
    n1 = next(m for m in res["mails"] if m.to == ["pi@hospa.test"])
    assert res["picks"][0]["short"] in n1.text() and n1.subject.startswith("TrialBox：")
    n2 = next(m for m in res["mails"] if m.to == ["crc1@hospa.test"])
    assert "声をかける" in n2.text() and "後日再確認" in n2.text()
    # sent once per person and day
    from console import notify

    assert notify.send_all(h, res["day"]) == []
    # FR-REP-09: the research office counts
    office = crc.get(f"/reports/research-office?year={res['day'].year}")
    assert office.status_code == 200 and "GZQO" in office.text
    assert crc.get(f"/reports/research-office.xlsx?year={res['day'].year}").status_code == 200
