"""The SQL of the v3 qualifiers that :func:`criteria_compiler.semantics.lower` keeps beside each lowered atom.

The optional OMOP relations must be visible in the same SQL snapshot as the
flattened tables. Record and person maps are the existing export mappings;
duplicate mappings fail as scalar subqueries rather than multiplying evidence.
"""

from pathlib import Path
from string import Template
from typing import Any

from tb_contracts.criterion_ir import Atom as Atom3

from criteria_compiler.semantics import Window, fmt_num


def sql_template(name: str, **parts: str) -> str:
    """Internal SQL templates: identifiers come from code, values are SQL literals."""
    return Template(Path(__file__).with_name(name + ".sql").read_text(encoding="utf-8").strip()).substitute(parts)


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
        "supply": "m.days_supply",
        "start_date": "m.drug_exposure_start_date",
        "end_date": "m.drug_exposure_end_date",
    }
    join = detail("drug_exposure", "x", "mid", fields)
    checks, missing = [], []
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
