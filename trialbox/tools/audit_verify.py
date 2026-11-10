"""Recompute the TrialBox audit hash chain (SPEC §10.2). Exit 0 when intact, 1 otherwise.

Usage::

    python tools/audit_verify.py <audit_dir> [--json] [--anchor FILE] [--no-head]
    python tools/audit_verify.py <audit_dir> --find-ids [--json]
    python tools/audit_verify.py <audit_dir> --reanchor "why" --actor NAME

* The chain must end where its head anchor (``<audit_dir>/HEAD.json``) says (D-272, register CR-054). ``--anchor``
  also checks an anchor kept elsewhere, such as the audit archive's ``HEAD.json``: that catches a chain rewritten
  together with its own anchor. ``--no-head`` checks a copy that has no anchor (a decompressed archive).
* ``--find-ids`` lists the events that hold a chart number in clear (written before D-272, register CR-016): file,
  line, time, event, job and the field, never the value. They stay in the chain until the owner rules (OD-7); this
  is the list for that ruling. It also counts, per event, the rows that name a patient pseudonym (DATA-013).
  Exit 0 when none is found, 1 otherwise.
* ``--reanchor`` is for a person who has looked at a chain that does not match its anchor: it records the old
  anchor, the chain as found and the reason as an ``audit.reanchored`` event, and anchors the chain where it ends.
  No line is changed or removed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from tb_common.audit import AuditLog, clear_ids, verify

_PID = re.compile(r"\b[0-9a-f]{32}\b")


def find_ids(directory: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rows that hold a chart number in clear, and per event the rows that name a 32-hex pseudonym."""
    rows: list[dict[str, Any]] = []
    pids: Counter[str] = Counter()
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                body = {k: v for k, v in rec.items() if k not in ("hash", "prev_hash", "input_sha", "output_sha")}
                where = clear_ids(body)
                if where:
                    rows.append({"file": path.name, "line": lineno, "ts": rec.get("ts"), "event": rec.get("event"),
                                 "job_id": rec.get("job_id"), "hash": rec.get("hash"), "fields": where})  # fmt: skip
                if _PID.search(json.dumps(rec.get("detail") or {}, ensure_ascii=False)):
                    pids[str(rec.get("event"))] += 1
    return rows, dict(sorted(pids.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audit_dir", type=Path)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--anchor", type=Path, help="a head anchor kept elsewhere (the archive's HEAD.json)")
    ap.add_argument("--no-head", action="store_true", help="the folder is a copy without HEAD.json")
    ap.add_argument("--find-ids", action="store_true", help="list events holding a chart number in clear")
    ap.add_argument("--reanchor", metavar="REASON", help="record the gap and anchor the chain where it ends")
    ap.add_argument("--actor", default="", help="who runs --reanchor")
    args = ap.parse_args(argv)
    if not args.audit_dir.is_dir():
        print(f"no such directory: {args.audit_dir}", file=sys.stderr)
        return 2
    if args.reanchor is not None:
        if not args.actor.strip() or not args.reanchor.strip():
            print("--reanchor needs a reason and --actor", file=sys.stderr)
            return 2
        rec = AuditLog(args.audit_dir).reanchor(f"audit_verify:{args.actor.strip()}", args.reanchor)
        print(f"audit.reanchored written: {canonical_detail(rec)}")
        return 0
    if args.find_ids:
        rows, pids = find_ids(args.audit_dir)
        if args.json:
            print(json.dumps({"rows": rows, "pseudonym_rows_by_event": pids}, ensure_ascii=False))
        else:
            print(f"{len(rows)} audit events hold a chart number in clear (the value is not printed)")
            for r in rows:
                print(f"  {r['file']}:{r['line']} {r['ts']} {r['event']} job={r['job_id']} {', '.join(r['fields'])}")
            print(f"events naming a patient pseudonym: {sum(pids.values())}")
            for event, n in pids.items():
                print(f"  {event}: {n}")
        return 1 if rows else 0
    anchor = json.loads(args.anchor.read_text(encoding="utf-8")) if args.anchor else None
    res = verify(args.audit_dir, anchor=anchor, require_head=not args.no_head)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": res.ok,
                    "files": res.files,
                    "lines": res.lines,
                    "last_hash": res.last_hash,
                    "head": res.head,
                    "errors": res.errors,
                    "notes": res.notes,
                },
                ensure_ascii=False,
            )
        )
    else:
        status = "PASS" if res.ok else "FAIL"
        print(f"audit chain {status}: {res.files} files, {res.lines} events, head {res.last_hash[:16]}…")
        for err in res.errors[:50]:
            print(f"  {err}")
        for note in res.notes[:20]:
            print(f"  note: {note}")
    return 0 if res.ok else 1


def canonical_detail(rec: dict[str, Any]) -> str:
    return json.dumps(rec.get("detail") or {}, sort_keys=True, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
