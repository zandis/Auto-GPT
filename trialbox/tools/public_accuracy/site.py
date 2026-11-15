"""The item builder: a :class:`~tools.public_accuracy.sets.Bundle` -> what a site's box screens, and the gold apart.

``<out>/site/`` is all the box is given:

* ``hospital/`` the hospital CSV feed (``patient``, ``encounter``, ``note``, ``diagnosis``, ``appointment``,
  ``practitioner``): the landing format ``tools/public_site.py`` writes and ``services/adapter/mapping/tw_core/
  demo_his.yaml`` maps (the CGRD-style feed of a site). One patient per source note, the note verbatim, attached to one
  outpatient visit with a chart clinician; no diagnosis row is derived (the note is the whole chart, so every
  condition criterion is the note judge's to answer).
* ``protocols/<RULESET>.txt`` each trial's eligibility text as a protocol (title, the source's inclusion lines, the
  ``placed`` age and sex lines, the exclusion lines), under headings in the protocol's own language. The box compiles
  it (``ir_extract``, ``concept_map``) when a coordinator mails it (``FEAS <RULESET>`` with the file) or pastes it.
* ``profiles/<RULESET>.yaml`` the study's site profile: SCREEN looks at the patients booked with the study's own
  investigator (one investigator per trial, ``P1xxxx``), so a screen of a trial reads exactly the patients the gold
  judged for it, through the product's own scope rule (``screen.scope_patients``), not a list handed in.

``<out>/gold/`` is never given to the box: ``pairs.jsonl``, ``criteria.jsonl``, ``compile_gold.json`` and
``ids.json`` (source ids -> chart numbers and ruleset ids). The scorer joins the box's answers to it by ids only, after
the run. Placed values (chart numbers, visit and appointment dates, birth month, staff) are listed in
``site/PROVENANCE.md`` as public_site does.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.public_accuracy.sets import Bundle, Trial

REF = date(2026, 11, 1)  # the snapshot day of a built site (as tools.public_site.REF)
CHART_DOCTOR = ("P00001", "Chart clinician (public-data site)", "MED")
MRN0 = 71000000  # chart numbers are placed: 8 digits (the box's mrn rule), outside public_site's 70000000 range
PI0 = 10001  # investigators P10001...: one per trial, the study's screen scope
RULESET_ID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
# The installed box's accuracy run puts several sets on one box: each set gets its own range of chart numbers (8
# digits; the largest set holds 500 patients), of investigator ids (TREC 2021+2022 at 3,000 pairs needs 2,133) and a
# ruleset prefix (the same NCT trial is in TREC and SIGIR). The in-process dry run builds one set and uses none.
SET_OFFSETS: dict[str, tuple[int, int, str]] = {
    name: (MRN0 + 100000 * i, PI0 + 3000 * i, prefix)
    for i, (name, prefix) in enumerate(
        (("trec", "T"), ("trec2023", "U"), ("sigir", "S"), ("tfda", "F"), ("jrct", "J"), ("chia", "C"),
         ("tcga", "G"), ("jmed", "M"), ("aci", "A"), ("maccrobat", "B"), ("opentw", "O"), ("pmc_zh", "Z")),
        1,
    )
}  # fmt: skip
HEADINGS = {
    "en": ("Inclusion criteria", "Exclusion criteria"),
    "ja": ("選択基準", "除外基準"),
    "zh-Hant": ("納入條件", "排除條件"),
    "zh-Hans": ("纳入标准", "排除标准"),
}


def ruleset_ids(trials: dict[str, Trial], prefix: str = "") -> dict[str, str]:
    """Trial key -> the box's ruleset id (1-16 letters, digits, ``-``, ``_``): the key itself when it fits (an NCT id,
    ``TCGA-BRCA``), else a short prefix and a number (``TW0001`` for a TFDA protocol, ``JP0001`` for jRCT).
    ``prefix`` (a few letters) goes in front of every id: several sets on one box (the installed box's accuracy run)
    may hold the same NCT trial, and each set's compile and screen must stay its own."""
    if prefix and not RULESET_ID.match(prefix):
        raise ValueError(f"ruleset prefix {prefix!r}: letters, digits, - and _ only")
    out: dict[str, str] = {}
    n: dict[str, int] = {}
    for key in sorted(trials):
        if RULESET_ID.match(prefix + key):
            out[key] = prefix + key
            continue
        short = {"TFDA": "TW", "jRCT": "JP"}.get(key.split(":")[0], "PA")
        n[short] = n.get(short, 0) + 1
        out[key] = f"{prefix}{short}{n[short]:04d}"
        if not RULESET_ID.match(out[key]):
            raise ValueError(f"ruleset id {out[key]!r} is longer than 16 characters: a shorter prefix")
    return out


def protocol_text(t: Trial) -> str:
    inc_h, exc_h = HEADINGS.get(t.lang, HEADINGS["en"])
    inc = [*t.inclusion, *t.placed]
    lines = [t.title or t.key, "", inc_h, *[f"{i}. {x}" for i, x in enumerate(inc, 1)]]
    if t.exclusion:
        lines += ["", exc_h, *[f"{i}. {x}" for i, x in enumerate(t.exclusion, 1)]]
    return "\n".join(lines) + "\n"


def profile_yaml(ruleset: str, title: str, pi: str) -> str:
    safe = json.dumps(title[:120], ensure_ascii=False)
    return (
        f"# Site profile of a public accuracy study (tools/public_accuracy): {ruleset}. Not a study of this site.\n"
        "kind: trial\n"
        f"title: {safe}\n"
        f'trial_alias: "{ruleset}"\n'
        'sponsor: "public data (accuracy run)"\n'
        'protocol_version: "1.0"\n'
        "index_date_rule: run_date\n"
        "scopes:\n"
        "  feas: {population: hospital, lookback_months: 36}\n"
        f'  screen: {{practitioners: ["{pi}"], appointment_window_days: 180, departments: ["MED"],\n'
        "           recent_encounter_months: 12, microbatch_window_days: 14}\n"
        "routing:\n"
        '  aggregate_to: ["crc1@hospa.test"]\n'
        '  list_to: ["crc1@hospa.test"]\n'
        "thresholds: {tier_high_confidence: 0.75, small_cell: 5}\n"
    )


def _write(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    # UTF-8 with a BOM, as a hospital's export often is: without one the adapter weighs the code page, and an English
    # note file with few non-ASCII characters was quarantined as "cannot be told for certain" (dry run 2026-11-14)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def build(
    bundle: Bundle, out: Path, ref: date = REF, *, mrn0: int = MRN0, pi0: int = PI0, rs_prefix: str = ""
) -> dict[str, Any]:
    """Write ``out/site`` (what the box is given) and ``out/gold`` (what only the scorer reads). Returns the counts.
    ``ref`` is the site's day (the installed box screens on its own calendar day, so its accuracy run builds on that
    day); ``mrn0``, ``pi0`` and ``rs_prefix`` keep the chart numbers, investigators and rulesets of several sets on one
    box apart (:data:`SET_OFFSETS`)."""
    site, gold = out / "site", out / "gold"
    hosp, protos, profiles = site / "hospital", site / "protocols", site / "profiles"
    for d in (hosp, protos, profiles, gold):
        d.mkdir(parents=True, exist_ok=True)
    rs = ruleset_ids(bundle.trials, rs_prefix)
    pis = {key: f"P{pi0 + i}" for i, key in enumerate(sorted(bundle.trials))}
    mrns = {key: f"{mrn0 + i}" for i, key in enumerate(sorted(bundle.patients), 1)}
    if len(str(mrn0 + len(mrns))) != 8:
        raise ValueError(f"chart numbers from {mrn0} for {len(mrns)} patients leave the 8 digits of the box's rule")
    pats, encs, notes, appts = [], [], [], []
    for i, (key, p) in enumerate(sorted(bundle.patients.items()), 1):
        mrn = mrns[key]
        visit = datetime.combine(ref - timedelta(days=7 + (i * 37) % 300), datetime.min.time()).replace(hour=10)
        birth = date(visit.year - p.age - (1 if visit.month < 7 else 0), 7, 1).isoformat() if p.age is not None else ""
        pats.append([mrn, "", "", birth, p.sex or "", "", ""])
        enc = f"E{mrn}"
        encs.append([enc, mrn, visit.strftime("%Y-%m-%d %H:%M:%S"), "MED", CHART_DOCTOR[0], "OPD"])
        ntype = "pathology" if bundle.set == "tcga" else "consult"
        notes.append([f"N{mrn}", mrn, enc, (visit + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), ntype, p.text])
    if not pats:  # a compile-only set (TFDA, jRCT, Chia): one placeholder chart so the box ingests a snapshot
        mrn = f"{mrn0}"
        pats.append([mrn, "", "", "", "", "", ""])
        seen = f"{(ref - timedelta(days=7)).isoformat()} 10:00:00"
        encs.append([f"E{mrn}", mrn, seen, "MED", CHART_DOCTOR[0], "OPD"])
        notes.append([f"N{mrn}", mrn, f"E{mrn}", seen, "consult", "Placeholder chart: this set has no patient."])
    booked = sorted({(p.patient, p.trial) for p in bundle.pairs} | {(c.patient, c.trial) for c in bundle.criteria})
    for j, (pk, tk) in enumerate(booked, 1):
        if pk not in mrns or tk not in rs:
            continue
        day = ref + timedelta(days=1 + j % 14)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        at = datetime.combine(day, datetime.min.time()).replace(hour=9 + j % 8, minute=(j * 5) % 60)
        appts.append([f"A{mrns[pk]}{j:05d}", mrns[pk], at.strftime("%Y-%m-%d %H:%M:%S"), 15, pis[tk], "MED", "B"])
    _write(hosp / "patient.csv", ["mrn", "name", "id_no", "birth_date", "sex", "death_date", "phone"], pats)
    _write(hosp / "encounter.csv", ["enc_no", "mrn", "visit_datetime", "dept_code", "staff_id", "enc_type"], encs)
    _write(hosp / "note.csv", ["note_no", "mrn", "enc_no", "note_datetime", "note_type", "text"], notes)
    _write(hosp / "diagnosis.csv", ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status"], [])
    _write(
        hosp / "appointment.csv",
        ["appt_no", "mrn", "appt_datetime", "duration_min", "staff_id", "dept_code", "status"],
        appts,
    )
    staff = [list(CHART_DOCTOR)] + [[pis[k], f"Investigator of {rs[k]} (public-data site)", "MED"] for k in sorted(pis)]
    _write(hosp / "practitioner.csv", ["staff_id", "name", "dept_code"], staff)
    for key, t in bundle.trials.items():
        (protos / f"{rs[key]}.txt").write_text(protocol_text(t), encoding="utf-8")
        (profiles / f"{rs[key]}.yaml").write_text(profile_yaml(rs[key], t.title or key, pis[key]), encoding="utf-8")
    ids = {
        "set": bundle.set,
        "patients": mrns,
        "rulesets": rs,
        "investigators": {rs[k]: v for k, v in pis.items()},
        "pair_of": {rs[k]: rs[t.pair_key] for k, t in bundle.trials.items() if t.pair_key in rs},
        "lang": {rs[k]: t.lang for k, t in bundle.trials.items()},
        "patient_lang": {mrns[k]: p.lang for k, p in bundle.patients.items()},
    }
    (gold / "ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    _jsonl(
        gold / "pairs.jsonl",
        [{**asdict(p), "mrn": mrns.get(p.patient), "ruleset": rs.get(p.trial)} for p in bundle.pairs],
    )
    _jsonl(
        gold / "criteria.jsonl",
        [{**asdict(c), "mrn": mrns.get(c.patient), "ruleset": rs.get(c.trial)} for c in bundle.criteria],
    )
    (gold / "compile_gold.json").write_text(
        json.dumps({rs[k]: v for k, v in bundle.compile_gold.items() if k in rs}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    summary = {
        **bundle.counts(),
        "set": bundle.set,
        "appointments": len(appts),
        "provenance": bundle.provenance,
        "site_sha256": _tree_sha(site),
    }
    (gold / "bundle.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (site / "PROVENANCE.md").write_text(provenance_md(bundle, len(appts)), encoding="utf-8")
    return summary


def _tree_sha(d: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(d)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def provenance_md(bundle: Bundle, appointments: int) -> str:
    placed = sorted(
        {n for t in bundle.trials.values() for n in t.notes} | {n for p in bundle.patients.values() for n in p.notes}
    )
    rows = [
        (
            "Note text (every word)",
            f"**Public source, verbatim** ({bundle.set}); see the source's licence in "
            "tools/public_accuracy/sources.py and NOTICE",
        ),
        (
            "Age, sex",
            "**From the source**: the note's own words (English rules of tools/public_site.py) or the "
            "source's structured fields; else left empty, never guessed",
        ),
        ("Protocol text", "**Public source, verbatim** (inclusion and exclusion lines), plus the lines below"),
        *[(n, "**Placed or remarked** by the builder") for n in placed],
        (
            f"Chart numbers, visit dates, birth month, staff, {appointments} appointments with each trial's "
            "investigator",
            "**Placed** (not in the sources; the box needs them to run and to scope SCREEN)",
        ),
        ("Diagnoses, labs, medicines as coded rows", "**None**: the note is the whole chart"),
        ("Gold labels", "**Not here**: in the gold folder beside this one, never given to the box"),
    ]
    table = "\n".join(f"| {a} | {b} |" for a, b in rows)
    return (
        f"# Public accuracy site: {bundle.set}\n\nBuilt by `tools/public_accuracy/site.py`. "
        f"{len(bundle.patients)} patients, {len(bundle.trials)} protocols.\n\n| What | Where it comes from |\n"
        f"| --- | --- |\n{table}\n"
    )
