"""``e2e_simple``: the one build gate (SRS FR-OPS-11, TB-PLAN-02 "How it is tested", TB-DS-04 §3.4.1, D-111).

One synthetic hospital (the ``ci`` profile: two sites of 2,500 patients, notes in JA, zh-TW and EN), stub model, no
network, no secrets, run in process:

    criteria pasted -> FEAS report (funnel) -> the investigator approves -> SCREEN -> the list (GZQO) and the cohort
    list (GOUT-COH) -> marks -> N1/N2 mail -> REDCap simulator record -> Run now -> screening log (HTML and XLSX)
    -> write-back of TrialBox's instrument -> consent in REDCap -> read back on the next run (D-123)
    -> the data core with REDCap off and on (stage 9) -> built-in forms, entry, history, ODM / REDCap CSV (stage 10)
    -> the trial lifecycle: enrolled, visit due, overdue, done, AEs, withdrawn; three counts agree (stage 11)
    -> a new site set up the hard way: protocol, charts, an IT dump, a messy list; the readiness page green (12)
    -> Japan: an SS-MIX2 hospital with ADT-52, OMP-11/12 and extended storage, JP Core $validate on the sample, the
       licensed-list loader, and the GOUT-COH funnel unchanged (13)
    -> ClinicalTrials.gov offline: the sample reference data pack loaded, a trial found by NCT id, condition and a
       Japan or Taiwan site, and its criteria drafted, with every outbound connection refused (14, D-140)

and each stage is checked against something it did not compute itself: the generator's own counts, a recount from
the hospital CSVs, the sent mail, the hash-chained audit log and a byte-identical re-run of the FEAS and SCREEN jobs.

    python -m tools.e2e_simple [--dir DIR] [--lang ja|zh-TW|en] [--json]      # exit 0 = every check passed
    make e2e-simple

``tests/integration/test_e2e_simple.py`` runs the same function under pytest; ``.github/workflows/trialbox-e2e.yml``
runs it on every pull request that touches ``trialbox/``.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import itertools
import json
import os
import re
import secrets
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import feas_demo as fd  # noqa: E402
from tools import list_demo as ld  # noqa: E402
from tools import rc_demo  # noqa: E402

TRIAL, COHORT = ld.TRIAL, ld.COHORT
GOUT = ("M10", "M1A")  # GZQO-INC-02 / GOUT-COH-INC-01 value set (ICD-10-CM)
BUDGET_S = 15 * 60  # TB-DS-04 §3.4.1: the whole run within 15 minutes
# (judge, verifier) served names when tools.complete_run puts the GPU pair in the box; None = the stub (the gate)
PAIR: tuple[str, str] | None = None


@dataclass
class Stage:
    name: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    seconds: float = 0.0

    def check(self, what: str, ok: Any, detail: Any = "") -> None:
        self.checks.append((what, bool(ok), str(detail)[:300]))

    @property
    def ok(self) -> bool:
        return all(c[1] for c in self.checks)


def _age(birth: str, ref: date) -> int:
    b = date.fromisoformat(birth)
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


def _json_output(box: Any, job: Any, prefix: str) -> dict[str, Any]:
    out = next(
        o
        for o in job.outputs or []
        if o.filename.startswith(prefix) and o.filename.endswith(".json") and not o.filename.endswith(".raw.json")
    )
    data: dict[str, Any] = json.loads(box.store.get(out.minio_key))
    return data


def _mail_text(sent: Any) -> str:
    """Subject, every text part and every plain attachment of one sent mail (what a recipient can read)."""
    parts = [str(sent.subject)]
    for part in sent.msg.walk():
        if part.is_multipart():
            continue
        data = part.get_payload(decode=True) or b""
        if part.get_content_maintype() == "text" or (part.get_filename() or "").endswith((".csv", ".html", ".txt")):
            parts.append(data.decode(part.get_content_charset() or "utf-8", "replace"))
    return "\n".join(parts)


def _audit(box: Any) -> list[dict[str, Any]]:
    """Every record of the hash-chained audit log as written (the console's audit page shows a filtered view)."""
    out: list[dict[str, Any]] = []
    for path in sorted(Path(box.audit_dir).glob("*.jsonl")):
        out += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def _done(box: Any, type_: str, ruleset: str) -> list[Any]:
    return [j for j in box.orch.db.find(type_=type_, ruleset=ruleset, state="done", limit=50)]


def _stage10(res: dict[str, Any], api: Any, crc: Any, lang: str, mrns: set[str], box: Any) -> Stage:
    """Stage 10 (TB-PLAN-04 step 4, D-129): built-in data capture. The coordinator adds the built-in forms, enters a
    consent and a visit through the console, edits the consent (the history shows it), gets a required-field and a
    range refusal in the page's language; the ODM export re-imports into a fresh REDCap simulator project with the
    same dictionary, every value equal; the REDCap CSV's columns are the dictionary's."""
    from console.i18n import CATALOGUES
    from fastapi.testclient import TestClient as SimClient

    cat = CATALOGUES[lang]
    s = Stage("10 built-in data capture")
    t = time.perf_counter()
    rs, no = TRIAL, res["screening_no"]
    page = crc.get(f"/studies/{rs}/forms")
    r = crc.post(f"/studies/{rs}/forms/builtin", data={"csrf": fd._csrf(page.text)})
    s.check("the built-in forms are added in one call", 'data-testid="dc-builtin-added"' in r.text, r.status_code)
    names = [q["name"] for q in api("GET", f"/studies/{rs}/forms")]
    s.check("seven built-in forms", {"tb_screening_log", "tb_consent", "tb_enrolment", "tb_visit", "tb_adverse_event",
                                     "tb_deviation", "tb_withdrawal"} <= set(names), names)  # fmt: skip
    page = crc.get(f"/studies/{rs}/entry", params={"record": no, "form": "tb_consent"})
    label = {"ja": "同意取得日", "zh-TW": "簽署同意日期", "en": "Date of consent"}[lang]
    s.check("the entry page opens a screening number's consent, labels in the page's language",
            'data-testid="entry-form"' in page.text and label in page.text, page.status_code)  # fmt: skip
    csrf = fd._csrf(page.text)

    def save(form: str, values: dict[str, str], event: str = "") -> Any:
        data = {"csrf": csrf, "record": no, "event": event, "form": form, **{f"f_{k}": v for k, v in values.items()}}
        return crc.post(f"/studies/{rs}/entry", data=data)

    h = res["app"].state.helpers
    day = h.today().isoformat()  # T-513 (UX-003): the demo day, so the participant page shows no date after today
    r = save("tb_consent", {"ic_date": day, "ic_copy": "1"})
    s.check("a required field missing is refused, in the page's language",
            'data-testid="why-ic_version"' in r.text and cat["dc.why.required"].split("{label}")[-1] in r.text
            and not any(k.startswith("ic_") for k in api("GET", f"/studies/{rs}/data")["records"].get(no, {})),
            r.status_code)  # fmt: skip
    consent = {"ic_date": day, "ic_version": "v2.1", "ic_copy": "1", "ic_by": "KT"}
    r = save("tb_consent", consent)
    s.check("the consent is saved; the history page follows", 'data-testid="entry-saved"' in r.text, r.url)
    visit = {
        "vs_status": "1",
        "vs_date": day,
        "vs_window": "0",
        "vs_window_note": "二日遅れ",
        "vs_weight": "999",
    }
    r = save("tb_visit", visit, "v1")
    s.check("an out-of-range value is refused, per field", 'data-testid="why-vs_weight"' in r.text
            and "400" in r.text and 'data-testid="entry-saved"' not in r.text, r.status_code)  # fmt: skip
    r = save("tb_visit", {**visit, "vs_weight": "61.5"}, "v1")
    s.check("the visit is saved on event v1", 'data-testid="entry-saved"' in r.text, r.status_code)
    r = save("tb_consent", {**consent, "ic_version": "v2.2"})
    rec = api("GET", f"/studies/{rs}/records/{no}")
    edit = [h for h in rec["history"] if h["field"] == "ic_version" and h["old"] == "v2.1" and h["new"] == "v2.2"]
    row = re.search(rf'data-testid="hist-{edit[0]["id"]}">(.*?)</tr>', r.text, re.S) if edit else None
    s.check("the edit shows in the history: who, old, new", row is not None and "crc" in row.group(1)
            and "v2.1" in row.group(1) and "v2.2" in row.group(1), edit)  # fmt: skip
    # the ODM export, from the console, into a fresh REDCap project with the same dictionary
    odm = crc.get(f"/studies/{rs}/export.odm.xml")
    s.check("ODM 1.3.2 export downloads", odm.status_code == 200 and 'ODMVersion="1.3.2"' in odm.text, odm.status_code)
    meta = api("GET", f"/studies/{rs}/export/dictionary")["metadata"]
    data = api("GET", f"/studies/{rs}/data")["records"]
    names_in_forms = {m["field_name"] for m in meta}
    mine = {(rid, *(k.split(":", 1) if ":" in k else ("", k)), v["value"]) for rid, vals in data.items()
            for k, v in vals.items() if v["value"] != ""}  # fmt: skip
    mine = {x for x in mine if x[2] in names_in_forms}
    events = sorted({e or "event_1_arm_1" for _, e, _, _ in mine})
    sim = SimClient(res["sim"])
    made = sim.post("/sim/projects", json={"title": f"{rs} re-import", "metadata": meta, "events": events}).json()
    r = sim.post("/api/", data={"token": made["token"], "content": "record", "format": "odm", "type": "flat",
                                "data": odm.text})  # fmt: skip
    s.check("the fresh REDCap project takes the ODM", r.status_code == 200, r.text[:200])
    back = sim.post("/api/", data={"token": made["token"], "content": "record", "format": "json"}).json()
    theirs = set()
    for x in back:
        ev = str(x.pop("redcap_event_name", ""))
        rid = str(x.pop("record_id"))
        theirs |= {(rid, "" if ev == "event_1_arm_1" else ev, k, v) for k, v in x.items() if v != ""}
    s.check("every value equal after the ODM round trip", theirs == mine and len(mine) >= 9,
            {"only_trialbox": sorted(mine - theirs)[:5], "only_redcap": sorted(theirs - mine)[:5]})  # fmt: skip
    rows = list(csv.reader(io.StringIO(crc.get(f"/studies/{rs}/export.csv").text)))
    want = ["record_id", "redcap_event_name"]
    for m in meta[1:]:
        if m["field_type"] == "checkbox":
            want += [
                f"{m['field_name']}___{c.split(',')[0].strip()}" for c in m["select_choices_or_calculations"].split("|")
            ]
        else:
            want.append(m["field_name"])
    s.check("the REDCap CSV columns match the dictionary", rows and rows[0] == want, rows[0][:6] if rows else rows)
    s.check(
        "the REDCap CSV has one row per record and event",
        [(r[0], r[1]) for r in rows[1:]] == [(no, "event_1_arm_1"), (no, "v1")],
        [r[:2] for r in rows[1:]],
    )
    s.check("no chart number in the exports", not any(f'"{m}"' in odm.text for m in mrns))
    seen = {str(x["event"]) for x in _audit(box)}
    s.check("entry and export are in the audit", {"data.entry", "data.export", "console.data_entry"} <= seen)
    s.seconds = time.perf_counter() - t
    return s


def _stage11(res: dict[str, Any], api: Any, crc: Any, pi: Any, lang: str, mrns: set[str], box: Any) -> Stage:
    """Stage 11 (TB-PLAN-04 step 5, D-134): the trial lifecycle. A new participant: enrolled through the forms ->
    visit due -> overdue -> done ("Done today" on the coordinator's visit list) -> AEs logged on ae1 (serious, shown
    on the investigator's home page) and ae2 -> withdrawn; an illegal step refused with a plain reason. Then the
    screening log, the enrolment report and the REDCap read-back (the simulator) agree on every count."""
    from datetime import timedelta

    from console.i18n import CATALOGUES
    from fastapi.testclient import TestClient as SimClient
    from openpyxl import load_workbook
    from rc_bridge.writeback import STATUSES

    cat = CATALOGUES[lang]
    s = Stage("11 trial lifecycle")
    t = time.perf_counter()
    rs = TRIAL
    h = res["app"].state.helpers
    from console.timefmt import local_today, site_zone

    today = local_today(h.clock(), site_zone(h.bk))  # the site's date (07:00 in Tokyo is the day before in UTC)
    # a new participant: the next listed patient without a screening number gets one
    have = set(h.store.screening_nos(rs))
    pid = next(r["pid"] for r in h.week_bundle(None, rs)["rows"] if r["pid"] not in have)
    no = h.store.assign_screening_no(rs, pid, h.settings_of(rs), h.clock().isoformat())
    # the visit schedule, defined in TrialBox
    page = crc.get(f"/studies/{rs}/schedule")
    sched = {"csrf": fd._csrf(page.text), "action": "save", "visit": ["v1", "v2", "v3"], "label": ["", "", ""],
             "day": ["7", "28", "84"], "before": ["2", "3", "7"], "after": ["2", "3", "7"],
             "anchor": ["enrolment"] * 3}  # fmt: skip
    r = crc.post(f"/studies/{rs}/schedule", data=sched)
    s.check("the visit schedule is saved (3 visits with windows)", 'data-testid="schedule-saved"' in r.text,
            r.status_code)  # fmt: skip
    page = crc.get(f"/studies/{rs}/subjects")
    s.check("the new screening number is a participant (candidate)",
            re.search(rf'data-testid="subject-{no}">.*?data-state="candidate"', page.text, re.S) is not None,
            page.status_code)  # fmt: skip
    csrf = fd._csrf(page.text)
    r = crc.post(f"/studies/{rs}/subjects/{no}/step", data={"csrf": csrf, "to": "enrolled"})
    plain = cat["life.why.order"].split("{")[0]
    s.check("an illegal step is refused with a plain reason, in the page's language",
            r.status_code == 409 and 'data-testid="life-refused"' in r.text and plain.strip() in r.text,
            r.status_code)  # fmt: skip
    refused = api("GET", f"/studies/{rs}/subjects/{no}")["subject"]["state"]
    s.check("nothing changed after the refusal", refused == "candidate", refused)
    enrol = today - timedelta(days=12)  # v1 is due on day 7 (window +-2): overdue today
    day = enrol.isoformat()
    r = crc.post(
        f"/studies/{rs}/subjects/{no}/step",
        data={"csrf": csrf, "to": "approached", "on_day": (enrol - timedelta(days=3)).isoformat()},
    )
    s.check("approached, recorded by the coordinator", 'data-testid="life-saved"' in r.text, r.status_code)

    def save(form: str, values: dict[str, str], event: str = "", back: str = "subject") -> Any:
        data = {"csrf": csrf, "record": no, "event": event, "form": form, "back": back,
                **{f"f_{k}": v for k, v in values.items()}}  # fmt: skip
        return crc.post(f"/studies/{rs}/entry", data=data)

    save("tb_consent", {"ic_date": (enrol - timedelta(days=1)).isoformat(), "ic_version": "v3", "ic_copy": "1"})
    r = save("tb_enrolment", {"en_date": day, "en_eligible": "1"})
    s.check("consent and enrolment forms move the participant to enrolled",
            'data-state="enrolled"' in r.text and api("GET", f"/studies/{rs}/subjects/{no}")["subject"]["state"]
            == "enrolled", r.status_code)  # fmt: skip

    def v1(on: Any) -> str:
        one = api("GET", f"/studies/{rs}/subjects/{no}?today={on.isoformat()}")
        return str(next(v["status"] for v in one["visits"] if v["visit"] == "v1"))

    seq = [v1(enrol + timedelta(days=3)), v1(enrol + timedelta(days=7)), v1(today)]
    s.check("visit v1: due, then in its window, then overdue (given days, site time zone)",
            seq == ["due", "open", "overdue"], seq)  # fmt: skip
    page = crc.get(f"/studies/{rs}/visits")
    over = page.text[page.text.find('data-testid="visits-overdue"') :]
    s.check("the coordinator's visit list shows it under Overdue", f'data-testid="visit-{no}-v1"' in over,
            page.status_code)  # fmt: skip
    home = crc.get("/home").text
    s.check("the coordinator's home page lists the overdue visit", f'data-testid="visit-{no}-v1"' in home)
    from console import notify

    crc_user = next(u for u in h.users.users() if u.username == "crc")
    mail_day = today if today.weekday() < 5 else today + timedelta(days=7 - today.weekday())  # N2: working days
    lf = h.life_mail(rs, mail_day) if h.life_mail else {}
    n2 = notify.build_n2(crc_user, h.store.notify_person("crc"), mail_day, [], None, {rs: lf})
    body = n2.body if n2 else ""
    s.check("N2 lists the overdue visit by pseudonym with its screening number (D-136)",
            f"{pid[:8]} ({no})" in body, body[-300:])  # fmt: skip
    s.check(
        "N2 carries no chart number",
        bool(body) and not any(re.search(rf"(?<!\d){m_}(?!\d)", body) for m_ in mrns),
    )
    m = re.search(rf'href="([^"]+)" data-testid="done-{no}-v1"', page.text)
    form = crc.get(m.group(1).replace("&amp;", "&")).text if m else ""
    s.check("Done today opens the visit form filled in for today",
            f'value="{today.isoformat()}"' in form and 'name="back" value="visits"' in form, bool(m))  # fmt: skip
    r = save("tb_visit", {"vs_status": "1", "vs_date": today.isoformat(), "vs_window": "0",
                          "vs_window_note": "late"}, "v1", "visits")  # fmt: skip
    s.check("Save: the visit is done and leaves the list",
            'data-testid="visit-saved"' in r.text and f'data-testid="visit-{no}-v1"' not in r.text
            and v1(today) == "done", r.status_code)  # fmt: skip
    st = api("GET", f"/studies/{rs}/subjects/{no}")["subject"]["state"]
    s.check("the first visit done: on study", st == "on_study", st)
    r = save("tb_adverse_event", {"ae_term": "肺炎", "ae_onset": today.isoformat(), "ae_serious": "1",
                                  "ae_serious_why": "3", "ae_severity": "3", "ae_related": "9"}, "ae1")  # fmt: skip
    r = save("tb_adverse_event", {"ae_term": "頭痛", "ae_onset": today.isoformat(), "ae_serious": "0",
                                  "ae_severity": "1", "ae_related": "0"}, "ae2")  # fmt: skip
    aes = api("GET", f"/studies/{rs}/subjects/{no}")["aes"]
    s.check("two AEs logged on events ae1 and ae2", [a["event"] for a in aes] == ["ae1", "ae2"]
            and 'data-testid="ae-ae2"' in r.text, [a["event"] for a in aes])  # fmt: skip
    week = pi.get("/week").text
    s.check("the serious AE is shown on the investigator's home page",
            'data-testid="sae-banner"' in week and f'data-testid="sae-{no}-ae1"' in week)  # fmt: skip
    r = save("tb_withdrawal", {"wd_date": today.isoformat(), "wd_reason": "3", "wd_data_use": "1"})
    s.check("the withdrawal form: withdrawn, no further step offered",
            'data-state="withdrawn"' in r.text and 'data-testid="life-final"' in r.text, r.status_code)  # fmt: skip
    r = crc.post(f"/studies/{rs}/subjects/{no}/step", data={"csrf": csrf, "to": "on_study"})
    s.check("a step after withdrawal is refused", r.status_code == 409 and 'data-testid="life-refused"' in r.text)
    vs = [v["status"] for v in api("GET", f"/studies/{rs}/subjects/{no}")["visits"]]
    s.check("the remaining visits are not needed", vs == ["done", "stopped", "stopped"], vs)
    trail = [(x["old"], x["new"]) for x in api("GET", f"/studies/{rs}/subjects/{no}")["steps"]]
    want = [(None, "candidate"), ("candidate", "approached"), ("approached", "consented"), ("consented", "enrolled"),
            ("enrolled", "on_study"), ("on_study", "withdrawn")]  # fmt: skip
    s.check("every step is in the participant's history", trail == want, trail)
    # the three counts: Run now (S21 read and write-back), then the screening log, the report and REDCap agree
    log = crc.get(f"/studies/{rs}/screening-log")
    crc.post(f"/studies/{rs}/redcap-read", data={"csrf": fd._csrf(log.text), "back": "log"})
    x = crc.get(f"/studies/{rs}/screening-log.xlsx")
    ws = load_workbook(io.BytesIO(x.content), read_only=True).active
    rows = [list(r_) for r_ in ws.iter_rows(values_only=True)] if ws is not None else []
    col = rows[0].index("status") if rows else 0
    nos = {str(r_[0]) for r_ in rows[1:]}
    log_counts = dict(Counter(str(r_[col]) for r_ in rows[1:]))
    rep_csv = list(csv.reader(io.StringIO(crc.get(f"/studies/{rs}/enrolment.csv").text)))
    from datacore.lifecycle import REGISTRY_OF

    rep_counts: Counter[str] = Counter()
    for r_ in rep_csv:
        if r_[:2] == ["state", "now"] and int(r_[3]):
            rep_counts[REGISTRY_OF[r_[2]]] += int(r_[3])
    sim = SimClient(res["sim"])
    token_a = next(k for k, v in res["sim"].state.sim.projects.items() if v["project"]["project_id"] == 101)
    back = sim.post("/api/", data={"token": token_a, "content": "record", "format": "json", "type": "flat"}).json()
    rc_counts = dict(Counter(STATUSES[int(b["tb_status"]) - 1] for b in back
                             if b.get("tb_screening_no") in nos and b.get("tb_status")))  # fmt: skip
    s.check("screening log = enrolment report = REDCap read-back, on every count",
            log_counts == dict(rep_counts) == rc_counts and sum(log_counts.values()) == len(nos) >= 3,
            {"log": log_counts, "report": dict(rep_counts), "redcap": rc_counts})  # fmt: skip
    s.check("the new participant reads withdrawn in all three",
            log_counts.get("withdrawn", 0) >= 1 and any(b.get("tb_screening_no") == no and b.get("tb_status") == "7"
                                                        for b in back), no)  # fmt: skip
    xl = crc.get(f"/studies/{rs}/enrolment.xlsx")
    s.check(
        "the enrolment report downloads as XLSX and CSV",
        xl.status_code == 200 and xl.content[:2] == b"PK" and rep_csv[0] == ["table", "key", "state", "count"],
    )
    body = "\n".join([crc.get(f"/studies/{rs}/enrolment").text, json.dumps(rep_csv), xl.content.decode("latin-1")])
    s.check("no chart number in the report", not any(re.search(rf"(?<!\d){m}(?!\d)", body) for m in mrns))
    seen = {str(e["event"]) for e in _audit(box)}
    s.check("steps, refusals and the schedule are in the audit",
            {"life.step", "life.refused", "life.schedule", "console.life_step"} <= seen)  # fmt: skip
    s.seconds = time.perf_counter() - t
    return s


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SITE_RS = "SITE5B"  # the new site's trial (criteria drafted by the stub from its cassette)
SITE_WS = "newsite"  # the new site's own space, with its own lake: the hospital feed of stages 0-11 is untouched
SITE_CRITERIA = (
    "Inclusion Criteria\n1. Aged 18 years or older.\n2. Diagnosis of gout (ICD-10-CM M10 or M1A).\n"
    "3. Most recent serum urate in the last year at least 7.0 mg/dL.\n\nExclusion Criteria\n"
    "1. Any history of malignancy.\n"
)


def _stage12(res: dict[str, Any], crc: Any, pi: Any, lang: str, box: Any) -> Stage:
    """Stage 12 (TB-PLAN-04 step 5b, D-131, D-132, D-135): a new site set up the hard way. A protocol, two charts
    pasted from an EMR screen, an IT dump in Shift_JIS with the hospital's own codes, a PI's messy Excel list (a
    title row, merged cells, era and 民國 dates, full-width digits, a value in µmol/L and one in an unknown unit, a
    slashed date that could go both ways, a row without a chart number, an ID column that might be the chart
    number, a name column). A proposed fact only sends a patient to "needs information" until a coordinator
    confirms it; then it counts, and may exclude. A scripted coordinator works through the "please check" list and
    the hospital codes; the readiness page ends green."""
    from sitesetup import help as site_help
    from tb_common.crypto import pid_for_mrn

    s = Stage("12 site set-up and data harmonization")
    t = time.perf_counter()
    q = f"ws={SITE_WS}&study={SITE_RS}"
    key = (Path(box.orch.cfg.env.secrets_dir) / "site_hmac.key").read_bytes()
    pid = {no: pid_for_mrn(key, no) for no in ("10000001", "10000002", "10000003", "10000004", "10000005")}
    orch_api = res["app"].state.helpers.bk.study_api
    lake_before = box.orch.services.lake.snapshot()

    def state(name: str) -> str:
        m = re.search(rf'data-testid="q-{name}" data-state="([a-z]+)"', crc.get(f"/site?{q}").text)
        return m.group(1) if m else "?"

    def checks() -> list[dict[str, Any]]:
        return list(orch_api("GET", f"/setup/{SITE_WS}/checks?open_only=true"))

    def patients() -> dict[str, str]:
        out = orch_api("GET", f"/setup/{SITE_WS}/patients?study={SITE_RS}")
        return {p["pid"]: p["state"] for p in out["patients"]}

    def basis() -> dict[str, int]:
        f = orch_api("GET", f"/setup/{SITE_WS}/feasibility?study={SITE_RS}")["feas"] or {"steps": [{}]}
        return dict(f["steps"][-1])

    def csrf() -> str:
        return fd._csrf(crc.get(f"/site/charts?{q}").text)

    # -- question 1: the trial. The protocol's criteria are pasted; the stub drafts them; the investigator approves
    s.check("start: nothing yet, the patients question is red", state("patients") == "red", state("patients"))
    form = crc.get("/pilot/protocol")
    crc.post("/pilot/protocol", data={"csrf": fd._csrf(form.text), "ruleset": SITE_RS, "criteria": SITE_CRITERIA})
    waiting = box.orch.db.find(ruleset=SITE_RS, state="awaiting_approval", limit=5)
    s.check("the protocol's criteria are drafted and wait for the investigator", bool(waiting) and
            state("trial") == "amber", [j.state for j in box.orch.db.find(ruleset=SITE_RS, limit=5)])  # fmt: skip
    if waiting:
        page = pi.get(f"/pilot/jobs/{waiting[0].job_id}/approval")
        # D-309: a pasted protocol ships no labels in the page language; the investigator gives each one first
        for cid in re.findall(r'data-testid="label-missing-([A-Z0-9-]+)"', page.text):
            pi.post(
                f"/pilot/jobs/{waiting[0].job_id}/approval/label",
                data={"csrf": fd._csrf(page.text), "crit": cid, "text": f"{cid} label"},
            )
        page = pi.get(f"/pilot/jobs/{waiting[0].job_id}/approval")
        pi.post(
            f"/pilot/jobs/{waiting[0].job_id}/approve",
            data={"csrf": fd._csrf(page.text), "confirm": "yes"},
            follow_redirects=False,
        )
    s.check("approved: the trial question is green", state("trial") == "green", state("trial"))
    # -- question 2, with the least: two charts pasted, one by one
    for no, text in site_help.PRACTICE_CHARTS:
        r = crc.post("/site/charts", data={"csrf": csrf(), "ws": SITE_WS, "study": SITE_RS, "chart_no": no,
                                            "text": text})  # fmt: skip
    facts = orch_api("GET", f"/setup/{SITE_WS}/facts?status=proposed")
    s.check("two pasted charts: facts proposed, each beside its quote", len(facts) >= 7 and all(f["quote"] for f in
            facts) and 'data-testid="chart-saved"' in r.text, len(facts))  # fmt: skip
    page = crc.get(f"/site?{q}").text
    s.check("charts alone: the box says feasibility needs a bulk source",
            'data-testid="miss-bulk"' in page and 'data-testid="feas-needs-bulk"' in page)  # fmt: skip
    pc = patients()
    s.check("a proposed fact never counts and never excludes: both chart patients need information",
            pc.get(pid["10000004"]) == "needs" and pc.get(pid["10000005"]) == "needs", pc)  # fmt: skip
    # -- the IT dump: the hospital's own codes, mapped once for the site
    name, data = site_help.practice_inputs()["dump"]
    crc.post("/site/sheets", data={"csrf": csrf(), "ws": SITE_WS, "study": SITE_RS, "kind": "dump"},
             files={"file": (name, data, "text/csv")})  # fmt: skip
    page = crc.get(f"/site?{q}").text
    s.check("the dump: unmapped local codes and diagnoses in an unknown code system are listed",
            'data-testid="miss-unmapped"' in page and 'data-testid="miss-unknown_share"' in page)  # fmt: skip
    pc = patients()
    s.check("until mapped, a local code is an unknown code system: needs information, never a silent no (D-130)",
            pc.get(pid["10000003"]) == "needs" and pc.get(pid["10000001"]) == "needs", pc)  # fmt: skip

    def map_all() -> int:
        n = 0
        for _ in range(20):
            page = crc.get(f"/site/codes?{q}").text
            todo = re.findall(r'data-testid="map-other-([^"]+)"', page)
            if not todo:
                return n
            form = re.search(rf'data-testid="map-{re.escape(todo[0])}">(.*?)</form>', page, re.S)
            hidden = dict(re.findall(r'name="(domain|system|code)" value="([^"]*)"', form.group(1) if form else ""))
            use = re.search(r'name="use" value="([^"-][^"]*)"', form.group(1) if form else "")
            crc.post("/site/codes", data={"csrf": fd._csrf(page), "ws": SITE_WS, "study": SITE_RS, **hidden,
                                          **({"use": use.group(1)} if use else {"target": "I10"})})  # fmt: skip
            n += 1
        return n

    n_mapped = map_all()
    pc = patients()
    s.check("codes mapped with one tap each: the coded patients are read", n_mapped >= 4 and
            pc.get(pid["10000001"]) == "ready" and pc.get(pid["10000003"]) == "not_eligible",
            (n_mapped, pc))  # fmt: skip
    s.check("coded-eligible with a proposed malignancy from a chart: needs information, not excluded",
            pc.get(pid["10000005"]) == "needs", pc.get(pid["10000005"]))  # fmt: skip
    # -- the PI's messy Excel list: safe fixes made and listed, the rest asked
    name, data = site_help.practice_inputs()["sheet"]
    r = crc.post("/site/sheets", data={"csrf": csrf(), "ws": SITE_WS, "study": SITE_RS, "kind": "sheet"},
                 files={"file": (name, data, XLSX)})  # fmt: skip
    fixes = {f["kind"] for f in orch_api("GET", f"/setup/{SITE_WS}/fixes")}
    s.check("safe fixes made and listed: era and 民國 dates, full width, units, merged cells, the title row",
            {"era", "minguo", "width", "unit", "merged", "header_row"} <= fixes, sorted(fixes))  # fmt: skip
    open_ = {c["kind"] for c in checks()}
    s.check("the rest is asked, nothing guessed: day/month, an unknown unit, a possible chart number, no key",
            {"date_order", "unit", "chart_column", "no_key"} <= open_, sorted(open_))  # fmt: skip
    s.check("the name column is dropped and never shown", "氏名" in r.text and "青山" not in r.text and
            "山田" not in json.dumps(orch_api("GET", f"/setup/{SITE_WS}/facts"), ensure_ascii=False))  # fmt: skip
    answered = 0
    for _ in range(12):  # the scripted coordinator: the suggested answer, except the ID column, which is left out
        page = crc.get(f"/site/checks?{q}").text
        found = re.findall(r'data-testid="check-(\d+)" data-kind="([a-z_]+)"', page)
        if not found:
            break
        cid, kind = found[0]
        block = re.search(rf'data-testid="check-{cid}".*?</li>', page, re.S)
        opts = re.findall(r'name="answer" value="([^"]+)"( class="secondary")?', block.group(0) if block else "")
        ans = "drop" if kind == "chart_column" else next((o for o, sec in opts if not sec), "drop")
        crc.post(f"/site/checks/{cid}", data={"csrf": fd._csrf(page), "ws": SITE_WS, "study": SITE_RS, "answer": ans})
        answered += 1
    s.check("the scripted coordinator works through the \"please check\" list", answered >= 4 and not checks(),
            answered)  # fmt: skip
    map_all()
    people = orch_api("GET", f"/setup/{SITE_WS}/people")
    dis = people["disagreements"]
    s.check("one patient from the dump, the list and a chart is one pseudonym; the two birth dates are listed",
            [(d["pid"], d["what"]) for d in dis] == [(pid["10000002"], "birth_date")]
            and any(p["pid"] == pid["10000001"] and p["inputs"] == ["dump", "sheet"] for p in people["people"]),
            dis)  # fmt: skip
    page = crc.get(f"/site/people?{q}").text
    crc.post("/site/people/resolve", data={"csrf": fd._csrf(page), "ws": SITE_WS, "study": SITE_RS,
                                           "pid": pid["10000002"], "what": "birth_date",
                                           "keep": "1971-06-05"})  # fmt: skip
    b = basis()
    s.check("feasibility: proposed facts are not counted", b.get("proposed", 0) >= 1 and b.get("confirmed") == 0, b)
    # -- the coordinator confirms the proposed facts, one tap each (Confirm on the review list)
    n = 0
    for _ in range(30):
        page = crc.get(f"/site/facts?{q}").text
        ids = re.findall(r'data-testid="confirm-(\d+)"', page)
        if not ids:
            break
        crc.post(f"/site/facts/{ids[0]}", data={"csrf": fd._csrf(page), "ws": SITE_WS, "study": SITE_RS,
                                                 "action": "confirm"})  # fmt: skip
        n += 1
    pc = patients()
    s.check("confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready",
            n >= 7 and pc.get(pid["10000005"]) == "not_eligible" and pc.get(pid["10000004"]) == "ready",
            (n, pc))  # fmt: skip
    b = basis()
    s.check("feasibility says how much of the count rests on confirmed facts", b.get("confirmed", 0) >= 1 and
            b.get("proposed") == 0, b)  # fmt: skip
    # -- question 3: trial records in TrialBox's own forms
    page = crc.get(f"/studies/{SITE_RS}/forms")
    crc.post(f"/studies/{SITE_RS}/forms/builtin", data={"csrf": fd._csrf(page.text)})
    page = crc.get(f"/site?{q}").text
    s.check("the readiness page is green", 'data-testid="site-overall" data-state="green"' in page,
            re.findall(r'data-testid="miss-[^"]+"', page))  # fmt: skip
    # -- Ask TrialBox: explains and links, never changes anything
    before = json.dumps([orch_api("GET", f"/setup/{SITE_WS}/{x}") for x in ("facts", "codes", "checks")])
    nxt = {"ja": "次に何をすればよいですか？", "zh-TW": "下一步該做什麼？"}.get(lang, "What next?")
    r = crc.get("/ask", params={"q": nxt, "ws": SITE_WS, "study": SITE_RS})
    why = crc.get("/ask", params={"pid": pid["10000005"], "ws": SITE_WS, "study": SITE_RS})
    after = json.dumps([orch_api("GET", f"/setup/{SITE_WS}/{x}") for x in ("facts", "codes", "checks")])
    s.check("Ask TrialBox answers \"what next?\" and \"why?\" from the pages, and changes nothing",
            'data-kind="next"' in r.text and 'data-kind="why"' in why.text and before == after)  # fmt: skip
    # -- privacy: chart numbers and names stay inside the box's protected area
    text = "\n".join(crc.get(f"/site{p}?{q}").text for p in ("", "/facts", "/codes", "/checks", "/people", "/patients"))
    trail = json.dumps(_audit(box), ensure_ascii=False)
    s.check("no chart number or name on the pages or in the audit",
            not re.search(r"1000000[0-9]", re.sub(r'data-testid="[^"]*"', "", text) + trail)
            and not any(w in text + trail for w in ("青木", "青山", "石田", "上野", "江藤")))  # fmt: skip
    s.check("every decision is in the audit", {"setup.chart", "setup.input", "setup.map", "setup.check",
            "setup.resolve", "setup.fact", "console.site_fact"} <= {str(e["event"]) for e in _audit(box)})  # fmt: skip
    s.check("the hospital's own lake is untouched by the new site", box.orch.services.lake.snapshot() == lake_before)
    s.seconds = time.perf_counter() - t
    return s


def gout_coh_numbers(box: Any, cohort_members: int) -> dict[str, Any]:
    """The GOUT-COH numbers of this run: the FEAS funnel, the SCREEN funnel and tiers, and the cohort list."""
    out: dict[str, Any] = {"cohort": cohort_members}
    fj = _done(box, "FEAS", COHORT)
    if fj:
        raw = json.loads(
            box.store.get(next(o.minio_key for o in fj[0].outputs or [] if o.filename.endswith(".raw.json")))
        )
        out["feas"] = {"start": raw["start_n"], "remaining": raw["remaining"]}
    sj = _done(box, "SCREEN", COHORT)
    if sj:
        scr = _json_output(box, sj[0], "screen_")
        out["screen"] = {"funnel": dict(scr["funnel"]), "listed": scr["listed"], "tiers": scr["tiers"]}
    return out


def _stage13(work: Path, box: Any, gout: dict[str, Any]) -> Stage:
    """Stage 13 (TB-PLAN-04 step 7, D-137): Japan completeness. A synthetic SS-MIX2 hospital (400 patients) with
    ADT-52 class changes, OMP-11/12 実施 with and without their orders, HOT codes and extended-storage documents is
    read by the adapter; the sample passes JP Core ``$validate``; the licensed MEDIS / JLAC10 / YJ loader reads the
    three 10-row samples; the GOUT-COH funnel of the SS-MIX2 storage equals its CSV export's, and the main run's
    GOUT-COH funnel equals the numbers recorded before step 7."""
    from adapter import licensed
    from adapter.cli import main as adapter_main
    from adapter.pipeline import AdapterConfig, run_ingest
    from adapter.sources.ssmix2 import source as ss
    from adapter.validate.jpcore import JpCoreValidator, sample_per_type, validate_snapshot
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from lake.store import Lake
    from orchestrator.scenarios.feas_compute import FeasParams, compute
    from tb_common.audit import verify
    from tb_common.ruleset import Ruleset
    from tb_contracts import RebuildResult

    from tools.ssmix2_export import export
    from tools.synth_hospital import run as synth_run

    s = Stage("13 Japan: SS-MIX2, JP Core and the licensed code lists")
    t = time.perf_counter()
    jp = work / "japan"
    ref, snap = date(2026, 11, 1), "2026-10-31"
    synth_run(jp / "synth", profile="ci", sites="jp-e2e:JP:400", ref_date=ref)
    csv_dir, storage = jp / "synth" / "jp-e2e", jp / "ssmix2"
    sent = export(csv_dir, storage)
    s.check("the synthetic SS-MIX2 hospital has ADT-52, OMP-02/11/12 and extended-storage documents",
            all(sent[k] > 0 for k in ("ADT-52", "OMP-02", "OMP-11", "OMP-12", "document")), sent)  # fmt: skip

    # -- the licensed lists: "not loaded" first, then the three 10-row samples
    samples = ROOT / "tests" / "fixtures" / "licensed"
    files = {"medis": "medis_byomei_sample.txt", "jlac10": "jlac10_sample.tsv", "yj": "yj_hot_sample.txt"}
    s.check("without the files the box says which lists are not loaded",
            {x["kind"]: x["state"] for x in licensed.status()} == dict.fromkeys(files, "not_loaded"))  # fmt: skip
    st = licensed.TermStore()
    try:
        loaded = {k: st.load(k, (samples / f).read_bytes(), version="sample-2026", source=f, by="admin",
                             audit_dir=box.audit_dir) for k, f in files.items()}  # fmt: skip
    finally:
        st.close()
    s.check("the loader reads each 10-row sample in its own encoding and layout",
            {k: (v["rows"], v["encoding"]) for k, v in loaded.items()}
            == {"medis": (10, "cp932"), "jlac10": (10, "utf-8"), "yj": (10, "cp932")}, loaded)  # fmt: skip
    status = {x["kind"]: (x["state"], x["version"], x["source"]) for x in licensed.status()}
    s.check("each list is loaded with its version and source",
            all(v[0] == "loaded" and v[1] == "sample-2026" and v[2] == files[k] for k, v in status.items()),
            status)  # fmt: skip

    # -- D-130 with and without the lists: a 標準病名 code with no ICD-10 alternate and no site lookup
    try:
        saved, ss.JP_CORE = ss.JP_CORE, jp / "no-site-lookups"
        bare = ss.Ssmix2Source(storage, licensed={k: {} for k in files})
        list(bare.rows("diagnosis", "diagnosis", None, None))
        withlic = ss.Ssmix2Source(storage)
        list(withlic.rows("diagnosis", "diagnosis", None, None))
    finally:
        ss.JP_CORE = saved
    gone = sum(bare.missed.values()) - sum(withlic.missed.values())
    s.check("D-130: without the lists their codes resolve nowhere (unknown); the MEDIS list resolves its codes, "
            "the rest stay unknown", sum(bare.missed.values()) > 0 and gone > 0 and sum(withlic.missed.values()) > 0
            and withlic.stats["diagnosis:licensed"] == gone, (sum(bare.missed.values()), gone))  # fmt: skip

    # -- the adapter reads the storage; JP Core $validate on the sample
    sec = jp / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(secrets.token_bytes(32))
    reports = {}
    for kind, mapping in (("csv", "tw_core/demo_his.yaml"), ("ssmix2", "jp_core/ssmix2_site.yaml")):
        lake_dir = jp / f"lake-{kind}"

        def rebuild(sn: str, nd: Path, lake_dir: Path = lake_dir) -> RebuildResult:
            r = Lake(lake_dir, "Asia/Tokyo").rebuild(sn, HashEmbedder(), nd)
            return RebuildResult(snapshot=r.snapshot, tables=r.tables, chunks=r.chunks, embedded_new=r.embedded_new,
                                 seconds=r.seconds)  # fmt: skip

        cfg = AdapterConfig(lake_dir=lake_dir, secrets_dir=sec, site_id="JP-E2E", tz="Asia/Tokyo",
                            mapping_path=ROOT / "services/adapter/mapping" / mapping, rebuild=rebuild,
                            audit_dir=jp / "audit")  # fmt: skip
        reports[kind] = run_ingest(
            cfg, kind, str(csv_dir if kind == "csv" else storage), snapshot=snap, load_fhir=False
        )
    rep = reports["ssmix2"]
    reader = json.loads((jp / "lake-ssmix2/ndjson" / snap / "reader.json").read_text(encoding="utf-8"))["read"]
    s.check("ADT-52: every class change read into its visit", reader.get("ADT-52:class change") == sent["ADT-52"],
            reader)  # fmt: skip
    s.check("OMP-11/12: read with their order or on their own",
            all(reader.get(k, 0) > 0 for k in ("OMP-11:with its order", "OMP-11:without an order",
                                               "OMP-12:with its order", "OMP-12:without an order")))  # fmt: skip
    same = {t: (reports["csv"].counts.get(t), rep.counts.get(t)) for t in ("Patient", "Encounter", "MedicationRequest",
                                                                          "Condition", "Observation")}  # fmt: skip
    s.check("the storage gives the CSV's patients, visits, medicines, diagnoses and results",
            all(a == b and a for a, b in same.values()), same)  # fmt: skip
    pv = rep.profile_validation
    expect = sum(min(50, n) for n in rep.counts.values())
    s.check("JP Core $validate passes on the sample (50 per type, at ingest)",
            rep.passed and pv is not None and pv.errors == 0 and pv.sampled == expect,
            (pv and (pv.sampled, pv.errors, (pv.messages or [])[:2]), (rep.errors or [])[:2]))  # fmt: skip
    again = validate_snapshot(jp / "lake-ssmix2/ndjson" / snap, 50)
    with contextlib.redirect_stdout(io.StringIO()):  # the CLI prints its JSON; the check reads its exit status
        cli = adapter_main(["validate", "--lake", str(jp / "lake-ssmix2"), "--per-type", "10"])
    s.check("$validate over the written snapshot and the CLI agree", again.errors == 0 and cli == 0,
            (again.sampled, again.errors, cli))  # fmt: skip
    from adapter.ndjson import read_all

    tw = JpCoreValidator().validate(sample_per_type(
        [r for v in read_all(jp / "lake-csv/ndjson" / snap).values() for r in v], 5))  # fmt: skip
    s.check("the check bites: the TW Core output of the same hospital fails JP Core, and says why",
            tw.errors > 0 and any("claims a TW Core profile" in m for m in tw.messages()),
            tw.messages()[:2])  # fmt: skip

    # -- extended storage: documents with their text for the two models, no identifiers
    lj = LakeLocal(jp / "lake-ssmix2", HashEmbedder(), "Asia/Tokyo")
    docs = lj.query("SELECT did, type, text FROM document WHERE type IN ('discharge', 'report')").to_pylist()
    s.check("extended-storage documents are in the lake with their text (Shift_JIS text and a PDF)",
            reader.get("document") == sent["document"] and any("退院時サマリ" in d["text"] for d in docs)
            and any("no acute findings" in d["text"] for d in docs), (reader.get("document"), len(docs)))  # fmt: skip
    mrns = {r["mrn"] for r in csv.DictReader((csv_dir / "patient.csv").open(encoding="utf-8"))}
    ids = " ".join(d["did"] for d in docs)
    s.check("no chart number or storage path in the documents' ids", not any(m in ids for m in mrns)
            and "DSC-01" not in ids and "ext/" not in ids)  # fmt: skip

    # -- the GOUT-COH funnel: SS-MIX2 equals CSV, and the main run equals the numbers before step 7
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    params = FeasParams(run_date=ref, snapshot=snap, lookback_months=36)
    fun = {}
    for kind in ("csv", "ssmix2"):
        _, raw = compute(LakeLocal(jp / f"lake-{kind}", HashEmbedder(), "Asia/Tokyo"), rs, params)
        fun[kind] = (raw.start_n, raw.remaining)
    s.check("GOUT-COH funnel: the SS-MIX2 storage equals its CSV export", fun["ssmix2"] == fun["csv"]
            and list(fun["csv"][1].values())[2] > 0, fun)  # fmt: skip
    shift_file = work / "hospital" / fd.SHIFT_FILE  # T-513: dates moved to the demo day change the pinned numbers
    own_day = not shift_file.exists() or shift_file.read_text(encoding="utf-8").strip() == "0"
    if PAIR is None and own_day and gout["feas"]["start"] == GOUT_COH_BEFORE_STEP7["feas"]["start"]:  # the gate, stub
        s.check("GOUT-COH funnel of the main run unchanged by step 7 (FEAS, SCREEN, cohort list)",
                gout == GOUT_COH_BEFORE_STEP7, gout)  # fmt: skip
    else:  # another size (tools.complete_run) or another day (tools.demo): pinned on the gate's hospital and day
        rem = list(gout["feas"]["remaining"].values())
        sf = gout["screen"]["funnel"]
        s.check("GOUT-COH funnel of the main run: FEAS and SCREEN never grow",
                all(a >= b for a, b in itertools.pairwise([gout["feas"]["start"], *rem]))
                and sf["S0"] >= sf["S1"] >= sf["S3"], gout)  # fmt: skip
    events = {str(e["event"]) for e in _audit(box)}
    s.check("each licensed load is in the hash-chained audit", "terminology.load" in events
            and verify(box.audit_dir).ok)  # fmt: skip
    s.seconds = time.perf_counter() - t
    return s


# GOUT-COH on the e2e hospital, recorded on master f5c78fb before step 7 (D-137): step 7 must not move it
GOUT_COH_BEFORE_STEP7: dict[str, Any] = {
    "cohort": 5,
    "feas": {
        "start": 5000,
        "remaining": {
            "GOUT-COH-INC-02": 1210,
            "GOUT-COH-INC-03": 797,
            "GOUT-COH-INC-04": 237,
            "GOUT-COH-INC-05": 54,
            "GOUT-COH-INC-06": 26,
            "GOUT-COH-INC-07": 6,
        },
    },
    "screen": {
        "funnel": {"S0": 3341, "S1": 9, "S3": 0, "S4": 9},
        "listed": 9,
        "tiers": {"excluded": 3332, "high": 5, "review": 4},
    },
}


@contextlib.contextmanager
def _no_network() -> Any:
    """Every TCP connection off this machine fails (Unix sockets and loopback still work: the trial database)."""
    import socket

    real = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6) and str(address[0]) not in (
            "127.0.0.1",
            "::1",
            "localhost",
        ):
            raise OSError(f"e2e_simple stage 14: no network ({address[0]})")
        return real(self, address)

    socket.socket.connect = connect  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        socket.socket.connect = real  # type: ignore[method-assign]


def _stage14(work: Path, box: Any) -> Stage:
    """Stage 14 (D-140): ClinicalTrials.gov offline. The sample reference data pack (the synthetic trials of the
    cassettes, two real records, tiny TFDA / MHLW / NHI / ICD-10-CM excerpts) is built, verified and loaded; with every
    outbound connection refused, a trial is found by NCT id, by condition and by a Japan or Taiwan site, and the
    criteria are drafted from the pack's full record. D-170 to D-172: the Taiwan maps and synonyms of the same pack
    answer offline (NHI drug -> ATC, NHI lab -> LOINC, a TW 2014 ICD code -> 2023, a zh-TW word in the matcher).
    D-173 to D-175: the Japan items too (the WHO ICD-10 bridge, YJ -> ATC, CTCAE v5.0, a ja word in the matcher)."""
    from criteria_compiler.ctgov import CtGov
    from tb_common import refdata as rd
    from tb_contracts import CompileRequest, CtgovSearchRequest, ParseRequest

    from tools import refdata_fetch as rf

    s = Stage("14 ClinicalTrials.gov offline: the reference data pack")
    t = time.perf_counter()
    tar = rf.build(rf.sample_raw(work / "refdata" / "raw"), work / "refdata", "20261109", sample=True)
    with rd.opened(tar) as pack:
        m = rd.verify(pack)
        s.check("the pack verifies: every file's sha256 and record count", len(m["sources"]) == 15, m["pack_id"])
        s.check("each source has its URL, date, sha256, count, licence, terms and attribution",
                all(x["url"] and x["download_sha256"] and x["attribution"] for x in m["sources"]))  # fmt: skip
        with rd.RefStore() as st:
            loaded = st.load(pack, by="e2e_simple")
            status = st.status()
    s.check("loaded into the trial database (schema refdata, in the backup)", loaded.counts.get("ctgov") == 6
            and status is not None and status["data_as_of"] == "2026-11-09", loaded.counts)  # fmt: skip
    ct = CtGov(mode="offline")
    with _no_network():
        one = ct.search(CtgovSearchRequest(condition="", nct_id="NCT99000001"))
        jp = ct.search(CtgovSearchRequest(condition="gout", locations=["Japan"]))
        tw = ct.search(CtgovSearchRequest(condition="gout", locations=["Taiwan"]))
        s.check("found by NCT id", [x.nct_id for x in one.studies] == ["NCT99000001"] and one.source == "refdata")
        s.check("found by condition and a Japan site", sorted(x.nct_id for x in jp.studies) == ["NCT99000001",
                "NCT99000003"], [x.nct_id for x in jp.studies])  # fmt: skip
        s.check("found by condition and a Taiwan site", sorted(x.nct_id for x in tw.studies) == ["NCT99000001",
                "NCT99000002"], [x.nct_id for x in tw.studies])  # fmt: skip
        study = one.studies[0]
        key = f"ctgov/{study.nct_id}/{study.last_update}/{study.nct_id}_eligibility.txt"
        box.store.put(key, study.eligibility_text.encode("utf-8"), "text/plain")
        parsed = box.orch.services.parser.parse(ParseRequest(minio_key=key, job_id="e2e-refdata"))
        pkey = f"ctgov/{study.nct_id}/{study.last_update}/parsed.json"
        box.store.put(pkey, parsed.model_dump_json().encode("utf-8"), "application/json")
        res = box.orch.services.compiler.compile(CompileRequest(
            job_id="e2e-refdata", ruleset=study.nct_id, parsed_doc_key=pkey, kind="trial", title=study.title,
            requested_by="e2e_simple", options={"index_date": "2026-11-01", "incremental": "false"}))  # fmt: skip
    s.check("criteria drafted from the pack's record, with no network",
            bool(res.draft_zip_key) and bool(parsed.ie_block.inclusion), res.draft_zip_key)  # fmt: skip
    from criteria_compiler.terminology.mapper import Terminology
    from sitesetup import mapping as sm
    from tb_common import refdata_jp as rdjp

    with _no_network():
        drug = sm.suggest("medication", sm.local_system("drug-code"), "B004858100")
        lab = sm.suggest("observation", sm.local_system("lab-code"), "12198C")
        dx = sm.suggest("condition", sm.local_system("dx-code"), "P83.8")
        ra = Terminology(name_synonyms=rd.synonym_lookup()).map("condition", "類風濕關節炎")
        yj = sm.suggest("medication", sm.local_system("drug-code"), "3339004F1020")
        ja = Terminology(name_synonyms=rd.synonym_lookup()).map("condition", "関節リウマチ")
        who = rdjp.who_icd10_in_list("E11.9", set(), [(rdjp.ICD10CM, "E11")])
        with rd.RefStore() as st:
            nausea = st.term(rdjp.CTCAE5, "Nausea")
    dx_want = "P83.88" if sm.site_country() == "TW" else "P83.8"  # the 2014 -> 2023 step runs at Taiwan sites only
    s.check("D-170/171: NHI drug -> ATC, NHI lab -> LOINC and (Taiwan) TW 2014 -> 2023 ICD suggested offline",
            (drug.get("code"), lab.get("code"), dx.get("code")) == ("N05AF01", "83113-1", dx_want),
            (drug, lab, dx))  # fmt: skip
    s.check("D-172: 類風濕關節炎 maps to rheumatoid arthritis through the curated synonym dictionary, no review",
            ra.method == "synonym" and not ra.needs_review and bool(ra.concepts)
            and "tw_zh_synonyms" in " ".join(ra.notes), ra.notes)  # fmt: skip
    s.check("D-173: a WHO ICD-10 code (E11.9) falls in its ICD-10-CM family through the bridge", who == "yes", who)
    s.check("D-174: a YJ code (apixaban) -> ATC B01AF02 by its stem; CTCAE v5.0 Nausea with its grades, offline",
            yj.get("code") == "B01AF02" and nausea is not None and bool(nausea["extra"]["grades"]["1"]),
            (yj, nausea))  # fmt: skip
    s.check(
        "D-175: 関節リウマチ maps to rheumatoid arthritis through the ja synonym dictionary, no review",
        ja.method == "synonym" and not ja.needs_review and "ja_synonyms" in " ".join(ja.notes),
        ja.notes,
    )
    s.seconds = time.perf_counter() - t
    return s


def _stage15(res: dict[str, Any], pi: Any, crc: Any, password: str, lang: str, mrns: set[str], box: Any) -> Stage:
    """D-147: the PI keeps the delegation log, a sub-investigator sees the hospital's candidates and asks the treating
    doctor (unknown to the data: arranged outside TrialBox), the CRC records the agreement, Approach follows under the
    IRB warning (recorded), and an opt-out entered by chart number leaves the lists and the next screening run."""
    s = Stage("15 delegation, candidates and referral")
    t = time.perf_counter()
    app = res["app"]
    h = app.state.helpers

    def csrf(c: Any) -> str:
        return fd._csrf(c.get("/home").text) or ""

    def events(name: str) -> list[dict[str, Any]]:
        return [r for r in _audit(box) if r.get("event") == name]

    h.users.create("subpi", "investigator", password, "subpi@hospa.test")
    sub = ld.sign_in(app, "subpi", password, lang)
    today = h.today().isoformat()
    r1 = pi.post(f"/studies/{TRIAL}/team", data={"csrf": csrf(pi), "username": "pi", "role": "pi", "start": today},
                 follow_redirects=False)  # fmt: skip
    r2 = pi.post(f"/studies/{TRIAL}/team", data={"csrf": csrf(pi), "username": "subpi", "role": "sub_pi",
                                                 "tasks": ["screen", "refer"], "start": today,
                                                 "training_day": today}, follow_redirects=False)  # fmt: skip
    log = pi.get(f"/studies/{TRIAL}/team").text
    s.check("the PI adds themselves and a sub-investigator to the delegation log",
            (r1.status_code, r2.status_code) == (303, 303) and log.count('data-testid="entry-') == 2,
            (r1.status_code, r2.status_code))  # fmt: skip
    s.check(
        "the sub-investigator cannot change their own ticks (403)",
        sub.post(f"/studies/{TRIAL}/team/2", data={"csrf": csrf(sub), "tasks": ["approach"]}).status_code == 403,
    )
    cand = sub.get(f"/studies/{TRIAL}/candidates")
    week = h.week_bundle(None, TRIAL)
    rows = [r for r in (week["cl"] or {}).get("rows") or [] if r.get("tier") in ("high", "review")]
    shown = re.search(r'data-testid="cand-count">\D*(\d+)', cand.text)
    s.check("the sub-investigator sees every candidate of the study's run",
            cand.status_code == 200 and shown is not None and int(shown.group(1)) == len(rows),
            (cand.status_code, shown and shown.group(1), len(rows)))  # fmt: skip
    marks = h.store.latest_marks(TRIAL)
    x = next(str(r["pid"]) for r in rows if str(r["pid"]) not in marks)
    y = next(str(r["pid"]) for r in rows if str(r["pid"]) not in marks and str(r["pid"]) != x)
    first = sub.get(f"/studies/{TRIAL}/candidates/{x}").text
    view = sub.get(f"/studies/{TRIAL}/candidates/{x}?purpose=eligibility")
    logged = [e for e in events("console.candidate_view") if e["detail"].get("pid") == x]
    s.check("a candidate opens only with a purpose, logged with the study and the purpose",
            'data-testid="purpose"' in first and view.status_code == 200 and 'data-testid="why"' in view.text
            and logged and logged[-1]["detail"].get("purpose") == "eligibility" and logged[-1]["ruleset"] == TRIAL,
            len(logged))  # fmt: skip
    rv = sub.post(
        f"/studies/{TRIAL}/candidates/{x}/reveal", data={"csrf": csrf(sub), "purpose": "contact", "reason": "contact"}
    )  # D-143's reveal and reason
    m = re.search(r'data-testid="mrn">[^<]*<span class="mono">([^<]+)<', rv.text)
    s.check("the delegated sub-investigator reveals the chart number (D-143), audited with reason and purpose",
            m is not None and m.group(1) in mrns and any(
                e["detail"].get("purpose") == "contact" and e["actor"] == "console:subpi"
                for e in events("console.reveal_patient")), m and "shown")  # fmt: skip
    wk = sub.get(f"/studies/{TRIAL}/week?list=all&pid={x}").text
    r = sub.post(f"/studies/{TRIAL}/patients/{x}/mark", data={"csrf": fd._csrf(wk), "mark": "approach"})
    s.check("Approach without the tick is refused (403)", r.status_code == 403, r.status_code)
    r = sub.post(f"/studies/{TRIAL}/candidates/{x}/referral", data={"csrf": csrf(sub), "route": "outside"},
                 follow_redirects=False)  # fmt: skip
    ref = h.team.referrals(TRIAL, x)[-1] if h.team.referrals(TRIAL, x) else None
    s.check("a referral with no doctor named is accepted (arranged outside TrialBox) and numbered",
            r.status_code == 303 and ref is not None and ref.route == "outside" and h.store.screening_no(TRIAL, x),
            r.status_code)  # fmt: skip
    pk = pi.get(f"/studies/{TRIAL}/patients/{x}").text
    r = pi.post(f"/studies/{TRIAL}/patients/{x}/mark", data={"csrf": fd._csrf(pk), "mark": "approach"})
    s.check("the PI's Approach waits for the doctor's agreement (409)", r.status_code == 409, r.status_code)
    assert ref is not None
    lp = crc.get(f"/studies/{TRIAL}/referrals").text
    agree = {"csrf": fd._csrf(lp), "answer": "agree", "channel": "phone"}
    r = crc.post(f"/studies/{TRIAL}/referrals/{ref.id}/answer", data=agree, follow_redirects=False)
    r2 = pi.post(f"/studies/{TRIAL}/patients/{x}/mark", data={"csrf": fd._csrf(pk), "mark": "approach"},
                 follow_redirects=False)  # fmt: skip
    over = [e for e in events("console.approach_override") if e["detail"].get("pid") == x]
    s.check("the CRC records the doctor's agreement; Approach follows under the IRB warning, recorded",
            r.status_code == 303 and r2.status_code == 303 and len(over) == 1 and over[0]["actor"] == "console:pi",
            (r.status_code, r2.status_code, len(over)))  # fmt: skip
    from openpyxl import load_workbook

    xl = crc.get(f"/studies/{TRIAL}/screening-log.xlsx")
    ws: Any = load_workbook(io.BytesIO(xl.content), read_only=True).active
    table = [list(v) for v in ws.iter_rows(values_only=True)]
    by_pid = {str(v[1]): dict(zip(table[0], v, strict=False)) for v in table[1:]}
    row = by_pid.get(x) or {}
    s.check("the screening log counts the referral with its route and outcome",
            (row.get("referral_route"), row.get("referral_outcome")) == ("outside", "agreed")
            and row.get("approach_irb_override"), row)  # fmt: skip
    for who in ("cra", "viewer"):
        c = ld.sign_in(app, who, password, lang)
        got = [c.get(p).status_code for p in (f"/studies/{TRIAL}/candidates", f"/studies/{TRIAL}/candidates/{x}"
                                              "?purpose=eligibility", f"/studies/{TRIAL}/referrals")]  # fmt: skip
        s.check(f"the {who} account stays masked (403)", set(got) == {403}, got)
    # opt-out by chart number: the box turns it into the pseudonym; the number is never stored
    mrn_y = h.bk.reveal(week["job"].job_id, y, "console:crc", role="coordinator", scope="*")  # signed (D-273)
    op = crc.get("/site/opt-outs").text
    r = crc.post("/site/opt-outs", data={"csrf": fd._csrf(op), "chart_no": mrn_y or "", "source": "paper"},
                 follow_redirects=False)  # fmt: skip
    s.check("an opt-out entered by chart number is registered under the patient's pseudonym",
            r.status_code == 303 and y in h.optout.active() and mrn_y not in json.dumps(
                [e.__dict__ for e in h.optout.events()]), r.status_code)  # fmt: skip
    after = [str(v.get("pid")) for v in (h.week_bundle(None, TRIAL)["cl"] or {}).get("rows") or []]
    cand = pi.get(f"/studies/{TRIAL}/candidates").text
    s.check(
        "the opted-out patient leaves the list and the candidates (the count stays)",
        y not in after and f'data-testid="cand-{y[:8]}"' not in cand and 'data-testid="optout-count"' in cand,
    )
    form = crc.get(f"/pilot/request?ruleset={TRIAL}")
    r = crc.post("/pilot/request", data={"csrf": fd._csrf(form.text), "kind": "SCREEN", "ruleset": TRIAL, "pract": ""},
                 follow_redirects=False)  # fmt: skip
    jid = r.headers.get("location", "").rsplit("/", 1)[-1]
    job = box.orch.db.get(jid)
    out = _json_output(box, job, "candidate_list_") if job is not None and job.state == "done" else {}
    removed = [e for e in events("screen.opt_out_removed") if e.get("job_id") == jid]
    s.check("the next screening run leaves the opted-out patient out, and says so in the audit",
            bool(out) and y not in {str(v.get("pid")) for v in out.get("rows") or []} and len(removed) == 1,
            (job and job.state, len(removed)))  # fmt: skip
    s.seconds = time.perf_counter() - t
    return s


def _edc_expected(lake: Any, pid: str, visit: date) -> dict[str, str]:
    """What the hospital record says, read straight from the lake (not through the prefill code)."""
    out: dict[str, str] = {}
    rows = lake.query("SELECT birth_date, sex FROM patient WHERE pid = $1", [pid]).to_pylist()
    if rows and rows[0]["birth_date"] is not None:
        out["brthdat"] = str(rows[0]["birth_date"])[:10]
    obs = lake.query("SELECT CAST(effective AS DATE) AS d, value_num, unit, coalesce(value_cmp, '') AS cmp "
                     "FROM observation WHERE pid = $1 AND code = '3084-1' "
                     "AND CAST(effective AS DATE) <= CAST($2 AS DATE)",
                     [pid, visit.isoformat()]).to_pylist()  # fmt: skip
    if obs:
        last = max(o["d"] for o in obs)
        same = [o for o in obs if o["d"] == last]
        if len({o["value_num"] for o in same}) == 1 and all(not o["cmp"] for o in same) and all(
                str(o["unit"] or "").replace(" ", "").lower() == "mg/dl" for o in same):  # fmt: skip
            v = float(same[0]["value_num"])
            out["urate"] = str(int(v)) if v.is_integer() else f"{v:.6f}".rstrip("0").rstrip(".")
    return out


def _err_codes(page: str) -> list[str]:
    """The error codes a refused console page names (``edc.ack_date``...), so a failed check says why."""
    return sorted(set(re.findall(r"\b(?:edc\.err\.)?edc\.[a-z_]+(?:\.[a-z_]+)*\b", page)) - {"edc.err"})


def _stage16(res: dict[str, Any], pi: Any, crc: Any, password: str, lang: str, box: Any) -> Stage:
    """D-160: EDC prefill. The PI's switch is refused without the sponsor's acknowledgement, then turned on; the CRC
    reads the CRF's data dictionary from REDCap, saves the item map (CDASH tags), drafts a subject's visit from the
    hospital record (each value equal to the record, each with its citation), gets the refusals (no citation, no
    reason, send before signing, a wrong password), confirms, signs with the password and the meaning, and sends:
    a value someone entered in REDCap is not overwritten; every sent value reads back equal; the ODM file re-imports
    into a fresh project equal; viewer and CRA see nothing; off stops sending; the audit chain holds."""
    from console.timefmt import local_today, site_zone
    from fastapi.testclient import TestClient as SimClient
    from rc_bridge.client import RedcapClient
    from tb_common.audit import verify

    from tests import edc_kit

    s = Stage("16 EDC prefill")
    t = time.perf_counter()
    app = res["app"]
    h = app.state.helpers
    lake = box.orch.services.lake

    def csrf(c: Any, path: str = "/home") -> str:
        return fd._csrf(c.get(path).text) or ""

    on_list = h.optout.active() if h.optout is not None else set()
    nos = {p: n for p, n in h.store.screening_nos(TRIAL).items() if p not in on_list}
    with_urate = {str(r["pid"]) for r in lake.query("SELECT DISTINCT pid FROM observation WHERE code = '3084-1'"
                                                     ).to_pylist()}  # fmt: skip
    pid = next((p for p in sorted(nos) if p in with_urate), sorted(nos)[0] if nos else "")
    no = nos.get(pid, "")
    s.check("a GZQO subject with a screening number to prefill", bool(no), len(nos))
    if not no:
        s.seconds = time.perf_counter() - t
        return s
    visit = h.today()
    # the box refuses an acknowledgement or a visit dated after its own day: the console's site day must be the box's
    site_day = local_today(h.clock(), site_zone(h.bk))
    s.check("the console and the box keep one site date", site_day == box.orch.today(), (site_day, box.orch.today()))
    # T-513 (UX-003): the visit date the participant page shows (stage 10's v1) is the date EDC drafts below
    sub = crc.get(f"/studies/{TRIAL}/subjects/{res['screening_no']}").text
    shown = re.search(r'data-testid="sv-v1"[^>]*>.*?<span class="nowrap">(\d{4}-\d{2}-\d{2})</span>', sub, re.S)
    s.check("the participant page's visit date is the date EDC drafts, not after the box's day",
            shown is not None and shown.group(1) == visit.isoformat() and visit <= box.orch.today(),
            (shown and shown.group(1), visit, box.orch.today()))  # fmt: skip
    sim = SimClient(res["sim"])
    made = sim.post("/sim/projects", json={"title": "GZQO CRF", "metadata": edc_kit.CRF}).json()
    rc = RedcapClient(rc_demo.SIM_URL, made["token"])
    rc.import_records([{"record_id": "1", "tb_screening_no": no}])
    admin = res["admin"]
    page = admin.get("/admin/redcap")
    admin.post("/admin/redcap", data={"csrf": fd._csrf(page.text), "token_ref": "edc", "url": rc_demo.SIM_URL,
                                      "token": made["token"]})  # fmt: skip
    # the CRC signs under their own delegation-log entry (D-162): the PI adds it
    lg = pi.post(f"/studies/{TRIAL}/team", data={"csrf": csrf(pi), "username": "crc", "role": "crc",
                                                 "start": visit.isoformat(), "training_day": visit.isoformat()},
                 follow_redirects=False)  # fmt: skip
    s.check("the PI adds the CRC to the delegation log", lg.status_code == 303, lg.status_code)
    # off by default: nothing is drafted
    home = crc.get(f"/studies/{TRIAL}/edc")
    r = crc.post(f"/studies/{TRIAL}/edc/drafts", data={"csrf": fd._csrf(home.text), "record": no,
                                                       "visit_date": visit.isoformat()})  # fmt: skip
    s.check(
        "prefill is off by default; a draft is refused",
        home.status_code == 200
        and 'data-testid="edc-state"' in home.text
        and r.status_code == 409
        and "edc.off" in r.text,
        (home.status_code, r.status_code),
    )
    # the PI: refused without the acknowledgement, then on
    sw = {
        "csrf": csrf(pi, f"/studies/{TRIAL}/edc"),
        "on": "1",
        "kind": "sponsor_letter",
        "reference": "",
        "ack_date": visit.isoformat(),
        "reentry_pages": "30",
        "reentry_accuracy": "98.6",
    }
    r1 = pi.post(f"/studies/{TRIAL}/edc/switch", data=sw)
    r2 = pi.post(f"/studies/{TRIAL}/edc/switch", data={**sw, "reference": "SPN-GZQO-001"}, follow_redirects=False)
    r3 = crc.post(f"/studies/{TRIAL}/edc/switch", data={**sw, "csrf": fd._csrf(home.text), "reference": "x"})
    s.check("the PI switches prefill on only with the sponsor's acknowledgement; a CRC cannot (403)",
            r1.status_code == 409 and r2.status_code == 303 and r3.status_code == 403,
            (r1.status_code, r2.status_code, r3.status_code, _err_codes(r2.text)))  # fmt: skip
    # dictionary from REDCap, then the map through /api/v1
    mp = crc.get(f"/studies/{TRIAL}/edc/map")
    r = crc.post(
        f"/studies/{TRIAL}/edc/dictionary",
        data={"csrf": fd._csrf(mp.text), "token_ref": "edc", "record_field": "record_id"},
        follow_redirects=False,
    )
    sug = crc.get(f"/studies/{TRIAL}/edc/map?suggest=1").text
    s.check(
        "the CRF's data dictionary is read from REDCap (the identifier field dropped) and a map suggested",
        r.status_code == 303 and 'data-testid="map-weight"' in sug and "pt_initials" not in sug,
        r.status_code,
    )
    api = SimClient(app)
    tok = api.post("/api/v1/session", json={"username": "crc", "password": password}).json()["token"]
    hd = {"authorization": f"Bearer {tok}"}
    items = [dict(m) for m in edc_kit.MAP]
    for m in items:
        if m["item"] == "urate":
            m["window_days"] = 3650
        if m["item"] == "mh_gout":
            m["codes"] = list(GOUT)
    r = api.put(f"/api/v1/studies/{TRIAL}/edc/map", json={"items": items, "target": edc_kit.TARGET}, headers=hd)
    s.check("the item map with CDASH tags is saved through /api/v1", r.status_code == 200, r.text[:200])
    # draft the visit
    home = crc.get(f"/studies/{TRIAL}/edc").text
    r = crc.post(
        f"/studies/{TRIAL}/edc/drafts",
        data={"csrf": fd._csrf(home), "record": no, "visit_date": visit.isoformat()},
        follow_redirects=False,
    )
    st = h.bk.study_api("GET", f"/studies/{TRIAL}/edc/drafts?record={no}")
    d = {x["item"]: x for x in st}
    want = _edc_expected(lake, pid, visit)
    drafted = {k: v["value"] for k, v in d.items() if v["state"] == "drafted"}
    s.check("the subject's visit is drafted; every value carries a citation, every unknown a reason",
            r.status_code == 303 and d and all(bool(v["citation"]) == (v["state"] == "drafted") for v in d.values())
            and all(v["why"] for v in d.values() if v["state"] == "unknown"),
            (r.status_code, _err_codes(r.text), sorted(drafted)))  # fmt: skip
    s.check("the drafted values equal the hospital record (birth date, uric acid)",
            all(drafted.get(k) == v for k, v in want.items()) and all(
                k in want for k in drafted if k in ("brthdat", "urate")), (want, drafted))  # fmt: skip
    s.check(
        "an absent diagnosis or medicine is unknown, never 'No'",
        all(v["value"] != "0" for v in d.values()),
        {k: v["value"] for k, v in d.items()},
    )
    rev = crc.get(f"/studies/{TRIAL}/edc/review/{no}")
    c = fd._csrf(rev.text)
    s.check("the draft has the free-text item and at least one drafted value to review",
            "comments" in d and bool(drafted), (r.status_code, sorted(d)))  # fmt: skip
    if "comments" not in d or not drafted:
        s.seconds = time.perf_counter() - t
        return s  # a failed check, not a crash: the rest of the stage needs a draft
    r_cite = crc.post(f"/studies/{TRIAL}/edc/decide/{d['comments']['id']}", data={"csrf": c, "action": "confirm",
                                                                                  "record": no})  # fmt: skip
    first = next(iter(drafted))
    r_reason = crc.post(
        f"/studies/{TRIAL}/edc/decide/{d[first]['id']}",
        data={"csrf": c, "action": "edit", "value": drafted[first], "record": no},
    )
    s.check("the review screen refuses a value without a citation and a change without a reason",
            rev.status_code == 200 and r_cite.status_code == 409 and r_reason.status_code == 409,
            (rev.status_code, r_cite.status_code, r_reason.status_code))  # fmt: skip
    for k in drafted:
        crc.post(f"/studies/{TRIAL}/edc/decide/{d[k]['id']}", data={"csrf": c, "action": "confirm", "record": no})
    crc.post(f"/studies/{TRIAL}/edc/send", data={"csrf": c, "record": no})
    before = rc.records()[0]
    s.check("nothing reaches REDCap before the signature", all(before.get(k, "") == "" for k in drafted), before)
    shown = crc.get(f"/studies/{TRIAL}/edc/review/{no}").text
    m_seen = re.search(r'name="seen" value="([^"]*)"', shown)
    seen = m_seen.group(1) if m_seen else ""
    bad = crc.post(f"/studies/{TRIAL}/edc/sign", data={"csrf": c, "record": no, "password": "wrong-" + password,
                                                       "meaning_ack": "1", "seen": seen})  # fmt: skip
    stale = crc.post(f"/studies/{TRIAL}/edc/sign", data={"csrf": c, "record": no, "password": password,
                                                         "meaning_ack": "1", "seen": seen.split(",")[0]})  # fmt: skip
    s.check(
        "a signature over a different set of values than the page showed is refused",
        stale.status_code == 409 and seen.count(":") == len(drafted),
        (stale.status_code, seen.count(":")),
    )
    sign = {"csrf": c, "record": no, "password": password, "meaning_ack": "1", "seen": seen}
    good = crc.post(f"/studies/{TRIAL}/edc/sign", data=sign, follow_redirects=False)
    sigs = h.bk.study_api("GET", f"/studies/{TRIAL}/edc/trail/{no}")["signatures"]
    s.check("the signature needs the password again (a wrong one signs nothing) and records name, meaning, time",
            bad.status_code == 401 and good.status_code == 303 and len(sigs) == 1 and sigs[0]["meaning"] ==
            "transcribed" and sigs[0]["printed_name"], (bad.status_code, good.status_code, len(sigs)))  # fmt: skip
    # someone types a birth date in REDCap first: it is never overwritten
    clash = "brthdat" if "brthdat" in drafted else first
    rc.import_records([{"record_id": "1", clash: "1901-01-01" if clash == "brthdat" else "9"}])
    r = crc.post(f"/studies/{TRIAL}/edc/send", data={"csrf": c, "record": no}, follow_redirects=False)
    loc = r.headers.get("location", "")
    after = rc.records()[0]
    sent_ok = all(after.get(k) == v for k, v in drafted.items() if k != clash)
    s.check("signed values are sent and read back equal; a value entered in REDCap is listed, not overwritten",
            r.status_code == 303 and "conflict=1" in loc and sent_ok and after.get(clash) in ("1901-01-01", "9"),
            loc)  # fmt: skip
    odm = crc.get(f"/studies/{TRIAL}/edc/export.odm.xml")
    fresh = sim.post("/sim/projects", json={"title": "re-import", "metadata": edc_kit.CRF}).json()
    imp = sim.post("/api/", data={"token": fresh["token"], "content": "record", "format": "odm", "type": "flat",
                                  "data": odm.text})  # fmt: skip
    back = RedcapClient(rc_demo.SIM_URL, fresh["token"]).records()
    s.check("the ODM 1.3.2 file (audit record, signature, CDASH alias) re-imports into a fresh project equal",
            odm.status_code == 200 and "<Signature>" in odm.text and 'Context="CDASH"' in odm.text
            and imp.status_code == 200 and back and all(back[0].get(k) == v for k, v in drafted.items()),
            imp.text[:120])  # fmt: skip
    for who in ("viewer", "cra"):
        cl = ld.sign_in(app, who, password, lang)
        got = [cl.get(p).status_code for p in (f"/studies/{TRIAL}/edc", f"/studies/{TRIAL}/edc/review/{no}",
                                               f"/studies/{TRIAL}/edc/export.odm.xml")]  # fmt: skip
        s.check(f"the {who} account sees no prefill page (403/404)", set(got) <= {403, 404}, got)
    off = pi.post(f"/studies/{TRIAL}/edc/switch", data={"csrf": csrf(pi, f"/studies/{TRIAL}/edc"), "on": "0",
                                                        "reason": "e2e"}, follow_redirects=False)  # fmt: skip
    r = crc.post(f"/studies/{TRIAL}/edc/send", data={"csrf": c})
    s.check("switched off, nothing more is sent", off.status_code == 303 and r.status_code == 409,
            (off.status_code, r.status_code))  # fmt: skip
    ev = [x for x in _audit(box) if str(x.get("event", "")).startswith("edc.")]
    names = {str(x["event"]) for x in ev}
    blob = json.dumps([x.get("detail") for x in ev], ensure_ascii=False)
    s.check("every step is in the audit, without the clinical values, and the chain verifies",
            {"edc.switch", "edc.dictionary", "edc.map", "edc.drafts", "edc.decide", "edc.sign", "edc.sent",
             "edc.export"} <= names and (not want.get("brthdat") or want["brthdat"] not in blob)
            and verify(Path(box.audit_dir)).ok, sorted(names))  # fmt: skip
    s.seconds = time.perf_counter() - t
    return s


def _recorded_source(lake_dir: Path, snapshot: str) -> str | None:
    from tools.omop_parity import recorded_source

    return recorded_source(lake_dir, snapshot)


def run(work: Path, password: str, lang: str = "ja") -> dict[str, Any]:
    """Run the whole path once in ``work`` (must be empty or absent); return the stages and the timings."""
    from console.i18n import CATALOGUES
    from openpyxl import load_workbook
    from orchestrator.rerun import rerun
    from tb_common.audit import verify

    t0 = time.perf_counter()
    res = rc_demo.run(work, password, lang)  # FEAS -> approve -> SCREEN -> marks -> mail -> REDCap -> log
    t_chain = time.perf_counter() - t0
    lst = res["list"]
    box, app, pi, crc = lst["box"], res["app"], lst["pi"], res["crc"]
    h = app.state.helpers
    cat = CATALOGUES[lang]
    stages: list[Stage] = []
    hosp = work / "hospital"
    patients = list(csv.DictReader((hosp / "patient.csv").open(encoding="utf-8")))
    mrns = {p["mrn"] for p in patients}
    names = {p["name"] for p in patients if p["name"]}

    # ---------------------------------------------------------------- stage 0: data in
    s = Stage("0 data in")
    t = time.perf_counter()
    synth = json.loads((work / "synth" / "summary.json").read_text(encoding="utf-8"))
    s.check("generator rate checks", not synth["failures"] and synth["rate_cells"]["fail"] == 0, synth["rate_cells"])
    want = {"patient": 0, "note": 0, "encounter": 0}
    for site in synth["sites"]:
        meta = json.loads((work / "synth" / site["dir"] / "meta.json").read_text(encoding="utf-8"))
        for k in want:
            want[k] += int(meta["counts"][k])
    lake = box.orch.services.lake

    def q(sql: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = lake.query(sql).to_pylist()
        return rows

    got = {
        k: int(q(f"SELECT count(*) AS n FROM {t}")[0]["n"])
        for k, t in (("patient", "patient"), ("note", "document"), ("encounter", "encounter"))
    }
    s.check("lake counts = generator counts (patients, notes, encounters)", got == want, f"lake {got} generator {want}")
    tables = (
        "patient",
        "encounter",
        "condition",
        "observation",
        "medication",
        "document",
        "document_chunk",
        "appointment",
        "claim",
        "consent",
        "procedure",
        "report",
        "practitioner",
    )
    cols = {tb: set(lake.query(f"SELECT * FROM {tb} LIMIT 1").column_names) for tb in tables}
    bad = {
        tb: sorted(c & {"mrn", "id_no", "phone", "address"}) for tb, c in cols.items() if c & {"mrn", "id_no", "phone"}
    }
    s.check("no chart number, ID or phone column in the lake", not bad and "name" not in cols["patient"], bad)
    pids = {r["pid"] for r in q("SELECT pid FROM patient")}
    s.check("lake keys are pseudonyms, never chart numbers", not pids & mrns, len(pids & mrns))
    # T-202 (D-384): CI runs this gate on both lake sources; the lake must really come from the one asked for
    want_src = (os.environ.get("TB_LAKE_SOURCE") or "legacy").strip().lower()
    lake_dir = getattr(getattr(lake, "lake", None), "dir", None)
    said = _recorded_source(Path(lake_dir), str(lake.snapshot())) if lake_dir else None
    s.check(f"the lake was built from the source asked for ({want_src})", said == want_src, f"recorded {said}")
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 1: FEAS report
    s = Stage("1 feasibility report")
    t = time.perf_counter()
    feas = _done(box, "FEAS", TRIAL)
    s.check("a finished FEAS job for GZQO", bool(feas), [j.job_id for j in feas])
    fj = feas[0]
    names_out = sorted(o.filename for o in fj.outputs or [])
    s.check("PDF, XLSX and JSON report", all(any(n.endswith(x) for n in names_out) for x in (".pdf", ".xlsx", ".json")))
    rep = _json_output(box, fj, "feasibility_")
    raw = json.loads(box.store.get(next(o.minio_key for o in fj.outputs or [] if o.filename.endswith(".raw.json"))))
    # the funnel counts on month ends (feas_compute): the population is everyone with a visit from one month before the
    # first month end to the last month end of the 36; T-513 moves the data to the demo day, so that is not always
    # every patient (a patient seen only in the days after the last month end comes in next month)
    from tb_common.timeutil import add_months, month_ends

    ends = month_ends(fj.run_date or box.orch.today(), 36)
    lo, ref = add_months(ends[0], -1).isoformat(), ends[-1]
    with (hosp / "encounter.csv").open(encoding="utf-8") as fh:
        in_window = {r["mrn"] for r in csv.DictReader(fh) if lo <= r["visit_datetime"][:10] <= ref.isoformat()}
    adults = {p["mrn"] for p in patients if p["mrn"] in in_window and _age(p["birth_date"], ref) >= 18}
    gout = {
        r["mrn"] for r in csv.DictReader((hosp / "diagnosis.csv").open(encoding="utf-8")) if r["icd10"].startswith(GOUT)
    }
    s.check("start = every patient seen in 36 months", raw["start_n"] == len(in_window),
            (raw["start_n"], len(in_window)))  # fmt: skip
    s.check(
        "INC-01 age >= 18 = recount from patient.csv",
        raw["remaining"]["GZQO-INC-01"] == len(adults),
        (raw["remaining"]["GZQO-INC-01"], len(adults)),
    )
    s.check(
        "INC-02 gout dx = recount from diagnosis.csv",
        raw["remaining"]["GZQO-INC-02"] == len(adults & gout),
        (raw["remaining"]["GZQO-INC-02"], len(adults & gout)),
    )
    rem = [row["remaining"] for row in rep["funnel"]]
    s.check("funnel never grows", all(a >= b for a, b in itertools.pairwise(rem)), rem)
    prov = rep.get("provenance") or {}
    need = (
        "study",
        "ruleset_version",
        "snapshot",
        "data_sources",
        "model_summary",
        "prompt_versions",
        "run_date",
        "clock",
        "job_id",
        "language",
    )
    s.check("FR-REP-01 provenance block", all(k in prov for k in need) and prov.get("job_id") == fj.job_id, prov)
    s.check(
        "FEAS ran without a model (D-101)", prov.get("models") == [] and "no model" in str(prov.get("model_summary"))
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 2: approval
    s = Stage("2 investigator approval")
    t = time.perf_counter()
    approved = [r for r in h.bk.audit(None, 5000) if r.event == "console.approve_all"]
    s.check(
        "both studies approved by the investigator",
        len(approved) == 2 and {r.actor for r in approved} == {"console:pi"},
        [(r.ruleset, r.actor) for r in approved],
    )
    job_id = fj.job_id
    page = crc.get(f"/pilot/jobs/{job_id}/approval")
    r = crc.post(f"/pilot/jobs/{job_id}/approve", data={"csrf": fd._csrf(page.text) or ""}, follow_redirects=False)
    s.check("a coordinator's approve is refused (403, FR-AUTH-13)", r.status_code == 403, r.status_code)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 3: SCREEN
    s = Stage("3 screening")
    t = time.perf_counter()
    sj = _done(box, "SCREEN", TRIAL)[0]
    scr = _json_output(box, sj, "screen_")
    j = scr["judging"]
    if PAIR is None:
        s.check("stub model ran, single judge", j["judge_model"] == "stub" and j["verifier_model"] is None, j)
        s.check(
            "no note-based exclusion without two models agreeing", j["note_block"] == "never" and not j["may_block"], j
        )
    else:  # tools.complete_run on the card: the pair ran, and a note excludes only when both agree (D-115, D-117)
        s.check("the pair ran: judge and verifier", (j["judge_model"], j["verifier_model"]) == PAIR, j)
        s.check("the pair canary passed, so notes may exclude", j["may_block"], j)
        s.check("a note excludes only when both models agree", j["note_block"] == "both_agree", j)
    fun = dict((k, v) for k, v in scr["funnel"])
    s.check("funnel S0 >= S1 >= S3 >= S4 > 0", fun["S0"] >= fun["S1"] >= fun["S3"] >= fun["S4"] > 0, fun)
    s.check("listed = high + review", scr["listed"] == scr["tiers"]["high"] + scr["tiers"]["review"], scr["tiers"])
    sp = scr.get("provenance") or {}
    s.check(
        "FR-REP-01 provenance names the model and prompt",
        sp.get("models") == (["stub"] if PAIR is None else list(PAIR)) and sp.get("prompt_versions"),
        sp,
    )
    s.check(
        "cohort list for GOUT-COH (no contact step)",
        lst["cohort_new"] > 0 and 'data-testid="mark-' not in lst["cohort_html"],
        lst["cohort_new"],
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 4: list, marks, mail
    s = Stage("4 list, marks and mail")
    t = time.perf_counter()
    picks = lst["picks"]
    # the investigator changes their mind on the third patient: not_now -> approach (the history keeps both)
    third = picks[2]["pid"]
    page = pi.get(f"/studies/{TRIAL}/week?list=all&pid={third}")
    r = pi.post(
        f"/studies/{TRIAL}/patients/{third}/mark",
        data={"csrf": fd._csrf(page.text), "mark": "approach", "back": "list:all"},
        follow_redirects=False,
    )
    s.check("replacing a mark is accepted", r.status_code == 303, r.status_code)
    hist = [m.mark for m in h.store.mark_history(TRIAL, third)]
    s.check("mark history keeps the replaced mark", hist[-2:] == ["not_now", "approach"], hist)
    mails = lst["mails"]
    s.check("N1 and N2 mail sent", len(mails) >= 2, [m.subject for m in mails])
    body = "\n".join(_mail_text(m) for m in mails)
    leaked = sorted(m for m in mrns if re.search(rf"(?<!\d){m}(?!\d)", body))
    s.check("mail carries no chart number", not leaked, leaked[:3])
    s.check("mail carries no patient name", not [n for n in names if n in body][:1])
    numbered = [(p[:8], n) for p, n in h.store.screening_nos(TRIAL).items() if f"({n})" in body]
    s.check("mail shows the screening number beside the pseudonym (D-136)",
            bool(numbered) and all(f"{p} ({n})" in body for p, n in numbered), numbered[:3])  # fmt: skip
    s.check(
        "the PI's marked patients appear in the mail by pseudonym",
        all(f"{p['pid'][:8]}" in body for p in picks),
        [p["pid"][:8] for p in picks],
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 5: ready vs needs information (D-120)
    s = Stage("5 ready and needs-information lists")
    t = time.perf_counter()
    from console import studies as st

    today = h.today()
    wrows = h.week_bundle(None, TRIAL)["rows"]
    ready = [r for r in wrows if st.in_worklist(r, "ready", today)]
    needs = [r for r in wrows if st.in_worklist(r, "needs", today)]
    s.check("ready and needs information do not overlap", not {r["pid"] for r in ready} & {r["pid"] for r in needs})
    s.check("ready rows have no unknown", all(st.n_open(r) == 0 for r in ready), len(ready))
    s.check("needs-information rows have an unknown", all(st.n_open(r) > 0 for r in needs), len(needs))
    rail = {}
    for k in ("ready", "needs"):
        page = pi.get(f"/studies/{TRIAL}/week?list={k}").text
        m = re.search(rf'data-testid="list-{k}"[^>]*>.*?<span class="n[^"]*">(\d+)</span>', page, re.S)
        rail[k] = int(m.group(1)) if m else -1
        shown = [int(x) for x in re.findall(r'data-testid="open-n-[0-9a-f]{8}">\D*(\d+)', page)]
        if k == "needs":
            s.check("needs information: fewest unknowns first", shown == sorted(shown), shown[:10])
        n_rows = len(re.findall(r'data-testid="row-[0-9a-f]{8}"', page))
        s.check(f"{k}: at most {st.PAGE_SIZE} rows a page", n_rows <= st.PAGE_SIZE, n_rows)
    s.check("rail counts = the split", rail == {"ready": len(ready), "needs": len(needs)}, rail)
    # T-513 (UX-003): one run, one date: the list and the not-matched page name the same run day, not after today
    run_days = {
        k: re.findall(r"\d{4}-\d{2}-\d{2}", m.group(1))[:1]
        for k, path, tid in (("week", f"/studies/{TRIAL}/week?list=all", "week-run"),
                             ("not matched", f"/studies/{TRIAL}/excluded", "ex-run"))
        if (m := re.search(rf'data-testid="{tid}">(.*?)</p>', pi.get(path).text, re.S))
    }  # fmt: skip
    s.check("the week page and the not-matched page show the same run date, not after today",
            len(run_days) == 2 and run_days["week"] == run_days["not matched"] != []
            and run_days["week"][0] <= today.isoformat(), (run_days, today))  # fmt: skip
    feas = pi.get(f"/studies/{TRIAL}/feasibility").text
    m = re.search(r'data-testid="bridge-list">([^<]*)<', feas)
    nums = [int(x) for x in re.findall(r"\d+", m.group(1))] if m else []
    s.check(
        "S3 explains the list: listed, ready, needs",
        nums[:3] == [len(wrows), len(ready), len(needs)],
        f"{nums[:3]} vs {[len(wrows), len(ready), len(needs)]}",
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 7: REDCap and the screening log
    s = Stage("7 REDCap read-back and screening log")
    t = time.perf_counter()
    s.check("S36 test connection", res["s36_ok"])
    s.check(
        "candidate -> consented -> enrolled",
        res["before"] == cat["registry.status.candidate"]
        and res["after_consent"].startswith(cat["registry.status.consented"])
        and res["after_enrol"].startswith(cat["registry.status.enrolled"]),
        (res["before"], res["after_consent"], res["after_enrol"]),
    )
    s.check("sponsor subject number shown", res["subject_shown"])
    x = crc.get(f"/studies/{TRIAL}/screening-log.xlsx")
    ok_x = x.status_code == 200 and x.content[:2] == b"PK"
    rows: list[list[Any]] = []
    if ok_x:
        ws = load_workbook(io.BytesIO(x.content), read_only=True).active
        rows = [list(r) for r in ws.iter_rows(values_only=True)] if ws is not None else []
    s.check("screening log exports as XLSX", ok_x and len(rows) >= 2, x.status_code)
    s.check(
        "the log row is consented/enrolled",
        any(res["screening_no"] in [str(c) for c in r] and any("enrol" in str(c) for c in r) for r in rows[1:]),
        rows[1:3],
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- audit (FR-AUD-01a/b/e)
    s = Stage("audit")
    t = time.perf_counter()
    reason = "consent"
    approached = picks[0]["pid"]
    page = pi.get(f"/studies/{TRIAL}/patients/{approached}")
    r = pi.post(f"/studies/{TRIAL}/patients/{approached}/reveal", data={"csrf": fd._csrf(page.text), "reason": reason})
    s.check("D-143: the study's investigator reveals a chart number (owner, 2026-11-09)", r.status_code == 200,
            r.status_code)  # fmt: skip
    page = crc.get(f"/studies/{TRIAL}/patients/{approached}")
    r = crc.post(f"/studies/{TRIAL}/patients/{approached}/reveal", data={"csrf": fd._csrf(page.text), "reason": reason})
    s.check("the coordinator reveals one chart number", r.status_code == 200, r.status_code)
    recs = _audit(box)
    ev = [r["event"] for r in recs]

    def det(r: dict[str, Any]) -> dict[str, Any]:
        d: dict[str, Any] = r.get("detail") or {}
        return d

    for jb in (fj, sj):
        seen = [det(r).get("to") for r in recs if r["event"] == "job.state" and r.get("job_id") == jb.job_id]
        s.check(f"01a: {jb.type} state changes in the audit", {"received", "done"} <= set(seen), seen)
        outs = {det(r).get("filename") for r in recs if r["event"] == "output" and r.get("job_id") == jb.job_id}
        s.check(
            f"01a: every {jb.type} output file in the audit", {o.filename for o in jb.outputs or []} <= outs, len(outs)
        )
    rv = [r for r in recs if r["event"] == "console.reveal_patient" and det(r).get("pid") == approached]
    pi_rv = [r for r in rv if r.get("actor") == "console:pi" and det(r).get("role") == "investigator"]
    s.check("01b: the investigator's reveal is recorded with the role", bool(pi_rv), len(rv))
    s.check(
        "01b: reveal with user, study, pid, reason and time",
        bool(rv)
        and rv[-1].get("actor") == "console:crc"
        and rv[-1].get("ruleset") == TRIAL
        and det(rv[-1]).get("reason") == reason
        and bool(rv[-1].get("ts")),
        rv[-1] if rv else None,
    )
    s.check(
        "01b: the box side records the same reveal",
        any(r["event"] == "screen.reveal" and det(r).get("pid") == approached for r in recs),
    )
    marks = [r for r in recs if r["event"] == "console.pi_mark"]
    s.check("01e: every investigator mark (3 + 1 replaced)", len(marks) >= 4, len(marks))
    s.check("01e: the coordinator's contact outcome", "console.contact_outcome" in ev)
    changes = [c for r in recs if r["event"] == "redcap.read" for c in det(r).get("status_changes", [])]
    s.check(
        "01e: registry status changes from REDCap, by pseudonym",
        [c["to"] for c in changes][-2:] == ["consented", "enrolled"] and not any(c["pid"] in mrns for c in changes),
        changes,
    )
    chain = verify(box.audit_dir)
    s.check("hash chain verifies", chain.ok, chain.errors[:3])
    trail = "\n".join(json.dumps(r, ensure_ascii=False) for r in recs)
    s.check("no patient name in the audit", not [n for n in names if n in trail][:1])
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 8: REDCap write-back (D-123)
    s = Stage("8 REDCap write-back")
    t = time.perf_counter()
    from fastapi.testclient import TestClient as SimClient

    sim = SimClient(res["sim"])
    token_a = next(k for k, v in res["sim"].state.sim.projects.items() if v["project"]["project_id"] == 101)

    def sim_rows() -> dict[str, dict[str, str]]:
        r = sim.post("/api/", data={"token": token_a, "content": "record", "format": "json", "type": "flat"})
        return {str(x["record_id"]): x for x in r.json()}

    before = sim_rows()
    page = crc.get(f"/studies/{TRIAL}/setup")
    form = {**rc_demo.LINK_FORM, "write_mode": "create", "write_form": "trialbox_screening"}
    r = crc.post(f"/studies/{TRIAL}/setup/redcap", data={"csrf": fd._csrf(page.text), **form})
    s.check("S21 saves the link with write-back on", r.status_code == 200 and 'data-testid="link-on"' in r.text)
    nos = {no: pid for pid, no, _at in h.store.screening_rows(TRIAL)}
    s.check("at least two screening numbers on the log", len(nos) >= 2, sorted(nos))
    log = crc.get(f"/studies/{TRIAL}/screening-log")
    r = crc.post(f"/studies/{TRIAL}/redcap-read", data={"csrf": fd._csrf(log.text), "back": "log"})
    s.check("Run now reports the write", 'data-testid="rc-write"' in r.text, r.status_code)
    after = sim_rows()
    by_no = {x["tb_screening_no"]: x for x in after.values() if x.get("tb_screening_no")}
    s.check("every screening number has its REDCap record", set(nos) <= set(by_no), sorted(set(nos) - set(by_no)))
    s.check(
        "TrialBox's instrument is filled for each",
        all(by_no[n]["tb_status"] and by_no[n]["tb_screen_date"] for n in nos if n in by_no),
        {n: by_no[n].get("tb_status") for n in nos if n in by_no},
    )
    enrolled_code = "4"
    s.check("the enrolled patient reads 4 (enrolled) in tb_status", by_no.get(res["screening_no"], {}).get("tb_status")
            == enrolled_code, by_no.get(res["screening_no"]))  # fmt: skip
    owned = {"tb_screen_date", "tb_status", "tb_status_date"}
    touched = [
        (rid, f)
        for rid, old in before.items()
        for f, v in old.items()
        if f not in owned and after.get(rid, {}).get(f) != v
    ]
    s.check("no REDCap-owned field changed", not touched, touched[:5])
    new_no = next((n for n in sorted(nos) if n != res["screening_no"]), "")
    new_rid = str(by_no.get(new_no, {}).get("record_id", ""))
    s.check("a new screening number got a new REDCap record", new_rid and new_rid not in before, (new_no, new_rid))
    # the coordinator records consent in REDCap; the next Run now reads it back and TrialBox's status follows
    day = h.today().isoformat()
    sim.post("/sim/records", json={"project_id": 101, "records": [{"record_id": new_rid, "consent_date": day}]})
    r = crc.post(f"/studies/{TRIAL}/redcap-read", data={"csrf": fd._csrf(r.text), "back": "log"})
    s.check(
        "next run: consent read back on the log",
        rc_demo.status_of(r.text, new_no).startswith(cat["registry.status.consented"]),
        rc_demo.status_of(r.text, new_no),
    )
    s.check("next run: tb_status follows (3, consented)", sim_rows().get(new_rid, {}).get("tb_status") == "3")
    r = crc.post(f"/studies/{TRIAL}/redcap-read", data={"csrf": fd._csrf(r.text), "back": "log"})
    s.check("a third run writes nothing new", len(sim_rows()) == len(after), len(sim_rows()))
    s.check("the write is in the audit", any(x["event"] == "redcap.write" for x in _audit(box)))
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 9: the data core (TB-PLAN-04 step 3)
    # REDCap off -> entries in TrialBox -> REDCap attached -> sync pushes TrialBox's fields -> a REDCap-side edit of
    # a TrialBox field is listed as a conflict -> resolved -> pushed; a PI's sheet with a name column imports with the
    # column dropped and the chart number pseudonymised. Project B of the simulator (longitudinal, DAGs), study RB.
    s = Stage("9 data core: REDCap off then on, conflicts, a PI's sheet")
    t = time.perf_counter()
    from rc_sim.app import load_projects

    api = h.bk.study_api
    proj_b = next(p for p in load_projects().values() if p["project"]["project_id"] == 202)
    admin = res["admin"]
    page = admin.get("/admin/redcap")
    r = admin.post("/admin/redcap", data={"csrf": fd._csrf(page.text), "token_ref": "rb", "url": rc_demo.SIM_URL,
                                          "token": proj_b["token"]})  # fmt: skip
    s.check("S36 saves the second project's connection", r.status_code == 200, r.status_code)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(proj_b["metadata"][0]))
    w.writeheader()
    w.writerows(proj_b["metadata"])
    forms_out = api("POST", "/studies/RB/forms/dictionary", {"csv": buf.getvalue(), "record_field": "rec_id",
                                                              "by": "crc1"})  # fmt: skip
    s.check("the data dictionary becomes TrialBox forms", bool(api("GET", "/studies/RB/forms")), forms_out)
    day = h.today().isoformat()
    api("PUT", "/studies/RB/data/RB0901", {"values": {"icf_dt": "2026-10-01", "tb_status": "3"}, "by": "crc1"})
    api("PUT", "/studies/RB/data/RB0950", {"values": {"tb_status": "2", "tb_screen_date": day}, "by": "crc1"})
    data = api("GET", "/studies/RB/data")
    s.check("REDCap off: entries kept in TrialBox alone", {"RB0901", "RB0950"} <= set(data.get("records") or []),
            data.get("records"))  # fmt: skip
    fields = ["icf_dt", "rand_yn", "withdrawn", "tb_status", "tb_screen_date"]
    api("PUT", "/studies/RB/sources/redcap", {"token_ref": "rb", "field_map": {f: f for f in fields},
        "owned": ["icf_dt", "rand_yn", "withdrawn"], "key_field": "tb_screening_no", "event": "screening_arm_1",
        "dag": "cgmh_linkou", "create": True, "by": "crc1"})  # fmt: skip
    r1 = api("POST", "/studies/RB/sync/redcap", {"by": "crc1"})
    first = {c["field"]: c for c in r1["conflicts"]}
    s.check("REDCap on: TrialBox's own earlier consent date vs REDCap's is listed, not forced",
            "icf_dt" in first and first["icf_dt"]["trialbox"] == "2026-10-01", r1["conflicts"])  # fmt: skip
    sim = SimClient(res["sim"])

    def rb_rows() -> list[dict[str, str]]:
        r = sim.post("/api/", data={"token": proj_b["token"], "content": "record", "format": "json", "type": "flat"})
        return [x for x in r.json() if x.get("redcap_event_name", "screening_arm_1") == "screening_arm_1"]

    by_no = {x["tb_screening_no"]: x for x in rb_rows() if x.get("tb_screening_no")}
    s.check(
        "sync pushes TrialBox's fields to REDCap", by_no.get("RB0901", {}).get("tb_status") == "3", by_no.get("RB0901")
    )
    s.check("a TrialBox record REDCap lacked is created there", by_no.get("RB0950", {}).get("tb_status") == "2",
            sorted(by_no))  # fmt: skip
    rec7 = str(by_no["RB0901"]["rec_id"])
    edit = {"rec_id": rec7, "redcap_event_name": "screening_arm_1", "tb_status": "5"}
    sim.post("/sim/records", json={"project_id": 202, "records": [edit]})
    r2 = api("POST", "/studies/RB/sync/redcap", {"by": "crc1"})
    s.check("a REDCap-side edit of a TrialBox field is listed as a conflict, not taken",
            [(c["field"], c["theirs"]) for c in r2["conflicts"]] == [("tb_status", "5")] and r2["pushed"] == 0,
            r2)  # fmt: skip
    open_c = api("GET", "/studies/RB/conflicts")
    for c in open_c:
        keep = "theirs" if c["field"] == "icf_dt" else "trialbox"
        api("POST", f"/studies/RB/conflicts/{c['id']}", {"keep": keep, "by": "crc1"})
    r3 = api("POST", "/studies/RB/sync/redcap", {"by": "crc1"})
    by_no = {x["tb_screening_no"]: x for x in rb_rows() if x.get("tb_screening_no")}
    s.check("resolved: no open conflict, TrialBox's status pushed back",
            api("GET", "/studies/RB/conflicts") == [] and by_no["RB0901"].get("tb_status") == "3", r3)  # fmt: skip
    rec = api("GET", "/studies/RB/data")
    s.check("the chosen consent date is REDCap's", "2026-10-02" in json.dumps(rec), "icf_dt")
    sheet = "カルテ番号,氏名,同意日\n00123,山田太郎,2026-11-01\n,佐藤,2026-11-02\n"
    imp = api("POST", "/studies/RB/import/sheet", {"name": "pi", "csv": sheet, "columns": {"同意日": "icf_dt"},
                                                    "mrn_column": "カルテ番号", "by": "crc1"})  # fmt: skip
    s.check("a PI's sheet: the name column is dropped", imp.get("dropped") == ["氏名"], imp.get("dropped"))
    s.check("a PI's sheet: a row without a chart number is refused and listed", len(imp.get("refused") or []) == 1,
            imp.get("refused"))  # fmt: skip
    dump = json.dumps(api("GET", "/studies/RB/data"), ensure_ascii=False)
    s.check("a PI's sheet: the chart number is pseudonymised, no name stored",
            imp.get("taken") == 1 and "00123" not in dump and "山田" not in dump, imp)  # fmt: skip
    seen_events = {str(x["event"]) for x in _audit(box)}
    s.check("sync, resolve and import are in the audit", {"data.sync", "data.resolve", "data.import"} <= seen_events)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    stages.append(_stage10(res, api, crc, lang, mrns, box))
    stages.append(_stage11(res, api, crc, pi, lang, mrns, box))
    stages.append(_stage12(res, crc, pi, lang, box))
    stages.append(_stage13(work, box, gout_coh_numbers(box, lst["cohort_new"])))
    stages.append(_stage14(work, box))

    # ---------------------------------------------------------------- FR-REP-02: byte-identical re-run
    s = Stage("re-run (FR-REP-02)")
    t = time.perf_counter()
    from tb_contracts import JobCreate

    # the pasted-criteria FEAS job also compiled and wrote the ruleset (a side effect, never repeated): re-run the
    # report as the investigator would re-request it, on the approved version
    again = box.orch.create(JobCreate(type="FEAS", ruleset=TRIAL, requested_by="pi@hospa.test"))
    box.orch.drain()
    again = box.orch.db.get(again.job_id)
    s.check("FEAS on the approved ruleset", again is not None and again.state == "done", again and again.error)
    # with the GPU pair only FEAS (no model) is re-run: a second SCREEN would double the paid card time, and batched
    # model answers are not bit-reproducible (as spark_e2e's cascade check on GB10); the stub gate re-runs both
    for jb in [x for x in (again, sj if PAIR is None else None) if x is not None]:
        rr = rerun(box.orch, jb.job_id)
        s.check(
            f"{jb.type} re-run byte-identical", rr.identical, [f for f in rr.files if not f["same"]][:3] or rr.error
        )
    s.seconds = time.perf_counter() - t
    stages.append(s)
    # after the re-run: the opt-out it registers must not touch the jobs the re-run reproduces (D-82)
    stages.append(_stage15(res, pi, crc, password, lang, mrns, box))
    stages.append(_stage16(res, pi, crc, password, lang, box))

    total = time.perf_counter() - t0
    budget = Stage("runtime")
    budget.check(f"whole run within {BUDGET_S // 60} min", total <= BUDGET_S, f"{total:.1f} s")
    stages.append(budget)
    return {
        "ok": all(st.ok for st in stages),
        "stages": stages,
        "seconds": round(total, 1),
        "chain_seconds": round(t_chain, 1),
        "jobs": {"feas": fj.job_id, "screen": sj.job_id},
        "result": res,
    }


def report(out: dict[str, Any]) -> str:
    lines = []
    for st in out["stages"]:
        lines.append(f"{'PASS' if st.ok else 'FAIL'}  {st.name}  ({st.seconds:.1f} s)")
        for what, ok, detail in st.checks:
            lines.append(f"   {'ok ' if ok else 'BAD'} {what}" + ("" if ok else f"  -> {detail}"))
    lines.append(
        f"e2e_simple {'PASSED' if out['ok'] else 'FAILED'} in {out['seconds']} s (chain {out['chain_seconds']} s)"
    )
    return "\n".join(lines)


def missing_prerequisites() -> list[str]:
    """What the run needs from outside the Python venv and lacks, named before anything starts (DATA-019): the CQL
    translator's ``quick-*.jar``, which holds ``FHIRHelpers-4.0.1.cql``. The run compiles with the in-process fake
    translator (``tests/inproc_box.py``), so it needs no Java and no ``cql-to-elm-cli`` jar (the demo image has
    neither). Without the jar the run used to fail late, as a FEAS job "failed in compiling"."""
    import zipfile

    from criteria_compiler.compile_cql import translator

    lib = translator._lib_dir()
    try:
        translator.fhirhelpers_source()
    except (FileNotFoundError, KeyError, OSError, zipfile.BadZipFile) as exc:
        return [f"the CQL translator jars are missing or broken in {lib} ({exc}): run `make jvm-deps` "
                "(or set TB_CQL_TRANSLATOR_LIB to a folder that holds quick-*.jar)"]  # fmt: skip
    return []


def prepare_root() -> None:
    """Mark ``TB_TEST_ROOT`` as a test root before anything is made in it (DATA-019): ``make e2e-simple`` puts the
    work folder inside the root, and a root that holds that folder and no marker is refused by ``pglocal`` (the
    shared cluster's home). A root that already holds other files and no marker is still refused here."""
    from tools import pglocal

    env = os.environ.get("TB_TEST_ROOT")
    if env:
        pglocal.mark_test_root(Path(env))


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import adopt_site_tz

    from tools.pglocal import scratch_root

    adopt_site_tz()  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_E2E_DIR") or scratch_root() / "tb-e2e-simple"))
    ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--json", type=Path, help="also write the checks as JSON here")
    a = ap.parse_args(argv)
    missing = missing_prerequisites()
    for m in missing:
        print(f"e2e_simple: {m}", file=sys.stderr)
    if missing:
        return 2
    try:
        prepare_root()
    except ValueError as exc:
        print(f"e2e_simple: {exc}", file=sys.stderr)
        return 2
    import logging

    logging.disable(logging.INFO)  # the in-process services log every request; the checks are the output
    if a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True)
    out = run(a.dir, os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12), a.lang)
    print(report(out))
    if a.json:
        a.json.write_text(
            json.dumps(
                {
                    "ok": out["ok"],
                    "seconds": out["seconds"],
                    "stages": [
                        {"name": st.name, "ok": st.ok, "seconds": round(st.seconds, 2), "checks": st.checks}
                        for st in out["stages"]
                    ],
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
