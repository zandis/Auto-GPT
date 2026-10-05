"""Retrospective NAV harness (SPEC §11.2 NAV acceptance): evaluate an NHI ruleset at the date of every past
application in the claims table and compare the system verdict with the actual NHI outcome.

* system "eligible" = every structured inclusion TRUE and no structured exclusion TRUE at the application date
  (note/human criteria are not decidable retrospectively and are reported as such);
* agreement on decided applications (approved / denied; pending ones are skipped);
* safety: applications the system calls eligible although a hard exclusion is *coded* — checked by an independent
  code-presence query over every exclusion criterion's condition ValueSets and windows (target: zero).

    python tools/nav_retro.py --lake <lake_dir> --ruleset rulesets/RA-BIO [--months 12] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in ("libs", "services"):
    sys.path.insert(0, str(ROOT / p))


def _coded_exclusions(lake: Any, rs: Any, pid: str, index: date) -> list[str]:
    from criteria_compiler.semantics import atoms

    hits = []
    for c in rs.active():
        if c.kind != "exclusion" or c.class_ != "structured":
            continue
        for a in atoms(c.logic):
            if a.domain != "condition" or a.valueset not in rs.valuesets:
                continue
            codes = [
                x["code"] for inc in rs.valuesets[a.valueset]["compose"]["include"] for x in inc.get("concept", [])
            ]
            lo = None if a.window is None or a.window.from_days is None else index + timedelta(days=a.window.from_days)
            hi = index + timedelta(
                days=a.window.to_days if a.window is not None and a.window.to_days is not None else 0
            )
            n = lake.query(
                "SELECT count(*) AS n FROM condition WHERE pid = $1 AND list_contains(CAST($2 AS VARCHAR[]), code) "
                "AND coalesce(onset, recorded) <= CAST($3 AS DATE) "
                "AND ($4 IS NULL OR coalesce(onset, recorded) >= CAST($4 AS DATE))",
                [pid, codes, hi.isoformat(), lo.isoformat() if lo else None],
            ).to_pylist()[0]["n"]
            if n:
                hits.append(c.id)
    return sorted(set(hits))


def retro(lake: Any, rs: Any, until: date, months: int = 12) -> dict[str, Any]:
    from tb_common.timeutil import add_months

    since = add_months(until, -months)
    codes = list(rs.manifest.twpas.drug_codes or []) if rs.manifest.twpas else []
    claims = lake.query(
        "SELECT kid, pid, created, outcome FROM claim WHERE created BETWEEN CAST($1 AS DATE) AND CAST($2 AS DATE) "
        + ("AND list_contains(CAST($3 AS VARCHAR[]), product) " if codes else "")
        + "ORDER BY created, kid",
        [since.isoformat(), until.isoformat(), *([codes] if codes else [])],
    ).to_pylist()
    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for c in claims:
        by_date[c["created"]].append(c)
    inc = [c.id for c in rs.active() if c.kind == "inclusion" and c.class_ == "structured"]
    exc = [c.id for c in rs.active() if c.kind == "exclusion" and c.class_ == "structured"]
    undecidable = [c.id for c in rs.active() if c.kind in ("inclusion", "exclusion") and c.class_ != "structured"]
    rows = []
    for d, cl in sorted(by_date.items()):
        res = {r["pid"]: r for r in lake.query(rs.sql, [[d.isoformat()], [c["pid"] for c in cl]]).to_pylist()}
        for c in cl:
            r = res.get(c["pid"], {})
            inc_v = [r.get(f"C_{i}") for i in inc]
            exc_v = [r.get(f"C_{e}") for e in exc]
            eligible = all(v is True for v in inc_v) and not any(v is True for v in exc_v)
            unknown = any(v is None for v in inc_v)
            coded = _coded_exclusions(lake, rs, c["pid"], d) if eligible else []
            rows.append(
                {
                    "claim": c["kid"],
                    "date": d.isoformat(),
                    "outcome": c["outcome"],
                    "eligible": eligible,
                    "unknown_inclusion": unknown,
                    "coded_exclusions": coded,
                }
            )
    decided = [r for r in rows if r["outcome"] in ("approved", "denied")]
    agree = sum(
        (r["eligible"] and r["outcome"] == "approved") or (not r["eligible"] and r["outcome"] == "denied")
        for r in decided
    )
    approved = [r for r in decided if r["outcome"] == "approved"]
    return {
        "ruleset": rs.id,
        "version": rs.version,
        "window": [since.isoformat(), until.isoformat()],
        "applications": len(rows),
        "decided": len(decided),
        "pending_skipped": len(rows) - len(decided),
        "agreement": round(agree / len(decided), 4) if decided else None,
        "agreement_on_approvals": round(sum(r["eligible"] for r in approved) / len(approved), 4) if approved else None,
        "unknown_inclusion": sum(r["unknown_inclusion"] for r in decided),
        "eligible_with_coded_hard_exclusion": [r for r in rows if r["coded_exclusions"]],
        "not_decidable_retrospectively": undecidable,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeHttp, LakeLocal
    from tb_common.ruleset import Ruleset

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lake", default="http://127.0.0.1:8013", help="lake directory or lake service URL")
    ap.add_argument("--ruleset", type=Path, default=ROOT / "rulesets" / "RA-BIO")
    ap.add_argument("--until", default="")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    lake: Any = LakeHttp(args.lake) if args.lake.startswith("http") else LakeLocal(Path(args.lake), HashEmbedder())
    rs = Ruleset.load(args.ruleset)
    until = date.fromisoformat(args.until) if args.until else date.fromisoformat(lake.snapshot())
    rep = retro(lake, rs, until, args.months)
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {k: v for k, v in rep.items() if k != "rows"}
    summary["eligible_with_coded_hard_exclusion"] = len(rep["eligible_with_coded_hard_exclusion"])
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0 if not rep["eligible_with_coded_hard_exclusion"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
