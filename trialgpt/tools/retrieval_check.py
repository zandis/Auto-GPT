import sys
import time

from trialgpt_local import datasets, metrics, retrieval

c = sys.argv[1]
qtype = sys.argv[2]
t0 = time.time()
idx = retrieval.HybridIndex.build(datasets.corpus(c), name=c)
print(c, "index", len(idx.nctids), f"{time.time() - t0:.0f}s", flush=True)
co = datasets.load(c)
rec = {n: [] for n in (100, 500, 1000)}
for qid, rel in co.qrels.items():
    q = co.id2queries[qid][qtype]
    conds = [q] if isinstance(q, str) else q["conditions"]
    ranked = [t for t, _ in idx.search(conds, n=2000)]
    for n in rec:
        rec[n].append(metrics.recall_at_n(ranked, rel, n))
print(c, qtype, {n: round(metrics.mean(v), 4) for n, v in rec.items()}, f"{time.time() - t0:.0f}s")
