"""Multilingual criterion-judging benchmark (SPEC_v4 §8.5 `judge_ml`; model selection by evidence, NFR-19).

Task: one patient note + one eligibility criterion → label + evidence sentence ids, the TrialBox S3 judge task.

Data: NCBI TrialGPT-Criterion-Annotations (1,015 patient–criterion pairs labelled by physicians, public domain;
Jin et al., Nat Commun 2024), with each of its 53 SIGIR patient notes also rendered in Traditional Chinese (zh-TW),
Japanese (ja) and Taiwanese code-mixed EMR style (mixed). Translations keep the sentence order and count, so the
expert's evidence sentence ids hold in every language. Criteria stay in English, as protocols arrive.

Models: any OpenAI-compatible endpoint. Default is OpenRouter (``OPENROUTER_API_KEY``) to compare open-weight models
before buying hardware; the same code points at the box's vLLM (``--base-url http://llm-service:8000/v1``).

    python -m tools.mlbench run --models qwen/qwen3.6-35b-a3b google/gemma-4-26b-a4b-it --langs en zh-TW ja mixed
    python -m tools.mlbench report --out eval/criterion_ml/results

Every response is cached on disk by a hash of (base_url, model, messages, params); re-runs are free and resumable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

DATA = Path(__file__).resolve().parents[1] / "eval" / "criterion_ml"
LANGS = ("en", "zh-TW", "ja", "mixed")
LABELS = {
    "inclusion": ("included", "not included", "not enough information", "not applicable"),
    "exclusion": ("excluded", "not excluded", "not enough information", "not applicable"),
}
# Screening view: does the criterion block the patient? "not applicable" never blocks.
BLOCKS = {"not included", "excluded"}
UNKNOWN = {"not enough information"}

SYSTEM = (
    "You are a clinical research coordinator assessing ONE clinical-trial eligibility criterion for ONE patient. "
    "The patient note may be written in English, Traditional Chinese, Japanese, or a mix of Chinese and English with "
    "medical abbreviations (e.g. s/p = status post, r/o = rule out, denied = negative). Read it as written; do not "
    "assume facts that are not stated. Each note sentence has an id in square brackets.\n"
    'Answer with JSON only: {"label": <label>, "evidence": [<sentence ids that support the label>], '
    '"explanation": <one short sentence in English>}.\n'
    'Labels for an inclusion criterion: "included" (the note shows the patient meets it), "not included" (the '
    'note shows the patient does not meet it), "not enough information", "not applicable".\n'
    'Labels for an exclusion criterion: "excluded" (the note shows the exclusion applies), "not excluded" (the '
    'note shows it does not apply), "not enough information", "not applicable".\n'
    'Use "not enough information" when the note does not say; an absent finding is not a negative finding unless '
    "the note states it is absent."
)


@dataclass(frozen=True)
class Pair:
    annotation_id: str
    patient_id: str
    trial_id: str
    criterion_type: str  # inclusion | exclusion
    criterion: str
    expert_label: str
    expert_sentences: tuple[int, ...]
    gpt4_label: str
    training: bool  # NCBI flag; False marks pairs where GPT-4 disagreed with the physician (see ``sample``)


@dataclass
class Result:
    model: str
    lang: str
    annotation_id: str
    label: str | None
    evidence: list[int] = field(default_factory=list)
    valid_json: bool = False
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    error: str | None = None


def norm_label(text: Any, ctype: str) -> str | None:
    if not isinstance(text, str):
        return None
    t = re.sub(r"[\s.]+$", "", text.strip().lower()).replace("_", " ")
    if t in LABELS[ctype]:
        return t
    # tolerate the other type's wording ("not met" etc.) only where unambiguous
    alias = {
        "inclusion": {"met": "included", "not met": "not included", "insufficient": "not enough information"},
        "exclusion": {"met": "excluded", "not met": "not excluded", "insufficient": "not enough information"},
    }[ctype]
    return alias.get(t)


def load_pairs(data: Path = DATA) -> list[Pair]:
    out = []
    for line in (data / "annotations.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        out.append(
            Pair(
                annotation_id=str(r["annotation_id"]),
                patient_id=r["patient_id"],
                trial_id=r["trial_id"],
                criterion_type=r["criterion_type"],
                criterion=r["criterion_text"],
                expert_label=r["expert_eligibility"],
                expert_sentences=tuple(int(i) for i in r["expert_sentences"]),
                gpt4_label=r["gpt4_eligibility"],
                training=bool(r["training"]),
            )
        )
    return out


def load_notes(lang: str, data: Path = DATA) -> dict[str, list[str]]:
    notes: dict[str, list[str]] = json.loads((data / f"notes_{lang}.json").read_text(encoding="utf-8"))
    return notes


def sample(pairs: list[Pair], n: int, seed: int = 20261017) -> list[Pair]:
    """Seeded subset: every pair whose physician label blocks the patient (the rare, safety-relevant class), then a
    label-stratified fill from the rest. ``n <= 0`` returns everything.

    The dataset's ``training`` flag is not a held-out split: it is False almost exactly where GPT-4's label differs
    from the physician's (129 of 134), so it marks hard cases. It is reported as a slice, not used for sampling."""
    if n <= 0 or n >= len(pairs):
        return list(pairs)
    rng = random.Random(seed)
    blocks = [p for p in pairs if p.expert_label in BLOCKS]
    rng.shuffle(blocks)
    by_label: dict[str, list[Pair]] = defaultdict(list)
    for p in pairs:
        if p.expert_label not in BLOCKS:
            by_label[p.expert_label].append(p)
    for v in by_label.values():
        v.sort(key=lambda p: int(p.annotation_id))
        rng.shuffle(v)
    # fill proportionally to the label distribution of the non-blocking pairs (largest remainder)
    room = max(0, n - len(blocks))
    total = sum(len(v) for v in by_label.values())
    quota = {lab: room * len(v) / total for lab, v in by_label.items()} if total else {}
    take = {lab: int(q) for lab, q in quota.items()}
    for lab in sorted(quota, key=lambda k: quota[k] - take[k], reverse=True)[: room - sum(take.values())]:
        take[lab] += 1
    fill = [p for lab, v in sorted(by_label.items()) for p in v[: take.get(lab, 0)]]
    chosen = (blocks + fill)[:n]
    return sorted(chosen, key=lambda p: int(p.annotation_id))


def messages(pair: Pair, note: list[str]) -> list[dict[str, str]]:
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(note))
    user = (
        f"Criterion type: {pair.criterion_type}\nCriterion: {pair.criterion}\n\nPatient note:\n{numbered}\n\n"
        "Return the JSON object."
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse_output(text: str) -> dict[str, Any] | None:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch == "{":
            try:
                v, _ = dec.raw_decode(t[i:])
                return v if isinstance(v, dict) else None
            except json.JSONDecodeError:
                continue
    return None


class Client:
    """OpenAI-compatible chat client with a disk cache and bounded retries."""

    def __init__(self, base_url: str, api_key: str, cache: Path, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.http = httpx.Client(timeout=timeout)
        self.openrouter = "openrouter.ai" in self.base_url

    def body(self, model: str, msgs: list[dict[str, str]]) -> dict[str, Any]:
        b: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": 0,
            "seed": 7,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
        }
        if self.openrouter:
            # public-domain synthetic data, but keep the habit: no provider training on prompts; report cost
            b["provider"] = {"data_collection": "deny"}
            b["usage"] = {"include": True}
            b["reasoning"] = {"effort": "low", "exclude": True}
        return b

    def key(self, body: dict[str, Any]) -> str:
        blob = json.dumps({"u": self.base_url, "b": body}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def chat(self, model: str, msgs: list[dict[str, str]]) -> dict[str, Any]:
        body = self.body(model, msgs)
        path = self.cache / f"{self.key(body)}.json"
        if path.exists():
            cached: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return cached
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.openrouter:
            headers |= {"HTTP-Referer": "https://github.com/zandis/Auto-GPT", "X-Title": "TrialBox mlbench"}
        last = ""
        for attempt in range(5):
            t0 = time.monotonic()
            try:
                r = self.http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as e:
                last = f"transport: {e}"
            else:
                if r.status_code == 200:
                    data = r.json()
                    data["_seconds"] = time.monotonic() - t0
                    if data.get("choices"):
                        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                        return dict(data)
                    last = f"no choices: {str(data)[:200]}"
                elif r.status_code in (400, 401, 402, 403, 404):
                    return {"_error": f"HTTP {r.status_code}: {r.text[:300]}"}
                else:
                    last = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(min(30.0, 2.0 * 2**attempt))
        return {"_error": last}


def judge(client: Client, model: str, lang: str, pair: Pair, note: list[str]) -> Result:
    data = client.chat(model, messages(pair, note))
    res = Result(model=model, lang=lang, annotation_id=pair.annotation_id, label=None)
    if "_error" in data:
        res.error = str(data["_error"])
        return res
    msg = data["choices"][0].get("message") or {}
    text = msg.get("content") or ""
    usage = data.get("usage") or {}
    res.seconds = float(data.get("_seconds", 0.0))
    res.prompt_tokens = int(usage.get("prompt_tokens") or 0)
    res.completion_tokens = int(usage.get("completion_tokens") or 0)
    res.cost = float(usage.get("cost") or 0.0)
    obj = parse_output(text)
    if obj is None:
        res.error = "unparseable"
        return res
    res.valid_json = True
    res.label = norm_label(obj.get("label"), pair.criterion_type)
    ev = obj.get("evidence") or []
    res.evidence = sorted({int(i) for i in ev if isinstance(i, int | str) and str(i).isdigit() and int(i) < len(note)})
    if res.label is None:
        res.error = f"bad label: {str(obj.get('label'))[:40]}"
    return res


def run(
    client: Client, models: Iterable[str], langs: Iterable[str], pairs: list[Pair], out: Path, workers: int = 8
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    notes = {lang: load_notes(lang) for lang in langs}
    lock = threading.Lock()
    for model in models:
        dest = out / f"{model.replace('/', '__')}.jsonl"
        done = set()
        if dest.exists():
            for line in dest.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if not (r.get("error") or "").startswith("HTTP"):
                    done.add((r["lang"], r["annotation_id"]))
        jobs = [(lang, p) for lang in notes for p in pairs if (lang, p.annotation_id) not in done]
        t0 = time.monotonic()
        with dest.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(workers) as pool:
            for res in pool.map(lambda j, m=model: judge(client, m, j[0], j[1], notes[j[0]][j[1].patient_id]), jobs):
                with lock:
                    fh.write(json.dumps(res.__dict__, ensure_ascii=False) + "\n")
                    fh.flush()
        print(f"{model}: {len(jobs)} calls in {time.monotonic() - t0:.0f} s")


# ---------------------------------------------------------------- scoring


def _f1(pred: set[int], gold: set[int]) -> float:
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    tp = len(pred & gold)
    if tp == 0:
        return 0.0
    p, r = tp / len(pred), tp / len(gold)
    return 2 * p * r / (p + r)


def cp_upper(x: int, n: int, alpha: float = 0.05) -> float:
    """One-sided Clopper–Pearson upper bound for x events in n trials (bisection on the binomial CDF)."""
    if n == 0:
        return 1.0
    if x >= n:
        return 1.0

    def cdf(p: float) -> float:
        return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(x + 1))

    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if cdf(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def score(results: list[dict[str, Any]], pairs: dict[str, Pair]) -> dict[str, Any]:
    """Metrics for one model × language. Accuracy is exact 4-way label agreement with the physician label.
    Screening metrics collapse labels to 'blocks the patient' or not: a false block silently loses an eligible
    patient (recall harm); a missed block wastes the investigator's time (precision harm)."""
    n = len(results)
    correct = valid = 0
    fb = nb = tb = pb = 0  # false blocks, non-block gold, true blocks, positive gold blocks
    ev_f1: list[float] = []
    labels_pred: Counter[str] = Counter()
    per_class: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # tp, fp, fn
    cost = secs = 0.0
    tokens = 0
    trial_gold: dict[tuple[str, str], bool] = defaultdict(bool)
    trial_pred: dict[tuple[str, str], bool] = defaultdict(bool)
    for r in results:
        p = pairs[r["annotation_id"]]
        valid += bool(r["valid_json"] and r["label"])
        pred = r["label"] or "not enough information"  # an unusable answer abstains
        labels_pred[pred] += 1
        correct += pred == p.expert_label
        for c in set(LABELS[p.criterion_type]):
            per_class[c][0] += pred == c and p.expert_label == c
            per_class[c][1] += pred == c and p.expert_label != c
            per_class[c][2] += pred != c and p.expert_label == c
        gold_block, pred_block = p.expert_label in BLOCKS, pred in BLOCKS
        trial_gold[(p.patient_id, p.trial_id)] |= gold_block
        trial_pred[(p.patient_id, p.trial_id)] |= pred_block
        if gold_block:
            pb += 1
            tb += pred_block
        else:
            nb += 1
            fb += pred_block
        if p.expert_sentences and p.expert_label not in UNKNOWN and pred == p.expert_label:
            ev_f1.append(_f1(set(r["evidence"]), set(p.expert_sentences)))
        cost += r.get("cost", 0.0)
        secs += r.get("seconds", 0.0)
        tokens += r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
    # patient × trial view: the physician blocks none of the evaluated criteria, the model blocks at least one
    open_pairs = [k for k, v in trial_gold.items() if not v]
    lost = sum(trial_pred[k] for k in open_pairs)
    f1s = []
    for tp, fp, fn in per_class.values():
        if tp + fp + fn:
            f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return {
        "n": n,
        "accuracy": correct / n if n else 0.0,
        "macro_f1": sum(f1s) / len(f1s) if f1s else 0.0,
        "valid_rate": valid / n if n else 0.0,
        "false_block_rate": fb / nb if nb else 0.0,
        "false_block_upper95": cp_upper(fb, nb),
        "block_recall": tb / pb if pb else 0.0,
        "trials_open": len(open_pairs),
        "trial_false_exclusion": lost / len(open_pairs) if open_pairs else 0.0,
        "trial_false_exclusion_upper95": cp_upper(lost, len(open_pairs)),
        "evidence_f1": sum(ev_f1) / len(ev_f1) if ev_f1 else 0.0,
        "cost_usd": cost,
        "cost_per_1k": 1000 * cost / n if n else 0.0,
        "sec_per_call": secs / n if n else 0.0,
        "tokens_per_call": tokens / n if n else 0.0,
    }


def gpt4_reference(pairs: list[Pair]) -> dict[str, Any]:
    rows = [
        {"annotation_id": p.annotation_id, "label": p.gpt4_label, "valid_json": True, "evidence": []} for p in pairs
    ]
    m = score(rows, {p.annotation_id: p for p in pairs})
    m["evidence_f1"] = None  # not comparable: NCBI stored GPT-4's sentence lists separately
    return m


def report(results_dir: Path, pairs_all: list[Pair], subset: list[Pair]) -> dict[str, Any]:
    pairs = {p.annotation_id: p for p in pairs_all}
    ids = {p.annotation_id for p in subset}
    table: dict[str, dict[str, Any]] = {}
    for f in sorted(results_dir.glob("*.jsonl")):
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        rows = [r for r in rows if r["annotation_id"] in ids]
        model = rows[0]["model"] if rows else f.stem.replace("__", "/")
        by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for r in rows:
            latest[(r["lang"], r["annotation_id"])] = r  # a resumed run's last answer wins
        for (lang, _), r in latest.items():
            by_lang[lang].append(r)
        table[model] = {lang: score(v, pairs) for lang, v in sorted(by_lang.items())}
        for lang, v in sorted(by_lang.items()):
            hard = [r for r in v if not pairs[r["annotation_id"]].training]
            if hard:
                table[model][f"_hard:{lang}"] = {"n": len(hard), "accuracy": score(hard, pairs)["accuracy"]}
        langs = [lang for lang in LANGS if lang in table[model]]
        if langs:
            accs = [table[model][lang]["accuracy"] for lang in langs]
            table[model]["_summary"] = {
                "langs": langs,
                "mean_accuracy": sum(accs) / len(accs),
                "worst_accuracy": min(accs),
                "parity_gap": max(accs) - min(accs),
                "mean_false_block": sum(table[model][lang]["false_block_rate"] for lang in langs) / len(langs),
                "cost_per_1k": sum(table[model][lang]["cost_per_1k"] for lang in langs) / len(langs),
            }
    table["NCBI GPT-4 (published labels, en)"] = {
        "en": gpt4_reference(subset),
        "_summary": {"langs": ["en"], "note": "GPT-4 labels from the dataset, English only"},
    }
    return table


def write_markdown(table: dict[str, Any], dest: Path, n_pairs: int) -> None:
    lines = [
        "# Multilingual criterion judging: model comparison",
        "",
        f"{n_pairs} patient–criterion pairs (NCBI TrialGPT-Criterion-Annotations, physician labels) × languages. "
        "Accuracy = exact 4-way label agreement with the physician. False-block rate = share of pairs where the "
        "physician did not block the patient but the model did (an eligible patient silently lost). Parity gap = best "
        "minus worst language accuracy.",
        "",
        "| model | langs | mean acc | worst acc | parity gap | false-block | cost / 1k calls (USD) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    ranked = sorted(
        ((m, v) for m, v in table.items() if "mean_accuracy" in v.get("_summary", {})),
        key=lambda kv: -kv[1]["_summary"]["mean_accuracy"],
    )
    for m, v in ranked:
        s = v["_summary"]
        lines.append(
            f"| {m} | {' '.join(s['langs'])} | {s['mean_accuracy']:.3f} | {s['worst_accuracy']:.3f} | "
            f"{s['parity_gap']:.3f} | {s['mean_false_block']:.3f} | {s['cost_per_1k']:.2f} |"
        )
    lines += [
        "",
        "## Per language",
        "",
        "| model | lang | acc | macro-F1 | false-block | block recall | evidence F1 | valid JSON | s/call |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m, v in table.items():
        for lang, s in v.items():
            if lang.startswith("_"):
                continue
            ev = "–" if s["evidence_f1"] is None else f"{s['evidence_f1']:.3f}"
            lines.append(
                f"| {m} | {lang} | {s['accuracy']:.3f} | {s['macro_f1']:.3f} | "
                f"{s['false_block_rate']:.3f} ({s['false_block_upper95']:.3f}) | "
                f"{s['trial_false_exclusion']:.3f} ({s['trial_false_exclusion_upper95']:.3f}) | "
                f"{s['block_recall']:.3f} | {ev} | {s['valid_rate']:.3f} | {s['sec_per_call']:.1f} |"
            )
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="mlbench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--langs", nargs="+", default=list(LANGS), choices=LANGS)
    r.add_argument("--n", type=int, default=400, help="pairs (0 = all 1,015)")
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--base-url", default=os.environ.get("MLBENCH_BASE_URL", "https://openrouter.ai/api/v1"))
    r.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    r.add_argument("--out", type=Path, default=DATA / "results")
    r.add_argument("--cache", type=Path, default=Path(".cache/mlbench"))
    g = sub.add_parser("report")
    g.add_argument("--n", type=int, default=400)
    g.add_argument("--out", type=Path, default=DATA / "results")
    a = ap.parse_args(argv)
    pairs = load_pairs()
    subset = sample(pairs, a.n)
    if a.cmd == "run":
        key = os.environ.get(a.api_key_env, "")
        if not key and "openrouter.ai" in a.base_url:
            raise SystemExit(f"set {a.api_key_env} (OpenRouter API key) or pass --base-url for a local server")
        run(Client(a.base_url, key or "none", a.cache), a.models, a.langs, subset, a.out, a.workers)
    table = report(a.out, pairs, subset)
    (a.out / "report.json").write_text(json.dumps(table, indent=1, ensure_ascii=False), encoding="utf-8")
    write_markdown(table, a.out / "report.md", len(subset))
    print((a.out / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
