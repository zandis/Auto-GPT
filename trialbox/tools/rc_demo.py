"""Step-3 REDCap demo (20-build-map §2 step 3): link the simulator's fixture project, change a status in the
simulator, press Run now and see it in the screening log. Stub model, no network, no API key.

    python -m tools.rc_demo --dir /tmp/tb-rc                      # run once, print what happened, exit 0 on success
    python -m tools.rc_demo --dir /tmp/tb-rc --serve              # then keep the console up

What it does, after the step-2 run of ``tools.list_demo`` (the investigator marked a GZQO patient Approach, so the
patient has the screening number GZQO-0001):

1. the administrator enters the REDCap base URL (``inproc://rc-sim``, the built-in simulator) and project A's API
   token on S36 and presses **Test connection** (version and project are read: R1, R2);
2. the coordinator fills S21 section 2 (the project link: ``tb_screening_no``, ``consent_date``, ``enrolled``,
   ``sf_reason`` with its choice map, ``subject_no``); saving checks every field against the data dictionary (R3);
3. in the simulator, the CRC creates the REDCap record for GZQO-0001 with a consent date (``POST /sim/records``);
   the coordinator presses **Run now**: the log shows *consented*, the REDCap record id, and the two fixture
   records "in REDCap, not in TrialBox";
4. in the simulator the record's ``enrolled`` field is set to 1 and a subject number is given; **Run now** again:
   the log shows *enrolled* and the subject number. Nothing is ever written to REDCap.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import feas_demo as fd  # noqa: E402
from tools import list_demo as ld  # noqa: E402

TRIAL = ld.TRIAL
SIM_URL = "inproc://rc-sim"
LINK_FORM = {
    "token_ref": "gzqo",
    "project_id": "101",
    "link_field": "tb_screening_no",
    "consent_field": "consent_date",
    "enrol_field": "enrolled",
    "enrol_value": "1",
    "screenfail_field": "sf_reason",
    "screenfail_choice_map": "1=inclusion, 2=exclusion, 3=consent_withdrawn, 9=other",
    "subject_no_field": "subject_no",
}


def status_of(html: str, no: str) -> str:
    m = re.search(rf'data-testid="status-{re.escape(no)}">([^<]+)', html)
    return m.group(1).strip().rstrip("·").strip() if m else ""


def run(work: Path, password: str, lang: str = "ja") -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from rc_sim.app import create_app, load_projects, register_inproc

    sim = create_app()  # a fresh simulator per run: records from an earlier run in this process never leak in
    register_inproc(sim)  # demo box only (FR-RC-17a)
    token_a = next(t for t, p in load_projects().items() if p["project"]["project_id"] == 101)
    res = ld.run(work, password, lang)
    app, h, crc = res["app"], res["app"].state.helpers, res["crc"]
    no = res["screening_no"]
    admin = ld.sign_in(app, "admin", password, lang)
    out: dict[str, Any] = {"list": res, "screening_no": no, "admin": admin, "crc": crc, "app": app, "sim": sim}

    # 1 S36: URL and token, then Test connection
    page = ld.ok(admin.get("/admin/redcap"), "S36")
    ld.ok(admin.post("/admin/redcap", data={"csrf": fd._csrf(page.text), "token_ref": "gzqo", "url": SIM_URL,
                                            "token": token_a}), "S36 save")  # fmt: skip
    t = ld.ok(admin.post("/admin/redcap/gzqo/test", data={"csrf": fd._csrf(page.text)}), "S36 test")
    out["s36_ok"] = "16.0.10" in t.text and token_a not in t.text

    # 2 S21: the project link (checked against the data dictionary)
    page = ld.ok(crc.get(f"/studies/{TRIAL}/setup"), "S21")
    r = ld.ok(crc.post(f"/studies/{TRIAL}/setup/redcap", data={"csrf": fd._csrf(page.text), **LINK_FORM}), "link")
    assert 'data-testid="link-on"' in r.text, re.sub(r"<[^>]+>", " ", r.text)[-600:]

    # 3 the CRC creates the REDCap record with the screening number and a consent date; Run now
    sc = TestClient(sim)
    rec = {"record_id": "3", "tb_screening_no": no, "consent_date": h.today().isoformat()}
    assert sc.post("/sim/records", json={"project_id": 101, "records": [rec]}).status_code == 200
    log = ld.ok(crc.get(f"/studies/{TRIAL}/screening-log"), "log")
    out["before"] = status_of(log.text, no)
    r = ld.ok(crc.post(f"/studies/{TRIAL}/redcap-read", data={"csrf": fd._csrf(log.text), "back": "log"}), "run now")
    out["after_consent"] = status_of(r.text, no)
    out["unmatched_shown"] = 'data-testid="rc-unmatched"' in r.text  # fixture records 1 and 2 (GZQO-0901/0902)

    # 4 change the status in the simulator: enrolled, with a sponsor subject number; Run now again
    upd = {"record_id": "3", "enrolled": "1", "subject_no": "S-0003"}
    assert sc.post("/sim/records", json={"project_id": 101, "records": [upd]}).status_code == 200
    r = ld.ok(crc.post(f"/studies/{TRIAL}/redcap-read", data={"csrf": fd._csrf(r.text), "back": "log"}), "run now 2")
    out["after_enrol"] = status_of(r.text, no)
    out["log_html"] = r.text
    out["subject_shown"] = "S-0003" in r.text
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR", "/tmp/tb-rc-demo")))
    ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--serve", action="store_true", help="keep the console up after the run")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--fresh", action="store_true", help="delete --dir first")
    a = ap.parse_args(argv)
    if a.fresh and a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    res = run(a.dir, password, a.lang)
    print(f"S36 test connection: {'ok' if res['s36_ok'] else 'FAILED'}")
    print(f"screening log {res['screening_no']}: {res['before']} -> {res['after_consent']} -> {res['after_enrol']}")
    print(
        f"subject number shown: {res['subject_shown']} · 'in REDCap, not in TrialBox' shown: {res['unmatched_shown']}"
    )
    from console.i18n import CATALOGUES

    enrolled = CATALOGUES[a.lang]["registry.status.enrolled"]
    good = res["s36_ok"] and res["after_enrol"].startswith(enrolled) and res["subject_shown"]
    if a.serve:
        import uvicorn

        print(f"\nconsole on http://{a.host}:{a.port}/home  accounts: {', '.join(x[0] for x in fd.ACCOUNTS)}")
        if not os.environ.get("TB_DEMO_PASSWORD"):
            print(f"password (all accounts): {password}")
        uvicorn.run(res["app"], host=a.host, port=a.port, log_level="warning")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
