"""Embedding comparison (owner's approval of 2026-11-09, D-148): bge-m3 against Qwen3-Embedding-0.6B on Japanese and
Traditional Chinese clinical-style text, on the card.

    python -m tools.bench_embed build --synth <synthetic hospital> --out set.json   # the labelled set (stdlib only)
    python -m tools.bench_embed run --set set.json --out result.json --backend hf   # on the GPU (torch, transformers)
    python -m tools.bench_embed run --set set.json --out result.json --backend hash # anywhere: a tiny stub encoder

The labelled set is made from the synthetic hospital (``tools.synth_hospital``: fictional patients only, never real
patient data). Documents: every ja and zh-TW note. Queries, per language:

* **needle** queries: the generator's planted retrieval needles (``needles.json``, keyword-style); relevant = every
  note that contains the needle's sentence;
* **finding** queries: two plain-language questions per note finding (criterion and value in ``gold/notes.jsonl``),
  written here as a coordinator would ask, not copied from the generator's sentences; relevant = every note with
  that finding. Each pair of a criterion's values (e.g. a gout attack now / no attack now) is a negation trap.

Measured per model: throughput over every document (docs/s, tokens/s, the model's own tokenizer, after a warm-up),
GPU memory (weights, and the peak while encoding, from torch), retrieval quality over the whole bilingual corpus
(needle: MRR@10 and recall@10; finding: nDCG@10 and precision@10), per language. The on-disk size of a vector is
pgvector's ``halfvec``: 2 bytes per dimension plus an 8-byte header, at 1024 dimensions (both models' native size).
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Protocol

LANGS = ("ja", "zh-TW")
DIMS = 1024
SYNTH_SITES = "jp-a:JP:2000,tw-a:TW:2000"  # about 3,300 notes per site, about 90 % in the site's language
MODELS = {  # name -> (Hugging Face id, pooling, query instruction)
    "bge-m3": ("BAAI/bge-m3", "cls", ""),
    "qwen3-embedding-0.6b": (
        "Qwen/Qwen3-Embedding-0.6B",
        "last",
        "Instruct: Given a clinical question, retrieve patient notes that answer it\nQuery:",
    ),
}
MAX_TOKENS = 1024
BATCH = 32

# finding -> per language, two questions as a coordinator would ask them (paraphrases, not the generator's sentences)
FINDING_QUERIES: dict[tuple[str, str], dict[str, list[str]]] = {
    ("GZQO-INC-05", "yes"): {
        "ja": ["コルヒチンで治療した急性痛風発作の既往がある患者", "最近痛風の発作で関節が腫れた人"],
        "zh-TW": ["曾以秋水仙素治療急性痛風發作的病人", "最近因痛風發作關節腫痛的人"],
    },
    ("GZQO-INC-05", "no"): {
        "ja": ["この一年、痛風発作を繰り返していない患者", "痛風発作が一年に一回以下の人"],
        "zh-TW": ["過去一年沒有反覆痛風發作的病人", "一年內痛風發作不超過一次的人"],
    },
    ("GZQO-EXC-11", "yes"): {
        "ja": ["今まさに急性痛風発作を起こしている患者", "現在、足の親指の付け根が赤く腫れて痛む人"],
        "zh-TW": ["目前正處於急性痛風發作的病人", "現在大腳趾根部紅腫疼痛的人"],
    },
    ("GZQO-EXC-11", "no"): {
        "ja": ["診察時に急性発作がなく関節の圧痛もない患者", "今は痛風の発作が起きていない人"],
        "zh-TW": ["就診時沒有急性發作、關節也無壓痛的病人", "目前沒有痛風發作的人"],
    },
    ("GZQO-INC-07", "willing"): {
        "ja": ["週一回の自己注射に同意している患者", "自分で皮下注射をしてもよいと言っている人"],
        "zh-TW": ["同意每週自行注射一次的病人", "願意自己打皮下注射的人"],
    },
    ("GZQO-INC-07", "unwilling"): {
        "ja": ["注射が怖くて自己注射を断った患者", "自己注射を希望しない人"],
        "zh-TW": ["因怕打針而拒絕自行注射的病人", "不想自己打針的人"],
    },
    ("RA-BIO-REN-02", "yes"): {
        "ja": ["生物学的製剤で関節リウマチの疾患活動性が十分下がった患者", "DAS28がしっかり改善している人"],
        "zh-TW": ["使用生物製劑後類風濕性關節炎活動度明顯下降的病人", "DAS28改善良好的人"],
    },
    ("RA-BIO-REN-02", "no"): {
        "ja": ["関節リウマチの治療効果が乏しく薬の変更を考えている患者", "DAS28があまり下がっていない人"],
        "zh-TW": ["類風濕性關節炎治療效果不佳、考慮換藥的病人", "DAS28下降有限的人"],
    },
    ("ONC-OSI-INC-04", "yes"): {
        "ja": ["全身状態が良く身の回りのことが自分でできるがん患者", "PSが良好な人"],
        "zh-TW": ["體能狀態良好、生活可以自理的癌症病人", "日常活動能力良好的人"],
    },
}


# ------------------------------------------------------------------------------------------------ the labelled set
def build_set(synth: Path) -> dict[str, Any]:
    """Documents and queries with their relevant document ids, from a synthetic hospital's sites (ja and zh-TW
    notes only)."""
    summary = json.loads((synth / "summary.json").read_text(encoding="utf-8"))
    csv.field_size_limit(10_000_000)
    docs: list[dict[str, str]] = []
    finding_docs: dict[tuple[str, str, str], list[str]] = {}
    needles: list[dict[str, str]] = []
    for site in summary["sites"]:
        d = synth / site["dir"]
        gold = {}
        for line in (d / "gold" / "notes.jsonl").read_text(encoding="utf-8").splitlines():
            g = json.loads(line)
            gold[g["note_no"]] = g
        with (d / "note.csv").open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                g = gold.get(row["note_no"], {})
                lang = g.get("lang", "")
                if lang not in LANGS:
                    continue
                doc_id = f"{site['dir']}/{row['note_no']}"
                docs.append({"id": doc_id, "lang": lang, "text": row["text"]})
                for f in g.get("findings") or []:
                    finding_docs.setdefault((lang, f["criterion"], f["value"]), []).append(doc_id)
        if (d / "needles.json").exists():
            needles += json.loads((d / "needles.json").read_text(encoding="utf-8"))
    by_lang = {lang: [x for x in docs if x["lang"] == lang] for lang in LANGS}
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in needles:
        lang = next((lg for lg in LANGS if any(n["fragment"] in x["text"] for x in by_lang[lg][:])), "")
        if not lang or n["query"] in seen:
            continue
        seen.add(n["query"])
        rel = [x["id"] for x in by_lang[lang] if n["fragment"] in x["text"]]
        queries.append({"id": f"needle-{len(queries)}", "kind": "needle", "lang": lang, "text": n["query"],
                        "relevant": rel})  # fmt: skip
    for (crit, value), texts in FINDING_QUERIES.items():
        for lang in LANGS:
            rel = finding_docs.get((lang, crit, value), [])
            if not rel:
                continue
            for k, text in enumerate(texts[lang]):
                queries.append({"id": f"{crit}={value}/{lang}/{k}", "kind": "finding", "lang": lang, "text": text,
                                "criterion": crit, "value": value, "relevant": rel})  # fmt: skip
    counts = {lang: sum(1 for q in queries if q["lang"] == lang) for lang in LANGS}
    return {
        "source": "tools.synth_hospital (fictional patients only)",
        "docs": docs,
        "queries": queries,
        "counts": {"docs": {lang: len(by_lang[lang]) for lang in LANGS}, "docs_total": len(docs), "queries": counts},
    }


# ------------------------------------------------------------------------------------------------ encoders
class Encoder(Protocol):
    name: str
    model_id: str
    dims: int

    def encode(self, texts: list[str], query: bool) -> Any: ...  # (n, dims) float32, L2-normalised rows

    def tokens(self, texts: list[str]) -> int: ...

    def memory(self) -> dict[str, float]: ...


class HashEncoder:
    """A tiny, deterministic stand-in for tests and the laptop: character bigrams hashed into ``dims`` buckets."""

    def __init__(self, name: str = "hash-stub", dims: int = DIMS) -> None:
        self.name, self.model_id, self.dims = name, "hash", dims

    def encode(self, texts: list[str], query: bool) -> Any:
        import zlib

        import numpy as np

        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for i, t in enumerate(texts):
            for a, b in itertools.pairwise(t):
                out[i, zlib.crc32((a + b).encode()) % self.dims] += 1.0
        norm = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norm == 0, 1, norm)

    def tokens(self, texts: list[str]) -> int:
        return sum(len(t) for t in texts)

    def memory(self) -> dict[str, float]:
        return {}


class HfEncoder:  # pragma: no cover - needs a GPU and the weights; runs in the vLLM image on the card
    """A Hugging Face model in fp16 on CUDA, pooled as its model card says: bge-m3 the [CLS] vector, Qwen3-Embedding
    the last token (left padding), queries with its instruction. Rows L2-normalised."""

    def __init__(self, name: str) -> None:
        import torch  # type: ignore[import-not-found,unused-ignore]
        from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found,unused-ignore]

        self.name = name
        self.model_id, self.pooling, self.instruction = MODELS[name]
        self.torch = torch
        torch.cuda.reset_peak_memory_stats()
        before = torch.cuda.memory_allocated()
        self.tok = AutoTokenizer.from_pretrained(
            self.model_id, padding_side="left" if self.pooling == "last" else "right"
        )
        self.model = AutoModel.from_pretrained(self.model_id, torch_dtype=torch.float16).cuda().eval()
        self.weights_mib = (torch.cuda.memory_allocated() - before) / 2**20
        self.dims = int(self.model.config.hidden_size)

    def _batch(self, texts: list[str]) -> Any:
        return self.tok(texts, padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt").to("cuda")

    def encode(self, texts: list[str], query: bool) -> Any:
        torch = self.torch
        if query and self.instruction:
            texts = [f"{self.instruction}{t}" for t in texts]
        out = []
        with torch.inference_mode():
            for i in range(0, len(texts), BATCH):
                b = self._batch(texts[i : i + BATCH])
                h = self.model(**b).last_hidden_state
                v = h[:, 0] if self.pooling == "cls" else h[:, -1]
                out.append(torch.nn.functional.normalize(v.float(), dim=-1).cpu())
        torch.cuda.synchronize()
        return torch.cat(out).numpy()

    def tokens(self, texts: list[str]) -> int:
        return sum(min(len(ids), MAX_TOKENS) for ids in self.tok(texts, truncation=False)["input_ids"])

    def memory(self) -> dict[str, float]:
        t = self.torch
        return {
            "weights_mib": round(self.weights_mib, 1),
            "peak_allocated_mib": round(t.cuda.max_memory_allocated() / 2**20, 1),
            "peak_reserved_mib": round(t.cuda.max_memory_reserved() / 2**20, 1),
        }


# ------------------------------------------------------------------------------------------------ measures
def halfvec_bytes(dims: int = DIMS) -> int:
    """pgvector ``halfvec``: 2 bytes per dimension plus an 8-byte header (``vector``: 4 per dimension plus 8)."""
    return 2 * dims + 8


def storage(dims: int = DIMS, n: int = 1_000_000) -> dict[str, Any]:
    h = halfvec_bytes(dims)
    return {
        "dims": dims,
        "halfvec_bytes": h,
        "vector_fp32_bytes": 4 * dims + 8,
        "halfvec_mib_per_million": round(h * n / 2**20, 1),
        "note": "column value only; each table row adds its tuple header and the id, an HNSW index adds its own",
    }


def retrieval(
    doc_ids: list[str], doc_vecs: Any, queries: list[dict[str, Any]], q_vecs: Any, k: int = 10
) -> dict[str, Any]:
    """Cosine top-k over the whole corpus (both languages). Needle: MRR@k, recall@k. Finding: nDCG@k, P@k."""
    import numpy as np

    scores = q_vecs @ doc_vecs.T
    top = np.argsort(-scores, axis=1)[:, :k]
    per: dict[str, dict[str, list[float]]] = {}
    for qi, q in enumerate(queries):
        rel = set(q["relevant"])
        hits = [doc_ids[j] in rel for j in top[qi]]
        m = per.setdefault(f"{q['kind']}/{q['lang']}", {})
        if q["kind"] == "needle":
            first = next((r + 1 for r, h in enumerate(hits) if h), 0)
            m.setdefault(f"mrr@{k}", []).append(1 / first if first else 0.0)
            m.setdefault(f"recall@{k}", []).append(sum(hits) / max(1, min(k, len(rel))))
        else:
            dcg = sum(1 / math.log2(r + 2) for r, h in enumerate(hits) if h)
            ideal = sum(1 / math.log2(r + 2) for r in range(min(k, len(rel))))
            m.setdefault(f"ndcg@{k}", []).append(dcg / ideal if ideal else 0.0)
            m.setdefault(f"p@{k}", []).append(sum(hits) / k)
    return {g: {name: round(sum(v) / len(v), 4) for name, v in ms.items()} | {"queries": len(next(iter(ms.values())))}
            for g, ms in sorted(per.items())}  # fmt: skip


def bench(enc: Encoder, labelled: dict[str, Any]) -> dict[str, Any]:
    docs = labelled["docs"]
    texts = [d["text"] for d in docs]
    enc.encode(texts[: min(64, len(texts))], query=False)  # warm-up (kernels, allocator)
    t0 = time.perf_counter()
    doc_vecs = enc.encode(texts, query=False)
    doc_s = time.perf_counter() - t0
    qs = labelled["queries"]
    t0 = time.perf_counter()
    q_vecs = enc.encode([q["text"] for q in qs], query=True)
    q_s = time.perf_counter() - t0
    n_tok = enc.tokens(texts)
    per_lang = {}
    for lang in LANGS:
        idx = [i for i, d in enumerate(docs) if d["lang"] == lang]
        per_lang[lang] = {"docs": len(idx), "tokens": enc.tokens([texts[i] for i in idx])}
    return {
        "name": enc.name,
        "model_id": enc.model_id,
        "dims": int(doc_vecs.shape[1]),
        "throughput": {
            "docs": len(texts),
            "tokens": n_tok,
            "seconds": round(doc_s, 2),
            "docs_per_s": round(len(texts) / doc_s, 1),
            "tokens_per_s": round(n_tok / doc_s, 1),
            "batch": BATCH,
            "max_tokens": MAX_TOKENS,
            "queries_seconds": round(q_s, 3),
            "per_lang": per_lang,
        },
        "memory": enc.memory(),
        "retrieval": retrieval([d["id"] for d in docs], doc_vecs, qs, q_vecs),
        "storage": storage(int(doc_vecs.shape[1])),
    }


def run(labelled: dict[str, Any], encoders: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"set": labelled["counts"], "source": labelled["source"], "models": []}
    for make in encoders:
        try:
            enc = make()
            out["models"].append(bench(enc, labelled))
            del enc
        except Exception as exc:  # one model that does not load is a row, not a lost bench
            out["models"].append({"name": getattr(make, "name", str(make)), "dims": 0, "error": repr(exc)[:300],
                                  "throughput": {"docs": 0}})  # fmt: skip
        _free()
    return out


def _free() -> None:
    import gc

    gc.collect()
    try:  # pragma: no cover - only with torch on a GPU
        import torch  # type: ignore[import-not-found,unused-ignore]

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def summary(res: dict[str, Any]) -> dict[str, Any]:
    """The comparison in one block for the report."""
    rows = {}
    for m in res.get("models") or []:
        if m.get("error"):
            rows[m["name"]] = {"error": m["error"]}
            continue
        t, r = m["throughput"], m["retrieval"]
        rows[m["name"]] = {
            "docs_per_s": t["docs_per_s"],
            "tokens_per_s": t["tokens_per_s"],
            "memory": m["memory"],
            "retrieval": r,
            "halfvec_bytes": m["storage"]["halfvec_bytes"],
            "halfvec_mib_per_million": m["storage"]["halfvec_mib_per_million"],
        }
    return {"set": res.get("set"), "models": rows}


def markdown(res: dict[str, Any]) -> str:
    lines = [
        "| model | docs/s | tokens/s | GPU weights MiB | GPU peak MiB | needle MRR@10 ja / zh-TW | "
        "finding nDCG@10 ja / zh-TW | halfvec bytes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in res.get("models") or []:
        if m.get("error"):
            lines.append(f"| {m['name']} | error: {m['error'][:80]} | | | | | | |")
            continue
        r, t, mem = m["retrieval"], m["throughput"], m["memory"]

        def g(key: str, metric: str, r: dict[str, Any] = r) -> str:
            return " / ".join(str(r.get(f"{key}/{lg}", {}).get(metric, "-")) for lg in LANGS)

        lines.append(f"| {m['name']} | {t['docs_per_s']} | {t['tokens_per_s']} | {mem.get('weights_mib', '-')} | "
                     f"{mem.get('peak_allocated_mib', '-')} | {g('needle', 'mrr@10')} | {g('finding', 'ndcg@10')} | "
                     f"{m['storage']['halfvec_bytes']} |")  # fmt: skip
    return "\n".join(lines)


def _encoders(backend: str, names: list[str]) -> list[Any]:
    if backend == "hash":
        return [HashEncoder]

    def make(name: str) -> Any:
        f = lambda: HfEncoder(name)  # noqa: E731
        f.name = name  # type: ignore[attr-defined]
        return f

    return [make(n) for n in names]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--synth", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--backend", choices=["hf", "hash"], default="hf")
    r.add_argument("--models", default=",".join(MODELS))
    a = ap.parse_args(argv)
    if a.cmd == "build":
        s = build_set(a.synth)
        a.out.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(s["counts"], ensure_ascii=False))
        return 0
    labelled = json.loads(a.set.read_text(encoding="utf-8"))
    res = run(labelled, _encoders(a.backend, [n for n in a.models.split(",") if n]))
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(markdown(res))
    return 0 if all(not m.get("error") for m in res["models"]) else 1


if __name__ == "__main__":
    sys.exit(main())
