#!/usr/bin/env python3
"""Turn a collected cloud-run results folder into the files of the results pull request (lane G).

    python deploy/gcp/results_report.py <collected results dir> --out docs/plan/measurements/<run folder> \\
        --studies 5 --night-hours 8 [--window-patients 50000] [--vm-hours 6.2] [--chosen 16]

It reads what ``deploy/gcp/complete-run.sh --collect`` leaves (``plan.json``, ``TB_HEAD.json``, ``parts/<tag>.json``;
the part files may also lie flat in the folder, as in ``docs/plan/measurements/g1-2026-11-11``) and writes:

* ``README.md``: run id, commit, hours, cost against the estimate and the cap, one row per part with its status, the
  G-1 verdict (plan v7 section 7.1) and the G-3 table;
* ``capacity_inputs.json``: the measured figures the capacity statement and the hardware note read (T-667, T-637,
  T-734);
* ``DEFECTS.md``: one entry per failed part or failed check, for the integrator, with empty Cause, Fix and Card.

The reader only reads: it calls no service, runs no command and needs no network. Standard library only. A part with
no result is PENDING or MISSING, by name; it is never dropped and never counted as passed. The exit code is 0 unless a
file is malformed (2) or the output folder holds a README this reader did not write (3). Model ids never reach the
output: the results name them, the reader prints the role (judge, verifier) in their place.

The G-3 threshold is computed, never a figure in this file (OD-10, plan v7 section 7.1)::

    required calls/s = patients x studies x calls per patient and study / (night hours x 3600 x window share)

``calls per patient and study`` is measured by the run (the calls of the chosen setting over the part's patients);
patients, studies and night hours come from the arguments or from the plan's ``window`` block.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

MARK = "<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->"
SCHEMA = "tb-capacity-inputs/1"
PASSED, FAILED, PENDING, MISSING = "PASSED", "FAILED", "PENDING", "MISSING"
G1_TAG = "chat-template"  # the part of plan v7 test G-1 (tools/complete_run.py G1_CHECK)
# Files of a collected folder that are not part results.
NOT_PARTS = {"plan.json", "TB_HEAD.json", "gpu_peak.json", "report.json", "report-partial.json", "now.json",
             "capacity_inputs.json", "vm.json"}  # fmt: skip
# A declared setting (OD-10), not a measurement: the share of the night window the model calls may use. The deep
# review of 2026-11-12 (LLM-012) plans the window "used to 70 %"; the rest is ingest, reports and the backup.
# Change it with --window-share or the plan's window.usable_share.
WINDOW_SHARE = 0.7
ROLE_OF_ENDPOINT = {"serving": "judge", "verifier": "verifier"}  # the gateway's endpoint names (tools/run_metrics.py)
DETAIL_CHARS = 300  # a check's detail in DEFECTS.md: the part writer cuts its own crash text at the same length


class MalformedError(Exception):
    """A file of the folder that cannot be read as what it must be."""


# ---------------------------------------------------------------- reading
def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MalformedError(f"{path}: not readable JSON ({exc})") from exc


def base_run_id(run_id: str) -> str:
    """``<run id>-s<N>`` (one VM of a run) -> ``<run id>``."""
    return re.sub(r"-s\d+$", "", run_id)


def find_parts(folder: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """The part results of the folder by tag, and the tags with a half-written result (``<tag>.json.part``)."""
    home = folder / "parts" if (folder / "parts").is_dir() else folder
    parts: dict[str, dict[str, Any]] = {}
    for f in sorted(home.glob("*.json")):
        if f.name in NOT_PARTS or f.name.startswith("serving_config"):
            continue
        doc = load_json(f)
        if not isinstance(doc, dict) or not isinstance(doc.get("stages"), list):
            raise MalformedError(f"{f}: a part result must be an object with a list of stages")
        for st in doc["stages"]:
            if not isinstance(st, dict) or not isinstance(st.get("checks", []), list):
                raise MalformedError(f"{f}: a stage must be an object with a list of checks")
            if any(not isinstance(c, list) or len(c) < 2 for c in st.get("checks", [])):
                raise MalformedError(f"{f}: a check must be [name, passed, detail]")
        doc["_file"] = str(f.relative_to(folder))
        parts[f.stem] = doc
    partial = {f.name[: -len(".json.part")] for f in home.glob("*.json.part")}
    return parts, partial - set(parts)


def read_run(folder: Path) -> dict[str, Any]:
    if not folder.is_dir():
        raise MalformedError(f"{folder}: not a folder")
    parts, partial = find_parts(folder)
    plan = load_json(folder / "plan.json") if (folder / "plan.json").exists() else {}
    head = load_json(folder / "TB_HEAD.json") if (folder / "TB_HEAD.json").exists() else {}
    rep_file = folder / "report" / "report.json"
    rep = load_json(rep_file) if rep_file.exists() else {}
    for name, doc in (("plan.json", plan), ("TB_HEAD.json", head), ("report/report.json", rep)):
        if not isinstance(doc, dict):
            raise MalformedError(f"{folder / name}: must be an object")
    return {"folder": folder, "parts": parts, "partial": partial, "plan": plan, "head": head, "report": rep}


def planned_tags(run: dict[str, Any], extra: list[str]) -> list[str]:
    """Every part the run was to produce, in plan order: the plan's shards, then ``--expect``, then what is there."""
    out: list[str] = []
    shards = (run["plan"].get("plan") or {}).get("shards") or run["plan"].get("shards") or []
    for tag in [t for s in shards for t in s.get("tags") or []] + extra + list(run["parts"]) + sorted(run["partial"]):
        if tag not in out:
            out.append(tag)
    return out


# ---------------------------------------------------------------- model ids never leave
def model_ids(run: dict[str, Any]) -> dict[str, str]:
    """Every model id the results name -> its role. The output carries the role only."""
    out: dict[str, str] = {}

    def add(value: Any, role: str) -> None:
        if isinstance(value, str) and value.strip():
            out[value] = role
            out[value.rsplit("/", 1)[-1]] = role

    for res in run["parts"].values():
        judging = (res.get("screen") or {}).get("judging") or {}
        add(judging.get("judge_model"), "judge")
        add(judging.get("verifier_model"), "verifier")
        for m in (res.get("canary") or {}).get("models") or []:
            add(m.get("model"), str(m.get("role") or "model"))
        add((res.get("chat_template") or {}).get("judge_model"), "judge")
    for i, m in enumerate(run["report"].get("models") or []):
        add(m, ("judge", "verifier")[i] if i < 2 else "model")
    out.pop("stub", None)
    return out


def scrub(text: str, ids: dict[str, str]) -> str:
    for model in sorted(ids, key=len, reverse=True):
        text = text.replace(model, f"<{ids[model]}>")
    return text


# ---------------------------------------------------------------- the parts
def part_status(tag: str, run: dict[str, Any], pending: set[str]) -> dict[str, Any]:
    res = run["parts"].get(tag)
    states = {x.get("tag"): x.get("state") for x in run["report"].get("not_started") or []}
    row: dict[str, Any] = {"tag": tag, "checks": 0, "failed": 0, "seconds": None, "in_flight": None, "note": ""}
    if res is None or res.get("state"):
        state = (res or {}).get("state") or states.get(tag) or ""
        if tag in run["partial"]:
            row.update(status=PENDING, note="a half-written result is in the folder")
        elif tag in pending or state == "pending":
            row.update(status=PENDING, note="its VM still runs, or it is later in this run")
        else:
            row.update(status=MISSING, note=state or "no result in the folder")
        return row
    checks = [c for st in res["stages"] for c in st.get("checks", [])]
    failed = [c for c in checks if not c[1]]
    row.update(checks=len(checks), failed=len(failed), seconds=res.get("wall_seconds"),
               in_flight=res.get("llm_concurrency"), file=res["_file"])  # fmt: skip
    if res.get("not_run"):
        row.update(status=FAILED, note=f"did not run: {res['not_run']}")
    elif failed or not checks:
        row.update(status=FAILED, note=f"{len(failed)} failed check(s)" if failed else "no check ran")
    else:
        row["status"] = PASSED
    return row


def identity(run: dict[str, Any]) -> dict[str, Any]:
    runs = [p["run"] for p in run["parts"].values() if isinstance(p.get("run"), dict)]
    ids = sorted({base_run_id(str(r["id"])) for r in runs if r.get("id")})
    heads = list(dict.fromkeys([run["head"].get("head", "")] + [str(r.get("head") or "") for r in runs]))
    heads = [h for h in heads if h]
    card = next((p["card"] for p in run["parts"].values() if isinstance(p.get("card"), str)), None)
    return {"run_ids": ids, "run_id": ids[0] if len(ids) == 1 else None, "commits": heads,
            "commit": heads[0] if len(heads) == 1 else None, "dirty": bool(run["head"].get("dirty")),
            "card": card}  # fmt: skip


def cost(
    run: dict[str, Any], rows: list[dict[str, Any]], vm_hours: float | None, price: float | None
) -> dict[str, Any]:
    plan = run["plan"]
    price = price if price is not None else plan.get("price_per_hour")
    part_hours = round(sum(float(r["seconds"] or 0) for r in rows) / 3600, 2)
    hours, source = (vm_hours, "VM hours given with --vm-hours") if vm_hours is not None else (
        part_hours, "the parts' own wall time: a lower bound, VM start and setup are not in it")  # fmt: skip
    usd = round(hours * price, 2) if price is not None else None
    cap_usd = plan.get("cap_usd")
    over = None if usd is None or cap_usd is None else usd > cap_usd
    return {"hours": hours, "hours_source": source, "part_hours": part_hours, "price_per_hour": price, "usd": usd,
            "estimate_hours": plan.get("hours"), "estimate_usd": plan.get("usd"), "cap_hours": plan.get("cap_hours"),
            "cap_usd": cap_usd, "over_cap": over}  # fmt: skip


# ---------------------------------------------------------------- G-1
def g1(run: dict[str, Any], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The chat-template verdict: both sha256 and the differing tokens. The part result lists at most five differing
    prompts with their first difference and the two lengths, not a token count: the count here is a lower bound
    (one token per listed prompt, or the difference of the two lengths when that is larger)."""
    row = rows.get(G1_TAG)
    if row is None:
        return {"status": "NOT PLANNED", "note": f"the plan has no {G1_TAG} part"}
    if row["status"] in (PENDING, MISSING):
        return {"status": row["status"], "note": row["note"]}
    block = run["parts"][G1_TAG].get("chat_template")
    if not isinstance(block, dict):
        return {"status": FAILED, "note": row["note"] or "the part has no chat_template block", "file": row["file"]}
    tok = block.get("tokens") or {}
    passed_sha = block.get("passed_text_sha256") or (block.get("passed") or {}).get("sha256")
    listed = [d for key in ("server_different", "passed_different") for d in tok.get(key) or []]
    at_least = sum(max(1, abs(d["lengths"][0] - d["lengths"][1]) if len(d.get("lengths") or []) == 2 else 1)
                   for d in listed)  # fmt: skip
    same_sha = bool(passed_sha) and passed_sha == block.get("folder_template_sha256")
    same_tok = tok.get("server_equals_folder") is True and tok.get("passed_equals_folder") is not False
    return {"status": "IDENTICAL" if same_sha and same_tok and row["status"] == PASSED else "DIFFERENT",
            "passed_sha256": passed_sha, "folder_sha256": block.get("folder_template_sha256"),
            "sha256_equal": same_sha, "prompts": tok.get("prompts"), "tokens_compared": tok.get("tokens"),
            "differing_prompts_listed": sorted({d.get("prompt") for d in listed}),
            "differing_tokens_at_least": at_least, "tokens_equal": same_tok, "file": row["file"]}  # fmt: skip


# ---------------------------------------------------------------- G-3
def part_patients(res: dict[str, Any], run: dict[str, Any]) -> int | None:
    for v in (res.get("patients"), ((res.get("scenario") or {}).get("counts") or {}).get("patients"),
              (run["parts"].get("prepare") or {}).get("patients"), run["plan"].get("patients")):  # fmt: skip
        if isinstance(v, int) and v > 0:
            return v
    return None


def setting_row(tag: str, row: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    m = re.fullmatch(r"hospital-(.+?)(?:@c(\d+))?", tag)
    assert m is not None  # the caller filters on the prefix
    out: dict[str, Any] = {"tag": tag, "lang": m.group(1), "status": row["status"],
                           "in_flight": int(m.group(2)) if m.group(2) else row.get("in_flight")}  # fmt: skip
    res = run["parts"].get(tag)
    if res is None or row["status"] in (PENDING, MISSING):
        return out
    t, metrics, cand = res.get("throughput") or {}, res.get("metrics") or {}, res.get("candidates") or {}
    gpu = metrics.get("gpu") or {}
    patients = part_patients(res, run)
    wall, busy = res.get("wall_seconds"), t.get("busy_seconds")
    opens = t.get("breaker_opens")
    out.update({
        "in_flight": out["in_flight"] or res.get("llm_concurrency"), "file": row["file"],
        "calls": t.get("calls"), "cached_calls": t.get("cached"), "calls_per_second": t.get("calls_per_second"),
        "tokens_per_second": t.get("tokens_per_second"), "tokens_in_per_second": t.get("tokens_in_per_second"),
        "tokens_out_per_second": t.get("tokens_out_per_second"), "p50_s": t.get("p50_s"), "p95_s": t.get("p95_s"),
        "gpu_util_mean_pct": gpu.get("util_mean_pct"), "gpu_util_max_pct": gpu.get("util_max_pct"),
        "gpu_memory_peak_mib": gpu.get("memory_peak_mib"), "gpu_memory_total_mib": gpu.get("memory_total_mib"),
        "breaker_opens": sum(opens.values()) if isinstance(opens, dict) else opens,
        "by_role": {ROLE_OF_ENDPOINT.get(ep, ep): {k: s.get(k) for k in ("calls", "calls_per_second",
                                                                           "tokens_per_second", "p50_s", "p95_s")}
                    for ep, s in (t.get("endpoints") or {}).items()},
        "patients": patients, "wall_seconds": wall, "model_busy_seconds": busy,
        "seconds_per_patient": round(wall / patients, 4) if wall and patients else None,
        "model_seconds_per_patient": round(busy / patients, 4) if busy and patients else None,
        "candidates": cand.get("count"), "candidates_sha256": cand.get("sha256"),
        "_list": {tuple(x) for x in cand.get("list") or []} if isinstance(cand.get("list"), list) else None,
    })  # fmt: skip
    return out


def list_verdict(settings: list[dict[str, Any]]) -> dict[str, Any]:
    """Is the candidate list the same at every setting? The reference is the list most settings share (the lowest
    setting's on a tie); a setting with another list is named."""
    have = [s for s in settings if s.get("candidates_sha256")]
    waiting = [s["in_flight"] or "the default" for s in settings if not s.get("candidates_sha256")]
    if len(have) < 2:
        return {"status": "NOT JUDGED", "note": "fewer than two settings have a candidate list", "waiting": waiting}
    count = Counter(s["candidates_sha256"] for s in have)
    top = max(count.values())
    ref = next(s for s in have if count[s["candidates_sha256"]] == top)
    same = [s["in_flight"] for s in have if s["candidates_sha256"] == ref["candidates_sha256"]]
    differing = []
    for s in have:
        if s["candidates_sha256"] == ref["candidates_sha256"]:
            continue
        d: dict[str, Any] = {"in_flight": s["in_flight"], "candidates": s.get("candidates")}
        if s.get("_list") is not None and ref.get("_list") is not None:
            d.update(only_here=len(s["_list"] - ref["_list"]), not_here=len(ref["_list"] - s["_list"]))
        differing.append(d)
    status = "DIFFERENT" if differing else ("IDENTICAL" if not waiting else "IDENTICAL SO FAR")
    return {"status": status, "reference_settings": same, "differing": differing, "waiting": waiting}


def window(args: argparse.Namespace, plan: dict[str, Any], chosen: dict[str, Any] | None) -> dict[str, Any]:
    """The calls per second the night window needs, from the site's size and the run's own calls per patient."""
    w = plan.get("window") or {}
    patients = args.window_patients or w.get("patients") or plan.get("patients")
    studies = args.studies or w.get("studies")
    hours = args.night_hours or w.get("night_hours")
    share = args.window_share or w.get("usable_share") or WINDOW_SHARE
    per = args.calls_per_patient
    per_source = "given with --calls-per-patient"
    if per is None and chosen and chosen.get("patients") and chosen.get("calls") is not None:
        demand = chosen["calls"] + (chosen.get("cached_calls") or 0)
        per = demand / chosen["patients"]
        per_source = (f"measured: {demand:,} calls for {chosen['patients']:,} patients in `{chosen['tag']}`, "
                      "taken as one study")  # fmt: skip
    out: dict[str, Any] = {"patients": patients, "studies": studies, "night_hours": hours, "usable_share": share,
                           "calls_per_patient_and_study": round(per, 5) if per is not None else None,
                           "calls_per_patient_source": per_source if per is not None else None}  # fmt: skip
    lacking = [n for n, v in (("patients (--window-patients)", patients), ("studies (--studies)", studies),
                              ("night hours (--night-hours)", hours), ("calls per patient", per)) if not v]  # fmt: skip
    if lacking:
        return {**out, "status": "NOT COMPUTED", "note": "not given and not in the plan: " + ", ".join(lacking)}
    need = patients * studies * per / (hours * 3600 * share)
    got = (chosen or {}).get("calls_per_second")
    out.update(required_calls_per_second=round(need, 3), measured_calls_per_second=got)
    out["status"] = "NOT COMPUTED" if got is None else ("MEETS" if got >= need else "BELOW")
    return out


def g3(run: dict[str, Any], rows: dict[str, dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    by_lang: dict[str, list[dict[str, Any]]] = {}
    for tag, row in rows.items():
        if tag.startswith("hospital-"):
            s = setting_row(tag, row, run)
            by_lang.setdefault(s["lang"], []).append(s)
    out: dict[str, Any] = {}
    for lang, settings in by_lang.items():
        settings.sort(key=lambda s: (s["in_flight"] is None, s["in_flight"] or 0))
        lists = list_verdict(settings)
        good = [s for s in settings if s.get("calls_per_second") is not None and not s.get("breaker_opens")
                and (s["in_flight"] in lists.get("reference_settings", [s["in_flight"]]))]  # fmt: skip
        chosen, how = None, "no setting has a measured rate, the reference list and no breaker opening"
        if args.chosen is not None:
            chosen = next((s for s in settings if s["in_flight"] == args.chosen), None)
            how = "given with --chosen" if chosen else f"--chosen {args.chosen} is not a setting of this run"
        elif good:
            chosen = max(good, key=lambda s: s["calls_per_second"])
            how = "the highest calls/s among the settings with the reference list and no breaker opening"
        out[lang] = {"settings": settings, "lists": lists, "chosen": chosen and chosen["in_flight"], "chosen_how": how,
                     "window": window(args, run["plan"], chosen)}  # fmt: skip
    return out


# ---------------------------------------------------------------- defects
def defects(run: dict[str, Any], rows: dict[str, dict[str, Any]], verdicts: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for tag, row in rows.items():
        if row["status"] != FAILED:
            continue
        res = run["parts"][tag]
        bad = [(st.get("name", "?"), c) for st in res["stages"] for c in st.get("checks", []) if not c[1]]
        if not bad:
            out.append({"title": f"`{tag}`: {row['note']}", "symptom": f"The part `{tag}` {row['note']}.",
                        "evidence": row["file"]})  # fmt: skip
        for stage, c in bad:
            detail = str(c[2])[:DETAIL_CHARS] if len(c) > 2 and c[2] not in ("", None) else "no detail"
            out.append({"title": f"`{tag}`, stage \"{stage}\": a failed check",
                        "symptom": f"The check \"{c[0]}\" failed. It returned: `{detail}`",
                        "evidence": f"{row['file']}, stage \"{stage}\""})  # fmt: skip
    one = verdicts["g1"]
    if one["status"] == "DIFFERENT":
        out.append({"title": "G-1: the passed chat template is not the weights folder's own",
                    "symptom": f"sha256 passed `{one.get('passed_sha256')}`, folder `{one.get('folder_sha256')}`; "
                               f"at least {one.get('differing_tokens_at_least')} differing token(s) in prompts "
                               f"{one.get('differing_prompts_listed')}.",
                    "evidence": f"{one.get('file')}, block `chat_template`"})  # fmt: skip
    for lang, g in verdicts["g3"].items():
        for d in g["lists"].get("differing", []):
            ref = ", ".join(str(n) for n in g["lists"]["reference_settings"])
            diff = f" {d['only_here']} listed only here, {d['not_here']} missing here." if "only_here" in d else ""
            out.append({"title": f"G-3: the candidate list of hospital-{lang} depends on the calls in flight",
                        "symptom": f"The list at {d['in_flight']} in flight differs from the list at {ref}.{diff}",
                        "evidence": f"parts `hospital-{lang}@c{d['in_flight']}`, block `candidates`"})  # fmt: skip
        w = g["window"]
        if w["status"] == "BELOW":
            out.append({"title": f"G-3: hospital-{lang} is slower than the night window needs",
                        "symptom": f"{w['measured_calls_per_second']} calls/s at {g['chosen']} in flight; the window "
                                   f"needs {w['required_calls_per_second']} ({w['patients']:,} patients, "
                                   f"{w['studies']} studies, {w['night_hours']} h).",
                        "evidence": f"capacity_inputs.json, `g3.{lang}.window`"})  # fmt: skip
        for s in g["settings"]:
            if s.get("breaker_opens"):
                out.append({"title": f"G-3: the breaker opened at {s['in_flight']} in flight (hospital-{lang})",
                            "symptom": f"{s['breaker_opens']} breaker opening(s) during `{s['tag']}`.",
                            "evidence": f"{s['file']}, `throughput.breaker_opens`"})  # fmt: skip
    if verdicts["cost"]["over_cap"]:
        c = verdicts["cost"]
        out.append({"title": "The run cost more than its cap", "evidence": "plan.json, `cap_usd`",
                    "symptom": f"US${c['usd']} against a cap of US${c['cap_usd']} ({c['hours']} h)."})  # fmt: skip
    return out


# ---------------------------------------------------------------- writing
def cell(v: Any) -> str:
    if v is None or v == "":
        return "-"
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else str(v)


def table(head: list[str], lines: list[list[Any]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |",
            *("| " + " | ".join(cell(v) for v in ln) + " |" for ln in lines)]  # fmt: skip


def money(v: Any) -> str:
    return "not in the folder" if v is None else f"US${v:,.2f}"


def g3_lines(lang: str, g: dict[str, Any]) -> list[str]:
    out = ["", f"### hospital-{lang}", ""]
    out += table(["in flight", "status", "calls/s", "tokens/s", "p50 s", "p95 s", "GPU % mean", "GPU MiB peak",
                  "GPU MiB total", "breaker opened", "listed", "list sha256"],
                 [[s["in_flight"] or "default", s["status"], s.get("calls_per_second"),
                   s.get("tokens_per_second"), s.get("p50_s"),
                   s.get("p95_s"), s.get("gpu_util_mean_pct"), s.get("gpu_memory_peak_mib"),
                   s.get("gpu_memory_total_mib"), s.get("breaker_opens"), s.get("candidates"),
                   f"`{s['candidates_sha256'][:12]}`" if s.get("candidates_sha256") else None]
                  for s in g["settings"]])  # fmt: skip
    lists, w = g["lists"], g["window"]
    out.append("")
    if lists["status"] == "DIFFERENT":
        ref = ", ".join(str(n) for n in lists["reference_settings"])
        out += [f"- **FAIL: the candidate list at {d['in_flight']} in flight differs from the list at {ref}.** "
                "The list must not depend on the calls in flight." for d in lists["differing"]]  # fmt: skip
    elif lists["status"] == "NOT JUDGED":
        out.append(f"- Candidate list: **NOT JUDGED**, {lists['note']}.")
    else:
        at = ", ".join(str(n) for n in lists["reference_settings"])
        out.append(f"- Candidate list: **{lists['status']}** at {at}"
                   " in flight.")  # fmt: skip
    if lists.get("waiting"):
        out.append(f"- No list yet at: {', '.join(str(n) for n in lists['waiting'])} in flight.")
    out.append(f"- Chosen setting: **{cell(g['chosen'])}** in flight ({g['chosen_how']}).")
    for s in g["settings"]:
        if s.get("cached_calls"):
            out.append(f"- At {s['in_flight']} in flight the gateway answered {s['cached_calls']:,} call(s) from its "
                       "cache: the rate is over the calls a server answered.")  # fmt: skip
    if w["status"] == "NOT COMPUTED":
        out.append(f"- Night window: **NOT COMPUTED**. {w.get('note') or 'No measured rate at the chosen setting.'}")
    else:
        verdict = "**PASS: meets the window.**" if w["status"] == "MEETS" else "**FAIL: below the window.**"
        out += [f"- Night window: {verdict} Measured {w['measured_calls_per_second']} calls/s; needed "
                f"{w['required_calls_per_second']} calls/s.",
                f"- How the need is computed: {w['patients']:,} patients x {w['studies']} studies x "
                f"{w['calls_per_patient_and_study']} calls per patient and study / ({w['night_hours']} h x 3600 x "
                f"{w['usable_share']}). Calls per patient and study: {w['calls_per_patient_source']}."]  # fmt: skip
    return out


def readme(v: dict[str, Any]) -> str:
    ident, c, one = v["identity"], v["cost"], v["g1"]
    counts = Counter(r["status"] for r in v["rows"])
    out = [MARK, "", f"# Cloud run results: {ident['run_id'] or 'run id not in the folder'}", "",
           "Synthetic data only. Written from the collected results folder by `deploy/gcp/results_report.py`.", "",
           f"- **Run id**: {', '.join(f'`{x}`' for x in ident['run_ids']) or 'not in the folder'}",
           f"- **Commit**: {', '.join(f'`{x}`' for x in ident['commits']) or 'not in the folder'}"
           + (" (the tree was dirty)" if ident["dirty"] else ""),
           f"- **Card**: {ident['card'] or 'not in the folder'}",
           f"- **Hours**: {c['hours']} h ({c['hours_source']}); estimate {cell(c['estimate_hours'])} h; "
           f"cap {cell(c['cap_hours'])} h",
           f"- **Cost**: {money(c['usd'])} at US${cell(c['price_per_hour'])} an hour; estimate "
           f"{money(c['estimate_usd'])}; cap {money(c['cap_usd'])}"
           + ("; **FAIL: over the cap**" if c["over_cap"] else ""),
           f"- **Parts**: {counts[PASSED]} passed, {counts[FAILED]} failed, {counts[PENDING]} pending, "
           f"{counts[MISSING]} missing, of {len(v['rows'])} planned",
           f"- **Verdict**: **{v['verdict']}**"]  # fmt: skip
    if len(ident["run_ids"]) > 1 or len(ident["commits"]) > 1:
        out.append("- **FAIL: the parts come from more than one run or commit.** Every one is named above.")
    out += ["", "## Parts", ""]
    out += table(["part", "status", "checks passed", "in flight", "seconds", "note"],
                 [[f"`{r['tag']}`", r["status"], f"{r['checks'] - r['failed']}/{r['checks']}" if r["checks"] else None,
                   r["in_flight"], r["seconds"], r["note"]] for r in v["rows"]])  # fmt: skip
    out += ["", "A part with no result is PENDING (its VM still runs, or a half-written result is there) or MISSING. "
            "Neither counts as passed.", "", "## G-1: chat template identity", ""]  # fmt: skip
    if "passed_sha256" in one:
        out += [f"- **Verdict: {one['status']}**",
                f"- sha256 of the template the serving configuration passes: `{one['passed_sha256']}`",
                f"- sha256 of the weights folder's own template: `{one['folder_sha256']}`",
                "- Differing tokens: "
                + ("0" if one["tokens_equal"] else f"at least {one['differing_tokens_at_least']}")
                + f" of {cell(one['tokens_compared'])} over {cell(one['prompts'])} prompts"
                + (f"; differing prompts listed: {one['differing_prompts_listed']} (the part lists five at most)"
                   if one["differing_prompts_listed"] else "")]  # fmt: skip
    else:
        out.append(f"- **Verdict: {one['status']}** ({one['note']})")
    out += ["", "## G-3: throughput at each number of calls in flight"]
    if not v["g3"]:
        out += ["", "The plan has no hospital part: no curve."]
    for lang, g in v["g3"].items():
        out += g3_lines(lang, g)
    out += [
        "",
        "## Defects",
        "",
        f"{len(v['defects'])} entry(ies) in `DEFECTS.md`." if v["defects"] else "None: `DEFECTS.md` is empty.",
        "",
        "Files: `capacity_inputs.json` (the figures T-667, T-637 and T-734 read), `DEFECTS.md`.",
        "",
    ]
    return "\n".join(out)


def defects_md(v: dict[str, Any]) -> str:
    ident = v["identity"]
    out = [MARK, "", f"# Defects found by run {ident['run_id'] or '(run id not in the folder)'}", "",
           "For the integrator. One entry per failed part or failed check. Each entry gives:", "",
           "- **Symptom**: what was seen.", "- **Evidence**: where it can be checked.", "- **Cause**.",
           "- **Fix**: what should change.", "- **Card**.", "- **Status**.", "",
           "Cause, Fix and Card are empty: the integrator fills them. Lane G changes no product code.", ""]  # fmt: skip
    if not v["defects"]:
        out += ["No part that ran failed, and no check of the run failed.", ""]
    for i, d in enumerate(v["defects"], 1):
        out += [f"### D{i}. {d['title']}", "", f"- **Symptom.** {d['symptom']}", f"- **Evidence.** {d['evidence']}",
                "- **Cause.**", "- **Fix.**", "- **Card.**", "- **Status.** Open.", ""]  # fmt: skip
    rest = [r for r in v["rows"] if r["status"] in (PENDING, MISSING)]
    if rest:
        out += ["## Parts with no result (not defects, not passed)", ""]
        out += [f"- `{r['tag']}`: {r['status']} ({r['note']})" for r in rest] + [""]
    return "\n".join(out)


def capacity(v: dict[str, Any]) -> dict[str, Any]:
    ident = v["identity"]

    def clean(s: dict[str, Any]) -> dict[str, Any]:
        return {k: x for k, x in s.items() if not k.startswith("_")}

    return {"schema": SCHEMA, "run_id": ident["run_id"], "run_ids": ident["run_ids"], "commit": ident["commit"],
            "commits": ident["commits"], "card": ident["card"], "synthetic_data_only": True,
            "complete": v["verdict"] == PASSED, "verdict": v["verdict"],
            "parts": {r["tag"]: r["status"] for r in v["rows"]},
            "g1": {k: x for k, x in v["g1"].items() if k != "file"},
            "g3": {lang: {"chosen_in_flight": g["chosen"], "chosen_how": g["chosen_how"],
                          "candidate_lists": g["lists"], "window": g["window"],
                          "settings": [clean(s) for s in g["settings"]]} for lang, g in v["g3"].items()},
            "cost": v["cost"]}  # fmt: skip


def build(folder: Path, args: argparse.Namespace) -> dict[str, Any]:
    run = read_run(folder)
    pending = {t for x in args.pending for t in x.replace(",", " ").split()}
    extra = [t for x in args.expect for t in x.replace(",", " ").split()]
    row_list = [part_status(tag, run, pending) for tag in planned_tags(run, extra)]
    rows = {r["tag"]: r for r in row_list}
    v: dict[str, Any] = {"identity": identity(run), "rows": row_list,
                         "cost": cost(run, row_list, args.vm_hours, args.price_per_hour)}  # fmt: skip
    v["g1"], v["g3"] = g1(run, rows), g3(run, rows, args)
    v["defects"] = defects(run, rows, v)
    mixed = len(v["identity"]["run_ids"]) > 1 or len(v["identity"]["commits"]) > 1
    if v["defects"] or mixed:
        v["verdict"] = FAILED
    else:
        v["verdict"] = "INCOMPLETE" if any(r["status"] != PASSED for r in row_list) or not row_list else PASSED
    v["model_ids"] = model_ids(run)
    return v


def write(v: dict[str, Any], out: Path, force: bool = False) -> list[Path]:
    old = out / "README.md"
    if old.exists() and not force and MARK not in old.read_text(encoding="utf-8", errors="replace"):
        raise FileExistsError(f"{old} was not written by this reader: choose another --out, or pass --force")
    out.mkdir(parents=True, exist_ok=True)
    ids = v["model_ids"]
    files = {
        "README.md": readme(v),
        "DEFECTS.md": defects_md(v),
        "capacity_inputs.json": json.dumps(capacity(v), indent=1, ensure_ascii=False, default=str) + "\n",
    }
    for name, text in files.items():
        (out / name).write_text(scrub(text, ids), encoding="utf-8")
    return [out / n for n in files]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("results", type=Path, help="the collected results folder")
    p.add_argument("--out", type=Path, required=True, help="where README.md, DEFECTS.md, capacity_inputs.json go")
    p.add_argument("--window-patients", type=int, help="patients of the site the window is for (default: the plan's)")
    p.add_argument("--studies", type=int, help="studies screened in one night")
    p.add_argument("--night-hours", type=float, help="length of the night window in hours")
    p.add_argument("--window-share", type=float, help=f"share of the window for model calls (declared: {WINDOW_SHARE})")
    p.add_argument("--calls-per-patient", type=float, help="calls per patient and study (default: measured)")
    p.add_argument("--chosen", type=int, help="the chosen calls in flight (default: the fastest sound setting)")
    p.add_argument("--vm-hours", type=float, help="billed VM hours, from the driver (default: the parts' wall time)")
    p.add_argument("--price-per-hour", type=float, help="US$ an hour (default: the plan's)")
    p.add_argument("--pending", action="append", default=[], help="tags whose VM still runs (PENDING, not MISSING)")
    p.add_argument("--expect", action="append", default=[], help="tags the run was to produce, beyond the plan's")
    p.add_argument("--force", action="store_true", help="overwrite a README.md this reader did not write")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        v = build(args.results, args)
        files = write(v, args.out, args.force)
    except MalformedError as exc:
        print(f"malformed: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    counts = Counter(r["status"] for r in v["rows"])
    print(
        f"{v['verdict']}: {counts[PASSED]} passed, {counts[FAILED]} failed, {counts[PENDING]} pending, "
        f"{counts[MISSING]} missing; {len(v['defects'])} defect(s); wrote {', '.join(str(f) for f in files)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
