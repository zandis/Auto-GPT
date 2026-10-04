"""COHORT (SPEC §8.3): quarterly "major criteria × count" tables per disease in the alliance schema v1, a report,
and an enrolment simulation against recruiting trials from ClinicalTrials.gov; ``COHORT MERGE`` on the alliance root
merges member tables.

* Counts come from the approved cohort ruleset's SQL at each quarter end (≤ snapshot): the population is the
  manifest's ``cohort.population_criterion``; every other criterion and each configured combination is counted inside
  it; ``n_contactable`` counts the part with an active research-contact consent (lake ``consent``, from the registry,
  D-72). Small cells are suppressed before anything leaves the box (§10.1).
* A member box sends its table to ``settings.cohort.root_address`` with the subject ``COHORT MERGE``; the root stores
  every accepted table (its own included) and returns the merged table (D-73).
* Trial simulation: the top recruiting trials for ``cohort.ctgov_condition`` (Taiwan/Japan) are compiled from their
  public eligibility text (cached by NCT id + last update), counted like FEAS and simulated (D-74). These compiles are
  never approved and are labelled as automatic.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tb_common.ruleset import Ruleset
from tb_common.smallcell import suppress
from tb_contracts import CohortTable, schema_errors

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.scenarios.review import recipients, require_approved
from orchestrator.scenarios.screen import report_meta, small_cell

COLUMNS = (
    "site_id",
    "disease",
    "quarter",
    "criterion_id",
    "criterion_label",
    "n",
    "n_contactable",
    "definition_version",
)
SCHEMA_VERSION = "alliance-v1"
ALLIANCE = "ALLIANCE"
NOT_AVAILABLE = "n/a"


# ------------------------------------------------------------------------------------------------------- quarters
def quarter_end(d: date) -> date:
    q_last_month = ((d.month - 1) // 3 + 1) * 3
    first_next = date(d.year + (q_last_month == 12), q_last_month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def completed_quarters(as_of: date, n: int) -> list[date]:
    """The last ``n`` quarter ends on or before ``as_of`` (oldest first)."""
    end = quarter_end(as_of)
    if end > as_of:
        end = quarter_end(date(end.year, end.month - 2, 1) - timedelta(days=1))
    out = [end]
    while len(out) < n:
        prev = out[-1]
        out.append(quarter_end(date(prev.year, prev.month - 2, 1) - timedelta(days=1)))
    return sorted(out)


def quarter_label(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


# --------------------------------------------------------------------------------------------------------- counts
@dataclass
class Item:
    criterion_id: str
    label: str
    pids: set[str]


def _label(rs: Ruleset, cid: str) -> str:
    c = next((x for x in rs.criteria if x.id == cid), None)
    return (c.label or c.text) if c else cid


def population_id(rs: Ruleset) -> str:
    cfg = rs.manifest.cohort
    if cfg and cfg.population_criterion:
        return cfg.population_criterion
    first = next((c for c in rs.ordered() if c.kind == "inclusion"), None)
    if first is None:
        raise StepFailed("ruleset", f"{rs.id} has no population criterion")
    return first.id


def items_at(ctx: Ctx, rs: Ruleset, index: date) -> list[Item]:
    rows = ctx.services.lake.query(rs.sql, [[index.isoformat()], None]).to_pylist()
    pop = population_id(rs)
    p_rows = [r for r in rows if r.get(f"C_{pop}") is True]
    out = [Item(pop, _label(rs, pop), {r["pid"] for r in p_rows})]
    for c in rs.ordered():
        if c.id == pop or c.class_ != "structured" or (c.review and c.review.status == "rejected"):
            continue
        out.append(Item(c.id, _label(rs, c.id), {r["pid"] for r in p_rows if r.get(f"C_{c.id}") is True}))
    for combo in (rs.manifest.cohort.combinations if rs.manifest.cohort else None) or []:
        ids = list(combo)
        out.append(
            Item(
                "+".join(ids),
                " ∧ ".join(_label(rs, i) for i in ids),
                {r["pid"] for r in p_rows if all(r.get(f"C_{i}") is True for i in ids)},
            )
        )
    return out


def contactable_pids(ctx: Ctx, index: date) -> set[str] | None:
    """Patients with an active research-contact consent at ``index``; ``None`` when the site has no registry."""
    reg = ctx.cfg.settings.registry_source
    if reg is None or reg.type == "none":
        return None
    try:
        rows = ctx.services.lake.query(
            "SELECT pid, contact_ok FROM consent WHERE status = 'active' "
            "AND (date IS NULL OR date <= CAST($1 AS DATE)) ORDER BY pid, date",
            [index.isoformat()],
        ).to_pylist()
    except Exception:  # lake without a consent table (registry never ingested)
        return None
    latest: dict[str, bool] = {}
    for r in rows:
        latest[r["pid"]] = bool(r["contact_ok"])
    return {p for p, ok in latest.items() if ok}


def table_rows(ctx: Ctx, rs: Ruleset, quarters: list[date]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Alliance rows (suppressed) and the unsuppressed population sizes kept in the box for the report."""
    site = ctx.cfg.settings.site.id
    sc = small_cell(ctx, rs)
    disease = rs.manifest.cohort.disease if rs.manifest.cohort and rs.manifest.cohort.disease else rs.id
    rows: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    for q in quarters:
        items = items_at(ctx, rs, q)
        contact = contactable_pids(ctx, q)
        raw[quarter_label(q)] = {it.criterion_id: len(it.pids) for it in items}
        for it in items:
            rows.append(
                {
                    "site_id": site,
                    "disease": disease,
                    "quarter": quarter_label(q),
                    "criterion_id": it.criterion_id,
                    "criterion_label": it.label,
                    "n": suppress(len(it.pids), sc),
                    "n_contactable": NOT_AVAILABLE if contact is None else suppress(len(it.pids & contact), sc),
                    "definition_version": f"{rs.id}@{rs.version}",
                }
            )
    return rows, raw


# ------------------------------------------------------------------------------------------------------ alliance CSV
def to_csv(rows: Iterable[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(COLUMNS), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r[k] for k in COLUMNS})
    return buf.getvalue().encode("utf-8")


def _count(v: str) -> int | str:
    v = v.strip()
    return int(v) if v.isdigit() else v


def parse_csv(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Alliance schema v1 CSV -> rows; errors name the line. The header must be exactly the v1 columns."""
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if tuple(h.strip() for h in reader.fieldnames or []) != COLUMNS:
        return [], [f"header must be {','.join(COLUMNS)}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, r in enumerate(reader, start=2):
        row = {k: (r.get(k) or "").strip() for k in COLUMNS}
        row["n"], row["n_contactable"] = _count(row["n"]), _count(row["n_contactable"])
        errs = schema_errors("cohort_table", {"schema_version": SCHEMA_VERSION, "rows": [row]})
        if errs:
            errors.extend(f"line {i}: {e.split(': ', 1)[-1]}" for e in errs)
        else:
            rows.append(row)
    if rows and len({r["site_id"] for r in rows}) != 1:
        errors.append("one file must hold one site's table")
    return rows, errors


def merge_counts(values: list[int | str], k: int) -> int | str:
    """Alliance total of site counts: plain sum, or a ``lo-hi`` range when a site cell is suppressed ``<k``."""
    lo = hi = 0
    exact = True
    for v in values:
        if isinstance(v, int):
            lo += v
            hi += v
        elif isinstance(v, str) and v.startswith("<") and v[1:].isdigit():
            exact = False
            lo += 1
            hi += int(v[1:]) - 1
        else:
            return NOT_AVAILABLE
    if exact:
        return suppress(lo, k)
    if hi < k:
        return f"<{k}"
    if lo < k:  # the total may itself be small: give only the upper bound
        return f"<{hi + 1}"
    return f"{lo}-{hi}"


def merged(rows: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Per-site rows plus one ``ALLIANCE`` row per (disease, quarter, definition, criterion); different definition
    versions are never summed together."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["disease"], r["quarter"], r["definition_version"], r["criterion_id"]), []).append(r)
    out: list[dict[str, Any]] = []
    for (disease, quarter, version, cid), members in sorted(groups.items()):
        members.sort(key=lambda r: r["site_id"])
        out.extend(members)
        out.append(
            {
                "site_id": ALLIANCE,
                "disease": disease,
                "quarter": quarter,
                "criterion_id": cid,
                "criterion_label": members[0]["criterion_label"],
                "n": merge_counts([m["n"] for m in members], k),
                "n_contactable": merge_counts([m["n_contactable"] for m in members], k),
                "definition_version": version,
            }
        )
    return out


# ------------------------------------------------------------------------------------------------------ scenarios
def run(ctx: Ctx) -> Outcome:
    if (ctx.job.ruleset or "").upper() == "MERGE":
        return run_merge(ctx)
    return run_cohort(ctx)


def run_cohort(ctx: Ctx) -> Outcome:
    from orchestrator.reports import cohort_pdf, trial_sim_xlsx
    from orchestrator.scenarios import trials

    job = ctx.job
    rs = require_approved(ctx, (job.ruleset or "").upper(), (job.options or {}).get("version"))
    if rs.manifest.kind != "cohort":
        raise StepFailed("ruleset", f"{rs.id} is a {rs.manifest.kind} ruleset; COHORT needs a cohort ruleset.")
    ctx.update(ruleset_version=rs.version)
    snapshot = ctx.services.lake.snapshot()
    if not snapshot:
        raise StepFailed("running", "The lake has no snapshot yet; run the nightly ingest first.")
    ctx.update(snapshot_date=date.fromisoformat(snapshot))
    n_quarters = int((job.options or {}).get("lookback") or 4)
    quarters = completed_quarters(min(ctx.today(), date.fromisoformat(snapshot)), max(1, min(n_quarters, 12)))
    ctx.state("running")
    rows, raw = table_rows(ctx, rs, quarters)
    table = CohortTable.model_validate({"schema_version": SCHEMA_VERSION, "rows": rows})
    site = ctx.cfg.settings.site.id
    sc = small_cell(ctx, rs)
    pop = population_id(rs)
    ctx.metrics(patients_scoped=raw[quarter_label(quarters[-1])][pop])
    if ctx.cfg.settings.cohort and ctx.cfg.settings.cohort.alliance_root:
        ctx.orch.db.cohort_store([r.model_dump(mode="json") for r in table.rows], job.job_id, f"self:{site}")
    sims = trials.simulate_for(ctx, rs, quarters[-1], snapshot)
    ctx.state("reporting")
    meta = report_meta(ctx, rs, snapshot, ctx.today())
    last = quarter_label(quarters[-1])
    stem = f"{rs.id}_{site}_{last}"
    to = recipients(rs.manifest.routing, job.requested_by)
    outputs = [
        ctx.publish(f"cohort_table_{stem}.csv", to_csv(r.model_dump(mode="json") for r in table.rows), "aggregate", to),
        ctx.publish(f"cohort_report_{stem}.pdf", cohort_pdf.render(rs, table, sims, meta), "aggregate", to),
    ]
    if sims is not None:
        outputs.append(ctx.publish(f"trial_sim_{stem}.xlsx", trial_sim_xlsx.render(sims, meta), "aggregate", to))
    head = [r for r in table.rows if r.quarter == last]
    text = (
        f"COHORT **{rs.id} v{rs.version}** at {site}, {quarter_label(quarters[0])}–{last} "
        f"(snapshot {snapshot}): population {head[0].n} in {last}; {len(head) - 1} criteria/combinations counted; "
        f"small cells < {sc} suppressed."
        + (f" Trial simulation: {len(sims.rows)} recruiting trials." if sims is not None else "")
    )
    deliveries = [Delivery(to=to, outputs=outputs, body_md=text, routing=rs.manifest.routing)]
    cs = ctx.cfg.settings.cohort
    if cs and cs.root_address and not cs.alliance_root:
        deliveries.append(
            Delivery(
                to=[cs.root_address],
                outputs=[outputs[0]],
                subject=f"COHORT MERGE -- {site} {rs.id} {last}",
                body_md=f"Alliance table v1 from {site}: {rs.id} v{rs.version}, {quarter_label(quarters[0])}–{last}.",
                kind="cohort-share",
                routing=rs.manifest.routing,
            )
        )
    return Outcome(summary_md=text, deliveries=deliveries)


def run_merge(ctx: Ctx) -> Outcome:
    job = ctx.job
    cs = ctx.cfg.settings.cohort
    if not cs or not cs.alliance_root:
        raise StepFailed("received", "This box is not the alliance root; COHORT MERGE is refused.")
    files = [f for f in job.inputs or [] if f.filename.lower().endswith(".csv")]
    if not files:
        raise StepFailed("received", "Attach one or more cohort_table_*.csv files (alliance schema v1).")
    ctx.state("running")
    accepted: list[dict[str, Any]] = []
    problems: list[str] = []
    for f in files:
        rows, errors = parse_csv(ctx.input_bytes(f))
        if errors:
            problems.extend(f"{f.filename}: {e}" for e in errors[:10])
            continue
        accepted.extend(rows)
        ctx.orch.db.cohort_store(rows, job.job_id, job.requested_by)
    if not accepted:
        raise StepFailed("running", "No valid alliance table:\n" + "\n".join(f"- {p}" for p in problems[:20]))
    keys = sorted({(r["disease"], r["quarter"]) for r in accepted})
    stored = [r for d, q in keys for r in ctx.orch.db.cohort_rows(d, q)]
    sc = int((ctx.cfg.settings.thresholds.small_cell if ctx.cfg.settings.thresholds else None) or 5)
    table = merged(stored, sc)
    ctx.state("reporting")
    sites = sorted({r["site_id"] for r in stored})
    names = "_".join(sorted({d for d, _ in keys}))
    last = max(q for _, q in keys)
    to = sorted({job.requested_by, *([ctx.cfg.settings.site.contact] if ctx.cfg.settings.site.contact else [])})
    out = ctx.publish(f"cohort_merged_{names}_{last}.csv", to_csv(table), "aggregate", to)
    versions = sorted({r["definition_version"] for r in stored})
    text = (
        f"COHORT MERGE: {len(accepted)} rows accepted from {len(files) - len({p.split(':')[0] for p in problems})} "
        f"file(s); merged table for {', '.join(f'{d} {q}' for d, q in keys)} over {len(sites)} sites "
        f"({', '.join(sites)}); definitions {', '.join(versions)}."
        + ("\n\nRejected:\n" + "\n".join(f"- {p}" for p in problems[:20]) if problems else "")
    )
    return Outcome(summary_md=text, deliveries=[Delivery(to=to, outputs=[out], body_md=text)])


def load_draft(store_bytes: bytes) -> Ruleset:
    """A compiler draft zip (manifest, IR, SQL, ...) as a Ruleset (trial simulation only; never approved)."""
    tmp = Path(tempfile.mkdtemp(prefix="tb-trial-"))
    with zipfile.ZipFile(io.BytesIO(store_bytes)) as z:
        for name in z.namelist():
            if name.endswith("/") or ".." in name or name.startswith("/"):
                continue
            target = tmp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
    roots = [p.parent for p in tmp.rglob("manifest.yaml")]
    if not roots:
        raise StepFailed("running", "draft package has no manifest.yaml")
    return Ruleset.load(roots[0])


def dumps(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
