"""Derived observations (SPEC §3.3): one constants file shared by the Python reference, the CQL helper library
``TB_Common`` (rendered from these constants) and the DuckDB SQL templates.

* BMI = weight[kg] / (height[cm] / 100)^2, latest height and weight within the window (default 365 d).
* eGFR, two equations (owner decision 2026-11-09, D-144/D-149): CKD-EPI 2021 race-free (``egfr_ckd_epi``; the
  default in Taiwan) and the Japanese Society of Nephrology 2009 equation (``egfr_jsn``, Matsuo 2009; the default in
  Japan): 194 x Cr^-1.094 x age^-0.287 (x 0.739 female). A protocol may name either; a criterion that says only
  ``egfr`` is given the site's default when it is compiled (:func:`egfr_for_site`), so the approved ruleset always
  names its equation. A stored ``egfr`` (approved before D-149) stays CKD-EPI 2021, as it was approved.
* DAS28 = DAS28-ESR when an ESR exists at the visit, else DAS28-CRP (CRP in mg/L); needs TJC28, SJC28 and patient
  global (0-100 mm).
* BASDAI = (Q1 + Q2 + Q3 + Q4 + (Q5 + Q6) / 2) / 5 (each 0-10).
* ASDAS-CRP = 0.12 back pain + 0.06 morning-stiffness duration + 0.11 patient global (0-10) + 0.07 peripheral pain
  + 0.58 ln(CRP + 1).
* CDAI = TJC28 + SJC28 + PtGA (0-10) + EvGA (0-10); SDAI = CDAI + CRP (mg/dL) (D-189: in the SQL and CQL engines
  too). The 0-10 globals are their LOINC items (75844-1, 75846-6); a 0-100 mm VAS recorded under them is divided by
  10, a 10 cm VAS is already 0-10, and a value outside 0-10 is no value (``derived_unit``: not the item's scale).
* DAS28-ESR and DAS28-CRP each on its own (``das28_esr``, ``das28_crp``; stored derived rows, D-190): the catalogue
  computes both variants and never mixes them; ``das28`` above stays the screening atom's ESR-else-CRP form.

Definitions (D-189). The catalogue's ``catalogue/scores/*.yaml`` is the source: ``tools/gen_score_defs.py`` writes
``score_defs.json``, :mod:`tb_common.scores` reads it, and the same-visit windows of CDAI, SDAI and the two DAS28
variants come from it (:data:`SAME_VISIT`). Stored rows with provenance, recompute and conflicts with a documented
score: :mod:`tb_common.derived_store` (D-190).

Inputs that count (D-190). A row counts only when its status is one of :data:`COUNTS` (a feed result is ``final``).
A proposed fact (a value a model read from a chart, not yet confirmed) never counts as an input, nor does a rejected,
preliminary or entered-in-error row: the score then has no value and says which input is missing, as for any
missing input. The status rule works only where the caller knows the row's status. The lake's ``observation`` table
has no status column yet, so the nightly batch (:func:`tb_common.derived_store.rows_from_lake`) records
:data:`NOT_RECORDED`, which counts: the lake holds only hospital feed rows and confirmed facts (flatten keeps a
proposed fact out of ``observation`` by its basis tag), so no proposed fact reaches a stored score that way. But an
entered-in-error or preliminary feed row is not filtered there until the lake carries ``Observation.status``.

Impossible values. A value outside :data:`DOMAIN` after conversion (a negative CRP or ESR, a joint count outside
0-28, a creatinine of 0 or less, a value that is not a finite number) gives no value and ``derived_unit:<component>``,
like a global outside its 0-10 scale; an age of 0 or less gives ``derived_missing_input:age``. No input makes
:func:`compute` raise. The SQL ``egfr_jsn`` template has the same creatinine and age guard; the SQL and CQL engines
do not yet carry the other ranges.

Units (dataflow review P0-5, D-149). Every component value is converted to the unit the formula expects with the
factors of :data:`UNITS` (UCUM codes; ``mg/dL`` CRP x 10 = ``mg/L``, ``umol/L`` creatinine / 88.4 = ``mg/dL``). A row
whose unit is not one of the allowed ones gives no value and the reason ``derived_unit``; a lab row with no unit at
all is the same (sheets and charts: unknown until the unit is known). A hospital feed's analytes carry the site's
declared unit (the mapping's lab lookup, or ``unit_defaults``), so a feed row always has one. Before D-149 the CRP
term assumed mg/L whatever the row said: a Japanese or Taiwanese CRP of 1.0 mg/dL entered as 1.0, not 10.

Same visit. A multi-component score takes its components from one visit: the newest *anchor* component in the window
(the joint count for DAS28, BASDAI Q1 / Q2 for BASDAI / ASDAS), and each other component the newest one within
:data:`SAME_VISIT` days of it (0 = the same calendar day; 7 for an ESR or CRP drawn around the visit). Before D-149
each component was the newest in the window on its own, so a DAS28 could join counts and a CRP 90 days apart.

A missing input or a unit that does not fit gives **no value and a reason** (``derived_missing_input:<component>``,
``derived_unit:<component>``), never FALSE: the screening engines read no value as unknown (D-130).

Values are compared unrounded (DECISIONS D-17).
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from tb_common import scores

LOINC = "http://loinc.org"
SCORE = "https://trialbox.local/fhir/CodeSystem/clinical-score"

# component -> (system, code)
CODES: dict[str, tuple[str, str]] = {
    "weight": (LOINC, "29463-7"),
    "height": (LOINC, "8302-2"),
    "creatinine": (LOINC, "2160-0"),
    "tjc28": (SCORE, "TJC28"),
    "sjc28": (SCORE, "SJC28"),
    "ptga": (SCORE, "PTGA"),
    "esr": (LOINC, "4537-7"),
    "crp": (LOINC, "1988-5"),
    "basdai_q1": (SCORE, "BASDAI-Q1"),
    "basdai_q2": (SCORE, "BASDAI-Q2"),
    "basdai_q3": (SCORE, "BASDAI-Q3"),
    "basdai_q4": (SCORE, "BASDAI-Q4"),
    "basdai_q5": (SCORE, "BASDAI-Q5"),
    "basdai_q6": (SCORE, "BASDAI-Q6"),
    "ptga10": (LOINC, "75844-1"),  # patient global assessment 0-10 (CDAI, SDAI; catalogue rheum.ptga_0_10)
    "evga": (LOINC, "75846-6"),  # evaluator global assessment 0-10 (catalogue rheum.evga_0_10)
}

COMPONENTS: dict[str, list[str]] = {
    "bmi": ["weight", "height"],
    "egfr": ["creatinine"],
    "egfr_ckd_epi": ["creatinine"],
    "egfr_jsn": ["creatinine"],
    "das28": ["tjc28", "sjc28", "ptga", "esr", "crp"],
    "basdai": ["basdai_q1", "basdai_q2", "basdai_q3", "basdai_q4", "basdai_q5", "basdai_q6"],
    "asdas": ["basdai_q2", "basdai_q6", "ptga", "basdai_q3", "crp"],
    # the anchor component first: a missing input is reported in this order by every engine
    "cdai": ["tjc28", "sjc28", "ptga10", "evga"],
    "sdai": ["tjc28", "sjc28", "ptga10", "evga", "crp"],
    "das28_esr": ["tjc28", "sjc28", "ptga", "esr"],
    "das28_crp": ["tjc28", "sjc28", "ptga", "crp"],
}

DEFAULT_WINDOW_DAYS: dict[str, int] = {
    "bmi": 365,
    "egfr": 365,
    "egfr_ckd_epi": 365,
    "egfr_jsn": 365,
    "das28": 90,
    "basdai": 90,
    "asdas": 90,
    "cdai": 90,
    "sdai": 90,
    "das28_esr": 90,
    "das28_crp": 90,
}

EGFR = {
    "k": 142.0,
    "kappa_f": 0.7,
    "kappa_m": 0.9,
    "alpha_f": -0.241,
    "alpha_m": -0.302,
    "exp_hi": -1.200,
    "age_base": 0.9938,
    "female": 1.012,
}
# JSN 2009 (Matsuo S et al. Am J Kidney Dis 2009;53:982-992); catalogue/scores/egfr_jsn_2009.yaml
EGFR_JSN = {"k": 194.0, "scr_exp": -1.094, "age_exp": -0.287, "female": 0.739}
DAS28 = {"tjc": 0.56, "sjc": 0.28, "gh": 0.014, "esr_ln": 0.70, "crp_ln": 0.36, "crp_const": 0.96}
ASDAS = {"back": 0.12, "stiff": 0.06, "ptga": 0.11, "periph": 0.07, "crp_ln": 0.58}

# the eGFR equation a criterion that says only "egfr" gets at a site of this country (owner decision 2026-11-09)
EGFR_BY_COUNTRY = {"JP": "egfr_jsn", "TW": "egfr_ckd_epi"}
EGFR_NAMES = {
    "egfr": "eGFR CKD-EPI 2021 (approved before the equation was named)",
    "egfr_ckd_epi": "eGFR CKD-EPI 2021",
    "egfr_jsn": "eGFR JSN 2009 (Japanese equation)",
}

# --------------------------------------------------------------------------------------------- units
# component -> (the unit the formula expects, {allowed unit (normalised UCUM) -> factor to that unit})
UNITS: dict[str, tuple[str, dict[str, float]]] = {
    "creatinine": ("mg/dL", {"mg/dl": 1.0, "umol/l": 1 / 88.4}),
    "crp": ("mg/L", {"mg/l": 1.0, "mg/dl": 10.0, "ug/ml": 1.0}),
    "esr": ("mm/h", {"mm/h": 1.0, "mm/hr": 1.0, "mm/(1.h)": 1.0, "mm/1h": 1.0}),
    "weight": ("kg", {"kg": 1.0, "g": 0.001, "[lb_av]": 0.45359237, "lb": 0.45359237}),
    "height": ("cm", {"cm": 1.0, "m": 100.0, "mm": 0.1, "[in_i]": 2.54, "in": 2.54}),
    # 0-10 globals: no unit or a score annotation; a 10 cm VAS is 0-10; a 0-100 mm VAS is divided by 10
    "ptga10": ("{score}", {"": 1.0, "1": 1.0, "{score}": 1.0, "cm": 1.0, "mm": 0.1}),
    "evga": ("{score}", {"": 1.0, "1": 1.0, "{score}": 1.0, "cm": 1.0, "mm": 0.1}),
}
# the item's scale after conversion: a value outside it is no value with ``derived_unit`` (a 40 entered under the
# 0-10 item is a 0-100 mm VAS without its unit, not a 40)
RANGE: dict[str, tuple[float, float]] = {"ptga10": (0.0, 10.0), "evga": (0.0, 10.0)}
# components that are counts or scores: no unit, or a UCUM annotation for "a number"; any other unit is wrong.
# The patient global is a 0-100 mm VAS by definition of the item, so ``mm`` is its only unit.
UNITLESS = {"", "1", "{count}", "{score}", "{#}", "{joints}"}
UNIT_OF_SCORE_ITEM: dict[str, set[str]] = {"ptga": {"mm", ""}}

# score -> (anchor component, {other component: max days from the anchor}); a score not listed has no visit rule
SAME_VISIT: dict[str, tuple[str, dict[str, int]]] = {
    "das28": ("tjc28", {"sjc28": 0, "ptga": 0, "esr": 7, "crp": 7}),
    "basdai": ("basdai_q1", {f"basdai_q{i}": 0 for i in range(2, 7)}),
    "asdas": ("basdai_q2", {"basdai_q6": 0, "ptga": 0, "basdai_q3": 0, "crp": 7}),
}

# the scores whose same-visit windows are read from their catalogue definition (D-189)
for _score in ("cdai", "sdai", "das28_esr", "das28_crp"):
    SAME_VISIT[_score] = scores.visit_rule(_score)
    # the anchor is reported first everywhere, and the definition names exactly the engine's inputs
    if SAME_VISIT[_score][0] != COMPONENTS[_score][0] or set(SAME_VISIT[_score][1]) != set(COMPONENTS[_score][1:]):
        raise ValueError(f"the catalogue definition of {_score} does not match its engine inputs")

# the status of a row whose source does not record one (the lake's ``observation`` table, which holds only feed rows
# and confirmed facts): it counts, and provenance says the status was not recorded rather than inventing "final"
NOT_RECORDED = "not_recorded"
# row statuses that count as an input (D-190); anything else, a proposed fact first of all, never does
COUNTS = frozenset({"final", "amended", "corrected", "confirmed", "signed", NOT_RECORDED})

# the values a component can take after conversion, as (low, high, low allowed): outside is no value with
# ``derived_unit``. Creatinine must be above 0 (the eGFR equations divide by it or raise it to a negative power); a
# joint count is 0-28; CRP and ESR are never negative (an ESR of 0 is "no value" by the catalogue's zero rule).
DOMAIN: dict[str, tuple[float, float, bool]] = {
    "creatinine": (0.0, math.inf, False),
    "tjc28": (0.0, 28.0, True),
    "sjc28": (0.0, 28.0, True),
    "crp": (0.0, math.inf, True),
    "esr": (0.0, math.inf, True),
}

MISSING = "derived_missing_input"
UNIT = "derived_unit"


def norm_unit(unit: str | None) -> str:
    """A unit as the conversion table spells it: NFKC, no spaces, lower case, ``µ``/``μ`` as ``u``."""
    u = unicodedata.normalize("NFKC", unit or "").replace(" ", "").replace("µ", "u").replace("μ", "u")
    return u.lower()


def convert(comp: str, value: float | None, unit: str | None) -> tuple[float | None, str | None]:
    """``(value in the formula's unit, None)`` or ``(None, reason)`` for one component row."""
    if value is None:
        return None, f"{MISSING}:{comp}"
    u = norm_unit(unit)
    if comp in UNITS:
        factor = UNITS[comp][1].get(u)
        if factor is None:
            return None, f"{UNIT}:{comp}"
        lo, hi = RANGE.get(comp, (-math.inf, math.inf))
        v = value * factor
        return (v, None) if lo <= v <= hi else (None, f"{UNIT}:{comp}")
    allowed = UNIT_OF_SCORE_ITEM.get(comp, UNITLESS)
    return (value, None) if u in allowed else (None, f"{UNIT}:{comp}")


def in_domain(comp: str, value: float) -> bool:
    """Whether a converted value is possible for the component (:data:`DOMAIN`); any value must be a finite number."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(v):
        return False
    lo, hi, lo_allowed = DOMAIN.get(comp, (-math.inf, math.inf, True))
    return (lo <= v if lo_allowed else lo < v) and v <= hi


def unit_sql(comp: str, value: str, unit: str) -> str:
    """The SQL twin of :func:`convert`: the value in the formula's unit, or NULL for a unit that is not allowed."""
    u = f"lower(replace(replace(replace(coalesce({unit}, ''), ' ', ''), 'µ', 'u'), 'μ', 'u'))"
    if comp in UNITS:
        arms = " ".join(f"WHEN '{k}' THEN {value} * {v!r}" for k, v in sorted(UNITS[comp][1].items()))
        conv = f"(CASE {u} {arms} ELSE NULL END)"
        if comp not in RANGE:
            return conv
        lo, hi = RANGE[comp]
        return f"(CASE WHEN {conv} BETWEEN {lo!r} AND {hi!r} THEN {conv} ELSE NULL END)"
    allowed = ", ".join(f"'{k}'" for k in sorted(UNIT_OF_SCORE_ITEM.get(comp, UNITLESS)))
    return f"(CASE WHEN {u} IN ({allowed}) THEN {value} ELSE NULL END)"


def egfr_for_site(country: str | None) -> str:
    """The equation a plain ``egfr`` criterion gets at a site: JSN 2009 in Japan, CKD-EPI 2021 elsewhere."""
    return EGFR_BY_COUNTRY.get((country or "").upper(), "egfr_ckd_epi")


def country_of(tz: str | None = None, locale: str | None = None) -> str | None:
    """The site's country from its settings (time zone, else page locale): ``JP``, ``TW`` or None."""
    if tz in ("Asia/Tokyo", "Japan"):
        return "JP"
    if tz in ("Asia/Taipei", "ROC"):
        return "TW"
    loc = (locale or "").lower()
    return "JP" if loc.startswith("ja") else "TW" if loc in ("zh-tw", "zh_tw", "zh-hant") else None


def reason_of(items: Iterable[str]) -> tuple[str | None, list[str]]:
    """Split a criterion's evidence list into the derived-score reason code (if any) and the record references."""
    code: str | None = None
    rest: list[str] = []
    for x in items:
        if x.startswith((MISSING, UNIT)):
            code = code or (UNIT if x.startswith(UNIT) else MISSING)
        else:
            rest.append(x)
    return code, rest


# --------------------------------------------------------------------------------------------- formulas
def bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100.0) ** 2


def egfr(creatinine_mg_dl: float, age_years: int, female: bool) -> float:
    """CKD-EPI 2021, race-free."""
    kappa = EGFR["kappa_f"] if female else EGFR["kappa_m"]
    alpha = EGFR["alpha_f"] if female else EGFR["alpha_m"]
    ratio = creatinine_mg_dl / kappa
    val = EGFR["k"] * min(ratio, 1.0) ** alpha * max(ratio, 1.0) ** EGFR["exp_hi"] * EGFR["age_base"] ** age_years
    return float(val * EGFR["female"] if female else val)


egfr_ckd_epi = egfr


def egfr_jsn(creatinine_mg_dl: float, age_years: int, female: bool) -> float:
    """Japanese Society of Nephrology 2009: 194 x Cr^-1.094 x age^-0.287 (x 0.739 female)."""
    val = EGFR_JSN["k"] * creatinine_mg_dl ** EGFR_JSN["scr_exp"] * age_years ** EGFR_JSN["age_exp"]
    return float(val * EGFR_JSN["female"] if female else val)


def das28_esr(tjc: float, sjc: float, ptga: float, esr: float) -> float:
    return (
        DAS28["tjc"] * math.sqrt(tjc)
        + DAS28["sjc"] * math.sqrt(sjc)
        + DAS28["esr_ln"] * math.log(esr)
        + DAS28["gh"] * ptga
    )


def das28_crp(tjc: float, sjc: float, ptga: float, crp_mg_l: float) -> float:
    return (
        DAS28["tjc"] * math.sqrt(tjc)
        + DAS28["sjc"] * math.sqrt(sjc)
        + DAS28["crp_ln"] * math.log(crp_mg_l + 1)
        + DAS28["gh"] * ptga
        + DAS28["crp_const"]
    )


def basdai(q1: float, q2: float, q3: float, q4: float, q5: float, q6: float) -> float:
    return (q1 + q2 + q3 + q4 + (q5 + q6) / 2.0) / 5.0


def asdas_crp(back_pain: float, stiffness: float, ptga_mm: float, peripheral: float, crp_mg_l: float) -> float:
    return (
        ASDAS["back"] * back_pain
        + ASDAS["stiff"] * stiffness
        + ASDAS["ptga"] * (ptga_mm / 10.0)
        + ASDAS["periph"] * peripheral
        + ASDAS["crp_ln"] * math.log(crp_mg_l + 1)
    )


def cdai(tjc: float, sjc: float, ptga_0_10: float, evga_0_10: float) -> float:
    return tjc + sjc + ptga_0_10 + evga_0_10


def sdai(tjc: float, sjc: float, ptga_0_10: float, evga_0_10: float, crp_mg_dl: float) -> float:
    return tjc + sjc + ptga_0_10 + evga_0_10 + crp_mg_dl


def age_at(birth: date, index: date) -> int:
    """Complete years (the day before the birthday is still the younger age)."""
    return index.year - birth.year - ((index.month, index.day) < (birth.month, birth.day))


# --------------------------------------------------------------------------------------------- the engine
@dataclass(frozen=True)
class Obs:
    """One component row: value, unit as recorded, date, record id."""

    value: float | None
    unit: str | None
    on: date
    oid: str = ""
    status: str = "final"  # a proposed fact is "proposed" and never counts (:data:`COUNTS`)


@dataclass
class Derived:
    """A computed score, or no value and the reason (``derived_missing_input:<c>`` / ``derived_unit:<c>``)."""

    value: float | None
    reason: str | None = None
    inputs: dict[str, Obs] = field(default_factory=dict)


def _latest(rows: Iterable[Obs], near: date | None = None, days: int = 0) -> Obs | None:
    pick = [o for o in rows if near is None or abs((o.on - near).days) <= days]
    return max(pick, key=lambda o: (o.on, o.oid)) if pick else None


def compute(
    score: str,
    obs: Mapping[str, Iterable[Obs]],
    *,
    age: int | None = None,
    female: bool | None = None,
) -> Derived:
    """The reference engine the SQL templates mirror: pick the visit's components (:data:`SAME_VISIT`), convert their
    units (:data:`UNITS`), compute, or say why not. ``obs`` holds each component's rows inside the window."""
    rows = {c: [o for o in obs.get(c, ()) if o.status in COUNTS] for c in COMPONENTS[score]}
    picked: dict[str, Obs] = {}
    rule = SAME_VISIT.get(score)
    if rule is not None:
        anchor_comp, spread = rule
        anchor = _latest(rows[anchor_comp])
        if anchor is None:
            return Derived(None, f"{MISSING}:{anchor_comp}")
        picked[anchor_comp] = anchor
        for c, days in spread.items():
            got = _latest(rows[c], anchor.on, days)
            if got is not None:
                picked[c] = got
    else:
        for c in COMPONENTS[score]:
            got = _latest(rows[c])
            if got is not None:
                picked[c] = got
    need = list(COMPONENTS[score])
    if score == "das28":  # ESR when the visit has one, else CRP
        need.remove("crp" if "esr" in picked else "esr")
    val: dict[str, float] = {}
    for c in need:
        if c not in picked:
            return Derived(None, f"{MISSING}:{c}", picked)
        v, why = convert(c, picked[c].value, picked[c].unit)
        if v is None:
            return Derived(None, why, picked)
        if not in_domain(c, v):  # an impossible value: no value and the reason, never an error
            return Derived(None, f"{UNIT}:{c}", picked)
        val[c] = v
    if score.startswith("egfr"):
        if age is None or age <= 0:  # JSN raises the age to a negative power: 0 or less is no usable age
            return Derived(None, f"{MISSING}:age", picked)
        if female is None:
            return Derived(None, f"{MISSING}:sex", picked)
        fn = egfr_jsn if score == "egfr_jsn" else egfr
        return Derived(fn(val["creatinine"], age, female), None, picked)
    if score == "bmi":
        return Derived(bmi(val["weight"], val["height"]), None, picked)
    if score == "das28":
        if "esr" in val:
            if val["esr"] <= 0:  # ln(0): the zero rule of the catalogue is "no value"
                return Derived(None, f"{MISSING}:esr", picked)
            return Derived(das28_esr(val["tjc28"], val["sjc28"], val["ptga"], val["esr"]), None, picked)
        return Derived(das28_crp(val["tjc28"], val["sjc28"], val["ptga"], val["crp"]), None, picked)
    if score in ("das28_esr", "das28_crp"):
        joints = (val["tjc28"], val["sjc28"], val["ptga"])
        if score == "das28_crp":
            return Derived(das28_crp(*joints, val["crp"]), None, picked)
        if val["esr"] <= 0:  # ln(0): the catalogue's zero rule is "no value"
            return Derived(None, f"{MISSING}:esr", picked)
        return Derived(das28_esr(*joints, val["esr"]), None, picked)
    if score == "cdai":
        return Derived(cdai(val["tjc28"], val["sjc28"], val["ptga10"], val["evga"]), None, picked)
    if score == "sdai":  # CRP in mg/dL: the unit table gives mg/L
        return Derived(sdai(val["tjc28"], val["sjc28"], val["ptga10"], val["evga"], val["crp"] / 10.0), None, picked)
    if score == "basdai":
        return Derived(basdai(*(val[f"basdai_q{i}"] for i in range(1, 7))), None, picked)
    if score == "asdas":
        v = asdas_crp(val["basdai_q2"], val["basdai_q6"], val["ptga"], val["basdai_q3"], val["crp"])
        return Derived(v, None, picked)
    raise ValueError(f"derived {score}")
