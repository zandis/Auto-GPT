"""Shared, engine-independent interpretation of Criterion IR atoms (used by both the CQL and the SQL generator).

Normative semantics (DECISIONS D-17):

* Window ``[I + from_days, I + to_days]`` on the local calendar date of the event, inclusive; missing ``from_days`` =
  unbounded past, missing ``to_days`` = index date. Derived atoms default to their DEFAULT_WINDOW_DAYS.
* Code-presence atoms (``condition``, ``medication`` without duration, ``procedure``, ``encounter``, ``claim``,
  ``report``, ``observation`` without ``value``) are never null.
* ``observation`` with ``value``: null when no matching observation is in the window; ``latest`` compares the most
  recent observation (ties broken by resource id); ``any``/``all``/``none``/``count>=`` over all matching ones.
  A number is compared in the criterion's unit (``value.unit``): a row in another unit is converted when
  ``tb_common.labunit`` has a factor for that analyte, or when both units are of one kind (g/L and g/dL, D-418), and
  otherwise (a row with no unit included) has no usable number, like a text result: it never makes the comparison
  true or false (D-275).
* ``demographic``: age = complete years at the index date; null when the birth date is missing or the gender is
  not ``male`` / ``female`` (missing, ``other``, ``unknown``; D-275).
* ``derived``: computed from the latest components in the window; null when a component is missing; without
  ``value`` the atom is true when computable.
* ``medication`` with ``duration``: validity periods clipped to the window, merged when the gap <= ``gap_days``,
  longest island in days (inclusive) compared with ``min_days``. Null when the dated periods do not reach
  ``min_days`` and a matching order has no end date (it began on or before the window's end) or no date at all:
  its length is not known (D-275). An order with no end date still counts one day towards the dated periods.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from tb_common.derived import COMPONENTS, DEFAULT_WINDOW_DAYS
from tb_contracts import Atom, BoolExpr, CriterionIR
from tb_contracts.criterion_ir import Atom as Atom3
from tb_contracts.criterion_ir import CriterionIRv3, NotV1Expressible, downgrade_to_v1, upgrade_v1

UNBOUNDED_PAST = "1900-01-01"
#: the evidence token of a ``value.ref`` comparison that has no bound: the result carries no reference range of its
#: own and the signed site table has none for its code, unit and sex (RULES-ARCH §2.5)
NO_REFERENCE_RANGE = "no_reference_range"


class CompileError(ValueError):
    """IR that cannot be compiled deterministically (blocks the ruleset; flagged needs_review)."""


class UnknownValueSet(CompileError, KeyError):
    """B14 (D-502): IR naming a value set that no concept candidate defined (a model answer can). A
    :class:`CompileError`, so the criterion goes to a person and the rest compiles; still a ``KeyError`` for any caller
    that caught one."""

    def __str__(self) -> str:  # KeyError would quote the message
        return str(self.args[0]) if self.args else ""


class Kind(StrEnum):
    PRESENCE = "presence"  # exists/count/none over coded events (never null)
    OBS_VALUE = "obs_value"  # observation value comparison (null when no observation)
    DEMOGRAPHIC = "demographic"
    DERIVED = "derived"
    MED_DURATION = "med_duration"


@dataclass(frozen=True)
class Window:
    from_days: int | None
    to_days: int


@dataclass(frozen=True)
class AnchoredWindow(Window):
    """A window counted from a study anchor (screening / randomization) instead of the index date: ``anchor`` is the
    engine's expression for that date (``b.screening_date`` in SQL, ``ScreeningDate`` in CQL)."""

    anchor: str = "b.index_date"


@dataclass(frozen=True)
class RefRangeRow:
    """One line of the site table: the range a lab reports for one analyte code in one unit, for one sex or both."""

    system: str
    code: str
    unit: str
    sex: Literal["male", "female"] | None
    low: float | None
    high: float | None


@dataclass(frozen=True)
class SiteRefRanges:
    """The signed site default table of reference ranges (RULES-ARCH §2.3, risk 4): ``value.ref`` reads it when a
    result carries no range of its own. A table without a signer and a date is refused, and nothing in it is a
    default the compiler invents: a code, unit or sex it does not list gives no bound (``no_reference_range``)."""

    signed_by: str
    signed_at: str
    rows: tuple[RefRangeRow, ...]

    @classmethod
    def load(cls, path: Path) -> SiteRefRanges:
        """``{"signed": {"by": ..., "at": ...}, "ranges": [{"system", "code", "unit", "sex"?, "low"?, "high"?}]}``."""
        doc = json.loads(path.read_text(encoding="utf-8"))
        signed = doc.get("signed") or {}
        if not str(signed.get("by") or "").strip() or not str(signed.get("at") or "").strip():
            raise ValueError(f"{path}: the site reference-range table is not signed (signed.by and signed.at)")
        rows = []
        for r in doc.get("ranges") or []:
            low, high = r.get("low"), r.get("high")
            if r.get("sex") not in (None, "male", "female"):
                raise ValueError(f"{path}: sex {r.get('sex')!r} is not male, female or absent")
            if (low is None and high is None) or any(
                x is not None and not (isinstance(x, int | float) and math.isfinite(x)) for x in (low, high)
            ):
                raise ValueError(f"{path}: {r.get('code')}: a range needs a finite low or high")
            rows.append(RefRangeRow(r["system"], r["code"], r["unit"], r.get("sex"), low, high))
        return cls(str(signed["by"]), str(signed["at"]), tuple(rows))

    def bounds(self, kind: Literal["uln", "lln"], codes: list[tuple[str, str]]) -> list[tuple[RefRangeRow, float]]:
        """The rows giving a ``kind`` bound for those (system, code) pairs: a row for the patient's sex before the
        row for both, as a lab that gives both means; first match wins."""
        want = set(codes)
        out = [(r, r.high if kind == "uln" else r.low) for r in self.rows if (r.system, r.code) in want]
        got = [(r, b) for r, b in out if b is not None]
        return sorted(got, key=lambda rb: rb[0].sex is None)  # stable: the table's order within each group


def window(atom: Atom) -> Window:
    if atom.derived and atom.window is None:
        return Window(-DEFAULT_WINDOW_DAYS[atom.derived], 0)
    if atom.window is None:
        return Window(None, 0)
    if atom.window.anchor not in (None, "index"):
        raise CompileError("window anchor 'event' is not supported in v1.0 (use index-relative windows)")
    to_days = 0 if atom.window.to_days is None else atom.window.to_days
    if atom.window.from_days is not None and atom.window.from_days > to_days:
        raise CompileError(f"empty window [{atom.window.from_days}, {to_days}]")
    return Window(atom.window.from_days, to_days)


def kind(atom: Atom) -> Kind:
    if atom.domain == "demographic":
        if atom.age is None and atom.sex is None:
            raise CompileError("demographic atom needs age and/or sex")
        lo, hi = (atom.age.min, atom.age.max) if atom.age is not None else (None, None)
        if (lo is not None and lo < 0) or (hi is not None and hi < 0):  # D-914
            raise CompileError("an age bound below 0")
        if lo is not None and hi is not None and lo > hi:  # D-914: matched by no one ("80 to 18")
            raise CompileError(f"age range {lo} to {hi} is reversed")
        # D-946 (F2 of P1b, NCT01260883 "0.17 years"): the age is complete years (D-442), so a bound of 0.17 is met by
        # no one under 1 and 1.5 by no one under 2; a person reads it (months are not compared)
        for b in (lo, hi):  # review: NaN and infinity are refused too (int() raised past every CompileError catch)
            if b is not None and not (math.isfinite(float(b)) and float(b).is_integer()):
                raise CompileError(f"age bound {b!r} is not a whole number of years; the age is counted in years")
        return Kind.DEMOGRAPHIC
    if atom.derived is not None:
        if atom.domain != "observation":
            raise CompileError("derived values are observation atoms")
        # G5 of the P1b review (D-956, NCT01187901): a derived name that does not exist, with value.op "in", reached
        # the CQL as ``(None in { })`` and failed the translator. A derived value is a known score, compared as a number
        if atom.derived not in COMPONENTS:
            raise CompileError(f"derived value {atom.derived!r} is not one this box computes ({', '.join(COMPONENTS)})")
        if atom.value is not None:  # none: "computable" (TRUE when the score can be computed, D-149)
            if atom.value.op == "in":
                raise CompileError(
                    f"derived value {atom.derived} is a number: 'in' a list of codes does not compare it"
                )
            check_value(atom)
        return Kind.DERIVED
    if atom.duration is not None:
        if atom.domain != "medication" or atom.duration.min_days is None:
            raise CompileError("duration requires domain=medication and min_days")
        if atom.duration.min_days <= 0:  # D-914 (lane G, case 10): "within 3 months" as at least -90 days, met by all
            raise CompileError(f"duration of at least {atom.duration.min_days} days is met by everyone; a time limit "
                               f"is a window, a duration a positive number of days")  # fmt: skip
        return Kind.MED_DURATION
    if atom.value is not None:
        if atom.domain != "observation":
            raise CompileError(f"value comparison is only supported for observations (got {atom.domain})")
        check_value(atom)
        return Kind.OBS_VALUE
    if atom.quantifier in ("latest", "all"):
        raise CompileError(f"quantifier {atom.quantifier} requires a value comparison")
    if atom.quantifier == "count>=" and atom.count is None:
        raise CompileError("count>= requires count")
    if atom.valueset in ("", "NONE"):
        raise CompileError(f"{atom.domain} atom needs a ValueSet")
    return Kind.PRESENCE


def lower(criterion: CriterionIR | CriterionIRv3) -> tuple[CriterionIR, dict[int, Atom3]]:
    """How both generators read a criterion (RULES-ARCH §2.3): a v1 criterion is upgraded to IR 3 at load
    (``upgrade_v1``), then each atom becomes the v1-shaped atom the shared templates compile, and its v3 atom is kept
    beside it (keyed by the lowered atom's ``id()``) for the qualifiers a generator compiles itself. A qualifier no
    generator compiles raises :class:`CompileError` (the criterion goes to a person); none is dropped. ``card_ref`` is
    provenance and changes nothing; ``on_hit: exclude``, ``unit: d`` and ``subject: patient`` mean what their absence
    means."""
    if isinstance(criterion, CriterionIR):
        criterion = upgrade_v1(criterion)
    if criterion.macros:
        raise CompileError("expand macros before SQL compilation")
    extensions: dict[int, Atom3] = {}
    by_id = {a.id: a for a in criterion.atoms}

    def walk(node: Any) -> Atom | BoolExpr:
        if not isinstance(node, str):
            return BoolExpr.model_construct(op=node.op, args=[walk(arg) for arg in node.args])
        return switched(by_id[node], ())

    def switched(a: Atom3, seen: tuple[str, ...]) -> Atom | BoolExpr:
        """``value_if`` (first match wins) as logic over atoms: with condition c, its threshold x and the rest r,
        ``(c AND x) OR (NOT c AND r) OR (x AND r)``. Under three-valued logic that is x when c holds, r when it does
        not, and, when c is unknown, the answer both thresholds agree on, else unknown. Each use is lowered afresh,
        so every atom of the result is its own object."""
        if not a.value_if:
            return one(a)
        if a.id in seen:
            raise CompileError(f"atom {a.id}: value_if conditions refer back to it")
        if a.value is None:
            raise CompileError(f"atom {a.id}: value_if needs the atom's own value")
        return branches(a, (*seen, a.id))

    def branches(a: Atom3, seen: tuple[str, ...]) -> Atom | BoolExpr:
        """The atom's own ``value_if`` list from its first branch on. ``seen`` already holds the atom: the later
        branches are the same atom, not a reference back to it, so only ``cond()`` checks for a cycle."""
        if not a.value_if:
            return one(a)
        first, later = a.value_if[0], a.value_if[1:]

        def rest() -> Atom | BoolExpr:
            return branches(a.model_copy(update={"value_if": later or None}), seen)

        def cond() -> Atom | BoolExpr:
            return switched(by_id[first.if_atom], seen)

        def alt() -> Atom | BoolExpr:
            return one(a.model_copy(update={"value": first.value, "value_if": None}))

        def node(op: Literal["and", "or", "not"], *args: Atom | BoolExpr) -> BoolExpr:
            return BoolExpr.model_construct(op=op, args=list(args))

        return node(
            "or",
            node("and", cond(), alt()),
            node("and", node("not", cond()), rest()),
            node("and", alt(), rest()),
        )

    def one(a: Atom3) -> Atom | BoolExpr:
        if a.attribute or a.change or a.aggregate or a.lot or a.diagnosis_role:
            raise CompileError(f"atom {a.id}: unsupported v3 qualifier")
        if a.window and a.window.unit == "h":
            raise CompileError(f"atom {a.id}: a window counted in hours is not compiled")
        data = a.model_dump(exclude_none=True)
        data.pop("on_hit", None)
        if data.get("subject") == "patient":
            del data["subject"]
        if "window" in data:
            data["window"].pop("unit", None)
        if a.window and a.window.anchor in ("screening", "randomization"):
            data["window"]["anchor"] = "index"
        if a.value and a.value.ref:
            if a.domain != "observation" or a.derived or a.value.op not in (">", ">=", "<", "<=", "="):
                raise CompileError("value.ref requires a scalar observation comparison")
            if a.value.num is not None or a.value.num2 is not None:
                raise CompileError("value.ref cannot also specify an absolute threshold")
            if not math.isfinite(a.value.ref.multiple):
                raise CompileError("reference multiple must be finite")
            data["value"] = {"op": a.value.op, "num": 0}
        if a.medication:
            if a.value or a.derived:
                raise CompileError("medication details cannot also carry an observation value")
            if a.duration or a.medication.status or (a.medication.dose and a.medication.dose.per_ingredient):
                raise CompileError("medication duration, status and per-ingredient qualifiers are unsupported")
            dose = a.medication.dose
            if dose and dose.basis == "single":
                raise CompileError("single administration dose cannot be inferred from exposure quantity")
            if dose and (
                dose.op not in (">", ">=", "<", "<=", "=", "between")
                or dose.num is None
                or (dose.op == "between" and dose.num2 is None)
            ):
                raise CompileError("dose requires numeric thresholds")
            if dose and any(not math.isfinite(n) for n in (dose.num, dose.num2) if n is not None):
                raise CompileError("dose thresholds must be finite")
            if a.medication.route == []:
                raise CompileError("medication.route must not be empty")
            if a.medication.route:  # ponytail: refused until a SNOMED -> OMOP route table exists; then map, compare
                raise CompileError(
                    f"atom {a.id}: medication.route is SNOMED and no SNOMED -> OMOP route mapping exists "
                    "(no_route_mapping)"
                )
            data.pop("medication")
            # Reuse observation quantifiers, including latest/all, for row predicates.
            data["domain"] = "observation"
            data["value"] = {"op": "=", "num": 1}
        shell = CriterionIRv3(
            ir_version=criterion.ir_version,  # a 3.1.0 atom reaches downgrade_to_v1, which refuses it by name
            id=criterion.id,
            ruleset=criterion.ruleset,
            kind=criterion.kind,
            class_=criterion.class_,
            text=criterion.text,
            atoms=[Atom3.model_validate(data)],
            logic=a.id,
        )
        try:
            atom = CriterionIR.model_validate(downgrade_to_v1(shell)).logic
        except NotV1Expressible as exc:
            raise CompileError(str(exc)) from exc
        extensions[id(atom)] = a
        return atom

    return (
        CriterionIR.model_construct(
            id=criterion.id,
            ruleset=criterion.ruleset,
            kind=criterion.kind,
            class_=criterion.class_,
            text=criterion.text.source,
            logic=walk(criterion.logic),
        ),
        extensions,
    )


def check_value(atom: Atom) -> None:
    v = atom.value
    assert v is not None
    if v.op is None:
        raise CompileError("value.op is required")
    if v.op == "in":
        if not v.codes:
            raise CompileError("value op 'in' requires codes")
    elif v.op == "between":
        if v.num is None or v.num2 is None:
            raise CompileError("value op 'between' requires num and num2")
    elif v.num is None:
        raise CompileError(f"value op {v.op!r} requires num")
    if atom.quantifier == "count>=" and atom.count is None:
        raise CompileError("count>= requires count")


def atoms(expr: Atom | BoolExpr) -> list[Atom]:
    if isinstance(expr, Atom):
        return [expr]
    out: list[Atom] = []
    for a in expr.args:
        out.extend(atoms(a))
    return out


def check_bool(expr: Atom | BoolExpr) -> None:
    if isinstance(expr, BoolExpr):
        if expr.op == "not" and len(expr.args) != 1:
            raise CompileError("'not' takes exactly one argument")
        for a in expr.args:
            check_bool(a)


FILTERED = ("structured", "mixed")  # classes whose logic is compiled to CQL/SQL (D-32, D-98)
JUDGED = ("note", "mixed")  # classes whose note_question goes to the model


def demographic_alone(logic: Atom | BoolExpr | None) -> bool:
    """Whether a criterion's coded logic is an age or a sex and nothing else: every atom demographic, none naming a
    ValueSet or a derived value (P2b: an exclusion that compiled to this while its line named more lost its
    qualifier; a mixed inclusion that compiled to this was met on its age alone, card 10A-2)."""
    if logic is None:
        return False
    got = atoms(logic)
    return bool(got) and all(_demographic(a) for a in got)


def _demographic(a: Atom) -> bool:
    """An age or sex atom (as :func:`demographic_alone` reads one)."""
    return a.domain == "demographic" and a.valueset in ("NONE", "", None) and not a.derived and bool(a.sex or a.age)


def met_on_demographics(logic: Atom | BoolExpr | None) -> bool:
    """Whether a criterion's coded logic can be true on its age and sex atoms alone: true for some answer of its age
    and sex atoms while every other record is absent (an atom false, a ``none`` atom true; card 10A-2: ``age``,
    ``age and sex``, ``age or gout``, ``age or not gout``, ``age and no gout record`` and ``not age`` can; ``gout``
    and ``age and gout`` cannot). A logic with more than 12 age or sex atoms
    is read as one that can (never seen; the answer that keeps the notes asked)."""
    if logic is None:
        return False
    demo = [a for a in atoms(logic) if _demographic(a)]
    if not demo:
        return False
    if len(demo) > 12:
        return True

    def ev(e: Atom | BoolExpr, on: dict[int, bool]) -> bool:
        if isinstance(e, Atom):  # a record's absence ("none") is true when every other record is taken as absent
            return on.get(id(e), e.quantifier == "none")
        if e.op == "not":
            return not ev(e.args[0], on)
        got = [ev(x, on) for x in e.args]
        return all(got) if e.op == "and" else any(got)

    return any(ev(logic, {id(a): bool(n >> i & 1) for i, a in enumerate(demo)}) for n in range(1 << len(demo)))


def codes_settle(c: CriterionIR) -> bool:
    """Whether a ``mixed`` criterion's coded part, when true, settles the line without its note question (D-98).
    Card 10A-2 (review 15, P2b: 6 of 81 mixed inclusions): an inclusion whose coded part can be true on an age or a
    sex alone ("18 years or older with a diagnosis of FAP", "women with a negative pregnancy test" kept as
    ``female``, or an age in an "or") is not met on that part: the notes decide the rest, and with no answer from
    them the line stays unknown, never met and never excluded. An exclusion keeps D-98 (the compiler's
    ``qualifier_dropped`` rule keeps an age-or-sex-alone exclusion from running)."""
    return not (c.class_ == "mixed" and c.kind == "inclusion" and met_on_demographics(c.logic))


def class_split(criteria: list[CriterionIR]) -> dict[str, int]:
    """How many active (not rejected) inclusion/exclusion criteria each class checks (D-101)."""
    out = {"structured": 0, "mixed": 0, "note": 0, "human": 0}
    for c in criteria:
        if c.kind in ("inclusion", "exclusion") and not (c.review and c.review.status == "rejected"):
            out[c.class_] = out.get(c.class_, 0) + 1
    return out


def human_heavy(split: dict[str, int]) -> bool:
    """True when at least half of the criteria are left to a person: the box would do little of the screening."""
    n = sum(split.values())
    return n > 0 and split.get("human", 0) * 2 >= n


def compiled(criteria: list[CriterionIR]) -> list[CriterionIR]:
    """Class ``structured`` and ``mixed`` criteria are compiled to CQL/SQL (note/human are judged or asked; D-32).
    A mixed criterion's compiled part is a pre-check: it decides the patient when the coded data can, and the note
    judge decides the rest (D-98)."""
    return [c for c in criteria if c.class_ in FILTERED]


def fmt_num(x: float) -> str:
    """Render a number literal identically for CQL and SQL (integers without a decimal point)."""
    if float(x).is_integer():
        return str(int(x))
    return repr(float(x))


def ident(crit_id: str) -> str:
    """SQL-safe identifier fragment for a criterion id."""
    return crit_id.replace("-", "_")
