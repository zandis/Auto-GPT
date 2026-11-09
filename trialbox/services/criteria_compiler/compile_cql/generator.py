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
    EGFR,
    EGFR_JSN,
    LOINC,
    SAME_VISIT,
    SCORE,
    UNIT_OF_SCORE_ITEM,
    UNITLESS,
    UNITS,
)
from tb_common.fhir import library_name
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
        (comp, (target, [(u, _cql_dec(f)) for u, f in sorted(factors.items())]))
        for comp, (target, factors) in sorted(UNITS.items())
    ]
    unitless = [
        (comp, ", ".join(f"'{u}'" for u in sorted(UNIT_OF_SCORE_ITEM.get(comp, UNITLESS))))
        for comp in sorted(CODES)
        if comp not in UNITS
    ]
    return _env.get_template("TB_Common.cql.j2").render(
        egfr=EGFR, jsn=EGFR_JSN, das=DAS28, asdas=ASDAS, units=units, unitless=unitless
    )


def q(name: str) -> str:
    return '"' + name.replace('"', '\\"') + '"'


def date_expr(days: int) -> str:
    if days == 0:
        return "IndexDate"
    return f"IndexDate - {abs(days)} days" if days < 0 else f"IndexDate + {days} days"


def win_expr(w: Window) -> str:
    lo = f"@{UNBOUNDED_PAST}" if w.from_days is None else date_expr(w.from_days)
    return f"Interval[{lo}, {date_expr(w.to_days)}]"


def cmp_expr(atom: Atom, value: str, code: str | None = None) -> str:
    v = atom.value
    assert v is not None and v.op is not None
    if v.op == "in":
        codes = ", ".join("'" + c + "'" for c in v.codes or [])
        return f"({code} in {{ {codes} }})"
    if v.op == "between":
        assert v.num is not None and v.num2 is not None
        return f"({value} >= {fmt_num(v.num)} and {value} <= {fmt_num(v.num2)})"
    assert v.num is not None
    return f"({value} {v.op} {fmt_num(v.num)})"


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
        # an undated record cannot be placed in the window: unknown where the dated ones do not settle the atom, as
        # the SQL says (scenario run DUMP-01)
        defs = [
            f"define {qn}:\n  {retrieve}{joiner}{date} in {win}",
            f"define {un}:\n  {retrieve}{joiner}{date} is null",
        ]
        quant = atom.quantifier or "any"
        if quant == "count>=":
            settled, reach = f"Count({qn}) >= {atom.count}", f"Count({qn}) + Count({un}) >= {atom.count}"
        else:
            settled, reach = f"exists ({qn})", f"exists ({un})"
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
        if quant == "count>=":
            reach = f"Count({qn}) + Count({un}) + Count({q('UO_' + p)}) >= {atom.count}"
        else:
            reach = f"exists ({un}) or exists ({q('UO_' + p)})"
        a = f"if {settled} then {hit} else if exists ({on}) then null as Boolean else if {reach} then null as Boolean else {miss}"
        ev = f"if exists ({qn}) then ({ev}) else ({on} X return X.id + '|' + ToString({date}))"
        return defs, a, ev

    def _obs_value(self, cid: str, n: int, atom: Atom, w: Window) -> tuple[list[str], str, str]:
        p = f"{cid}_{n}"
        vsname = q(atom.valueset)
        win = win_expr(w)
        comp = self.vs.is_component_set(atom.valueset)
        if comp:
            retrieve = (
                f"[Observation] X where TB.ObsDate(X) in {win} and exists (X.component C where C.code in {vsname})"
            )

            def val(o: str) -> str:
                return f"TB.CompValue(First({o}.component C where C.code in {vsname}))"

            def code(o: str) -> str:
                return f"First(({o}.component C where C.code in {vsname}).value as FHIR.CodeableConcept).coding"
        else:
            retrieve = f"[Observation: {vsname}] X where TB.ObsDate(X) in {win}"

            def val(o: str) -> str:
                return f"TB.ObsValue({o})"

            def code(o: str) -> str:
                return f"TB.ObsCode({o})"

        if comp and atom.value is not None and atom.value.op == "in":
            raise CompileError("coded comparisons on panel components are not supported")
        defs = [f"define {q('Q_' + p)}:\n  {retrieve}"]
        quant = atom.quantifier or "any"
        qn = q("Q_" + p)
        if quant == "latest":
            defs.append(f"define {q('L_' + p)}:\n  TB.LatestObs({qn})")
            ln = q("L_" + p)
            a = f"if {ln} is null then null else {cmp_expr(atom, val(ln), code(ln))}"
            ev = f"if {ln} is null then List<String>{{}} else {{ {ln}.id + '|' + ToString(TB.ObsDate({ln})) }}"
            return defs, a, ev
        c = cmp_expr(atom, val("X"), code("X"))
        # D-142 (review B-01), as the SQL: a record without a readable number leaves the answer unknown unless the
        # readable records settle it; it never counts as a failed test
        unread = f"exists ({qn} X where ({c}) is null)"
        if quant == "any":
            a = f"if not exists ({qn}) then null else if exists ({qn} X where {c}) then true else if {unread} then null else false"
        elif quant == "none":
            a = f"if not exists ({qn}) then null else if exists ({qn} X where {c}) then false else if {unread} then null else true"
        elif quant == "all":
            a = (
                f"if not exists ({qn}) then null else if exists ({qn} X where not ({c})) then false "
                f"else if {unread} then null else true"
            )
        elif quant == "count>=":
            met = f"Count({qn} X where {c})"
            a = (
                f"if not exists ({qn}) then null else if {met} >= {atom.count} then true "
                f"else if {met} + Count({qn} X where ({c}) is null) >= {atom.count} then null else false"
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
            latest[comp] = f"TB.{q('Conv_' + comp)}({q(f'L_{p}_{comp}')})"  # in the formula's unit (D-149)
        match atom.derived:
            case "bmi":
                value = f"TB.BMI({latest['weight']}, {latest['height']})"
            case "egfr" | "egfr_ckd_epi":
                value = f"TB.EGFR2021({latest['creatinine']}, AgeInYearsAt(IndexDate), TB.IsFemale(Patient))"
            case "egfr_jsn":
                value = f"TB.EGFRJSN({latest['creatinine']}, AgeInYearsAt(IndexDate), TB.IsFemale(Patient))"
            case "das28":
                has_esr = f"{q(f'L_{p}_esr')} is not null"
                value = (
                    f"TB.DAS28({latest['tjc28']}, {latest['sjc28']}, {latest['ptga']}, {has_esr}, {latest['esr']}, "
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
        qn, pn, dn = q("Q_" + p), q("P_" + p), q("D_" + p)
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
        ]
        a = f"{dn} >= {atom.duration.min_days}"
        ev = f"{qn} X return X.id + '|' + ToString(date from X.authoredOn)"
        return defs, a, ev

    def _demographic(self, atom: Atom) -> tuple[list[str], str, str]:
        conds = []
        if atom.age is not None:
            if atom.age.min is not None:
                conds.append(f"AgeInYearsAt(IndexDate) >= {fmt_num(atom.age.min)}")
            if atom.age.max is not None:
                conds.append(f"AgeInYearsAt(IndexDate) <= {fmt_num(atom.age.max)}")
        if atom.sex is not None:
            conds.append(f"(if Patient.gender is null then null else Patient.gender.value = '{atom.sex}')")
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
