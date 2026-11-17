"""The offline replay of a stored launch (card H-4, D-1111): the run's stored drafts, verdicts and traces scored and
partly re-run by the current code, with no GPU, no model and no network, and the three targets of the confirming
launch (plan 42, section 3) printed as figures.

    python -m tools.public_accuracy.replay RUN [RUN ...] [--json OUT] [--pathology-run DIR] [--require-targets]

``RUN`` is a stored set (a ``.tgz`` as the driver stores it, holding ``built/gold`` and ``work/``; or that folder
extracted; or a folder holding such tarballs or ``acc/<set>/`` folders). A tarball is read as untrusted: it is unpacked
by :func:`safe_extract` into a new empty folder outside the repository (no absolute path, no "..", no link, no special
file), and nothing in it is ever run. The tool fetches nothing.

Two levels, each figure labelled with its own:

* **(a) re-score.** The stored verdicts scored by the current scorer (``tools.box_run.acc_score``, which maps the
  box's pseudonyms through ``work/pidmap.json`` and calls :func:`tools.public_accuracy.score.score`) on answer key v1
  (the run's own ``built/gold``) and on the corrected key v2 (D-1104): v1's gold with the rows
  ``eval/public_accuracy_key/MANIFEST.json`` lists as changed for this run, applied where they match one row.
* **(b) re-run the deterministic parts** (:mod:`.rerun`): the compile from the stored ``ir_extract`` and
  ``concept_map`` replies, the causes the P1b review named for each failure class, SCREEN's deterministic steps, the
  coded age and sex lines on each key's birth dates, and the current inference guard on stored note exclusions. A
  note verdict, an ``ir_extract`` reply the run never got and a time budget are "as stored, not re-run".

The targets: (1) eligible patients wrongly excluded (none, on the corrected key); (2) the pathology figure of PoC-1
reproduced (a run without tcga is "not scored", never a pass); (3) fewer than one protocol in ten of those attempted
failing (before or in SCREEN, as the scorer counts it, D-1107; failing before SCREEN said beside it). Exit 0 when the
tool ran, whatever the figures; ``--require-targets`` exits 3 when a target is not met at the replay's highest level.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SCHEMA_VERSION = 1
MANIFEST = ROOT / "eval" / "public_accuracy_key" / "MANIFEST.json"
POC1_CLAIM = {"commit": "b266f9b7", "reports": 500, "excluded": 384, "ineligible": 450, "wrong": 0, "lost": 0,
              "eligible": 50}  # fmt: skip
POC1_SENTENCE = (
    "on 500 public pathology reports the pair excluded 384 of 450, with 0 wrong exclusions, and lost 0 of 50 "
    "eligible patients (PoC-1, commit b266f9b7)"
)
#: the record of launch P1b on key v1 (the integrator's, plan 42 section 3; H-3's scorer counts jmed's 34 rows with no
#: verdict apart, S2, so its denominator is 355 - 34)
P1B_RECORD = {
    "sigir": {"eligible_answered": 30, "eligible_excluded": 4},
    "jmed": {"wrong_exclusions": 7, "wrong_of_with_no_verdict_rows": 355, "caught": 182, "caught_of": 239},
}
MAX_MEMBER = 512 * 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024 * 1024
#: the failure classes of the scorer (D-1107) and what level (b) can check for each
RERUN_BY_CLASS = {
    "feas_equivalence": "compile re-run; the causes named (G1 D-955 ValueSet id over 64, G2 D-957 encounter with no "
    "code) checked on its ruleset; the FHIR server's equivalence itself is not run",
    "approve_failed": "compile re-run; the FHIR load's cause named (G1 D-955 ValueSet id over 64) checked; the "
    "approval and the FHIR server are not run (G3 D-952 makes a refusal fail before anything is written)",
    "feas_cql_translate": "compile re-run; G5 (D-956) ``None`` in the CQL checked; the CQL translator is not run",
    "screen_running": "compile re-run; G7 (D-953) the cascade's coded test and the notes-only budget",
    "screen_reporting": "compile re-run; G6 (D-951) the candidate list with judging mode 'nothing' built",
    "screen_judging": "G8 (D-958) the job's stored judge replies read again; the rest of SCREEN needs the models",
    "feas_ir_extract": "not re-run: the model gave no reply (G4 D-981 asks a refused part again in halves, which "
    "needs the model)",
    "feas_timeout": "not re-run: a time budget is not decided offline",
}


class Refused(ValueError):
    """An input the replay will not read (an unsafe archive, a folder inside the repository)."""


# ---------------------------------------------------------------- reading the run, safely
def safe_extract(archive: Path, dest: Path) -> list[str]:
    """Unpack a stored run's tarball into ``dest``, a new or empty folder outside the repository. Only plain files and
    folders are written, each by its relative name; an absolute name, a ".." part, a link, a device or a FIFO refuses
    the whole archive before anything is written. Modes and owners in the archive are ignored."""
    dest = dest.resolve()
    if dest == ROOT or ROOT in dest.parents:
        raise Refused(f"{dest}: the replay unpacks a stored run outside the repository")
    if dest.exists() and any(dest.iterdir()):
        raise Refused(f"{dest}: not empty")
    with tarfile.open(archive, "r:*") as tar:
        members = tar.getmembers()
        total = 0
        for m in members:
            name = m.name
            parts = Path(name).parts
            if not name or name.startswith(("/", "\\")) or Path(name).is_absolute() or ".." in parts or "\\" in name:
                raise Refused(f"{archive.name}: member {name!r} has an absolute or parent path")
            if not (m.isreg() or m.isdir()):
                raise Refused(f"{archive.name}: member {name!r} is a link or a special file")
            if m.size > MAX_MEMBER:
                raise Refused(f"{archive.name}: member {name!r} is over {MAX_MEMBER} bytes")
            total += m.size
        if total > MAX_TOTAL:
            raise Refused(f"{archive.name}: over {MAX_TOTAL} bytes in all")
        dest.mkdir(parents=True, exist_ok=True)
        written = []
        for m in members:
            target = (dest / m.name).resolve()
            if dest not in target.parents and target != dest:
                raise Refused(f"{archive.name}: member {m.name!r} leaves the folder")
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            if src is None:
                raise Refused(f"{archive.name}: member {m.name!r} cannot be read")
            with src, target.open("xb") as fh:
                shutil.copyfileobj(src, fh)
            written.append(m.name)
    return written


def _is_set(d: Path) -> bool:
    return (d / "built" / "gold" / "ids.json").exists() and (d / "work").is_dir()


def collect(paths: list[Path], scratch: Path) -> dict[str, Path]:
    """{set name: folder with ``built/`` and ``work/``} from the RUN arguments (tarballs are unpacked safely)."""
    found: dict[str, Path] = {}
    n = 0

    def add(d: Path) -> None:
        ids = json.loads((d / "built" / "gold" / "ids.json").read_text(encoding="utf-8"))
        name = str(ids.get("set") or d.name)
        if name in found:
            raise Refused(f"set {name} given twice ({found[name]} and {d})")
        found[name] = d

    def one(p: Path) -> None:
        nonlocal n
        if p.is_file() and p.name.endswith((".tgz", ".tar.gz", ".tar")):
            n += 1
            dest = scratch / "runs" / f"{n:02d}-{p.name.split('.')[0]}"
            safe_extract(p, dest)
            if not _is_set(dest):
                raise Refused(f"{p}: holds no built/gold/ids.json and work/")
            add(dest)
        elif p.is_dir() and _is_set(p):
            add(p)
        elif p.is_dir() and (p / "acc").is_dir():
            for d in sorted(x for x in (p / "acc").iterdir() if x.is_dir() and _is_set(x)):
                add(d)
        elif p.is_dir():
            kids = sorted(p.iterdir())
            hits = [
                k for k in kids if (k.is_file() and k.name.endswith((".tgz", ".tar.gz"))) or (k.is_dir() and _is_set(k))
            ]
            if not hits:
                raise Refused(f"{p}: no stored set in it (a .tgz, or a folder with built/gold and work/)")
            for k in hits:
                one(k)
        else:
            raise Refused(f"{p}: not a stored set")

    for p in paths:
        one(p)
    return found


# ---------------------------------------------------------------- level (a): the current scorer, both keys
def _gold_sha(built: Path) -> dict[str, str]:
    g = built / "gold"
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(g.glob("*")) if f.is_file()}


def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def identify(name: str, built: Path) -> dict[str, Any]:
    """Whether the set's ``built/gold`` is launch P1b's key v1, file for file (the sha256 MANIFEST.json pins)."""
    v1 = ((manifest().get("versions") or {}).get("v1") or {}).get("launch_p1b") or {}
    pinned = (v1.get("sha256") or {}).get(name) or {}
    got = _gold_sha(built)
    same = bool(pinned) and all(got.get(f) == h for f, h in pinned.items())
    return {"launch_p1b_key_v1": same, "run": v1.get("run") if same else None,
            "build_day": v1.get("build_day") if same else None}  # fmt: skip


def v2_overlay(name: str, built: Path, out: Path, *, pinned: bool, require_pin: bool = True) -> dict[str, Any]:
    """Key v2 of a stored v1 set, offline: ``built`` copied with the label rows MANIFEST.json lists for launch P1b
    (``versions.v2.launch_p1b_rows_that_change``) applied where each matches exactly one gold row. What the list does
    not cover stays v1, and is said. The rows are P1b's: unless the set's gold is P1b's key v1 file for file (the
    sha256 MANIFEST.json pins, ``pinned``), key v2 is refused for the set and its v2 figures are "not scored"
    (``require_pin=False`` is for a test's slice of P1b's gold, which cannot match the pins)."""
    shutil.copytree(built / "gold", out / "gold")
    if require_pin and not pinned:
        return {"key": "v2", "applied": 0, "refused": "the stored gold is not launch P1b's key v1 (its sha256 differs "
                "from MANIFEST.json's pins), so MANIFEST.json's v2 rows cannot be applied to it"}  # fmt: skip
    rows = (((manifest().get("versions") or {}).get("v2") or {}).get("launch_p1b_rows_that_change") or {}).get(name)
    info: dict[str, Any] = {"key": "v2", "how": "the stored v1 gold with MANIFEST.json's listed changes applied",
                            "gold_matches_the_pins": pinned}  # fmt: skip
    if not rows:
        info["applied"] = 0
        info["note"] = "MANIFEST.json lists no label row of this set that v2 changes"
        return info
    info["manifest_says"] = {k: v for k, v in rows.items() if k != "labels"}
    f = out / "gold" / "criteria.jsonl"
    crits = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    applied, unmatched = 0, []
    for ch in rows.get("labels") or []:
        hit = [c for c in crits if c.get("patient") == ch.get("patient") and c.get("trial") == ch.get("trial")
               and c.get("label") == ch.get("v1")]  # fmt: skip
        if len(hit) != 1:
            unmatched.append(f"{ch.get('trial')} {ch.get('patient')}")
            continue
        hit[0]["label"] = ch["v2"]
        applied += 1
    f.write_text("".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in crits), encoding="utf-8")
    info |= {"applied": applied, "unmatched": unmatched}
    return info


def score_all(sets: dict[str, tuple[Path, Any, Path]], where: Path) -> dict[str, Any]:
    """Score {set: (built, answers or the stored work folder, the stored work folder)} with
    ``tools.box_run.acc_score`` (the driver's own path: the box's pseudonyms through ``pidmap.json``, then the scorer)
    and return {set: score.json}."""
    from tools import box_run

    for name, (built, answers, work) in sets.items():
        d = where / "acc" / name
        (d / "work").mkdir(parents=True)
        shutil.copytree(built, d / "built")
        if isinstance(answers, Path):
            shutil.copy(answers / "answers.json", d / "work" / "answers.json")
        else:
            (d / "work" / "answers.json").write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
        if (work / "pidmap.json").exists():
            shutil.copy(work / "pidmap.json", d / "work" / "pidmap.json")
    box_run.acc_score(where)
    return {name: json.loads((where / "acc" / name / "score.json").read_text(encoding="utf-8")) for name in sets}


# ---------------------------------------------------------------- the figures
def eligible_figure(name: str, sc: dict[str, Any], refused: str | None = None) -> dict[str, Any]:
    """Target 1 for one set: pair level where the set has eligibility labels (gold-eligible pairs the box excluded,
    of those it answered), else criterion level (gold met or not applicable rows the box blocked, of those answered:
    JMED's "not excluded"). ``refused``: the key could not be applied to the set (not scored, with the reason)."""
    if refused:
        return {"set": name, "scored": False, "why": refused, "numerator": 0, "denominator": 0}
    if sc.get("not_scored_because"):
        return {"set": name, "scored": False, "why": sc["not_scored_because"], "numerator": 0, "denominator": 0}
    summ = (sc.get("pairs") or {}).get("summary") or {}
    if summ:
        k = sum(int(s["eligible_lost"]["k"]) for s in summ.values())
        n = sum(int(s["eligible_lost"]["n"]) for s in summ.values())
        extra = {lang: {kk: s.get(kk) for kk in ("eligible_lost_where_the_criterion_labels_exclude",
                                                 "eligible_lost_on_the_line_the_criterion_labels_exclude")}
                 for lang, s in summ.items()}  # fmt: skip
        return {"set": name, "scored": True, "what": "gold-eligible pairs the box excluded, of those it answered",
                "numerator": k, "denominator": n, "s1_label_conflicts": extra}  # fmt: skip
    cr = sc.get("criteria") or {}
    w = cr.get("wrong_exclusion") or {}
    return {"set": name, "scored": True, "numerator": int(w.get("k") or 0), "denominator": int(w.get("n") or 0),
            "what": "gold rows met or not applicable (JMED: not excluded) the box blocked, of those it answered",
            "rows_with_no_verdict": cr.get("no_verdict")}  # fmt: skip


def figure(level: str, key: str, per_set: list[dict[str, Any]]) -> dict[str, Any]:
    k = sum(int(x.get("numerator") or 0) for x in per_set)
    n = sum(int(x.get("denominator") or 0) for x in per_set)
    scored = all(x.get("scored", True) for x in per_set)
    return {"level": level, "key": key, "numerator": k, "denominator": n, "met": scored and n > 0 and k == 0,
            "all_sets_scored": scored, "per_set": per_set}  # fmt: skip


def protocols_figure(level: str, scores: dict[str, Any], rerun: dict[str, Any] | None = None) -> dict[str, Any]:
    """Target 3: failed (before or in SCREEN) of those attempted, and failed before SCREEN, over the sets. At level
    (b) a failure counts as gone only when the re-run shows its named cause gone; one not re-run still counts."""
    att = failed = before = 0
    classes: dict[str, int] = {}
    per_set = {}
    for name, sc in sorted(scores.items()):
        pr = sc.get("protocols") or {}
        per_set[name] = {k: pr.get(k) for k in ("in_set", "screened", "not_run_time_budget", "attempted", "failed",
                                                "failed_before_screen", "failed_in_screen")}  # fmt: skip
        att += int(pr.get("attempted") or 0)
        failed += int(pr.get("failed") or 0)
        before += int(pr.get("failed_before_screen") or 0)
        for cls, n in (pr.get("failed_by_class") or {}).items():
            classes[cls] = classes.get(cls, 0) + int(n)
    out: dict[str, Any] = {"level": level, "attempted": att, "failed_by_class": classes, "per_set": per_set}
    if rerun is not None:
        gone = [r for r in rerun.values() if r["outcome"] == "cause_gone"]
        gone_before = [r for r in gone if r["status"] == "failed_before_screen"]
        for key, r in rerun.items():
            ps = per_set.get(key.split(":", 1)[0])
            if ps is not None and r["outcome"] == "cause_gone":
                ps["no_longer_failing"] = int(ps.get("no_longer_failing") or 0) + 1
        out["no_longer_failing"] = sorted(r["ruleset"] for r in gone)
        out["proof"] = "cause-level: the step that failed re-run as far as it runs offline; see each protocol"
        failed -= len(gone)
        before -= len(gone_before)
        out["still_failing_by_outcome"] = {o: sum(1 for r in rerun.values() if r["outcome"] == o)
                                           for o in ("still_fails", "not_rerun")}  # fmt: skip
    out |= {
        "numerator": failed,
        "denominator": att,
        "share": round(failed / att, 4) if att else None,
        "failed_before_screen": before,
        "failed_before_screen_share": round(before / att, 4) if att else None,
        "met": att > 0 and failed * 10 < att,
        "met_before_screen_only": att > 0 and before * 10 < att,
        "target": "fewer than one protocol in ten of those attempted fails (before or in SCREEN, D-1107); failing "
        "before SCREEN alone is said beside it",
    }
    return out


def pathology_from_run(scores: dict[str, Any], names: list[str]) -> dict[str, Any]:
    if "tcga" in scores:
        p = scores["tcga"].get("pathology") or {}
        fig: dict[str, Any] = {"level": "a", "scored": bool(p.get("scored")), "detail": p}
        if p.get("scored"):
            ie, we, el = p["ineligible_excluded"], p["wrong_exclusions"], p["eligible_lost"]
            fig |= {"numerator": ie["k"], "denominator": ie["n"], "wrong_exclusions": we["k"], "eligible_lost": el["k"],
                    "eligible": el["n"], "reports": p.get("reports"),
                    "met": (p.get("reports"), ie["k"], ie["n"], we["k"], el["k"], el["n"]) == (
                        POC1_CLAIM["reports"], POC1_CLAIM["excluded"], POC1_CLAIM["ineligible"], POC1_CLAIM["wrong"],
                        POC1_CLAIM["lost"], POC1_CLAIM["eligible"])}  # fmt: skip
        else:
            fig |= {"met": False, "not_scored_because": p.get("not_scored_because")}
        return fig
    return {
        "level": "a",
        "scored": False,
        "met": False,
        "numerator": None,
        "denominator": None,
        "not_scored_because": f"the stored run holds no tcga set (sets given: {', '.join(names) or 'none'}); launch "
        "P1b's tcga ran no protocol: its filter named G2TCGA-BRCA while the set's ids carry the tag, Gm2TCGA-BRCA "
        "(D-1108)",
    }


def pathology_from_stored_counts(folder: Path) -> dict[str, Any]:
    """A run kept as counts only (PoC-1's ``sets-<commit>.json``: no answers, no gold): its tcga figures read back,
    never re-scored, and compared with the claim."""
    out: dict[str, Any] = {"folder": str(folder), "level": "read", "re_scored": False, "runs": []}
    for f in sorted(folder.glob("sets-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for name, s in sorted((d.get("sets") or {}).items()):
            if not name.startswith("tcga"):
                continue
            en = (((s.get("score") or {}).get("pairs") or {}).get("summary") or (s.get("score") or {}).get("pairs")
                  or {}).get("en") or {}  # fmt: skip
            if not en:
                out["runs"].append({"file": f.name, "set": name, "read": False, "why": "no pair figures stored"})
                continue
            ex, we, el = en["excluded_caught"], en["wrong_exclusions"], en["eligible_lost"]
            row = {"file": f.name, "set": name, "commit": (d.get("meta") or {}).get("commit"), "read": True,
                   "answered": en.get("answered"), "excluded": ex["k"], "ineligible": ex["n"],
                   "wrong_exclusions": we["k"], "eligible_lost": el["k"], "eligible": el["n"]}  # fmt: skip
            row["matches_the_claim"] = (row["answered"], ex["k"], ex["n"], we["k"], el["k"], el["n"]) == (
                POC1_CLAIM["reports"], POC1_CLAIM["excluded"], POC1_CLAIM["ineligible"], POC1_CLAIM["wrong"],
                POC1_CLAIM["lost"], POC1_CLAIM["eligible"])  # fmt: skip
            out["runs"].append(row)
    out["could_not"] = ("re-score: the folder keeps counts only (no answers.json, no gold, no patient id), so the "
                        "figure is read back as stored, not reproduced from verdicts")  # fmt: skip
    return out


# ---------------------------------------------------------------- level (b)
def rerun_level(name: str, d: Path, scratch: Path, tz: str, index_day: date, build_day: date | None) -> dict[str, Any]:
    """Re-compile every attempted protocol of a set from its stored replies, check each failure's named cause, and
    decide its stored answers' deterministic parts again (key v1 and v2 birth dates where the note is public)."""
    from tools.public_accuracy import rerun as rr
    from tools.public_accuracy import score as sc
    from tools.public_accuracy import site

    work = d / "work"
    answers = json.loads((work / "answers.json").read_text(encoding="utf-8"))
    prog = json.loads((work / "progress.json").read_text(encoding="utf-8")) if (work / "progress.json").exists() else {}
    ids = json.loads((d / "built" / "gold" / "ids.json").read_text(encoding="utf-8"))
    stored = rr.Stored.read(work)
    recompiled: dict[str, Any] = {}
    protocols: dict[str, Any] = {}
    for rs_id, a in sorted(answers.items()):
        status, cls = sc.protocol_status(a)
        if status in ("not_run_time_budget", "not_in_answers"):
            continue
        job = str((prog.get(rs_id) or {}).get("feas_job") or "")
        r = rr.recompile(stored, job, index_day, tz) if job else rr.Recompiled(rs_id, "not_rerun", "", "no FEAS job")
        recompiled[rs_id] = r
        if status not in ("failed_before_screen", "failed_in_screen"):
            continue
        row: dict[str, Any] = {"ruleset": rs_id, "status": status, "class": cls, "what": RERUN_BY_CLASS.get(cls, ""),
                               "compile": r.status, "compile_step": r.step, "compile_message": r.message[:200],
                               "lines": r.lines, "concepts_not_stored": len(r.concepts_not_stored)}  # fmt: skip
        checks = rr.cause_checks(r)
        row["checks"] = checks
        if cls in ("screen_running", "screen_reporting"):
            row["checks"] |= rr.screen_checks(r, len(a.get("patients") or {}) or 1)
        if cls == "screen_judging":
            row["checks"] |= rr.judge_replies(stored, str((prog.get(rs_id) or {}).get("screen_job") or ""))
        row["outcome"] = _outcome(cls, r, row["checks"])
        protocols[rs_id] = row
    pid_mrn: dict[str, str] = {}
    pm = work / "pidmap.json"
    if pm.exists():
        pid_mrn = {v: k for k, v in json.loads(pm.read_text(encoding="utf-8")).items()}
    ages: dict[str, dict[str, tuple[int | None, str]]] = {"v1": {}, "v2": {}}
    births: dict[str, Any] = {}
    if name == "sigir" and build_day is not None:
        births = rr.sigir_births(ids, build_day, site.SET_OFFSETS["sigir"][0])
        for mrn, b in births.items():
            if "birth_v1" in b:
                ages["v1"][mrn] = (rr.age_on(b["birth_v1"], index_day), b["sex"])
                ages["v2"][mrn] = (rr.age_on(b["birth_v2"], index_day), b["sex"])
    tables = rr.AgeTable(index_day, scratch / f"age-{name}", tz)
    out: dict[str, Any] = {"protocols": protocols, "answers": {}, "rescreen": {}}
    for key in ("v1", "v2"):
        res = rr.rescreen(answers, recompiled, tables, pid_mrn, ages[key] or None, ages["v1"] or None)
        out["answers"][key] = res.answers
        out["rescreen"][key] = {
            "verdicts_changed": dict(res.changes),
            "calibration_on_key_v1": dict(res.calibration),
            "birth_dates": (
                f"{len(ages[key])} of {len(ids.get('patients') or {})} patients from the public note "
                f"(key {key}); the rest from the ages their stored coded verdicts allow"
            )
            if ages[key]
            else "none known here: each patient's age from what their stored coded verdicts allow "
            "(the run's key v1 birth dates), the same for both keys",
            "notes": res.notes[:20],
        }
    out["recompiled"] = {rs: {"status": r.status, "step": r.step, "concepts_not_stored": len(r.concepts_not_stored)}
                         for rs, r in recompiled.items()}  # fmt: skip
    return out


def _outcome(cls: str, r: Any, checks: dict[str, Any]) -> str:
    """cause_gone / still_fails / not_rerun for one failed protocol at level (b)."""
    if cls in ("feas_ir_extract", "feas_timeout"):
        return "not_rerun"
    if cls == "screen_judging":
        if checks.get("stored_replies") and not checks.get("still_no_answer") and not checks.get("no_reply_stored"):
            return "cause_gone"
        return "still_fails" if checks.get("still_no_answer") else "not_rerun"
    if r.status == "not_rerun":
        return "not_rerun"
    if r.status == "failed":
        return "still_fails"
    ok = checks.get("valueset_ids_are_fhir_ids") and not checks.get("encounter_atoms_without_a_code")
    if cls in ("feas_equivalence", "approve_failed"):
        return "cause_gone" if ok else "still_fails"
    if cls == "feas_cql_translate":
        return "cause_gone" if ok and not checks.get("none_in_cql") else "still_fails"
    if cls == "screen_running":
        return "cause_gone" if checks.get("coded_criteria") or checks.get("notes_only_budget") else "still_fails"
    if cls == "screen_reporting":
        return "cause_gone" if checks.get("candidate_list_builds") else "still_fails"
    return "not_rerun"


# ---------------------------------------------------------------- the whole replay
def commit() -> dict[str, Any]:
    def git(*a: str) -> str:
        try:
            return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return ""

    return {"commit": git("rev-parse", "HEAD").strip() or "unknown",
            "working_tree_differs": bool(git("status", "--porcelain", "--", ".").strip())}  # fmt: skip


def replay(
    paths: list[Path],
    scratch: Path,
    *,
    rerun: bool = True,
    pathology_run: Path | None = None,
    tz: str = "Asia/Taipei",
    index_day: date | None = None,
    build_day: date | None = None,
    require_pin: bool = True,
) -> dict[str, Any]:
    from tools.public_accuracy import key as keys

    found = collect(paths, scratch)
    names = sorted(found)
    report: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "tool": "python -m tools.public_accuracy.replay",
                              **commit(), "sets": {}, "answer_keys": {"v1": keys.KEYS["v1"], "v2": keys.KEYS["v2"]},
                              "limits": []}  # fmt: skip
    ident = {n: identify(n, found[n] / "built") for n in names}
    bday = build_day or next((date.fromisoformat(i["build_day"]) for i in ident.values() if i.get("build_day")), None)
    iday = index_day or bday
    v2dirs: dict[str, Path] = {}
    for n in names:
        v2dirs[n] = scratch / "key-v2" / n
        v2dirs[n].mkdir(parents=True)
        kv2 = v2_overlay(
            n, found[n] / "built", v2dirs[n], pinned=ident[n]["launch_p1b_key_v1"], require_pin=require_pin
        )
        report["sets"][n] = {"folder": str(found[n]), "identified": ident[n], "key_v2": kv2}
    a1 = score_all({n: (found[n] / "built", found[n] / "work", found[n] / "work") for n in names}, scratch / "a-v1")
    a2 = score_all({n: (v2dirs[n], found[n] / "work", found[n] / "work") for n in names}, scratch / "a-v2")
    for n in names:
        report["sets"][n]["level_a"] = {"v1": _brief(a1[n]), "v2": _brief(a2[n])}
        if ident[n]["launch_p1b_key_v1"]:
            report["sets"][n]["p1b_record"] = _record(n, a1[n])
    refused = {n: report["sets"][n]["key_v2"].get("refused") for n in names}
    t1 = {"a": {"v1": figure("a", "v1", [eligible_figure(n, a1[n]) for n in names]),
                "v2": figure("a", "v2", [eligible_figure(n, a2[n], refused[n]) for n in names])}}  # fmt: skip
    t3 = {"a": protocols_figure("a", a1)}
    if rerun and iday is not None:
        b_runs = {n: rerun_level(n, found[n], scratch, tz, iday, bday) for n in names}
        b1 = score_all(
            {n: (found[n] / "built", b_runs[n]["answers"]["v1"], found[n] / "work") for n in names}, scratch / "b-v1"
        )
        b2 = score_all({n: (v2dirs[n], b_runs[n]["answers"]["v2"], found[n] / "work") for n in names}, scratch / "b-v2")
        for n in names:
            report["sets"][n]["level_b"] = {
                "v1": _brief(b1[n]), "v2": _brief(b2[n]), "rescreen": b_runs[n]["rescreen"],
                "failed_protocols": b_runs[n]["protocols"], "recompiled": b_runs[n]["recompiled"]}  # fmt: skip
        t1["b"] = {"v1": figure("b", "v1", [eligible_figure(n, b1[n]) for n in names]),
                   "v2": figure("b", "v2", [eligible_figure(n, b2[n], refused[n]) for n in names])}  # fmt: skip
        allrr = {f"{n}:{rs}": r for n in names for rs, r in b_runs[n]["protocols"].items()}
        t3["b"] = protocols_figure("b", a1, allrr)
    elif rerun:
        report["limits"].append("level (b) not run: no index day (give --index-day, or a run whose key MANIFEST.json "
                                "pins, which names its build day)")  # fmt: skip
    t2: dict[str, Any] = {"run": pathology_from_run(a1, names)}
    if pathology_run is not None:
        t2["stored_counts"] = pathology_from_stored_counts(pathology_run)
    t2["claim"] = POC1_SENTENCE
    report["targets"] = {
        "eligible_wrongly_excluded": {**t1, "target": "no eligible patient excluded, on the corrected answer key"},
        "pathology": {**t2, "target": "the pathology figure of PoC-1 reproduced: " + POC1_SENTENCE},
        "protocols_failing": {**t3},
    }
    report["met"] = {
        "eligible_wrongly_excluded": t1.get("b", t1["a"])["v2"]["met"],
        "pathology": t2["run"]["met"],
        "protocols_failing": t3.get("b", t3["a"])["met"],
        "at_level": "b" if "b" in t1 else "a",
    }
    report["limits"] += _limits(report, rerun)
    return report


def _brief(sc: dict[str, Any]) -> dict[str, Any]:
    keep = ("not_scored_because", "protocols", "pathology", "unjudged_exclusions")
    out = {k: sc[k] for k in keep if k in sc}
    if "pairs" in sc:
        out["pairs"] = {lang: {k: v for k, v in s.items() if k != "denominators"}
                        for lang, s in sc["pairs"]["summary"].items()}  # fmt: skip
        out["label_conflicts"] = {k: v for k, v in sc["pairs"]["label_conflicts"].items() if k != "excluded"}
    if "criteria" in sc:
        keep_c = ("answered", "wrong_exclusion", "caught", "no_verdict", "not_compiled", "rows_in_gold")
        out["criteria"] = {k: sc["criteria"][k] for k in keep_c if k in sc["criteria"]}
    if "protocols" in out:
        out["protocols"] = {k: v for k, v in out["protocols"].items() if k not in ("statuses", "classes", "what")}
    return out


def _record(name: str, sc: dict[str, Any]) -> dict[str, Any]:
    rec = P1B_RECORD.get(name)
    if not rec:
        return {}
    if name == "sigir":
        en = sc["pairs"]["summary"]["en"]
        got = {"eligible_answered": en["eligible_lost"]["n"], "eligible_excluded": en["eligible_lost"]["k"]}
    else:
        c = sc["criteria"]
        got = {"wrong_exclusions": c["wrong_exclusion"]["k"],
               "wrong_of_with_no_verdict_rows": c["wrong_exclusion"]["n"] + int(c.get("no_verdict") or 0),
               "caught": c["caught"]["k"], "caught_of": c["caught"]["n"]}  # fmt: skip
    return {"record": rec, "replayed": got, "reproduced": got == rec}


def _limits(r: dict[str, Any], rerun: bool) -> list[str]:
    out = [
        "Level (a) scores the verdicts as the run stored them; nothing there is re-run.",
        "Key v2 is offline: v1's gold with the label rows MANIFEST.json lists for the run. For jmed those are the rows "
        "whose note the run's judge read in full (319 of 594); the other rows' notes are not in the stored run. For "
        "sigir v2 changes no label (B1 and B2 change the site's birth dates and age lines, which only level (b) "
        "shows, for the coded age lines).",
    ]
    if rerun and r["met"]["at_level"] == "b":
        out += [
            "Level (b) answers each model call only from the run's stored replies (ir_extract, concept_map, judge). "
            "A note verdict stays as stored (only the inference guard, D-985, is re-run on it); a line whose "
            "ir_extract reply was never stored is not re-run.",
            "The CQL translator, the FHIR server and the box's lake are not run: the equivalence and approve steps "
            "are checked by the causes the P1b review named (G1, G2, G5), not end to end.",
            "Coded lines are re-decided only where their whole logic is age and sex (an age table on the run's "
            "index day). Other coded lines are as stored; a line the cascade never reached for a patient is open.",
            "The birth dates are those of the answer key (site.birth_date_v1 / site.birth_date) from the public note "
            "in eval/criterion_ml (sigir); a patient without one, and every jmed patient (the site's birth dates are "
            "not in the stored run), is placed by what their stored coded verdicts allow, which is key v1's.",
        ]
    return out


# ---------------------------------------------------------------- printing
def render(r: dict[str, Any]) -> str:
    lines: list[str] = []
    w = lines.append
    w(f"Offline replay (schema {r['schema_version']}) on commit {r['commit'][:12]}"
      + (" (working tree differs)" if r.get("working_tree_differs") else ""))  # fmt: skip
    for n, s in r["sets"].items():
        idn = s["identified"]
        w(f"  set {n}: {s['folder']}" + (f"  [launch P1b, run {idn['run']}]" if idn.get("launch_p1b_key_v1") else ""))
        if s.get("p1b_record"):
            rec = s["p1b_record"]
            w(f"    P1b record on key v1: {'reproduced' if rec['reproduced'] else 'NOT reproduced'} "
              f"({json.dumps(rec['replayed'])})")  # fmt: skip
        kv = s["key_v2"]
        if kv.get("refused"):
            w(f"    key v2: refused: {kv['refused']}")
            continue
        w(f"    key v2: {kv.get('applied', 0)} label rows applied"
          + (f", {len(kv['unmatched'])} unmatched" if kv.get("unmatched") else ""))  # fmt: skip
    t = r["targets"]
    w("")
    w("1. Eligible patients wrongly excluded (target: none, on the corrected key)")
    w(f"   {'level':<6}{'key':<5}{'excluded':>10}{'of':>6}  met   per set")
    for lvl, by in sorted((k, v) for k, v in t["eligible_wrongly_excluded"].items() if k in ("a", "b")):
        for key, f in sorted(by.items()):
            per = ", ".join(f"{x['set']} {x['numerator']}/{x['denominator']}" if x.get("scored", True)
                            else f"{x['set']} not scored" for x in f["per_set"])  # fmt: skip
            w(f"   ({lvl})   {key:<5}{f['numerator']:>10}{f['denominator']:>6}  {_yes(f['met']):<4}  {per}")
    w("2. Pathology figure (target: " + t["pathology"]["claim"] + ")")
    pr = t["pathology"]["run"]
    if pr.get("scored"):
        w(f"   (a) the run's tcga: excluded {pr['numerator']} of {pr['denominator']}, {pr['wrong_exclusions']} wrong, "
          f"lost {pr['eligible_lost']} of {pr['eligible']}: {'met' if pr['met'] else 'not met'}")  # fmt: skip
    else:
        w(f"   (a) not scored: {pr['not_scored_because']}  -> not met")
    sc_ = t["pathology"].get("stored_counts")
    if sc_:
        for row in sc_["runs"]:
            if row.get("read"):
                w(f"   (read, not re-scored) {row['file']} {row['set']}: excluded {row['excluded']} of "
                  f"{row['ineligible']}, {row['wrong_exclusions']} wrong, lost {row['eligible_lost']} of "
                  f"{row['eligible']} over {row['answered']} answered: "
                  f"{'matches the claim' if row['matches_the_claim'] else 'differs from the claim'}")  # fmt: skip
        w(f"   could not: {sc_['could_not']}")
    w("3. Protocols failing (target: fewer than one in ten of those attempted)")
    for lvl in ("a", "b"):
        f = t["protocols_failing"].get(lvl)
        if not f:
            continue
        w(f"   ({lvl}) failed {f['numerator']} of {f['denominator']} ({_pct(f['share'])}): "
          f"{'met' if f['met'] else 'not met'}; before SCREEN {f['failed_before_screen']} of {f['denominator']} "
          f"({_pct(f['failed_before_screen_share'])}): {_met(f['met_before_screen_only'])}")  # fmt: skip
        if lvl == "a":
            w("       by class: " + ", ".join(f"{k} {v}" for k, v in sorted(f["failed_by_class"].items())))
        else:
            w(f"       no longer failing (cause-level): {len(f['no_longer_failing'])}; still failing: "
              f"{f['still_failing_by_outcome']}")  # fmt: skip
    for n, s in r["sets"].items():
        fp = (s.get("level_b") or {}).get("failed_protocols") or {}
        if fp:
            w(f"   {n}, per failed protocol at level (b):")
            for rs, row in sorted(fp.items(), key=lambda kv: (kv[1]["class"], kv[0])):
                w(f"     {rs:<18}{row['class']:<20}{row['outcome']:<12}{_why(row)}")
    m = r["met"]
    w("")
    w(
        f"Targets at level ({m['at_level']}): eligible {'met' if m['eligible_wrongly_excluded'] else 'not met'}; "
        f"pathology {_met(m['pathology'])}; protocols {_met(m['protocols_failing'])}"
    )
    w("Limits:")
    for x in r["limits"]:
        w(f"  - {x}")
    return "\n".join(lines) + "\n"


def _met(x: Any) -> str:
    return "met" if x else "not met"


def _yes(x: Any) -> str:
    return "yes" if x else "no"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f} %"


def _why(row: dict[str, Any]) -> str:
    c = row.get("checks") or {}
    if row["outcome"] == "not_rerun":
        return str(row.get("compile_message") or row.get("what", ""))
    if row["outcome"] == "still_fails":
        return f"{row.get('compile_step')}: {row.get('compile_message')}" if row.get("compile_step") else json.dumps(c)
    bits = []
    if c.get("valuesets_whose_p1b_style_id_is_over_64"):
        bits.append(
            f"{c['valuesets_whose_p1b_style_id_is_over_64']} ValueSet id(s) over 64 in P1b's form, all FHIR ids now"
        )
    if row["class"] in ("feas_equivalence", "approve_failed") and not bits:
        bits.append("no ValueSet id over 64, no encounter without a code")
    if row["class"] == "feas_cql_translate":
        bits.append("no None in the CQL")
    if row["class"] == "screen_running":
        bits.append(f"{c.get('coded_criteria')} coded criteria; notes-only budget {c.get('notes_only_budget')}")
    if row["class"] == "screen_reporting":
        bits.append("candidate list with mode 'nothing' builds")
    if row["class"] == "screen_judging":
        bits.append(f"{c.get('stored_replies')} stored judge replies, {c.get('still_no_answer')} still no answer")
    if row.get("concepts_not_stored"):
        bits.append(f"{row['concepts_not_stored']} concept map(s) not stored, answered 'no choice'")
    return "; ".join(bits)


# ---------------------------------------------------------------- command line
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.replay", description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("runs", nargs="+", type=Path, help="stored sets: .tgz, extracted folders, or a folder of them")
    ap.add_argument("--json", type=Path, help="write the report here (JSON)")
    ap.add_argument("--scratch", type=Path, help="an empty folder outside the repository (default: a temporary one)")
    ap.add_argument("--pathology-run", type=Path, help="a run kept as counts (sets-<commit>.json), e.g. PoC-1's")
    ap.add_argument("--no-rerun", action="store_true", help="level (a) only")
    ap.add_argument("--tz", default=os.environ.get("TB_TZ") or "Asia/Taipei", help="the site's zone for the compile")
    ap.add_argument("--index-day", type=date.fromisoformat, help="SCREEN's day (default: the run's build day)")
    ap.add_argument("--build-day", type=date.fromisoformat, help="the key's build day (default: MANIFEST.json's)")
    ap.add_argument("--require-targets", action="store_true", help="exit 3 when a target is not met")
    a = ap.parse_args(argv)
    os.environ.setdefault("TB_ENV", "DEV")
    try:
        if a.scratch:
            if a.scratch.exists() and any(a.scratch.iterdir()):
                raise Refused(f"--scratch {a.scratch}: not empty")
            res = replay(a.runs, a.scratch, rerun=not a.no_rerun, pathology_run=a.pathology_run, tz=a.tz,
                         index_day=a.index_day, build_day=a.build_day)  # fmt: skip
        else:
            with tempfile.TemporaryDirectory(prefix="tb-replay-") as t:
                res = replay(a.runs, Path(t), rerun=not a.no_rerun, pathology_run=a.pathology_run, tz=a.tz,
                             index_day=a.index_day, build_day=a.build_day)  # fmt: skip
    except (Refused, tarfile.TarError, OSError) as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(res))
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    if a.require_targets and not all(v for k, v in res["met"].items() if k != "at_level"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
