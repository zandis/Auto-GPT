"""The OMOP store from the command line (D-149). The database is ``TB_OMOP_DB_URL`` or ``TB_DB_URL``.

python -m omop load --lake /data/lake [--snapshot 2026-10-31] [--tz Asia/Taipei]   # a snapshot + the site inputs
python -m omop status                                                              # rows per table, conflicts
python -m omop dqd [--json out.json]                                               # exit 1 when a check fails
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from omop import dqd, schema
from omop.load import load_batch


def _read(directory: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(directory.glob("*.ndjson")):
        with f.open(encoding="utf-8") as fh:
            out[f.stem] = [json.loads(line) for line in fh if line.strip()]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m omop")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ld = sub.add_parser("load")
    ld.add_argument("--lake", type=Path, required=True)
    ld.add_argument("--snapshot")
    ld.add_argument("--tz", default="Asia/Taipei")
    sub.add_parser("status")
    dq = sub.add_parser("dqd")
    dq.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    db = schema.connect()
    try:
        if a.cmd == "load":
            snap = a.snapshot or (a.lake / "CURRENT").read_text().strip()
            feed = _read(a.lake / "ndjson" / snap)
            site = _read(a.lake / "site")
            out = [
                load_batch(db, "feed", snap, feed, None, a.tz).as_dict(),
                load_batch(db, "site", f"site@{snap}", site, None, a.tz).as_dict(),
            ]
            print(json.dumps(out, indent=1, ensure_ascii=False))
            return 0
        if a.cmd == "status":
            tables = [*schema.CDM_TABLES, "tb_record", "tb_conflict", "tb_appointment", "tb_claim", "tb_consent"]
            counts = {t: int(db.fetchval(f"SELECT count(*) FROM {t}")) for t in tables}
            counts["conflicts_open"] = int(db.fetchval("SELECT count(*) FROM tb_conflict WHERE state = 'open'"))
            print(json.dumps(counts, indent=1))
            return 0
        res = dqd.run(db)
        if a.json:
            a.json.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        print(json.dumps(dqd.summary(res)))
        for r in res:
            if r["status"] != "pass":
                print(
                    f"{r['status']:5} {r['checkName']} {r['cdmTableName']}.{r['cdmFieldName']}: "
                    f"{r['numViolatedRows']}/{r['numDenominatorRows']} {r['notes']}"
                )
        return 1 if any(r["status"] == "fail" for r in res) else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
