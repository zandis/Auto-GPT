"""The console's own time for a request, in a ``Server-Timing`` header (D-1245, card 10E-13, review 13 item 13-14).

One metric, ``total``: the milliseconds from the moment the console's outermost middleware received the request to
the moment its answer (headers and the rendered page) was ready, to one decimal. Numbers only: no path, no account, no
study, no patient, no description field. The console does not separate the time it spends waiting on the
orchestrator from its own (every backend call goes through ``console.backend`` and the workspace's helpers, with no
single seam to time), so no backend share is written; a share timed at some calls and not others would mislead.

**An allow-list.** The header is written only on a ``200`` answer to a ``GET`` of a route in :data:`TIMED`, named by
its route template (the matched route's path, never the request's path and never a prefix): the ten pages the walk
measures. Every other route and method, and any route added later, carries no header until someone adds it here on
purpose, with the reason next to it.

The rule a listed route meets: **the header adds nothing to what the status already says**. A route is listed only
when an account that gets a ``200`` for a thing that exists gets something other than a ``200`` (403, 404 or a
redirect, none of which carries the header) for a thing that does not, or when the route names no thing at all. Who
gets the ``200`` is the route's own rule, not this module's (a sub-investigator off a study's log opens that study's
state and its jobs' pages, on master as here). A route that answers ``200`` both for a thing that exists and for one
that does not (the header search, ``/cmd``, D-1241) stays out: the time of the two answers would differ where the
status does not. ``tests/console/test_console_timing.py`` walks every registered route and holds :data:`TIMED` equal
to the walk's page list.

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
    "/home": "names no thing: each signed-in account gets its own home page",
    "/studies/{rs}/week": "a study that does not exist: 404; a study the account opens: 200; the status already "
    "differs, the header adds nothing",
    "/studies/{rs}/patients/{pid}": "a study or a pseudonym that does not exist: no 200; the status already differs",
    "/studies/{rs}/candidates": "a study that does not exist: 404; the status already differs",
    "/studies/{rs}/subjects": "a study that does not exist: 404; the status already differs",
    "/studies/{rs}/state": "a study that does not exist: 404; an account that opens it (a sub-investigator off its "
    "log included): 200; the status already differs, the header adds nothing",
    "/pilot/jobs/{job_id}": "a job that does not exist: 404; an account that opens it (a sub-investigator off the "
    "study's log included): 200; the status already differs, the header adds nothing",
    "/pilot/protocol": "names no thing: a form",
    "/audit": "names no thing in its path; its filters are query values on one page",
    "/admin/ops": "names no thing",
}


def timed(status: int, route: str | None, method: str) -> bool:
    """Whether an answer carries the header: a ``200`` to a ``GET`` of a route template in :data:`TIMED`, nothing
    else (a ``POST`` to a listed path answers with its own page and stays untimed)."""
    return status == 200 and method == "GET" and route is not None and route in TIMED
