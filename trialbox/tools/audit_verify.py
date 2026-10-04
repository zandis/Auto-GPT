"""Recompute the TrialBox audit hash chain (SPEC §10.2). Exit 0 when intact, 1 otherwise.

Usage: python tools/audit_verify.py <audit_dir> [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tb_common.audit import verify


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audit_dir", type=Path)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    if not args.audit_dir.is_dir():
        print(f"no such directory: {args.audit_dir}", file=sys.stderr)
        return 2
    res = verify(args.audit_dir)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": res.ok,
                    "files": res.files,
                    "lines": res.lines,
                    "last_hash": res.last_hash,
                    "errors": res.errors,
                },
                ensure_ascii=False,
            )
        )
    else:
        status = "PASS" if res.ok else "FAIL"
        print(f"audit chain {status}: {res.files} files, {res.lines} events, head {res.last_hash[:16]}…")
        for err in res.errors[:50]:
            print(f"  {err}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
