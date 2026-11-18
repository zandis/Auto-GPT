"""COHORT (SPEC §8.3): quarterly "major criteria × count" tables per disease in the alliance schema v1, a report,
and an enrolment simulation against recruiting trials from ClinicalTrials.gov; ``COHORT MERGE`` on the alliance root
merges member tables.

* Counts come from the approved cohort ruleset's SQL at each quarter end (≤ snapshot): the population is the
  manifest's ``cohort.population_criterion``; every other criterion and each configured combination is counted inside
  it; ``n_contactable`` counts the part with an active research-contact consent (lake ``consent``, from the registry,
  D-72). Small cells are suppressed before anything leaves the box (§10.1).
* A member box sends its table to ``settings.cohort.root_address`` with the subject ``COHORT MERGE``; the root stores
  every accepted table (its own included) and returns the merged table (D-73).
* The table travels signed (D-144, D-1226): the member box signs it with its site key
  (``TB_ALLIANCE_SIGNING_KEY_FILE``) and sends the signature file beside the CSV; the root stores a member's table
  only when the signature holds for the key its register holds for that site (``TB_ALLIANCE_SITE_KEYS_FILE``), and
  only over an older table of the site (:mod:`tb_common.alliance`). A table stored before this is kept, marked
  unverified, and merged again only once its site sends it signed.
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
from functools import partial
from pathlib import Path
from typing import Any

from criteria_compiler.compile_sql.overlay import safe_sql
from matching.batches import query_by_patients
from tb_common import alliance
from tb_common.authz import norm
from tb_common.csvfile import for_spreadsheet
from tb_common.encoding import EncodingRefused
from tb_common.opportunity import FeedRefused
from tb_common.ruleset import Ruleset
from tb_common.smallcell import suppress
from tb_contracts import CohortTable, schema_errors

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.db import JobDB
from orchestrator.decision_context import decision_of
from orchestrator.scenarios import upload_text
from orchestrator.scenarios.review import recipients, require_approved
from orchestrator.scenarios.screen import report_meta, small_cell
from orchestrator.scheduler import require_open

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


def items_at(ctx: Ctx, rs: Ruleset, index: date, snapshot: str | None = None) -> list[Item]:
    # NEW-B-53: every patient, in batches of rows (D-748's rule)
    rows = query_by_patients(ctx.services.lake, safe_sql(rs), [index.isoformat()], None, snapshot).to_pylist()
    from matching.stored_scores import apply_rows

    from orchestrator import derive

    # D-442: the stored-row read while the flag is on, the same function as every screening path
    apply_rows(rows, rs.active(), derive.reader_for(ctx), snapshot, getattr(rs.manifest, "derived_pins", None))
    pop = population_id(rs)
    gone = decision_of(ctx).uncounted()  # D-477 (OD-8, CR-026): the register and the registry's refusals
    p_rows = [r for r in rows if r.get(f"C_{pop}") is True and r["pid"] not in gone]
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


def contactable_pids(ctx: Ctx, index: date, snapshot: str | None = None) -> set[str] | None:
    """Patients with an active research-contact consent at ``index``; ``None`` when the site has no registry.

    The patient's latest consent record on or before ``index`` decides (an undated one counts as the oldest): a
    later withdrawal (``inactive``, ``rejected``) ends an earlier ``active`` consent. A record entered in error is
    not a statement."""
    reg = ctx.cfg.settings.registry_source
    if reg is None or reg.type == "none":
        return None
    # D-477: the one consent rule, read through the job's context (D-441 MED-2: of two statements on one day the
    # not-contactable one is taken, so a same-day withdrawal or refusal is never read as contactable)
    return decision_of(ctx).contactable(index, snapshot)


def table_rows(
    ctx: Ctx, rs: Ruleset, quarters: list[date], snapshot: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Alliance rows (suppressed) and the unsuppressed population sizes kept in the box for the report."""
    site = ctx.cfg.settings.site.id
    sc = small_cell(ctx, rs)
    disease = rs.manifest.cohort.disease if rs.manifest.cohort and rs.manifest.cohort.disease else rs.id
    rows: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    for q in quarters:
        items = items_at(ctx, rs, q, snapshot)
        contact = contactable_pids(ctx, q, snapshot)
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
    """The alliance table as the file the job publishes: UTF-8 with the byte order mark, so a spreadsheet on a
    Japanese or Chinese Windows reads it as UTF-8 (:func:`tb_common.csvfile.for_spreadsheet`). The ledger's hash
    is of these bytes; :func:`parse_csv` reads the file with or without the mark."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(COLUMNS), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r[k] for k in COLUMNS})
    return for_spreadsheet(buf.getvalue())


def _count(v: str) -> int | str:
    v = v.strip()
    return int(v) if v.isdigit() else v


def parse_csv(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Alliance schema v1 CSV -> rows; errors name the line. The header must be exactly the v1 columns."""
    try:
        text = upload_text.read(data)  # UX-004: UTF-8 with or without the mark, Shift_JIS, Big5; else an error line
    except EncodingRefused as exc:
        where = f" (line {exc.line})" if exc.line is not None else ""
        return [], [f"the character set cannot be told for certain{where}: save the table as UTF-8"]
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
    require_open(job.ruleset)  # D-386 (LIFE-008): no list for a study that is not open
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
    rows, raw = table_rows(ctx, rs, quarters, snapshot)  # every count from the snapshot the report names
    table = CohortTable.model_validate({"schema_version": SCHEMA_VERSION, "rows": rows})
    site = ctx.cfg.settings.site.id
    sc = small_cell(ctx, rs)
    pop = population_id(rs)
    ctx.metrics(patients_scoped=raw[quarter_label(quarters[-1])][pop])
    if ctx.cfg.settings.cohort and ctx.cfg.settings.cohort.alliance_root:
        ctx.orch.db.cohort_store(
            [r.model_dump(mode="json") for r in table.rows], job.job_id, f"self:{site}", verified_by=alliance.OWN
        )
    sims = trials.simulate_for(ctx, rs, quarters[-1], snapshot)
    ctx.state("reporting")
    meta = report_meta(ctx, rs, snapshot, ctx.today())
    last = quarter_label(quarters[-1])
    stem = f"{rs.id}_{site}_{last}"
    to = recipients(rs.manifest.routing, job.requested_by)
    csv_bytes = to_csv(r.model_dump(mode="json") for r in table.rows)
    outputs = [
        ctx.publish(f"cohort_table_{stem}.csv", csv_bytes, "aggregate", to),
        ctx.publish(f"cohort_report_{stem}.pdf", cohort_pdf.render(rs, table, sims, meta), "aggregate", to),
    ]
    signature = sign_table(ctx, csv_bytes)
    signed = []
    if signature is not None:
        signed = [ctx.publish(f"cohort_table_{stem}{alliance.SUFFIX}", signature, "aggregate", to)]
        outputs.extend(signed)
    if sims is not None:
        outputs.append(ctx.publish(f"trial_sim_{stem}.xlsx", trial_sim_xlsx.render(sims, meta), "aggregate", to))
    head = [r for r in table.rows if r.quarter == last]
    text = (
        f"COHORT **{rs.id} v{rs.version}** at {site}, {quarter_label(quarters[0])}–{last} "
        f"(snapshot {snapshot}): population {head[0].n} in {last}; {len(head) - 1} criteria/combinations counted; "
        f"small cells < {sc} suppressed."
        + (f" Trial simulation: {len(sims.rows)} recruiting trials." if sims is not None else "")
    )
    cs = ctx.cfg.settings.cohort
    share = bool(cs and cs.root_address and not cs.alliance_root)
    if share and signature is None:  # D-1226: the root takes only signed tables; nothing unsigned is mailed to it
        text += (
            " Not sent to the alliance root: this box has no alliance signing key, and the root takes only signed "
            "tables."
        )
        share = False
    deliveries = [Delivery(to=to, outputs=outputs, body_md=text, routing=rs.manifest.routing)]
    if share and cs and cs.root_address:
        deliveries.append(
            Delivery(
                to=[cs.root_address],
                outputs=[outputs[0], *signed],  # the table and its signature
                subject=f"COHORT MERGE -- {site} {rs.id} {last}",
                body_md=f"Alliance table v1 from {site}: {rs.id} v{rs.version}, {quarter_label(quarters[0])}–{last}.",
                kind="cohort-share",
                routing=rs.manifest.routing,
            )
        )
    return Outcome(summary_md=text, deliveries=deliveries)


def sign_table(ctx: Ctx, csv_bytes: bytes) -> bytes | None:
    """The signature file of the table this box publishes (D-1226), or None when the box has no alliance signing
    key. It covers the table as the root will read it (the CSV through :func:`parse_csv`), and its sequence is the
    time the job was received, so a re-run signs the same bytes and a later run a higher number. A setting that
    names a missing key file, or one others may read, stops the job: never read as "no key"."""
    try:
        key = alliance.signing_key(ctx.cfg.env.extra)
    except alliance.KeyFileRefused:
        raise StepFailed(
            "reporting",
            "The alliance signing key cannot be used: TB_ALLIANCE_SIGNING_KEY_FILE names a file that is not there, "
            "or one its group or others may read (it must be mode 600).",
        ) from None
    if key is None:
        return None
    rows, errors = parse_csv(csv_bytes)
    if errors or not rows:
        raise StepFailed("reporting", "The alliance table cannot be read back for its signature.")
    at = ctx.job.received_at
    return alliance.to_bytes(alliance.sign(rows, key, alliance.seq_of(at), at))


def sender_refusal(site: str, own_site: str, senders: set[str], sender: str) -> str | None:
    """A merged table replaces its site's rows, so the site must be the sender's: never the root's own (that comes
    only from its own COHORT run) and bound to the address its table in the store came from (``senders``: whose
    tables of the site stand in the store now). Otherwise anyone allowed to mail COHORT could overwrite another
    site's counts. The sentence goes back to the sender and into the job's record: it names the site, never an
    address (D-555)."""
    if site == own_site:
        return f"site_id {site} is this box's own table; it comes only from its own COHORT run"
    if senders - {sender}:
        return f"site {site} sends its table from another address; a table of this site is taken only from that one"
    return None


def merge_refusal(db: JobDB, rows: list[dict[str, Any]], sender: str, own_site: str) -> str | None:
    """:func:`sender_refusal` for the site of ``rows`` as the store stands now. A look before the store, for a
    replay; the merge itself asks inside the store's transaction (``cohort_store(refuse=...)``), where no other
    store can come between the question and the write."""
    site = rows[0]["site_id"]
    return sender_refusal(site, own_site, db.cohort_senders(site), sender)


class RecordChanged(RuntimeError):
    """A recorded table cannot be read, or is not the table its hash was taken of."""


class ReplayUnsure(RuntimeError):
    """The record does not settle what a re-run of the merge would read (D-648)."""


def _recorded(stored: list[dict[str, Any]]) -> list[tuple[list[dict[str, Any]], str, str, dict[str, Any]]]:
    """The recorded stores as (table, job, sender, how it was verified), each table checked against its hash."""
    from orchestrator.db import cohort_table_hash

    out = []
    for t in stored:
        try:
            rows = json.loads(t["rows"])
            same = cohort_table_hash(rows) == t["table_sha256"]
        except (ValueError, KeyError, TypeError):
            same = False
        if not same:
            raise RecordChanged(
                f"the record of the table of site {t['site_id']} stored by job {t['job_id']} cannot be read, or was "
                "altered"
            )
        signed = {k: t.get(k) for k in ("verified_by", "signed_seq", "signed_sha256")}
        out.append((rows, str(t["job_id"]), str(t["received_from"]), signed))
    return out


def replay_until(record: JobDB, into: JobDB, upto: int | None = None) -> None:
    """Rebuild in ``into`` the alliance tables of ``record`` as they stood after its store number ``upto`` (after
    its last store when None), from the record alone (D-648): the tables the version that began the record found,
    then every recorded table in the order of the stores, whichever job stored it. Every recorded table is checked
    before anything is stored."""
    tables = _recorded(record.cohort_stored_all(upto))
    before: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for r in record.cohort_before():  # a store replaced a whole (site, disease, quarter, definition): one group each
        before.setdefault((r["site_id"], r["disease"], r["quarter"], r["definition_version"]), []).append(r)
    for group in before.values():  # stored before signatures (D-1226): unverified, but the root's own
        sender = str(group[0]["received_from"])
        own = alliance.OWN if sender.startswith("self:") else None
        into.cohort_store(group, group[0]["job_id"], sender, verified_by=own)
    for rows, job_id, sender, signed in tables:
        into.cohort_store(rows, job_id, sender, **signed)


def replay_stored(record: JobDB, into: JobDB, job_id: str) -> bool:
    """For a re-run of the merge ``job_id``: rebuild in ``into`` the alliance tables as they stood when the merge
    read them for its output (:func:`replay_until` its recorded read point, D-648). It follows the order of the
    stores, not of the jobs, so merges that ran at the same time and a merge that was stopped and run again later
    are replayed as they happened; it needs no job's files, today's reader or any job's ending.

    False, and nothing stored: the merge has no recorded read (it read before the record began); the caller then
    has only how the earlier jobs ended (D-666). :class:`ReplayUnsure`: between this merge's store of a table (a
    site's rows for one disease, quarter and definition) and its read, another job stored that same table; the
    re-run would store this merge's over it and read something else. :class:`RecordChanged`: a recorded table
    cannot be read."""
    upto = record.cohort_read_point(job_id)
    if upto is None:
        return False
    # the groups a store replaces: (site, disease, quarter, definition). The re-run's own store replaces only the
    # merge's groups, so only another job's store of one of THOSE before the read cannot be replayed
    last: dict[tuple[str, str, str, str], str] = {}
    mine: set[tuple[str, str, str, str]] = set()
    for rows, by, _sender, _signed in _recorded(record.cohort_stored_all(upto)):
        for r in rows:
            group = (str(r["site_id"]), str(r["disease"]), str(r["quarter"]), str(r["definition_version"]))
            last[group] = by
            if by == job_id:
                mine.add(group)
    for group in sorted(mine):
        if last[group] != job_id:
            site, disease, quarter, _version = group
            raise ReplayUnsure(
                f"after the merge {job_id} stored the table of site {site} for {disease} {quarter} and before it "
                f"read the tables, the job {last[group]} stored that table again; a re-run cannot give what the "
                "first run read"
            )
    replay_until(record, into, upto)
    return True


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
    sender = norm(job.requested_by)
    signatures = _signatures(ctx)
    try:
        register = alliance.register_of(ctx.cfg.env.extra)
    except (FeedRefused, OSError, ValueError):
        register = None  # a register that cannot be read verifies nothing: every table is refused
    for f in files:
        rows, errors = parse_csv(ctx.input_bytes(f))
        if not errors and rows:
            # D-1226: the signature, by the key registered for the site, before anything is stored; the root's own
            # site is refused first (asked again in the store), so its sentence comes before the signature's
            own = rows[0]["site_id"] == ctx.cfg.settings.site.id
            said = sender_refusal(rows[0]["site_id"], rows[0]["site_id"], set(), "") if own else None
            ok = said or alliance.checked(rows, _signatures_for(rows, signatures), register)
            if isinstance(ok, str):
                errors = [ok]
            else:
                # who may send this site's table, and whether it is newer than the one stored, are asked in the
                # store's transaction: asked before it, another store of the same site could come between the
                # answer and the write (review of D-648)
                rule = partial(sender_refusal, rows[0]["site_id"], ctx.cfg.settings.site.id, sender=sender)
                refused = ctx.orch.db.cohort_store(
                    rows,
                    job.job_id,
                    sender,
                    refuse=rule,
                    verified_by=ok.key_sha256,
                    signed_seq=ok.seq,
                    signed_sha256=ok.table_sha256,
                    stale=partial(alliance.stale_refusal, ok.site_id, ok.seq, ok.table_sha256),
                )
                errors = [refused] if refused else []
        if errors:
            problems.extend(f"{f.filename}: {e}" for e in errors[:10])
            continue
        accepted.extend(rows)
    if not accepted:
        raise StepFailed("running", "No valid alliance table:\n" + "\n".join(f"- {p}" for p in problems[:20]))
    keys = sorted({(r["disease"], r["quarter"]) for r in accepted})
    # D-648: with the record of the point they are read at. D-1226: a member's rows only when signed by the key the
    # register holds for the site now; the others are kept in the store and left out, and the summary names them
    registered = {site: e["key_sha256"] for site, e in (register or {}).items()}
    stored = ctx.orch.db.cohort_read(job.job_id, keys, registered)
    unverified, revoked = ctx.orch.db.cohort_left_out(keys, registered)
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
        + (f"\n\n{alliance.unverified_note(unverified)}" if unverified else "")
        + (f"\n\n{alliance.revoked_note(revoked)}" if revoked else "")
    )
    return Outcome(summary_md=text, deliveries=[Delivery(to=to, outputs=[out], body_md=text)])


def _signatures(ctx: Ctx) -> list[dict[str, Any]]:
    """The signature files attached to the merge (``*.sig.json``) that read as signatures; one that does not is
    no signature, and its table is then refused as unsigned or as not the table it covers."""
    out = []
    for f in ctx.job.inputs or []:
        if f.filename.lower().endswith(alliance.SUFFIX):
            doc = alliance.read(ctx.input_bytes(f))
            if doc is not None:
                out.append(doc)
    return out


def _signatures_for(rows: list[dict[str, Any]], signatures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The candidate signatures of this table: those that cover it (by the table's hash), else those of its site,
    which then tell the sender what does not match; none: the site sent no signature. Each is tried in turn
    (:func:`tb_common.alliance.checked`), so a forged one cannot push out the good one."""
    digest = alliance.table_sha256(rows)
    same = [d for d in signatures if d["table_sha256"] == digest]
    return same or [d for d in signatures if d["site_id"] == rows[0]["site_id"]]


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
