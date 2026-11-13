"""The three-engine boundary table (T-711, D-480; review 2026-11-12 ``decision.md`` answer 3, card AD-7).

The equivalence gate compares SQL and CQL on a sample of a site's own patients at one index date: a boundary case
is compared only if the site happens to hold one, and the Python reference (:mod:`tb_common.derived`) is in no gate.
This module generates synthetic patients that each sit on one edge of one criterion of a shipped ruleset, with the
answer the **Python reference** gives:

* **age**: the birthday itself and the day before; a 29 February birth on 28 February and 1 March of a common year
  and on 28 and 29 February of a leap year; the upper bound of an age range;
* **window**: the first and the last day of a window and the day outside each, for a value criterion, a derived
  score, a window that ends before the index date and a condition;
* **zone**: an instant written in UTC that is another day in the site's zone, at both ends of a window;
* **unit**: each unit a derived score converts, a unit it does not know and no unit;
* **impossible**: a value outside the physiological range of its component;
* **score**: each derived score just on either side of its criterion's threshold, the visit rule of DAS28 and the
  adult-only rule of eGFR.

``tools/boundary_check.py`` runs the table through the generated SQL (an in-process lake built from the FHIR
resources by the ingest's own steps) and CQL (the local engine), and fails on a disagreement of any two of the
three. That is the ``differential`` gate of TB-PLAN-06 §7.5.

Nothing here is a person: every id, date and value is made up for the check (synthetic data only). No site zone is
named: the table runs in the zone of the edge fixture (``edge.SITE_TZ``, D-315).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tb_common import derived
from tb_common.ruleset import Ruleset

from criteria_compiler.equivalence.edge import SITE_TZ

INDEX = date(2026, 10, 5)
#: the rulesets the table reads its criteria from (their SQL, CQL and ELM are committed)
RULESETS = ("GZQO", "RA-BIO", "RA-JAK", "AD-MAB")
UCUM = "http://unitsofmeasure.org"
GROUPS = ("age", "window", "zone", "unit", "impossible", "score")
Answer = bool | None


@dataclass(frozen=True)
class Case:
    """One patient on one edge: at ``index`` the criterion's answer is ``expected`` by the Python reference."""

    pid: str
    ruleset: str
    criterion: str
    index: date
    expected: Answer
    group: str
    edge: str

    @property
    def key(self) -> str:
        return f"{self.ruleset}/{self.criterion}/{self.pid}@{self.index.isoformat()}"


@dataclass
class Table:
    cases: list[Case] = field(default_factory=list)
    resources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # ruleset -> FHIR resources

    def of(self, ruleset: str) -> list[Case]:
        return [c for c in self.cases if c.ruleset == ruleset]

    def index_dates(self, ruleset: str) -> list[date]:
        return sorted({c.index for c in self.of(ruleset)})


# ------------------------------------------------------------------------------------------------ FHIR resources
def _local(day: date, hhmm: str = "09:00") -> str:
    """A site-local time as the feed writes it (the zone's own offset on that day)."""
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo(SITE_TZ)).isoformat()


def _site_day(when: str) -> date:
    """The calendar day of an instant in the site's zone: what a window is counted in."""
    return datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(ZoneInfo(SITE_TZ)).date()


def _patient(pid: str, birth: date, female: bool) -> dict[str, Any]:
    return {"resourceType": "Patient", "id": pid, "gender": "female" if female else "male",
            "birthDate": birth.isoformat()}  # fmt: skip


def _observation(pid: str, n: int, system: str, code: str, when: str, value: float, unit: str | None,
                 ucum: str | None = None) -> dict[str, Any]:  # fmt: skip
    """``unit``: the unit as the result prints it; ``ucum``: its UCUM code when the two differ."""
    qty: dict[str, Any] = {"value": value}
    if unit is not None:
        qty.update({"unit": unit, "system": UCUM, "code": ucum or unit})
    return {
        "resourceType": "Observation",
        "id": f"{pid}-o{n}",
        "status": "final",
        "code": {"coding": [{"system": system, "code": code}]},
        "subject": {"reference": f"Patient/{pid}"},
        "effectiveDateTime": when,
        "valueQuantity": qty,
    }


def _condition(pid: str, n: int, system: str, code: str, on: date) -> dict[str, Any]:
    clinical = "http://terminology.hl7.org/CodeSystem/condition-clinical"
    return {
        "resourceType": "Condition",
        "id": f"{pid}-c{n}",
        "clinicalStatus": {"coding": [{"system": clinical, "code": "active"}]},
        "code": {"coding": [{"system": system, "code": code}]},
        "subject": {"reference": f"Patient/{pid}"},
        "onsetDateTime": on.isoformat(),
        "recordedDate": on.isoformat(),
    }


def first_code(valueset: Mapping[str, Any]) -> tuple[str, str]:
    """(system, code) of the first concept of a ValueSet's ``compose``."""
    inc = valueset["compose"]["include"][0]
    return str(inc["system"]), str(inc["concept"][0]["code"])


# ------------------------------------------------------------------------------------------------ the reference
def _atom(rs: Ruleset, cid: str) -> dict[str, Any]:
    c = rs.by_id()[cid]
    logic = c.logic if isinstance(c.logic, dict) else c.logic.model_dump(exclude_none=True)
    if "domain" not in logic:
        raise ValueError(f"{cid} is not a single atom: the table reads its window and threshold from one")
    return dict(logic)


def _window(atom: Mapping[str, Any], index: date) -> tuple[date | None, date | None]:
    w = atom.get("window") or {}
    lo = index + timedelta(days=int(w["from_days"])) if w.get("from_days") is not None else None
    hi = index + timedelta(days=int(w["to_days"])) if w.get("to_days") is not None else None
    return lo, hi


def _inside(day: date, atom: Mapping[str, Any], index: date) -> bool:
    lo, hi = _window(atom, index)
    return (lo is None or day >= lo) and (hi is None or day <= hi)


def _compare(value: float | None, atom: Mapping[str, Any]) -> Answer:
    if value is None:
        return None
    op, num = atom["value"]["op"], float(atom["value"]["num"])
    table: dict[str, Callable[[float, float], bool]] = {
        ">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    }  # fmt: skip
    return table[op](value, num)


def ref_age(atom: Mapping[str, Any], birth: date, index: date) -> Answer:
    """The age atom by the reference: complete years on the index date within the range (both ends included)."""
    age = derived.age_at(birth, index)
    lo, hi = atom["age"].get("min"), atom["age"].get("max")
    return (lo is None or age >= lo) and (hi is None or age <= hi)


Row = tuple[str, str, float, str | None]  # component (or "" for the atom's own code), instant, value, unit


def ref_latest(atom: Mapping[str, Any], rows: list[Row], index: date) -> Answer:
    """A value criterion: the latest result of the window against the threshold; none in the window is unknown."""
    inside = [(when, v) for _, when, v, _ in rows if _inside(_site_day(when), atom, index)]
    if not inside:
        return None
    return _compare(max(inside, key=lambda r: datetime.fromisoformat(r[0].replace("Z", "+00:00")))[1], atom)


def ref_score(atom: Mapping[str, Any], rows: list[Row], birth: date, female: bool, index: date) -> Answer:
    """A derived score by :func:`tb_common.derived.compute` over the window's component rows, against the
    threshold; no value (a missing input, a unit, an impossible value, the adult-only rule) is unknown."""
    score = str(atom["derived"])
    obs: dict[str, list[derived.Obs]] = {}
    for i, (comp, when, value, unit) in enumerate(rows):
        day = _site_day(when)
        if _inside(day, atom, index):
            obs.setdefault(comp, []).append(derived.Obs(value, unit, day, f"o{i}"))
    got = derived.compute(score, obs, age=derived.age_at(birth, index), female=female)
    return _compare(got.value, atom)


def ref_condition(atom: Mapping[str, Any], days: list[date], index: date) -> Answer:
    """A coded condition, quantifier ``any``: present when one is dated inside the window."""
    return any(_inside(d, atom, index) for d in days)


# ------------------------------------------------------------------------------------------------ the generator
class _Builder:
    def __init__(self, rulesets: Mapping[str, Ruleset]) -> None:
        self.rs = rulesets
        self.t = Table(resources={rid: [] for rid in rulesets})
        self._n = 0

    def _add(self, rid: str, pid: str, birth: date, female: bool, extra: list[dict[str, Any]]) -> None:
        self.t.resources[rid] += [_patient(pid, birth, female), *extra]

    def _case(self, pid: str, rid: str, cid: str, index: date, expected: Answer, group: str, edge: str) -> None:
        self.t.cases.append(Case(pid, rid, cid, index, expected, group, edge))

    # -- age
    def age(self, rid: str, cid: str, pid: str, birth: date, indexes: list[date], edge: str) -> None:
        atom = _atom(self.rs[rid], cid)
        self._add(rid, pid, birth, True, [])
        for index in indexes:
            self._case(pid, rid, cid, index, ref_age(atom, birth, index), "age", edge)

    # -- a value criterion (one coded result)
    def latest(self, rid: str, cid: str, pid: str, when: str, value: float, unit: str, group: str, edge: str,
               index: date = INDEX) -> None:  # fmt: skip
        rs = self.rs[rid]
        atom = _atom(rs, cid)
        system, code = first_code(rs.valuesets[atom["valueset"]])
        self._add(rid, pid, date(1970, 3, 1), True, [_observation(pid, 1, system, code, when, value, unit)])
        self._case(pid, rid, cid, index, ref_latest(atom, [("", when, value, unit)], index), group, edge)

    # -- a derived score
    def score(self, rid: str, cid: str, pid: str, rows: list[Row], group: str, edge: str, *,
              birth: date = date(1960, 3, 1), female: bool = True, index: date = INDEX,
              ucum: str | None = None) -> None:  # fmt: skip
        """``ucum``: the UCUM code of the rows' unit when it differs from the printed unit (one-component scores)."""
        atom = _atom(self.rs[rid], cid)
        res = [
            _observation(pid, i, *derived.CODES[comp], when, value, unit, ucum)
            for i, (comp, when, value, unit) in enumerate(rows, start=1)
        ]
        self._add(rid, pid, birth, female, res)
        self._case(pid, rid, cid, index, ref_score(atom, rows, birth, female, index), group, edge)

    # -- a condition
    def condition(self, rid: str, cid: str, pid: str, on: date, edge: str, index: date = INDEX) -> None:
        rs = self.rs[rid]
        atom = _atom(rs, cid)
        system, code = first_code(rs.valuesets[atom["valueset"]])
        self._add(rid, pid, date(1970, 3, 1), True, [_condition(pid, 1, system, code, on)])
        self._case(pid, rid, cid, index, ref_condition(atom, [on], index), "window", edge)


def _creatinine_at(target: float, age: int, female: bool, fn: Callable[[float, int, bool], float]) -> float:
    """The creatinine (mg/dL) at which the equation gives ``target`` (the eGFR falls as creatinine rises)."""
    lo, hi = 0.2, 20.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if fn(mid, age, female) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def build(rulesets: Mapping[str, Ruleset]) -> Table:
    """The table for the shipped rulesets ``rulesets`` (:data:`RULESETS`, loaded by the caller)."""
    b = _Builder(rulesets)
    day = timedelta(days=1)
    visit = INDEX - 10 * day

    # ---------------------------------------------------------------- age (GZQO: 18 or older; RA-JAK: 18 to 75)
    common = [date(2026, 2, 28), date(2026, 3, 1)]  # 2026 has no 29 February
    leap = [date(2028, 2, 28), date(2028, 2, 29)]
    b.age("GZQO", "GZQO-INC-01", "b-age-18-today", date(2008, 10, 5), [INDEX], "the 18th birthday is the index date")
    b.age("GZQO", "GZQO-INC-01", "b-age-18-tomorrow", date(2008, 10, 6), [INDEX], "the day before the 18th birthday")
    b.age("GZQO", "GZQO-INC-01", "b-age-feb29-common", date(2008, 2, 29), common,
          "born 29 February, turning 18 in a common year: 28 February and 1 March")  # fmt: skip
    b.age("RA-JAK", "RA-JAK-INC-01", "b-age-75-last-day", date(1950, 10, 6), [INDEX], "75 until tomorrow: in range")
    b.age("RA-JAK", "RA-JAK-INC-01", "b-age-76-today", date(1950, 10, 5), [INDEX], "the 76th birthday: out of range")
    b.age("RA-JAK", "RA-JAK-INC-01", "b-age-feb29-76-leap", date(1952, 2, 29), leap,
          "born 29 February, turning 76 in a leap year: 28 and 29 February")  # fmt: skip
    b.age("RA-JAK", "RA-JAK-INC-01", "b-age-18-today", date(2008, 10, 5), [INDEX], "the 18th birthday: the lower end")
    b.age(
        "AD-MAB", "AD-MAB-INC-01", "b-age-50-tomorrow", date(1976, 10, 6), [INDEX], "the day before the 50th birthday"
    )
    b.age("AD-MAB", "AD-MAB-INC-01", "b-age-86-today", date(1940, 10, 5), [INDEX], "the 86th birthday: out of range")
    b.age("AD-MAB", "AD-MAB-INC-01", "b-age-feb29-50-common", date(1976, 2, 29), common,
          "born 29 February, turning 50 in a common year: 28 February and 1 March")  # fmt: skip
    b.age("AD-MAB", "AD-MAB-INC-01", "b-age-feb29-86-common", date(1940, 2, 29), common,
          "born 29 February, turning 86 in a common year: 28 February and 1 March")  # fmt: skip

    # ---------------------------------------------------------------- window ends (GZQO-EXC-13: ALT, 180 days)
    alt = ("GZQO", "GZQO-EXC-13")
    first = INDEX - 180 * day
    b.latest(*alt, "b-win-last-day", _local(INDEX, "12:00"), 200.0, "U/L", "window", "a result on the index date")
    b.latest(*alt, "b-win-day-after", _local(INDEX + day, "00:30"), 200.0, "U/L", "window",
             "a result half an hour into the day after the index date")  # fmt: skip
    b.latest(*alt, "b-win-first-day", _local(first, "00:30"), 200.0, "U/L", "window", "the first day of the window")
    b.latest(*alt, "b-win-day-before", _local(first - day, "23:30"), 200.0, "U/L", "window",
             "half an hour before the window opens")  # fmt: skip
    # the same edges written in UTC: another calendar day in the site's zone
    utc_open = datetime.fromisoformat(_local(first, "07:30")).astimezone(UTC)
    utc_close = datetime.fromisoformat(_local(INDEX, "23:30")).astimezone(UTC)
    utc_after = datetime.fromisoformat(_local(INDEX + day, "00:30")).astimezone(UTC)
    for pid, when, edge in (
        ("b-zone-open-utc", utc_open, "UTC the day before the window opens, the first day in the site's zone"),
        ("b-zone-close-utc", utc_close, "23:30 on the index date in the site's zone, written in UTC"),
        ("b-zone-after-utc", utc_after, "00:30 on the day after the index date in the site's zone, written in UTC"),
    ):
        b.latest(*alt, pid, when.strftime("%Y-%m-%dT%H:%M:%SZ"), 200.0, "U/L", "zone", edge)
    # a condition window (RA-BIO-EXC-06: serious infection in the 30 days before)
    inf = ("RA-BIO", "RA-BIO-EXC-06")
    b.condition(*inf, "b-win-cond-first-day", INDEX - 30 * day, "a condition on the first day of the window")
    b.condition(*inf, "b-win-cond-day-before", INDEX - 31 * day, "a condition the day before the window opens")
    b.condition(*inf, "b-win-cond-index", INDEX, "a condition on the index date")
    b.condition(*inf, "b-win-cond-day-after", INDEX + day, "a condition dated the day after the index date")

    # ---------------------------------------------------------------- derived scores
    # BMI (GZQO-INC-03: 27 or more, 365 days)
    bmi = ("GZQO", "GZQO-INC-03")

    def body(weight: float, wu: str | None, height: float, hu: str | None, on: date = visit) -> list[Row]:
        return [("weight", _local(on), weight, wu), ("height", _local(on), height, hu)]

    b.score(*bmi, "b-bmi-above", body(78.5, "kg", 170.0, "cm"), "score", "BMI just above 27")
    b.score(*bmi, "b-bmi-below", body(77.5, "kg", 170.0, "cm"), "score", "BMI just below 27")
    b.score(*bmi, "b-bmi-lb-in", body(173.1, "[lb_av]", 66.93, "[in_i]"), "unit", "weight in pounds, height in inches")
    b.score(*bmi, "b-bmi-g-m", body(78500.0, "g", 1.70, "m"), "unit", "weight in grams, height in metres")
    b.score(*bmi, "b-bmi-unit-unknown", body(78.5, "st", 170.0, "cm"), "unit", "a weight unit the table does not know")
    b.score(*bmi, "b-bmi-no-unit", body(78.5, None, 170.0, "cm"), "unit", "a weight with no unit")
    b.score(*bmi, "b-bmi-height-zero", body(78.5, "kg", 0.0, "cm"), "impossible", "a height of 0: no division by zero")
    b.score(*bmi, "b-bmi-weight-negative", body(-78.5, "kg", 170.0, "cm"), "impossible",
            "a negative weight: no component range is declared, so the three give the same (false) answer")  # fmt: skip
    b.score(*bmi, "b-bmi-first-day", body(78.5, "kg", 170.0, "cm", INDEX - 365 * day), "window",
            "both components on the first day of the 365-day window")  # fmt: skip
    b.score(*bmi, "b-bmi-day-before", body(78.5, "kg", 170.0, "cm", INDEX - 366 * day), "window",
            "both components the day before the window opens")  # fmt: skip

    # eGFR CKD-EPI 2021 (GZQO-INC-08: 30 or more; RA-JAK-EXC-11: under 40)
    egfr = ("GZQO", "GZQO-INC-08")
    c30 = _creatinine_at(30.0, derived.age_at(date(1960, 3, 1), INDEX), True, derived.egfr)

    def crea(value: float, unit: str | None, on: date = visit) -> list[Row]:
        return [("creatinine", _local(on), value, unit)]

    b.score(*egfr, "b-egfr-above", crea(round(c30 * 0.98, 3), "mg/dL"), "score", "eGFR just above 30")
    b.score(*egfr, "b-egfr-below", crea(round(c30 * 1.02, 3), "mg/dL"), "score", "eGFR just below 30")
    b.score(*egfr, "b-egfr-umol-above", crea(round(c30 * 0.98 * 88.4, 1), "umol/L"), "unit", "creatinine in umol/L")
    b.score(*egfr, "b-egfr-umol-micro-printed", crea(round(c30 * 1.02 * 88.4, 1), "µmol/L"), "unit",
            "creatinine printed as µmol/L with the UCUM code umol/L", ucum="umol/L")  # fmt: skip
    b.score(*egfr, "b-egfr-umol-micro", crea(round(c30 * 1.02 * 88.4, 1), "µmol/L"), "unit",
            "creatinine whose unit code itself starts with the micro sign")  # fmt: skip
    b.score(*egfr, "b-egfr-unit-upper", crea(round(c30 * 1.02, 3), "MG/DL"), "unit", "the unit in upper case")
    b.score(*egfr, "b-egfr-unit-spaces", crea(round(c30 * 1.02, 3), "mg / dL"), "unit", "the unit with spaces")
    b.score(*egfr, "b-egfr-unit-unknown", crea(1.0, "mmol/L"), "unit", "a creatinine unit the table does not know")
    b.score(*egfr, "b-egfr-zero", crea(0.0, "mg/dL"), "impossible", "a creatinine of 0")
    b.score(*egfr, "b-egfr-negative", crea(-1.0, "mg/dL"), "impossible", "a negative creatinine")
    b.score(*egfr, "b-egfr-18-today", crea(1.0, "mg/dL"), "score", "eGFR on the 18th birthday: an adult",
            birth=date(2008, 10, 5))  # fmt: skip
    b.score(*egfr, "b-egfr-17", crea(1.0, "mg/dL"), "score", "eGFR the day before the 18th birthday: not computed",
            birth=date(2008, 10, 6))  # fmt: skip
    b.score(*egfr, "b-egfr-male", crea(round(c30 * 0.98, 3), "mg/dL"), "score", "the same creatinine in a man",
            female=False)  # fmt: skip
    jak = ("RA-JAK", "RA-JAK-EXC-11")
    c40 = _creatinine_at(40.0, derived.age_at(date(1960, 3, 1), INDEX), True, derived.egfr)
    b.score(*jak, "b-egfr40-above", crea(round(c40 * 0.98, 3), "mg/dL"), "score", "eGFR just above 40: not excluded")
    b.score(*jak, "b-egfr40-below", crea(round(c40 * 1.02, 3), "mg/dL"), "score", "eGFR just below 40: excluded")
    # eGFR JSN 2009 (AD-MAB-EXC-04: under 30)
    jsn = ("AD-MAB", "AD-MAB-EXC-04")
    j30 = _creatinine_at(30.0, derived.age_at(date(1960, 3, 1), INDEX), True, derived.egfr_jsn)
    b.score(*jsn, "b-jsn-above", crea(round(j30 * 0.98, 3), "mg/dL"), "score", "eGFR (JSN) just above 30")
    b.score(*jsn, "b-jsn-below", crea(round(j30 * 1.02, 3), "mg/dL"), "score", "eGFR (JSN) just below 30")
    b.score(*jsn, "b-jsn-umol", crea(round(j30 * 1.02 * 88.4, 1), "umol/L"), "unit", "creatinine in umol/L (JSN)")

    # DAS28 (RA-BIO-INC-05: above 5.1, the 90 days before; RA-BIO-INC-06: the 90 days before those)
    das = ("RA-BIO", "RA-BIO-INC-05")

    def joints(ptga: float, on: date = visit, tjc: float = 10.0, sjc: float = 8.0) -> list[Row]:
        return [("tjc28", _local(on), tjc, None), ("sjc28", _local(on), sjc, None), ("ptga", _local(on), ptga, "mm")]

    def esr(value: float, on: date = visit, unit: str | None = "mm/h") -> list[Row]:
        return [("esr", _local(on), value, unit)]

    def crp(value: float, unit: str | None, on: date = visit) -> list[Row]:
        return [("crp", _local(on), value, unit)]

    b.score(*das, "b-das-esr-above", joints(60.0) + esr(30.0), "score", "DAS28-ESR above 5.1")
    b.score(*das, "b-das-esr-below", joints(10.0) + esr(12.0), "score", "DAS28-ESR below 5.1")
    b.score(*das, "b-das-crp-mgl", joints(60.0) + crp(20.0, "mg/L"), "unit", "DAS28-CRP, CRP in mg/L")
    b.score(*das, "b-das-crp-mgdl", joints(60.0) + crp(2.0, "mg/dL"), "unit", "DAS28-CRP, the same CRP in mg/dL")
    b.score(*das, "b-das-crp-ugml", joints(60.0) + crp(20.0, "µg/mL"), "unit",
            "DAS28-CRP, CRP in µg/mL: a unit code that starts with the micro sign")  # fmt: skip
    b.score(*das, "b-das-crp-mgdl-low", joints(5.0, tjc=6.0, sjc=4.0) + crp(0.2, "mg/dL"), "unit",
            "DAS28-CRP below 5.1 only when mg/dL is converted (read as mg/L it is lower still)")  # fmt: skip
    b.score(*das, "b-das-esr-wins", joints(60.0) + esr(30.0) + crp(0.1, "mg/L"), "score",
            "an ESR and a CRP at the visit: the ESR form is used")  # fmt: skip
    b.score(*das, "b-das-tjc-29", joints(60.0, tjc=29.0) + esr(30.0), "impossible", "a tender joint count of 29")
    b.score(*das, "b-das-crp-negative", joints(60.0) + crp(-1.0, "mg/L"), "impossible", "a negative CRP")
    b.score(*das, "b-das-esr-zero", joints(60.0) + esr(0.0), "impossible", "an ESR of 0")
    b.score(*das, "b-das-esr-7-days", joints(60.0) + esr(30.0, visit - 7 * day), "window",
            "the ESR seven days before the joint count: the same visit")  # fmt: skip
    b.score(*das, "b-das-esr-8-days", joints(60.0) + esr(30.0, visit - 8 * day), "window",
            "the ESR eight days before the joint count: not the same visit")  # fmt: skip
    b.score(*das, "b-das-first-day", joints(60.0, INDEX - 90 * day) + esr(30.0, INDEX - 90 * day), "window",
            "the visit on the first day of the 90-day window")  # fmt: skip
    b.score(*das, "b-das-day-before", joints(60.0, INDEX - 91 * day) + esr(30.0, INDEX - 91 * day), "window",
            "the visit the day before the window opens")  # fmt: skip
    b.score(*das, "b-das-no-ptga", joints(60.0)[:2] + esr(30.0), "score", "no patient global: no value")
    earlier = ("RA-BIO", "RA-BIO-INC-06")
    for pid, back, edge in (
        ("b-das-earlier-last-day", 90, "the last day of a window that ends 90 days before the index date"),
        ("b-das-earlier-day-after", 89, "the day after that window closes"),
        ("b-das-earlier-first-day", 180, "the first day of that window"),
        ("b-das-earlier-day-before", 181, "the day before that window opens"),
    ):
        on = INDEX - back * day
        b.score(*earlier, pid, joints(60.0, on) + esr(30.0, on), "window", edge)
    return b.t
