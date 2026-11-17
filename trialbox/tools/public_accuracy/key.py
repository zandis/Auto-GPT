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
  v1. The physicians' labels (SIGIR, TREC) are the same in both.
* ``v2`` also marks a pair ``conflicted`` (D-1064), never relabelled: its pair label says ``eligible`` while the same
  physicians' criterion labels for that patient in that trial exclude the patient (an inclusion ``not included``, or
  an exclusion ``excluded``; :data:`EXCLUDING`, the one definition the scorer's S1 uses too). The rule is read from
  the gold alone, so the mark is a property of the key, the same for every run. The marks are written to
  ``gold/conflicted.json`` (:func:`write_conflicted`); a folder of key v2 without the file (built before it) has them
  computed by the same rule. The target "no eligible patient excluded" is read without them, beside the figure with
  them (D-1064 item 2). Only ``eligible`` pairs are marked: ``would consider`` (SIGIR's 1) does not claim every
  criterion met, so a criterion label that excludes does not contradict it, and neither ``would consider`` nor
  ``would not refer`` enters the eligible target. On launch P1b's sigir gold the rule marks 6 of the 46 eligible pairs
  (and would touch 10 ``would consider`` pairs, which it leaves unmarked for that reason).

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
        "over the same patients as v1; D-1064: an eligible pair whose own criterion labels exclude the patient is "
        "marked conflicted, not relabelled"
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
    "conflicted": "D-1064: the pair label conflicts with the same physicians' criterion labels; set aside, not "
    "relabelled",
    "only_old": "row only in the old key",
    "only_new": "row only in the new key",
}


#: a criterion label that excludes the patient (the physicians' criterion-level reading): S1's and D-1064's rule
EXCLUDING = frozenset({("inclusion", "not included"), ("exclusion", "excluded")})
#: the pair labels a conflict is read on (see the module's docstring)
CONFLICT_LABELS = ("eligible",)
CONFLICTED_FILE = "conflicted.json"
#: the versions that mark conflicted pairs (D-1064); a version's entry never changes
MARKS_CONFLICTED = {"v1": False, "v2": True}


def criterion_says_excluded(crits: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(mrn, ruleset) of every patient x trial whose own criterion labels exclude the patient (:data:`EXCLUDING`)."""
    return {
        (str(c["mrn"]), str(c["ruleset"]))
        for c in crits
        if c.get("mrn") and c.get("ruleset") and (c.get("kind"), c.get("label")) in EXCLUDING
    }


def conflicted(pairs: list[dict[str, Any]], crits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """D-1064: every pair whose label is in :data:`CONFLICT_LABELS` while its own criterion labels exclude the patient,
    with the criterion rows that exclude, sorted by (patient, trial). Read from the gold alone."""
    rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for c in crits:
        if (c.get("kind"), c.get("label")) in EXCLUDING and c.get("mrn") and c.get("ruleset"):
            rows.setdefault((str(c["mrn"]), str(c["ruleset"])), []).append(
                {"kind": c["kind"], "label": c["label"], "text": c.get("text") or ""}
            )
    by = criterion_says_excluded(crits)
    out = []
    for p in pairs:
        k = (str(p.get("mrn")), str(p.get("ruleset")))
        if p.get("mrn") and p.get("ruleset") and p.get("label") in CONFLICT_LABELS and k in by:
            out.append({"patient": p.get("patient"), "trial": p.get("trial"), "mrn": p["mrn"], "ruleset": p["ruleset"],
                        "label": p["label"], "why": "D-1064", "excluding": rows[k]})  # fmt: skip
    return sorted(out, key=lambda r: (str(r["patient"]), str(r["trial"])))


def write_conflicted(gold: Path, pairs: list[dict[str, Any]], crits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Write ``gold/conflicted.json`` (a file of its own, so no file v1 wrote changes) and return the marks."""
    marks = conflicted(pairs, crits)
    (gold / CONFLICTED_FILE).write_text(json.dumps(marks, ensure_ascii=False, indent=1), encoding="utf-8")
    return marks


def conflicted_of(built: Path) -> dict[str, Any]:
    """The conflicted marks of a built folder: ``{"marks": [...], "from": ...}``; ``marks`` is None for a key that
    marks none (v1). ``gold/conflicted.json`` when present (a v2 build, or the replay's offline v2 of a stored v1);
    else, for a folder that states v2, computed by the same rule from its gold."""
    g = _gold(built)
    f = g / CONFLICTED_FILE
    if f.exists():
        return {"marks": json.loads(f.read_text(encoding="utf-8")), "from": f"gold/{CONFLICTED_FILE}"}
    if not MARKS_CONFLICTED[version_of(built)]:
        return {"marks": None, "from": "key v1 marks no conflicted pair"}
    return {"marks": conflicted(_jsonl(g / "pairs.jsonl"), _jsonl(g / "criteria.jsonl")),
            "from": f"computed by the rule (key v2 folder without gold/{CONFLICTED_FILE})"}  # fmt: skip


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
    co = {(str(r["patient"]), str(r["trial"])): r for r in (conflicted_of(old)["marks"] or [])}
    cn = {(str(r["patient"]), str(r["trial"])): r for r in (conflicted_of(new)["marks"] or [])}
    for k in sorted(set(co) ^ set(cn)):
        r = cn.get(k) or co[k]
        mark = f"{r['label']}, conflicted"
        excl = "; ".join(f"{e['kind']} {e['label']}: {e['text']}" for e in r["excluding"])
        row("conflicted", str(r["patient"]), str(r["ruleset"]), f"pair (excluding: {excl})",
            r["label"] if k in cn else mark, mark if k in cn else r["label"])  # fmt: skip
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
