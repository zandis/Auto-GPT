"""Recruitment calibration used by the FEAS simulation (SPEC §8.1/§8.2): ``calibration/<RULESET>.json`` or
``calibration/site.json`` under the orchestrator data dir, else ``settings.calibration_defaults``."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tb_contracts import Settings

DEFAULT_CONCENTRATION = 20.0


@dataclass(frozen=True)
class Calibration:
    reach_rate: float
    accept_rate: float
    source: str  # calibrated | default
    contacted: int = 0

    @property
    def concentration(self) -> float:
        """Beta concentration: the number of contacted patients behind a calibrated rate (min 20)."""
        return (
            max(float(self.contacted), DEFAULT_CONCENTRATION) if self.source == "calibrated" else DEFAULT_CONCENTRATION
        )


def load(data_dir: Path, ruleset: str, settings: Settings) -> Calibration:
    for path in (data_dir / "calibration" / f"{ruleset}.json", data_dir / "calibration" / "site.json"):
        if path.exists():
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("reach_rate") is not None and body.get("accept_rate") is not None:
                return Calibration(
                    float(body["reach_rate"]), float(body["accept_rate"]), "calibrated", int(body.get("contacted") or 0)
                )
    d = settings.calibration_defaults
    return Calibration(
        d.reach_rate if d and d.reach_rate is not None else 0.6,
        d.accept_rate if d and d.accept_rate is not None else 0.35,
        "default",
    )


MIN_CONTACTED = 10


def compute(
    ruleset: str,
    pool: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
    at: str,
    min_contacted: int = MIN_CONTACTED,
) -> dict[str, Any]:
    """reach = reached / (reached + not_contacted); accept = enrolled / reached (P(enrol | reached), the quantity the
    FEAS simulation multiplies); screen-fail reasons counted per reason code (criterion id)."""
    n = Counter(f["outcome"] for f in feedback)
    reached = n["enrolled"] + n["screen_fail"] + n["declined"]
    with_fb = reached + n["not_contacted"]
    ok = reached >= min_contacted
    reasons = Counter((f.get("reason_code") or "unspecified") for f in feedback if f["outcome"] == "screen_fail")
    return {
        "ruleset": ruleset,
        "computed_at": at,
        "listed": len(pool),
        "with_feedback": with_fb,
        "contacted": reached,
        "not_contacted": n["not_contacted"],
        "enrolled": n["enrolled"],
        "screen_fail": n["screen_fail"],
        "declined": n["declined"],
        "reach_rate": round(reached / with_fb, 4) if ok and with_fb else None,
        "accept_rate": round(n["enrolled"] / reached, 4) if ok and reached else None,
        "screen_fail_rate": round(n["screen_fail"] / reached, 4) if reached else None,
        "screen_fail_reasons": dict(sorted(reasons.items())),
        "min_contacted": min_contacted,
        "used_by_feas": ok,
    }


def suppressed(body: dict[str, Any], t: int) -> dict[str, Any]:
    """The aggregate (published) calibration: counts small-cell suppressed, and a rate withheld when it would reveal
    a small count (accept 5 % of 20 contacted = 1 enrolled). The exact file stays in the box for FEAS."""
    from tb_common.smallcell import rate_publishable, suppress

    out = dict(body)
    for k in ("listed", "with_feedback", "contacted", "not_contacted", "enrolled", "screen_fail", "declined"):
        out[k] = suppress(int(body[k]), t)
    out["screen_fail_reasons"] = {k: suppress(int(v), t) for k, v in body["screen_fail_reasons"].items()}
    parts = {
        "reach_rate": (body["contacted"], body["with_feedback"]),
        "accept_rate": (body["enrolled"], body["contacted"]),
        "screen_fail_rate": (body["screen_fail"], body["contacted"]),
    }
    withheld = [k for k, (num, den) in parts.items() if out[k] is not None and not rate_publishable(num, den, t)]
    for k in withheld:
        out[k] = None
    out["rates_withheld"] = withheld
    return out


def _pct(rate: float | None) -> str:
    return f"{rate:.0%}" if rate is not None else "withheld (small cells)"


def run(ctx: Any) -> Any:
    """CALIBRATION job (monthly): recompute calibration.json per ruleset with feedback (SPEC §8.2)."""
    from orchestrator.core import Delivery, Outcome
    from orchestrator.scenarios.review import approved_or_none, recipients

    db = ctx.orch.db
    targets = [ctx.job.ruleset.upper()] if ctx.job.ruleset else db.feedback_rulesets()
    ctx.state("running")
    deliveries = []
    lines = []
    for rid in targets:
        body = compute(rid, db.pool(rid), db.feedback(rid), ctx.orch._now().isoformat())
        path = ctx.data_dir / "calibration" / f"{rid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        rs = approved_or_none(ctx, rid)
        routing = rs.manifest.routing if rs else None
        to = recipients(routing, "" if ctx.job.requested_by == "scheduler" else ctx.job.requested_by)
        t = int(ctx.cfg.settings.thresholds.small_cell if ctx.cfg.settings.thresholds else 5) or 5
        pub = suppressed(body, t)
        out = ctx.publish(
            f"calibration_{rid}.json",
            (json.dumps(pub, indent=1, sort_keys=True) + "\n").encode(),
            "aggregate",
            to,
        )

        rates = (
            f"reach {_pct(pub['reach_rate'])}, accept {_pct(pub['accept_rate'])}"
            if body["used_by_feas"]
            else f"too few contacts ({pub['contacted']} < {body['min_contacted']}); FEAS keeps default rates"
        )
        lines.append(f"{rid}: {rates}")
        if to:
            deliveries.append(
                Delivery(
                    to=to,
                    outputs=[out],
                    routing=routing,
                    kind="calibration",
                    subject=f"Calibration {rid} — job {ctx.job.job_id}",
                    body_md=f"Monthly recruitment calibration for **{rid}**: {rates}.",
                )
            )
    return Outcome(summary_md="\n".join(lines) or "No feedback yet.", deliveries=deliveries)
