"""The answer key's versions (D-1104): the corrected key is a new version, and the old one stays.

The answer key of a public set is what the builder (:mod:`.sets`, :mod:`.site`) writes for it: the gold labels in
``built/gold`` and the placed facts in ``built/site`` that those labels are scored against (a patient's birth date, the
age and sex lines written into a protocol). It is built at run time from the pinned sources, never committed;
``eval/public_accuracy_key/MANIFEST.json`` pins what is known of each version.

* ``v1``: the key as launch P1b used it (run ``box-20261116T074927Z-3b2f5e38``), the builder of master ``fa639b61``.
  Still built byte for byte with ``--key v1``: the files P1b's ``built/gold`` holds come out the same.
* ``v2``: the corrections of the P1b review, B1 to B3 (the integrator's list on #649, 2026-11-16): B1 the birth date
  is the visit minus the age the note states, in its unit; B2 a placed age line keeps its unit and is left out when
  the protocol states that bound; B3 the JMED truth is read from the note the box reads, over the same patients as
  v1. The physicians' labels (SIGIR, TREC) are the same in both: a pair label that conflicts with the physicians' own
  criterion labels is the scorer's to report (S1), never relabelled here.

A built folder names its version in ``gold/key.json``; a folder without one was built before keys had versions and is
``v1`` (P1b's stored folders). :func:`diff` lists what differs between two built folders, row by row, and why.

    python -m tools.public_accuracy build --set jmed --out DIR --key v1
    python -m tools.public_accuracy key-diff OLD_DIR NEW_DIR
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

#: every version of the key and what it is; a new version is a new entry, an entry is never changed
KEYS: dict[str, str] = {
    "v1": (
        "as launch P1b used it (builder of master fa639b61): birth date 1 July of the visit's year minus the age; "
        "placed age lines in years, written even when the protocol states the bound; JMED truth from the structured "
        "主病名/既往歴/現病歴"
    ),
    "v2": (
        "B1-B3 of the P1b review: B1 birth date the visit minus the stated age in its unit; B2 placed age lines keep "
        "their unit and a bound the protocol states is not written again; B3 JMED truth from the note the box reads, "
        "over the same patients as v1"
    ),
}
CURRENT = "v2"
FILE = "key.json"
#: why a row differs, by the fix that changes it
WHY = {
    "birth_date": "B1: birth date is the visit minus the stated age, in its unit",
    "protocol_line": "B2: placed age line keeps its unit; a bound the protocol states is not written again",
    "jmed_label": "B3: JMED truth from the note the box reads",
    "label": "a label no fix of B1-B3 changes (not expected)",
    "only_old": "row only in the old key",
    "only_new": "row only in the new key",
}


def check(key: str) -> str:
    if key not in KEYS:
        raise ValueError(f"answer key {key!r}: one of {', '.join(sorted(KEYS))}")
    return key


def stamp(gold: Path, key: str) -> None:
    """Write ``gold/key.json``: the version this folder was built as (a new file; no older file changes)."""
    (gold / FILE).write_text(
        json.dumps({"key": check(key), "what": KEYS[key]}, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _gold(built: Path) -> Path:
    return built if (built / "ids.json").exists() else built / "gold"


def version_of(built: Path) -> str:
    """The key version of a built folder (``built`` or its ``gold``): ``gold/key.json``, else ``v1`` (built before
    keys had versions)."""
    f = _gold(built) / FILE
    if not f.exists():
        return "v1"
    return check(str(json.loads(f.read_text(encoding="utf-8"))["key"]))


def describe(built: Path) -> dict[str, Any]:
    """What a score or report names: the version, what it is, and whether the folder says so itself."""
    v = version_of(built)
    return {"key": v, "what": KEYS[v], "stamped": (_gold(built) / FILE).exists()}


# ---------------------------------------------------------------- the listing of what differs
def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x] if p.exists() else []


def _births(built: Path) -> dict[str, str] | None:
    p = built / "site" / "hospital" / "patient.csv"
    if not p.exists():
        return None
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return {r["mrn"]: r["birth_date"] for r in csv.DictReader(fh)}


def _protocol_lines(built: Path) -> dict[str, list[str]] | None:
    d = built / "site" / "protocols"
    if d.is_dir():
        # the line without its number: a line left out renumbers the ones after it, which is no change of theirs
        return {
            f.stem: [re.sub(r"^\d+\.\s+", "", ln) for ln in f.read_text(encoding="utf-8").splitlines()]
            for f in sorted(d.glob("*.txt"))
        }
    w = _gold(built) / "written.json"
    if w.exists():
        return {k: list(v) for k, v in json.loads(w.read_text(encoding="utf-8")).items()}
    return None


def diff(old: Path, new: Path) -> dict[str, Any]:
    """Every (set, patient, protocol, criterion or line) whose key differs between two built folders, and why.

    Labels: ``gold/criteria.jsonl`` by (patient, trial, kind, text), ``gold/pairs.jsonl`` by (patient, trial). Placed
    facts, where both folders hold them: each patient's birth date (``site/hospital/patient.csv``) and each
    protocol's lines (``site/protocols``, else ``gold/written.json``). A part one folder lacks (P1b's stored folders
    keep ``built/gold`` only) is named in ``not_compared``, never taken as equal."""
    go, gn = _gold(old), _gold(new)
    ids_o = json.loads((go / "ids.json").read_text(encoding="utf-8"))
    ids_n = json.loads((gn / "ids.json").read_text(encoding="utf-8"))
    name = str(ids_n.get("set") or ids_o.get("set") or "")
    rows: list[dict[str, Any]] = []

    def row(why: str, patient: str, ruleset: str, what: str, a: Any, b: Any) -> None:
        rows.append({"set": name, "why": why, "patient": patient, "ruleset": ruleset, "what": what, "old": a, "new": b})

    for fname, keyf, what in (
        ("criteria.jsonl", lambda r: (r["patient"], r["trial"], r["kind"], r["text"]), "criterion"),
        ("pairs.jsonl", lambda r: (r["patient"], r["trial"]), "pair"),
    ):
        o = {keyf(r): r for r in _jsonl(go / fname)}
        n = {keyf(r): r for r in _jsonl(gn / fname)}
        for k in sorted(set(o) | set(n)):
            a, b = o.get(k), n.get(k)
            r = b if b is not None else a or {}
            label = f"{what}: {r['text']}" if what == "criterion" else what
            rs = str(r.get("ruleset") or r["trial"])
            if a is None or b is None:
                was, now = a and a["label"], b and b["label"]
                row("only_new" if a is None else "only_old", r["patient"], rs, label, was, now)
            elif a["label"] != b["label"]:
                why = "jmed_label" if name == "jmed" and what == "criterion" else "label"
                row(why, r["patient"], rs, label, a["label"], b["label"])
    not_compared = []
    bo, bn = _births(old), _births(new)
    if bo is None or bn is None:
        not_compared.append("birth dates (B1): a folder has no site/hospital/patient.csv")
    else:
        back = {m: p for p, m in (ids_n.get("patients") or {}).items()}
        for mrn in sorted(set(bo) & set(bn)):
            if bo[mrn] != bn[mrn]:
                row("birth_date", back.get(mrn, mrn), "", "birth_date", bo[mrn], bn[mrn])
    po, pn = _protocol_lines(old), _protocol_lines(new)
    if po is None or pn is None:
        not_compared.append("protocol lines (B2): a folder has no site/protocols and no gold/written.json")
    else:
        for rs in sorted(set(po) & set(pn)):
            gone = [ln for ln in po[rs] if ln not in pn[rs]]
            came = [ln for ln in pn[rs] if ln not in po[rs]]
            for ln in gone:
                row("protocol_line", "", rs, "line", ln, None)
            for ln in came:
                row("protocol_line", "", rs, "line", None, ln)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["why"]] = counts.get(r["why"], 0) + 1
    for r in rows:
        r["why"] = WHY[r["why"]]
    return {
        "set": name,
        "old": describe(old),
        "new": describe(new),
        "counts": counts,
        "rows": rows,
        "not_compared": not_compared,
    }
