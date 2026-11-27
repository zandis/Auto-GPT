"""``trialbox provenance``: the provenance index of D-989 (``tb_common.provenance_index``), on the host.

    trialbox provenance --check                          # the index against the chain; exit 1 when they differ
    trialbox provenance --rebuild                        # write the index again from the chain (the chain wins)
    trialbox provenance --search --build <sha>           # the records a build's calls touched
    trialbox provenance --search --prompt judge --version 4
    trialbox provenance --search --prompt-sha <sha> --model <name> [--json]

The chain is ``TB_AUDIT_DIR`` (default ``/data/audit``), the database ``TB_DB_URL``. Opted-out patients are read
from the register (``tb_common.optout.opted_out``): their use rows are neither written back by a rebuild nor reported
missing by the check. The search names patients by pseudonym only; it is for a steward or an administrator.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _connect(url: str) -> Any:
    from tb_common.audit_writer import _dsn, _psycopg

    return _psycopg().connect(_dsn(url), autocommit=True, connect_timeout=10)


def main(argv: Sequence[str] | None = None) -> int:
    from tb_common import provenance_index as idx

    ap = argparse.ArgumentParser(prog="trialbox provenance", description=__doc__.split("\n\n")[0])
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--check", action="store_true", help="compare the index with the chain (exit 1 on a difference)")
    what.add_argument("--rebuild", action="store_true", help="write the index again from the chain")
    what.add_argument("--search", action="store_true", help="the records the matching calls touched")
    ap.add_argument("--model")
    ap.add_argument("--build", dest="build_sha")
    ap.add_argument("--prompt-sha")
    ap.add_argument("--prompt", dest="prompt_id")
    ap.add_argument("--version", dest="prompt_version")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--json", action="store_true", help="print the search as JSON")
    ap.add_argument("--audit-dir", default=os.environ.get("TB_AUDIT_DIR") or "/data/audit")
    ap.add_argument("--db-url", default=os.environ.get("TB_DB_URL") or "")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if not a.db_url:
        print("trialbox provenance: TB_DB_URL is not set", file=sys.stderr)
        return 2
    if a.check:  # P19-DESIGN-3 §2: refused with the operator's step before any database work
        m = idx.read_marker(Path(a.audit_dir))
        if not m.clean:
            print(m.text)
            return 1
    con = _connect(a.db_url)
    try:
        if not idx.installed(con):
            print("provenance index: not installed (the role script creates provenance.model_calls and model_uses)")
            return 1
        if a.search:
            try:
                rows = idx.search(con, model=a.model, build_sha=a.build_sha, prompt_sha=a.prompt_sha,
                                  prompt_id=a.prompt_id, prompt_version=a.prompt_version, limit=a.limit,
                                  directory=Path(a.audit_dir))  # fmt: skip
            except ValueError as exc:
                print(f"trialbox provenance: {exc}", file=sys.stderr)
                return 2
            except idx.ProvenanceRebuildRequired as exc:  # P-19 (review P19-X1)
                print(f"trialbox provenance: {exc}", file=sys.stderr)
                return 1
            if a.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1))
            else:
                for r in rows:
                    ref = ", ".join(f"{k}={v}" for k, v in sorted(r["record_ref"].items()))
                    how = f" {r['decision']} by {r['by']}" if r["event"] == "confirmed" else ""
                    print(f"{r['at']}  {r['record_kind']:<9} {ref}  {r['event']}{how}  call {r['call_id']}")
                print(f"{len(rows)} record(s)")
            return 0
        audit = Path(a.audit_dir)
        if a.rebuild:  # P19-DESIGN-3 §3: the rebuild writes the marker itself, verified last
            try:
                calls, uses = idx.rebuild(con, audit, say=print)
            except idx.RebuildRefused as exc:
                print(f"provenance index: the rebuild was refused: {exc}", file=sys.stderr)
                return 1
            print(f"provenance index rebuilt from {audit}: {calls} call(s), {uses} use(s)")
            return 0
        diff = idx.check(con, audit)
        if diff.ok:
            print("provenance index: equal to the chain")
            return 0
        print(f"provenance index differs from the chain: {len(diff.missing)} row(s) missing, {len(diff.extra)} "
              "extra; the chain wins: run trialbox provenance --rebuild")  # fmt: skip
        for table, rec_hash, call_id in (diff.missing + diff.extra)[:20]:
            print(f"  {table} line {rec_hash[:16]} call {call_id}")
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
