"""The OMOP store from the command line (D-151). The database is ``TB_OMOP_DB_URL`` or ``TB_DB_URL``.

python -m omop load --lake /data/lake [--snapshot 2026-10-31] [--tz Asia/Tokyo]           # a snapshot + the site inputs
python -m omop status                                                              # rows per table, conflicts
python -m omop dqd [--json out.json] [--tz Asia/Tokyo]                             # exit 1 when a check fails
python -m omop vocab terminology [--rulesets DIR]        # the compiler's Parquet into the vocabulary (D-301)
python -m omop vocab code-list --system URI --version FY2027 --file F [--rulesets DIR]   # e.g. ICD-10-CM FY2027
python -m omop vocab licensed | refdata | local --ws main                     # JP masters, refdata terms, local maps
python -m omop vocab athena --file DIR                    # an Athena bundle (allow-listed vocabularies only)
python -m omop vocab status                                                   # releases, release id, recompile list
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from omop import dqd, schema
from omop.load import load_batch


def _read(directory: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(directory.glob("*.ndjson")):
        with f.open(encoding="utf-8") as fh:
            out[f.stem] = [json.loads(line) for line in fh if line.strip()]
    return out


def _site_today(tz: str, now: datetime | None = None) -> date | None:
    """The site's calendar date in ``tz`` (D-270); None (the container's date) when no zone is given."""
    if not tz:
        return None
    return (now.astimezone(ZoneInfo(tz)) if now else datetime.now(ZoneInfo(tz))).date()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m omop")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ld = sub.add_parser("load")
    ld.add_argument("--lake", type=Path, required=True)
    ld.add_argument("--snapshot")
    ld.add_argument("--tz", default=os.environ.get("TB_TZ") or None)  # none: load_batch refuses (D-315)
    sub.add_parser("status")
    dq = sub.add_parser("dqd")
    dq.add_argument("--json", type=Path)
    # the site's zone for "today" in the plausibility checks (D-270); without it, the container's own date
    dq.add_argument("--tz", default=os.environ.get("TB_TZ") or "")
    vo = sub.add_parser("vocab")
    vo.add_argument("what", choices=["terminology", "code-list", "licensed", "refdata", "local", "athena", "status"])
    vo.add_argument("--rulesets", type=Path)
    vo.add_argument("--system")
    vo.add_argument("--version")
    vo.add_argument("--file", type=Path)
    vo.add_argument("--ws", default="main")
    vo.add_argument("--by", default="operator")
    a = ap.parse_args(argv)
    db = schema.connect()
    try:
        if a.cmd == "vocab":
            print(json.dumps(_vocab(db, a), indent=1, ensure_ascii=False, default=str))
            return 0
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
        res = dqd.run(db, today=_site_today(a.tz))
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


def _vocab(db: Any, a: argparse.Namespace) -> Any:
    from omop import vocab_load as vl

    if a.what == "terminology":
        from criteria_compiler.terminology.mapper import TERM_DIR

        return vl.load_terminology(db, TERM_DIR, by=a.by, rulesets_dir=a.rulesets).as_dict()
    if a.what == "code-list":
        if not (a.system and a.version and a.file):
            raise SystemExit("code-list needs --system, --version and --file")
        codes = vl.read_code_list(a.file)
        return vl.load_code_list(db, a.system, a.version, codes, source=a.file.name, by=a.by,
                                 rulesets_dir=a.rulesets).as_dict()  # fmt: skip
    if a.what == "licensed":
        from adapter import licensed

        versions = {r["kind"]: r["version"] for r in licensed.status() if r["state"] == "loaded"}
        return [r.as_dict() for r in vl.load_licensed(db, licensed.tables(), versions=versions, by=a.by)]
    if a.what == "refdata":
        return [vl.load_refdata_terms(db, sid, rows, version=sid, by=a.by).as_dict()
                for sid, rows in vl.refdata_terms().items()]  # fmt: skip
    if a.what == "athena":
        if not a.file:
            raise SystemExit("athena needs --file (the unpacked bundle's directory)")
        return vl.load_athena(db, a.file, by=a.by).as_dict()
    if a.what == "local":
        return {"mapped": vl.load_local_codes(db, vl.local_code_rows(None, a.ws), by=a.by)}
    return {"terminology_release": vl.terminology_release(db), "releases": vl.releases(db),
            "recompile_needed": vl.recompile_needed(db)}  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
