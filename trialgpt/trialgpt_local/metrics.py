"""Evaluation metrics as defined in Jin et al. 2024 (Eqs. 27-29): graded relevance r in {0, 1, 2}.

* NDCG@k with linear gain: DCG = sum r_i / log2(i + 1);
* P@k graded: sum r_i / (2 k) — an excluded/"potential" trial (r=1) in the top k earns half credit;
* AUROC "excluding": the paper does not name the classes; here eligible (2) is positive and excluded (1) negative,
  scored by the trial score (so a good ranker puts excluded trials lower);
* Recall@N graded: sum of r of the retrieved / sum of r of all judged trials.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def ndcg_at_k(ranked: Sequence[str], rel: Mapping[str, int], k: int = 10) -> float | None:
    dcg = sum(rel.get(t, 0) / math.log2(i + 2) for i, t in enumerate(ranked[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else None


def precision_at_k(ranked: Sequence[str], rel: Mapping[str, int], k: int = 10, max_rel: int = 2) -> float:
    return sum(rel.get(t, 0) for t in ranked[:k]) / (max_rel * k)


def auroc(scores: Mapping[str, float], rel: Mapping[str, int], pos: int = 2, neg: int = 1) -> float | None:
    """Mann-Whitney AUROC of ``scores`` for label ``pos`` against label ``neg`` (ties count half)."""
    p = [scores[t] for t, r in rel.items() if r == pos and t in scores]
    n = [scores[t] for t, r in rel.items() if r == neg and t in scores]
    if not p or not n:
        return None
    wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in p for b in n)
    return wins / (len(p) * len(n))


def recall_at_n(retrieved: Sequence[str], rel: Mapping[str, int], n: int) -> float | None:
    total = sum(rel.values())
    if total == 0:
        return None
    top = set(retrieved[:n])
    return sum(r for t, r in rel.items() if t in top) / total


def mean(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None
