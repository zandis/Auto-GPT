"""Round-1 baseline (INVEST-1 J2): the run ledger on the release code for every set of the round. Prints counts only.

    # the synthetic hospital, one ruleset per process, the two-model note judge on local servers
    python -m bench.invest.baseline night --source <site dir> --work <dir> --out <root> --ruleset GZQO \\
        --judge-url URL --judge-model NAME --verifier-url URL --verifier-model NAME --concurrency 8
    # a lake that has no notes (the real-data twin): coded stages only, no judge; only the aggregate leaves
    python -m bench.invest.baseline coded --lake <lake dir> --tz Asia/Taipei --out <root> --salt-file <file> \\
        --agg <file.json>
    # the repeat row: coded rows of two runs byte-identical? model verdicts differing?
    python -m bench.invest.baseline repeat --a <root>/<run id> --b <root>/<run id>
    # a note set through the frozen bench (cases + final answers) as ledger rows
    python -m bench.invest.baseline noteset --name held --cases <cases.jsonl> --final <final.jsonl> --out <root>

Real data: ``coded`` keeps the ledger where it is written (the salt file is private, mode 600) and writes the aggregate
through ``export.write_agg`` (cells below 10 suppressed, identifiers refused). Nothing here prints a row.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import secrets
import threading
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from bench.invest import export, ledger, match_adapter
from bench.invest.dry_run import LIVE, _git_sha, _lookback


class _Sampled(httpx.Client):
    """An httpx client that adds what the gateway forces on every call (``models/routing.yaml`` ``sampling``), the
    frozen bench's way of calling a server directly; ``urls``: several servers of one build, taken in turn."""

    def __init__(self, timeout: Any, sampling: dict[str, Any], base: str, urls: list[str]) -> None:
        super().__init__(timeout=timeout)
        self.extra, self.base = dict(sampling), base
        self._next = itertools.cycle(urls)
        self._lock = threading.Lock()
        self.posts = Counter[str]()

    def post(self, url: Any, **kw: Any) -> httpx.Response:
        with self._lock:
            host = next(self._next)
            self.posts[host] += 1
        kw["json"] = {**(kw.get("json") or {}), **self.extra}
        return super().post(str(url).replace(self.base, host, 1), **kw)


def _client(urls: str, model: str) -> Any:
    import yaml
    from tb_common.llm import LlmClient

    hosts = [u.rstrip("/") for u in urls.split(",") if u]
    root = Path(__file__).resolve().parents[2]
    sampling = yaml.safe_load((root / "models" / "routing.yaml").read_text(encoding="utf-8"))["sampling"]
    c = LlmClient(hosts[0], model)
    c.http = _Sampled(c.http.timeout, sampling, hosts[0], hosts)
    return c


def _judge(a: argparse.Namespace, lake: Any) -> Any:
    from orchestrator.scenarios.screen_cascade import OrchestratorJudge

    verifier = _client(a.verifier_url, a.verifier_model) if a.verifier_url else None
    return OrchestratorJudge(
        lake=lake, llm=_client(a.judge_url, a.judge_model), prompt="judge", job_id="invest", verifier=verifier,
        in_flight=a.concurrency,
    )  # fmt: skip


def _gold(source: Path, rs: Any) -> dict[tuple[str, str], Any]:
    """The synthetic site's note truth (``note_truth.json``) as ``(pid, criterion id)`` -> label; empty without it."""
    from tools.cascade_e2e import _Truth

    truth = _Truth.load(source)
    if truth is None:
        return {}
    ids = {c.id for c in rs.active()}
    return {(pid, cid): lab for pid, d in truth.notes.items() for cid, lab in d.items() if cid in ids}


def _ingest(source: Path, work: Path, tz: str) -> tuple[Path, date, str]:
    from tools.cascade_e2e import SITE_KEY
    from tools.ingest_local import run_local

    meta = json.loads((source / "meta.json").read_text("utf-8")) if (source / "meta.json").exists() else {}
    run_date = date.fromisoformat(str(meta.get("ref_date", "2026-10-05")))
    lake_dir = work / "ingest" / "lake"
    if not (lake_dir / "CURRENT").exists():  # built once; the night and its repeat read the same snapshot
        snapshot = date.fromordinal(run_date.toordinal() - 1).isoformat()
        site = str(meta.get("site_id", "DEMO-A"))
        run_local(source, work / "ingest", kind="csv", site_id=site, site_key=SITE_KEY, snapshot=snapshot, tz=tz)
    return lake_dir, run_date, (lake_dir / "CURRENT").read_text(encoding="utf-8").strip()


def _cascade(lake: Any, rs: Any, run_date: date, snap: str, judge: Any, concurrency: int, tag: str) -> Any:
    """SCREEN's cascade settings (``screen_with_cascade``) over the whole lake; the hash embedder, as the timed
    nights ran."""
    from embed_service.embedder import HashEmbedder
    from matching.cascade import CascadeConfig, run_cascade

    cfg = CascadeConfig(
        study_id=rs.id, run_date=run_date, lookback_months=max(1, _lookback(rs)), index_mode="single",
        purpose="screening", step_id=f"invest:{tag}", language="zh-TW", notes_language="auto",
        sample_per_stratum=None, snapshot=snap, absence_semantics=False, s2b_when_fits=False, require_retrieval=True,
        max_llm_items=None, llm_concurrency=concurrency,
    )  # fmt: skip
    return run_cascade(lake, rs, cfg, judge=judge, embedder=HashEmbedder(), reviewer=None)


def _write(root: Path, rs: Any, res: Any, snap: str, salt: str, pins: dict[str, Any], sets: dict[str, Any],
           gold: dict[tuple[str, str], Any] | None, pair: bool,
           clock: dict[str, Any]) -> tuple[str, dict[str, Any]]:  # fmt: skip
    header = {
        "code_sha": _git_sha(), "bench_sha": _git_sha(), "model_pins_json": pins, "prompt_shas_json": {},
        "schema_shas_json": {}, "terminology_sha": None, "lake_snapshot_sha": ledger.sha_of_text(snap),
        "ruleset_hashes_json": {rs.id: res.ir_hash}, "sets_json": sets,
    }  # fmt: skip
    rid = ledger.run_id_of(header)
    w = ledger.LedgerWriter(root, rid, header)
    counts = match_adapter.add_cascade(w, rs, res, lake_snapshot=snap, pid_salt=salt, pair=pair, gold=gold or None)
    w.close(clock=clock)
    return rid, counts


def night(a: argparse.Namespace) -> int:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    from tools.cascade_e2e import load_trial

    lake_dir, run_date, snap = _ingest(a.source, a.work, a.tz)
    if a.ingest_only:  # the lake once, copied untouched for every process that reads it
        print(json.dumps({"lake": "built", "snapshot": snap}))
        return 0
    lake = LakeLocal(lake_dir, HashEmbedder(), a.tz)
    rs = load_trial(a.ruleset)
    judge = _judge(a, lake) if a.judge_url else None
    t0 = time.monotonic()
    res = _cascade(lake, rs, run_date, snap, judge, a.concurrency, a.tag)
    secs = round(time.monotonic() - t0, 1)
    pins = {"judge": a.judge_model or None, "verifier": a.verifier_model or None, "embedder": "hash",
            "concurrency": a.concurrency, "temperature": "routing.yaml sampling"}  # fmt: skip
    clock = {"written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cascade_s": secs}
    if judge is not None:
        clock |= {"calls": judge.calls, "failures": judge.failures, "disagreements": judge.disagreements,
                  "tokens_in": judge.tokens_in, "tokens_out": judge.tokens_out,
                  "posts": dict(judge.llm.http.posts)}  # fmt: skip
    rid, counts = _write(a.out, rs, res, snap, a.salt, pins, {"synthetic": [a.ruleset], "tag": a.tag},
                         _gold(a.source, rs), judge is not None and judge.verifier is not None, clock)  # fmt: skip
    con = ledger.connect(a.out, rid)
    bad = match_adapter.reconcile(con, res, rs)
    print(json.dumps({"ruleset": rs.id, "run_id": rid, "rows": counts, "cascade_s": secs,
                      **{k: v for k, v in clock.items() if k not in ("written", "cascade_s")}}))  # fmt: skip
    print("reconcile:", bad or "OK")
    return 0 if not bad else 1


def coded(a: argparse.Namespace) -> int:
    """Coded stages on a lake without notes; the ledger stays under ``--out``, only ``--agg`` may leave the machine."""
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    from tools.cascade_e2e import load_trial

    salt_file = Path(a.salt_file)
    if not salt_file.exists():
        salt_file.parent.mkdir(parents=True, exist_ok=True)
        salt_file.write_text(secrets.token_hex(16), encoding="utf-8")
        os.chmod(salt_file, 0o600)
    salt = salt_file.read_text(encoding="utf-8").strip()
    snap = (Path(a.lake) / "CURRENT").read_text(encoding="utf-8").strip()
    run_date = date.fromisoformat(a.run_date) if a.run_date else date.fromisoformat(snap[:10]).fromordinal(
        date.fromisoformat(snap[:10]).toordinal() + 1)  # fmt: skip
    lake = LakeLocal(Path(a.lake), HashEmbedder(), a.tz)
    ids = tuple(x for x in a.rulesets.split(",") if x)
    header_sets = {"real_twin": list(ids)}
    rss, res, secs = {}, {}, {}
    for rid in ids:
        rss[rid] = load_trial(rid)
        t0 = time.monotonic()
        res[rid] = _cascade(lake, rss[rid], run_date, snap, None, 1, "twin")
        secs[rid] = round(time.monotonic() - t0, 1)
    header = {
        "code_sha": _git_sha(), "bench_sha": _git_sha(), "model_pins_json": {"judge": None, "embedder": "hash"},
        "prompt_shas_json": {}, "schema_shas_json": {}, "terminology_sha": None,
        "lake_snapshot_sha": ledger.sha_of_text(snap), "ruleset_hashes_json": {k: r.ir_hash for k, r in res.items()},
        "sets_json": header_sets,
    }  # fmt: skip
    run_id = ledger.run_id_of(header)
    w = ledger.LedgerWriter(Path(a.out), run_id, header)
    for k in ids:
        match_adapter.add_cascade(w, rss[k], res[k], lake_snapshot=snap, pid_salt=salt)
    w.close(clock={"written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cascade_s": secs})
    con = ledger.connect(Path(a.out), run_id)
    bad = [f"{k}: {m}" for k in ids for m in match_adapter.reconcile(con, res[k], rss[k])]
    known = set(ids) | {c.id for r in rss.values() for c in r.active()}
    agg = export.ledger_agg(con)
    export.write_agg(Path(a.agg), agg, export.pids_of(con), known)  # refuses identifiers, suppresses < 10
    print(json.dumps({"run_id": run_id, "protocols": len(ids), "cascade_s": secs,
                      "agg_rows": {t: len(r) for t, r in agg.items()}}))  # fmt: skip
    print("reconcile:", "OK" if not bad else f"{len(bad)} mismatches")  # the messages carry no identifier, kept short
    return 0 if not bad else 1


def compare(a_dir: Path, b_dir: Path) -> dict[str, Any]:
    """Coded rows (S0, S1) of two runs: identical apart from ``row_key`` and ``run_id``? Model-stage verdicts: the
    share that differ per (patient, protocol, criterion); and the patients whose final-list membership differs."""
    import duckdb

    con = duckdb.connect()
    for name, d in (("ma", a_dir), ("mb", b_dir)):
        con.read_parquet(sorted(str(p) for p in d.glob("match_stage/*/*.parquet"))).create_view(name)

    for sql in VIEWS:
        con.execute(sql)

    def one(sql: str) -> Any:
        return con.execute(sql).fetchone()

    n_a = one("SELECT count(*) FROM ca")[0]
    only_a = one("SELECT count(*) FROM (SELECT * FROM ca EXCEPT ALL SELECT * FROM cb)")[0]
    only_b = one("SELECT count(*) FROM (SELECT * FROM cb EXCEPT ALL SELECT * FROM ca)")[0]
    m = one(
        "SELECT count(*), count(*) FILTER (WHERE la.v IS DISTINCT FROM lb.v) FROM la "
        "FULL JOIN lb USING (pid, protocol_id, criterion_id)"
    )
    t = one(
        "SELECT count(*), count(*) FILTER (WHERE ta.final IS DISTINCT FROM tb.final) FROM ta "
        "FULL JOIN tb USING (pid, protocol_id)"
    )
    return {
        "coded_rows": int(n_a), "coded_only_a": int(only_a), "coded_only_b": int(only_b),
        "coded_identical": only_a == 0 and only_b == 0,
        "model_criteria": int(m[0]), "model_differ": int(m[1]),
        "model_differ_pct": round(100 * m[1] / m[0], 2) if m[0] else None,
        "patients": int(t[0]), "final_differ": int(t[1]),
    }  # fmt: skip


#: over the two runs ``ma`` and ``mb``: coded rows (S0, S1) without the run's own keys; each criterion's last model
#: stage verdict; each patient's final-list membership
VIEWS = (
    "CREATE VIEW ca AS SELECT * EXCLUDE (row_key, run_id) FROM ma WHERE stage IN ('S0', 'S1')",
    "CREATE VIEW cb AS SELECT * EXCLUDE (row_key, run_id) FROM mb WHERE stage IN ('S0', 'S1')",
    "CREATE VIEW la AS SELECT pid, protocol_id, criterion_id, arg_max(verdict, CASE stage WHEN 'S4' THEN 4 "
    "WHEN 'S3' THEN 3 WHEN 'S2b' THEN 2 ELSE 1 END) AS v FROM ma WHERE stage IN ('S2', 'S2b', 'S3', 'S4') GROUP BY ALL",
    "CREATE VIEW lb AS SELECT pid, protocol_id, criterion_id, arg_max(verdict, CASE stage WHEN 'S4' THEN 4 "
    "WHEN 'S3' THEN 3 WHEN 'S2b' THEN 2 ELSE 1 END) AS v FROM mb WHERE stage IN ('S2', 'S2b', 'S3', 'S4') GROUP BY ALL",
    "CREATE VIEW ta AS SELECT pid, protocol_id, final FROM ma WHERE stage = 'tier'",
    "CREATE VIEW tb AS SELECT pid, protocol_id, final FROM mb WHERE stage = 'tier'",
)


ANSWER = {"yes": "T", "no": "F", "unknown": "U", "pass": "T", "fail": "F"}


def noteset(a: argparse.Namespace) -> int:
    """One S3 row per case of a frozen-bench run: the bench's final answer and why, the pair's answers, the gold."""
    cases = {c["id"]: c for c in map(json.loads, a.cases.read_text(encoding="utf-8").splitlines()) if c}
    final = [json.loads(x) for x in a.final.read_text(encoding="utf-8").splitlines() if x.strip()]
    bench_sha = ledger.sha_of_text("".join(sorted(p.name for p in a.final.parent.glob("*"))))
    header = {
        "code_sha": _git_sha(), "bench_sha": a.bench_sha or bench_sha, "model_pins_json": {"bench": "frozen T2"},
        "prompt_shas_json": {}, "schema_shas_json": {}, "terminology_sha": None, "lake_snapshot_sha": None,
        "ruleset_hashes_json": {}, "sets_json": {a.name: len(cases), "cases_sha": ledger.sha_of_text(
            a.cases.read_text(encoding="utf-8"))},
    }  # fmt: skip
    rid = ledger.run_id_of(header)
    w = ledger.LedgerWriter(a.out, rid, header)
    for f in sorted(final, key=lambda r: str(r["id"])):
        c = cases.get(f["id"], {})
        gold = c.get("truth", c.get("gold_answer"))
        w.add("match_stage", a.name, {
            "pid": ledger.content_hash(a.name, f["id"]), "protocol_id": a.name, "criterion_id": str(f["id"]),
            "stage": "S3", "attempt": 0, "inputs_hash": ledger.content_hash(c.get("criterion_text"), c.get("excerpts")),
            "model_raw_json": ledger.canonical_json({"pair": f.get("pair"), "why": f.get("why")}),
            "passages_json": ledger.canonical_json(f.get("quotes")), "verdict": ANSWER.get(str(f.get("answer")), "U"),
            "reason_code": str(f.get("why") or "")[:80] or None, "basis": "pair", "final": True,
            "unknown_kind": c.get("kind"), "gold": ANSWER.get(str(gold)) if gold is not None else None,
        })  # fmt: skip
    w.close(clock={"written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    print(json.dumps({"set": a.name, "run_id": rid, "rows": len(final), "cases": len(cases)}))
    return 0 if len(final) == len(cases) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("night")
    n.add_argument("--source", type=Path, required=True)
    n.add_argument("--work", type=Path, required=True)
    n.add_argument("--out", type=Path, required=True)
    n.add_argument("--ruleset", required=True, choices=LIVE)
    n.add_argument("--tz", default="Asia/Taipei")
    n.add_argument("--tag", default="night")
    n.add_argument("--salt", default="invest-r1-synthetic")
    n.add_argument("--concurrency", type=int, default=8)
    n.add_argument("--ingest-only", action="store_true", help="build the lake under --work and stop")
    n.add_argument("--judge-url", default="", help="one or more servers of one build, comma-separated")
    n.add_argument("--judge-model", default="")
    n.add_argument("--verifier-url", default="")
    n.add_argument("--verifier-model", default="")
    c = sub.add_parser("coded")
    c.add_argument("--lake", required=True)
    c.add_argument("--tz", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--salt-file", required=True)
    c.add_argument("--agg", required=True)
    c.add_argument("--run-date", default="")
    c.add_argument("--rulesets", default=",".join(LIVE))
    r = sub.add_parser("repeat")
    r.add_argument("--a", type=Path, required=True)
    r.add_argument("--b", type=Path, required=True)
    s = sub.add_parser("noteset")
    s.add_argument("--name", required=True)
    s.add_argument("--cases", type=Path, required=True)
    s.add_argument("--final", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--bench-sha", default="")
    a = ap.parse_args(argv)
    if a.cmd == "night":
        return night(a)
    if a.cmd == "coded":
        return coded(a)
    if a.cmd == "repeat":
        print(json.dumps(compare(a.a, a.b)))
        return 0
    return noteset(a)


if __name__ == "__main__":
    raise SystemExit(main())
