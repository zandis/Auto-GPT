"""TrialBox S3 judge vs TrialGPT-Matching on TrialGPT's own physician-labelled SIGIR data, same models, same harness.

* TrialBox side: the ``judge_ml`` prompt of :mod:`tools.mlbench`, one call per criterion (label + evidence ids).
* TrialGPT side: NCBI's matching prompt verbatim (``services/matching/registry_match/prompts.py``), one call per
  patient x trial x inclusion|exclusion with every criterion of the trial in one prompt.
* Data: ``eval/criterion_ml`` (1,015 pairs, 105 patient x trial pairs; physician labels, D0) and NCBI's
  ``trial_info.json`` for the criteria lists (fetched at run time, filtered to the 103 SIGIR trials, never committed).
  15 annotated criteria are not present verbatim in ``trial_info.json``; both sides are scored on the other 1,000.
* Scoring: :func:`tools.mlbench.score` for both, plus block precision and abstain rate. An unusable answer abstains
  ("not enough information") on both sides.

    python -m tools.trialgpt_compare fetch
    OPENROUTER_API_KEY=... python -m tools.trialgpt_compare run --models qwen/qwen3.6-35b-a3b --langs en ja
    python -m tools.trialgpt_compare score        # -> eval/trialgpt_compare/results/scores.json

Responses are cached by request hash (``.cache/trialgpt_compare``), so re-runs and re-scoring are free.
"""

from __future__ import annotations

import argparse
import difflib
import gzip
import importlib.util
import json
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from tools import mlbench

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "trialgpt_compare"
RESULTS = ROOT / "eval" / "trialgpt_compare" / "results"
TRIALS_FILE = CACHE / "sigir_trials.json"
FTP = "https://ftp.ncbi.nlm.nih.gov/pub/lu/TrialGPT/trial_info.json"
# thinking off where the provider allows it, low effort otherwise; the same for both pipelines
NO_THINK = {"qwen", "google", "nvidia", "nousresearch"}
# S4-style pairs scored from the recorded single-model runs: a criterion blocks only when both models block it
ENSEMBLES = [
    ("openai/gpt-oss-120b", "google/gemma-4-26b-a4b-it"),
    ("openai/gpt-oss-120b", "qwen/qwen3.6-35b-a3b"),
    ("google/gemma-4-26b-a4b-it", "qwen/qwen3.6-35b-a3b"),
]

_spec = importlib.util.spec_from_file_location("ncbi_prompts", ROOT / "services/matching/registry_match/prompts.py")
assert _spec and _spec.loader
ncbi: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ncbi)


def fetch() -> None:
    """Download NCBI trial_info.json (~1.1 GB) once and keep only the SIGIR trials of eval/criterion_ml."""
    if TRIALS_FILE.exists():
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    raw = CACHE / "trial_info.json"
    with httpx.stream("GET", FTP, timeout=900, follow_redirects=True) as r, raw.open("wb") as fh:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            fh.write(chunk)
    ids = {p.trial_id for p in mlbench.load_pairs()}
    allt = json.loads(raw.read_text())
    TRIALS_FILE.write_text(json.dumps({k: allt[k] for k in sorted(ids) if k in allt}))
    raw.unlink()


def trials() -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = json.loads(TRIALS_FILE.read_text())
    return data


def parsed_criteria(trial: dict[str, Any], kind: str) -> list[str]:
    """NCBI's ``parse_criteria`` numbering, as a list."""
    out = []
    for c in str(trial[kind + "_criteria"]).split("\n\n"):
        c = c.strip()
        if "inclusion criteria" in c.lower() or "exclusion criteria" in c.lower() or len(c) < 5:
            continue
        out.append(c)
    return out


def best_index(text: str, crits: list[str]) -> int | None:
    t = " ".join(str(text).split()).lower()
    best, score = None, 0.0
    for i, c in enumerate(crits):
        cc = " ".join(c.split()).lower()
        s = 1.0 if t == cc or (len(t) > 20 and t in cc) else difflib.SequenceMatcher(None, t, cc).ratio()
        if s > score:
            best, score = i, s
    return best if score >= 0.6 else None


def comparable(pairs: list[mlbench.Pair], tr: dict[str, dict[str, Any]]) -> list[mlbench.Pair]:
    return [p for p in pairs if best_index(p.criterion, parsed_criteria(tr[p.trial_id], p.criterion_type)) is not None]


class Client(mlbench.Client):
    max_tokens = 2000

    def body(self, model: str, msgs: list[dict[str, str]]) -> dict[str, Any]:
        b = super().body(model, msgs)
        b["max_tokens"] = self.max_tokens
        if self.openrouter:
            think_off = model.split("/", maxsplit=1)[0] in NO_THINK
            b["reasoning"] = {"enabled": False} if think_off else {"effort": "low", "exclude": True}
        return b


def _safe(model: str) -> str:
    return model.replace("/", "__")


def run_trialbox(c: Client, model: str, lang: str, workers: int) -> None:
    notes = mlbench.load_notes(lang)
    pairs = mlbench.load_pairs()
    with (
        gzip.open(RESULTS / "raw" / f"trialbox__{_safe(model)}__{lang}.jsonl.gz", "wt") as fh,
        ThreadPoolExecutor(workers) as ex,
    ):
        for res in ex.map(lambda p: mlbench.judge(c, model, lang, p, notes[p.patient_id]), pairs):
            fh.write(json.dumps(res.__dict__, ensure_ascii=False) + "\n")


def trialgpt_call(c: Client, model: str, note: list[str], trial: dict[str, Any], kind: str) -> dict[str, Any]:
    patient = "\n".join(f"{j}. {s}" for j, s in enumerate(note))
    t = dict(trial)
    t[kind + "_criteria"] = str(t[kind + "_criteria"])
    system, user = ncbi.get_matching_prompt(t, kind, patient)
    data = c.chat(model, [{"role": "system", "content": system}, {"role": "user", "content": user}])
    if "_error" in data:
        return {
            "error": data["_error"],
            "text": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "seconds": 0.0,
            "cost": 0.0,
        }
    u = data.get("usage") or {}
    return {
        "text": (data["choices"][0].get("message") or {}).get("content") or "",
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "seconds": float(data.get("_seconds", 0.0)),
        "cost": float(u.get("cost") or 0.0),
    }


def run_trialgpt(c: Client, model: str, lang: str, workers: int) -> None:
    notes, tr = mlbench.load_notes(lang), trials()
    jobs = sorted({(p.patient_id, p.trial_id, k) for p in mlbench.load_pairs() for k in ("inclusion", "exclusion")})

    def one(j: tuple[str, str, str]) -> dict[str, Any]:
        pid, tid, kind = j
        return {"patient_id": pid, "trial_id": tid, "kind": kind} | trialgpt_call(c, model, notes[pid], tr[tid], kind)

    with (
        gzip.open(RESULTS / "raw" / f"trialgpt__{_safe(model)}__{lang}.jsonl.gz", "wt") as fh,
        ThreadPoolExecutor(workers) as ex,
    ):
        for row in ex.map(one, jobs):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


ENTRY = re.compile(r'"(\d+)"\s*:\s*\[\s*"(?:[^"\\]|\\.)*"\s*,\s*(\[[^\]]*\]|"[^"]*")\s*,\s*"([^"]+)"\s*\]', re.S)


def lenient(text: str) -> dict[str, Any]:
    """JSON first; else recover every complete criterion entry (some outputs degenerate into whitespace)."""
    obj = mlbench.parse_output(text)
    if obj:
        return obj
    return {
        m.group(1): ["", [int(x) for x in re.findall(r"\d+", m.group(2))], m.group(3)] for m in ENTRY.finditer(text)
    }


def trialgpt_rows(
    calls: list[dict[str, Any]], pairs: list[mlbench.Pair], tr: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    by = {(c["patient_id"], c["trial_id"], c["kind"]): c for c in calls}
    n: dict[tuple[str, str, str], int] = defaultdict(int)
    for p in pairs:
        n[(p.patient_id, p.trial_id, p.criterion_type)] += 1
    rows = []
    for p in pairs:
        k = (p.patient_id, p.trial_id, p.criterion_type)
        if k not in by:
            continue
        c = by[k]
        obj = lenient(c.get("text") or "")
        idx = best_index(p.criterion, parsed_criteria(tr[p.trial_id], p.criterion_type))
        v = obj.get(str(idx)) if idx is not None else None
        label, ev = None, []
        if isinstance(v, list) and len(v) >= 3:
            label = mlbench.norm_label(v[2], p.criterion_type)
            ev = [int(x) for x in (v[1] or []) if str(x).isdigit()]
        share = 1 / n[k]  # a call's tokens, time and cost are shared by the criteria it judged
        rows.append(
            {
                "annotation_id": p.annotation_id,
                "label": label,
                "valid_json": bool(obj) and label is not None,
                "evidence": ev,
                "prompt_tokens": c["prompt_tokens"] * share,
                "completion_tokens": c["completion_tokens"] * share,
                "seconds": c["seconds"] * share,
                "cost": c.get("cost", 0.0) * share,
            }
        )
    return rows


def _load(p: Path) -> list[dict[str, Any]]:
    with gzip.open(p, "rt") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def score() -> dict[str, Any]:
    pairs, tr = mlbench.load_pairs(), trials()
    comp = comparable(pairs, tr)
    by_id = {p.annotation_id: p for p in comp}
    out: dict[str, Any] = {"n_pairs": len(comp), "gpt4_published": mlbench.gpt4_reference(comp)}
    for f in sorted((RESULTS / "raw").glob("*.jsonl.gz")):
        pipe, org, name, lang = f.name.removesuffix(".jsonl.gz").split("__")
        raw = _load(f)
        rows = raw if pipe == "trialbox" else trialgpt_rows(raw, comp, tr)
        rows = [r for r in rows if r["annotation_id"] in by_id]
        if not rows:
            continue
        m = mlbench.score(rows, by_id)
        blocks = [r for r in rows if (r["label"] or "") in mlbench.BLOCKS]
        m["block_precision"] = (
            sum(by_id[r["annotation_id"]].expert_label in mlbench.BLOCKS for r in blocks) / len(blocks)
            if blocks
            else None
        )
        m["abstain_rate"] = sum(
            (r["label"] or "not enough information") == "not enough information" for r in rows
        ) / len(rows)
        m["calls"] = len(raw)
        m["sec_per_call_raw"] = sum(float(c.get("seconds") or 0.0) for c in raw) / max(1, len(raw))
        out[f"{pipe}|{org}/{name}|{lang}"] = m
    for a, b in ENSEMBLES:
        for lang in mlbench.LANGS:
            fa, fb = (RESULTS / "raw" / f"trialbox__{_safe(x)}__{lang}.jsonl.gz" for x in (a, b))
            if not (fa.exists() and fb.exists()):
                continue
            ra = {r["annotation_id"]: r for r in _load(fa) if r["annotation_id"] in by_id}
            rb = {r["annotation_id"]: r for r in _load(fb) if r["annotation_id"] in by_id}
            rows = []
            for i, r in ra.items():
                both = (r["label"] or "") in mlbench.BLOCKS and (rb[i]["label"] or "") in mlbench.BLOCKS
                label = r["label"] if both or (r["label"] or "") not in mlbench.BLOCKS else "not enough information"
                rows.append(
                    r
                    | {
                        "label": label,
                        "cost": r.get("cost", 0.0) + rb[i].get("cost", 0.0),
                        "prompt_tokens": r["prompt_tokens"] + rb[i]["prompt_tokens"],
                        "completion_tokens": r["completion_tokens"] + rb[i]["completion_tokens"],
                    }
                )
            m = mlbench.score(rows, by_id)
            out[f"trialbox_s4|{a}+{b}|{lang}"] = m
    (RESULTS / "scores.json").write_text(json.dumps(out, indent=1))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="trialgpt_compare")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--pipelines", nargs="+", default=["trialbox", "trialgpt"], choices=["trialbox", "trialgpt"])
    r.add_argument("--langs", nargs="+", default=["en"], choices=mlbench.LANGS)
    r.add_argument("--workers", type=int, default=12)
    r.add_argument("--base-url", default=os.environ.get("MLBENCH_BASE_URL", "https://openrouter.ai/api/v1"))
    sub.add_parser("score")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch()
        return
    if a.cmd == "score":
        for k, v in score().items():
            if isinstance(v, dict):
                print(
                    f"{k:55s} acc={v['accuracy']:.3f} false_block={v['false_block_rate']:.3f} "
                    f"pairs_lost={v['trial_false_exclusion']:.3f} $/1k={v['cost_per_1k']:.3f}"
                )
        return
    fetch()
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    key = os.environ.get("OPENROUTER_API_KEY", "none")
    for model in a.models:
        for lang in a.langs:
            for pipe in a.pipelines:
                c = Client(a.base_url, key, CACHE / "responses")
                c.max_tokens = 2000 if pipe == "trialbox" else 6000
                (run_trialbox if pipe == "trialbox" else run_trialgpt)(c, model, lang, a.workers)
                print("done", pipe, model, lang, flush=True)


if __name__ == "__main__":
    main()
