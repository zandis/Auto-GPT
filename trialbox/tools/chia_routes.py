"""How much of a protocol can the deterministic filters decide? Chia (1,000 trials, 12,409 criteria) says.

The filter-first design (D-95) rests on one number: on the 1,003 SIGIR criteria Fable routed, the LLM has to read
about 42 % (notes + mixed) and 21 % go to a person. This tool recomputes that share on Chia, the largest public corpus
of annotated eligibility criteria (Kury et al., Sci Data 2020; figshare 10.6084/m9.figshare.11855817, **CC BY 4.0**,
fetched at run time, never committed), with a fixed rule on Chia's own entity labels instead of a model:

* ``human``: the criterion carries a Non-query-able, Post-eligibility, Informed_consent, Competing_trial or
  Parsing_Error entity (consent, willingness, investigator judgement, "other trial").
* ``llm``: otherwise, an Observation, Mood (suspected, possible, planned), Context or Pregnancy_considerations entity,
  or (``--qualifier-llm``, the default) a Qualifier ("severe", "uncontrolled", "known"): facts a code rarely carries.
* ``filter``: everything else, i.e. only Person (age, sex), Condition, Drug, Procedure, Measurement, Device, Visit,
  Value, Temporal, Multiplier, Reference_point, Negation and Scope: codeable with ICD / ATC / LOINC / dates.

It also counts negated exclusions (an exclusion line with a Negation entity), the commonest model error on TREC
(eval/trec_ct/AUDIT.md), to size the fix of rewriting them at protocol import.

    python -m tools.chia_routes            # -> eval/chia/results/routes.json
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "chia"
RESULTS = ROOT / "eval" / "chia" / "results"
URL = "https://ndownloader.figshare.com/files/21728853"  # chia_without_scope.zip, figshare 11855817 v2, CC BY 4.0
HUMAN = {"Non-query-able", "Post-eligibility", "Informed_consent", "Competing_trial", "Parsing_Error"}
LLM = {"Observation", "Mood", "Context", "Pregnancy_considerations"}
SEED = 20261105


def fetch() -> Path:
    dest = CACHE / "x"
    if not dest.exists():
        r = httpx.get(URL, timeout=300, follow_redirects=True)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in z.namelist():
                if n.endswith((".ann", ".txt")) and "__MACOSX" not in n:
                    out = dest / Path(n).name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(z.read(n))
    return dest


def criteria(folder: Path) -> list[dict[str, Any]]:
    """One row per non-empty line of each ``<NCT>_inc|exc.txt`` with the Chia entity types whose span starts on it."""
    rows = []
    for txt in sorted(folder.glob("*.txt")):
        nct, kind = txt.stem.rsplit("_", 1)
        text = txt.read_text(encoding="utf-8")
        starts, pos = [], 0
        for line in text.split("\n"):
            starts.append((pos, line))
            pos += len(line) + 1
        ents: dict[int, set[str]] = defaultdict(set)
        ann = txt.with_suffix(".ann")
        for a in ann.read_text(encoding="utf-8").splitlines() if ann.exists() else []:
            if not a.startswith("T"):
                continue
            head = a.split("\t")[1].split()
            etype, begin = head[0], int(head[1])
            idx = max(i for i, (s, _) in enumerate(starts) if s <= begin)
            ents[idx].add(etype)
        for i, (_, line) in enumerate(starts):
            if line.strip():
                rows.append(
                    {
                        "trial": nct,
                        "kind": "inclusion" if kind == "inc" else "exclusion",
                        "text": line.strip(),
                        "entities": sorted(ents.get(i, set())),
                    }
                )
    return rows


def route(entities: list[str], qualifier_llm: bool = True) -> str:
    e = set(entities)
    if e & HUMAN:
        return "human"
    if e & LLM or (qualifier_llm and "Qualifier" in e):
        return "llm"
    return "filter" if e else "unannotated"


def _ci(k: int, n: int) -> list[float]:
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def trial_ci(rows: list[dict[str, Any]], key: str, value: str, reps: int = 1000) -> list[float]:
    """Bootstrap over trials (criteria of one trial are not independent)."""
    by: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by[r["trial"]].append(r[key] == value)
    ids = sorted(by)
    rng = random.Random(SEED)
    vals = []
    for _ in range(reps):
        k = n = 0
        for t in (rng.choice(ids) for _ in ids):
            k += sum(by[t])
            n += len(by[t])
        vals.append(k / n)
    vals.sort()
    return [round(vals[int(0.025 * reps)], 4), round(vals[int(0.975 * reps) - 1], 4)]


def summarise(rows: list[dict[str, Any]], qualifier_llm: bool) -> dict[str, Any]:
    for r in rows:
        r["route"] = route(r["entities"], qualifier_llm)
    ann = [r for r in rows if r["route"] != "unannotated"]
    out: dict[str, Any] = {"criteria": len(rows), "annotated": len(ann), "trials": len({r["trial"] for r in rows})}
    c = Counter(r["route"] for r in ann)
    out["routes"] = {
        k: {"n": v, "share": round(v / len(ann), 4), "trial95": trial_ci(ann, "route", k)} for k, v in sorted(c.items())
    }
    for kind in ("inclusion", "exclusion"):
        sub = [r for r in ann if r["kind"] == kind]
        ck = Counter(r["route"] for r in sub)
        out[f"routes_{kind}"] = {k: round(v / len(sub), 4) for k, v in sorted(ck.items())}
    exc = [r for r in ann if r["kind"] == "exclusion"]
    neg = [r for r in exc if "Negation" in r["entities"]]
    out["negated_exclusions"] = {
        "n": len(neg),
        "of": len(exc),
        "share": round(len(neg) / len(exc), 4),
        "wilson95": _ci(len(neg), len(exc)),
        "examples": [r["text"][:160] for r in random.Random(SEED).sample(neg, 8)],
    }
    mood = [r for r in ann if "Mood" in r["entities"]]
    out["mood_criteria"] = {"n": len(mood), "share": round(len(mood) / len(ann), 4)}
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="chia_routes")
    ap.parse_args(argv)
    rows = criteria(fetch())
    res = {"qualifier_needs_llm": summarise(rows, True), "qualifier_codeable": summarise(rows, False)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "routes.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    for k, v in res.items():
        print(k, v["annotated"], "criteria", {r: (x["share"], x["trial95"]) for r, x in v["routes"].items()})
    print(
        "negated exclusions",
        res["qualifier_needs_llm"]["negated_exclusions"]["share"],
        res["qualifier_needs_llm"]["negated_exclusions"]["wilson95"],
    )


if __name__ == "__main__":
    main()
