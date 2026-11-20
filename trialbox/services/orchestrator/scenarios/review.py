"""Shared compile/approval steps (SPEC §5 approval loop, §8.1 first half)."""

from __future__ import annotations

import re
from typing import Any, cast

from criteria_compiler.semantics import human_heavy
from tb_common.authz import norm
from tb_common.ruleset import RecompileNeeded, Ruleset, RulesetNotApproved, load_approved
from tb_contracts import CompileRequest, DiffRequest, JobFile, JobOutput, ParsedDoc, ParseRequest, Routing, dump_json

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery

DOC_EXT = (".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv")
_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.S | re.I)


def approved_or_none(ctx: Ctx, ruleset: str, version: str | None = None, run: bool = True) -> Ruleset | None:
    """The approved ruleset, or None. ``run``: it is about to run, so one compiled against another terminology
    release than the box's is refused (:class:`RecompileNeeded`, D-301), and the version is the one in force today
    (D-364, LIFE-009): a version approved with a later effective date waits, its predecessor screens until then."""
    from criteria_compiler.terminology import resolver

    try:
        rs = load_approved(
            ctx.rulesets_dir,
            ruleset,
            version,
            terminology=resolver.guard() if run else None,
            on=ctx.today() if run else None,  # the job's run date, not the wall clock's (D-477, review L1)
        )
    except RecompileNeeded:  # approved, but compiled against another terminology release (D-301): never "none"
        raise
    except RulesetNotApproved:
        if version:  # a specific version was requested and is not the approved one
            raise
        return None
    if run:
        guard_arrived(ctx, rs)
    return rs


#: D-1369 (the review of f8fcc04e, H1): what each job type does with a rule set installed from outside the box
#: through the gate (``tb_common.ruleset.site_scoped``). ``narrows``: it runs it inside the site's accepted
#: practitioners and departments (``screen._scope_terms``, ``screen.in_arrived_scope``); ``refuses``: it refuses it
#: (:func:`guard_arrived`, audited ``job.ruleset_refused``); ``no rule set run``: it runs no rule set over patients.
#: A job type missing here refuses (tests/unit/test_ruleset_part_gate.py holds the table to the registry).
ARRIVED_RULE: dict[str, str] = {
    "SCREEN": "narrows", "MICROBATCH": "narrows",
    "FEAS": "refuses", "NAV": "refuses", "COHORT": "refuses", "CASE": "refuses", "SUBMIT": "refuses",
    "CALIBRATION": "refuses",
    "APPROVE": "no rule set run", "FEEDBACK": "no rule set run", "STATUS": "no rule set run",
    "CANCEL": "no rule set run", "INGEST": "no rule set run", "RETENTION": "no rule set run",
    "CONSENT": "no rule set run", "RELEASE": "no rule set run",
}  # fmt: skip

#: the refusal, in the three languages of the box
ARRIVED_REFUSED = {
    "en": "{rid} v{version} arrived in an update (approved on another box): this box runs it only as SCREEN and "
    "MICROBATCH, inside the practitioners and departments the site accepted; a {kind} job is refused (D-1369)",
    "ja": "{rid} v{version} は更新で届いた基準です（別のボックスで承認）。このボックスでは SCREEN と MICROBATCH "
    "として、施設が受け入れた医師と診療科の範囲内でのみ実行します。{kind} ジョブは拒否されました（D-1369）",
    "zh-TW": "{rid} v{version} 是經由更新送達的條件（於另一台機器核准）：本機只以 SCREEN 與 MICROBATCH 執行，"
    "且限於本院接受的醫師與科別；{kind} 作業已拒絕（D-1369）",
}


def guard_arrived(ctx: Ctx, rs: Ruleset) -> None:
    """D-1369 (H1): the one check every job that runs a rule set passes (:func:`approved_or_none` with ``run``): a
    rule set installed through the gate runs only as a job type that narrows it to the site's accepted scope
    (:data:`tb_common.ruleset.ARRIVED_NARROWS`), and only while that scope names someone; any other job type is refused
    with a sentence in en, ja and zh-TW and the audited event ``job.ruleset_refused``. A rule set approved here is
    unchanged."""
    from tb_common.ruleset import ARRIVED_NARROWS, ArrivedScopeClosed, arrived_scope

    try:
        scope = arrived_scope(ctx.rulesets_dir, rs)
        closed = None
    except ArrivedScopeClosed as exc:
        scope, closed = (None, None), str(exc)
    if scope is None:
        return
    job = getattr(ctx, "job", None)
    kind = str(getattr(job, "type", None) or "unknown")
    if kind in ARRIVED_NARROWS and closed is None:
        return
    why = closed or "\n".join(f"{lang}: {t.format(rid=rs.id, version=rs.version, kind=kind)}"
                              for lang, t in ARRIVED_REFUSED.items())  # fmt: skip
    ctx.orch.audit.append("job.ruleset_refused", job_id=getattr(job, "job_id", None), ruleset=rs.id,
                          ruleset_version=rs.version,
                          detail={"job_type": kind, "closed": closed is not None})  # fmt: skip
    raise StepFailed("ruleset", why)


def pin_state(rs: Ruleset) -> dict[str, Any]:
    """``tb_common.ruleset.approval_state`` of an approved ruleset against this box's prompt registry and terminology
    release (D-318): ``approval_needed`` sends the same criteria to the investigator again as a new draft."""
    from criteria_compiler.terminology import resolver
    from tb_common.ruleset import approval_state

    try:
        release: str | None = resolver.current_release()
    except Exception:  # the vocabulary cannot be read: the run itself refuses (D-301); no terminology reason here
        release = None
    return approval_state(rs.manifest, terminology_release=release)


def protocol_input(ctx: Ctx) -> JobFile | None:
    """The protocol / rule document among the attachments (PDF, DOCX first; then XLSX/TXT/MD/CSV)."""
    files = [f for f in ctx.job.inputs or [] if f.filename.lower().endswith(DOC_EXT)]
    files.sort(key=lambda f: (not f.filename.lower().endswith((".pdf", ".docx")), f.filename))
    return files[0] if files else None


def parse(ctx: Ctx, f: JobFile) -> tuple[str, ParsedDoc]:
    ctx.state("parsing")
    parsed = ctx.services.parser.parse(ParseRequest(minio_key=f.minio_key, job_id=ctx.job.job_id))
    key = f"attachments/{ctx.job.job_id}/parsed/{f.filename}.json"
    ctx.store.put(key, dump_json(parsed).encode("utf-8"), "application/json")
    return key, parsed


def recipients(routing: Routing | None, requester: str) -> list[str]:
    to = {norm(a) for a in (routing.aggregate_to if routing and routing.aggregate_to else [])}
    if requester and "@" in requester:
        to.add(norm(requester))
    return sorted(to)


def compile_draft(ctx: Ctx, ruleset: str, doc: JobFile, approved: Ruleset | None, kind: str) -> Delivery | None:
    """Parse the attached document; when it differs from the approved version (or nothing is approved), compile a
    draft and return the review delivery. ``None`` means the approved ruleset already matches the document."""
    key, parsed = parse(ctx, doc)
    opts = dict(ctx.job.options or {})
    if approved is not None:
        d = ctx.services.compiler.diff(DiffRequest(ruleset=ruleset, new_doc_key=key, job_id=ctx.job.job_id))
        if not (d.changed or d.added or d.removed) and pin_state(approved)["state"] != "approval_needed":
            return None
    ctx.state("compiling")
    copts = {k: v for k, v in opts.items() if k in ("lookback",)}
    copts["index_date"] = ctx.today().isoformat()
    res = ctx.services.compiler.compile(
        CompileRequest(
            job_id=ctx.job.job_id,
            ruleset=ruleset,
            parsed_doc_key=key,
            kind=cast(Any, kind),
            version=opts.get("version") if approved is None else None,
            requested_by=ctx.job.requested_by,
            options=copts,
        )
    )
    ctx.update(ruleset_version=res.version)
    assert res.review_html_key and res.review_xlsx_key and res.draft_zip_key
    return review_delivery(
        ctx,
        ruleset,
        res.version,
        res.manifest.routing,
        res.review_html_key,
        res.review_xlsx_key,
        res.draft_zip_key,
        1,
        parsed.filename,
    )


_CLASS = re.compile(r"<td>(?:inclusion|exclusion)</td><td>(structured|note|human|mixed)</td>")


def check_split(html: str) -> str:
    """One line on how the box will check the criteria: filter, model on notes, or a person (the review's class)."""
    found = _CLASS.findall(html)
    if not found:
        return ""
    n = {k: found.count(k) for k in ("structured", "note", "human", "mixed")}
    mixed = (
        f", **{n['mixed']}** by the filter first and the model on the notes where the codes are silent"
        if n["mixed"]
        else ""
    )
    warn = (
        f"**Check this:** {n['human']} of {len(found)} criteria are left to a person, so the box would do little of "
        f"the screening for this trial. Re-read the class column before approving.\n\n"
        if human_heavy(n)
        else ""
    )
    return (
        f"How the box will check the {len(found)} criteria: **{n['structured']}** by a fixed filter on structured "
        f"data (age, sex, diagnosis codes, labs, drugs), **{n['note']}** by the model reading reports and notes"
        f"{mixed}, **{n['human']}** left to a person at screening. The model proposed this routing; on open trial "
        f"data it agreed with expert annotators about 6 times in 10, so your approval is the check of every class "
        f"(filter / model / person).\n\n" + warn
    )


def review_delivery(
    ctx: Ctx,
    ruleset: str,
    version: str,
    routing: Routing | None,
    html_key: str,
    xlsx_key: str,
    zip_key: str,
    round_no: int,
    source: str = "",
) -> Delivery:
    to = recipients(routing, ctx.job.requested_by)
    html = ctx.store.get(html_key).decode("utf-8")
    m = _BODY.search(html)
    outs: list[JobOutput] = [
        ctx.publish(f"review_{ruleset}_v{version}_r{round_no}.html", html.encode("utf-8"), "aggregate", to),
        ctx.copy_object(xlsx_key, f"review_{ruleset}_v{version}_r{round_no}.xlsx", "aggregate", to),
        ctx.copy_object(zip_key, f"ruleset_{ruleset}_v{version}-draft.zip", "aggregate", to),
    ]
    intro = (
        f"Ruleset **{ruleset} v{version}** was compiled{f' from {source}' if source else ''} (review round "
        f"{round_no}).\n\n"
        + check_split(html)
        + f"If the criteria look right, approve them: one click on the job page in the console, or reply to this "
        f"message (or send `APPROVE {ruleset} version={version}`) with the workbook attached. To change a "
        f"criterion, edit its *decision* column (approve / reject / edit) first. Runs use the ruleset only after "
        f"approval. This is the study team's check of the criteria, not a regulated e-signature.\n\n"
    )
    return Delivery(
        to=to,
        outputs=outs,
        subject=f"APPROVE {ruleset} version={version} -- review round {round_no}, job {ctx.job.job_id}",
        body_md=intro + (m.group(1) if m else ""),
        kind="review",
        routing=routing,
    )


def require_approved(ctx: Ctx, ruleset: str, version: str | None) -> Ruleset:
    rs = approved_or_none(ctx, ruleset, version)
    if rs is None:
        raise StepFailed(
            "ruleset",
            f"Ruleset {ruleset} has no approved version on this box. Attach the protocol (PDF/DOCX) to compile it, "
            f"then approve the review workbook.",
        )
    return rs
