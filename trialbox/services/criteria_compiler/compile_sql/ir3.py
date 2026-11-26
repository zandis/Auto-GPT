"""Lower v3 logic into the existing SQL assembly, retaining supported qualifiers.

The optional OMOP relations must be visible in the same SQL snapshot as the
flattened tables. Record and person maps are the existing export mappings;
duplicate mappings fail as scalar subqueries rather than multiplying evidence.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

from tb_contracts import Atom, BoolExpr, CriterionIR
from tb_contracts.criterion_ir import Atom as Atom3
from tb_contracts.criterion_ir import CriterionIRv3, NotV1Expressible, downgrade_to_v1

from criteria_compiler.semantics import CompileError, Window, fmt_num


@dataclass(frozen=True)
class AnchoredWindow(Window):
    anchor: str = "b.index_date"


def sql_template(name: str, **parts: str) -> str:
    """Internal SQL templates: identifiers come from code, values are SQL literals."""
    return Template(Path(__file__).with_name(name + ".sql").read_text(encoding="utf-8").strip()).substitute(parts)


def lower(criterion: CriterionIR | CriterionIRv3) -> tuple[CriterionIR, dict[int, Atom3]]:
    if isinstance(criterion, CriterionIR):
        return criterion, {}
    if criterion.macros:
        raise CompileError("expand macros before SQL compilation")
    extensions: dict[int, Atom3] = {}
    by_id = {a.id: a for a in criterion.atoms}

    def walk(node: Any) -> Atom | BoolExpr:
        if not isinstance(node, str):
            return BoolExpr.model_construct(op=node.op, args=[walk(arg) for arg in node.args])
        a = by_id[node]
        if a.value_if or a.attribute or a.change or a.aggregate or a.lot or a.diagnosis_role:
            raise CompileError(f"atom {a.id}: unsupported v3 qualifier")
        data = a.model_dump(exclude_none=True)
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
            data.pop("medication")
            # Reuse observation quantifiers, including latest/all, for row predicates.
            data["domain"] = "observation"
            data["value"] = {"op": "=", "num": 1}
        shell = CriterionIRv3(
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


def detail(table: str, row: str, rid: str, fields: dict[str, str]) -> str:
    """One scalar struct from the exact source record, never a patient-wide range."""
    from .generator import lit

    key = f"r.source_record_id = {row}.{rid}"
    if table == "measurement":
        key = (
            "(CASE WHEN r.part = 0 THEN r.source_record_id ELSE "
            f"r.source_record_id || '.' || m.measurement_source_value END) = {row}.{rid}"
        )
    return sql_template(
        "detail",
        fields=", ".join(f"{name} := {expr}" for name, expr in fields.items()),
        table=table,
        table_literal=lit(table),
        row=row,
        key=key,
    )


def medication_source(gen: Any, atom: Atom3, w: Window) -> str:
    from criteria_compiler.terminology.mapper import SYSTEMS, YJ_STEM

    from .generator import YJ_STEM_OF, date_bound, lit

    med = atom.medication
    assert med is not None
    assert atom.valueset is not None
    cols = [(lit(SYSTEMS["atc"]), "x.atc"), (lit(SYSTEMS["nhi_drug"]), "x.nhi_code")]
    if gen.vs.yj_stems(atom.valueset):
        cols.append((lit(YJ_STEM), YJ_STEM_OF.format(col="x.nhi_code")))
    match = " OR ".join(gen._vs_match(atom.valueset, sc, cc) for sc, cc in cols)
    off = " OR ".join(gen._family_offlist(atom.valueset, sc, cc) for sc, cc in cols)
    fields = {
        "quantity": "m.quantity",
        "unit": "m.dose_unit_source_value",
        "route": "m.route_concept_id",
        "supply": "m.days_supply",
        "start_date": "m.drug_exposure_start_date",
        "end_date": "m.drug_exposure_end_date",
    }
    join = detail("drug_exposure", "x", "mid", fields)
    checks, missing = [], []
    if med.route:
        missing.append("d.detail.route IS NULL OR d.detail.route = 0")
        checks.append(f"CAST(d.detail.route AS VARCHAR) IN ({', '.join(lit(x) for x in med.route)})")
    if med.dose:
        dose = med.dose
        assert dose.num is not None
        missing.extend(["d.detail.quantity IS NULL", "d.detail.unit IS NULL", f"d.detail.unit <> {lit(dose.unit)}"])
        value = "d.detail.quantity"
        if dose.basis == "daily":
            missing.extend(["d.detail.supply IS NULL", "d.detail.supply <= 0"])
            value = "(d.detail.quantity / nullif(d.detail.supply, 0))"
        if dose.op == "between":
            assert dose.num2 is not None
            checks.append(f"{value} BETWEEN {fmt_num(dose.num)} AND {fmt_num(dose.num2)}")
        else:
            checks.append(f"{value} {dose.op} {fmt_num(dose.num)}")
    pred = " AND ".join(checks) or "TRUE"
    unknown = " OR ".join(missing) or "FALSE"
    family = gen.vs.families(atom.valueset)
    pred = f"CASE WHEN ({unknown}) THEN NULL ELSE ({pred}) END"
    if family:
        pred = f"CASE WHEN ({match}) THEN ({pred}) END"
        match = f"({match}) OR ({off})"
    start = "coalesce(d.detail.start_date, x.authored)"
    end = (
        "coalesce(d.detail.end_date, CASE WHEN d.detail.supply > 0 THEN "
        f"{start} + CAST(d.detail.supply AS INTEGER) - 1 END, {start})"
    )
    anchor = getattr(w, "anchor", "b.index_date")
    within = f"{start} <= {date_bound(w.to_days, anchor)}"
    uncertain = f"{start} IS NULL"
    if w.from_days is not None:
        lo = date_bound(w.from_days, anchor)
        uncertain += (
            f" OR ({start} < {lo} AND d.detail.end_date IS NULL AND (d.detail.supply IS NULL OR d.detail.supply <= 0))"
        )
        within += f" AND ({end} >= {lo} OR ({uncertain}))"
    return sql_template(
        "medication", start=start, predicate=pred, uncertain=uncertain, detail=join, match=match, within=within
    )
