"""Scenario registry: job type -> ``run(ctx) -> Outcome`` (SPEC §8)."""

from __future__ import annotations

from orchestrator.core import Scenario


def registry() -> dict[str, Scenario]:
    from orchestrator.scenarios import admin, approve, calibration, feas, feedback, microbatch, nav, screen

    return {
        "FEAS": feas.run,
        "SCREEN": screen.run,
        "NAV": nav.run,
        "MICROBATCH": microbatch.run,
        "FEEDBACK": feedback.run,
        "CALIBRATION": calibration.run,
        "APPROVE": approve.run,
        "STATUS": admin.status,
        "CANCEL": admin.cancel,
        "INGEST": admin.ingest,
    }
