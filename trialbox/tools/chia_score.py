"""Chia as bench gold (HOLISTIC-3 lane N, owner decision D7 (i)): what the deterministic layer decides, scored.

Chia (Kury et al., Sci Data 2020; figshare 10.6084/m9.figshare.11855817, **CC BY 4.0**, fetched at run time, never
committed) annotates 1,000 trials' criteria with entities, relations and OR groups. ``chia_with_scope.zip`` adds the
Scope spans a relation can point at. Per line this tool reads:

* the concepts (Condition, Drug, Procedure, Observation, Device, Measurement) and whether each is negated: the
  ``Arg1`` of a ``Has_negation`` relation, or inside the span of a negated Scope;
* whether the line is composite: an OR group (``*  OR``) or an ``AND`` relation, i.e. two approvable parts.

It scores ``negation_scope.governed`` per concept against the gold (``not_found`` = the line never names the concept
in a form the rule reads) and counts entities per type and composite lines, the size of the splitter's job. The
model-written atoms (``ir_extract``) and the window parser are not scored here: one needs a model run, the other is
not in this tree yet. Nothing Chia-derived ships (D7); the results are counts, no corpus text.

    python -m tools.chia_score            # -> eval/chia/results/scores.json
"""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from criteria_compiler.ir_extract.negation_scope import governed

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "chia" / "scope"
RESULTS = ROOT / "eval" / "chia" / "results"
URL = "https://ndownloader.figshare.com/files/21728850"  # chia_with_scope.zip, figshare 11855817 v2, CC BY 4.0
CONCEPTS = {"Condition", "Drug", "Procedure", "Observation", "Device", "Measurement"}


def fetch() -> Path:
    if not CACHE.exists():
        r = httpx.get(URL, timeout=300, follow_redirects=True)
        r.raise_for_status()
        part = CACHE.with_name(CACHE.name + ".part")  # renamed to CACHE once every member is written
        shutil.rmtree(part, ignore_errors=True)
        part.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in z.namelist():
                if n.endswith((".ann", ".txt")) and "__MACOSX" not in n:
                    (part / Path(n).name).write_bytes(z.read(n))
        part.rename(CACHE)
    return CACHE


def parse(txt: str, ann: str) -> list[dict[str, Any]]:
    """One row per non-empty line: its text, entity types, concepts with the gold negation, and ``composite``."""
    ents: dict[str, dict[str, Any]] = {}
    negs: set[str] = set()
    grouped: set[str] = set()
    for row in ann.splitlines():
        parts = row.split("\t")
        if len(parts) < 2:
            continue
        head = parts[1].split()
        if row.startswith("T"):
            nums = [int(x) for x in " ".join(head[1:]).replace(";", " ").split()]
            ents[parts[0]] = {
                "type": head[0],
                "start": nums[0],
                "end": nums[-1],
                "text": parts[2] if len(parts) > 2 else "",
            }
        elif row.startswith("R") and head[0] == "Has_negation":
            negs.add(head[1].removeprefix("Arg1:"))
        elif (row.startswith("R") and head[0] == "AND") or (row.startswith("*") and head[0] == "OR"):
            grouped.update(a.split(":")[-1] for a in head[1:])
    neg_spans = [(ents[i]["start"], ents[i]["end"]) for i in negs if i in ents]
    out, pos = [], 0
    for line in txt.split("\n"):
        start, end = pos, pos + len(line)
        pos = end + 1
        if not line.strip():
            continue
        mine = {k: e for k, e in ents.items() if start <= e["start"] < end + 1}
        concepts = [
            {
                "type": e["type"],
                "text": e["text"],
                "negated": k in negs or any(s <= e["start"] and e["end"] <= t for s, t in neg_spans),
            }
            for k, e in sorted(mine.items(), key=lambda kv: kv[1]["start"])
            if e["type"] in CONCEPTS
        ]
        out.append(
            {
                "text": line.strip(),
                "types": [e["type"] for e in mine.values()],
                "concepts": concepts,
                "composite": bool(grouped & mine.keys()),
            }
        )
    return out


def _f1(tp: int, fp: int, fn: int) -> float:
    return round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0


def score(lines: list[dict[str, Any]]) -> dict[str, Any]:
    c = Counter({"tp": 0, "fp": 0, "fn": 0, "tn": 0, "not_found": 0})
    for ln in lines:
        names = [e["text"] for e in ln["concepts"]]
        for e in ln["concepts"]:
            got = governed(ln["text"], [e["text"]], [n for n in names if n != e["text"]])
            if got is None:
                c["not_found"] += 1
            else:
                c[("t" if got == e["negated"] else "f") + ("p" if got else "n")] += 1
    neg: dict[str, Any] = dict(c)
    neg["precision"] = round(c["tp"] / (c["tp"] + c["fp"]), 4) if c["tp"] + c["fp"] else 0.0
    neg["recall"] = round(c["tp"] / (c["tp"] + c["fn"]), 4) if c["tp"] + c["fn"] else 0.0
    neg["f1"] = _f1(c["tp"], c["fp"], c["fn"])
    return {
        "lines": len(lines),
        "composite_lines": sum(ln["composite"] for ln in lines),
        "entities": dict(Counter(t for ln in lines for t in ln["types"]).most_common()),
        "negation_scope": neg,
    }


def main() -> None:
    folder = fetch()
    lines = [
        row
        for txt in sorted(folder.glob("*.txt"))
        for row in parse(txt.read_text("utf-8"), txt.with_suffix(".ann").read_text("utf-8"))
    ]
    res = score(lines)
    RESULTS.mkdir(parents=True, exist_ok=True)
    part = RESULTS / "scores.json.part"
    part.write_text(json.dumps(res, indent=1) + "\n")
    os.replace(part, RESULTS / "scores.json")
    print(json.dumps({k: v for k, v in res.items() if k != "entities"}))


if __name__ == "__main__":
    main()
