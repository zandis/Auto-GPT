"""Card instance -> IR 3.1 criterion, for the cards whose core compiles today (fallback form of the card-protocol job).

A bench step on unsigned proposals: nothing here is approved, nothing is a product ruleset. Anything that is not
expressed exactly is refused with a reason code, never approximated.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tb_contracts.criterion_ir import CriterionIRv3

ROOT = Path(__file__).resolve().parents[2]

# the 29 cards graded S in the rule-card to IR gap table (core compiled today)
SET29 = frozenset(
    [
        "demo.age",
        "demo.sex",
        "human.consent-logistics",
        "human.investigator-judgement",
        "human.other-trial",
        "study.period-rollover",
        "gout.diagnosis",
        "ra.diagnosis",
        "dx.differential",
        "gout.secondary-hyperuricaemia",
        "gout.flare-history",
        "gout.uncontrolled",
        "ra.serology",
        "other.activity-scores",
        "lab.renal",
        "cardiac.events",
        "inf.hbv",
        "inf.hcv-hiv",
        "inf.tb",
        "hx.malignancy",
        "hx.comorbidity",
        "hx.thrombosis",
        "hx.transplant-immunodeficiency",
        "hx.blood-donation",
        "repro.pregnancy",
        "proc.surgery",
        "imm.vaccination",
        "social.substance",
        "enc.healthcare-use",
    ]
)
# the earlier-generation card of the same family and logic; counted apart so the strict figure can be read
ALIASES = {"F01.age": "demo.age", "F01.sex": "demo.sex"}
HUMAN_CARDS = frozenset(
    [
        "human.consent-logistics",
        "human.investigator-judgement",
        "human.other-trial",
        "study.period-rollover",
        "social.substance",
        "hx.blood-donation",
        "hx.comorbidity",
        "repro.pregnancy",
    ]
)
# a card whose code list is not in the repository: reason valueset_missing
NO_VALUESET = frozenset(
    [
        "dx.differential",
        "gout.secondary-hyperuricaemia",
        "gout.flare-history",
        "gout.uncontrolled",
        "ra.serology",
        "other.activity-scores",
        "inf.hcv-hiv",
        "hx.transplant-immunodeficiency",
        "proc.surgery",
        "imm.vaccination",
        "enc.healthcare-use",
    ]
)
REASONS = ("no_card", "card_outside_29", "param_unmapped", "valueset_missing", "calculator_missing", "compile_error")


class Uncompiled(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def valueset(name: str) -> dict[str, Any]:
    for p in sorted((ROOT / "rulesets").glob(f"*/valuesets/{name}.json")):
        return json.loads(p.read_text("utf-8"))  # type: ignore[no-any-return]
    raise Uncompiled("valueset_missing", name)


def _only(params: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(params) - allowed - {"polarity"})
    if extra:
        raise Uncompiled("param_unmapped", ",".join(extra))


def _win(days: Any, default: int | None = None) -> dict[str, Any] | None:
    if days is None:
        days = default
    if days is None:
        return None
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        raise Uncompiled("param_unmapped", f"window {days!r}")
    return {"anchor": "index", "from_days": -days, "to_days": 0}


def _presence(atom_id: str, vs: str, window: dict[str, Any] | None) -> dict[str, Any]:
    valueset(vs)
    a: dict[str, Any] = {"id": atom_id, "domain": "condition", "valueset": vs, "quantifier": "any"}
    if window:
        a["window"] = window
    return a


def _or(ids: list[str]) -> Any:
    return ids[0] if len(ids) == 1 else {"op": "or", "args": ids}


def _num(p: dict[str, Any], *keys: str) -> Any:
    v = next((p[k] for k in keys if p.get(k) is not None), None)
    if v is not None and (not isinstance(v, int | float) or isinstance(v, bool)):
        raise Uncompiled("param_unmapped", f"{keys[0]} {v!r}")
    return v


def _age(p: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    _only(p, {"min_years", "max_years", "max_inclusive", "anchor", "min_age_years", "max_age_years",
              "lower_exclusive", "upper_exclusive"})  # fmt: skip
    lo, hi = _num(p, "min_years", "min_age_years"), _num(p, "max_years", "max_age_years")
    if lo is None and hi is None:
        raise Uncompiled("param_unmapped", "no bound")
    if lo is not None and p.get("lower_exclusive"):
        lo += 1  # whole years (D-946): "> 18" is 19 and over
    if hi is not None and (p.get("upper_exclusive") or p.get("max_inclusive") is False):
        hi -= 1
    age = {k: float(v) for k, v in (("min", lo), ("max", hi)) if v is not None}
    return [{"id": "a1", "domain": "demographic", "valueset": "NONE", "quantifier": "any", "age": age}], "a1"


def _sex(p: dict[str, Any], side: str) -> tuple[list[dict[str, Any]], Any]:
    _only(p, {"sex", "sex_allowed", "female_only_if_non_childbearing"})
    sx = p.get("sex", p.get("sex_allowed"))
    if p.get("female_only_if_non_childbearing"):
        raise Uncompiled("param_unmapped", "female_only_if_non_childbearing")
    if sx in (None, "any"):
        return [], None  # vacuous: nothing to compile
    if sx not in ("male", "female") or side != "inclusion":
        raise Uncompiled("param_unmapped", f"sex {sx!r} on {side}")  # an exclusion's direction is not stated
    return [{"id": "a1", "domain": "demographic", "valueset": "NONE", "quantifier": "any", "sex": sx}], "a1"


def _coded(card: str, p: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    if card == "gout.diagnosis":
        _only(p, {"criteria_set"})
        return [_presence("a1", "VS_GOUT", None)], "a1"
    if card == "ra.diagnosis":
        _only(p, {"criteria_set", "min_duration_days"})
        w = _win(p.get("min_duration_days"))
        if w:  # diagnosed at least N days before: the window ends N days back
            w = {"anchor": "index", "to_days": -p["min_duration_days"]}
        return [_presence("a1", "VS_RHEUMATOID_ARTHRITIS", w)], "a1"
    if card == "hx.malignancy":
        _only(p, {"window_years", "exceptions"})
        exc = p.get("exceptions") or []
        if not isinstance(exc, list) or set(exc) - {"nmsc", "nmsc_resected", "bcc_only", "scc_skin"}:
            raise Uncompiled("param_unmapped", f"exceptions {exc!r}")
        vs = "VS_MALIGNANCY_EXCEPT_NON_MELANOMA_SKIN_CANCER" if exc else "VS_MALIGNANCY"
        y = _num(p, "window_years")
        return [_presence("a1", vs, _win(int(y * 365)) if y else None)], "a1"
    if card == "hx.thrombosis":
        _only(p, {"include", "window_days"})
        if set(p.get("include") or []) - {"dvt", "pe"}:
            raise Uncompiled("valueset_missing", f"include {p.get('include')!r}")
        return [_presence("a1", "VS_VENOUS_THROMBOEMBOLISM", _win(p.get("window_days")))], "a1"
    if card == "cardiac.events":
        _only(p, {"events", "window_days"})
        vs_of = {"mi": "VS_MYOCARDIAL_INFARCTION", "stroke": "VS_STROKE"}
        ev = p.get("events") or []
        if not ev or set(ev) - set(vs_of):
            raise Uncompiled("valueset_missing", f"events {ev!r}")
        w = _win(p.get("window_days"))
        atoms = [_presence(f"a{i}", vs_of[e], w) for i, e in enumerate(ev, 1)]
        return atoms, _or([a["id"] for a in atoms])
    if card == "lab.renal":
        _only(p, {"equation", "op", "value", "window_days", "unit", "dialysis_excludes"})
        if p.get("equation", "ckd_epi_2021") not in ("ckd_epi_2021", "any"):
            raise Uncompiled("calculator_missing", str(p["equation"]))
        if p.get("dialysis_excludes"):
            raise Uncompiled("valueset_missing", "dialysis")
        if p.get("unit") not in (None, "mL/min/1.73m2") or p.get("op") is None or p.get("value") is None:
            raise Uncompiled("param_unmapped", f"unit {p.get('unit')!r} op {p.get('op')!r} value {p.get('value')!r}")
        valueset("VS_EGFR_COMPONENTS")
        a = {"id": "a1", "domain": "observation", "valueset": "VS_EGFR_COMPONENTS", "quantifier": "latest",
             "derived": {"calc": "egfr_ckd_epi_2021@1.0.0"},
             "value": {"op": p["op"], "num": float(_num(p, "value")), "unit": "mL/min/{1.73_m2}"},
             "window": _win(p.get("window_days"), 90)}  # fmt: skip
        return [a], "a1"
    if card == "inf.hbv":
        _only(p, {"hbsag_positive_excludes", "co_listed_viruses", "screening_required"})
        if p.get("hbsag_positive_excludes") is False:
            raise Uncompiled("param_unmapped", "hbsag_positive_excludes false")
        valueset("VS_HBSAG")
        a = {"id": "a1", "domain": "observation", "valueset": "VS_HBSAG", "quantifier": "latest",
             "value": {"op": "in", "codes": ["LA6576-8"]}}  # fmt: skip
        return [a], "a1"
    if card == "inf.tb":
        _only(p, {"test_window_days", "latent_allowed_if", "indeterminate", "indeterminate_result", "active_history"})
        if p.get("active_history"):
            raise Uncompiled("valueset_missing", "active tuberculosis history")
        valueset("VS_IGRA")
        a = {"id": "a1", "domain": "observation", "valueset": "VS_IGRA", "quantifier": "latest",
             "value": {"op": "in", "codes": ["LA6576-8"]}, "window": _win(p.get("test_window_days"), 365)}  # fmt: skip
        return [a], "a1"
    raise Uncompiled("card_outside_29", card)


def _human(card: str, text: str) -> tuple[list[dict[str, Any]], Any, dict[str, Any]]:
    key = "hq_" + hashlib.sha256(f"{card}|{text}".encode()).hexdigest()[:10]
    human = {"checklist": [{"key": key, "item": {"en": text}, "who": "investigator"}]}
    return [{"id": "a1", "domain": "demographic", "valueset": "NONE", "quantifier": "any"}], "a1", human


def card_version(cards_dir: Path, card: str) -> str:
    m = re.search(r"^version: (\S+)", (cards_dir / f"{card}.yaml").read_text("utf-8"), re.M)
    return m.group(1) if m else "0.1.0"


def instantiate(
    rs: str, n: int, side: str, text: str, card: str, params: dict[str, Any], version: str
) -> tuple[CriterionIRv3 | None, str]:
    """(criterion, compiled_as); criterion None when the instance is vacuous. Raises Uncompiled."""
    base = ALIASES.get(card, card)
    if base not in SET29:
        raise Uncompiled("card_outside_29", card)
    if not isinstance(params, dict):
        raise Uncompiled("param_unmapped", "params not an object")
    human: dict[str, Any] | None = None
    if base == "demo.age":
        atoms, logic = _age(params)
    elif base == "demo.sex":
        atoms, logic = _sex(params, side)
    elif base in HUMAN_CARDS:
        atoms, logic, human = _human(base, text)
    elif base in NO_VALUESET:
        raise Uncompiled("valueset_missing", base)
    else:
        atoms, logic = _coded(base, params)
    if logic is None:
        return None, "vacuous"
    crit = {
        "ir_version": "3.1.0",
        "id": f"{rs}-{'INC' if side == 'inclusion' else 'EXC'}-{n:03d}",
        "ruleset": rs,
        "kind": side,
        "class": "human" if human else "structured",
        "text": {"source": text},
        "logic": logic,
        "atoms": atoms,
        "card_ref": {"card_id": f"card.{base}", "card_version": version, "params": params},
    }
    if human:
        crit["human"] = human
    return CriterionIRv3.model_validate(crit), "human" if human else "coded"


def atoms_hash(c: CriterionIRv3) -> str:
    d = c.model_dump(mode="json", by_alias=True, exclude_none=True)
    return hashlib.sha256(json.dumps([d["atoms"], d["logic"], d.get("human")], sort_keys=True).encode()).hexdigest()[
        :12
    ]
