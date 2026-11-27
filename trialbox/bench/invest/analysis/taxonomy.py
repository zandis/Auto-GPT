"""The battery's closed error taxonomy (INVEST-1 §2): one code per failure row, and the automatic preventable rule.

Trial side T1-T11, patient side P1-P11. A row is a *failure* when it did not settle the way it should have: wrong
against gold, an unknown on a criterion that should decide, a check that rejected the answer, a model that did not
answer. By-design outcomes are not failures: a criterion a person decides (``human``), a criterion the cascade did not
reach (``not_evaluated`` with no unknown kind), a tier or scope row.

*Preventable* means the ledger shows the needed input was present upstream (a coded row exists but was not used, the
model read a passage, gold says the record holds the answer); *inherent* means it was absent (no record, no notes, no
date); *undetermined* means the ledger does not keep the column that would tell (passages are not stored today, so a
model abstention without gold cannot be judged). The rule is code over ledger columns, never a model.
"""

from __future__ import annotations

import json
from typing import Any

CODES: dict[str, str] = {
    "T1": "region miss",
    "T2": "split (composite line)",
    "T3": "family wrong",
    "T4": "value / op / unit wrong",
    "T5": "window wrong",
    "T6": "concept not normalised",
    "T7": "template fragment",
    "T8": "card wrong or missing",
    "T9": "uncompiled construct",
    "T10": "value set empty at the site",
    "T11": "SQL / CQL / Circe disagree",
    "P1": "site gap (input absent)",
    "P2": "code system not carried / unmapped code",
    "P3": "unit or value unusable",
    "P4": "undated / stale / pending",
    "P5": "retrieval miss",
    "P6": "extraction wrong or abstained",
    "P7": "code-check rejection",
    "P8": "pair disagreement",
    "P9": "verdict wrong with evidence present",
    "P10": "non-determinism",
    "P11": "latency, budget or outage",
}

#: the instrument of INVEST-1 §1.3 a fix of the code moves
INSTRUMENT: dict[str, str] = {
    **{f"T{i}": "trial-side gold" for i in range(1, 11)},
    "T11": "cross-oracle",
    "P1": "F17 data-gap rows",
    "P2": "F17 coded decides",
    "P3": "F17 coded decides",
    "P4": "F17 coded decides",
    "P5": "note settled share (held / JA-1 / set D)",
    "P6": "held / JA-1 correct",
    "P7": "held / JA-1 missed and decided-on-unknown",
    "P8": "set D conflicts handled",
    "P9": "set D wrong decided",
    "P10": "repeat identity",
    "P11": "cost and latency",
}

# product reason code -> (taxonomy code, preventable when no gold says otherwise)
_REASON: dict[str, tuple[str, str]] = {
    "data_gap": ("P1", "inherent"),
    "no_record_of_kind": ("P1", "inherent"),
    "no_notes": ("P1", "inherent"),
    "derived_missing_input": ("P1", "inherent"),
    "derived_adult_only": ("P1", "inherent"),
    "not_in_snapshot": ("P1", "inherent"),
    "unknown_kept": ("P1", "inherent"),
    "code_outside_list": ("P2", "preventable"),  # the record is there, the list does not hold its code
    "unknown_code_system": ("P2", "preventable"),
    "code_system_not_carried": ("P2", "preventable"),
    "unit_mismatch": ("P3", "preventable"),  # the value is there, its unit was not used
    "derived_unit": ("P3", "preventable"),
    "unknown_value": ("P3", "preventable"),
    "derived_not_stored": ("P4", "preventable"),  # the inputs are there, the stored score is not
    "order_dates_missing": ("P4", "inherent"),
    "check_dates": ("P4", "inherent"),
    "condition_not_active": ("P4", "inherent"),
    "suspected_diagnosis": ("P4", "inherent"),
    "proposed_fact": ("P4", "inherent"),
    "derived_vs_documented": ("P4", "inherent"),
    "not_mentioned": ("P5", "inherent"),
    "notes_over_budget": ("P5", "preventable"),
    "abstained": ("P6", "undetermined"),
    "low_confidence": ("P6", "undetermined"),
    "quote_not_found": ("P7", "preventable"),  # the model read a passage and quoted something else
    "verifier_quote_missing": ("P7", "preventable"),
    "planted_instruction": ("P7", "preventable"),
    "refused": ("P7", "inherent"),
    "disagree": ("P8", "preventable"),
    "single_model": ("P8", "preventable"),
    "not_final": ("P8", "preventable"),
    "rules_changed": ("P9", "preventable"),
    "model_down": ("P11", "preventable"),
}
_NOTE_STAGES = ("S2", "S2b")
_BY_DESIGN = frozenset({"human"})


def gold_verdict(gold: Any, kind: str | None) -> str | None:
    """The verdict gold implies, or None. Note sets carry T/F/U directly; the synthetic hospital's note truth says
    whether the record states the criterion's fact (yes/no/unknown), and passing is ``yes`` for an inclusion and
    ``no`` for an exclusion (the product's own oracle, ``tools/cascade_e2e._oracles``)."""
    if gold is None:
        return None
    g = json.loads(gold) if isinstance(gold, str) and gold[:1] in '"[{' else gold
    if g in ("T", "F", "U"):
        return str(g)
    if g == "unknown":
        return "U"
    if g in ("yes", "no") and kind in ("inclusion", "exclusion"):
        return "T" if (g == "yes") == (kind == "inclusion") else "F"
    return None


def classify_match(
    stage: str, verdict: str, reason_code: str | None, unknown_kind: str | None, gold: str | None = None
) -> tuple[str, str] | None:
    """(code, preventable | inherent | undetermined) for one ``match_stage`` row, or None when it is not a failure.
    ``gold`` is the gold *verdict* (see ``gold_verdict``), when the set has one."""
    if stage in ("S0", "tier") or verdict == "not_applicable":
        return None
    reason = reason_code or ""
    if verdict in ("T", "F"):
        if gold is None or gold == verdict:
            return None
        if gold == "U":  # decided where the record does not say: an invented fact
            return ("P6", "preventable")
        return ("P9", "preventable")  # decided the wrong way with the answer in the record
    # an unknown
    if reason in _BY_DESIGN or unknown_kind == "pending_human":
        return None
    if gold == "U":
        return None  # the record does not say: an unknown is the right answer
    if reason.startswith("veto"):  # the frozen bench's code checks
        return ("P7", "preventable")
    if reason == "not_evaluated":
        if unknown_kind is None:
            return None
        code = "P5" if stage in _NOTE_STAGES else "P11"
        return (code, "preventable")
    code, prev = _REASON.get(reason, ("P6" if stage in ("S3", "S4") else "P1", "undetermined"))
    if gold in ("T", "F"):  # gold says the record holds the answer: whatever stopped it, the input was there
        prev = "preventable"
    return (code, prev)


def classify_trial(stage: str, status: str | None, reason_code: str | None) -> tuple[str, str] | None:
    """(code, preventable) for one ``trial_stage`` row, or None when the line went through."""
    if status in (None, "ok"):
        return None
    if reason_code and reason_code.split(".")[0] in CODES and reason_code.startswith("T"):
        return (reason_code.split(".")[0], "preventable")
    if status == "no_card":
        return ("T8", "preventable")
    if status in ("uncompiled_construct", "CompileError"):
        return ("T11", "preventable") if stage == "equivalence" else ("T9", "preventable")
    return ({"region": "T1", "split": "T2", "template": "T7"}.get(stage, "T8"), "undetermined")


def family_of(atoms_json: str | None, criterion_class: str | None = None) -> str:
    """The criterion's family for grouping: a derived score's name, else the first atom's domain, else its class."""
    try:
        atoms = json.loads(atoms_json) if atoms_json else []
    except ValueError:
        atoms = []
    for a in atoms if isinstance(atoms, list) else []:
        if isinstance(a, dict):
            if a.get("derived"):
                return f"derived:{a['derived']}"
            if a.get("domain"):
                return str(a["domain"])
    return criterion_class or "none"


#: which site view a family's rows come from (the data-gap map's rows)
VIEW_OF: dict[str, str] = {
    "condition": "diagnosis",
    "medication": "medication",
    "observation": "lab+vital",
    "measurement": "lab+vital",
    "procedure": "procedure",
    "demographic": "patient",
    "encounter": "encounter",
    "note": "note",
}


def view_of(family: str) -> str:
    if family.startswith("derived:"):
        return "lab+vital:score-inputs"
    return VIEW_OF.get(family, family)
