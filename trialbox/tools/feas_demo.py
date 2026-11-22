"""Step-1 feasibility demo (20-build-map §2 step 1): paste the GOUT-COH criteria on S2, get the S3 funnel on the
5,000-patient synthetic hospital, in Japanese. Stub model only, no network, no API key.

    python -m tools.feas_demo --dir /tmp/tb-feas            # build, ingest, run S2 -> S3 once, print the funnel
    python -m tools.feas_demo --dir /tmp/tb-feas --serve    # then keep the console up (accounts as tools.role_demo)

What it does:

1. ``tools.synth_hospital --profile ci``: one Japanese-style site (JP-A, 2,500 patients, notes 90 % JA / 10 % EN) and
   one Taiwanese-style site (TW-A, 2,500, notes 90 % zh-TW / 10 % EN), with gold files and the TB-DS-21 §6 checks;
2. joins the two sites into one 5,000-patient hospital (two campuses, one chart-number space) and ingests it into a
   local lake (the CSV adapter and the de-identification the nightly ingest uses);
3. starts the in-process box (orchestrator, mail gateway, stub model) with ``TB_ENV=DEV``: the schedule is on demand
   (FR-OPS-12), so the ingest and the job below run because the demo asks, and the ethics gate is off;
4. signs in to the console as the coordinator, switches to Japanese, opens S2 (``/pilot/protocol``), pastes the
   GOUT-COH criteria and submits: the pasted criteria match the approved ruleset, so FEAS runs at once and the
   browser lands on S3 (``/studies/GOUT-COH/feasibility``); the funnel is printed here.

Everything is synthetic. The GOUT-COH criteria are pasted as the ruleset was authored (zh-TW); the report, mail and
page chrome are Japanese. Pasting a different text compiles a new draft for review instead (approval is step 2).
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
from collections.abc import Mapping, MutableMapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

REF = date(2026, 11, 1)  # synthetic reference date (the data is "as of" the day before)
RULESET = "GOUT-COH"
KEY = b"trialbox-demo-site-key-0123456789abcdef"
# (username, role, mailbox, scope); crc and pi use mailboxes the demo site's settings allow to request FEAS
ACCOUNTS = [
    ("admin", "admin", "admin@hospa.test", {}),
    ("crc", "coordinator", "crc1@hospa.test", {}),
    ("pi", "investigator", "pi@hospa.test", {}),
    ("cra", "cro", "cra@hospa.test", {"affiliation": "cro", "studies": "GZQO,GOUT-COH"}),  # D-380: names its studies
    ("viewer", "viewer", "viewer@hospa.test", {}),
]


def pasted_criteria(ruleset: str = RULESET) -> str:
    """The criteria text a coordinator would paste: the approved ruleset's criteria, one per line, under headings."""
    inc: list[str] = []
    exc: list[str] = []
    for f in sorted((ROOT / "rulesets" / ruleset / "ir").glob("*.json")):
        c = json.loads(f.read_text(encoding="utf-8"))
        (exc if c.get("kind") == "exclusion" else inc).append(c["text"])
    lines = ["選択基準", *[f"{i}. {t}" for i, t in enumerate(inc, 1)]]
    if exc:
        lines += ["", "除外基準", *[f"{i}. {t}" for i, t in enumerate(exc, 1)]]
    return "\n".join(lines) + "\n"


def merge_sites(sites: list[Path], out: Path) -> int:
    """Concatenate the sites' landing tables into one hospital (chart numbers and row ids are already disjoint)."""
    out.mkdir(parents=True, exist_ok=True)
    names = sorted({p.name for s in sites for p in s.glob("*.csv")})
    patients = 0
    for name in names:
        header: list[str] | None = None
        seen: set[str] = set()
        with (out / name).open("w", newline="", encoding="utf-8") as fh:
            w: Any = None
            for s in sites:
                src = s / name
                if not src.exists() or src.stat().st_size == 0:
                    continue
                with src.open(newline="", encoding="utf-8") as fin:
                    r = csv.DictReader(fin)
                    if header is None:
                        header = list(r.fieldnames or [])
                        w = csv.DictWriter(fh, fieldnames=header)
                        w.writeheader()
                    for row in r:
                        if name == "practitioner.csv":  # both campuses share the staff list
                            if row["staff_id"] in seen:
                                continue
                            seen.add(row["staff_id"])
                        w.writerow(row)
                        patients += name == "patient.csv"
    return patients


# the Japanese demo site of scenario J1 (T-503): one hospital in Asia/Tokyo, Japanese page locale, notes in Japanese
# and English only (UX-004: a ja reader never sees zh-TW note text or a Taipei clock)
SITE_JP: dict[str, Any] = {
    "site": {
        "id": "DEMO-J",
        "name": "デモ病院J（合成）",
        "tz": "Asia/Tokyo",
        "locale": "ja",
        "contact": "crc1@hospa.test",
    }
}


# T-513 (UX-003): a cell that is a date or a date-time, as the synthetic hospital's landing tables write them
_DATE_CELL = re.compile(r"(\d{4}-\d{2}-\d{2})([ T]\d{2}:\d{2}(?::\d{2})?)?")
SHIFT_FILE = ".date-shift"  # the number of days the hospital folder's dates were moved by


def data_day() -> date:
    """The synthetic data's own demo day: the box's day after an ingest of :data:`REF` (the PI's first clinic)."""
    return REF + timedelta(days=1)


def shift_dates(folder: Path, days: int) -> int:
    """T-513 (UX-003): move every date and date-time cell of the landing tables in ``folder`` by ``days``, so the
    synthetic hospital reads as if it had been made for another day. Intervals between dates are kept; note text is
    not rewritten. Returns the number of cells moved."""
    moved = 0
    if not days:
        return moved
    step = timedelta(days=days)
    for f in sorted(folder.glob("*.csv")):
        with f.open(newline="", encoding="utf-8") as fh:
            r = csv.DictReader(fh)
            header = list(r.fieldnames or [])
            rows = list(r)
        for row in rows:
            for k, v in row.items():
                m = _DATE_CELL.fullmatch(v or "")
                if m:
                    row[k] = (date.fromisoformat(m.group(1)) + step).isoformat() + (m.group(2) or "")
                    moved += 1
        with f.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=header)
            w.writeheader()
            w.writerows(rows)
    return moved


SITE_LANG_ENV = "TB_DEMO_SITE_LANG"  # DEMO-JA: the language of the demo hospital's records and notes
SITE_LANGS = ("ja", "zh-TW")


def site_profile(profile: str, environ: Mapping[str, str] | None = None) -> str:
    """DEMO-JA: the ``ci`` hospital (a Japanese and a Taiwanese campus) in one language when ``TB_DEMO_SITE_LANG`` is
    ``ja`` (both campuses Japanese-style: ``ci-ja``) or ``zh-TW`` (``ci-zh-TW``); unset keeps both campuses. Other
    profiles have one language already and are kept."""
    value = str((os.environ if environ is None else environ).get(SITE_LANG_ENV) or "").strip()
    if profile != "ci" or not value:
        return profile
    if value not in SITE_LANGS:
        raise SystemExit(f"{SITE_LANG_ENV}={value!r}: use ja or zh-TW (unset: both campuses)")
    return f"ci-{value}"


def stub_reads_site_lang(environ: MutableMapping[str, str] | None = None) -> None:
    """DEMO-JA: on the Japanese site (``TB_DEMO_SITE_LANG=ja``) the stub model also reads the Japanese notes
    (``llm_stub.handlers.NOTE_LANGS_ENV``); without it no GZQO note criterion could pass and every patient would be
    "review". A value set by hand is kept."""
    env = os.environ if environ is None else environ
    if str(env.get(SITE_LANG_ENV) or "").strip() == "ja":
        env.setdefault("TB_LLM_STUB_NOTE_LANGS", "zh-TW,ja")


def build(work: Path) -> tuple[Any, Any, Path, dict[str, Any]]:
    """The demo's box on the ``ci`` hospital (tools.complete_run wraps this one-argument form)."""
    return build_site(work)


def people_mailboxes(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """D-758: the demo VM's people (``TB_DEMO_PEOPLE``, ``name:role`` by commas, as deploy/gcp/demo-vm-boot.sh names
    them) whose role reads patient data, as the mailboxes their accounts get (``<name>@hospa.test``)."""
    raw = str((os.environ if environ is None else environ).get("TB_DEMO_PEOPLE") or "")
    out = []
    for part in (p.strip() for p in raw.split(",")):
        name, _, role = part.partition(":")
        # steps mode (D-1063): name:role+role; a person who may act as investigator or coordinator reads patient data
        if name and {r.strip() for r in role.split("+")} & {"investigator", "coordinator"}:
            out.append(f"{name.strip()}@hospa.test")
    return tuple(out)


def build_site(
    work: Path, profile: str = "ci", settings_update: dict[str, Any] | None = None, day: date | None = None
) -> tuple[Any, Any, Path, dict[str, Any]]:
    """``profile``: the ``tools.synth_hospital`` profile (``ci``: the JP + TW hospital; ``jp-ad``: the Japanese
    memory-clinic site of scenario J1, with ``settings_update=SITE_JP``). ``day`` (T-513): the box's day; the
    hospital's dates are moved so that its data is as of the day before (None: :func:`data_day`, nothing moved)."""
    from adapter.cli import keys_init
    from console.sitestore import SiteStore
    from orchestrator import app as orch_app
    from tb_common.flags import Flags

    from tests.inproc_box import ingest_site, make_box
    from tools import pglocal
    from tools.role_demo import orch_client
    from tools.synth_hospital import run as synth_run

    stub_reads_site_lang()
    synth = work / "synth"
    if not (synth / "summary.json").exists():
        res = synth_run(synth, profile=site_profile(profile), ref_date=REF)
        if not res.passed:
            raise SystemExit("synthetic hospital checks failed:\n" + "\n".join(res.failures))
    summary = json.loads((synth / "summary.json").read_text(encoding="utf-8"))
    hospital = work / "hospital"
    shift = (day - data_day()).days if day is not None else 0
    if not (hospital / "patient.csv").exists():
        merge_sites([synth / s["dir"] for s in summary["sites"]], hospital)
        shift_dates(hospital, shift)
        (hospital / SHIFT_FILE).write_text(f"{shift}\n", encoding="utf-8")
    shift_file = hospital / SHIFT_FILE
    had = int(shift_file.read_text(encoding="utf-8")) if shift_file.exists() else 0
    if had != shift:
        raise SystemExit(f"{work} holds a hospital made for another day (moved {had} days, not {shift}): use --fresh")
    sec = work / "sec"
    site_id = str((settings_update or {}).get("site", {}).get("id") or "DEMO-A")
    shutil.rmtree(work / "box", ignore_errors=True)  # the box (jobs, mail, repo) starts fresh on every run
    # As a real install: the key ceremony, the data folder set, the box made, then the night that publishes the
    # screening inputs. A lake kept from an earlier run is reused only while its install's grant still holds on this
    # box's database; else the install starts over (a new box cannot inherit an old box's grant).
    url = pglocal.for_work(work / "box")
    if (work / "lake").exists() and not install_holds(work, url):
        for name in ("lake", "sec", "screening-inputs"):
            shutil.rmtree(work / name, ignore_errors=True)
    fresh = not (work / "lake").exists()
    sec.mkdir(parents=True, exist_ok=True)
    if fresh and keys_init(sec) != 0:
        raise SystemExit("the site key could not be made")
    # the installed feed is the hospital's folder, so the night's own checks accept it as this site's
    feed = {
        "data_source": {"type": "csv", "path": str(hospital), "mapping": "mapping/tw_core/demo_his.yaml"},
        "registry_source": {"type": "csv", "path": str(hospital / "registry.csv")},
    }
    settings = {**(settings_update or {}), **feed}
    box = make_box(work / "box", work / "lake", sec, day or data_day(), settings_update=settings,
                   extra_list_to=people_mailboxes(),
                   extra_env={"TB_DATA_DIR": str(work), "TB_RULESETS_DIR": str(work / "box" / "repo")})  # fmt: skip
    if fresh:
        Flags(url=box.orch.db.url, audit=box.orch.audit).seed()
        SiteStore(box.orch.db.url).close()
        snapshot = REF - timedelta(days=1) + timedelta(days=shift)
        night = ingest_site(hospital, work / "lake", sec, snapshot.isoformat(), site_id=site_id,
                            screening_site=box.orch.cfg)  # fmt: skip
        if not night.passed:
            raise SystemExit(f"the demo's night did not pass: {night.errors}")
    orch_app._orch = box.orch
    return box, orch_client(orch_app.app), work / "box" / "repo", summary


def site_key(work: Path) -> bytes:
    """The site key the install ceremony of :func:`build_site` made in ``work`` (the lake's pseudonyms)."""
    return (work / "sec" / "site_hmac.key").read_bytes()


def install_holds(work: Path, url: str) -> bool:
    """Whether the grant of the install kept in ``work`` was given on this database's release (gate 4's check)."""
    from tb_common.flags import Flags
    from tb_common.screening_inputs import RestoreClearance, clearance_path, release_id
    from tb_common.study_manifest import load_json

    try:
        grant = RestoreClearance.model_validate(load_json(clearance_path(work).read_bytes()))
        return grant.state == "released" and grant.clearance_id == release_id(Flags(url=url))
    except Exception:
        return False


def reopen_site(work: Path, settings_update: dict[str, Any] | None = None) -> tuple[Any, Any, Path]:
    """T-505b (``tools.demo --keep``): the box of an earlier :func:`build_site` run in ``work``, reopened as it was
    left: the lake, the jobs, the rulesets repo and the audit log are kept, nothing is rebuilt or deleted."""
    from orchestrator import app as orch_app

    from tests.inproc_box import make_box
    from tools.role_demo import orch_client

    if not (work / "lake").exists() or not (work / "box" / "repo").exists():
        raise SystemExit(f"{work} holds no seeded demo to keep; start once without --keep")
    stub_reads_site_lang()
    box = make_box(work / "box", work / "lake", work / "sec", REF + timedelta(days=1), settings_update=settings_update)
    orch_app._orch = box.orch
    return box, orch_client(orch_app.app), work / "box" / "repo"


def fresh_console_db(work: Path) -> str:
    """The run's trial database URL, with the console's stores (schemas ``auth`` and ``site``, D-126) emptied:
    accounts, sessions, marks and site settings start fresh with the box, as the console's files used to."""
    from tb_common.db import Database

    from tools import pglocal

    url = pglocal.for_work(work)
    for name in ("auth", "site"):
        with Database.connect(url, name) as db:
            db.execute(f'DROP SCHEMA "{db.schema}" CASCADE')
    return url


def seed_pi(url: str | None = None, pi: str = "pi", studies: tuple[str, ...] = ()) -> None:
    """D-380 (ROLE-008): only the PI a study's delegation log names acts as PI, so the demo writes the signed log's
    PI entry for the demo investigator on every demo study (or on ``studies``) that has none (as the steward
    would)."""
    from console.teamstore import TeamStore

    team = TeamStore(url)
    try:
        for rs in studies or tuple(sorted(p.name for p in (ROOT / "rulesets").iterdir() if (p / "ir").is_dir())):
            if team.pi_of(rs, date.today()) is None:
                team.add_entry(rs, username=pi, name="PI (demo)", role="pi", tasks=(), start="2026-01-01",
                               end=None, training_day="2025-06-01", training_ref="demo seed (synthetic)",
                               by="demo-seed", at="2026-01-01T00:00:00+00:00")  # fmt: skip
    finally:
        team.close()


def console(work: Path, box: Any, client: Any, repo: Path, password: str) -> Any:
    from console.app import create_app
    from console.auth import UserStore
    from tb_common.audit import AuditLog

    from tools.role_demo import InprocBackend

    shutil.rmtree(work / "console", ignore_errors=True)  # the console's files start fresh with the box
    (work / "console").mkdir(parents=True)
    url = fresh_console_db(work)
    users = UserStore(url)  # and so do its accounts and sessions
    for name, role, mailbox, scope in ACCOUNTS:
        users.create(name, role, password, mailbox)  # type: ignore[arg-type]
        if scope:
            users.set_scope(name, **scope)
    seed_pi(url)
    env = {
        "TB_ENV": "DEV",
        "TB_CONSOLE_PILOT": "1",
        "TB_DATA_CLASS": "D0",
        "TB_CONSOLE_DIR": str(work / "console"),
        "TB_CONSOLE_ADMIN_EMAIL": "admin@hospa.test",
        "TB_CONSOLE_SECURE_COOKIE": "0",
    }
    return create_app(env, backend=InprocBackend(box, client, repo), audit=AuditLog(box.audit_dir), users=users)


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "no csrf token on the page"
    return m.group(1)


def paste_and_report(app: Any, password: str, lang: str = "ja", ruleset: str = RULESET) -> tuple[str, str]:
    """Drive S2 -> S3 through the console as the coordinator; returns (final URL path, S3 HTML)."""
    from fastapi.testclient import TestClient

    c = TestClient(app)
    tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert tok
    r = c.post("/login", data={"username": "crc", "password": password, "login_csrf": tok.group(1)})
    assert r.status_code == 200, r.status_code
    c.post("/lang", data={"csrf": _csrf(c.get("/home").text), "lang": lang, "back": "/pilot/protocol"})
    form = c.get("/pilot/protocol")
    assert 'name="criteria"' in form.text
    r = c.post(
        "/pilot/protocol",
        data={"csrf": _csrf(form.text), "ruleset": ruleset, "criteria": pasted_criteria(ruleset)},
    )
    assert r.status_code == 200, (r.status_code, re.sub(r"<[^>]+>", " ", r.text)[-1500:])
    return r.url.path, r.text


def funnel(box: Any, ruleset: str = RULESET) -> dict[str, Any]:
    job = box.orch.db.find(type_="FEAS", ruleset=ruleset)[0]
    out = next(o for o in job.outputs or [] if o.filename.endswith(".json") and o.filename.startswith("feasibility_"))
    return {"job": job, "result": json.loads(box.store.get(out.minio_key))}


def main(argv: list[str] | None = None) -> int:
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR") or scratch_root() / "tb-feas-demo"))
    ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--serve", action="store_true", help="keep the console up after the run")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--fresh", action="store_true", help="delete --dir first")
    a = ap.parse_args(argv)
    if a.fresh and a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True, exist_ok=True)
    box, client, repo, summary = build(a.dir)
    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    app = console(a.dir, box, client, repo, password)
    path, _html = paste_and_report(app, password, a.lang)
    got = funnel(box)
    res, job = got["result"], got["job"]
    print(f"synthetic hospital: {sum(s['patients'] for s in summary['sites'])} patients ({a.dir / 'hospital'})")
    print(f"S2 -> {path}  job {job.job_id} {job.state}  snapshot {res['snapshot']}  start n={res['start_n']}")
    for f in res["funnel"]:
        print(f"  {f['criterion_id']:<18} {f['label']:<16} remaining {f['remaining']!s:>6}  unknown {f['unknown']}")
    if a.serve:
        import uvicorn

        print(f"console on http://{a.host}:{a.port}{path}  accounts: {', '.join(a[0] for a in ACCOUNTS)}")
        if not os.environ.get("TB_DEMO_PASSWORD"):
            print(f"password (all accounts): {password}")
        uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    return 0 if job.state == "done" and path == f"/studies/{RULESET}/feasibility" else 1


if __name__ == "__main__":
    raise SystemExit(main())
