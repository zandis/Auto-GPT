"""Residual fault clustering (INVEST-1 §2): the failure records the deterministic grouping leaves in its long tail are
embedded, clustered (HDBSCAN, then k-means on what it leaves as noise) and named from their members (``name_of``).

A record is criterion-level text (the criterion's wording, stage, expected vs got, reason), never a patient value, so
the same code runs for real ledgers; there it runs on the machine that holds them, and a name leaves only through
``battery.refuse`` (letters only, short, no identifier).

    # in an image with the embedder's libraries (the embed service's), the residual records -> labels
    python -m bench.invest.analysis.cluster --in records.json --out labels.json [--embedder-path DIR]
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

_KEEP = re.compile(r"[^A-Za-z ,/()+\-]")


def record_text(r: Mapping[str, Any]) -> str:
    """What one residual record says, for the embedder and the namer."""
    got = r.get("verdict") or "?"
    want = r.get("gold") or ("decided" if got == "U" else "?")
    return (
        f"{r.get('text') or r.get('criterion_id')} | family {r.get('family')} | stage {r.get('stage')} | "
        f"expected {want}, got {got} | reason {r.get('reason_code') or 'none'}"
    )


def embed(texts: Sequence[str], path: str | None = None) -> tuple[np.ndarray, str]:
    """Vectors for ``texts`` with the pinned local embedder when ``path`` is given, else the deterministic hash
    embedder; returns (vectors, the embedder's name)."""
    from embed_service.embedder import HashEmbedder, LocalEmbedder

    e: Any = LocalEmbedder(path) if path else HashEmbedder()
    return np.asarray(e.embed(list(texts)), dtype=np.float64), str(getattr(e, "model", type(e).__name__))


def kmeans(x: np.ndarray, k: int, iters: int = 50) -> np.ndarray:
    """Deterministic k-means: farthest-point seeding from the first row, Lloyd steps until stable."""
    k = max(1, min(k, len(x)))
    centres = [x[0]]
    for _ in range(1, k):
        d = np.min([((x - c) ** 2).sum(1) for c in centres], axis=0)
        centres.append(x[int(np.argmax(d))])
    c = np.asarray(centres)
    labels = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        new = np.argmin(((x[:, None, :] - c[None, :, :]) ** 2).sum(2), axis=1)
        if (new == labels).all() and _ > 0:
            break
        labels = new
        c = np.asarray([x[labels == j].mean(0) if (labels == j).any() else c[j] for j in range(k)])
    return labels


def cluster(x: np.ndarray, min_size: int = 3) -> tuple[list[int], str]:
    """Cluster labels for the rows of ``x`` and the method used: HDBSCAN where scikit-learn has it, its noise then
    split by k-means; k-means alone when it is absent."""
    if len(x) == 0:
        return [], "none"
    labels = np.full(len(x), -1)
    method = "kmeans"
    try:  # scikit-learn is not a dependency of the repository; the embedder's image carries it
        hdbscan = importlib.import_module("sklearn.cluster").HDBSCAN
    except (ImportError, AttributeError):
        hdbscan = None
    if hdbscan is not None and len(x) >= min_size:
        labels = hdbscan(min_cluster_size=min_size).fit_predict(x)
        method = "hdbscan+kmeans"
    rest = np.flatnonzero(labels < 0)
    if len(rest):
        base = int(labels.max()) + 1
        sub = kmeans(x[rest], math.ceil(math.sqrt(len(rest) / 2)))
        labels[rest] = base + sub
    return [int(v) for v in labels], method


def name_of(members: Sequence[str]) -> str:
    """A short name for a cluster from its members: their most common reason and family, letters only.

    The spec names clusters with a local model. Every model call goes through the gateway with a registered prompt
    (ENG-04, ``tests/unit/test_no_direct_model_calls.py``); no naming prompt is registered yet, so the name is this
    rule until one is."""
    reasons = Counter(m.rsplit("| reason ", 1)[-1].strip() for m in members)
    fams = Counter(m.split("| family ", 1)[-1].split(" |", 1)[0].strip() for m in members if "| family " in m)
    top = [x.most_common(1)[0][0] if x else "mixed" for x in (reasons, fams)]
    words = f"{top[0]} in {top[1]}".replace("_", " ")  # no stage: a name carries no digit (``battery._NAME``)
    return " ".join(_KEEP.sub(" ", words).split())[:80] or "mixed"


def _rows_by_criterion(members: Sequence[Mapping[str, Any]]) -> Counter[str]:
    out: Counter[str] = Counter()
    for r in members:
        out[f"{r['protocol_id']}/{r['criterion_id']}"] += int(r["n"])
    return out


def residual_clusters(records: Sequence[Mapping[str, Any]], labels: Sequence[int]) -> list[dict[str, Any]]:
    """Residual clusters, largest first: name, size in rows, records, preventable share, the codes inside."""
    groups: dict[int, list[Mapping[str, Any]]] = {}
    for r, lab in zip(records, labels, strict=True):
        groups.setdefault(lab, []).append(r)
    out: list[dict[str, Any]] = []
    for members in groups.values():
        members = sorted(members, key=lambda r: (-int(r["n"]), record_text(r)))
        n = sum(int(r["n"]) for r in members)
        prev = sum(int(r["n"]) for r in members if r.get("preventable") == "preventable")
        out.append(
            {
                "name": name_of([record_text(r) for r in members]),
                "n": n,
                "size": len(members),
                "preventable_n": prev,
                "preventable_share": round(prev / n, 3) if n else None,
                "codes": dict(Counter(str(r["code"]) for r in members).most_common()),
                "stages": dict(Counter(str(r["stage"]) for r in members).most_common()),
                "criteria": dict(_rows_by_criterion(members).most_common(10)),
            }
        )
    out.sort(key=lambda c: (-c["n"], c["name"]))
    for i, c in enumerate(out, 1):
        c["cluster_id"] = f"R{i:03d}"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--embedder-path", default=None)
    ap.add_argument("--min-size", type=int, default=3)
    a = ap.parse_args(argv)
    records = json.loads(a.inp.read_text("utf-8"))
    x, embedder = embed([record_text(r) for r in records], a.embedder_path)
    labels, method = cluster(x, a.min_size)
    a.out.write_text(json.dumps({"labels": labels, "method": method, "embedder": embedder}) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "clusters": len(set(labels)), "method": method, "embedder": embedder}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
