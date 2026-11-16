"""The steps of ``journeys.yaml`` (T-315a, D-448): one function per step id, doing what the step's "do" says through
the console's pages, as the person would, and asserting what its "expect" says. Steps the PoC scripts already walk
(T-508) are reused from ``tests/integration/test_poc_scripts.py``. A step with ``langs`` checks its text in each
language from the console's own catalogues, so a missing or English-only string fails here."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from tests.e2e.journeys import journey_site as js
from tests.integration import test_poc_scripts as poc
from tools import cgmh_demo as cd

Site = js.Site
Step = Callable[[Site, dict[str, Any]], None]
STEPS: dict[str, Step] = {}
RS = "RA-JAK"


def step(sid: str) -> Callable[[Step], Step]:
    def put(fn: Step) -> Step:
        STEPS[sid] = fn
        return fn

    return put


def tr(lang: str, key: str, **kw: Any) -> str:
    from console.i18n import translate

    return translate(lang, key, **kw)


def user(key: str) -> str:
    return js.ACCOUNTS[key][0]


def in_langs(s: Site, key: str, path: str, want: Callable[[str], str], langs: list[str]) -> None:
    """The page at ``path`` shows ``want(lang)`` in each language of the step; the account ends in English."""
    c = s.c[user(key)]
    for lang in langs:  # each language has its own text in the catalogue, not the English fallback
        assert lang == "en" or want(lang) != want("en"), (lang, want(lang))
    for lang in [*langs, "en"]:
        r = c.post("/lang", data={"csrf": poc.csrf(c.get("/help").text), "lang": lang, "back": "/help"})
        assert r.status_code == 200, (lang, r.status_code)
        page = js.text(c.get(path).text)
        assert want(lang) in page, (lang, path, want(lang), page[:400])


def first_sign_in(s: Site, key: str) -> Any:
    """The first sign-in of an issued account: password and enrolment code, the authenticator set up from the key
    on the page, the forced password change (D-279), then a sign-in with the own password and a new code."""
    name = user(key)
    got = s.issued[name]
    c = s.sign_in(name, got["password"], got["enrolment code"])
    acct = c.get("/home")
    assert acct.url.path == "/account", acct.url  # a password someone else set is replaced first
    r = c.post("/account/password", data={"csrf": poc.csrf(acct.text), "current": got["password"],
                                          "new": js.OWN_PW, "again": js.OWN_PW})  # fmt: skip
    assert r.url.path == "/login"  # the change signs the account out everywhere
    c = s.sign_in(name, js.OWN_PW)
    home = c.get("/home")
    assert home.status_code == 200 and home.url.path not in ("/login", "/account"), home.url
    return home


def events(s: Site, name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(s.box.audit_dir.glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e.get("event") == name]


def spare(s: Site, n: int) -> str:
    """The n-th RA-JAK candidate (by the list's own order) that no other step uses."""
    used = {v for v in s.state.values() if isinstance(v, str)}
    used |= set(s.state.get(f"order.{RS}", [])[:8])
    free = [str(r["pid"]) for r in poc.rows(s, RS) if str(r["pid"]) not in used]
    return free[-1 - n]


# ---------------------------------------------------------------------------------------------- administrator
@step("J-ADM-01")
def _adm_sign_in(s: Site, st: dict[str, Any]) -> None:
    name = user("it")
    for lang in st["langs"]:  # the front door in the browser's language, before any account is known
        c = TestClient(s.served)
        page = c.get("/login", headers={"accept-language": lang})
        assert tr(lang, "login.title") in js.text(page.text), lang
        tok = re.search(r'name="login_csrf" value="([^"]+)"', page.text)
        assert tok
        r = c.post("/login", headers={"accept-language": lang},
                   data={"username": name, "password": s.issued[name]["password"], "login_csrf": tok.group(1)})  # fmt: skip
        assert r.url.path == "/login/totp" and tr(lang, "totp.enrol.title") in js.text(r.text), (lang, r.url)
    home = first_sign_in(s, "it")
    assert home.url.path == "/home"


@step("J-ADM-02")
def _adm_held_night(s: Site, st: dict[str, Any]) -> None:
    from adapter.pipeline import AdapterConfig, run_ingest

    from tests.inproc_box import ROOT
    from tools import pglocal

    lake = s.work / "lake"
    served = (lake / "CURRENT").read_text(encoding="utf-8").strip()
    night = s.work / "night-without-lab"
    shutil.rmtree(night, ignore_errors=True)
    shutil.copytree(s.work / "hospital", night, ignore=shutil.ignore_patterns("lab.csv", "*.json", ".*"))
    cfg = AdapterConfig(lake_dir=lake, secrets_dir=s.work / "sec",
                        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml", site_id="DEMO-A",
                        audit_dir=s.box.audit_dir, rebuild=None, db_url=pglocal.for_work(s.work))  # fmt: skip
    nxt = s.h.today().isoformat()  # tonight's export, after the night the box serves
    rep = run_ingest(cfg, "csv", str(night), snapshot=nxt, load_fhir=False, validate=False)
    assert rep.held and not rep.passed, (rep.errors or [])[:3]
    assert (lake / "CURRENT").read_text(encoding="utf-8").strip() == served  # the night before is still served
    s.state["held_snapshot"] = nxt
    in_langs(s, "it", f"/site?study={RS}", lambda lang: tr(lang, "site.miss.feed_held", tables="lab"), st["langs"])


@step("J-ADM-03")
def _adm_no_patient(s: Site, st: dict[str, Any]) -> None:
    pid = spare(s, 0)
    s.state["bg_pid"] = pid
    assert s.c[user("it")].get(f"/studies/{RS}/patients/{pid}").status_code == 403
    assert pid[:8] not in s.c[user("it")].get("/home").text


@step("J-ADM-04")
def _adm_break_glass(s: Site, st: dict[str, Any]) -> None:
    it, pid = s.c[user("it")], s.state["bg_pid"]
    page = it.get("/breakglass")
    r = it.post("/breakglass", data={"csrf": poc.csrf(page.text), "reason": "support", "kind": "patient",
                                     "note": "support call about one patient", "ruleset": RS, "pid": pid},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == "/breakglass?done=open", r.headers.get("location")
    sheet = it.get(f"/studies/{RS}/patients/{pid}")
    assert sheet.status_code == 200
    assert it.get(f"/studies/{RS}/patients/{spare(s, 1)}").status_code == 403  # that patient, and nobody else
    opened = events(s, "console.breakglass_open")
    assert opened and opened[-1]["detail"]["pid"] == pid
    gid = opened[-1]["detail"]["grant"]
    bg = it.get("/breakglass").text
    r = it.post(f"/breakglass/{gid}/end", data={"csrf": poc.csrf(bg)}, follow_redirects=False)
    assert r.status_code == 303
    assert it.get(f"/studies/{RS}/patients/{pid}").status_code == 403
    s.state["grant"] = gid


# ---------------------------------------------------------------------------------------------- steward
@step("J-STW-01")
def _stw_sign_in(s: Site, st: dict[str, Any]) -> None:
    assert first_sign_in(s, "stw").url.path == "/breakglass"


@step("J-STW-02")
def _stw_review(s: Site, st: dict[str, Any]) -> None:
    stw, gid = s.c[user("stw")], s.state["grant"]
    page = stw.get("/breakglass").text
    assert f'data-grant="{gid}"' in page and 'data-testid="bg-waiting"' in page and 'data-testid="bg-review"' in page
    r = stw.post(f"/breakglass/{gid}/review", data={"csrf": poc.csrf(page), "note": "matches the support ticket"},
                 follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == "/breakglass?done=review"
    page = stw.get("/breakglass").text
    assert 'data-reviewed="yes"' in page and "matches the support ticket" in page
    assert f'data-grant="{gid}"' in s.c[user("pi")].get("/breakglass").text  # the study's PI sees it too


@step("J-STW-03")
def _stw_conflict(s: Site, st: dict[str, Any]) -> None:
    from omop import schema

    pid = spare(s, 2)
    # what the nightly OMOP load records when the feed and the site's sheet disagree (omop.load._conflicts); the
    # journey site serves the legacy lake, so the row is written here as that load writes it (synthetic values)
    claims = [{"value": "1960-02-03", "source": ["feed", "Patient", "birthDate"]},
              {"value": "1961-02-03", "source": ["site", "Patient", "birthDate"]}]  # fmt: skip
    db = schema.connect()
    try:
        db.execute("INSERT INTO tb_id_map (id_kind, source_id, omop_id) VALUES ('person', ?, 900001)", (pid,))
        cid = int(db.fetchval(
            "INSERT INTO tb_conflict (person_id, kind, item, values_sha, claims, state, detected_batch) VALUES "
            "(900001, 'source_vs_source', 'birth_date', 'journey', ?::jsonb, 'open', ?) RETURNING conflict_id",
            (json.dumps(claims), s.h.today().isoformat())))  # fmt: skip
    finally:
        db.close()
    in_langs(s, "stw", "/data/conflicts", lambda lang: tr(lang, "conflicts.title"), st["langs"])
    stw = s.c[user("stw")]
    page = stw.get("/data/conflicts").text
    assert pid in page and "1960-02-03" in page and "1961-02-03" in page
    r = stw.post(f"/data/conflicts/{cid}/resolve", data={"csrf": poc.csrf(page), "choice": "1961-02-03",
                                                         "reason": "the signed chart says 1961"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].endswith("done=1"), r.headers.get("location")
    assert stw.get("/data/conflicts").text.count('data-testid="conflict"') == 0
    trail = stw.get("/data/conflicts?all=1").text
    assert 'data-state="resolved"' in trail and "the signed chart says 1961" in trail


@step("J-STW-04")
def _stw_data_ops(s: Site, st: dict[str, Any]) -> None:
    stw = s.c[user("stw")]
    page = stw.get("/data-ops")
    assert page.status_code == 200, page.status_code
    held = [m for m in re.finditer(r'data-testid="held" data-batch="(\d+)">(.*?)</tr>', page.text, re.S)
            if s.state["held_snapshot"] in m.group(2)]  # fmt: skip
    assert held and "lab" in js.text(held[0].group(2)), js.text(page.text)[:400]
    assert 'value="accept"' not in page.text and 'data-testid="dataops-accept-off"' in page.text  # D-443: not yet
    bid = held[0].group(1)
    r = stw.post(f"/data-ops/batches/{bid}/decide", data={"csrf": poc.csrf(page.text), "decision": "reject",
                 "reason": "lab extract missing; the export is redone tonight"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == "/data-ops?done=reject", r.headers.get("location")
    trail = js.text(stw.get(f"/data-ops/batches/{bid}").text)
    assert "REJECTED" in trail.upper() and "the export is redone tonight" in trail, trail[:400]
    gone = tr("en", "site.miss.feed_held", tables="lab")
    assert gone not in js.text(s.c[user("it")].get(f"/site?study={RS}").text)  # decided: no longer shown as held


# ---------------------------------------------------------------------------------------------- coordinator
@step("J-CRC-01")
def _crc_sign_in(s: Site, st: dict[str, Any]) -> None:
    home = first_sign_in(s, "crc")
    assert home.url.path == "/home" and "My tasks" in js.text(home.text)


@step("J-CRC-02")
def _crc_protocol(s: Site, st: dict[str, Any]) -> None:
    c = s.c[user("crc")]
    form = c.get("/pilot/protocol")
    criteria = cd.criteria_text("GZQO", {cd.BMI_FROM: cd.BMI_TO}, (cd.ADDED,))
    r = c.post("/pilot/protocol", data={"csrf": poc.csrf(form.text), "ruleset": "GZQO", "criteria": criteria})
    assert r.status_code == 200 and r.url.path.startswith("/pilot/jobs/"), (r.status_code, js.text(r.text)[-300:])
    s.state["amend_job"] = r.url.path.rsplit("/", 1)[-1]


@step("J-CRC-03")
def _crc_screen(s: Site, st: dict[str, Any]) -> None:
    res = cd.screen({"crc": s.c[user("crc")], "box": s.box, "h": s.h}, "GZQO")
    assert res["rows"], "the GZQO v1.1.0 list has no candidate"
    assert res["job"].ruleset_version == "1.1.0", res["job"].ruleset_version
    in_langs(s, "crc", "/studies/GZQO/week", lambda lang: tr(lang, "week.title"), st["langs"])


@step("J-CRC-04")
def _crc_referral_answer(s: Site, st: dict[str, Any]) -> None:
    poc._crc_answer(s)


@step("J-CRC-05")
def _crc_irb(s: Site, st: dict[str, Any]) -> None:
    poc._crc_irb(s)


@step("J-CRC-06")
def _crc_consent(s: Site, st: dict[str, Any]) -> None:
    poc._crc_outcome(s)
    name, no = user("crc"), s.state["screening_no"]
    for to in ("consented", "enrolled"):
        page = s.get(name, f"/studies/{RS}/subjects/{no}")
        r = s.post(name, f"/studies/{RS}/subjects/{no}/step", {"to": to, "on_day": s.h.today().isoformat()},
                   page.text)  # fmt: skip
        assert r.status_code == 200, (to, js.text(r.text)[:300])
        one = s.h.bk.study_api("GET", f"/studies/{RS}/subjects/{no}?today={s.h.today().isoformat()}")
        assert one["subject"]["state"] == to, one["subject"]


@step("J-CRC-07")
def _crc_edc_review(s: Site, st: dict[str, Any]) -> None:
    rs, name, no = cd.REGISTRY, user("crc"), s.state["reg_no"]
    home = s.get(name, f"/studies/{rs}/edc")
    r = s.post(name, f"/studies/{rs}/edc/drafts", {"record": no, "visit_date": s.h.today().isoformat()}, home.text)
    assert r.status_code == 200, js.text(r.text)[-400:]
    d = {x["item"]: x for x in s.h.bk.study_api("GET", f"/studies/{rs}/edc/drafts?record={no}")}
    drafted = {k for k, v in d.items() if v["state"] == "drafted"}
    assert {"brthdat", "sex"} <= drafted, drafted
    t = js.text(s.get(name, f"/studies/{rs}/edc/review/{no}").text)
    assert "hospital record" in t and "Comments comments unknown · not drafted" in t
    in_langs(s, "crc", f"/studies/{rs}/edc/review/{no}", lambda lang: tr(lang, "edc.review.help"), st["langs"])
    held = s.state["rc"].records()[0]  # REDCap holds only what the site put there: nothing drafted is sent
    assert not any(held.get(k) for k in drafted), held


# ---------------------------------------------------------------------------------------------- investigator (PI)
@step("J-PI-01")
def _pi_sign_in(s: Site, st: dict[str, Any]) -> None:
    home = first_sign_in(s, "pi")
    assert home.url.path == "/week", home.url
    assert "Criteria waiting for your approval: GZQO v1.1.0" in js.text(home.text) or "amend_job" not in s.state


@step("J-PI-02")
def _pi_approve(s: Site, st: dict[str, Any]) -> None:
    poc._tw_amend(s)


@step("J-PI-03")
def _pi_sheet(s: Site, st: dict[str, Any]) -> None:
    poc._pi_sheet(s)


@step("J-PI-04")
def _pi_referral(s: Site, st: dict[str, Any]) -> None:
    poc._pi_referral(s)


@step("J-PI-05")
def _pi_approach(s: Site, st: dict[str, Any]) -> None:
    name, pid = user("pi"), s.state["referred"]
    page = poc.sheet(s, name, RS, pid).text
    assert 'data-testid="irb-warning"' not in page and f'data-testid="approach-{pid[:8]}"' in page
    r = poc.mark(s, name, RS, pid, "approach")
    assert r.status_code == 200 and "Approved. The coordinator has a task to contact this patient." in js.text(r.text)
    no = s.h.store.screening_no(RS, pid)
    assert no and no.startswith(f"{RS}-")
    assert no in js.text(s.get(name, f"/studies/{RS}/screening-log").text)
    s.state.update(approached=pid, screening_no=no)


@step("J-PI-06")
def _pi_monitor_grant(s: Site, st: dict[str, Any]) -> None:
    name, day = user("pi"), s.h.today()
    page = s.get(name, f"/studies/{RS}/team")
    form = {"username": user("cra"), "role": "monitor", "start": day.isoformat(),
            "end": (day + timedelta(days=2)).isoformat(), "training_ref": "MV-01"}  # fmt: skip
    r = s.post(name, f"/studies/{RS}/team", form, page.text, follow_redirects=False)
    assert r.status_code == 303, r.status_code
    grant = [e for e in s.h.team.entries(RS) if e.username == user("cra") and e.role == "monitor"]
    assert grant and grant[-1].training_ref == "MV-01" and grant[-1].end == form["end"]


@step("J-PI-07")
def _pi_weekly_sample(s: Site, st: dict[str, Any]) -> None:
    name = user("pi")
    page = s.get(name, f"/studies/{RS}/not-matched/sample")
    assert 'data-testid="nm-counter"' in page.text and 'data-testid="nm-held"' not in page.text, js.text(page.text)[
        :300
    ]
    shown = list(dict.fromkeys(re.findall(rf'action="/studies/{RS}/not-matched/sample/([0-9a-f]+)"', page.text)))
    assert 1 <= len(shown) <= 10, len(shown)
    pid = shown[0]
    r = s.post(name, f"/studies/{RS}/not-matched/sample/{pid}", {"answer": "send_back",
               "note": "the record shows the value inside the range"}, page.text, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and "done=send_back" in r.headers["location"], r.headers.get("location")
    row = next((x for x in poc.rows(s, RS) if str(x["pid"]) == pid), None)
    assert row is not None and row.get("sent_back"), row
    s.state["sent_back"] = pid


# ---------------------------------------------------------------------------------------------- sub-investigator
@step("J-SI-01")
def _si_sign_in(s: Site, st: dict[str, Any]) -> None:
    home = first_sign_in(s, "subpi")
    assert home.url.path == f"/studies/{RS}/week" and f"This week's patients · {RS}" in js.text(home.text)


@step("J-SI-02")
def _si_no_approach(s: Site, st: dict[str, Any]) -> None:
    poc._si_no_approach(s)


@step("J-SI-03")
def _si_need_info(s: Site, st: dict[str, Any]) -> None:
    poc._si_need_info(s)


@step("J-SI-04")
def _si_not_delegated(s: Site, st: dict[str, Any]) -> None:
    poc._si_not_delegated(s)


# ---------------------------------------------------------------------------------------------- monitor (CRO)
@step("J-MON-01")
def _mon_sign_in(s: Site, st: dict[str, Any]) -> None:
    assert first_sign_in(s, "cra").url.path == "/reports"


@step("J-MON-02")
def _mon_no_candidate(s: Site, st: dict[str, Any]) -> None:
    c = s.c[user("cra")]
    assert c.get(f"/studies/{RS}/week").status_code == 403
    assert c.get(f"/studies/{RS}/patients/{s.state['approached']}").status_code == 403


@step("J-MON-03")
def _mon_subject(s: Site, st: dict[str, Any]) -> None:
    r = s.c[user("cra")].get(f"/studies/{RS}/monitor/{s.state['screening_no']}")
    assert r.status_code == 200, r.status_code
    assert "MV-01" in js.text(r.text) and s.state["approached"][:8] not in r.text


# ---------------------------------------------------------------------------------------------- viewer
@step("J-VWR-01")
def _vwr_sign_in(s: Site, st: dict[str, Any]) -> None:
    assert first_sign_in(s, "view").url.path == "/reports"
    in_langs(s, "view", "/reports", lambda lang: tr(lang, "reports.title"), st["langs"])


@step("J-VWR-02")
def _vwr_refused(s: Site, st: dict[str, Any]) -> None:
    c = s.c[user("view")]
    assert c.get(f"/studies/{RS}/patients/{s.state['approached']}").status_code == 403
    assert c.get(f"/studies/{RS}/week").status_code == 403
    jobs = len(s.h.bk.list_jobs(500))
    page = c.get(f"/pilot/request?ruleset={RS}")
    r = c.post("/pilot/request", data={"csrf": poc.csrf(page.text), "kind": "FEAS", "ruleset": RS},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 403 and len(s.h.bk.list_jobs(500)) == jobs


# ---------------------------------------------------------------------------------------------- privacy office
@step("J-PRV-01")
def _prv_sign_in(s: Site, st: dict[str, Any]) -> None:
    assert first_sign_in(s, "dpo").url.path == "/site/opt-outs"
    in_langs(s, "dpo", "/site/opt-outs", lambda lang: tr(lang, "team.optout.title"), st["langs"])


@step("J-PRV-02")
def _prv_opt_out(s: Site, st: dict[str, Any]) -> None:
    lake = s.box.orch.services.lake
    pid = next(
        p
        for p in (spare(s, i) for i in range(3, 40))
        if lake.query("SELECT count(*) AS n FROM document_chunk WHERE pid = ?", [p]).to_pylist()[0]["n"]
    )
    chart = js.chart_numbers(s)[pid]
    pi, crc = s.c[user("pi")], s.c[user("crc")]
    assert pid in {str(x["pid"]) for x in poc.rows(s, RS)}  # on the PI's list before
    assert pi.get(f"/studies/{RS}/patients/{pid}").status_code == 200
    dpo = s.c[user("dpo")]
    page = dpo.get("/site/opt-outs")
    r = dpo.post("/site/opt-outs", data={"csrf": poc.csrf(page.text), "chart_no": chart, "source": "paper"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == "/site/opt-outs?done=added"  # no pseudonym back
    assert pid[:8] not in pi.get(f"/studies/{RS}/week?list=all").text
    assert pid not in {str(x["pid"]) for x in poc.rows(s, RS)}
    assert pid[:8] not in crc.get(f"/studies/{RS}/candidates").text
    assert pi.get(f"/studies/{RS}/patients/{pid}").status_code == 404
    res = cd.screen({"crc": crc, "box": s.box, "h": s.h}, RS)  # the next screening run
    assert res["rows"] and pid not in res["rows"]
    s.state["opted_out"] = pid


@step("J-PRV-03")
def _prv_worker(s: Site, st: dict[str, Any]) -> None:
    from datacore import optout_worker

    out = optout_worker.tick(s.box.orch)
    assert out is not None and out["failed"] == [], out
    assert out["opted_out"] >= 1 and {"candidate_pool", "candidate_registry"} <= set(out["stores"]), out
    pid = s.state["opted_out"]
    for rs in sorted({str(x["ruleset"]) for x in s.box.orch.db.candidate_summaries()}):
        for row in s.box.orch.db.candidates(rs):
            assert str(row["pid"]) != pid or row["status"] not in optout_worker.OPEN_STATUSES, (rs, row["status"])


@step("J-PRV-04")
def _prv_lake(s: Site, st: dict[str, Any]) -> None:
    lake = s.box.orch.services.lake
    n = lake.query("SELECT count(*) AS n FROM document_chunk WHERE pid = ?", [s.state["opted_out"]]).to_pylist()
    assert n[0]["n"] == 0, n


# ------------------------------------------------------------ NEW-JRN-1 (D-540): a new study to its first list
NEW_RS = "GOUT-NEW"  # a study the box has no ruleset folder for; its criteria are GZQO's, pasted under a new id


@step("J-ADM-05")
def _adm_new_study(s: Site, st: dict[str, Any]) -> None:
    it = user("it")
    assert all(r.id != NEW_RS for r in s.h.bk.rulesets())
    form = s.get(it, "/pilot/protocol")
    r = s.post(it, "/pilot/protocol", {"ruleset": NEW_RS, "criteria": cd.criteria_text("GZQO")}, form.text)
    assert r.status_code == 200 and r.url.path.startswith("/pilot/jobs/"), (r.status_code, js.text(r.text)[-300:])
    job = r.url.path.rsplit("/", 1)[-1]
    s.state["new_job"] = job
    page = s.get(it, f"/pilot/jobs/{job}/approval")
    assert page.status_code == 200 and 'data-testid="approve-needs-pi"' in page.text, js.text(page.text)[-300:]
    # the PI's and the coordinator's accounts are limited to their studies (D-104): the new one is added to them
    for key in ("pi", "crc"):
        name = user(key)
        s.get(name, f"/pilot/jobs/{job}/approval", 404)
        acct = next(u for u in s.h.users.users() if u.username == name)
        users = s.get(it, "/ops/users")
        r = s.post(it, "/ops/users", {"action": "scope", "username": name, "affiliation": acct.affiliation,
                                      "studies": ",".join([*acct.studies, NEW_RS]), "expires": acct.expires or ""},
                   users.text, follow_redirects=False)  # fmt: skip
        assert r.status_code == 303, (name, r.status_code, js.text(r.text)[-300:])
    # D-719 (NEW-SEC-3): a protected account's studies change when a second person confirms; the steward does
    stw = user("stw")
    waiting = s.get(stw, "/ops/accounts/requests")
    rids = re.findall(r'data-request="([a-f0-9]+)"', waiting.text)
    assert len(rids) == 2, js.text(waiting.text)[-300:]
    for rid in rids:
        r = s.post(stw, "/ops/accounts/requests", {"request": rid, "decision": "confirm"}, waiting.text)
        assert r.status_code == 200, (rid, r.status_code, js.text(r.text)[-300:])
        waiting = s.get(stw, "/ops/accounts/requests")
    page = s.get(user("pi"), f"/pilot/jobs/{job}/approval")
    assert 'data-testid="approve-needs-pi"' in page.text and 'data-testid="approve"' not in page.text


@step("J-STW-05")
def _stw_names_the_pi(s: Site, st: dict[str, Any]) -> None:
    stw = user("stw")
    home = s.get(stw, "/breakglass")
    assert f'data-testid="task-name-pi-{NEW_RS}"' in home.text, js.text(home.text)[:300]
    log = s.get(stw, f"/studies/{NEW_RS}/team")
    assert log.status_code == 200, log.status_code
    r = s.post(stw, f"/studies/{NEW_RS}/team", {"username": user("pi"), "role": "pi", "start": "2026-01-01",
                                               "training_day": "2025-06-01"}, log.text, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, (r.status_code, js.text(r.text)[-300:])
    assert f'data-testid="task-name-pi-{NEW_RS}"' not in s.get(stw, "/breakglass").text


@step("J-PI-08")
def _pi_first_approval(s: Site, st: dict[str, Any]) -> None:
    name, job = user("pi"), s.state["new_job"]
    page = s.get(name, f"/pilot/jobs/{job}/approval")
    assert 'data-testid="approve-needs-pi"' not in page.text
    for cid in re.findall(r'data-testid="open-([A-Z0-9-]+)"', page.text):  # every amber line opened
        page = s.get(name, f"/pilot/jobs/{job}/approval?open={cid}")
    for cid in re.findall(r'data-testid="label-missing-([A-Z0-9-]+)"', page.text):  # the site's label (D-309)
        r = s.post(name, f"/pilot/jobs/{job}/approval/label", {"crit": cid, "text": f"{cid} label"}, page.text)
        assert r.status_code == 200, js.text(r.text)[-300:]
        page = s.get(name, f"/pilot/jobs/{job}/approval")
    r = s.post(name, f"/pilot/jobs/{job}/approve", {"confirm": "yes"}, page.text)
    assert r.status_code == 200 and f"APPROVE {NEW_RS} v1.0.0 done" in js.text(r.text), js.text(r.text)[:300]
    assert {x.id: x for x in s.h.bk.rulesets()}[NEW_RS].status == "approved"


@step("J-CRC-08")
def _crc_first_list(s: Site, st: dict[str, Any]) -> None:
    crc = user("crc")
    setup = s.get(crc, f"/studies/{NEW_RS}/setup")  # the new study's set-up page opens for its coordinator
    r = s.post(crc, f"/studies/{NEW_RS}/setup/scope", {"mode": "hospital"}, setup.text)
    assert r.status_code == 200 and 'data-testid="who-now"' in r.text, (r.status_code, js.text(r.text)[-300:])
    res = cd.screen({"crc": s.c[user("crc")], "box": s.box, "h": s.h}, NEW_RS)
    assert res["job"].ruleset_version == "1.0.0", res["job"].ruleset_version
    page = s.c[user("crc")].get(f"/studies/{NEW_RS}/week")
    assert page.status_code == 200, page.status_code


# ------------------------------------------------------------ NEW-JRN-20 (D-773): the steps a site needs to run a study
NEW_CRC = "tw.crc2"
NEW_CRC_PW = "journey-crc2-own-password-0001"


@step("J-ADM-06")
def _adm_new_account(s: Site, st: dict[str, Any]) -> None:
    it = user("it")
    page = s.get(it, "/ops/users")
    r = s.post(it, "/ops/users", {"action": "add", "username": NEW_CRC, "role": "coordinator", "affiliation": "hospital",
                                  "studies": "", "expires": ""}, page.text)  # fmt: skip
    assert r.status_code == 200 and 'data-testid="account-requested"' in r.text, js.text(r.text)[-300:]
    assert 'data-testid="enrol-code-value"' not in r.text and 'data-testid="users-pw-field"' not in r.text
    assert s.h.users.get(NEW_CRC) is None  # nothing exists until the second person confirms (D-719)


@step("J-STW-06")
def _stw_confirms_the_account(s: Site, st: dict[str, Any]) -> None:
    stw = user("stw")
    waiting = s.get(stw, "/ops/accounts/requests")
    rids = re.findall(r'data-request="([a-f0-9]+)"', waiting.text)
    assert len(rids) == 1, js.text(waiting.text)[-300:]
    r = s.post(stw, "/ops/accounts/requests", {"request": rids[0], "decision": "confirm"}, waiting.text)
    code = re.search(r'data-testid="request-secret"[^>]*value="([a-z0-9-]+)"', r.text)
    assert r.status_code == 200 and code, js.text(r.text)[-300:]
    again = s.get(stw, "/ops/accounts/requests").text  # shown once, to the steward, and never again
    assert 'data-testid="request-secret"' not in again and code.group(1) not in again
    # the new coordinator's first sign-in: the code, an own password, an authenticator set up from the page
    c = TestClient(s.served)
    tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/enrol").text)
    assert tok
    r = c.post("/enrol", data={"username": NEW_CRC, "enrol_code": code.group(1), "password": NEW_CRC_PW,
                               "password2": NEW_CRC_PW, "login_csrf": tok.group(1)}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == "/login/totp", (r.status_code, js.text(r.text)[-300:])
    page = c.get("/login/totp").text
    key = re.search(r'data-testid="totp-key"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*data-testid="totp-key"', page)
    mfa = re.search(r'name="mfa_csrf" value="([^"]+)"', page)
    assert key and mfa, js.text(page)[-300:]
    s.secrets_[NEW_CRC] = (key.group(1) or key.group(2)).replace(" ", "")
    r = c.post("/login/totp", data={"code": s.code(NEW_CRC), "mfa_csrf": mfa.group(1)}, follow_redirects=False)
    assert r.status_code == 303, (r.status_code, js.text(r.text)[-300:])
    home = c.get("/home")
    assert home.url.path == "/home" and tr("en", "wb.crc.title") in js.text(home.text), (
        home.url,
        js.text(home.text)[:300],
    )
    s.c[NEW_CRC] = c
    c2 = TestClient(s.served)  # the code is spent: a second first sign-in with it is refused
    tok = re.search(r'name="login_csrf" value="([^"]+)"', c2.get("/enrol").text)
    assert tok
    r = c2.post("/enrol", data={"username": NEW_CRC, "enrol_code": code.group(1), "password": NEW_CRC_PW + "x",
                                "password2": NEW_CRC_PW + "x", "login_csrf": tok.group(1)}, follow_redirects=False)  # fmt: skip
    assert r.status_code != 303 or r.headers.get("location") != "/login/totp", r.status_code
    made = [e for e in events(s, "console.user") if e["detail"].get("user") == NEW_CRC]
    assert made and made[-1]["detail"]["confirmed_by"] == stw and code.group(1) not in json.dumps(made)


def _entry(s: Site, name: str, rs: str, record: str, form: str, values: dict[str, str], event: str = "",
           back: str = "subject") -> Any:  # fmt: skip
    """A built-in form saved through the entry page, as the person fills it in."""
    page = s.get(name, f"/studies/{rs}/entry?record={record}&form={form}&event={event}&back={back}")
    data = {"record": record, "event": event, "form": form, "back": back, **{f"f_{k}": v for k, v in values.items()}}
    r = s.post(name, f"/studies/{rs}/entry", data, page.text)
    assert r.status_code == 200, (form, r.status_code, js.text(r.text)[-400:])
    return r


@step("J-CRC-09")
def _crc_visit(s: Site, st: dict[str, Any]) -> None:
    name, no, today = user("crc"), s.state["screening_no"], s.h.today()
    forms = s.get(name, f"/studies/{RS}/forms")
    r = s.post(name, f"/studies/{RS}/forms/builtin", {}, forms.text)
    assert r.status_code == 200 and "err" not in r.url.params and int(r.url.params.get("builtin") or 0) >= 7, r.url
    sched = s.get(name, f"/studies/{RS}/schedule")
    r = s.post(name, f"/studies/{RS}/schedule", {"action": "save", "visit": ["v1", "v2", ""],
               "label": ["Week 1", "Week 4", ""], "day": ["7", "28", ""], "before": ["7", "3", ""],
               "after": ["7", "3", ""],
               "anchor": ["enrolment", "enrolment", "enrolment"]}, sched.text)  # fmt: skip
    assert 'data-testid="schedule-saved"' in r.text, js.text(r.text)[-300:]
    page = s.get(name, f"/studies/{RS}/visits").text
    row = re.search(rf'data-testid="visit-{no}-v1"(.*?)</(?:tr|li)>', page, re.S)
    assert row and "In the window" in js.text(row.group(1)), js.text(page)[:600]
    r = _entry(s, name, RS, no, "tb_visit", {"vs_status": "1", "vs_date": today.isoformat(), "vs_window": "1"}, "v1",
               "visits")  # fmt: skip
    assert 'data-testid="visit-saved"' in r.text and f'data-testid="visit-{no}-v1"' not in r.text
    one = s.h.bk.study_api("GET", f"/studies/{RS}/subjects/{no}?today={today.isoformat()}")
    assert one["subject"]["state"] == "on_study" and one["visits"][0]["status"] == "done", one["subject"]
    assert [v["visit"] for v in one["visits"] if v["status"] != "done"] == ["v2"], one["visits"]  # Week 4 is next
    page = s.get(name, f"/studies/{RS}/subjects/{no}").text  # and the participant page says so
    assert 'data-state="on_study"' in page and 'data-testid="sv-v1" data-status="done"' in page
    assert re.search(r'data-testid="sv-v2" data-status="(?!done)', page), js.text(page)[:400]


@step("J-CRC-10")
def _crc_sae(s: Site, st: dict[str, Any]) -> None:
    name, no, today = user("crc"), s.state["screening_no"], s.h.today()
    now = s.h.clock().astimezone(ZoneInfo(cd.SITE_TW["site"]["tz"]))
    aware = (now - timedelta(minutes=30)).strftime("%H:%M")  # known half an hour ago, at the site
    assert (now - timedelta(minutes=30)).date() == today, now
    setup = s.get(name, f"/studies/{RS}/setup")
    r = s.post(name, f"/studies/{RS}/setup/sae", {"rule_set": "tw_trial"}, setup.text)
    assert r.status_code == 200 and r.url.params.get("saved") == "sae", (r.url, js.text(r.text)[-300:])
    now = re.search(r'data-testid="setup-sae-now">(.*?)</p>', r.text, re.S)
    assert now and tr("en", "sae.set.tw_trial") in js.text(now.group(1)) and "warn" not in now.group(1), r.text[-300:]
    r = _entry(s, name, RS, no, "tb_adverse_event", {"ae_term": "Pneumonia", "ae_onset": today.isoformat(),
               "ae_aware": today.isoformat(), "ae_aware_time": aware, "ae_serious": "1", "ae_serious_why": "3",
               "ae_severity": "3", "ae_related": "9"}, "ae1")  # fmt: skip
    assert 'data-testid="ae-ae1"' in r.text, js.text(r.text)[-300:]
    for who, path in ((name, "/home"), (user("pi"), "/week")):  # the banner names this participant's AE
        assert f'data-testid="sae-{no}-ae1"' in s.get(who, path).text, (who, path)
    case = s.get(name, f"/studies/{RS}/sae/{no}/ae1").text
    due = re.search(r'data-testid="sae-due-at-sponsor">([^<]+)<', case)
    assert due and due.group(1).strip() == f"{(today + timedelta(days=1)).isoformat()} {aware}", (
        due.group(1) if due else js.text(case)[:400]
    )  # 24 hours after awareness, at the site


@step("J-CRC-11")
def _crc_deviation(s: Site, st: dict[str, Any]) -> None:
    name, no, today = user("crc"), s.state["screening_no"], s.h.today()
    what = "Week 1 blood draw taken outside the protocol window"
    r = _entry(s, name, RS, no, "tb_deviation", {"dv_date": today.isoformat(), "dv_kind": "3", "dv_what": what},
               "dv1")  # fmt: skip
    row = re.search(r'data-testid="dv-dv1">(.*?)</li>', r.text, re.S)
    assert row and today.isoformat() in row.group(1) and what in row.group(1), js.text(r.text)[-300:]


@step("J-CRC-12")
def _crc_edc_sign_send(s: Site, st: dict[str, Any]) -> None:
    rs, name, no = cd.REGISTRY, user("crc"), s.state["reg_no"]
    d = {x["item"]: x for x in s.h.bk.study_api("GET", f"/studies/{rs}/edc/drafts?record={no}")}
    drafted = {k: v["value"] for k, v in d.items() if v["state"] == "drafted"}
    rev = s.get(name, f"/studies/{rs}/edc/review/{no}")
    offered = dict(re.findall(r'action="/studies/[^"]+/edc/decide/(\d+)"[^>]*>(?:(?!</form>).)*?data-testid="confirm-([a-z0-9_]+)"',
                              rev.text, re.S))  # fmt: skip
    assert set(offered.values()) == set(drafted), (offered, drafted)  # a Confirm button for each drafted value
    for did, k in offered.items():  # each value checked against the source the page shows, then confirmed
        assert int(did) == d[k]["id"], (k, did)
        r = s.post(name, f"/studies/{rs}/edc/decide/{did}", {"action": "confirm", "record": no}, rev.text)
        assert r.status_code == 200, (k, js.text(r.text)[-300:])
    shown = s.get(name, f"/studies/{rs}/edc/review/{no}").text
    seen = re.search(r'name="seen" value="([^"]+)"', shown)
    assert seen, js.text(shown)[-300:]  # what the signer saw is what is signed
    form = {"record": no, "password": js.OWN_PW, "meaning_ack": "1", "seen": seen.group(1)}
    refused = s.post(name, f"/studies/{rs}/edc/sign", form, shown)  # no authenticator code: nothing is signed
    assert refused.status_code == 401 and "Nothing was signed" in js.text(refused.text), refused.status_code
    signed = s.post(name, f"/studies/{rs}/edc/sign", {**form, "otp": s.code(name)}, shown)
    assert signed.status_code == 200, js.text(signed.text)[-400:]
    sent = s.post(name, f"/studies/{rs}/edc/send", {"record": no}, signed.text)
    assert sent.status_code == 200 and re.search(r"Sent [1-9]\d*\..*Read-back differences 0", js.text(sent.text)), (
        js.text(sent.text)[:400]
    )
    held = s.state["rc"].records()[0]
    assert all(held.get(k) == v for k, v in drafted.items()), (drafted, held)


@step("J-MON-04")
def _mon_visit_record(s: Site, st: dict[str, Any]) -> None:
    name, no, today = user("cra"), s.state["screening_no"], s.h.today()
    page = s.get(name, f"/studies/{RS}/monitor")
    finding = "consent form copy not filed in the subject binder"
    r = s.post(name, f"/studies/{RS}/monitor/visits", {"visit_day": today.isoformat(), "subjects": [no],
               "findings": finding}, page.text)  # fmt: skip
    assert r.status_code == 200 and 'data-testid="sdv-visit-saved"' in r.text, js.text(r.text)[-300:]
    body = re.search(r'data-testid="sdv-visits">.*?<tbody>(.*?)</tbody>', r.text, re.S)
    assert body, js.text(r.text)[-300:]
    rows = [[js.text(c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr_, re.S)]
            for tr_ in re.findall(r"<tr>(.*?)</tr>", body.group(1), re.S)]  # fmt: skip
    assert [today.isoformat(), "MV-01", name, no, finding] in rows, rows


@step("J-PI-09")
def _pi_close(s: Site, st: dict[str, Any]) -> None:
    import io

    import openpyxl

    name, rs = user("pi"), "GZQO"
    why = "the sponsor stopped recruitment at every site"
    page = s.get(name, f"/studies/{rs}/state")
    r = s.post(name, f"/studies/{rs}/state", {"state": "closed", "reason": why}, page.text)
    assert r.status_code == 200 and 'data-state="closed"' in r.text, (r.status_code, js.text(r.text)[-300:])
    assert why in js.text(r.text)
    log = js.text(s.get(name, f"/studies/{rs}/screening-log").text)
    assert re.search(rf"Now: Closed \(since {s.h.today().isoformat()} [0-9:]+, by {re.escape(name)}\)", log), log[:400]
    xlsx = s.get(name, f"/studies/{rs}/screening-log.xlsx")  # the exported log, as the site downloads it
    about = [
        [str(c.value or "") for c in row] for row in openpyxl.load_workbook(io.BytesIO(xlsx.content))["about"].rows
    ]
    assert about[[r[0] for r in about].index("state")][:2] == ["state", "closed"], about
    closed = next(r for r in about if r[0] == "state.closed")
    at = datetime.fromisoformat(closed[1]).astimezone(ZoneInfo(cd.SITE_TW["site"]["tz"]))  # stored with its offset
    assert at.date() == s.h.today() and name in closed[2] and closed[3] == why, closed
