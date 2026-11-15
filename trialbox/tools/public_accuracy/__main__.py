"""``python -m tools.public_accuracy`` (see the package docstring)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main(argv: list[str] | None = None) -> int:
    from tools.public_accuracy import sources

    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy", description=(__doc__ or "").strip())
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="the pinned files of the sets (into .cache/public_accuracy)")
    f.add_argument("--only", default="", help="comma-separated sets (default: all)")
    b = sub.add_parser("build", help="a set's site and gold folders")
    d = sub.add_parser("dryrun", help="build, screen on the stand-in models, score: a plumbing proof")
    for p in (b, d):
        p.add_argument("--set", required=True)
        p.add_argument(
            "--size", type=int, default=20, help="pairs (TREC, SIGIR), trials (TFDA, jRCT, Chia), else items"
        )
        p.add_argument("--out", type=Path, required=True)
    b.add_argument("--ref", default="", help="the site's day YYYY-MM-DD (default: the builder's fixed day)")
    b.add_argument(
        "--for-box",
        action="store_true",
        help="the set's own chart numbers, investigators and ruleset prefix (site.SET_OFFSETS): sets share one box",
    )
    s = sub.add_parser("score", help="score a run folder against its gold")
    s.add_argument("--out", type=Path, required=True)
    e = sub.add_parser("estimate", help="the first real-model run's sample, calls, hours and US$")
    e.add_argument("--box-s-per-protocol", type=float, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        print(json.dumps(sources.fetch([x for x in a.only.split(",") if x] or None), indent=1))
        return 0
    if a.cmd in ("build", "dryrun"):
        from tools.public_accuracy import sets, site

        bundle = sets.read(a.set, size=a.size)
        kw: dict[str, Any] = {}
        if getattr(a, "ref", ""):
            kw["ref"] = date.fromisoformat(a.ref)
        if getattr(a, "for_box", False):
            if a.set not in site.SET_OFFSETS:
                raise SystemExit(f"--for-box: set {a.set} has no offsets in site.SET_OFFSETS")
            kw["mrn0"], kw["pi0"], kw["rs_prefix"] = site.SET_OFFSETS[a.set]
        print(json.dumps(site.build(bundle, a.out / "built", **kw), ensure_ascii=False, indent=1))
        if a.cmd == "build":
            return 0
        from tools.public_accuracy import box

        compile_only = a.set in ("tfda", "jrct", "chia")
        r = box.run(a.out / "built", a.out / "work", screen=not compile_only, approve=not compile_only)
        print(json.dumps({k: v for k, v in r.items() if k != "answers"}, ensure_ascii=False, indent=1, default=str))
    if a.cmd in ("dryrun", "score"):
        from tools.public_accuracy import score

        res = score.score(a.out / "built", a.out / "work")
        (a.out / "score.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])
        return 0
    if a.cmd == "estimate":
        from tools.public_accuracy import plan

        print(json.dumps(plan.table(box_s_per_protocol=a.box_s_per_protocol), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
