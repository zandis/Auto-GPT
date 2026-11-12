"""The log-marker step plants a random marker in a note; a marker the PHI tripwire reads as a phone or ID number made
the gateway refuse the call and failed the step (about 0.6 % of runs, seen once in CI on the B3 branch)."""

from __future__ import annotations

import re

from guard.guard import Guard

from tools import qualify as q


def test_the_planted_marker_never_trips_the_phi_tripwire() -> None:
    g = Guard(None)
    for _ in range(5000):
        marker = q.new_marker()
        assert re.fullmatch(r"TBQMARK[A-Z]{16}", marker)
        assert not g.tripwire(f"No gout flare today. Ref {marker}.").hit
