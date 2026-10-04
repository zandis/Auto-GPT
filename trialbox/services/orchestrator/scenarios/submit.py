"""SUBMIT (SPEC §8.4): a physician replies ``SUBMIT <ruleset> pid=<pid> bundle=<NAV job id>`` to send one TWPAS
bundle produced by that NAV run to NHI. Never automatic; the only path on which PHI leaves the box (§5).

Checks before anything is sent (DECISIONS D-68):

* sender is a physician in settings (also enforced at intake by ``permissions.SUBMIT``);
* the NAV job is ``done``, of the same ruleset, not older than ``MAX_AGE_DAYS``;
* the stored bundle still hashes to the sha256 recorded in the job's outputs (and the audit chain);
* that bundle had 0 HL7 validator errors and a passing NHI pre-check;
* the same bundle was not already submitted for real.

Dry run (``settings.twpas.dry_run`` or no ``NHI_TWPAS_BASE_URL``): nothing leaves the box; a simulated
``ClaimResponse`` (outcome ``queued``) is returned. Live: ``POST {NHI_TWPAS_BASE_URL}/Claim/$submit`` with the Bundle;
the returned ``ClaimResponse`` is stored. Either way a ``twpas.submit`` audit event carries the bundle hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from tb_common.authz import allowed, norm
from tb_common.routing import RoutingViolation, check

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.scenarios.review import require_approved

MAX_AGE_DAYS = 14
NHI_DISPLAY = "衛生福利部中央健康保險署"


def _nav_job(ctx: Ctx, ruleset: str, ref: str | None, pid: str) -> Any:
    if ref:
        nav = ctx.orch.db.get(ref.upper())
        if nav is None or nav.type != "NAV" or (nav.ruleset or "").upper() != ruleset:
            raise StepFailed("received", f"bundle={ref} is not a NAV job for {ruleset} on this box.")
        return nav
    # no bundle= → the latest finished NAV run of this ruleset that holds a bundle for the patient
    for nav in ctx.orch.db.find(type_="NAV", ruleset=ruleset, state="done"):  # newest first
        if any(o.filename == _bundle_name(ruleset, pid) for o in nav.outputs or []):
            return nav
    raise StepFailed("received", f"No NAV run of {ruleset} holds a TWPAS bundle for pid {pid[:12]}.")


def _bundle_name(ruleset: str, pid: str) -> str:
    return f"twpas_{ruleset}_{pid[:12]}.json"


def _check_validation(ctx: Ctx, nav: Any, ruleset: str, pid: str, live: bool) -> list[str]:
    """Refuses a bundle with validator errors or a failed pre-check. A live submission also needs the HL7 validator
    (not the structural fallback) and a pre-check that ran; a dry run only notes their absence (returned)."""
    rep = next((o for o in nav.outputs or [] if o.filename == f"twpas_validation_{ruleset}.json"), None)
    if rep is None:
        raise StepFailed("received", f"NAV job {nav.job_id} has no TWPAS validation report.")
    data = json.loads(ctx.store.get(rep.minio_key))
    entry = next((b for b in data.get("bundles", []) if str(b.get("pid", "")).startswith(pid[:12])), None)
    if entry is None or not entry.get("file"):
        raise StepFailed("received", f"NAV job {nav.job_id} built no bundle for pid {pid[:12]}.")
    errors = entry.get("validator_errors") or []
    pre = entry.get("precheck") or {}
    problems = [*errors, *(pre.get("issues") or [])]
    if errors or pre.get("passed") is False:
        raise StepFailed(
            "received",
            "The bundle did not pass validation/pre-check and will not be submitted:\n"
            + "\n".join(f"- {p}" for p in problems[:20]),
        )
    gaps = []
    if data.get("validator") != "hl7-validator":
        gaps.append("validated structurally only (HL7 validator not installed)")
    if pre.get("passed") is not True:
        gaps.append("NHI pre-check did not run: " + "; ".join(pre.get("issues") or ["no result"]))
    if gaps and live:
        raise StepFailed("received", "Not submitted to NHI — " + "; ".join(gaps) + ".")
    return gaps


def _resource(bundle: dict[str, Any], rtype: str) -> dict[str, Any] | None:
    for e in bundle.get("entry", []):
        r = e.get("resource") or {}
        if r.get("resourceType") == rtype:
            return dict(r)
    return None


def simulated_response(bundle: dict[str, Any], created: str, job_id: str) -> dict[str, Any]:
    claim = _resource(bundle, "Claim") or {}
    patient = _resource(bundle, "Patient") or {}
    return {
        "resourceType": "ClaimResponse",
        "id": f"dryrun-{job_id.lower()}",
        "status": "active",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "pharmacy"}]},
        "use": "preauthorization",
        "patient": {"reference": f"Patient/{patient.get('id', '')}"},
        "created": created,
        "insurer": {"display": NHI_DISPLAY},
        "request": {"reference": f"Claim/{claim.get('id', '')}"},
        "outcome": "queued",
        "disposition": "DRY RUN — the bundle was not transmitted (settings.twpas.dry_run / no NHI_TWPAS_BASE_URL).",
    }


def post_bundle(base_url: str, bundle_bytes: bytes, timeout: float = 120.0) -> dict[str, Any]:
    """POST the Bundle to the NHI endpoint; returns the ClaimResponse (direct or inside a response Bundle)."""
    import httpx

    url = base_url.rstrip("/") + "/Claim/$submit"
    try:
        resp = httpx.post(
            url,
            content=bundle_bytes,
            headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise StepFailed("running", f"NHI endpoint unreachable ({type(exc).__name__}); nothing was submitted.") from exc
    if resp.status_code >= 400:
        raise StepFailed("running", f"NHI endpoint answered HTTP {resp.status_code}; see the box log.")
    body = resp.json()
    if body.get("resourceType") == "ClaimResponse":
        return dict(body)
    found = _resource(body, "ClaimResponse") if body.get("resourceType") == "Bundle" else None
    if found is None:
        raise StepFailed("running", f"NHI endpoint returned {body.get('resourceType')!r}, not a ClaimResponse.")
    return found


def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    ruleset = (job.ruleset or "").upper()
    opts = job.options or {}
    pid = (opts.get("pid") or "").strip().lower()
    if len(pid) < 12:
        raise StepFailed("received", "Give the patient: SUBMIT <ruleset> pid=<pid> bundle=<NAV job id>.")
    if not allowed(ctx.cfg.settings, "SUBMIT", job.requested_by):  # also enforced at intake; jobs may come via API
        raise StepFailed("received", "Only senders in settings.permissions.SUBMIT (physicians) may SUBMIT to NHI.")
    site = ctx.cfg.settings.twpas
    if not site or not site.enabled:
        raise StepFailed("received", "TWPAS is not enabled in settings.")
    nav = _nav_job(ctx, ruleset, opts.get("bundle"), pid)
    rs = require_approved(ctx, ruleset, nav.ruleset_version)
    try:  # the receipt is phi: the requester must be on the ruleset's list_to — checked before anything is sent
        check("phi", [norm(job.requested_by)], rs.manifest.routing, ctx.cfg.settings.internal_domains)
    except RoutingViolation as exc:
        raise StepFailed("received", f"{job.requested_by} is not a list recipient of {ruleset}: {exc}") from exc
    if nav.state != "done":
        raise StepFailed("received", f"NAV job {nav.job_id} is {nav.state}, not done.")
    if nav.received_at.date() < ctx.today() - timedelta(days=MAX_AGE_DAYS):
        raise StepFailed("received", f"NAV job {nav.job_id} is older than {MAX_AGE_DAYS} days; run NAV again.")
    out = next((o for o in nav.outputs or [] if o.filename == _bundle_name(ruleset, pid)), None)
    if out is None:
        raise StepFailed("received", f"NAV job {nav.job_id} holds no TWPAS bundle for pid {pid[:12]}.")
    base = ctx.cfg.env.nhi_twpas_base_url
    dry = bool(site.dry_run) or not base
    gaps = _check_validation(ctx, nav, ruleset, pid, live=not dry)
    ctx.state("running")
    data = ctx.store.get(out.minio_key)
    sha = hashlib.sha256(data).hexdigest()
    if sha != out.sha256:
        raise StepFailed("running", f"Stored bundle {out.filename} does not match its audited hash; not submitted.")
    if ctx.orch.db.submissions(sha, live_only=True):
        raise StepFailed("running", f"{out.filename} from job {nav.job_id} was already submitted to NHI.")
    bundle = json.loads(data)
    now = ctx.orch._now().isoformat(timespec="seconds")
    response = simulated_response(bundle, now, job.job_id) if dry else post_bundle(str(base), data)
    outcome = str(response.get("outcome") or "unknown")
    ctx.orch.audit.append(
        "twpas.submit",
        job_id=job.job_id,
        ruleset=ruleset,
        output_sha=sha,
        detail={
            "nav_job_id": nav.job_id,
            "pid": pid[:12],
            "dry_run": dry,
            "endpoint": None if dry else str(base),
            "outcome": outcome,
            "by": norm(job.requested_by),
        },
    )
    ctx.orch.db.submission_add(
        {
            "job_id": job.job_id,
            "ruleset": ruleset,
            "pid": pid,
            "nav_job_id": nav.job_id,
            "bundle_sha": sha,
            "dry_run": dry,
            "outcome": outcome,
            "submitted_by": norm(job.requested_by),
            "submitted_at": now,
        }
    )
    ctx.state("reporting")
    receipt = ctx.publish(
        f"twpas_claimresponse_{ruleset}_{pid[:12]}.json",
        (json.dumps(response, ensure_ascii=False, indent=1) + "\n").encode(),
        "phi",
        [job.requested_by],
    )
    mode = "**dry run** — nothing left the box" if dry else f"sent to NHI ({base})"
    text = (
        f"TWPAS submission for **{ruleset}** pid `{pid[:12]}…` ({mode}).\n\n"
        f"- bundle: `{out.filename}` from NAV job `{nav.job_id}` (sha256 `{sha[:16]}…`)\n"
        f"- ClaimResponse outcome: **{outcome}**\n"
        f"- disposition: {response.get('disposition') or '—'}\n"
        + "".join(f"- note: {g} — a live submission would be refused\n" for g in gaps)
    )
    return Outcome(
        summary_md=text,
        deliveries=[Delivery(to=[job.requested_by], outputs=[receipt], body_md=text, routing=rs.manifest.routing)],
    )
