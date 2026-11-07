# ruff: noqa: E501
# mypy: ignore-errors
# (one-off evaluation script of the 2026-11-07 survey; not imported by the product)
"""PHI detectors on synthetic Japanese / Traditional Chinese / English notes (eval/phi_synth, 2026-11-07).

    python tools/phi_synth_eval.py eval/phi_synth/notes.jsonl regex            # TrialBox guard recognisers
    python tools/phi_synth_eval.py eval/phi_synth/notes.jsonl pf-multi-v2      # OpenMed privacy-filter-multilingual-v2 (CPU)
    python tools/phi_synth_eval.py eval/phi_synth/notes.jsonl openmed-ja-600m  # OpenMed Japanese PII 600M (ja only)
    OPENROUTER_API_KEY=... python tools/phi_synth_eval.py eval/phi_synth/notes.jsonl google/gemma-4-26b-a4b-it

A planted identifier counts as found when detected spans cover at least half of its characters; a decoy (eponym,
drug, role word) counts as a false hit on any overlap. HF models use score >= 0.5.
"""

import concurrent.futures as cf
import json
import os
import sys
from pathlib import Path

import httpx

_R = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_R), str(_R / "libs"), str(_R / "services")]
notes = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
which = sys.argv[2]


def regex(t):
    from guard import recognisers as R

    out = []
    for _, f in R.recognisers():
        out += [(x.start, x.end) for x in f(t)]
    return out


_pipes = {}


def hf(mid):
    def f(t):
        from transformers import pipeline

        if mid not in _pipes:
            _pipes[mid] = pipeline("token-classification", model=mid, aggregation_strategy="simple", device=-1)
        return [(int(e["start"]), int(e["end"])) for e in _pipes[mid](t) if float(e["score"]) >= 0.5]

    return f


K = os.environ.get("OPENROUTER_API_KEY")
LP = """List every protected health identifier in this clinical note: names of patients, relatives or staff; dates (birth, admission, visit); addresses; phone numbers; e-mails; chart, ID or insurance numbers; named hospitals or clinics; ages over 89. Do NOT list diseases, eponyms (Parkinson, 橋本病), drugs, departments or role words.
Return only JSON {{"phi": ["exact substring", ...]}}.

NOTE:
{t}"""


def llm(model):
    def f(t):
        for _ in range(3):
            try:
                r = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": "Bearer " + K},
                    timeout=120,
                    json={
                        "model": model,
                        "temperature": 0,
                        "max_tokens": 1500,
                        "reasoning": {"enabled": False},
                        "messages": [{"role": "user", "content": LP.format(t=t)}],
                    },
                )
                c = r.json()["choices"][0]["message"]["content"]
                c = c[c.index("{") : c.rindex("}") + 1]
                spans = json.loads(c)["phi"]
                break
            except Exception:
                spans = []
        out = []
        for s in spans:
            s = str(s)
            i = t.find(s)
            while s and i >= 0:
                out.append((i, i + len(s)))
                i = t.find(s, i + 1)
        return out

    return f


D = {
    "regex": regex,
    "pf-multi-v2": hf("OpenMed/privacy-filter-multilingual-v2"),
    "openmed-ja-600m": hf("OpenMed/OpenMed-PII-Japanese-QwenMed-XLarge-600M-v1"),
}
det = D[which] if which in D else llm(which)


def ov(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def run(d):
    t = d["text"]
    if which == "openmed-ja-600m" and d["lang"] != "ja":
        return None
    try:
        spans = det(t)
    except Exception as e:
        print("err", e, file=sys.stderr)
        spans = []
    res = [("share", d["lang"], len(t), len(set(k for q in spans for k in range(q[0], q[1]))))]
    for p in d["phi"]:
        i = t.find(p["span"])
        g = (i, i + len(p["span"]))
        cov = set(k for q in spans for k in range(q[0], q[1]))
        res.append(("phi", d["lang"], p["type"], sum(k in cov for k in range(*g)) >= 0.5 * (g[1] - g[0])))
    for x in d["decoys"]:
        if any(x == p["span"] or x in p["span"] for p in d["phi"]):
            continue
        i = t.find(x)
        g = (i, i + len(x))
        res.append(("decoy", d["lang"], "", any(ov(g, q) > 0 for q in spans)))
    return res


rows = []
ex = cf.ThreadPoolExecutor(1 if which in D else 12)
for r in ex.map(run, notes):
    if r:
        rows += r
out = {}
for lang in ["ja", "zh-TW", "en"]:
    ph = [r for r in rows if r[0] == "phi" and r[1] == lang]
    sh = [r for r in rows if r[0] == "share" and r[1] == lang]
    dc = [r for r in rows if r[0] == "decoy" and r[1] == lang]
    if not ph:
        continue
    bytype = {
        ty: round(sum(r[3] for r in ph if r[2] == ty) / max(1, sum(r[2] == ty for r in ph)), 2)
        for ty in ["PERSON", "DATE", "ADDRESS", "PHONE", "ID", "FACILITY", "AGE"]
    }
    out[lang] = {
        "recall": round(sum(r[3] for r in ph) / len(ph), 3),
        "n": len(ph),
        "decoy_hit": round(sum(r[3] for r in dc) / max(1, len(dc)), 3),
        "n_decoy": len(dc),
        "text_flagged": round(sum(r[3] for r in sh) / max(1, sum(r[2] for r in sh)), 3),
        "by_type": bytype,
    }
print(json.dumps({which: out}, ensure_ascii=False))
