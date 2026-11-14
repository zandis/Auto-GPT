"""CLI for the synthetic hospital; see ``tools.synth_hospital`` and TB-DS-21 §3."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from tools.synth_hospital import CHUNK, DEFAULT_STUDIES, PROFILES, parse_lang_mix, run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.synth_hospital", description=__doc__)
    ap.add_argument("--profile", choices=sorted(PROFILES), default="ci")
    ap.add_argument("--sites", help="site:style:patients,... (style JP, TW or EN); default from the profile")
    ap.add_argument("--lang-mix", nargs="*", help="STYLE=lang:w,lang:w ... e.g. JP=ja:0.9,en:0.1")
    ap.add_argument("--studies", default=",".join(DEFAULT_STUDIES))
    ap.add_argument("--ref-date", default="2026-11-01")
    ap.add_argument("--years", type=int, default=8, help="accepted for TB-DS-21 §3; history depth is fixed today")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chunk", type=int, default=CHUNK)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--synthea", type=Path, help="optional Synthea CSV export (off; no mapping in this build)")
    args = ap.parse_args(argv)
    if args.synthea:
        print("--synthea: the Synthea structured base is optional and not mapped in this build; ignoring it.")
    res = run(
        args.out,
        profile=args.profile,
        sites=args.sites,
        lang_mix=parse_lang_mix(args.lang_mix),
        studies=[s.strip() for s in args.studies.split(",") if s.strip()],
        ref_date=date.fromisoformat(args.ref_date),
        seed=args.seed,
        chunk=args.chunk,
    )
    s = res.summary
    for site in s["sites"]:
        print(
            f"{site['site_id']} ({site['style']}): {site['patients']} patients, {site['notes']} notes "
            f"{site['note_languages']}, PHI in {site['notes_with_phi']} notes ({site['phi_spans']} spans), "
            f"{site['seconds']} s -> {args.out / site['dir']}"
        )
    print(f"rate cells: {json.dumps(s['rate_cells'])} (tolerance ±{s['tolerance_points']:.0f} points)")
    print(f"digest {s['digest'][:16]}  total {s['seconds']} s")
    if res.failures:
        print("CHECKS FAILED:")
        for f in res.failures:
            print("  " + f)
        return 1
    print("checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
