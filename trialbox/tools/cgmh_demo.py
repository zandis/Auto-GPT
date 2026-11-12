"""The CGMH clinician-PoC scenarios on the Taiwanese rheumatology site (T-504), walked through the console.

Stub model only, no network, no API key, synthetic data only (``tools.synth_hospital --profile tw-ra``: 1,500
patients of a rheumatology clinic, Asia/Taipei, notes in Traditional Chinese and English).

    python -m tools.cgmh_demo --dir /tmp/tb-cgmh --walk list --lang zh-TW      # T2
    python -m tools.cgmh_demo --dir /tmp/tb-cgmh --walk amend --lang ja        # T1, in any of ja, zh-TW, en
    python -m tools.cgmh_demo --dir /tmp/tb-cgmh --walk registry --lang zh-TW  # T3

* ``list`` (T2): the interventional trial RA-JAK (approved v1.0.0, protocol ``RA-JAK_試驗計畫書_v1``). The
  coordinator asks for the patient list; the investigator (P12345) opens it. A patient whose herpes zoster or
  venous thromboembolism is coded is not listed; one whose only mention is in a note is listed for a person to read.
* ``amend`` (T1): the GZQO trial amended. The coordinator pastes the criteria with the BMI cut lowered from 27 to 25
  and one exclusion added (aged 80 or older). The investigator opens S20: the "changes since v1.0.0" box lists both,
  every changed row is opened and given a label in the page's language, and Approve all makes v1.1.0. The new list
  gains the BMI 25-27 patients and loses the patients aged 80 or older.
* ``registry`` (T3): the investigator-initiated GOUT-COH registry. The coordinator asks for the clinics' cohort
  list; the investigator takes one patient on (Approach, which gives the registry number), names themselves and the
  coordinator on the delegation log and switches REDCap prefill on with the acknowledgement; the coordinator reads
  the CRF's data dictionary, saves the item map, drafts the patient's visit from the hospital record, confirms each
  value, signs with the password and sends; every sent value reads back from REDCap (the built-in simulator) equal
  to the record.

The tools.demo hookup (one command for the demo image) is T-505b's; until then this script is the walk.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import secrets
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import feas_demo as fd  # noqa: E402
from tools import list_demo as ld  # noqa: E402

PROFILE = "tw-ra"
SITE_TW: dict[str, Any] = {
    "site": {
        "id": "DEMO-T",
        "name": "示範醫院T（合成）",
        "tz": "Asia/Taipei",
        "locale": "zh-TW",
        "contact": "crc1@hospa.test",
    }
}
PI = "P12345"
TRIAL, AMENDED, REGISTRY = "RA-JAK", "GZQO", "GOUT-COH"
CLINICS = ld.COHORT_CLINICS
BMI_FROM = "Body mass index (BMI) ≥27 kg/m² at screening."
BMI_TO = "Body mass index (BMI) ≥25 kg/m² at screening."
ADDED = "Aged 80 years or older at screening."
WALKS = ("list", "amend", "registry")
# the short label a site gives a changed criterion, per page language (D-120, D-309); English pages need none
NEW_LABELS = {
    "ja": {"bmi": "BMI 25以上", "age": "80歳以上"},
    "zh-TW": {"bmi": "BMI ≥25", "age": "年滿80歲"},
    "en": {"bmi": "BMI ≥25", "age": "Aged 80 or older"},
}
SIM_URL = "inproc://rc-sim"
# a small gout registry CRF in the REDCap simulator (synthetic): demographics, uric acid and two history items
COH_CRF: list[dict[str, str]] = [
    {"field_name": "record_id", "form_name": "demographics", "field_type": "text", "field_label": "Record ID"},
    {"field_name": "tb_screening_no", "form_name": "demographics", "field_type": "text",
     "field_label": "Registry number"},
    {"field_name": "brthdat", "form_name": "demographics", "field_type": "text", "field_label": "Birth date",
     "text_validation_type_or_show_slider_number": "date_ymd", "field_label:zh-TW": "出生日期"},
    {"field_name": "sex", "form_name": "demographics", "field_type": "radio", "field_label": "Sex",
     "select_choices_or_calculations": "1, Male | 2, Female"},
    {"field_name": "urate", "form_name": "baseline", "field_type": "text", "field_label": "Serum uric acid (mg/dL)",
     "text_validation_type_or_show_slider_number": "number"},
    {"field_name": "mh_gout", "form_name": "baseline", "field_type": "yesno", "field_label": "History of gout"},
    {"field_name": "cm_allo", "form_name": "baseline", "field_type": "yesno", "field_label": "Allopurinol"},
    {"field_name": "comments", "form_name": "baseline", "field_type": "notes", "field_label": "Comments"},
]  # fmt: skip
COH_MAP: list[dict[str, Any]] = [
    {"item": "brthdat", "cdash": "DM.BRTHDAT", "source": "patient", "what": "birth_date"},
    {"item": "sex", "cdash": "DM.SEX", "source": "patient", "what": "sex", "sex_codes": {"male": "1", "female": "2"}},
    {"item": "urate", "cdash": "LB.LBORRES", "test": "URATE", "source": "observation", "what": "value",
     "codes": ["3084-1"], "system": "http://loinc.org", "unit": "mg/dL", "window_days": 3650},
    {"item": "mh_gout", "cdash": "MH.MHOCCUR", "source": "condition", "what": "presence", "codes": ["M10"],
     "window_days": 0},
    {"item": "cm_allo", "cdash": "CM.CMOCCUR", "source": "medication", "what": "presence", "codes": ["M04AA01"],
     "window_days": 0},
    {"item": "comments"},
]  # fmt: skip
TARGET = {"token_ref": "edc", "key_field": "tb_screening_no", "id_field": "record_id"}


def start(work: Path, password: str, lang: str) -> dict[str, Any]:
    """The tw-ra site's box (synthetic site and lake cached in ``work``, the box and console fresh) and the three
    accounts signed in."""
    os.environ["TB_TZ"] = SITE_TW["site"]["tz"]  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    box, client, repo, summary = fd.build_site(work, PROFILE, SITE_TW)
    clock = ld.Clock(box.today[0], ld.site_tz_of(box))
    app = ld.console(work, box, client, repo, password, clock)
    out = {"box": box, "app": app, "h": app.state.helpers, "summary": summary, "clock": clock, "work": work}
    for who in ("crc", "pi", "admin"):
        out[who] = ld.sign_in(app, who, password, lang, PI)
    states = json.loads((work / "synth" / PROFILE / "states.json").read_text(encoding="utf-8"))
    out["states"] = states
    out["mrn"] = {pid_of(m): m for m in states}
    return out


def pid_of(mrn: str) -> str:
    from tb_common.crypto import pid_for_mrn

    return pid_for_mrn(fd.KEY, mrn)


def screen(s: dict[str, Any], rs: str, pract: str = "") -> dict[str, Any]:
    """The coordinator asks for a study's list (SCREEN); returns the console's candidate list (rows by pid)."""
    crc, box = s["crc"], s["box"]
    form = crc.get(f"/pilot/request?ruleset={rs}")
    r = crc.post(
        "/pilot/request",
        data={"csrf": fd._csrf(form.text), "kind": "SCREEN", "ruleset": rs, "pract": pract},
        follow_redirects=False,
    )
    assert r.status_code == 303, (rs, r.status_code, r.text[-400:])
    job = box.orch.db.get(r.headers["location"].rsplit("/", 1)[-1])
    assert job is not None and job.state == "done", (rs, job and job.state, job and job.error)
    wk = s["h"].week_bundle(None, rs)
    assert wk is not None and wk["job"].job_id == job.job_id
    return {"job": job, "rows": {str(r["pid"]): r for r in (wk["cl"] or {}).get("rows") or []}}


def criteria_text(ruleset: str, replace: dict[str, str] | None = None, added: tuple[str, ...] = ()) -> str:
    text = fd.pasted_criteria(ruleset)
    for a, b in (replace or {}).items():
        assert a in text, a
        text = text.replace(a, b)
    n = len(re.findall(r"^\d+\. ", text.split("除外基準", 1)[-1], re.M))
    return text.rstrip("\n") + "".join(f"\n{n + i}. {t}" for i, t in enumerate(added, 1)) + "\n"


def approve(s: dict[str, Any], job_id: str, lang: str, labels: dict[str, str]) -> dict[str, Any]:
    """The investigator on S20: open every amber row, give each unlabelled row its label, Approve all."""
    pi = s["pi"]
    page = ld.ok(pi.get(f"/pilot/jobs/{job_id}/approval"), "S20")
    changes = re.search(r'data-testid="changes">(.*?)</section>', page.text, re.S)
    ambers = re.findall(r'data-testid="open-([A-Z0-9-]+)"', page.text)
    for cid in ambers:
        page = ld.ok(pi.get(f"/pilot/jobs/{job_id}/approval?open={cid}"), f"open {cid}")
    missing = re.findall(r'data-testid="label-missing-([A-Z0-9-]+)"', page.text)
    for cid in missing:
        r = pi.post(
            f"/pilot/jobs/{job_id}/approval/label",
            data={"csrf": fd._csrf(page.text), "crit": cid, "text": labels.get(cid) or cid},
            follow_redirects=False,
        )
        assert r.status_code == 303, (cid, r.status_code, r.text[-300:])
        page = ld.ok(pi.get(f"/pilot/jobs/{job_id}/approval"), "S20 after label")
    assert 'data-testid="label-missing-' not in page.text
    r = pi.post(
        f"/pilot/jobs/{job_id}/approve", data={"csrf": fd._csrf(page.text), "confirm": "yes"}, follow_redirects=False
    )
    assert r.status_code == 303, (r.status_code, _why(r.text))
    return {"changes": changes.group(1) if changes else "", "amber": ambers, "labelled": missing, "html": page.text}


def _why(html: str) -> str:
    """A refused page's message, without the page around it."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    m = re.search(r"<main.*?</main>", body, re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", m.group(0) if m else body).split())[:600]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def ages(site: Path, on: date) -> dict[str, int]:
    out = {}
    for r in _rows(site / "patient.csv"):
        b = date.fromisoformat(r["birth_date"][:10])
        out[r["mrn"]] = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
    return out


# ------------------------------------------------------------------------------------------------ T2
def walk_list(s: dict[str, Any], lang: str) -> dict[str, Any]:
    from tools.synth import rajak

    res = screen(s, TRIAL)
    page = ld.ok(s["pi"].get(f"/studies/{TRIAL}/week?list=all"), "RA-JAK list")
    listed = {s["mrn"][p] for p in res["rows"]}
    st = s["states"]
    coded = {m for m in listed if st[m].get("zoster") == "coded_recent" or str(st[m].get("vte")).startswith("coded")}
    note_only = {
        m
        for m, v in st.items()
        if v.get("archetype") == "rajak" and (v["zoster"] == "note_recent" or v["vte"] == "note_only")
    }
    first = next(iter(sorted(res["rows"])), "")
    s5 = ld.ok(s["pi"].get(f"/studies/{TRIAL}/patients/{first}"), "S5").text if first else ""
    return {
        "listed": listed,
        "coded_listed": coded,
        "note_only_listed": note_only & listed,
        "gold_candidates": {m for m, v in st.items() if v.get("archetype") == "rajak" and rajak.coded_candidate(v)},
        "list_html": page.text,
        "patient_html": s5,
        "rows": res["rows"],
    }


# ------------------------------------------------------------------------------------------------ T1
def walk_amend(s: dict[str, Any], lang: str) -> dict[str, Any]:
    box, crc, pi = s["box"], s["crc"], s["pi"]
    before = screen(s, AMENDED)
    marked = sorted(before["rows"])[0]  # a patient the investigator took on before the amendment
    page = pi.get(f"/studies/{AMENDED}/week?list=all&pid={marked}")
    r = pi.post(
        f"/studies/{AMENDED}/patients/{marked}/mark",
        data={"csrf": fd._csrf(page.text), "mark": "approach", "back": "list:all"},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, _why(r.text))
    form = crc.get("/pilot/protocol")
    text = criteria_text(AMENDED, {BMI_FROM: BMI_TO}, (ADDED,))
    r = ld.ok(
        crc.post("/pilot/protocol", data={"csrf": fd._csrf(form.text), "ruleset": AMENDED, "criteria": text}),
        "paste",
    )
    job = box.orch.db.get(r.url.path.rsplit("/", 1)[-1])
    assert job is not None and job.state == "awaiting_approval", job and job.state
    words = NEW_LABELS[lang]
    labels = {"GZQO-INC-03": words["bmi"]}
    page = ld.ok(s["pi"].get(f"/pilot/jobs/{job.job_id}/approval"), "S20")
    added = sorted(set(re.findall(r'id="(GZQO-EXC-\d+)"', page.text)) - _ids(AMENDED, "EXC"))
    labels |= {cid: words["age"] for cid in added}
    ap = approve(s, job.job_id, lang, labels)
    infos = {x.id: x for x in s["h"].bk.rulesets()}
    after = screen(s, AMENDED)
    return {
        "job": job,
        "approval": ap,
        "added": added,
        "version": infos[AMENDED].version,
        "before": {s["mrn"][p] for p in before["rows"]},
        "after": {s["mrn"][p] for p in after["rows"]},
        "after_rows": after["rows"],
        "marked": s["mrn"][marked],
        "mark_after": getattr(s["h"].store.latest_marks(AMENDED).get(marked), "mark", None),
        "list_html": ld.ok(pi.get(f"/studies/{AMENDED}/week?list=all"), "list after").text,
    }


def _ids(rs: str, part: str) -> set[str]:
    return {p.stem for p in (ROOT / "rulesets" / rs / "ir").glob(f"{rs}-{part}-*.json")}


# ------------------------------------------------------------------------------------------------ T3
def walk_registry(s: dict[str, Any], lang: str, password: str) -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from rc_bridge.client import RedcapClient
    from rc_sim.app import create_app, register_inproc

    h, crc, pi, admin = s["h"], s["crc"], s["pi"], s["admin"]
    res = screen(s, REGISTRY, CLINICS)
    cohort = ld.ok(pi.get(f"/studies/{REGISTRY}/cohort"), "cohort list")
    members = re.findall(r'data-testid="member-([^"]+)"', cohort.text)  # new members: every criterion met
    assert res["rows"], "nobody on the registry's list"
    # a new member if there is one, else a patient the list asks a person to check (one criterion unknown)
    pid = next((p for p in sorted(res["rows"]) if p[:8] in members), sorted(res["rows"])[0])
    page = pi.get(f"/studies/{REGISTRY}/patients/{pid}")
    r = pi.post(
        f"/studies/{REGISTRY}/patients/{pid}/mark",
        data={"csrf": fd._csrf(page.text), "mark": "approach", "back": "patient"},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[-300:])
    no = h.store.screening_no(REGISTRY, pid)
    assert no, "no registry number on Approach"
    visit = h.today()

    sim = create_app()
    register_inproc(sim)
    sc = TestClient(sim)
    made = sc.post("/sim/projects", json={"title": "GOUT-COH CRF", "metadata": COH_CRF}).json()
    rc = RedcapClient(SIM_URL, made["token"])
    rc.import_records([{"record_id": "1", "tb_screening_no": no}])
    page = ld.ok(admin.get("/admin/redcap"), "S36")
    ld.ok(
        admin.post(
            "/admin/redcap",
            data={"csrf": fd._csrf(page.text), "token_ref": "edc", "url": SIM_URL, "token": made["token"]},
        ),
        "S36 save",
    )
    # the delegation log: the steward wrote the investigator's PI entry (the demo seed, D-380); only the log's PI
    # switches prefill on, and the PI adds the CRC
    for who, role, extra in (("crc", "crc", {"training_day": visit.isoformat()}),):
        lg = pi.post(
            f"/studies/{REGISTRY}/team",
            data={"csrf": fd._csrf(pi.get("/home").text), "username": who, "role": role, "start": visit.isoformat(),
                  **extra},
            follow_redirects=False,
        )  # fmt: skip
        assert lg.status_code == 303, (who, lg.status_code, _why(lg.text))
    sw = {
        "csrf": fd._csrf(pi.get(f"/studies/{REGISTRY}/edc").text),
        "on": "1",
        "kind": "sponsor_letter",
        "reference": "IIT-GOUTCOH-001",
        "ack_date": visit.isoformat(),
        "reentry_pages": "30",
        "reentry_accuracy": "98.6",
    }
    r = pi.post(f"/studies/{REGISTRY}/edc/switch", data=sw, follow_redirects=False)
    assert r.status_code == 303, (r.status_code, _why(r.text))
    mp = crc.get(f"/studies/{REGISTRY}/edc/map")
    r = crc.post(
        f"/studies/{REGISTRY}/edc/dictionary",
        data={"csrf": fd._csrf(mp.text), "token_ref": "edc", "record_field": "record_id"},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[-300:])
    api = TestClient(s["app"])
    tok = api.post("/api/v1/session", json={"username": "crc", "password": password}).json()["token"]
    hd = {"authorization": f"Bearer {tok}"}
    r = api.put(f"/api/v1/studies/{REGISTRY}/edc/map", json={"items": COH_MAP, "target": TARGET}, headers=hd)
    assert r.status_code == 200, r.text[:300]
    home = crc.get(f"/studies/{REGISTRY}/edc").text
    r = crc.post(
        f"/studies/{REGISTRY}/edc/drafts",
        data={"csrf": fd._csrf(home), "record": no, "visit_date": visit.isoformat()},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, sorted(set(re.findall(r"edc\.[a-z_.]+", r.text))))
    d = {x["item"]: x for x in h.bk.study_api("GET", f"/studies/{REGISTRY}/edc/drafts?record={no}")}
    drafted = {k: v["value"] for k, v in d.items() if v["state"] == "drafted"}
    rev = crc.get(f"/studies/{REGISTRY}/edc/review/{no}")
    c = fd._csrf(rev.text)
    for k in drafted:
        crc.post(f"/studies/{REGISTRY}/edc/decide/{d[k]['id']}", data={"csrf": c, "action": "confirm", "record": no})
    shown = crc.get(f"/studies/{REGISTRY}/edc/review/{no}").text
    m = re.search(r'name="seen" value="([^"]*)"', shown)
    sign = {"csrf": c, "record": no, "password": password, "meaning_ack": "1", "seen": m.group(1) if m else ""}
    signed = crc.post(f"/studies/{REGISTRY}/edc/sign", data=sign, follow_redirects=False)
    assert signed.status_code == 303, (signed.status_code, signed.text[-300:])
    sent = crc.post(f"/studies/{REGISTRY}/edc/send", data={"csrf": c, "record": no}, follow_redirects=False)
    assert sent.status_code == 303, (sent.status_code, sent.text[-300:])
    return {
        "pid": pid,
        "mrn": s["mrn"][pid],
        "no": no,
        "members": members,
        "cohort_html": cohort.text,
        "drafts": d,
        "drafted": drafted,
        "readback": rc.records()[0],
        "review_html": shown,
    }


def run(work: Path, password: str, walk: str, lang: str) -> dict[str, Any]:
    s = start(work, password, lang)
    if walk == "list":
        return {**s, **walk_list(s, lang)}
    if walk == "amend":
        return {**s, **walk_amend(s, lang)}
    return {**s, **walk_registry(s, lang, password)}


def main(argv: list[str] | None = None) -> int:
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR") or scratch_root() / "tb-cgmh-demo"))
    ap.add_argument("--walk", default="list", choices=WALKS)
    ap.add_argument("--lang", default="zh-TW", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--fresh", action="store_true", help="delete --dir first")
    a = ap.parse_args(argv)
    if a.fresh and a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    res = run(a.dir, password, a.walk, a.lang)
    good = True
    if a.walk == "list":
        good = bool(res["listed"]) and not res["coded_listed"]
        print(f"{TRIAL} list: {len(res['listed'])} patients; coded zoster/VTE listed: {len(res['coded_listed'])}; "
              f"note-only zoster/VTE kept for review: {len(res['note_only_listed'])}")  # fmt: skip
    elif a.walk == "amend":
        gained, lost = res["after"] - res["before"], res["before"] - res["after"]
        good = res["version"] == "1.1.0" and "GZQO-INC-03" in res["approval"]["changes"] and bool(res["added"])
        changed = ", ".join(["GZQO-INC-03", *res["added"]])
        labelled = ", ".join(res["approval"]["labelled"]) or "-"
        print(f"{AMENDED} v{res['version']}: changed {changed}; labelled {labelled}; list +{len(gained)} -{len(lost)}")
    else:
        rb = res["readback"]
        good = bool(res["drafted"]) and all(rb.get(k) == v for k, v in res["drafted"].items())
        print(f"{REGISTRY} member {res['no']}: drafted {sorted(res['drafted'])}; read back equal: {good}")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
