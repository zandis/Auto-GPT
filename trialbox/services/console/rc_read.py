"""Nightly REDCap read-back (ICD-04 R7, D-109): ``python -m console.rc_read [--study RS]``.

For every study with a REDCap link that is on (or only ``--study``), the orchestrator reads the records changed since
the last read through the study's project link and updates the registry; the screening log shows the result. The
same call as the Run now button on S21 and the screening log. Run by the box's timer after the nightly ingest.
"""

from __future__ import annotations

import argparse
from typing import Any

from console import s28
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.study_setup import read_now


def run(h: Helpers, only: str | None = None) -> list[tuple[str, str]]:
    """``[(study, summary)]`` for each linked study read; errors are reported per study, never raised."""
    try:
        links = (s28.call(h.bk, "GET", "/redcap/connections") or {}).get("links") or []
    except (Problem, Unavailable) as exc:
        return [("*", f"error {getattr(exc, 'code', 'unavailable')}")]
    out: list[tuple[str, str]] = []
    for lk in links:
        rs = str(lk["ruleset"])
        if (only and rs != only.upper()) or (not lk.get("enabled", True) and not only):
            continue
        try:
            res: dict[str, Any] = read_now(h, rs)
        except (Problem, Unavailable) as exc:
            out.append((rs, f"error {getattr(exc, 'code', 'unavailable')}"))
            continue
        h.au.append("console.redcap_read", ruleset=rs, actor="console:nightly", detail={"changes": len(res["changes"])})
        out.append(
            (
                rs,
                f"{res['rows']} rows, {len(res['changes'])} changes, {len(res['duplicates'])} duplicates, "
                f"{len(res['conflicts'])} conflicts, {len(res['unmatched'])} not in TrialBox",
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="console.rc_read")
    ap.add_argument("--study", default="")
    args = ap.parse_args(argv)
    from console.app import create_app

    app = create_app()
    h = getattr(app.state, "helpers", None)
    if h is None:
        raise SystemExit("the console pilot workspace is off (TB_CONSOLE_PILOT=1)")
    results = run(h, args.study or None)
    for rs, summary in results:
        print(f"{rs}: {summary}")
    return 1 if any(s.startswith("error") for _rs, s in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
