"""Reading real Japanese clinical text: the TrialBox judge on NTCIR-16 Real-MedNLP MedTxt-CR / MedTxt-RR.

Earlier Japanese numbers came from machine-translated SIGIR notes. MedTxt is real Japanese text written by clinicians:
148 case reports (MedTxt-CR, training split; the test split is not redistributed) and 135 radiology reports
(MedTxt-RR), each with an English translation, with every disease / finding tagged ``<d certainty=...>``: positive,
negative (stated absent), suspicious, general. Licence CC BY 4.0 (Sociocom, NAIST); fetched at run time, never
committed.

Each tagged finding becomes one exclusion criterion, "Patients with <finding>." (the English wording of the tag, as an
international protocol would read), judged against the Japanese original and against the English translation:

* ``positive``   -> the exclusion applies; blocking is right (recall)
* ``negative``   -> the note states it is absent; blocking is a **false block** (negation error)
* ``suspicious`` -> suspected, not confirmed; TrialBox should route to review, so blocking is an over-block
* ``absent``     -> a finding from another report that this report never mentions; blocking is a hallucinated block

Only reports whose JA and EN tag sequences align are used, so the label comes from the Japanese annotation and the
criterion text from the aligned English tag. Same prompt and client as :mod:`tools.mlbench`.

    python -m tools.medtxt_eval fetch
    OPENROUTER_API_KEY=... python -m tools.medtxt_eval run --models openai/gpt-oss-120b google/gemma-4-26b-a4b-it
    python -m tools.medtxt_eval score             # -> eval/medtxt/results/scores.json
"""

from __future__ import annotations

import argparse
import gzip
import html
import io
import json
import os
import random
import re
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import httpx

from tools import mlbench
from tools.trec_ct_eval import cluster_ci, wilson
from tools.trialgpt_compare import Client, _safe, _split

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "medtxt"
RESULTS = ROOT / "eval" / "medtxt" / "results"
URL = "https://sociocom.naist.jp/download/real-mednlp-test-collection/?wpdmdl=4864"
SEED = 20261105
FILES = {
    "CR": ["MedTxt-CR/MedTxt-CR-{L}-training-pub.xml"],
    "RR": ["MedTxt-RR/MedTxt-RR-{L}-training-pub.xml", "MedTxt-RR/MedTxt-RR-{L}-test-answer-pub.xml"],
}
LANGS = ("ja", "en")
# Candidate amendment to the judge prompt (tested here, not yet in services/orchestrator/prompts/judge_v3.md): a
# suspected finding is not a confirmed one, so it should go to review rather than exclude the patient.
SUSPECTED = (
    " A finding the note calls suspected, possible, probable, likely, 'cannot be ruled out' or 'to be ruled out' is "
    'not confirmed: answer "not enough information" for it, unless the criterion itself asks about a suspected '
    "diagnosis. A condition the note says has resolved, disappeared or been removed is part of the history: judge it "
    "as history."
)
VARIANTS = {"base": "", "suspected": SUSPECTED}
OUTCOME = {"positive": "applies", "negative": "stated_absent", "suspicious": "suspected", "absent": "not_mentioned"}


def fetch() -> None:
    dest = CACHE / "Test collection"
    if dest.exists():
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    r = httpx.get(URL, timeout=120, follow_redirects=True)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for n in z.namelist():
            if n.startswith("Test collection/") and n.endswith(".xml") and "__MACOSX" not in n:
                out = CACHE / n
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(n))


ART = re.compile(r'<article id="([^"]+)"[^>]*>(.*?)</article>', re.S)
DTAG = re.compile(r'<d certainty="(\w+)"[^>]*>(.*?)</d>', re.S)
TAG = re.compile(r"<[^>]+>")


def articles(corpus: str, lang: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in FILES[corpus]:
        text = (CACHE / "Test collection" / f.format(L=lang.upper())).read_text(encoding="utf-8")
        out |= {f"{corpus}:{k}": v for k, v in ART.findall(text)}
    return out


def sentences(raw: str, lang: str) -> list[str]:
    plain = html.unescape(TAG.sub("", raw))
    parts = re.split(r"(?<=[。．])|\n" if lang == "ja" else r"(?<=[.!?])\s+|\n", plain)
    return [" ".join(p.split()) for p in parts if p and p.strip()]


def dataset() -> tuple[list[dict[str, Any]], dict[str, dict[str, list[str]]]]:
    """Items (report, criterion, outcome) and notes[lang][report]."""
    rng = random.Random(SEED)
    notes: dict[str, dict[str, list[str]]] = {lang: {} for lang in LANGS}
    items: list[dict[str, Any]] = []
    positives_pool: list[tuple[str, str]] = []
    per_report: list[tuple[str, list[tuple[str, str]]]] = []
    for corpus in FILES:
        ja, en = articles(corpus, "ja"), articles(corpus, "en")
        for rid in sorted(ja):
            tj, te = DTAG.findall(ja[rid]), DTAG.findall(en.get(rid, ""))
            if [c for c, _ in tj] != [c for c, _ in te]:
                continue  # tags not aligned: no trustworthy English wording for the Japanese label
            notes["ja"][rid], notes["en"][rid] = sentences(ja[rid], "ja"), sentences(en[rid], "en")
            tags = [(c, " ".join(html.unescape(TAG.sub("", t)).split())) for (c, _), (_, t) in zip(tj, te, strict=True)]
            per_report.append((rid, tags))
            positives_pool += [(rid, t) for c, t in tags if c == "positive" and 3 <= len(t) <= 60]
    for rid, tags in per_report:
        seen: set[str] = set()
        keep = []
        for c, t in tags:
            k = t.lower()
            if c == "general" or k in seen or not (3 <= len(t) <= 80):
                continue
            seen.add(k)
            keep.append((c, t))
        neg_sus = [x for x in keep if x[0] in ("negative", "suspicious")]
        pos = [x for x in keep if x[0] == "positive"]
        rng.shuffle(pos)
        chosen = neg_sus + pos[: max(2, len(neg_sus))]
        text_en = " ".join(notes["en"][rid]).lower()
        others = [t for r, t in positives_pool if r != rid and t.lower() not in text_en]
        rng.shuffle(others)
        chosen += [("absent", t) for t in others[:2]]
        for i, (c, t) in enumerate(chosen):
            items.append(
                {"id": f"{rid}|{i}", "report": rid, "finding": t, "certainty": c, "strict": strict(c, t, tags, text_en)}
            )
    return items, notes


GENERIC = {
    "findings",
    "finding",
    "mass",
    "masses",
    "lesion",
    "lesions",
    "shadow",
    "shadows",
    "abnormality",
    "abnormalities",
    "change",
    "changes",
    "nodes",
    "lymph nodes",
    "symptoms",
    "opacity",
    "opacities",
}


def _head(t: str) -> str:
    w = re.findall(r"[a-z0-9]+", t.lower())
    return w[-1] if w else ""


def strict(certainty: str, finding: str, tags: list[tuple[str, str]], text_en: str) -> bool:
    """A tag is local (one sentence), a criterion is about the patient. Keep a negative or suspicious tag as a
    report-level fact only when nothing else in the report says the same thing: the finding occurs once, no positive
    (or, for negatives, suspicious) tag shares its head word, and it is not a generic word ("mass", "shadows")."""
    if certainty in ("positive", "absent"):
        return True
    f = finding.lower()
    if f in GENERIC or _head(f) in GENERIC or text_en.count(f) > 1:
        return False
    other = {"positive", "suspicious"} if certainty == "negative" else {"positive"}
    return not any(c in other and _head(t) == _head(f) for c, t in tags)


def criterion(item: dict[str, Any]) -> mlbench.Pair:
    return mlbench.Pair(
        annotation_id=item["id"],
        patient_id=item["report"],
        trial_id="medtxt",
        criterion_type="exclusion",
        criterion=f"Patients with {item['finding']}.",
        expert_label="",
        expert_sentences=(),
        gpt4_label="",
        training=False,
    )


def variant_of(model: str) -> str:
    return model.partition("~")[2] or "base"


def raw_path(model: str, lang: str) -> Path:
    """``model~variant`` names a prompt variant (``~suspected``); the plain name is the unchanged mlbench prompt."""
    return RESULTS / "raw" / f"{_safe(model)}__{lang}.jsonl.gz"


def _judge(c: Client, model: str, lang: str, notes: dict[str, list[str]], p: mlbench.Pair) -> mlbench.Result:
    return mlbench.judge(c, model, lang, p, notes[p.patient_id])


def run(models: list[str], base_url: str, workers: int, variant: str = "base") -> None:
    items, notes = dataset()
    base_system = mlbench.SYSTEM
    mlbench.SYSTEM = base_system + VARIANTS[variant]  # read by mlbench.messages at call time
    key = os.environ.get("OPENROUTER_API_KEY", "none")
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    for model in models:
        c = Client(base_url, key, CACHE / "responses")
        base, c.quant = _split(model)
        tag = model if variant == "base" else f"{model}~{variant}"
        for lang in LANGS:
            with gzip.open(raw_path(tag, lang), "wt", encoding="utf-8") as fh, ThreadPoolExecutor(workers) as ex:
                jobs = [criterion(it) for it in items]
                one = partial(_judge, c, base, lang, notes[lang])
                for res in ex.map(one, jobs):
                    fh.write(json.dumps(res.__dict__, ensure_ascii=False) + "\n")
            print("done", tag, lang, len(items), flush=True)
    mlbench.SYSTEM = base_system


def load(model: str, lang: str) -> dict[str, dict[str, Any]]:
    with gzip.open(raw_path(model, lang), "rt", encoding="utf-8") as fh:
        return {r["annotation_id"]: r for r in map(json.loads, fh)}


def score_combo(models: list[str], lang: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    ans = {m: load(m, lang) for m in models}
    flags: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    cost = 0.0
    unanswered = 0
    for it in items:
        rs = [ans[m].get(it["id"], {}) for m in models]
        cost += sum(float(r.get("cost") or 0.0) for r in rs)
        unanswered += sum(1 for r in rs if not r or r.get("error"))
        blk = all((r.get("label") or "") in mlbench.BLOCKS for r in rs)
        flags[it["certainty"]].append((it["report"], blk))
        if it["strict"]:
            flags[f"{it['certainty']}_strict"].append((it["report"], blk))
        flags[f"{it['certainty']}_{it['report'].split(':')[0]}"].append((it["report"], blk))
    out: dict[str, Any] = {}
    for k, f in sorted(flags.items()):
        n, b = len(f), sum(x for _, x in f)
        out[k] = {
            "n": n,
            "blocked": b,
            "rate": b / n if n else 0.0,
            "wilson95": wilson(b, n),
            "cluster95": cluster_ci(f),
        }
    out["cost_usd"] = round(cost, 4)
    out["unanswered"] = unanswered
    return out


def score() -> dict[str, Any]:
    items, notes = dataset()
    models = sorted({f.name.rsplit("__", 1)[0].replace("__", "/", 1) for f in (RESULTS / "raw").glob("*.jsonl.gz")})
    res: dict[str, Any] = {
        "reports": len(notes["ja"]),
        "items": {c: sum(1 for i in items if i["certainty"] == c) for c in OUTCOME},
        "items_strict": {c: sum(1 for i in items if i["certainty"] == c and i["strict"]) for c in OUTCOME},
        "single": {},
        "both_must_block": {},
    }
    for lang in LANGS:
        for m in models:
            res["single"][f"{m}|{lang}"] = score_combo([m], lang, items)
        for i, a in enumerate(models):
            for b in models[i + 1 :]:
                if variant_of(a) != variant_of(b):
                    continue
                res["both_must_block"][f"{a}+{b}|{lang}"] = score_combo([a, b], lang, items)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "scores.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="medtxt_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("stats")
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--workers", type=int, default=16)
    r.add_argument("--variant", default="base", choices=sorted(VARIANTS))
    r.add_argument("--base-url", default=os.environ.get("MLBENCH_BASE_URL", "https://openrouter.ai/api/v1"))
    sub.add_parser("score")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch()
    elif a.cmd == "stats":
        fetch()
        items, notes = dataset()
        print(len(notes["ja"]), "reports", {c: sum(1 for i in items if i["certainty"] == c) for c in OUTCOME})
    elif a.cmd == "run":
        fetch()
        run(a.models, a.base_url, a.workers, a.variant)
    else:
        res = score()
        for group in ("single", "both_must_block"):
            for k, v in res[group].items():
                cells = "  ".join(
                    f"{c}={100 * v[c]['rate']:.1f}% ({100 * v[c]['cluster95'][0]:.0f}-{100 * v[c]['cluster95'][1]:.0f})"
                    for c in ("positive", "negative_strict", "suspicious_strict", "absent")
                    if c in v
                )
                print(f"{k:72s} blocked: {cells}")


if __name__ == "__main__":
    main()
