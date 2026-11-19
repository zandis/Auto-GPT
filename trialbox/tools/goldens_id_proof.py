"""D-1253: the proof that the goldens moved by ids alone (card item 7).

A patient's record id changed rule once (it now holds the patient). The committed goldens hash every lake column
and every screening outcome, so they move; this tool shows that **nothing but ids and values made from ids** moved.
It builds the goldens' data sets (``tools.goldens.build_sets``) with one checkout's code and dumps every row of every
lake table, the chunker's rows, and per ruleset the FEAS funnel, the candidates and every patient's full outcome
(verdicts, evidence, reasons); then it compares two dumps:

    python tools/goldens_id_proof.py dump --root <master checkout> --out /var/tmp/proof/old
    python tools/goldens_id_proof.py dump --root <this checkout>   --out /var/tmp/proof/new
    python tools/goldens_id_proof.py compare /var/tmp/proof/old /var/tmp/proof/new

``compare`` treats every 32-hex token in any value (a record id, a reference, a pid, a panel component's
``<id>.<code>``, an evidence string ``<id>|<day>``) as an id. It learns one map old token -> new token from the lake
rows whose content without their ids is unique in their table on both sides, refuses a map that is not one-to-one,
and then requires, for **every** row of every table and every outcome: the old row with its ids mapped is the new
row, exactly, a list compared as a set (evidence and references are listed by id, so their order follows the ids);
and every funnel, count and candidate list identical. Pids map to themselves (a patient's pseudonym did not
change). It prints the counts and exits 0 only when all holds. Data sets one side lacks (a set new in this card) are
named and skipped.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOKEN = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")


# ------------------------------------------------------------------------------------------------ dump
def _paths(root: Path) -> None:
    for p in (root / "services", root / "libs", root):
        sys.path.insert(0, str(p))


def _write(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def dump(root: Path, out: Path, work: Path, source: str) -> int:
    _paths(root.resolve())
    # the next night of this checkout's goldens, whichever release builds the sets: which records go follows their
    # content, never their ids (tools/golden_nights.py, loaded from this file's own folder)
    import importlib.util

    import duckdb
    import pyarrow.parquet as pq
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from lake.flatten import SCHEMAS
    from lake.source import force
    from orchestrator.scenarios.evaluate import SqlEngine, structured_candidate
    from tb_common.db import split_url

    from tools import goldens as g
    from tools import omop_parity as parity
    from tools import pglocal

    spec = importlib.util.spec_from_file_location("golden_nights_d1253", Path(__file__).resolve().with_name(
        "golden_nights.py"))  # fmt: skip
    assert spec is not None and spec.loader is not None
    nights = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nights)
    g.next_night = nights.next_night
    work.mkdir(parents=True, exist_ok=True)
    url = g.private_url(work)
    own = split_url(url)[1]
    os.environ.update({"TB_DB_URL": url, "TB_OMOP_DB_URL": url, "TB_LAKE_SOURCE": source})
    pglocal.drop_prefix(url, own)
    try:
        with force(source):
            built = g.build_sets(work)
        rulesets = [parity.load_ruleset(d) for d in parity.RULESETS]
        for b in built:
            base = out / b.name
            for name in SCHEMAS:
                t = pq.read_table(b.lake / "parquet" / f"snapshot={b.snapshot}" / f"{name}.parquet")
                _write(base / "tables" / f"{name}.jsonl.gz", t.to_pylist())
            con = duckdb.connect(str(b.lake / "db" / f"{b.snapshot}.duckdb"), read_only=True)
            try:
                cols = ("did", "chunk_no", "pid", "date", "type", "text", "tok", "sha")
                rows = con.execute(f"SELECT {', '.join(cols)} FROM document_chunk").fetchall()
            finally:
                con.close()
            _write(base / "tables" / "document_chunk.jsonl.gz", [dict(zip(cols, r, strict=True)) for r in rows])
            if not b.rulesets:
                continue
            lk = LakeLocal(b.lake, HashEmbedder(), b.tz)
            pids = sorted(str(r["pid"]) for r in lk.query("SELECT pid FROM patient", [], b.snapshot).to_pylist())
            for rs in rulesets:
                f = parity._feas(lk, rs, b)  # type: ignore[arg-type]
                active = [c for c in rs.active() if c.kind in ("inclusion", "exclusion")]
                from orchestrator.scenarios.evaluate import FILTERED

                structured = {c.id for c in active if c.class_ in FILTERED}
                evals = SqlEngine(lk, b.snapshot).evaluate(rs, pids, b.run_date, [c.id for c in rs.active()])
                cands = sorted(p for p in pids if structured_candidate(rs, evals.get(p), structured))
                outcomes = [{"pid": pid, "results": e.results, "evidence": e.evidence, "reasons": e.reasons}
                            for pid, e in sorted(evals.items())]  # fmt: skip
                _write(base / "rulesets" / f"{rs.id}.funnel.jsonl.gz", [f])
                _write(base / "rulesets" / f"{rs.id}.candidates.jsonl.gz", [{"candidates": cands}])
                _write(base / "rulesets" / f"{rs.id}.outcomes.jsonl.gz", outcomes)
    finally:
        with contextlib.suppress(Exception):
            pglocal.drop_prefix(url, own)
    print(f"dumped {len(built)} data sets from {root} to {out}")
    return 0


# ------------------------------------------------------------------------------------------------ compare
def _read(path: Path) -> list[Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _canon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def _sorted_lists(x: Any) -> Any:
    """Every list as a set (its order may follow the ids: evidence and references are listed by id)."""
    if isinstance(x, dict):
        return {k: _sorted_lists(v) for k, v in x.items()}
    if isinstance(x, list):
        return sorted((_sorted_lists(v) for v in x), key=_canon)
    return x


def _norm(text: str) -> str:
    return _canon(_sorted_lists(json.loads(text)))


def _skeleton(text: str) -> str:
    return _norm(TOKEN.sub("#", text))


class Proof:
    def __init__(self) -> None:
        self.map: dict[str, str] = {}
        self.back: dict[str, str] = {}
        self.problems: list[str] = []
        self.counts: Counter[str] = Counter()

    def learn(self, old: str, new: str, where: str) -> None:
        a, b = TOKEN.findall(old), TOKEN.findall(new)
        if len(a) != len(b):
            self.problems.append(f"{where}: a row with {len(a)} ids became one with {len(b)}")
            return
        for x, y in zip(a, b, strict=True):
            if self.map.setdefault(x, y) != y:
                self.problems.append(f"{where}: id {x[:8]}.. maps to two new ids")
            if self.back.setdefault(y, x) != x:
                self.problems.append(f"{where}: new id {y[:8]}.. comes from two old ids")

    def mapped(self, text: str) -> str:
        return TOKEN.sub(lambda m: self.map.get(m.group(0), "UNMAPPED:" + m.group(0)), text)


def _files(d: Path) -> dict[str, Path]:
    return {str(p.relative_to(d)): p for p in sorted(d.rglob("*.jsonl.gz"))}


def compare(old_dir: Path, new_dir: Path) -> int:
    pr = Proof()
    old_f, new_f = _files(old_dir), _files(new_dir)
    only_new = sorted({k.split("/")[0] for k in new_f} - {k.split("/")[0] for k in old_f})
    only_old = sorted({k.split("/")[0] for k in old_f} - {k.split("/")[0] for k in new_f})
    if only_old:
        pr.problems.append(f"data sets gone: {only_old}")
    common = sorted(set(old_f) & set(new_f))
    missing = sorted(k for k in old_f if k.split("/")[0] not in only_old and k not in new_f)
    pr.problems += [f"{k}: not in the new dump" for k in missing]
    texts: dict[str, tuple[list[str], list[str]]] = {}
    for k in common:
        texts[k] = ([_canon(r) for r in _read(old_f[k])], [_canon(r) for r in _read(new_f[k])])
    # 1. the map, from the lake rows whose content without its ids is unique in its file on both sides (an outcome's
    #    lists are ordered by id, so its tokens are never paired by position: outcomes are checked, not learned from)
    for k, (old, new) in texts.items():
        if len(old) != len(new):
            pr.problems.append(f"{k}: {len(old)} rows became {len(new)}")
            continue
        o_by: dict[str, list[str]] = defaultdict(list)
        n_by: dict[str, list[str]] = defaultdict(list)
        for r in old:
            o_by[_skeleton(r)].append(r)
        for r in new:
            n_by[_skeleton(r)].append(r)
        if Counter({s: len(v) for s, v in o_by.items()}) != Counter({s: len(v) for s, v in n_by.items()}):
            pr.problems.append(f"{k}: the rows' content without their ids differs")
            continue
        if "/tables/" not in k:
            continue
        for s, rows in o_by.items():
            if len(rows) == 1:
                pr.learn(rows[0], n_by[s][0], k)
    # 2. every row of every file: the old row with its ids mapped is the new row
    for k, (old, new) in texts.items():
        if len(old) != len(new):
            continue
        got = Counter(_norm(pr.mapped(r)) for r in old)
        want = Counter(_norm(r) for r in new)
        if got != want:
            bad = sum((got - want).values())
            pr.problems.append(f"{k}: {bad} rows differ once the old ids are mapped")
        pr.counts["rows"] += len(old)
        pr.counts["files"] += 1
    # 3. a patient's pseudonym is the same: every pid maps to itself
    for k, (old, _new) in texts.items():
        if k.endswith("tables/patient.jsonl.gz"):
            for r in old:
                pid = json.loads(r).get("pid")
                if pid and pr.map.get(pid, pid) != pid:
                    pr.problems.append(f"{k}: a patient's pid changed")
    changed = sum(1 for a, b in pr.map.items() if a != b)
    print(json.dumps({"files": pr.counts["files"], "rows": pr.counts["rows"], "ids": len(pr.map),
                      "ids_changed": changed, "ids_same": len(pr.map) - changed, "new_data_sets": only_new,
                      "problems": len(pr.problems)}, indent=1))  # fmt: skip
    by_file = Counter(p.split(": ", 1)[0] for p in pr.problems)
    for f, n in by_file.most_common():
        print(f"PROBLEMS {n:6d} {f}")
    for p in pr.problems[:20]:
        print("PROBLEM", p)
    if not pr.problems:
        print("PROVED: every row, funnel, candidate list and outcome is the same once the old ids are mapped, one to "
              "one; nothing else moved")  # fmt: skip
    return 1 if pr.problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--root", type=Path, required=True, help="the checkout whose code builds the data sets")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--work", type=Path, help="scratch for the builds (default <out>.work)")
    d.add_argument("--source", choices=("legacy", "omop"), default="legacy")
    c = sub.add_parser("compare")
    c.add_argument("old", type=Path)
    c.add_argument("new", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "dump":
        return dump(a.root, a.out, a.work or a.out.with_name(a.out.name + ".work"), a.source)
    return compare(a.old, a.new)


if __name__ == "__main__":
    sys.exit(main())
