"""``e2e_simple``: the one build gate (SRS FR-OPS-11, TB-PLAN-02 "How it is tested", TB-DS-04 §3.4.1, D-111).

One synthetic hospital (the ``ci`` profile: two sites of 2,500 patients, notes in JA, zh-TW and EN), stub model, no
network, no secrets, run in process:

    criteria pasted -> FEAS report (funnel) -> the investigator approves -> SCREEN -> the list (GZQO) and the cohort
    list (GOUT-COH) -> marks -> N1/N2 mail -> REDCap simulator record -> Run now -> screening log (HTML and XLSX)
    -> write-back of TrialBox's instrument -> consent in REDCap -> read back on the next run (D-123)
    -> the data core with REDCap off and on (stage 9) -> built-in forms, entry, history, ODM / REDCap CSV (stage 10)
    -> the trial lifecycle: enrolled, visit due, overdue, done, AEs, withdrawn; three counts agree (stage 11)

and each stage is checked against something it did not compute itself: the generator's own counts, a recount from
the hospital CSVs, the sent mail, the hash-chained audit log and a byte-identical re-run of the FEAS and SCREEN jobs.

    python -m tools.e2e_simple [--dir DIR] [--lang ja|zh-TW|en] [--json]      # exit 0 = every check passed
    make e2e-simple

``tests/integration/test_e2e_simple.py`` runs the same function under pytest; ``.github/workflows/trialbox-e2e.yml``
runs it on every pull request that touches ``trialbox/``.
"""

from __future__ import annotations

import argparse
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

    r = save("tb_consent", {"ic_date": "2026-11-02", "ic_copy": "1"})
    s.check("a required field missing is refused, in the page's language",
            'data-testid="why-ic_version"' in r.text and cat["dc.why.required"].split("{label}")[-1] in r.text
            and not any(k.startswith("ic_") for k in api("GET", f"/studies/{rs}/data")["records"].get(no, {})),
            r.status_code)  # fmt: skip
    consent = {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1", "ic_by": "KT"}
    r = save("tb_consent", consent)
    s.check("the consent is saved; the history page follows", 'data-testid="entry-saved"' in r.text, r.url)
    visit = {
        "vs_status": "1",
        "vs_date": "2026-11-09",
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
    s.check("N2 lists the overdue visit by pseudonym, never the screening number",
            f"{pid[:8]} " in body or f"{pid[:8]}（" in body or f"{pid[:8]}(" in body, body[-300:])  # fmt: skip
    s.check(
        "N2 carries no screening number and no chart number",
        bool(body) and no not in body and not any(re.search(rf"(?<!\d){m_}(?!\d)", body) for m_ in mrns),
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
    ref = date.fromisoformat(rep["snapshot"])
    adults = {p["mrn"] for p in patients if _age(p["birth_date"], ref) >= 18}
    gout = {
        r["mrn"] for r in csv.DictReader((hosp / "diagnosis.csv").open(encoding="utf-8")) if r["icd10"].startswith(GOUT)
    }
    s.check("start = every patient seen in 36 months", raw["start_n"] == len(patients), raw["start_n"])
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
    s.check("stub model ran, single judge", j["judge_model"] == "stub" and j["verifier_model"] is None, j)
    s.check("no note-based exclusion without two models agreeing", j["note_block"] == "never" and not j["may_block"], j)
    fun = dict((k, v) for k, v in scr["funnel"])
    s.check("funnel S0 >= S1 >= S3 >= S4 > 0", fun["S0"] >= fun["S1"] >= fun["S3"] >= fun["S4"] > 0, fun)
    s.check("listed = high + review", scr["listed"] == scr["tiers"]["high"] + scr["tiers"]["review"], scr["tiers"])
    sp = scr.get("provenance") or {}
    s.check(
        "FR-REP-01 provenance names the model and prompt",
        sp.get("models") == ["stub"] and sp.get("prompt_versions"),
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
    s.check("mail carries no screening number", lst["screening_no"] not in body, lst["screening_no"])
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

    today = h.clock().date()
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
    s.check("D-133: the investigator may not reveal a chart number (role text)", r.status_code == 403, r.status_code)
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
    day = h.clock().date().isoformat()
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
    day = h.clock().date().isoformat()
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
    for jb in [x for x in (again, sj) if x is not None]:
        rr = rerun(box.orch, jb.job_id)
        s.check(
            f"{jb.type} re-run byte-identical", rr.identical, [f for f in rr.files if not f["same"]][:3] or rr.error
        )
    s.seconds = time.perf_counter() - t
    stages.append(s)

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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_E2E_DIR", "/tmp/tb-e2e-simple")))
    ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--json", type=Path, help="also write the checks as JSON here")
    a = ap.parse_args(argv)
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
