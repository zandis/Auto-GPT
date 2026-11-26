"""Site go-live acceptance (SPEC §11.2) — one subcommand per criterion; each writes ``<out>/<check>.json`` and
``report`` assembles them into ``acceptance_report.md``. DECISIONS D-83.

    python tools/acceptance.py ingest     --report <lake>/ndjson/<snapshot>/ingest_report.json
    python tools/acceptance.py feas       --system <feasibility …raw.json> --manual manual_counts.csv
    python tools/acceptance.py screen-sample --candidates <candidates.json> --ruleset rulesets/GZQO --scoped scoped.txt
    python tools/acceptance.py screen     --candidates <candidates.json> --ruleset rulesets/GZQO \
                                          --adjudication adjudication.xlsx --key key.json
    python tools/acceptance.py nav        --lake <dir|url> --ruleset rulesets/RA-BIO
    python tools/acceptance.py twpas      twpas_validation_ONC-OSI.json [...]
    python tools/acceptance.py reproduce  --results rerun.jsonl     # from `python -m orchestrator.rerun <job ids>`
    python tools/acceptance.py audit      --dir <audit dir>
    python tools/acceptance.py capacity   --jobs <one night's jobs, JSON list> [--night <name>] [--tz <zone>]
    python tools/acceptance.py power-cycle --doctor <doctor --json, after the power came back> --audit-dir <dir>
    python tools/acceptance.py key-escrow --secrets <the secrets folder> [--deploy deploy]
    python tools/acceptance.py report     [--out acceptance/]

``screen-sample`` draws the blinded adjudication set (≥100 patients in four strata: high, review, excluded, scoped but
not listed) and writes the CRC workbook plus a separate key; ``screen`` unblinds it and computes trial-level
sensitivity/specificity (weighted by the inverse sampling fraction of each stratum), criterion-level agreement
(structured and note separately) and CRC minutes per candidate.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services", "."):
    sys.path.insert(0, str(ROOT / _p))

TARGETS = {
    "ingest": "nightly run passed; HL7 validator sample errors < 0.5 %",
    "feas": "each funnel step within ±15 % of the manual count, every difference explained",
    "screen_trial": "sens ≥ 75 % / spec ≥ 95 % at the default tier; sens ≥ 95 % at the review tier",
    "screen_criterion": "criterion agreement: structured ≥ 98 %, note ≥ 90 %",
    "screen_time": "CRC verification ≤ 10 min per candidate",
    "nav": "agreement ≥ 85 % on approvals; 0 eligible verdicts with a coded hard exclusion",
    "twpas": "0 validator errors; NHI pre-check passes on the test set",
    "reproduce": "same inputs + versions → identical output hashes (100 %)",
    "audit": "audit chain verifies",
    # T-317a (D-730)
    "capacity": "one night's chain ends done before the first morning notice, with at least 1 h to spare",
    "power_cycle": "after a power cut: trialbox doctor has no FAIL and the audit chain verifies",
    # INT-M5 (R22-33, D-894): a TPM-sealed KEK opens on new hardware only through its escrow set
    "key_escrow": "the KEK opens on new hardware: a TPM-sealed KEK has an escrow set on the newest ceremony record",
}
SPARE_H = 1.0  # T-317a (D-730): the capacity criterion's margin before the first morning notice
TERMINAL = ("done", "failed")
STRATA = ("high", "review", "excluded", "not_listed")


def _save(out: Path, name: str, body: dict[str, Any]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    body = {"check": name, "target": TARGETS.get(name, ""), **body}
    (out / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{name}: {'PASS' if body['passed'] else 'FAIL'} — {body.get('summary', '')}")
    return 0 if body["passed"] else 1


# ----------------------------------------------------------------------------------------------------------- checks
def check_ingest(report: dict[str, Any]) -> dict[str, Any]:
    v = report.get("validation") or {}
    pct = float(v.get("error_pct") or 0.0)
    ok = bool(report.get("passed")) and pct < 0.5
    return {
        "passed": ok,
        "summary": f"snapshot {report.get('snapshot')}, validator {v.get('validator')} {v.get('sampled')} sampled, "
        f"{pct:.2f} % errors",
        "errors": report.get("errors") or [],
    }


def check_feas(system: Path, manual: Path, tolerance: float = 15.0) -> dict[str, Any]:
    import csv

    from tools.funnel_compare import compare, system_counts

    rows = compare(
        system_counts(json.loads(system.read_text(encoding="utf-8"))),
        list(csv.DictReader(manual.open(encoding="utf-8"))),
        tolerance,
    )
    bad = [r for r in rows if r.diff_pct is not None and abs(r.diff_pct) > tolerance and not r.explanation.strip()]
    return {
        "passed": not bad and bool(rows),
        "summary": f"{len(rows)} steps compared, {len(bad)} outside ±{tolerance:g} % without an explanation",
        "steps": [r.__dict__ for r in rows],
    }


def screen_sample(
    candidates: dict[str, Any], scoped: list[str], n: int, seed: int = 11
) -> tuple[list[str], dict[str, Any]]:
    """Stratified draw: proportional to stratum size, at least min(10, size) per stratum, total ≥ n."""
    tiers = {r["pid"]: r["tier"] for r in candidates["rows"]}
    pools: dict[str, list[str]] = {s: [] for s in STRATA}
    for pid, tier in sorted(tiers.items()):
        pools[tier if tier in pools else "excluded"].append(pid)
    pools["not_listed"] = sorted(set(scoped) - set(tiers))
    total = sum(len(v) for v in pools.values())
    rng = random.Random(seed)
    take: dict[str, list[str]] = {}
    for s, pids in pools.items():
        k = min(len(pids), max(min(10, len(pids)), round(n * len(pids) / max(total, 1))))
        take[s] = sorted(rng.sample(pids, k))
    order = [p for s in STRATA for p in take[s]]
    rng.shuffle(order)  # blinded: the CRC sees no stratum order
    key = {"seed": seed, "strata": {s: {"population": len(pools[s]), "sampled": take[s]} for s in STRATA}}
    return order, key


def write_adjudication(pids: list[str], criteria: list[tuple[str, str]], mrns: dict[str, str]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation
    from tb_common.deterministic import normalize_ooxml

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "adjudication"
    head = ["pid", "MRN", "crc_eligible (Y/N)", "minutes", "comment"] + [f"{cid} {label}" for cid, label in criteria]
    ws.append(head)
    for p in pids:
        ws.append([p, mrns.get(p, ""), None, None, None] + [None] * len(criteria))
    dv = DataValidation(type="list", formula1='"pass,fail,unknown"', allow_blank=True)
    ws.add_data_validation(dv)
    if criteria:
        from openpyxl.utils import get_column_letter

        dv.add(f"F2:{get_column_letter(5 + len(criteria))}{len(pids) + 1}")
    buf = io.BytesIO()
    wb.save(buf)
    return normalize_ooxml(buf.getvalue())


def read_adjudication(data: bytes) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(data), data_only=True)["adjudication"]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h or "") for h in rows[0]]
    out = []
    for r in rows[1:]:
        d = dict(zip(head, r, strict=False))
        if not d.get("pid"):
            continue
        crit = {h.split(" ", 1)[0]: str(d[h]).strip().lower() for h in head[5:] if d.get(h) not in (None, "")}
        eligible = str(d.get("crc_eligible (Y/N)") or "").strip().upper()
        out.append(
            {
                "pid": str(d["pid"]),
                "eligible": None if eligible not in ("Y", "N") else eligible == "Y",
                "minutes": float(str(d["minutes"])) if d.get("minutes") not in (None, "") else None,
                "criteria": crit,
            }
        )
    return out


def ruleset_criteria(ruleset_dir: Path) -> dict[str, dict[str, str]]:
    """Criterion id -> {class, label} from the approved ruleset's IR (candidate rows carry only id + verdict)."""
    out: dict[str, dict[str, str]] = {}
    for path in sorted((ruleset_dir / "ir").glob("*.json")):
        ir = json.loads(path.read_text(encoding="utf-8"))
        out[ir["id"]] = {"class": str(ir.get("class") or ""), "label": str(ir.get("label") or ir["text"][:40])}
    if not out:
        raise SystemExit(f"{ruleset_dir}: no ir/*.json (give the approved ruleset directory)")
    return out


def check_screen(
    candidates: dict[str, Any],
    adjudication: list[dict[str, Any]],
    key: dict[str, Any],
    criteria: dict[str, dict[str, str]],
) -> dict[str, Any]:
    rows = {r["pid"]: r for r in candidates["rows"]}
    stratum_of = {p: s for s, v in key["strata"].items() for p in v["sampled"]}
    weight = {s: (v["population"] / len(v["sampled"])) if v["sampled"] else 0.0 for s, v in key["strata"].items()}
    judged = [a for a in adjudication if a["eligible"] is not None]
    conf: dict[str, dict[str, float]] = {t: {"tp": 0, "fn": 0, "tn": 0, "fp": 0} for t in ("default", "review")}
    for a in judged:
        w = weight.get(stratum_of.get(a["pid"], "not_listed"), 1.0)
        tier = rows.get(a["pid"], {}).get("tier", "not_listed")
        for name, positive in (("default", tier == "high"), ("review", tier in ("high", "review"))):
            cell = ("tp" if positive else "fn") if a["eligible"] else ("fp" if positive else "tn")
            conf[name][cell] += w

    def rate(num: float, den: float) -> float | None:
        return round(100.0 * num / den, 1) if den else None

    sens_d = rate(conf["default"]["tp"], conf["default"]["tp"] + conf["default"]["fn"])
    spec_d = rate(conf["default"]["tn"], conf["default"]["tn"] + conf["default"]["fp"])
    sens_r = rate(conf["review"]["tp"], conf["review"]["tp"] + conf["review"]["fn"])
    # criterion level (system verdicts exist for listed patients)
    agree = {"structured": [0, 0], "note": [0, 0]}
    for a in adjudication:
        sysrow = rows.get(a["pid"])
        if not sysrow:
            continue
        verdicts = {v["id"]: v for v in sysrow["criteria"]}
        for cid, crc in a["criteria"].items():
            v = verdicts.get(cid)
            if v is None or crc not in ("pass", "fail", "unknown"):
                continue
            klass = (criteria.get(cid) or {}).get("class")
            if klass not in ("structured", "note"):  # human criteria are never decided by the box
                continue
            agree[klass][1] += 1
            agree[klass][0] += int(v["verdict"] == crc)
    ag = {k: rate(x, n) for k, (x, n) in agree.items()}
    minutes = [a["minutes"] for a in adjudication if a["minutes"] is not None]
    med = round(statistics.median(minutes), 1) if minutes else None
    trial_ok = (sens_d or 0) >= 75 and (spec_d or 0) >= 95 and (sens_r or 0) >= 95 and len(judged) >= 100
    crit_ok = (ag["structured"] is None or ag["structured"] >= 98) and (ag["note"] is None or ag["note"] >= 90)
    return {
        "trial": {
            "passed": trial_ok,
            "summary": f"{len(judged)} adjudicated; default tier sens {sens_d} % spec {spec_d} %; review tier sens "
            f"{sens_r} %",
            "confusion_weighted": conf,
        },
        "criterion": {
            "passed": crit_ok and any(n for _, n in agree.values()),
            "summary": f"structured {ag['structured']} % (n={agree['structured'][1]}), note {ag['note']} % "
            f"(n={agree['note'][1]})",
        },
        "time": {
            "passed": med is not None and med <= 10,
            "summary": f"median {med} min over {len(minutes)} candidates",
        },
    }


def check_twpas(reports: list[dict[str, Any]]) -> dict[str, Any]:
    bundles = [b for r in reports for b in r.get("bundles", []) if b.get("file")]
    errors = sum(len(b.get("validator_errors") or []) for b in bundles)
    pre_fail = [b["pid"] for b in bundles if not (b.get("precheck") or {}).get("passed")]
    validators = {r.get("validator") for r in reports}
    ok = bool(bundles) and errors == 0 and not pre_fail and validators == {"hl7-validator"}
    return {
        "passed": ok,
        "summary": f"{len(bundles)} bundles, {errors} validator errors ({', '.join(sorted(map(str, validators)))}), "
        f"{len(pre_fail)} pre-check failures",
    }


def check_reproduce(results: list[dict[str, Any]]) -> dict[str, Any]:
    same = [r for r in results if r.get("identical")]
    files = sum(len(r.get("files") or []) for r in results)
    return {
        "passed": bool(results) and len(same) == len(results),
        "summary": f"{len(same)}/{len(results)} jobs identical over {files} output files",
        "jobs": [{k: r.get(k) for k in ("job_id", "type", "identical", "error")} for r in results],
    }


def _night_jobs(jobs: list[dict[str, Any]], night: str | None) -> tuple[str | None, list[dict[str, Any]]]:
    """The jobs of one night of the night runner (orchestrator.night): the chain's jobs carry ``options.night``; the
    night's ingest is the one whose published generation or snapshot date names it. ``night`` None: the newest."""
    named = [j for j in jobs if (j.get("options") or {}).get("night")]
    if night is None:
        if not named:
            return None, []
        night = str(max(named, key=lambda j: str(j.get("received_at")))["options"]["night"])
    chain = [j for j in named if str(j["options"]["night"]) == night]
    for j in jobs:
        opts = j.get("options") or {}
        if j.get("type") == "INGEST" and night in (str(opts.get("lake_generation") or ""), str(j.get("snapshot_date"))):
            chain.append(j)
    return night, chain


def check_capacity(
    jobs: list[dict[str, Any]], *, tz: str, ready_by: str, night: str | None = None, spare_h: float = SPARE_H
) -> dict[str, Any]:
    """T-317a (D-730): one night's chain ended ``done`` before the first morning notice (``ready_by``, the site's
    clock) that follows the night's start, with ``spare_h`` hours to spare."""
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    name, chain = _night_jobs(jobs, night)
    if not chain:
        return {"passed": False, "summary": f"no job of the night {night or '(none named)'} in the export"}
    zone = ZoneInfo(tz)
    not_done = sorted({str(j.get("state")) for j in chain if j.get("state") != "done"})
    if not_done:
        return {"passed": False, "night": name, "jobs": len(chain),
                "summary": f"the night {name}: jobs ended {', '.join(not_done)}, not done"}  # fmt: skip
    start = min(datetime.fromisoformat(str(j["received_at"])) for j in chain).astimezone(zone)
    end = max(datetime.fromisoformat(str(j["updated_at"])) for j in chain).astimezone(zone)
    hh, mm = (int(x) for x in ready_by.split(":"))
    deadline = datetime.combine(start.date(), time(hh, mm), zone)
    if deadline <= start:
        deadline += timedelta(days=1)  # a night that starts after the notice time is ready by the next morning
    spare = round((deadline - end).total_seconds() / 3600, 2)
    ok = spare >= spare_h
    return {
        "passed": ok,
        "night": name,
        "jobs": len(chain),
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "ready_by": deadline.isoformat(),
        "spare_hours": spare,
        "summary": f"the night {name}: {len(chain)} jobs done by {end:%H:%M}, {spare} h to spare before "
        f"{deadline:%H:%M} (at least {spare_h} h)",
    }


def check_power_cycle(doctor: list[dict[str, Any]], *, chain_ok: bool) -> dict[str, Any]:
    """T-317a (D-730): after the power came back (RUNBOOK §22, a planned power cut), ``trialbox doctor --json`` has
    no FAIL and the audit chain verifies. An empty doctor answer is no answer."""
    if not doctor:
        return {"passed": False, "summary": "the doctor gave no checks"}
    fails = [str(c.get("name")) for c in doctor if c.get("status") == "FAIL"]
    warns = sum(1 for c in doctor if c.get("status") == "WARN")
    ok = not fails and chain_ok
    said = f"FAIL: {', '.join(fails)}" if fails else "no FAIL"
    return {
        "passed": ok,
        "fails": fails,
        "summary": f"{len(doctor)} doctor checks, {said}, {warns} WARN; audit chain "
        f"{'verifies' if chain_ok else 'does not verify'}",
    }


def check_key_escrow(secrets: Path, deploy: Path) -> dict[str, Any]:
    """INT-M5 (R22-33): go-live is refused while a TPM-sealed box has no escrow set its custodians signed
    (``tools.key_escrow.go_live``; fails closed)."""
    from tools import key_escrow

    ok, why = key_escrow.go_live(secrets, deploy)
    return {"passed": ok, "summary": why}


def report(out: Path) -> str:
    lines = [
        "# TrialBox site acceptance (SPEC §11.2)",
        "",
        "| check | target | result | detail |",
        "| --- | --- | --- | --- |",
    ]
    passed = True
    for name, target in TARGETS.items():
        f = out / f"{name}.json"
        if not f.exists():
            lines.append(f"| {name} | {target} | not run | |")
            passed = False
            continue
        body = json.loads(f.read_text(encoding="utf-8"))
        passed = passed and body["passed"]
        verdict = "PASS" if body["passed"] else "FAIL"
        lines.append(f"| {name} | {target} | {verdict} | {body.get('summary', '')} |")
    lines += ["", f"Overall: {'PASS' if passed else 'NOT YET'}"]
    md = "\n".join(lines) + "\n"
    (out / "acceptance_report.md").write_text(md, encoding="utf-8")
    return md


# -------------------------------------------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("acceptance"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest")
    s.add_argument("--report", type=Path, required=True)
    s = sub.add_parser("feas")
    s.add_argument("--system", type=Path, required=True)
    s.add_argument("--manual", type=Path, required=True)
    s = sub.add_parser("screen-sample")
    s.add_argument("--candidates", type=Path, required=True)
    s.add_argument("--scoped", type=Path, help="text file: one scoped pid per line")
    s.add_argument("--mrns", type=Path, help="CSV pid,mrn for the CRC workbook (internal only)")
    s.add_argument("--n", type=int, default=120)
    s.add_argument("--ruleset", type=Path, required=True, help="approved ruleset directory (criterion labels)")
    s = sub.add_parser("screen")
    s.add_argument("--candidates", type=Path, required=True)
    s.add_argument("--ruleset", type=Path, required=True, help="approved ruleset directory (criterion classes)")
    s.add_argument("--adjudication", type=Path, required=True)
    s.add_argument("--key", type=Path, required=True)
    s = sub.add_parser("nav")
    s.add_argument("--lake", required=True)
    s.add_argument("--ruleset", type=Path, required=True)
    s.add_argument("--months", type=int, default=12)
    s = sub.add_parser("twpas")
    s.add_argument("reports", type=Path, nargs="+")
    s = sub.add_parser("reproduce")
    s.add_argument("--results", type=Path, required=True, help="JSON lines from `python -m orchestrator.rerun`")
    s = sub.add_parser("audit")
    s.add_argument("--dir", type=Path, required=True)
    s = sub.add_parser("capacity")
    s.add_argument("--jobs", type=Path, required=True, help="the night's jobs as the job API lists them (JSON list)")
    s.add_argument("--night", help="the night's name (its generation or snapshot date); default the newest")
    s.add_argument("--tz", help="the site's zone; default TB_TZ")
    s.add_argument("--ready-by", help="the first morning notice; default TB_NOTICE_N1_AT")
    s = sub.add_parser("power-cycle")
    s.add_argument("--doctor", type=Path, required=True, help="trialbox doctor --json, after the power came back")
    s.add_argument("--audit-dir", type=Path, required=True)
    s = sub.add_parser("key-escrow")
    s.add_argument("--secrets", type=Path, required=True, help="the box's secrets folder (on the host: its volume)")
    s.add_argument("--deploy", type=Path, default=Path("deploy"), help="the deploy folder (its site/ records)")
    sub.add_parser("report")
    a = ap.parse_args(argv)
    out: Path = a.out
    if a.cmd == "ingest":
        return _save(out, "ingest", check_ingest(json.loads(a.report.read_text(encoding="utf-8"))))
    if a.cmd == "feas":
        return _save(out, "feas", check_feas(a.system, a.manual))
    if a.cmd == "screen-sample":
        cands = json.loads(a.candidates.read_text(encoding="utf-8"))
        scoped = a.scoped.read_text(encoding="utf-8").split() if a.scoped else []
        pids, key = screen_sample(cands, scoped, a.n)
        mrns = {}
        if a.mrns:
            import csv

            mrns = {r["pid"]: r["mrn"] for r in csv.DictReader(a.mrns.open(encoding="utf-8"))}
        info = ruleset_criteria(a.ruleset)
        crit = sorted({(v["id"], info.get(v["id"], {}).get("label", "")) for r in cands["rows"] for v in r["criteria"]})
        out.mkdir(parents=True, exist_ok=True)
        (out / "adjudication.xlsx").write_bytes(write_adjudication(pids, crit, mrns))
        (out / "adjudication_key.json").write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
        print(f"{len(pids)} patients to adjudicate: {out / 'adjudication.xlsx'} (key kept apart)")
        return 0
    if a.cmd == "screen":
        scr = check_screen(
            json.loads(a.candidates.read_text(encoding="utf-8")),
            read_adjudication(a.adjudication.read_bytes()),
            json.loads(a.key.read_text(encoding="utf-8")),
            ruleset_criteria(a.ruleset),
        )
        rc = _save(out, "screen_trial", scr["trial"])
        rc |= _save(out, "screen_criterion", scr["criterion"])
        return rc | _save(out, "screen_time", scr["time"])
    if a.cmd == "nav":
        from embed_service.embedder import HashEmbedder
        from lake.client import LakeHttp, LakeLocal
        from tb_common.ruleset import Ruleset

        from tools.nav_retro import retro

        lake: Any = LakeHttp(a.lake) if a.lake.startswith("http") else LakeLocal(Path(a.lake), HashEmbedder())
        from datetime import date

        rep = retro(lake, Ruleset.load(a.ruleset), date.fromisoformat(lake.snapshot()), a.months)
        ok = (rep["agreement_on_approvals"] or 0) >= 0.85 and not rep["eligible_with_coded_hard_exclusion"]
        return _save(
            out,
            "nav",
            {
                "passed": ok,
                "summary": f"{rep['decided']} decided applications; agreement on approvals "
                f"{rep['agreement_on_approvals']}; coded-exclusion violations "
                f"{len(rep['eligible_with_coded_hard_exclusion'])}",
            },
        )
    if a.cmd == "twpas":
        return _save(out, "twpas", check_twpas([json.loads(p.read_text(encoding="utf-8")) for p in a.reports]))
    if a.cmd == "reproduce":
        lines = [json.loads(x) for x in a.results.read_text(encoding="utf-8").splitlines() if x.strip()]
        return _save(out, "reproduce", check_reproduce(lines))
    if a.cmd == "audit":
        from tb_common.audit import verify

        chain = verify(a.dir)
        return _save(out, "audit", {"passed": chain.ok, "summary": f"{chain.lines} events, {chain.files} files"})
    if a.cmd == "capacity":
        import os

        from tb_common.config import NO_SITE_TZ, ConfigError, site_tz

        jobs = json.loads(a.jobs.read_text(encoding="utf-8"))
        ready = a.ready_by or (os.environ.get("TB_NOTICE_N1_AT") or "07:00").strip()
        try:
            tz = a.tz or site_tz(None)
        except ConfigError as exc:
            if str(exc) != NO_SITE_TZ:
                raise
            raise SystemExit(
                "the site's time zone is not set (use --tz or set TB_TZ) / "
                "尚未設定站台時區（請使用 --tz 或設定 TB_TZ） / "
                "サイトのタイムゾーンが未設定です（--tz または TB_TZ で指定してください）"
            ) from None
        return _save(out, "capacity", check_capacity(jobs, tz=tz, ready_by=ready, night=a.night))
    if a.cmd == "power-cycle":
        from tb_common.audit import verify

        doctor = json.loads(a.doctor.read_text(encoding="utf-8"))
        return _save(out, "power_cycle", check_power_cycle(doctor, chain_ok=verify(a.audit_dir).ok))
    if a.cmd == "key-escrow":
        return _save(out, "key_escrow", check_key_escrow(a.secrets, a.deploy))
    print(report(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
