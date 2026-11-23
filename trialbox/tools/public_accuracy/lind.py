"""The like-for-like metric: Lind's definition, on our whole system (card R1-L0, plan 11 section 10.0; #639).

Lind's peer-reviewed figure (94.2 %) is whole-system, per-criterion agreement with expert coordinators: for each
(patient, criterion), the system's answer against the adjudicated label, coded and note criteria together. This module
measures ours the same way, on the answers of the product path (the box's SCREEN, ``answers.json``) against a gold
that was written before the run (the blind labels: the generator's planted truth, a person's blind check).

**The label mapping** (:data:`MAPPING`), written first and PROVISIONAL: the journal paper has not been read by this
project (it was refused), so its exact label set is not known; this table is amended after that reading, before any
reported run. Three labels: ``met``, ``not met``, ``not determinable``.

* The box's answer for a (patient, criterion) maps to ``met`` or ``not met`` only when a coded rule decided it
  (basis ``coded``) or the model pair agreed with a quote (basis ``pair``) and nothing marks it as less than final.
  Everything else is ``not determinable``: unknown or missing data, a single model, a disagreeing pair, a negated,
  family-history or suspected quote (D-1069), a quoteless note answer, a "not final" answer, anything sent to
  review, and a criterion the box did not compile or a patient it did not answer.
* The box's verdict is the patient's standing (pass or fail); the label is the criterion's: an inclusion that passes
  is ``met``, an exclusion that fails is ``met`` (its condition is present); an inclusion that fails and an exclusion
  that passes are ``not met``.
* The gold's ``not enough information`` and ``not applicable`` are ``not determinable``.

**Agreement** is the share of (patient, criterion) pairs whose mapped label equals the gold label, over ALL pairs. A
``not determinable`` answer against a ``met`` or ``not met`` gold is a disagreement; so is ``met`` against
``not determinable``. Reported overall, for coded criteria alone and note criteria alone (the compiled criterion's
class: ``note`` for a note criterion, ``structured`` for a coded one; a criterion the box did not compile has no class
and is counted in the overall figure and in ``unclassified`` only), and per language, each with its number of
pairs. Reported with it, never instead of it: the decided share and the false-block rate.

No figure from here is set beside a published figure unless the set is the blind-labelled whole-system set of
section 10.0; the report's top-level ``gold_kind`` says what a run's gold is, and it is never inferred."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from tools.public_accuracy import score as sc

MET, NOT_MET, UNDETERMINED = "met", "not met", "not determinable"
LABELS = (MET, NOT_MET, UNDETERMINED)
PROVISIONAL = True  # until the paper's label set is read (plan 11 section 10.0)
#: the box answers that may be mapped to met / not met; every other basis is not determinable
DECIDING_BASES = ("coded", "pair")
#: the reasons a decided answer may carry; any other reason (suspected, negated, not final, single model, ...) says
#: the answer is less than final, so it is not determinable
FINAL_REASONS = ("", "coded", "note")

MAPPING = {
    "box answer": "mapped label",
    "coded rule decides, inclusion holds or exclusion condition present": MET,
    "coded rule decides, inclusion fails or exclusion condition absent": NOT_MET,
    "model pair agrees, with a quote, same reading": "met / not met as the coded rows",
    "unknown, data missing, single model, pair disagrees, negated / family / suspected quote, quoteless, not final, "
    "sent to review, not compiled, patient not answered": UNDETERMINED,
    "gold: not enough information, not applicable": UNDETERMINED,
}

#: the gold's labels (the physician or planted truth) as Lind labels, by criterion kind
GOLD = {
    ("inclusion", "included"): MET,
    ("inclusion", "not included"): NOT_MET,
    ("exclusion", "excluded"): MET,
    ("exclusion", "not excluded"): NOT_MET,
}


def gold_label(kind: str, label: str) -> str:
    """The gold row's label as a Lind label; anything not in :data:`GOLD` (not enough information, not applicable)
    is ``not determinable``."""
    return GOLD.get((kind, label), UNDETERMINED)


def box_label(kind: str, verdict: dict[str, Any] | None) -> str:
    """The box's answer on one criterion as a Lind label (see the module's text). ``None``: no verdict."""
    if not verdict:
        return UNDETERMINED
    v = str(verdict.get("verdict") or "")
    if v not in ("pass", "fail"):
        return UNDETERMINED
    basis = str(verdict.get("basis") or "")
    if basis not in DECIDING_BASES:
        return UNDETERMINED
    if str(verdict.get("reason") or "") not in FINAL_REASONS or verdict.get("final") is False:
        return UNDETERMINED
    if basis == "pair" and not str(verdict.get("quote") or "").strip():
        return UNDETERMINED  # a note answer with no quote stands on nothing a person can check
    if kind == "inclusion":
        return MET if v == "pass" else NOT_MET
    if kind == "exclusion":
        return MET if v == "fail" else NOT_MET
    return UNDETERMINED  # a renewal or documentation line has no met / not met in this definition


def _cell() -> dict[str, int]:
    return {"n": 0, "agree": 0}


def _fig(c: dict[str, int]) -> dict[str, Any]:
    out = sc.rate(c["agree"], c["n"])
    return {"pairs": c["n"], "agree": c["agree"], "agreement": out["rate"], "ci95": out["ci95"]}


def labels_sha256(crits: list[dict[str, Any]]) -> str:
    """The hash of the gold rows this score reads, in a fixed order: recorded on #639 before the run, so a label is
    never written after the box has answered."""
    rows = sorted(
        (str(g.get("ruleset")), str(g.get("mrn")), str(g.get("text")), str(g.get("kind")), str(g.get("label")))
        for g in crits
    )
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def score_lind(
    ids: dict[str, Any], crits: list[dict[str, Any]], answers: dict[str, Any], key: bytes | None = None
) -> dict[str, Any]:
    """Lind's agreement on the gold criterion rows ``crits`` against the box's ``answers``."""
    lang_of = ids.get("lang") or {}
    overall, by_class = _cell(), defaultdict(_cell)
    by_lang: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(_cell))
    decided = _cell()
    wrongable, blocked = 0, 0
    confusion: Counter[str] = Counter()
    not_answered: Counter[str] = Counter()
    unclassified = 0
    for g in crits:
        rs, mrn = g.get("ruleset"), g.get("mrn")
        if not rs or not mrn:
            continue
        kind = str(g.get("kind"))
        gold = gold_label(kind, str(g.get("label")))
        a = answers.get(rs) or {}
        c = sc.match_criterion(str(g.get("text")), a.get("draft") or [], kind)
        p = (a.get("patients") or {}).get(sc.pid_of(str(mrn), key))
        v = None
        if c is None:
            not_answered["not compiled"] += 1
        elif p is None:
            not_answered["patient not answered"] += 1
        else:
            v = next((x for x in p.get("verdicts") or [] if x.get("id") == c["id"]), None)
            if v is None:
                not_answered["no verdict"] += 1
        got = box_label(kind, v)
        cls = None if c is None else ("note" if c.get("class") == "note" else "coded")
        agree = int(got == gold)
        lang = str(lang_of.get(str(rs), "?"))
        for cell in (overall, by_lang[lang]["overall"]):
            cell["n"] += 1
            cell["agree"] += agree
        if cls is None:
            unclassified += 1
        else:
            for cell in (by_class[cls], by_lang[lang][cls]):
                cell["n"] += 1
                cell["agree"] += agree
        decided["n"] += 1
        decided["agree"] += int(got != UNDETERMINED)  # "agree" here counts the decided pairs
        confusion[f"gold {gold} / box {got}"] += 1
        # a false block: the gold keeps the patient (an inclusion met, an exclusion not met), the box says fail
        if (kind, gold) in (("inclusion", MET), ("exclusion", NOT_MET)):
            wrongable += 1
            blocked += int(bool(v) and str(v.get("verdict")) == "fail")
    return {
        "definition": "Lind: whole-system, per-criterion agreement; the box's mapped label against the gold's, over "
        "all (patient, criterion) pairs",
        "provisional": PROVISIONAL,
        "provisional_because": "the journal paper's label set has not been read; the mapping is amended after that",
        "mapping": MAPPING,
        "labels_sha256": labels_sha256(crits),
        "overall": _fig(overall),
        "coded": _fig(by_class["coded"]),
        "note": _fig(by_class["note"]),
        "unclassified_pairs": unclassified,
        "by_language": {
            lang: {k: _fig(cells[k]) for k in ("overall", "coded", "note")} for lang, cells in sorted(by_lang.items())
        },
        "decided_share": sc.rate(decided["agree"], decided["n"]),
        "false_block": sc.rate(blocked, wrongable),
        "not_answered": dict(not_answered),
        "confusion": dict(sorted(confusion.items())),
    }
