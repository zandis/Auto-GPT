"""Candidate registry display helpers shared by the console pages (D-92)."""

from __future__ import annotations

from orchestrator.candidates import FORWARD, STATUSES


def status_options(current: str | None) -> tuple[str, ...]:
    """Statuses a coordinator may pick for a row in ``current`` (every status for a new row)."""
    if current is None or current not in FORWARD:
        return STATUSES
    return (current, *FORWARD[current])


__all__ = ["STATUSES", "status_options"]
