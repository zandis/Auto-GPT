"""The console's worker processes from the site's declared concurrent users (P2-11, ASSESS-1-ADDENDUM D7).

The site declares at install, with its patient count (``TB_SITE_PATIENTS``), how many people use the console at the
same time: ``TB_SITE_USERS`` in ``deploy/.env``, 25 when unset (written then, so the box states it). The service level
at that number: the 95th percentile of the common pages' answer time under 1 s (:data:`SLO_P95_S`), measured by
``tools.console_timing.under_load`` with that many users at once.

``--write`` sets ``TB_CONSOLE_WORKERS`` (uvicorn's ``--workers`` in deploy/docker-compose.yml) to :func:`workers`; a
value set by hand is kept (the line this tool wrote is recorded after ``#console_size:``).

Why one process per :data:`USERS_PER_WORKER` users: the audit's load run (25 users, one console process) held the
process at 120-135 % CPU with a p95 of 2.76 s, so one process cannot hold 25 users under 1 s; at one process per ten
users, 25 users get three, a little under three times the capacity that measured 2.76 s. That is an estimate from one
measurement, not a measured result: the R1 re-acceptance run at the declared size is what shows the service level
holds. Never more processes than the host has CPUs.

    python3 -m tools.trialbox.console_size --env-file deploy/.env [--write]
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

from tools.trialbox.memcaps import _parse_env
from tools.trialbox.private_file import replace_private

DEFAULT_USERS = 25
SLO_P95_S = 1.0
USERS_PER_WORKER = 10
MARKER = "#console_size:"


def users(env: dict[str, str]) -> tuple[int, bool]:
    """The declared concurrent users and whether the site declared them (``False``: the default)."""
    raw = (env.get("TB_SITE_USERS") or "").strip()
    if not raw:
        return DEFAULT_USERS, False
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError(f"TB_SITE_USERS={raw!r}: a whole number of people, 1 or more")
    return int(raw), True


def workers(n_users: int, cpus: int) -> int:
    return max(1, min(cpus, math.ceil(n_users / USERS_PER_WORKER)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--cpus", type=int, default=os.cpu_count() or 1)
    a = ap.parse_args(argv)
    text = a.env_file.read_text(encoding="utf-8") if a.env_file.is_file() else ""
    env = _parse_env(text)
    n, declared = users(env)
    wrote = next((ln.split("=", 1)[1].strip() for ln in text.splitlines() if ln.startswith(MARKER)), None)
    by_hand = "TB_CONSOLE_WORKERS" in env and env["TB_CONSOLE_WORKERS"] != wrote
    w = int(env["TB_CONSOLE_WORKERS"]) if by_hand else workers(n, a.cpus)
    print(f"console_size: {n} concurrent users ({'declared' if declared else 'the default'}), "
          f"{w} worker process{'es' if w != 1 else ''}{' (set by hand)' if by_hand else ''}; "
          f"service level p95 < {SLO_P95_S:g} s")  # fmt: skip
    if a.write:
        keep = ("TB_SITE_USERS=", "TB_CONSOLE_WORKERS=", MARKER)
        lines = [ln for ln in text.splitlines() if not ln.startswith(keep)]
        lines += [f"TB_SITE_USERS={n}", f"TB_CONSOLE_WORKERS={w}"] + ([] if by_hand else [f"{MARKER} {w}"])
        replace_private(a.env_file, "\n".join(lines) + "\n")  # whole, 0600, never in place (H-110)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
