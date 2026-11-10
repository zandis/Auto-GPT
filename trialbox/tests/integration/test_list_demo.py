"""Step 2 end to end, in process (D-108): S20 approval of a registry (GOUT-COH) and a trial (GZQO) ruleset, the
patient list, three marks, a contact outcome, the cohort list and the N1 / N2 mail in the sink. Stub model, no
network."""

from __future__ import annotations

import csv
import re
from datetime import timedelta
from pathlib import Path

import pytest

from tools import feas_demo as fd
from tools import list_demo


def test_a_later_clinic_day_moves_the_box_with_the_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding EDC-16 (complete run, 500 patients): when the PI's first clinic day is after the box's day, the demo
    moved the console's clock but not the box's. The console then dated the sponsor's acknowledgement "today" and the
    EDC service, days behind, refused it as a future date (edc.ack_date): e2e stage 16 could not switch prefill on."""
    from console import notify
    from console.timefmt import local_today, site_zone

    later = fd.REF + timedelta(days=3)  # the box's day is REF + 1 (Monday); the PI's clinic is on Wednesday
    monkeypatch.setattr(notify, "clinic_days", lambda rows, practitioner: {later})
    password = "pw-" + "x" * 16
    res = list_demo.run(tmp_path, password, "ja")
    box, h, pi = res["box"], res["app"].state.helpers, res["pi"]
    assert res["day"] == later
    assert local_today(h.clock(), site_zone(h.bk)) == box.orch.today() == later  # one site, one date
    # as e2e stage 16: the PI names themselves on the log and switches prefill on, acknowledged on the console's date
    today = h.clock().date().isoformat()
    log = pi.post("/studies/GZQO/team", data={"csrf": fd._csrf(pi.get("/home").text), "username": "pi", "role": "pi",
                                             "start": today}, follow_redirects=False)  # fmt: skip
    assert log.status_code == 303
    sw = {"csrf": fd._csrf(pi.get("/studies/GZQO/edc").text), "on": "1", "kind": "sponsor_letter",
          "reference": "SPN-GZQO-001", "ack_date": today, "reentry_pages": "30", "reentry_accuracy": "98.6"}  # fmt: skip
    r = pi.post("/studies/GZQO/edc/switch", data=sw, follow_redirects=False)
    assert r.status_code == 303, sorted(set(re.findall(r"edc\.[a-z_]+", r.text)))
    # E-10 still holds: a CRC, not on the log as PI, cannot
    crc = res["crc"]
    r = crc.post("/studies/GZQO/edc/switch", data={**sw, "csrf": fd._csrf(crc.get("/studies/GZQO/edc").text)})
    assert r.status_code == 403


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


def test_alzheimers_trial_in_japanese(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-503 scenario J1: ``list_demo --lang ja --trial AD-MAB`` on the Japanese memory clinic exits 0. The site's
    zone is Asia/Tokyo, no page carries Chinese text, and with no amyloid result nobody reads "criteria not matched"."""
    from console.timefmt import site_zone

    got: dict[str, object] = {}
    real = list_demo.run
    monkeypatch.setattr(list_demo, "run", lambda *a, **k: got.setdefault("res", real(*a, **k)))
    assert list_demo.main(["--dir", str(tmp_path), "--lang", "ja", "--trial", "AD-MAB"]) == 0
    res = got["res"]
    assert isinstance(res, dict)
    h = res["app"].state.helpers
    assert str(site_zone(h.bk)) == "Asia/Tokyo"
    assert res["versions"] == {"NEUR-COH": "1.1.0", "AD-MAB": "1.1.0"} and res["screening_no"] == "AD-MAB-0001"
    zh_only = re.compile("[醫斷說發藥檢續應體關歲與為兩對區號]")
    for page in (res["list_html"], res["patient_html"], res["cohort_html"], res["approvals"]["AD-MAB"]["html"]):
        m = zh_only.search(re.sub(r'<option value="zh-TW"[^<]*</option>', "", page))  # the language menu names 繁體中文
        assert not m, m
    s5 = res["patient_html"]
    amyloid = re.findall(r'data-testid="verdict-AD-MAB-INC-05">([^<]+)<', s5)
    assert amyloid and amyloid[0] in ("不明", "人の確認"), amyloid
    assert "対象外" not in res["list_html"]
    assert {m.to[0] for m in res["mails"]} == {"crc1@hospa.test", "pi@hospa.test"}
