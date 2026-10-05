"""Shared compile/approval steps (SPEC §5 approval loop, §8.1 first half)."""

from __future__ import annotations

import re
from typing import Any, cast

from tb_common.authz import norm
from tb_common.ruleset import Ruleset, RulesetNotApproved, load_approved
from tb_contracts import CompileRequest, DiffRequest, JobFile, JobOutput, ParsedDoc, ParseRequest, Routing, dump_json

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery

DOC_EXT = (".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv")
_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.S | re.I)


def approved_or_none(ctx: Ctx, ruleset: str, version: str | None = None) -> Ruleset | None:
    try:
        return load_approved(ctx.rulesets_dir, ruleset, version)
    except RulesetNotApproved:
        if version:  # a specific version was requested and is not the approved one
            raise
        return None


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
        if not (d.changed or d.added or d.removed):
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
        f"{round_no}).\n\nReview each criterion in the attached workbook (column *decision*: approve / reject / "
        f"edit) and reply to this message — or send `APPROVE {ruleset} version={version}` — with the workbook "
        f"attached. Runs use the ruleset only after approval.\n\n"
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
