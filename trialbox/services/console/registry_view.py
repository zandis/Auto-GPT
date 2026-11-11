"""Candidate registry display helpers shared by the console pages (D-92)."""

from __future__ import annotations

from orchestrator.candidates import FORWARD, STATUSES

# D-399 (T-302a, UX-012): consent is recorded one way, on the participant page's consent form; the screening log follows
# it. The registry's status select no longer offers "consented" (a row already there keeps it).
RECORDED_ELSEWHERE = ("consented",)


def status_options(current: str | None) -> tuple[str, ...]:
    """Statuses a coordinator may pick for a row in ``current`` (every status for a new row, but consent)."""
    opts = STATUSES if current is None or current not in FORWARD else (current, *FORWARD[current])
    return tuple(s for s in opts if s == current or s not in RECORDED_ELSEWHERE)


__all__ = ["RECORDED_ELSEWHERE", "STATUSES", "status_options"]
