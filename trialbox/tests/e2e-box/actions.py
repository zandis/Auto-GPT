"""The browser journeys of the e2e-box gate, as action lists for pw/journey.js, and what is made of their output.

    actions.py journey NAME TODAY [MRN DOCTOR]   print the actions of journey NAME (dates relative to the box's TODAY)
    actions.py rows ACTIONS.json OUT.jsonl        one tab-separated step row per action (journey, step, result, s, detail)
    actions.py walk-gen MATRIX USERS PARAMS       every GET route of the design table as every role
    actions.py walk-cmp MATRIX USERS OUT.jsonl CSV  the walk against the design table; prints the tally
    actions.py lang-gen WALK.csv PARAMS           every page some role opened, in en, ja and zh-TW, desktop and phone
    actions.py lang-sum OUT.jsonl CSV             raw text keys, English on ja/zh pages, overflow; prints the tally

Synthetic criteria and notes only. An action is {j, id, as, method, path, ...}: GET/POST use the role's signed-in
page session, API_* its bearer token, WAIT polls a page until a text appears, SCAN checks a page's language and
layout; ${name} is a value an earlier action saved (pw/journey.js).
"""

import csv
import datetime as dt
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

RS = "GOUT-301"
CRIT = """Inclusion criteria
1. Age 20 to 75 years.
2. A diagnosis of gout (ICD-10 M10).
3. Serum uric acid at or above 7.0 mg/dL within the last 6 months.
Exclusion criteria
1. eGFR below 30 mL/min/1.73m2 within the last 6 months.
2. Pregnancy.
3. Febuxostat taken within the last 3 months."""
CRIT_IDS = [f"{RS}-INC-0{i}" for i in (1, 2, 3)] + [f"{RS}-EXC-0{i}" for i in (1, 2, 3)]
NOTE_EN = (
    "Synthetic outpatient note (test data only). 58-year-old man with recurrent podagra; gout diagnosed in 2024 "
    "(ICD-10 M10.0).\nSerum uric acid 8.4 mg/dL. eGFR 72 mL/min/1.73m2. No febuxostat. Allopurinol 100 mg daily."
)
NOTE_JA = "合成テスト用の外来記録（架空）。58歳男性、再発性の足趾関節炎。2024年に痛風と診断（ICD-10 M10.0）。尿酸 8.4 mg/dL、eGFR 72。フェブキソスタットの服用なし。"
DONE = 'data-state="(done|held|awaiting[a-z_]*)"'
FAILED = 'data-state="(failed|refused|cancelled)"'
Action = dict[str, Any]


class Journey:
    def __init__(self) -> None:
        self.actions: list[Action] = []

    def act(self, j: str, i: str, who: str, method: str, path: str, **kw: Any) -> None:
        self.actions.append({"j": j, "id": i, "as": who, "method": method, "path": path, **kw})


def screen(a: Journey, today: dt.date, mrn: str, doctor: str) -> None:
    """A new study from pasted criteria (FEAS), the delegation log, the PI's approval, the study opened, SCREEN of the
    whole hospital and its lists, screen-now, the IRB record, CASE in English and Japanese, a second FEAS."""
    d = today.isoformat
    start, end, trained = (
        (today - dt.timedelta(days=7)).isoformat(),
        (today + dt.timedelta(days=400)).isoformat(),
        (today - dt.timedelta(days=30)).isoformat(),
    )
    s = "SCREEN-feas"
    a.act(s, "protocol page opens", "crc1", "GET", "/pilot/protocol")
    a.act(s, "paste criteria, new study (FEAS starts)", "crc1", "POST", "/pilot/protocol", form={"ruleset": RS, "criteria": CRIT},
          csrfFrom="/pilot/protocol", save={"feas": r"/pilot/jobs/([A-Za-z0-9_-]+)"}, expect=[303])  # fmt: skip
    a.act(s, "FEAS job ends", "crc1", "WAIT", "/pilot/jobs/${feas}", until='data-state="(done|held|awaiting[a-z_]*|approval[a-z_]*)"',
          fail=FAILED, every=10, max=90, keepBody=500)  # fmt: skip
    t = "PEOPLE-delegation"
    a.act(t, "steward: team page", "stw1", "GET", f"/studies/{RS}/team")
    for who, user, role, ref, extra in (
        ("stw1", "lpi1", "pi", "GCP-SYN-001", {}),
        ("lpi1", "subi1", "sub_pi", "GCP-SYN-002", {"tasks": "screen"}),
        ("lpi1", "crc1", "crc", "GCP-SYN-003", {}),
    ):
        a.act(t, f"{who} adds {user} as {role}", who, "POST", f"/studies/{RS}/team", csrfFrom=f"/studies/{RS}/team",
              form={"username": user, "role": role, "start": start, "end": end, "training_day": trained, "training_ref": ref,
                    **extra}, expect=[200, 303], keepBody=300)  # fmt: skip
    a.act(t, "PI gives the monitor a grant (cra1)", "lpi1", "POST", f"/studies/{RS}/team", csrfFrom=f"/studies/{RS}/team",
          form={"username": "cra1", "role": "monitor", "start": start, "end": (today + dt.timedelta(days=30)).isoformat(),
                "training_ref": "MV-SYN-1"}, expect=[200, 303], keepBody=300)  # fmt: skip
    a.act(t, "delegation log as JSON (API)", "lpi1", "API_GET", f"/api/v1/studies/{RS}/delegation", keepBody=600)
    a.act(
        t,
        "a PI not on the log is refused the study's patients",
        "pi1",
        "GET",
        f"/studies/{RS}/patients",
        expect=[403, 404],
    )
    p = "SCREEN-approve"
    a.act(p, "PI opens the criteria approval", "lpi1", "GET", "/pilot/jobs/${feas}/approval", keepBody=400)
    irb = {"confirm": "yes", "effective_from": d(), "irb_reference": "IRB-SYN-001",
           "irb_approved_on": (today - dt.timedelta(days=7)).isoformat()}  # fmt: skip
    a.act(p, "coordinator may not approve criteria (403)", "crc1", "POST", "/pilot/jobs/${feas}/approve", form=irb,
          csrfFrom="/home", expect=[403])  # fmt: skip
    for c in CRIT_IDS:
        a.act(p, f"PI opens amber row {c}", "lpi1", "GET", "/pilot/jobs/${feas}/approval?open=" + c)
        a.act(p, f"PI ticks {c}", "lpi1", "POST", "/pilot/jobs/${feas}/approval/tick", form={"crit": c},
              csrfFrom="/pilot/jobs/${feas}/approval", expect=[200, 303])  # fmt: skip
    a.act(p, "PI approves the criteria after the ticks", "lpi1", "POST", "/pilot/jobs/${feas}/approve", form=irb,
          csrfFrom="/pilot/jobs/${feas}/approval", expect=[200, 303], keepBody=400)  # fmt: skip
    a.act(p, "FEAS job after approval", "crc1", "WAIT", "/pilot/jobs/${feas}", until='data-state="done"', fail=FAILED, every=10,
          max=30, keepBody=300)  # fmt: skip
    a.act(p, "feasibility report (crc)", "crc1", "GET", f"/studies/{RS}/feasibility", keepBody=600)
    a.act(p, "feasibility report (viewer, aggregate)", "view1", "GET", f"/studies/{RS}/feasibility", keepBody=300)
    a.act(p, "sponsor pack of the FEAS job (zip)", "crc1", "GET", "/pilot/jobs/${feas}/sponsor-pack.zip")
    o = "SCREEN-open"
    a.act(o, "SAE reporting type (coordinator)", "crc1", "POST", f"/studies/{RS}/setup/sae", form={"rule_set": "tw_trial"},
          csrfFrom=f"/studies/{RS}/setup", expect=[303])  # fmt: skip
    a.act(o, "coordinator opens the study", "crc1", "POST", f"/studies/{RS}/state", form={"state": "open", "reason": "e2e",
          "confirm": "yes"}, csrfFrom=f"/studies/{RS}/state", expect=[200, 303], keepBody=300)  # fmt: skip
    a.act(o, "who to screen: the whole hospital", "crc1", "POST", f"/studies/{RS}/setup/scope",
          form={"mode": "hospital", "practitioners": ""}, csrfFrom=f"/studies/{RS}/setup", expect=[303])  # fmt: skip
    r = "SCREEN-screen"
    a.act(r, "SCREEN requested (coordinator)", "crc1", "POST", "/pilot/request", form={"kind": "SCREEN", "ruleset": RS},
          csrfFrom="/pilot/request", save={"screen": r"/pilot/jobs/([A-Za-z0-9_-]+)"}, expect=[303])  # fmt: skip
    a.act(
        r,
        "SCREEN job ends",
        "crc1",
        "WAIT",
        "/pilot/jobs/${screen}",
        until=DONE,
        fail=FAILED,
        every=15,
        max=200,
        keepBody=700,
    )
    pid = {"pid": rf"/studies/{RS}/(?:candidates|patients)/([a-f0-9]{{16,64}})"}
    a.act(r, "candidate list with tiers", "crc1", "GET", f"/studies/{RS}/candidates", keepBody=900, save=pid)
    a.act(r, "candidates as JSON (API)", "crc1", "API_GET", f"/api/v1/studies/{RS}/candidates", keepBody=900)
    a.act(r, "evidence view (candidate page)", "crc1", "GET", f"/studies/{RS}/candidates/" + "${pid}", keepBody=1200)
    a.act(r, "patient page with reason codes and still-needed", "crc1", "GET", f"/studies/{RS}/patients/" + "${pid}",
          keepBody=1200)  # fmt: skip
    a.act(r, "PI marks 'approach' with the whole hospital listed (death check)", "lpi1", "POST",
          f"/studies/{RS}/patients/" + "${pid}/mark", form={"mark": "approach", "note": "e2e"},
          csrfFrom=f"/studies/{RS}/patients/" + "${pid}", expect=[200, 303], keepBody=300)  # fmt: skip
    for who, path in (("lpi1", "week"), ("lpi1", "not-matched"), ("crc1", "excluded"), ("crc1", "screening-log")):
        a.act(r, f"study {path} ({who})", who, "GET", f"/studies/{RS}/{path}", keepBody=400)
    a.act(r, "screening log xlsx", "crc1", "GET", f"/studies/{RS}/screening-log.xlsx")
    a.act(r, "information still needed (admin)", "admin", "GET", "/admin/still-needed", keepBody=400)
    a.act(
        r, "sub-investigator with the screening task sees the candidates", "subi1", "GET", f"/studies/{RS}/candidates"
    )
    a.act(
        r, "PI not on the log is refused the candidates", "pi1", "GET", f"/studies/{RS}/candidates", expect=[403, 404]
    )
    a.act(r, "screen-now confirmed for all departments", "crc1", "POST", f"/studies/{RS}/screen-now", form={"all_dept": "1"},
          csrfFrom=f"/studies/{RS}/screen-now", save={"now": r"/pilot/jobs/([A-Za-z0-9_-]+)"}, expect=[200, 303],
          keepBody=300)  # fmt: skip
    a.act(
        r,
        "screen-now job ends",
        "crc1",
        "WAIT",
        "/pilot/jobs/${now}",
        until=DONE,
        fail=FAILED,
        every=15,
        max=160,
        keepBody=500,
    )
    a.act(r, "jobs list (admin)", "admin", "GET", "/jobs", keepBody=600)
    n = "SCREEN-scope"
    a.act(n, f"who to screen: one doctor ({doctor})", "crc1", "POST", f"/studies/{RS}/setup/scope",
          form={"mode": "practitioners", "practitioners": doctor}, csrfFrom=f"/studies/{RS}/setup", expect=[303])  # fmt: skip
    a.act(n, "SCREEN for one doctor's patients", "crc1", "POST", "/pilot/request", form={"kind": "SCREEN", "ruleset": RS},
          csrfFrom="/pilot/request", save={"screen2": r"/pilot/jobs/([A-Za-z0-9_-]+)"}, expect=[303])  # fmt: skip
    a.act(
        n,
        "SCREEN ends",
        "crc1",
        "WAIT",
        "/pilot/jobs/${screen2}",
        until=DONE,
        fail=FAILED,
        every=15,
        max=160,
        keepBody=500,
    )
    a.act(n, "candidate list (one doctor)", "crc1", "GET", f"/studies/{RS}/candidates", keepBody=600, save=pid)
    a.act(n, "patient page: death check readable", "crc1", "GET", f"/studies/{RS}/patients/" + "${pid}", keepBody=700)
    i = "SCREEN-irb"
    a.act(i, "PI: IRB page", "lpi1", "GET", f"/studies/{RS}/irb", keepBody=500)
    a.act(i, "PI records that the IRB text covers identified pre-screening", "lpi1", "POST", f"/studies/{RS}/irb-text",
          csrfFrom=f"/studies/{RS}/state", form={"covers": "1", "approval_ref": "IRB-SYN-001", "text_version": "v1",
          "approved_on": (today - dt.timedelta(days=7)).isoformat()}, expect=[200, 303], keepBody=400)  # fmt: skip
    a.act(
        i, "evidence view after the IRB record", "crc1", "GET", f"/studies/{RS}/candidates/" + "${pid}", keepBody=1200
    )
    c = "SCREEN-case"
    for lang, note in (("en", NOTE_EN), ("ja", NOTE_JA)):
        a.act(c, f"CASE ({lang}): synthetic chart note", "lpi1", "POST", "/pilot/case", form={"ruleset": RS, "mrn": mrn, "lang": lang},
              files={"charts": {"name": f"chart-{lang}.txt", "text": note}}, csrfFrom="/pilot/case",
              save={f"case{lang}": r"/pilot/jobs/([A-Za-z0-9_-]+)"}, expect=[303])  # fmt: skip
        a.act(c, f"CASE ({lang}) job ends", "lpi1", "WAIT", "/pilot/jobs/${case" + lang + "}", until=DONE, fail=FAILED, every=10,
              max=60, keepBody=900)  # fmt: skip
    f = "SCREEN-feas2"
    a.act(f, "FEAS for the open study (lookback 24 months)", "crc1", "POST", "/pilot/request",
          form={"kind": "FEAS", "ruleset": RS, "lookback": "24"}, csrfFrom="/pilot/request",
          save={"feas2": r"/pilot/jobs/([A-Za-z0-9_-]+)"}, expect=[303])  # fmt: skip
    a.act(
        f, "FEAS ends", "crc1", "WAIT", "/pilot/jobs/${feas2}", until=DONE, fail=FAILED, every=10, max=90, keepBody=700
    )
    a.act(f, "feasibility report (counts)", "crc1", "GET", f"/studies/{RS}/feasibility", keepBody=900)


def people(a: Journey, today: dt.date, *_: str) -> None:
    """After screening (VARS pid): review marks and refusals, the subject's life cycle, the monitor, reports, opt-out
    and break-glass."""
    pp = f"/studies/{RS}/patients/" + "${pid}"
    r = "PEOPLE-review"
    a.act(r, "PI marks the candidate 'approach'", "lpi1", "POST", pp + "/mark", form={"mark": "approach", "note": "e2e synthetic"},
          csrfFrom=pp, keepBody=200)  # fmt: skip
    a.act(r, "sub-investigator opens the candidate (delegated)", "subi1", "GET", pp)
    a.act(r, "viewer cannot see the patient (403)", "view1", "GET", pp, expect=[403, 404])
    a.act(r, "CRO without patient rights cannot see the candidate (403)", "cra1", "GET", pp, expect=[403, 404])
    a.act(r, "steward cannot mark (403)", "stw1", "POST", pp + "/mark", form={"mark": "approach"}, csrfFrom="/breakglass",
          expect=[403, 404])  # fmt: skip
    a.act(r, "coordinator records the contact: reached, booked", "crc1", "POST", pp + "/outcome",
          form={"outcome": "reached_booked", "note": "e2e", "confirm": "yes"}, csrfFrom=pp, keepBody=200)  # fmt: skip
    lc = "PEOPLE-lifecycle"
    a.act(lc, "subjects list", "crc1", "GET", f"/studies/{RS}/subjects", keepBody=500,
          save={"rec": rf"/studies/{RS}/subjects/([^\"/?#]+)"})  # fmt: skip
    sp = f"/studies/{RS}/subjects/" + "${rec}"
    for to in ("consented", "enrolled", "on_study"):
        a.act(lc, f"step: {to} (today)", "crc1", "POST", sp + "/step", form={"to": to, "on_day": today.isoformat(), "note": "e2e"},
              csrfFrom=sp, expect=[200, 303], keepBody=200)  # fmt: skip
    a.act(lc, "subject page after the steps", "crc1", "GET", sp, keepBody=700)
    a.act(lc, "subjects as JSON (API)", "crc1", "API_GET", f"/api/v1/studies/{RS}/subjects", keepBody=500)
    for path in ("visits", "enrolment", "deviations"):
        a.act(lc, f"study {path}", "crc1", "GET", f"/studies/{RS}/{path}", keepBody=400)
    a.act(lc, "SAE register", "lpi1", "GET", "/sae", keepBody=300)
    a.act(lc, "enrolment as CSV", "crc1", "GET", f"/studies/{RS}/enrolment.csv")
    a.act(lc, "consent age rule (majority 20, assent 7-19)", "crc1", "POST", f"/studies/{RS}/setup/consent-ages",
          form={"majority": "20", "assent_from": "7", "assent_to": "19"}, csrfFrom=f"/studies/{RS}/setup", keepBody=200)  # fmt: skip
    a.act(lc, "ICF and reconsent list", "crc1", "API_GET", f"/api/v1/studies/{RS}/reconsent", keepBody=300)
    m = "PEOPLE-monitor"
    a.act(m, "monitor (cra1, grant) opens Monitoring", "cra1", "GET", f"/studies/{RS}/monitor", keepBody=500)
    a.act(
        m,
        "monitor's source-reference sheet of the subject",
        "cra1",
        "GET",
        f"/studies/{RS}/monitor/" + "${rec}",
        keepBody=500,
    )
    a.act(m, "monitor records the visit (subject verified)", "cra1", "POST", f"/studies/{RS}/monitor/visits",
          form={"visit_day": today.isoformat(), "subjects": "${rec}", "findings": "e2e synthetic: none"},
          csrfFrom=f"/studies/{RS}/monitor", expect=[200, 303], keepBody=300)  # fmt: skip
    a.act(m, "monitor cannot open a candidate (403)", "cra1", "GET", f"/studies/{RS}/candidates", expect=[403, 404])
    a.act(m, "PI reads the monitor records", "lpi1", "GET", f"/studies/{RS}/monitor", keepBody=200)
    rp = "PEOPLE-reports"
    a.act(rp, "viewer: reports (aggregate)", "view1", "GET", "/reports", keepBody=300)
    a.act(rp, "CRO: reports (sponsor copy)", "cra1", "GET", "/reports", keepBody=300)
    a.act(rp, "study export xlsx (API)", "crc1", "API_GET", f"/api/v1/studies/{RS}/export/xlsx")
    a.act(rp, "research office counts", "crc1", "GET", "/reports/research-office", keepBody=300)
    a.act(rp, "research office counts xlsx", "crc1", "GET", "/reports/research-office.xlsx")
    a.act(rp, "audit: privacy office reads the patient's events", "dpo1", "GET", "/audit/patients/${pid}", keepBody=300)
    a.act(rp, "audit: chain verification", "dpo1", "POST", "/audit/verify", form={}, csrfFrom="/audit", keepBody=300)
    oo = "PEOPLE-optout"
    a.act(oo, "privacy office: opt-out register", "dpo1", "GET", "/site/opt-outs", keepBody=200)
    a.act(oo, "privacy office records an opt-out (synthetic chart)", "dpo1", "POST", "/site/opt-outs",
          form={"chart_no": "${optmrn}", "source": "written", "note": "e2e synthetic opt-out"}, csrfFrom="/site/opt-outs",
          keepBody=200)  # fmt: skip
    a.act(oo, "opt-outs as JSON (steward)", "stw1", "API_GET", "/api/v1/site/opt-outs", keepBody=300)
    b = "PEOPLE-breakglass"
    a.act(b, "admin opens a break-glass grant for one patient", "admin", "POST", "/breakglass",
          form={"reason": "support", "note": "e2e synthetic support check", "kind": "patient", "ruleset": RS, "pid": "${pid}"},
          csrfFrom="/breakglass", keepBody=300)  # fmt: skip
    a.act(b, "steward's review list shows the use", "stw1", "GET", "/breakglass", keepBody=300)


def edc(a: Journey, *_: Any) -> None:
    """The REDCap bench as the study's EDC (VARS secret_rc = its token, url = its address): the connection and its
    test, the study's link and its test, the EDC page, pre-fill drafts for the enrolled subject, the read-back."""
    e = "EDC-redcap"
    a.act(e, "admin: REDCap connection page", "admin", "GET", "/admin/redcap", keepBody=300)
    a.act(e, "admin saves the REDCap connection (bench)", "admin", "POST", "/admin/redcap",
          form={"token_ref": "main", "url": "${rcurl}", "token": "${secret_rc}"}, csrfFrom="/admin/redcap", expect=[303],
          keepBody=1500)  # fmt: skip
    a.act(e, "admin tests the connection", "admin", "POST", "/admin/redcap/main/test", form={}, csrfFrom="/admin/redcap",
          expect=[200, 303], keepBody=500)  # fmt: skip
    a.act(e, "connection page after the test", "admin", "GET", "/admin/redcap", keepBody=700)
    st = f"/studies/{RS}/setup"
    a.act(e, "coordinator links the study to project 1", "crc1", "POST", st + "/redcap", form={"project_id": "1", "token_ref": "main"},
          csrfFrom=st, expect=[303], keepBody=1500)  # fmt: skip
    a.act(e, "coordinator tests the study link", "crc1", "POST", st + "/redcap/test", form={}, csrfFrom=st, expect=[200, 303],
          keepBody=500)  # fmt: skip
    a.act(e, "study EDC page", "crc1", "GET", f"/studies/{RS}/edc", keepBody=700)
    a.act(e, "pre-fill drafts for the subject (screening visit)", "crc1", "POST", f"/studies/{RS}/edc/drafts",
          form={"record": "${rec}", "visit": "screening_arm_1", "visit_date": "${today}"}, csrfFrom=f"/studies/{RS}/edc",
          expect=[200, 303], keepBody=500)  # fmt: skip
    a.act(e, "draft review of the record", "crc1", "GET", f"/studies/{RS}/edc/review/" + "${rec}", keepBody=700)
    a.act(e, "read-back from REDCap", "crc1", "POST", f"/studies/{RS}/redcap-read", form={"back": "setup"}, csrfFrom=st,
          expect=[200, 303], keepBody=400)  # fmt: skip
    a.act(e, "data sources page after the read-back", "crc1", "GET", f"/studies/{RS}/sources", keepBody=600)
    a.act(e, "monitor's source-reference sheet with the EDC linked", "cra1", "GET", f"/studies/{RS}/monitor/" + "${rec}",
          keepBody=500)  # fmt: skip


def perf(a: Journey, *_: Any) -> None:
    """API and heavy-page latency with a warm session, three times each (the first call per role opens the token)."""
    for who, paths in (("crc1", ["/api/v1/studies", f"/api/v1/studies/{RS}/candidates", f"/api/v1/studies/{RS}/subjects",
                                 f"/api/v1/studies/{RS}/screening-log", f"/api/v1/studies/{RS}/enrolment"]),
                       ("admin", ["/api/v1/studies", "/api/v1/admin/ops", "/api/v1/data/batches"])):  # fmt: skip
        for p in paths:
            for k in range(1 if p == "/api/v1/studies" else 3):
                a.act("PERF-api", f"{who} {p} #{k + 1}", who, "API_GET", p)
    for p in (f"/studies/{RS}/week", f"/studies/{RS}/candidates", "/home", "/admin/ops"):
        who = "admin" if p == "/admin/ops" else "crc1"
        for k in range(3):
            a.act("PERF-page", f"{who} {p} #{k + 1}", who, "GET", p)


def model_down(a: Journey, *_: Any) -> None:
    """While the judge and the verifier are stopped: the health page, and a SCREEN whose coded list must still show."""
    j = "OPS-model-down"
    a.act(j, "admin health page names the stopped models", "admin", "GET", "/admin/ops", keepBody=3000)
    a.act(j, "SCREEN with the models down", "crc1", "POST", "/pilot/request", form={"kind": "SCREEN", "ruleset": RS},
          csrfFrom="/pilot/request", save={"md": r"/pilot/jobs/([A-Za-z0-9_-]+)"}, expect=[303])  # fmt: skip
    a.act(j, "SCREEN ends (coded criteria) while the models are down", "crc1", "WAIT", "/pilot/jobs/${md}",
          until='data-state="(done|held)"', fail='data-state="failed"', every=15, max=80, keepBody=500)  # fmt: skip
    a.act(j, "coded list still shows (candidates)", "crc1", "GET", f"/studies/{RS}/candidates", keepBody=500)
    a.act(j, "coded list still shows (study week list)", "lpi1", "GET", f"/studies/{RS}/week", keepBody=500)


def disk_full(a: Journey, *_: Any) -> None:
    j = "OPS-disk-full"
    a.act(j, "console answers on a full disk (crc1 home)", "crc1", "GET", "/home")
    a.act(j, "a write on a full disk (feedback) answers cleanly", "crc1", "POST", "/feedback",
          form={"path": "/home", "rating": "3", "comment": "disk full test"}, csrfFrom="/home",
          expect=[200, 303, 400, 503, 507])  # fmt: skip
    a.act(j, "admin health page on a full disk", "admin", "GET", "/admin/ops", keepBody=400)


JOURNEYS: dict[str, Callable[..., None]] = {
    "screen": screen, "people": people, "edc": edc, "perf": perf, "model-down": model_down, "disk-full": disk_full,
}  # fmt: skip


def journey(name: str, today: str, mrn: str = "", doctor: str = "") -> None:
    a = Journey()
    JOURNEYS[name](a, dt.date.fromisoformat(today), mrn, doctor)
    print(json.dumps({"actions": a.actions}, ensure_ascii=False))


def passed(a: Action, o: dict[str, Any]) -> bool:
    if o.get("error"):
        return False
    if a.get("method") == "WAIT":
        return bool(o.get("matched")) and not o.get("failed")
    st = o.get("status", 0)
    return bool(st in a["expect"]) if "expect" in a else 0 < st < 400


def rows(actions: str, out: str) -> None:
    with open(actions, encoding="utf-8") as fh:
        acts = {a["id"]: a for a in json.load(fh)["actions"]}
    for line in Path(out).read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        o = json.loads(line)
        a = acts.get(o["id"], {})
        det = f"{a.get('as')} {o.get('method')} {o.get('path')} -> {o.get('status', 0)} {o.get('location', '')} "
        det += o.get("err") or o.get("error") or o.get("body") or ""
        det += "".join(f" [{k[6:]}={o[k]}]" for k in o if k.startswith("saved_"))
        print("\t".join([a.get("j", "J"), o["id"], "PASS" if passed(a, o) else "FAIL", f"{(o.get('ms') or 0) / 1000:.2f}",
                         det.replace("\t", " ").replace("\n", " ")[:400]]))  # fmt: skip


def kv(s: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in s.split(",") if p)


def fill(route: str, params: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: params.get(m.group(1), "1"), route)


def matrix(path: str) -> list[tuple[str, str, dict[str, str]]]:
    """The rows of the design table (tests/console/data/role_route_matrix.md): method, route, cell per role."""
    cols: list[str] = []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("| Method |"):
            cols = [c.strip() for c in line.strip().strip("|").split("|")][2:]
        elif cols and re.match(r"^\| (GET|POST|PUT|DELETE) \|", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append((cells[0], cells[1].strip("`"), dict(zip(cols, cells[2:], strict=False))))
    return out


def walk_gen(path: str, users: str, params: str) -> None:
    u, p = kv(users), kv(params)
    acts = [{"j": "ROLE-walk", "id": f"{col}|{route}", "as": user, "method": "API_GET" if route.startswith("/api/v1/") else "GET",
             "path": fill(route, p)} for method, route, _ in matrix(path) if method == "GET" for col, user in u.items()]  # fmt: skip
    acts.sort(key=lambda a: a["as"])  # one role's routes together: one sign-in each
    print(json.dumps({"actions": acts}))


def klass(exp: str, got: str) -> str:
    """OK; ERROR (5xx other than 503); LEAK (the table says 403/404, the box let the role in); DENY (the table lets the
    role in, the box says 403); SIGNIN (sent to sign-in); DATA (a difference that follows from what the box holds)."""
    if exp == got:
        return "OK"
    if got == "E":
        return "ERROR"
    if exp in ("-", "n") and got == "Y":
        return "LEAK"
    if exp in ("Y", "U") and got == "-":
        return "DENY"
    return "SIGNIN" if got == "L" else "DATA"


def walk_cmp(path: str, users: str, out: str, csvfile: str) -> None:
    u = kv(users)
    table = {route: cells for method, route, cells in matrix(path) if method == "GET"}
    tally: dict[str, int] = {}
    with open(csvfile, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["role", "user", "route", "expected", "got", "status", "class", "ms", "location", "error"])
        for line in Path(out).read_text(encoding="utf-8").splitlines():
            if not line.startswith("{"):
                continue
            o = json.loads(line)
            col, route = o["id"].split("|", 1)
            exp, got = table.get(route, {}).get(col, "?"), o.get("cell", "X" if o.get("error") else "?")
            k = klass(exp, got)
            tally[k] = tally.get(k, 0) + 1
            w.writerow([col, u.get(col, ""), route, exp, got, o.get("status", ""), k, o.get("ms", ""), o.get("location", "")[:80],
                        (o.get("err") or o.get("error") or "")[:160]])  # fmt: skip
    print(json.dumps(tally))


SKIP = re.compile(r"^/(api/|about/NOTICE|.*\.(csv|xlsx|pdf|json|txt|ics|zip)$|.*/export|.*/report\.csv|.*/download)")


def lang_gen(walk: str, params: str) -> None:
    p, chosen = kv(params), {}
    for r in csv.DictReader(Path(walk).read_text(encoding="utf-8").splitlines()):
        if r["status"] == "200" and not SKIP.match(r["route"]) and r["route"] not in chosen:
            chosen[r["route"]] = r["user"]
    acts = [{"j": "LANG-scan", "id": f"{route}|{lang}|{vp}", "as": user, "method": "SCAN", "path": fill(route, p), "lang": lang,
             "viewport": vp} for user in sorted(set(chosen.values())) for lang in ("en", "ja", "zh-TW")
            for route in sorted(k for k, v in chosen.items() if v == user) for vp in ("desktop", "phone")]  # fmt: skip
    print(json.dumps({"actions": acts}))


def lang_sum(out: str, csvfile: str) -> None:
    tot = {"pages": 0, "raw_key_pages": 0, "english_pages": 0, "overflow_pages": 0, "errors": 0}
    with open(csvfile, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["route", "lang", "viewport", "as", "status", "ms", "html_lang", "raw_keys", "english_on_page", "overflow_px",
                    "wide_elements", "examples"])  # fmt: skip
        for line in Path(out).read_text(encoding="utf-8").splitlines():
            if not line.startswith("{"):
                continue
            o = json.loads(line)
            route, lang, vp = o["id"].split("|")
            nk, ne, ov = o.get("nkeys", 0), o.get("nenglish", 0), o.get("overflowPx", 0) or 0
            tot["pages"] += 1
            tot["errors"] += bool(o.get("error") or o.get("status", 0) >= 400)
            tot["raw_key_pages"] += nk > 0
            tot["english_pages"] += ne > 0
            tot["overflow_pages"] += ov > 4
            ex = "; ".join((o.get("keys") or [])[:4] + [e[:60] for e in (o.get("english") or [])[:2]])
            w.writerow([route, lang, vp, o.get("as"), o.get("status"), o.get("ms"), o.get("htmlLang"), nk, ne, ov, o.get("wideEls"),
                        ex or o.get("error", "")])  # fmt: skip
    print(json.dumps(tot))


if __name__ == "__main__":
    cmds: dict[str, Callable[..., None]] = {
        "journey": journey, "rows": rows, "walk-gen": walk_gen, "walk-cmp": walk_cmp, "lang-gen": lang_gen, "lang-sum": lang_sum,
    }  # fmt: skip
    cmds[sys.argv[1]](*sys.argv[2:])
