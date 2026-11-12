"""CASE: one patient's chart against one approved ruleset (the "is this patient eligible?" question a PI asks).

``CASE GZQO [mrn=<chart number>] [lang=en|ja|zh-TW] [version=1.0.0]`` with the chart attached (PDF, DOCX, TXT or
MD; several files allowed) produces a one-page **eligibility sheet**: every criterion of the ruleset with ``met``,
``not met``, ``unknown`` or ``needs a human``, the verbatim dated quote behind each answer, and what would resolve an
unknown. It is a reading aid for the study team, not a decision: the PI decides.

What it uses, in this order (D-91):

1. **Structured criteria from the hospital database** when ``mrn=`` is given and the patient is in the lake: the same
   deterministic CQL or SQL as SCREEN, on the current snapshot. The chart is never used for a criterion the database
   can answer.
2. **The uploaded chart for note criteria**, and for structured criteria of a patient the box does not know (a referral,
   a paper chart): the chart is split into dated excerpts (a date found in the text, else the upload date, flagged) and
   each criterion is put to the judge with the SCREEN prompt and the SCREEN rule: answer only from the excerpts, quote
   verbatim, ``unknown`` when the chart does not say. With a verifier build configured the two-model agreement rule
   applies (D-89). The quote is checked character for character against the excerpt.
3. **Human criteria** stay ``needs a human``.

An uploaded chart is a sample of the record, so ``unknown`` means "the chart did not say", never "not eligible"; the
sheet says so at the top in the reader's language. The chart and the sheet are PHI: they stay on the box, the sheet
goes only to the ruleset's internal ``list_to`` recipients (the study team; never the referral departments), and a
requester who is not one of them gets a summary with counts only. Chart numbers never appear in the stored record
(the pseudonym does).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from matching import decision
from tb_common import dates
from tb_common.crypto import load_key, pid_for_mrn, sha256_bytes
from tb_common.kek import key_present
from tb_common.quotes import quote_in
from tb_common.reasons import Reason
from tb_common.routing import is_internal
from tb_common.ruleset import Ruleset
from tb_common.subject import job_subject
from tb_contracts import CriterionIR, CriterionVerdict, Evidence, ParseRequest, PatientEvaluation

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_stamp
from orchestrator.decision_context import decision_of
from orchestrator.i18n import detect_lang
from orchestrator.reports import case_html
from orchestrator.scenarios.evaluate import (
    FILTERED,
    NoteJudge,
    NoteResult,
    coded_settles,
    engine_from_env,
    human_verdict,
    is_pair,
    not_final,
    note_verdict,
    note_window,
    structured_verdict,
)
from orchestrator.scenarios.review import require_approved
from orchestrator.scenarios.screen import judge_for, threshold

SCHEMA = "trialbox.case@1"
CHART_EXT = (".pdf", ".docx", ".txt", ".md")
MAX_CHART_CHARS = 200_000
MAX_EXCERPT_CHARS = 1_800  # about 450 tokens; long paragraphs are split so that one criterion sees several excerpts
LANGS = ("en", "ja", "zh-TW")

_HEADING = re.compile(r"^\s*(#{1,6}\s+|[【\[][^】\]]{1,40}[】\]]\s*$)")


# ------------------------------------------------------------------------------------------------ chart text
def find_date(text: str) -> date | None:
    """The first plausible calendar date in ``text`` (ISO or slashed first, then a Japanese era, then Minguo):
    :func:`tb_common.dates.find` (D-215)."""
    return dates.find(text)


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_EXCERPT_CHARS:
        return [text]
    parts = re.split(r"(?<=[。．.!?！？])\s*", text)
    out: list[str] = []
    cur = ""
    for p in parts:
        if cur and len(cur) + len(p) > MAX_EXCERPT_CHARS:
            out.append(cur)
            cur = ""
        cur += p
    if cur:
        out.append(cur)
    return [x for x in out if x.strip()]


def chart_excerpts(text: str, filename: str, fallback: date) -> list[dict[str, Any]]:
    """Dated excerpts from one chart file. A date found in a paragraph (or in the heading above it) applies to that
    paragraph and the ones after it until the next date; paragraphs before any date carry the fallback (the upload
    date), flagged ``date_source: "upload"`` so the sheet can say the chart did not date them."""
    text = unicodedata.normalize("NFKC", text).replace("\r", "")
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\s*(?:#|【|\[))", text) if p.strip()]
    out: list[dict[str, Any]] = []
    current: date | None = None
    note_type = Path(filename).stem[:40] or "chart"
    n = 0
    for p in paras:
        d = find_date(p[:200]) or find_date(p)
        if d is not None:
            current = d
        if _HEADING.match(p) and len(p) < 60:
            note_type = re.sub(r"^[#\s【\[]+|[】\]\s]+$", "", p)[:40] or note_type
            continue
        for piece in _split_long(p):
            n += 1
            out.append(
                {
                    "date": (current or fallback).isoformat(),
                    "note_type": note_type,
                    "text": piece,
                    "did": f"chart:{filename}#{n}",
                    "date_source": "document" if current is not None else "upload",
                }
            )
    return out


def read_charts(ctx: Ctx) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files = [f for f in ctx.job.inputs or [] if f.filename.lower().endswith(CHART_EXT)]
    if not files:
        raise StepFailed(
            "received",
            "Attach the patient's chart (discharge summary, clinic notes, lab report) as PDF, DOCX, TXT or MD: "
            "CASE GZQO mrn=<chart number> with the file attached.",
        )
    ctx.state("parsing")
    excerpts: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    total = 0
    for f in sorted(files, key=lambda x: x.filename):
        data = ctx.input_bytes(f)
        if f.filename.lower().endswith((".txt", ".md")):
            text = data.decode("utf-8-sig", errors="replace")
        else:
            parsed = ctx.services.parser.parse(ParseRequest(minio_key=f.minio_key, job_id=ctx.job.job_id))
            text = "\n\n".join((f"# {s.title}\n\n" if s.title else "") + s.text for s in parsed.sections)
        total += len(text)
        if total > MAX_CHART_CHARS:
            raise StepFailed(
                "parsing", f"the chart is longer than {MAX_CHART_CHARS} characters; attach the relevant notes"
            )
        ex = chart_excerpts(text, f.filename, ctx.today())
        if not ex:
            raise StepFailed("parsing", f"{f.filename}: no readable text found (scanned PDF without OCR?)")
        excerpts.extend(ex)
        meta.append(
            {
                "filename": f.filename,
                "sha256": sha256_bytes(data),
                "excerpts": len(ex),
                "dated": sum(1 for e in ex if e["date_source"] == "document"),
                "earliest": min(e["date"] for e in ex),
                "latest": max(e["date"] for e in ex),
            }
        )
    return excerpts, meta


# ------------------------------------------------------------------------------------------------ patient
@dataclass
class Subject:
    pid: str | None = None  # pseudonym when a chart number was given
    in_lake: bool = False
    snapshot: str | None = None
    note: str = ""  # why structured criteria came from the chart


def resolve_subject(ctx: Ctx, mrn: str | None) -> Subject:
    if not mrn:
        return Subject(note="no chart number given: structured criteria answered from the chart text")
    rx = ctx.cfg.settings.mrn_regex
    if rx and not re.match(rx, mrn):
        raise StepFailed("received", f"mrn={mrn!r} does not look like a chart number of this site")
    key_file = Path(ctx.cfg.env.secrets_dir) / "site_hmac.key"
    if not key_present(key_file):  # plain or wrapped under the KEK (T-210b)
        return Subject(note="the box has no site key yet (no ingest): structured criteria answered from the chart")
    pid = pid_for_mrn(load_key(key_file), mrn)
    snapshot = ctx.services.lake.snapshot()
    if not snapshot:
        return Subject(pid=pid, note="the lake has no snapshot yet: structured criteria answered from the chart")
    found = ctx.services.lake.query("SELECT 1 FROM patient WHERE pid = $1", [pid], snapshot).num_rows > 0
    if not found:
        return Subject(
            pid=pid, note="chart number not in the hospital data: structured criteria answered from the chart"
        )
    return Subject(pid=pid, in_lake=True, snapshot=snapshot)


def refuse_opted_out(ctx: Ctx, pid: str | None) -> None:
    """D-441: no eligibility sheet for a patient on the opt-out register (D-147) as it stood when the job was
    received. The refusal is audited without the pseudonym; the requester typed the chart number and is told why."""
    if pid is None:
        return
    d = decision_of(ctx)
    if pid in d.register() or pid in d.refused():  # D-477: a registry refusal as the register (the worker copies it)
        ctx.orch.audit.append("case.opt_out_refused", job_id=ctx.job.job_id, ruleset=ctx.job.ruleset,
                              detail={"register": "optout"})  # fmt: skip
        raise StepFailed("received", "This patient opted out of research use: no eligibility sheet is made.")


# ------------------------------------------------------------------------------------------------ judging
@dataclass
class ChartJudge:
    """The SCREEN judge over the chart's excerpts instead of the lake's chunks (same prompt, rule and span check)."""

    judge: NoteJudge
    excerpts: list[dict[str, Any]]
    results: dict[str, NoteResult] = field(default_factory=dict)

    def window(self, c: CriterionIR, index_date: date) -> list[dict[str, Any]]:
        lo, hi = note_window(c, index_date)
        inside = [e for e in self.excerpts if lo.isoformat() <= e["date"] <= hi.isoformat()]
        inside.sort(key=lambda e: (e["date"], e["did"]), reverse=True)
        return inside

    def decide(self, c: CriterionIR, index_date: date) -> NoteResult:
        ex = self.window(c, index_date)
        if not ex:
            r = NoteResult("unknown", 0.0, reason=Reason.NO_NOTES.value, source="chart")
        else:
            r = self.judge.judge_excerpts(c.text, c.note_question or c.text, index_date, ex, source="chart")
            if r.predicate != "unknown" and not r.dids:
                r.dids = [e["did"] for e in ex if r.quote and quote_in(r.quote, str(e["text"]))][:1]
        self.results[c.id] = r
        return r


def resolve_hint(c: CriterionIR, verdict: CriterionVerdict, lang: str) -> str:
    """What would turn an unknown into an answer: the ruleset's action where it has one, else by class."""
    if verdict.verdict not in ("unknown", "pending_human"):
        return ""
    if c.action:
        return c.action
    if c.class_ == "human":
        return case_html.HINT[lang]["human"]
    if c.class_ == "structured":
        return case_html.HINT[lang]["structured"]
    return case_html.HINT[lang]["note"]


def evaluate_case(
    ctx: Ctx, rs: Ruleset, subj: Subject, excerpts: list[dict[str, Any]], lang: str
) -> tuple[list[dict[str, Any]], NoteJudge | None]:
    index_date = ctx.today()
    active = [c for c in rs.active() if c.kind in ("inclusion", "exclusion")]
    evals: dict[str, PatientEvaluation] = {}
    if subj.in_lake and subj.pid:
        ids = [c.id for c in active if c.class_ in FILTERED]
        from orchestrator import derive

        # the lake snapshot, deterministic; the stored-row read while the flag is on (D-442), as on every path
        engine = engine_from_env("sql", None, ctx.services.lake, subj.snapshot, derive.reader_for(ctx))
        evals = engine.evaluate(rs, [subj.pid], index_date, ids) if ids else {}
    judge = judge_for(ctx, rs)
    cj = ChartJudge(judge, excerpts) if judge is not None else None
    # T-709 (D-478, review H2): the one status function decides what a criterion's answer says. One model's "not
    # met", or a pair's below the threshold, is printed as "to check" with the reading kept as evidence, never as
    # not met: a single model takes no patient off any path, the PI's sheet included
    may_block = decision_of(ctx).note_block(judge).may_block
    policy = decision.Policy(threshold(ctx, rs), may_block)
    pair = is_pair(judge)
    rows: list[dict[str, Any]] = []
    for c in active:
        source = "lake"
        if c.class_ == "human":
            v = human_verdict(c)
            source = "human"
        elif subj.in_lake and (c.class_ == "structured" or coded_settles(c, evals.get(subj.pid or ""))):
            v = structured_verdict(c, evals.get(subj.pid or ""))
        elif cj is not None:
            r = cj.decide(c, index_date)
            v = not_final(c, note_verdict(c, r, pair), may_block)
            source = "chart"
        else:
            v = CriterionVerdict(
                id=c.id, verdict="unknown", evidence=Evidence(resource_refs=[], reason=Reason.NOT_EVALUATED.value)
            )
            source = "chart"
        ev = v.evidence or Evidence(resource_refs=[])
        shown, why = v.verdict, ev.reason
        if v.verdict == "fail" and decision.answer_of(c, v, policy) == "unknown":
            single = v.basis == "single" or v.final is False
            shown = "unknown"
            why = Reason.SINGLE_MODEL.value if single else Reason.LOW_CONFIDENCE.value
            v = v.model_copy(update={"verdict": "unknown"})  # the hint below reads the answer as shown
        rows.append(
            {
                "id": c.id,
                "kind": c.kind,
                "class": c.class_,
                "label": c.label or c.text[:60],
                "text": c.text,
                "verdict": shown,
                "source": source,
                "quote": ev.quote,
                "quote_date": ev.quote_date,
                "reason": why,
                "refs": list(ev.resource_refs or [])[:5],
                "resolve": resolve_hint(c, v, lang),
            }
        )
    return rows, judge


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out = {"met": 0, "not_met": 0, "unknown": 0, "human": 0, "total": len(rows)}
    for r in rows:
        key = {"pass": "met", "fail": "not_met", "unknown": "unknown", "pending_human": "human"}[r["verdict"]]
        out[key] += 1
    return out


def headline(c: dict[str, int], lang: str) -> str:
    return case_html.HEADLINE[lang].format(**c)


def pick_lang(ctx: Ctx, chart_text: str | None = None) -> str:
    """The sheet's language: ``lang=`` when given; else the chart's own language (what the console option "Same as
    the chart" promises); else the site locale."""
    raw = (ctx.job.options or {}).get("lang")
    if raw:
        if raw not in LANGS:
            raise StepFailed("received", f"lang={raw!r}: use one of en, ja, zh-TW")
        return str(raw)
    if chart_text and chart_text.strip():
        return detect_lang(chart_text)
    loc = (ctx.cfg.settings.site.locale or "en") if ctx.cfg.settings.site else "en"
    return loc if loc in LANGS else ("ja" if loc.startswith("ja") else "zh-TW" if loc.startswith("zh") else "en")


# ------------------------------------------------------------------------------------------------ scenario
def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    opts = job.options or {}
    rs = require_approved(ctx, (job.ruleset or "").upper(), opts.get("version"))
    ctx.update(ruleset_version=rs.version)
    lang = pick_lang(ctx)
    domains = ctx.cfg.settings.internal_domains
    if not is_internal(job.requested_by, domains):
        raise StepFailed("received", "CASE sheets contain patient text and are sent to internal addresses only.")
    routing = rs.manifest.routing
    phi_to = sorted(
        a.lower() for a in (routing.list_to if routing and routing.list_to else []) if is_internal(a, domains)
    )
    if not phi_to:
        raise StepFailed(
            "routing", f"Ruleset {rs.id} has no internal routing.list_to; an eligibility sheet cannot be sent."
        )
    excerpts, charts = read_charts(ctx)
    lang = pick_lang(ctx, " ".join(str(e.get("text", "")) for e in excerpts[:40]))
    subj = resolve_subject(ctx, opts.get("mrn"))
    refuse_opted_out(ctx, subj.pid)
    if subj.snapshot:
        ctx.update(snapshot_date=date.fromisoformat(subj.snapshot))
    ctx.state("running")
    rows, judge = evaluate_case(ctx, rs, subj, excerpts, lang)
    c = counts(rows)
    rec: dict[str, Any] = {
        "schema": SCHEMA,
        "job_id": job.job_id,
        "ruleset": rs.id,
        "version": rs.version,
        "site": ctx.cfg.settings.site.id,
        "created": job_stamp(ctx),
        "index_date": ctx.today().isoformat(),
        "requested_by": job.requested_by,
        "lang": lang,
        "subject": {"pid": subj.pid, "in_lake": subj.in_lake, "snapshot": subj.snapshot, "note": subj.note},
        "charts": charts,
        "excerpts": len(excerpts),
        "undated_excerpts": sum(1 for e in excerpts if e["date_source"] == "upload"),
        "judge": {
            "model": judge.llm.model if judge else None,
            "mode": judge.mode if judge else None,
            "verifier": judge.verifier.model if judge and judge.verifier else None,
            "calls": judge.calls if judge else 0,
            "disagreements": judge.disagreements if judge else 0,
        },
        "counts": c,
        "criteria": rows,
    }
    ctx.state("reporting")
    to = sorted(set(phi_to) | ({job.requested_by.lower()} if job.requested_by.lower() in phi_to else set()))
    rec["recipients"] = to
    stem = f"case_{rs.id}_{job.job_id}"
    sheet = ctx.publish(f"{stem}.html", case_html.sheet(rec), "phi", to)
    ctx.publish(f"{stem}.json", json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True).encode(), "phi", to)
    if judge is not None:
        ctx.metrics(llm_calls=judge.calls, tokens_in=judge.tokens_in, tokens_out=judge.tokens_out)
    head = headline(c, lang)
    summary = case_html.summary_md(rec, to)
    deliveries = [
        Delivery(
            to=to,
            outputs=[sheet],
            routing=rs.manifest.routing,
            kind="list",
            subject=job_subject("sheet", "CASE", rs.id, job.job_id, head),
            body_md=summary,
        )
    ]
    # a requester who is not on list_to gets the orchestrator's "done" mail: summary_md, counts only, no sheet
    return Outcome(summary_md=summary, deliveries=deliveries, headline=head)


__all__ = ["chart_excerpts", "counts", "find_date", "run"]
