"""Validate local TrialGPT on CGRD against physician judgment. Runs entirely inside the hospital: notes are composed
from the database, matched by the local LLM (disk cache off) and judged by physicians in blinded workbooks.
Nothing is sent to trialgpt.app or any other outside service except trial look-ups by NCT id on ClinicalTrials.gov.

    python -m trialgpt_local.cgrd.validate select   --db cgrd.sqlite --trials NCT01,NCT02 --run r1 \\
                                                    [--per-trial 20 --controls 10]
    python -m trialgpt_local.cgrd.validate run      --run r1
    python -m trialgpt_local.cgrd.validate workbook --run r1 [--criteria-pairs 40]
    python -m trialgpt_local.cgrd.validate score    --run r1   # after physicians fill trial.xlsx / criteria.xlsx

Design (mirrors the NCBI paper's evaluation where it can):
* candidates per trial: BM25 retrieval of patient notes with the trial's conditions and title (the "likely" pool),
  plus random controls — so the physician sample holds both likely-eligible and likely-ineligible patients;
* trial level: physicians grade every pair 0/1/2 blind to the model; TrialGPT's combined score is evaluated by AUROC
  (eligible vs not eligible), sensitivity/specificity/PPV at score > 0 and per-trial recall of eligible patients;
* criterion level: a stratified sample of pairs, every criterion judged; accuracy and Cohen's kappa against the
  model's labels (the paper reports 87.3 % accuracy for GPT-4 with experts at 88.7-90.0 %).

Run folders (``results/cgrd/<run>``) contain patient notes: keep them on the encrypted volume, never commit them.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from trialgpt_local import annotate, core, ctgov, metrics
from trialgpt_local.cgrd.reader import Source, compose_notes, load_mapping, pseudonym
from trialgpt_local.config import settings
from trialgpt_local.llm import LLMClient
from trialgpt_local.retrieval import HybridIndex


def run_dir(run: str) -> Path:
    """The run folder holds patient notes (and so do its workbooks): owner-only, 0700 / files 0600."""
    d = settings().results_dir / "cgrd" / run
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    return d


def _seal(d: Path) -> None:
    for p in d.iterdir():
        if p.is_file():
            p.chmod(0o600)


def _save(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_trials(spec: str) -> dict[str, dict[str, Any]]:
    """Comma-separated NCT ids (ClinicalTrials.gov) or a JSON file of trial dicts (in-house protocols)."""
    p = Path(spec)
    if p.exists():
        items = json.loads(p.read_text(encoding="utf-8"))
        return {t["NCTID"]: t for t in items}
    return ctgov.get([x.strip() for x in spec.split(",") if x.strip()])


def select(
    db: str,
    mapping: Path | None,
    trials_spec: str,
    run: str,
    per_trial: int,
    controls: int,
    index_date: date,
    mrns_file: Path | None,
    seed: int = 11,
) -> None:
    src = Source(db, load_mapping(mapping))
    mrns = mrns_file.read_text(encoding="utf-8").split() if mrns_file else src.mrns()
    notes = compose_notes(src, mrns, index_date)
    pseud = {m: pseudonym(m) for m in mrns}
    docs = [{"_id": pseud[m], "title": "", "text": n, "metadata": {"diseases_list": []}} for m, n in notes.items()]
    index = HybridIndex.build(docs, dense=False)  # BM25 over notes: cheap, deterministic, no PHI in any cache
    trials = load_trials(trials_spec)
    rng = random.Random(seed)
    pairs = []
    for nct, t in trials.items():
        queries = [*t.get("diseases_list", []), t.get("brief_title", "")]
        likely = [pid for pid, _ in index.search(queries, n=per_trial, medcpt_wt=0)]
        rest = sorted(set(pseud.values()) - set(likely))
        ctrl = rng.sample(rest, min(controls, len(rest)))
        pairs += [{"patient_id": p, "nct_id": nct, "pool": "likely"} for p in likely]
        pairs += [{"patient_id": p, "nct_id": nct, "pool": "control"} for p in ctrl]
    d = run_dir(run)
    used = {p["patient_id"] for p in pairs}
    _save(d / "notes.json", {pseud[m]: n for m, n in notes.items() if pseud[m] in used})
    _save(d / "trials.json", trials)
    _save(d / "pairs.json", pairs)
    _save(
        d / "meta.json",
        {
            "index_date": index_date.isoformat(),
            "db": Path(db).name,
            "per_trial": per_trial,
            "controls": controls,
            "patients_considered": len(mrns),
            "seed": seed,
        },
    )
    print(f"{len(pairs)} pairs ({len(trials)} trials, {len(used)} patients) -> {d}")


def run_matching(run: str) -> None:
    d = run_dir(run)
    notes, trials, pairs = _load(d / "notes.json"), _load(d / "trials.json"), _load(d / "pairs.json")
    out_path = d / "matching.json"
    out = _load(out_path) if out_path.exists() else {}
    client = LLMClient(cache=False)  # prompts contain patient notes: never written to the shared cache
    for i, p in enumerate(pairs, 1):
        key = f"{p['patient_id']}|{p['nct_id']}"
        if key in out:
            continue
        numbered, _ = core.number_patient(notes[p["patient_id"]])
        t = trials[p["nct_id"]]
        m = core.aggregate(client, core.match_trial(client, t, numbered), t, numbered)
        out[key] = {
            "score": m.score,
            "matching": m.matching_score,
            "aggregation": m.aggregation,
            "criteria": [
                {
                    "kind": c.kind,
                    "idx": c.idx,
                    "criterion": c.criterion,
                    "label": c.label,
                    "evidence": c.evidence,
                    "reasoning": c.reasoning,
                }
                for c in m.criteria
            ],
            "errors": m.errors,
        }
        _save(out_path, out)
        print(f"[{i}/{len(pairs)}] {key} score={m.score:.2f}", flush=True)


def workbooks(run: str, criteria_pairs: int, seed: int = 5) -> None:
    d = run_dir(run)
    notes, trials, pairs, res = (
        _load(d / "notes.json"),
        _load(d / "trials.json"),
        _load(d / "pairs.json"),
        _load(d / "matching.json"),
    )

    def trial_text(t: dict[str, Any]) -> str:
        return (
            f"Conditions: {', '.join(t.get('diseases_list', []))}\n"
            f"Summary: {str(t.get('brief_summary', ''))[:1500]}\n\n"
            f"Inclusion:\n{t.get('inclusion_criteria', '')}\n\nExclusion:\n{t.get('exclusion_criteria', '')}"
        )

    items = [
        {
            "item_id": f"{p['patient_id']}|{p['nct_id']}",
            "patient_id": p["patient_id"],
            "patient": notes[p["patient_id"]],
            "nct_id": p["nct_id"],
            "trial_title": trials[p["nct_id"]].get("brief_title", ""),
            "trial_text": trial_text(trials[p["nct_id"]]),
            "pool": p["pool"],
        }
        for p in pairs
    ]
    annotate.write_workbook(
        items, d / "trial.xlsx", title="CGRD validation — trial-level eligibility (PHI: internal use only)"
    )
    # criterion level: stratified by model score (high / middle / low thirds) so every verdict type is represented
    done = [p for p in pairs if f"{p['patient_id']}|{p['nct_id']}" in res]
    done.sort(key=lambda p: res[f"{p['patient_id']}|{p['nct_id']}"]["score"])
    rng = random.Random(seed)
    thirds = [done[i * len(done) // 3 : (i + 1) * len(done) // 3] for i in range(3)]
    chosen = [x for part in thirds for x in rng.sample(part, min(len(part), criteria_pairs // 3 + 1))][:criteria_pairs]
    crit_items = []
    for p in chosen:
        key = f"{p['patient_id']}|{p['nct_id']}"
        t = trials[p["nct_id"]]
        for kind in ("inclusion", "exclusion"):
            for idx, text in enumerate(core.criteria_list(t, kind)):
                crit_items.append(
                    {
                        "item_id": f"{key}|{kind}|{idx}",
                        "patient_id": p["patient_id"],
                        "patient": notes[p["patient_id"]],
                        "nct_id": p["nct_id"],
                        "trial_title": t.get("brief_title", ""),
                        "trial_text": "",
                        "kind": kind,
                        "criterion": text,
                        "idx": str(idx),
                    }
                )
    annotate.write_workbook(
        crit_items, d / "criteria.xlsx", title="CGRD validation — criterion-level (PHI: internal use only)"
    )
    _seal(d)
    print(f"trial.xlsx: {len(items)} rows; criteria.xlsx: {len(crit_items)} rows from {len(chosen)} pairs -> {d}")


def _kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else None


def score(run: str) -> str:
    d = run_dir(run)
    res = _load(d / "matching.json")
    lines = [f"# CGRD validation `{run}` — local TrialGPT vs physicians", "", f"Model: `{settings().llm_model}`.", ""]
    if (d / "trial.xlsx").exists():
        judged = [
            j for j in annotate.read_workbook(d / "trial.xlsx") if isinstance(j["answer"], int) and j["item_id"] in res
        ]
        if judged:
            s = {j["item_id"]: res[j["item_id"]]["score"] for j in judged}
            y = {j["item_id"]: j["answer"] for j in judged}
            elig = {k: 2 if v == 2 else 1 for k, v in y.items()}  # AUROC eligible (2) vs not (0/1)
            auc = metrics.auroc(s, elig, pos=2, neg=1)
            tp = sum(1 for k in y if y[k] == 2 and s[k] > 0)
            fn = sum(1 for k in y if y[k] == 2 and s[k] <= 0)
            fp = sum(1 for k in y if y[k] != 2 and s[k] > 0)
            tn = sum(1 for k in y if y[k] != 2 and s[k] <= 0)
            sens = tp / (tp + fn) if tp + fn else None
            spec = tn / (tn + fp) if tn + fp else None
            ppv = tp / (tp + fp) if tp + fp else None
            mins = [j["minutes"] for j in judged if j["minutes"]]
            lines += [
                "## Trial level",
                "",
                f"{len(judged)} pairs judged ({sum(v == 2 for v in y.values())} eligible).",
                "",
                f"- AUROC (eligible vs not): {_f(auc)}",
                f"- at score > 0: sensitivity {_f(sens)}, specificity {_f(spec)}, PPV {_f(ppv)} "
                f"(TP {tp}, FP {fp}, FN {fn}, TN {tn})",
                f"- physician minutes per pair (median): {_f(sorted(mins)[len(mins) // 2] if mins else None, 1)}",
                "",
                "| trial | pairs | eligible | recall of eligible at score > 0 | AUROC |",
                "|---|---|---|---|---|",
            ]
            for nct in sorted({str(j["nct_id"]) for j in judged}):
                ks = [j["item_id"] for j in judged if j["nct_id"] == nct]
                pos = [k for k in ks if y[k] == 2]
                rec = sum(1 for k in pos if s[k] > 0) / len(pos) if pos else None
                t_auc = metrics.auroc({k: s[k] for k in ks}, {k: elig[k] for k in ks}, pos=2, neg=1)
                lines.append(f"| {nct} | {len(ks)} | {len(pos)} | {_f(rec)} | {_f(t_auc)} |")
            lines.append("")
    if (d / "criteria.xlsx").exists():
        rows = [j for j in annotate.read_workbook(d / "criteria.xlsx") if isinstance(j["answer"], str)]
        model, doc = [], []
        for j in rows:
            pair = "|".join(j["item_id"].split("|")[:2])
            pred = next(
                (
                    c["label"]
                    for c in res.get(pair, {}).get("criteria", [])
                    if c["kind"] == j["kind"] and c["idx"] == j["idx"]
                ),
                "missing",
            )
            model.append(pred)
            doc.append(j["answer"])
        if rows:
            acc = sum(a == b for a, b in zip(model, doc, strict=True)) / len(rows)
            lines += [
                "## Criterion level",
                "",
                f"{len(rows)} criteria judged.",
                "",
                f"- accuracy {_f(acc)} (paper, GPT-4 on SIGIR: 0.873; experts 0.887-0.900)",
                f"- Cohen's kappa {_f(_kappa(model, doc))}",
                "- model 'missing' (criterion skipped or unparseable): "
                f"{model.count('missing') + model.count('parse error')}",
                "",
                "| physician \\ model | " + " | ".join(sorted(set(model))) + " |",
                "|---|" + "---|" * len(set(model)),
            ]
            for lab in sorted(set(doc)):
                c = Counter(m for m, dd in zip(model, doc, strict=True) if dd == lab)
                lines.append(f"| {lab} | " + " | ".join(str(c.get(m, 0)) for m in sorted(set(model))) + " |")
    if len(lines) <= 4:
        lines.append("No physician answers yet: fill trial.xlsx / criteria.xlsx in the run folder.")
    text = "\n".join(lines) + "\n"
    (d / "report.md").write_text(text, encoding="utf-8")
    _seal(d)
    return text


def _f(v: float | None, nd: int = 3) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trialgpt_local.cgrd.validate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--db", required=True, help="CGRD SQLite file or SQLAlchemy URL")
    s.add_argument("--mapping", type=Path, help="table/column mapping (default: synthetic CGRD schema)")
    s.add_argument("--trials", required=True, help="NCT ids (comma separated) or a JSON file of trial dicts")
    s.add_argument("--run", required=True)
    s.add_argument("--per-trial", type=int, default=20)
    s.add_argument("--controls", type=int, default=10)
    s.add_argument("--index-date", type=date.fromisoformat, default=date.today())
    s.add_argument("--mrns-file", type=Path, help="restrict to these chart numbers (one per line)")
    r = sub.add_parser("run")
    r.add_argument("--run", required=True)
    w = sub.add_parser("workbook")
    w.add_argument("--run", required=True)
    w.add_argument("--criteria-pairs", type=int, default=40)
    c = sub.add_parser("score")
    c.add_argument("--run", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "select":
        select(a.db, a.mapping, a.trials, a.run, a.per_trial, a.controls, a.index_date, a.mrns_file)
    elif a.cmd == "run":
        run_matching(a.run)
    elif a.cmd == "workbook":
        workbooks(a.run, a.criteria_pairs)
    else:
        print(score(a.run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
