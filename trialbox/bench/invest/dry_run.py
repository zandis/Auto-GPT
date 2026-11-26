"""Dry run of the ledger: one synthetic site, every live ruleset, the coded stages (no judge), ledger + reconcile +
repeat check + aggregate export. Synthetic data only; prints counts, never rows.

    python -m bench.invest.dry_run --source <site dir with patient.csv> --work <dir> --out <ledger root> \\
        [--tz <zone>] [--rulesets GZQO,RA-JAK,...] [--repeat]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any

from bench.invest import export, ledger, match_adapter

ROOT = Path(__file__).resolve().parents[2]
LIVE = ("AD-MAB", "GOUT-COH", "GZQO", "NEUR-COH", "ONC-OSI", "RA-BIO", "RA-COH", "RA-JAK")


def _git_sha() -> str:
    if os.environ.get("INVEST_CODE_SHA"):  # a copy of the tree without .git (the machine the run is on)
        return os.environ["INVEST_CODE_SHA"]
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return out.stdout.strip() or "unknown"


def _lookback(rs: Any) -> int:
    feas = rs.manifest.scopes.feas if rs.manifest.scopes else None
    return int(feas.lookback_months) if feas and feas.lookback_months else 36


def cascades(
    source: Path, work: Path, ids: tuple[str, ...], tz: str
) -> tuple[dict[str, Any], dict[str, Any], str, str, dict[str, float]]:
    """Ingest ``source`` once, run the cascade for each ruleset; return (rulesets, results, snapshot, tz, seconds)."""
    from dataclasses import replace

    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from matching.cascade import CascadeConfig, run_cascade

    from tools.cascade_e2e import SITE_KEY, load_trial
    from tools.ingest_local import run_local

    meta = json.loads((source / "meta.json").read_text("utf-8")) if (source / "meta.json").exists() else {}
    run_date = date.fromisoformat(str(meta.get("ref_date", "2026-10-05")))
    site_id = str(meta.get("site_id", "DEMO-A"))
    snapshot = date.fromordinal(run_date.toordinal() - 1).isoformat()
    lake_dir = work / "ingest" / "lake"
    if not (lake_dir / "CURRENT").exists():  # a synthetic lake already built here is reused
        run_local(source, work / "ingest", kind="csv", site_id=site_id, site_key=SITE_KEY, snapshot=snapshot, tz=tz)
    snap = (lake_dir / "CURRENT").read_text(encoding="utf-8").strip()
    lake = LakeLocal(lake_dir, HashEmbedder(), tz)
    rss: dict[str, Any] = {}
    res: dict[str, Any] = {}
    secs: dict[str, float] = {}
    for rid in ids:
        rs = load_trial(rid)
        cfg = CascadeConfig(
            study_id=rid,
            run_date=run_date,
            lookback_months=_lookback(rs),
            purpose="feasibility",
            step_id="invest-dry",
            snapshot=snap,
        )
        t0 = time.monotonic()
        res[rid] = run_cascade(lake, rs, replace(cfg), judge=None, embedder=HashEmbedder(), reviewer=None)
        secs[rid] = round(time.monotonic() - t0, 1)
        rss[rid] = rs
    return rss, res, snap, tz, secs


def write_ledger(root: Path, rss: dict[str, Any], res: dict[str, Any], snap: str) -> tuple[Path, dict[str, Any], str]:
    header = {
        "code_sha": _git_sha(),
        "bench_sha": _git_sha(),
        "model_pins_json": {"judge": None, "embedder": "hash"},
        "prompt_shas_json": {},
        "schema_shas_json": {},
        "terminology_sha": None,
        "lake_snapshot_sha": ledger.sha_of_text(snap),
        "ruleset_hashes_json": {k: r.ir_hash for k, r in sorted(res.items())},
        "sets_json": {"synthetic": sorted(res)},
    }
    rid = ledger.run_id_of(header)
    w = ledger.LedgerWriter(root, rid, header)
    for k in sorted(res):
        match_adapter.add_cascade(w, rss[k], res[k], lake_snapshot=snap, pid_salt="invest-dry")
    manifest = w.close(clock={"written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return w.dir, manifest, rid


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tz", default="UTC", help="the lake's time zone (IANA name)")
    ap.add_argument("--rulesets", default=",".join(LIVE))
    ap.add_argument("--repeat", action="store_true", help="run everything twice and compare the coded rows' hashes")
    a = ap.parse_args(argv)
    ids = tuple(x for x in a.rulesets.split(",") if x)
    rss, res, snap, _tz, secs = cascades(a.source, a.work / "a", ids, a.tz)
    _path, manifest, rid = write_ledger(a.out, rss, res, snap)
    con = ledger.connect(a.out, rid)
    bad: list[str] = []
    for k in sorted(res):
        bad += [f"{k}: {m}" for m in match_adapter.reconcile(con, res[k], rss[k])]
    rows = {k: v["rows"] for k, v in manifest["files"].items()}
    print(
        json.dumps(
            {"run_id": rid, "protocols": len(res), "rows": sum(rows.values()), "files": len(rows), "cascade_s": secs}
        )
    )
    print("reconcile:", bad or "OK")
    known = {k for k in res} | {c.id for r in rss.values() for c in r.active()}
    agg = export.ledger_agg(con)
    export.write_agg(a.out / rid / "ledger_agg.json", agg, export.pids_of(con), known)
    print("ledger_agg: written,", {t: len(r) for t, r in agg.items()})
    same = True
    if a.repeat:
        rss2, res2, snap2, _t, _s = cascades(a.source, a.work / "b", ids, a.tz)
        path2, manifest2, rid2 = write_ledger(a.out / "repeat", rss2, res2, snap2)
        diff = sorted(k for k in manifest["files"] if manifest["files"][k] != manifest2["files"].get(k))
        same = rid == rid2 and not diff
        print(
            "repeat: run_id",
            "same" if rid == rid2 else "DIFFERENT",
            "| files differing:",
            diff or "none",
            "|",
            path2.name,
        )
    return 0 if not bad and same else 1


if __name__ == "__main__":
    raise SystemExit(main())
