"""Scenario registry: job type -> ``run(ctx) -> Outcome`` (SPEC §8)."""

from __future__ import annotations

from orchestrator.core import Scenario


def registry() -> dict[str, Scenario]:
    from orchestrator.scenarios import admin, approve, feas

    return {
        "FEAS": feas.run,
        "APPROVE": approve.run,
        "STATUS": admin.status,
        "CANCEL": admin.cancel,
        "INGEST": admin.ingest,
    }
