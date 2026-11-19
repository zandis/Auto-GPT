"""The console's own time for a request, in a ``Server-Timing`` header (D-1245, card 10E-13, review 13 item 13-14).

One metric, ``total``: the milliseconds from the moment the console's outermost middleware received the request to
the moment its answer (headers and the rendered page) was ready, to one decimal. Numbers only: no path, no account, no
study, no patient, no description field. The console does not separate the time it spends waiting on the
orchestrator from its own (every backend call goes through ``console.backend`` and the workspace's helpers, with no
single seam to time), so no backend share is written; a share timed at some calls and not others would mislead.

The header is written on a ``200`` answer only. A refusal (401, 403), a not-found (404), a redirect (a sign-in, a
refused page sent home) and an error carry none, so a refused account and a missing page answer alike (as D-1241 asks
of the header search): its presence says no more than the status code already says.

The walk (``tools.console_timing``) reads this header, not a client's clock: on a loaded CI runner the time between
the client and the server's middleware (the test client's own work, the event loop's queue) is not the page's."""

from __future__ import annotations

import re

HEADER = "Server-Timing"
METRIC = "total"
#: what the header holds, exactly: one metric, its duration in milliseconds, nothing else
SHAPE = re.compile(r"^total;dur=\d+(?:\.\d)?$")


def value(ms: float) -> str:
    """The header's value for ``ms`` milliseconds (never negative; one decimal)."""
    return f"{METRIC};dur={max(ms, 0.0):.1f}"


def timed(status: int) -> bool:
    """Whether an answer with this status carries the header: a page that was served, nothing else."""
    return status == 200
