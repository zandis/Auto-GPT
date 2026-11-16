"""IR -> CQL (SPEC §6.2). Template-based and deterministic: same IR + ValueSets -> byte-identical library text.

Naming inside the library: ``C_<ID>`` (Boolean or null) and ``E_<ID>`` (List<String> "resourceId|yyyy-mm-dd") per
criterion; helper definitions ``Q_/L_/V_/D_/A_/EA_<ID>_<n>`` per atom ``n`` (pre-order).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from tb_common.derived import (
    ASDAS,
    CODES,
    COMPONENTS,
    DAS28,
    DOMAIN,
    EGFR,
    EGFR_JSN,
    EGFR_MIN_AGE,
    LOINC,
    RANGE,
    SAME_VISIT,
    SCORE,
    UNIT_OF_SCORE_ITEM,
    UNITLESS,
    UNITS,
)
from tb_common.fhir import library_name
from tb_common.labunit import ANALYTES, DIGITS, UNITLESS_KEYS, conversion, key, scale_arms
from tb_contracts import Atom, BoolExpr, CriterionIR

from criteria_compiler.semantics import (
    UNBOUNDED_PAST,
    CompileError,
    Kind,
    Window,
    atoms,
    check_bool,
    compiled,
    fmt_num,
    kind,
    window,
)
from criteria_compiler.terminology.mapper import ValueSets

TEMPLATES = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False
)
CS_NAMES = {LOINC: "LOINC", SCORE: "TBSCORE"}
YJ_SHAPE = "[0-9]{7}[A-Z][0-9A-Z]{4}"  # a 12-character YJ code (T-610), as compile_sql's YJ_STEM_OF reads it
# resource type and coding list of a presence atom whose ValueSet is a code-prefix grouper (D-113 families)
FAMILY_CODINGS = {
    "condition": ("Condition", "X.code.coding"),
    "medication": ("MedicationRequest", "(X.medication as FHIR.CodeableConcept).coding"),
    "procedure": ("Procedure", "X.code.coding"),
    "report": ("DiagnosticReport", "X.code.coding"),
    "observation": ("Observation", "X.code.coding"),
}


def _cql_dec(x: float) -> str:
    """A CQL Decimal literal (at most 8 decimal places)."""
    s = f"{x:.8f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def render_common() -> str:
    units = [
        (
            comp,
            (
                target,
                [(u, _cql_dec(f)) for u, f in sorted(factors.items())],
                tuple(_cql_dec(x) for x in RANGE[comp]) if comp in RANGE else None,
            ),
        )
        for comp, (target, factors) in sorted(UNITS.items())
    ]
    unitless = [
        (comp, ", ".join(f"'{u}'" for u in sorted(UNIT_OF_SCORE_ITEM.get(comp, UNITLESS))))
        for comp in sorted(CODES)
        if comp not in UNITS
    ]
    return _env.get_template("TB_Common.cql.j2").render(
        egfr=EGFR, jsn=EGFR_JSN, das=DAS28, asdas=ASDAS, units=units, unitless=unitless, min_age=EGFR_MIN_AGE
    )


def domain_expr(comp: str, conv: str) -> str:
    """D-275, the CQL twin of the SQL ``domain_sql``: the converted value when ``tb_common.derived.DOMAIN`` allows it,
    else null (a null value fails every comparison, so it stays null; CQL decimals are always finite)."""
    lo, hi, lo_allowed = DOMAIN.get(comp, (float("-inf"), float("inf"), True))
    conds = []
    if lo != float("-inf"):
        conds.append(f"{conv} {'>=' if lo_allowed else '>'} {_cql_dec(lo)}")
    if hi != float("inf"):
        conds.append(f"{conv} <= {_cql_dec(hi)}")
    if not conds:
        return conv
    return f"if {' and '.join(conds)} then {conv} else null"


def q(name: str) -> str:
    return '"' + name.replace('"', '\\"') + '"'


def date_expr(days: int) -> str:
    if days == 0:
        return "IndexDate"
    return f"IndexDate - {abs(days)} days" if days < 0 else f"IndexDate + {days} days"


def win_expr(w: Window) -> str:
    lo = f"@{UNBOUNDED_PAST}" if w.from_days is None else date_expr(w.from_days)
    return f"Interval[{lo}, {date_expr(w.to_days)}]"


def unit_function(name: str, want: str | None) -> str:
    """D-275 (review S-1), the CQL twin of ``tb_common.labunit.value_sql``: a function giving a Quantity's number
    in the criterion's unit, or null when its unit is another one that cannot be converted (or is missing).
    ``Cd`` is the coding list of the observation (or component) the Quantity belongs to."""
    need = key(want)
    have = "TB.UnitKey(Q)"
    if need in UNITLESS_KEYS:
        allowed = ", ".join("'" + k + "'" for k in sorted(UNITLESS_KEYS))
        arms = [f"when {have} in {{ {allowed} }} then Q.value.value"]
    else:
        esc = need.replace("\\", "\\\\").replace("'", "\\'")
        arms = [f"when {have} = '{esc}' then Q.value.value"]
        for (sy, cd), table in sorted(ANALYTES.items()):
            for u in sorted(table):
                conv = conversion(u, need, sy, cd)
                if conv is not None:  # the factor as an exact decimal, the value rounded as in SQL (review F2, F4)
                    op, k = conv
                    arms.append(
                        f"when exists (Cd C where C.system.value = '{sy}' and C.code.value = '{cd}') "
                        f"and {have} = '{u}' then Round(Q.value.value {op} {_cql_dec(k)}, {DIGITS})"
                    )
        for u, op, k in scale_arms(need):  # units of one kind, any analyte, after the analytes' own (D-418)
            esc_u = u.replace("\\", "\\\\").replace("'", "\\'")
            arms.append(f"when {have} = '{esc_u}' then Round(Q.value.value {op} {_cql_dec(k)}, {DIGITS})")
    body = "\n    ".join(arms)
    return f"define function {q(name)}(Q FHIR.Quantity, Cd List<FHIR.Coding>):\n  case\n    {body}\n    else null end"


# T-619a (CR-001, CR-098, CR-115), as the SQL's ``_CENSORED`` (D-142): a censored result ("<0.3": at most the bound,
# ">1000": at least) decides a comparison only when every value on that side of the bound gives the same answer, else
# null. The bound counts as reachable, so the answer can only stay unknown, never be wrong. (side, op) -> (when, answer)
_CENSORED: dict[tuple[str, str], tuple[str, str]] = {
    ("below", ">="): ("{x} < {n}", "false"),
    ("below", ">"): ("{x} <= {n}", "false"),
    ("below", "<"): ("{x} < {n}", "true"),
    ("below", "<="): ("{x} <= {n}", "true"),
    ("below", "="): ("{x} < {n}", "false"),
    ("below", "between"): ("{x} < {n}", "false"),
    ("above", ">="): ("{x} >= {n}", "true"),
    ("above", ">"): ("{x} > {n}", "true"),
    ("above", "<"): ("{x} >= {n}", "false"),
    ("above", "<="): ("{x} > {n}", "false"),
    ("above", "="): ("{x} > {n}", "false"),
    ("above", "between"): ("{x} > {n2}", "false"),
}


def cmp_expr(atom: Atom, value: str, code: str | None = None, censor: str | None = None) -> str:
    """The comparison of one value. ``censor``: the CQL of the result's ``Quantity.comparator`` (T-619a); with it a
    censored result is compared as the SQL compares ``value_cmp``."""
    v = atom.value
    assert v is not None and v.op is not None
    if v.op == "in":
        codes = ", ".join("'" + c + "'" for c in v.codes or [])
        return f"({code} in {{ {codes} }})"
    if v.op == "between":
        assert v.num is not None and v.num2 is not None
        plain = f"({value} >= {fmt_num(v.num)} and {value} <= {fmt_num(v.num2)})"
    else:
        assert v.num is not None
        plain = f"({value} {v.op} {fmt_num(v.num)})"
    if censor is None:
        return plain
    n, n2 = fmt_num(v.num), fmt_num(v.num2) if v.num2 is not None else ""
    side = {}
    for s in ("below", "above"):
        cond, answer = _CENSORED[(s, v.op)]
        side[s] = f"if {cond.format(x=value, n=n, n2=n2)} then {answer} else null"
    # no comparator, or one the lake does not read as censored ("ad"): the plain comparison, as the SQL
    return (
        f"(case when {censor} in {{ '<', '<=' }} then ({side['below']}) "
        f"when {censor} in {{ '>', '>=' }} then ({side['above']}) else {plain} end)"
    )


@dataclass
class _Ctx:
    vs: ValueSets
    codes_used: dict[str, tuple[str, str]]


class CqlGenerator:
    def __init__(self, ruleset: str, version: str, valuesets: ValueSets, lookback_months: int = 36) -> None:
        self.ruleset = ruleset
        self.version = version
        self.vs = valuesets
        self.lookback = lookback_months
        self.library = library_name(ruleset, version)
        self.library_version = version

    # ------------------------------------------------------------------ atoms
    def _presence(self, cid: str, n: int, atom: Atom, w: Window) -> tuple[list[str], str, str]:
        p = f"{cid}_{n}"
        vs = q(atom.valueset)
        win = win_expr(w)
        match atom.domain:
            case "condition":
                date = "date from Coalesce(X.onset as FHIR.dateTime, X.recordedDate)"
                retrieve = f"[Condition: {vs}] X"
            case "medication":
                date = "date from X.authoredOn"
                retrieve = f"[MedicationRequest: {vs}] X"
                stems = self.vs.yj_stems(atom.valueset)
                if stems:  # T-610: a YJ code whose ingredient stem the ValueSet lists matches, as in the SQL
                    listed = ", ".join(f"'{st}'" for st in stems)
                    retrieve = (
                        f"[MedicationRequest] X where exists (({FAMILY_CODINGS['medication'][1]}) Cd where "
                        f"FHIRHelpers.ToCode(Cd) in {vs} or (Matches(Cd.code.value, '{YJ_SHAPE}') and "
                        f"Substring(Cd.code.value, 0, 7) in {{{listed}}})) and"
                    )
            case "procedure":
                date = "date from (X.performed as FHIR.dateTime)"
                retrieve = f"[Procedure: {vs}] X"
            case "report":
                date = "date from (X.effective as FHIR.dateTime)"
                retrieve = f"[DiagnosticReport: {vs}] X"
            case "observation":
                date = "TB.ObsDate(X)"
                retrieve = f"[Observation: {vs}] X"
            case "encounter":
                date = "date from X.period.start"
                retrieve = f"[Encounter] X where X.serviceType in {vs} and"
            case "claim":
                date = "date from X.created"
                retrieve = f"[Claim] X where exists (X.item I where I.productOrService in {vs}) and"
            case _:
                raise CompileError(f"unsupported domain {atom.domain}")
        joiner = " " if retrieve.endswith(" and") else " where "
        un, qn = q("U_" + p), q("Q_" + p)
        # D-917, as the SQL: a condition atom with ``clinical_status`` counts a row whose status (its first coded
        # clinicalStatus, as the lake keeps it) is listed or missing; a row of another status only makes it unknown
        statuses = atom.clinical_status if atom.domain == "condition" else None
        status = "Lower(First(X.clinicalStatus.coding C where C.code.value is not null return C.code.value))"
        listed_st = ", ".join(f"'{st}'" for st in statuses or ())
        counted = f" and ({status} is null or {status} in {{ {listed_st} }})" if statuses else ""
        # an undated record cannot be placed in the window: unknown where the dated ones do not settle the atom, as
        # the SQL says (scenario run DUMP-01)
        defs = [
            f"define {qn}:\n  {retrieve}{joiner}{date} in {win}{counted}",
            f"define {un}:\n  {retrieve}{joiner}{date} is null",
        ]
        quant = atom.quantifier or "any"
        unknown = [un]
        if statuses:
            sn = q("S_" + p)
            defs.append(
                f"define {sn}:\n  {retrieve}{joiner}{date} in {win} and {status} is not null "
                f"and not ({status} in {{ {listed_st} }})"
            )
            unknown.append(sn)
        if quant == "count>=":
            settled = f"Count({qn}) >= {atom.count}"
            reach = " + ".join([f"Count({qn})", *(f"Count({x})" for x in unknown)]) + f" >= {atom.count}"
        else:
            settled, reach = f"exists ({qn})", " or ".join(f"exists ({x})" for x in unknown)
        hit, miss = ("false", "true") if quant == "none" else ("true", "false")
        a = f"if {settled} then {hit} else if {reach} then null as Boolean else {miss}"
        ev = f"{qn} X return X.id + '|' + ToString({date})"
        fams = self.vs.families(atom.valueset)
        if not fams:
            return defs, a, ev
        # D-113 in CQL too (review F3, D-130): when the listed codes do not settle the atom but a record in the window
        # is coded inside the grouper's family and outside its list, the answer is null (unknown), as the SQL says
        if atom.domain not in FAMILY_CODINGS:
            raise CompileError(f"code families are not supported on {atom.domain} atoms")
        on = q("O_" + p)
        in_family = " or ".join(
            f"(Cd.system.value = '{sy}' and StartsWith(Cd.code.value, '{pre}'))" for sy, pre in sorted(set(fams))
        )
        for name, when in ((on, f"{date} in {win}"), (q("UO_" + p), f"{date} is null")):
            defs.append(
                f"define {name}:\n  [{FAMILY_CODINGS[atom.domain][0]}] X where ({when})\n"
                f"    and exists (({FAMILY_CODINGS[atom.domain][1]}) Cd where ({in_family}) "
                f"and not (FHIRHelpers.ToCode(Cd) in {vs}))"
            )
        unknown.append(q("UO_" + p))
        if quant == "count>=":
            reach = " + ".join([f"Count({qn})", *(f"Count({x})" for x in unknown)]) + f" >= {atom.count}"
        else:
            reach = " or ".join(f"exists ({x})" for x in unknown)
        a = f"if {settled} then {hit} else if exists ({on}) then null as Boolean else if {reach} then null as Boolean else {miss}"
        ev = f"if exists ({qn}) then ({ev}) else ({on} X return X.id + '|' + ToString({date}))"
        return defs, a, ev

    def _obs_value(self, cid: str, n: int, atom: Atom, w: Window) -> tuple[list[str], str, str]:
        p = f"{cid}_{n}"
        vsname = q(atom.valueset)
        win = win_expr(w)
        comp = self.vs.is_component_set(atom.valueset)
        numeric = atom.value is not None and atom.value.op != "in"
        nf = q("N_" + p)  # the value in the criterion's unit (D-275)
        # SCR-03: undated as the lake reads it (``lake.flatten`` ``effective``: a dateTime, else an instant, else a
        # period's start). A result dated by an instant or a period only is dated in the SQL, never undated here
        no_date = "(X.effective is null or (X.effective is FHIR.Period and (X.effective as FHIR.Period).start is null))"
        if comp:
            retrieve = (
                f"[Observation] X where TB.ObsDate(X) in {win} and exists (X.component C where C.code in {vsname})"
            )
            undated = f"[Observation] X where {no_date} and exists (X.component C where C.code in {vsname})"

            def val(o: str) -> str:
                c1 = f"First({o}.component C where C.code in {vsname})"
                return f"{nf}({c1}.value as FHIR.Quantity, {c1}.code.coding)"

            def code(o: str) -> str:
                return f"First(({o}.component C where C.code in {vsname}).value as FHIR.CodeableConcept).coding"

            def censor(o: str) -> str:
                return f"(First({o}.component C where C.code in {vsname}).value as FHIR.Quantity).comparator.value"
        else:
            retrieve = f"[Observation: {vsname}] X where TB.ObsDate(X) in {win}"
            undated = f"[Observation: {vsname}] X where {no_date}"

            def val(o: str) -> str:
                return f"{nf}({o}.value as FHIR.Quantity, {o}.code.coding)"

            def code(o: str) -> str:
                return f"TB.ObsCode({o})"

            def censor(o: str) -> str:
                return f"({o}.value as FHIR.Quantity).comparator.value"

        if comp and atom.value is not None and atom.value.op == "in":
            raise CompileError("coded comparisons on panel components are not supported")
        # SCR-03, as the SQL: an undated record cannot be placed in the window (nor before or after the dated ones);
        # the dated records' answer stands only when every undated one leaves it the same, else null (unknown)
        defs = [f"define {q('Q_' + p)}:\n  {retrieve}", f"define {q('U_' + p)}:\n  {undated}"]
        if numeric:
            assert atom.value is not None
            defs.insert(0, unit_function("N_" + p, atom.value.unit))
        quant = atom.quantifier or "any"
        qn, un = q("Q_" + p), q("U_" + p)
        c = cmp_expr(atom, val("X"), code("X"), censor("X"))
        may_true = f"exists ({un} X where ({c}) is not false)"  # an undated record that may meet the comparison
        may_false = f"exists ({un} X where ({c}) is not true)"  # one that may fail it
        if quant == "latest":
            defs.append(f"define {q('L_' + p)}:\n  TB.LatestObs({qn})")
            ln = q("L_" + p)
            cl = cmp_expr(atom, val(ln), code(ln), censor(ln))
            a = (
                f"if {ln} is null then null as Boolean else if ({cl}) is true and not {may_false} then true "
                f"else if ({cl}) is false and not {may_true} then false else null as Boolean"
            )
            ev = f"if {ln} is null then List<String>{{}} else {{ {ln}.id + '|' + ToString(TB.ObsDate({ln})) }}"
            return defs, a, ev
        # D-142 (review B-01), as the SQL: a record without a readable number leaves the answer unknown unless the
        # readable records settle it; it never counts as a failed test
        unread = f"exists ({qn} X where ({c}) is null)"
        if quant == "any":
            a = (
                f"if not exists ({qn}) then null else if exists ({qn} X where {c}) then true else if {unread} then null "
                f"else if {may_true} then null else false"
            )
        elif quant == "none":
            a = (
                f"if not exists ({qn}) then null else if exists ({qn} X where {c}) then false else if {unread} then null "
                f"else if {may_true} then null else true"
            )
        elif quant == "all":
            a = (
                f"if not exists ({qn}) then null else if exists ({qn} X where not ({c})) then false "
                f"else if {unread} then null else if {may_false} then null else true"
            )
        elif quant == "count>=":
            met = f"Count({qn} X where {c})"
            a = (
                f"if not exists ({qn}) then null else if {met} >= {atom.count} then true "
                f"else if {met} + Count({qn} X where ({c}) is null) + Count({un} X where ({c}) is not false) "
                f">= {atom.count} then null else false"
            )
        else:
            raise CompileError(f"quantifier {quant}")
        ev = f"{qn} X where {c} return X.id + '|' + ToString(TB.ObsDate(X))"
        return defs, a, ev

    def _code_name(self, ctx: _Ctx, comp: str) -> str:
        system, code = CODES[comp]
        name = f"TB code {comp}"
        ctx.codes_used[name] = (system, code)
        return name

    def _derived(self, ctx: _Ctx, cid: str, n: int, atom: Atom, w: Window) -> tuple[list[str], str, str]:
        p = f"{cid}_{n}"
        win = win_expr(w)
        defs: list[str] = []
        latest: dict[str, str] = {}
        assert atom.derived is not None
        if atom.derived not in COMPONENTS:
            raise CompileError(f"derived {atom.derived}")
        rule = SAME_VISIT.get(atom.derived)  # D-149: one visit, anchored on the newest anchor component
        comps = COMPONENTS[atom.derived]
        order = [rule[0], *[c for c in comps if c != rule[0]]] if rule else list(comps)
        for comp in order:
            cn = self._code_name(ctx, comp)
            qname = f"Q_{p}_{comp}"
            near = ""
            if rule is not None and comp != rule[0]:
                near = f" and TB.SameVisit(X, {q(f'L_{p}_{rule[0]}')}, {int(rule[1][comp])})"
            defs.append(f"define {q(qname)}:\n  [Observation: {q(cn)}] X where TB.ObsDate(X) in {win}{near}")
            defs.append(f"define {q(f'L_{p}_{comp}')}:\n  TB.LatestObs({q(qname)})")
            # in the formula's unit (D-149), and only a value possible for the component (D-275)
            conv = f"TB.{q('Conv_' + comp)}({q(f'L_{p}_{comp}')})"
            defs.append(f"define {q(f'K_{p}_{comp}')}:\n  {domain_expr(comp, conv)}")
            latest[comp] = q(f"K_{p}_{comp}")
        match atom.derived:
            case "bmi":
                value = f"TB.BMI({latest['weight']}, {latest['height']})"
            case "egfr" | "egfr_ckd_epi":
                value = f"TB.EGFR2021({latest['creatinine']}, TB.AgeAt(Patient, IndexDate), TB.IsFemale(Patient))"
            case "egfr_jsn":
                value = f"TB.EGFRJSN({latest['creatinine']}, TB.AgeAt(Patient, IndexDate), TB.IsFemale(Patient))"
            case "das28":
                has_esr = f"{q(f'L_{p}_esr')} is not null"
                value = (
                    f"TB.DAS28({latest['tjc28']}, {latest['sjc28']}, {latest['ptga']}, {has_esr}, {latest['esr']}, "
                    f"{latest['crp']})"
                )
            case "cdai":  # D-189
                value = f"TB.CDAI({latest['tjc28']}, {latest['sjc28']}, {latest['ptga10']}, {latest['evga']})"
            case "sdai":  # D-189: the CRP in mg/L from Conv_crp; TB.SDAI takes it to mg/dL
                value = (
                    f"TB.SDAI({latest['tjc28']}, {latest['sjc28']}, {latest['ptga10']}, {latest['evga']}, "
                    f"{latest['crp']})"
                )
            case "basdai":
                value = "TB.BASDAI(" + ", ".join(latest[f"basdai_q{i}"] for i in range(1, 7)) + ")"
            case "asdas":
                value = (
                    f"TB.ASDAS({latest['basdai_q2']}, {latest['basdai_q6']}, {latest['ptga']}, "
                    f"{latest['basdai_q3']}, {latest['crp']})"
                )
            case _:
                raise CompileError(f"derived {atom.derived}")
        defs.append(f"define {q('V_' + p)}:\n  {value}")
        vn = q("V_" + p)
        a = cmp_expr(atom, vn) if atom.value is not None else f"if {vn} is null then null else true"
        parts = [f"{q(f'L_{p}_{comp}')}" for comp in COMPONENTS[atom.derived]]
        ev = (
            "Flatten({ "
            + ", ".join(
                f"if {x} is null then List<String>{{}} else {{ {x}.id + '|' + ToString(TB.ObsDate({x})) }}"
                for x in parts
            )
            + " })"
        )
        return defs, a, ev

    def _med_duration(self, cid: str, n: int, atom: Atom, w: Window) -> tuple[list[str], str, str]:
        p = f"{cid}_{n}"
        assert atom.duration is not None and atom.duration.min_days is not None
        gap = 30 if atom.duration.gap_days is None else atom.duration.gap_days
        lo = f"@{UNBOUNDED_PAST}" if w.from_days is None else date_expr(w.from_days)
        hi = date_expr(w.to_days)
        qn, pn, dn, on = q("Q_" + p), q("P_" + p), q("D_" + p), q("O_" + p)
        start = "Coalesce(date from X.dispenseRequest.validityPeriod.start, date from X.authoredOn)"
        defs = [
            f"define {qn}:\n  [MedicationRequest: {q(atom.valueset)}] X",
            (
                f"define {pn}:\n  {qn} X\n    let s: Max({{ Coalesce(date from start of "
                f"FHIRHelpers.ToInterval(X.dispenseRequest.validityPeriod), date from X.authoredOn), {lo} }}),\n"
                f"        e: Min({{ Coalesce(date from end of FHIRHelpers.ToInterval(X.dispenseRequest.validityPeriod), "
                f"date from start of FHIRHelpers.ToInterval(X.dispenseRequest.validityPeriod), date from X.authoredOn), "
                f"{hi} }})\n    where Coalesce(date from start of FHIRHelpers.ToInterval(X.dispenseRequest.validityPeriod), "
                f"date from X.authoredOn) is not null and s <= e\n    return Interval[s, e]"
            ),
            (
                f"define {dn}:\n  Coalesce(Max((collapse ({pn} I return Interval[start of I, end of I + {gap} days]) "
                f"per day) J\n    return (days between start of J and (end of J - {gap} days)) + 1), 0)"
            ),
            # D-275 (review S-9), as the SQL: an order with no end date ran for an unknown time and one with no
            # date cannot be placed; where the dated periods do not reach min_days the answer is null (unknown)
            (
                f"define {on}:\n  {qn} X\n    where {start} is null\n"
                f"      or (X.dispenseRequest.validityPeriod.end is null and {start} <= {hi})"
            ),
        ]
        a = f"if {dn} >= {atom.duration.min_days} then true else if exists ({on}) then null as Boolean else false"
        ev = f"{qn} X return X.id + '|' + ToString(date from X.authoredOn)"
        return defs, a, ev

    def _demographic(self, atom: Atom) -> tuple[list[str], str, str]:
        conds = []
        if atom.age is not None:
            if atom.age.min is not None:
                conds.append(f"TB.AgeAt(Patient, IndexDate) >= {fmt_num(atom.age.min)}")
            if atom.age.max is not None:
                conds.append(f"TB.AgeAt(Patient, IndexDate) <= {fmt_num(atom.age.max)}")
        if atom.sex is not None:
            # D-275 (review S-5), as the SQL: other / unknown is null, not "not female"
            conds.append(
                f"(if Patient.gender.value in {{ 'male', 'female' }} then Patient.gender.value = '{atom.sex}' "
                f"else null)"
            )
        return [], "(" + " and ".join(conds) + ")", "List<String>{}"

    # ------------------------------------------------------------------ criteria
    def _atom(self, ctx: _Ctx, cid: str, n: int, atom: Atom) -> tuple[list[str], str, str]:
        k = kind(atom)
        w = window(atom)
        if k is Kind.PRESENCE:
            return self._presence(cid, n, atom, w)
        if k is Kind.OBS_VALUE:
            return self._obs_value(cid, n, atom, w)
        if k is Kind.DERIVED:
            return self._derived(ctx, cid, n, atom, w)
        if k is Kind.MED_DURATION:
            return self._med_duration(cid, n, atom, w)
        return self._demographic(atom)

    def _bool(self, expr: Atom | BoolExpr, names: dict[int, str]) -> str:
        if isinstance(expr, Atom):
            return names[id(expr)]
        parts = [self._bool(a, names) for a in expr.args]
        if expr.op == "not":
            return f"(not {parts[0]})"
        return "(" + f" {expr.op} ".join(parts) + ")"

    def criterion_defines(self, ctx: _Ctx, c: CriterionIR) -> list[str]:
        check_bool(c.logic)
        out: list[str] = []
        names: dict[int, str] = {}
        evs: list[str] = []
        for n, atom in enumerate(atoms(c.logic), start=1):
            defs, a, ev = self._atom(ctx, c.id, n, atom)
            out.extend(defs)
            aname = f"A_{c.id}_{n}"
            out.append(f"define {q(aname)}:\n  {a}")
            out.append(f"define {q('EA_' + c.id + '_' + str(n))}:\n  {ev}")
            names[id(atom)] = q(aname)
            evs.append(q(f"EA_{c.id}_{n}"))
        out.append(
            f"/* {c.id} ({c.kind}): {c.text.strip()[:160].replace('*/', '* /')} */\n"
            f"define {q('C_' + c.id)}:\n  {self._bool(c.logic, names)}"
        )
        out.append(f"define {q('E_' + c.id)}:\n  Flatten({{ {', '.join(evs)} }})")
        return out

    def render(self, criteria: list[CriterionIR]) -> str:
        """Library text whose version is ``<semver>-b<sha8 of content>`` (HAPI CR caches compiled libraries by
        name + version, so any content change must change the version)."""
        body = self._render(criteria, "__VERSION__")
        build = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
        self.library_version = f"{self.version}-b{build}"
        return body.replace("__VERSION__", self.library_version)

    def _render(self, criteria: list[CriterionIR], version: str) -> str:
        ctx = _Ctx(self.vs, {})
        defines: list[str] = []
        used_vs: set[str] = set()
        for c in compiled(criteria):
            defines.extend(self.criterion_defines(ctx, c))
            for a in atoms(c.logic):
                if a.domain != "demographic" and a.derived is None:
                    used_vs.add(a.valueset)
        codesystems = sorted({system for system, _ in ctx.codes_used.values()})
        return _env.get_template("library.cql.j2").render(
            library=self.library,
            ruleset=self.ruleset,
            version=version,
            lookback=self.lookback,
            codesystems=[{"name": CS_NAMES[s], "url": s} for s in codesystems],
            codes=[
                {"name": name, "code": code, "cs": CS_NAMES[system]}
                for name, (system, code) in sorted(ctx.codes_used.items())
            ],
            valuesets=[{"name": v, "url": self.vs.url(v), "version": self.vs.version(v)} for v in sorted(used_vs)],
            defines=defines,
        )

    @staticmethod
    def expression_names(criteria: list[CriterionIR]) -> list[str]:
        return [f"{p}_{c.id}" for c in compiled(criteria) for p in ("C", "E")]
