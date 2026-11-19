"""The console's own time for a request, in a ``Server-Timing`` header (D-1245, card 10E-13, review 13 item 13-14).

One metric, ``total``: the milliseconds from the moment the console's outermost middleware received the request to
the moment its answer (headers and the rendered page) was ready, to one decimal. Numbers only: no path, no account, no
study, no patient, no description field. The console does not separate the time it spends waiting on the
orchestrator from its own (every backend call goes through ``console.backend`` and the workspace's helpers, with no
single seam to time), so no backend share is written; a share timed at some calls and not others would mislead.

**An allow-list.** The header is written only on a ``200`` answer of a route in :data:`TIMED`, named by its route
template (the matched route's path, never the request's path and never a prefix): the ten pages the walk measures.
Every other route, and any route added later, carries no header until someone adds it here on purpose, with the
reason next to it. A route is in :data:`TIMED` only when its ``200`` cannot differ between a refused and a missing
thing: it answers those with 403, 404 or a redirect, which carry no header, so the header's presence says no more than
the status code. A route that answers ``200`` in both cases (the header search, ``/cmd``, D-1241) stays out: the time of
the two answers would differ. ``tests/console/test_console_timing.py`` walks every registered route and holds
:data:`TIMED` equal to the walk's page list.

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


#: route template -> why its 200 cannot differ between a refused and a missing thing (each is a page of the walk,
#: ``tests/console/timing_walk.py``; the test file checks the 403/404 of each)
TIMED: dict[str, str] = {
    "/home": "no identifier in the path: each signed-in account gets its own home page; nothing can be missing",
    "/studies/{rs}/week": "study_or_404: a study the account does not see and no such study are the same 404",
    "/studies/{rs}/patients/{pid}": "a study not seen or missing: 404; a pseudonym not on the study's list: no 200",
    "/studies/{rs}/candidates": "study_or_404 (the same 404 for not seen and missing), then the screen task (403)",
    "/studies/{rs}/subjects": "study_or_404: a study the account does not see and no such study are the same 404",
    "/studies/{rs}/state": "study_or_404: a study the account does not see and no such study are the same 404",
    "/pilot/jobs/{job_id}": "no such job: 404; another study's job for a scoped account: refused, never a 200",
    "/pilot/protocol": "no identifier in the path: a form; nothing can be missing",
    "/audit": "no identifier in the path: refused accounts 403; its filters are query values on one page",
    "/admin/ops": "no identifier in the path: refused accounts 403",
}


def timed(status: int, route: str | None) -> bool:
    """Whether an answer carries the header: a ``200`` of a route template in :data:`TIMED`, nothing else."""
    return status == 200 and route is not None and route in TIMED
