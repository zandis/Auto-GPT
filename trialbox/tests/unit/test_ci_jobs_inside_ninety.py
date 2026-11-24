"""CI-TIMEOUTS (D-995): every CI job names a time limit inside D-537's 90 minutes, or is named here with its reason.

D-537 (the owner): no CI job runs over 90 minutes, and no ceiling is raised to get there; the work is shrunk instead.
A job's ``timeout-minutes`` is where a hang ends and what a stuck run costs. This test reads every workflow:
- a job with no limit runs for GitHub's 360 minutes, so each job must name one;
- a limit above 90 must be on the list below, with the reason the integrator took to the owner.

The list grows only by a ruling of the integrator or the owner (the bench's full-set: 7119929149); otherwise it
only shrinks. The limits this card lowered were measured first (2026-11-17):
- ``checks``: 15 to 8, for a job of 3 min 8 s;
- ``compose``: 150 to 90, for 37.5 min plus about 10.5 for the new-study walk;
- ``rehearse``: 120 to 60, for about 20 min.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
CEILING = 90

#: (workflow, job): why it is above 90 for now. Each one is a question for the owner (D-995, #639, 2026-11-17).
ABOVE_CEILING = {
    ("trialbox-e2e.yml", "scale-50k"): "the 50k night: measured at 74 min on 2026-11-16, its limit not yet ruled",
    ("trialbox-images.yml", "multiarch"): "a release tag or by hand only; no measured run",
    ("trialbox-p0-media.yml", "media"): "by hand only, builds the owner's P-0 media (hours, stage b); no measured run",
    # the integrator's ruling 7119929149 (#639, 2026-11-24, card H-105): named with its reason and its figure's source
    (
        "trialbox-bench-ci.yml",
        "full-set",
    ): "a whole-set run on the bench host (three runs of every stage, a train or the "
    "owner's run by hand only); 600 min from the hosted runners' measured stages, not a bench run: about 110 min a "
    "run (the one-runner unit suite 35 to 43 min, 2026-11-12; compose 37.5 + 10.5 min, 2026-11-17; the rest a few "
    "minutes each), three runs 330, the GPU stage and a margin of 1.5 on top; to be re-set after the first bench run",
}


def _jobs() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for f in sorted(WORKFLOWS.glob("*.yml")):
        wf = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for name, job in (wf.get("jobs") or {}).items():
            if "uses" not in job:  # a reusable workflow's caller has no steps of its own
                out.append((f.name, name, job))
    return out


def test_every_job_names_a_limit() -> None:
    assert [(w, n) for w, n, j in _jobs() if j.get("timeout-minutes") is None] == []


def test_no_job_is_above_ninety_unless_named() -> None:
    above = {(w, n) for w, n, j in _jobs() if int(str(j["timeout-minutes"])) > CEILING}
    assert above <= set(ABOVE_CEILING), (
        f"over {CEILING} minutes and not named (D-537): {sorted(above - set(ABOVE_CEILING))}"
    )
    assert set(ABOVE_CEILING) <= above, (
        f"no longer above {CEILING}: take it off the list {sorted(set(ABOVE_CEILING) - above)}"
    )


def test_the_lowered_limits() -> None:
    jobs = {(w, n): j for w, n, j in _jobs()}
    assert jobs[("trialbox-ci.yml", "checks")]["timeout-minutes"] == 8
    assert jobs[("trialbox-e2e.yml", "compose")]["timeout-minutes"] == CEILING
    assert jobs[("trialbox-rehearse-box.yml", "rehearse")]["timeout-minutes"] == 60
