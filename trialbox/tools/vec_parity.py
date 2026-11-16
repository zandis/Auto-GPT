"""S2b parity between the on-the-fly path and the vector store (T-203b, D-449): ``eval/vec_parity/report.json``.

    TB_TZ=<the site zone> python -m tools.vec_parity --db-url postgresql://... --patients 300 [--out ...]

On a synthetic site (``tools.synth_hospital``, profile ci, seed 42, one Taiwanese site of ``--patients`` patients; no
network, no model), the lake is built with the embedder of the run, its notes are indexed into the vector store
(``vec``, pgvector: the database in ``--db-url``, in schemas of its own prefix, dropped at the end; the site's zone is
``TB_TZ``, D-315), and the SCREEN cascade of every committed ruleset with note criteria runs twice over every
patient: the flag ``vec.s2b`` off (S2b embeds the window sentences on the fly) and on (S2b ranks them from the
stored vectors).

The judge is a deterministic keyword stand-in (:class:`KeywordJudge`): its answer depends only on the excerpts it is
shown, so every difference in the final results comes from a difference in the S2b excerpts. The record counts, per
ruleset, the S2b pairs, how many were ranked from the store and how many fell back, how many excerpt sets differ
between the two runs, and how many patients' final results (tier or any criterion's status) differ.

**This is the hash stub's record.** D-429: the embedder and the S2b threshold refit come from G1. A later card repeats
this run with the chosen embedder (``--embedder model``) and the real judge pair before the flag is switched on at a
site; the record names the embedder model, so the two are never confused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

REF = date(2026, 11, 1)
SEED = 42
OUT = ROOT / "eval" / "vec_parity" / "report.json"
_WORD = 5  # criterion words of at least this length are the stand-in judge's keywords


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


@dataclass
class KeywordJudge:
    """A deterministic stand-in for the judge: ``pass`` quoting the first excerpt sentence that holds a word of the
    criterion, else a confident ``fail`` ("not met") quoting the first excerpt sentence. Records every excerpt set it
    is shown, by patient and criterion text."""

    pid_of: dict[str, str]
    seen: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def judge(self, *, role: str, criterion_text: str, excerpts: list[dict[str, Any]], **_: Any) -> Any:
        from matching.cascade.judge import JudgeReply
        from matching.excerpts import sentences

        pid = self.pid_of.get(str(excerpts[0].get("did")), "?") if excerpts else "?"
        self.seen[(pid, criterion_text, role)] = _sha([(e.get("did"), e.get("text")) for e in excerpts])
        words = {w.lower() for w in criterion_text.replace(",", " ").split() if len(w) >= _WORD}
        for e in excerpts:
            for s in sentences(str(e.get("text") or "")):
                if any(w in s.lower() for w in words):
                    return JudgeReply("pass", 0.9, s, str(e.get("date")), "keyword stand-in", call_id="kw")
        e = excerpts[0]  # no keyword in what it was shown: a confident "not met", as a real judge may say
        first = next(iter(sentences(str(e.get("text") or ""))), "")
        return JudgeReply("fail", 0.95, first or None, str(e.get("date")), "keyword stand-in: no keyword", call_id="kw")


def _count(items: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


def build_site(work: Path, patients: int) -> tuple[Path, str, str]:
    """A synthetic Taiwanese site of ``patients`` patients: its NDJSON folder, snapshot and zone (``TB_TZ``)."""
    from tb_common.config import site_tz

    from tools import omop_parity as parity
    from tools.synth_hospital import run as synth_run

    tz = site_tz()
    snap = (REF - timedelta(days=1)).isoformat()
    synth_run(work / "synth", profile="ci", sites=f"tw-a:TW:{patients}", ref_date=REF, seed=SEED)
    nd = parity._ingest(work, "csv", work / "synth" / "tw-a", snap, tz, "tw_core/demo_his.yaml", "tw-a")
    return nd, snap, tz


def compare(
    lk: Any, rs: Any, snapshot: str, pids: list[str], pid_of: dict[str, str], embedder: Any, language: str = "auto"
) -> dict[str, Any]:
    """One ruleset: the cascade with the flag off and on, and what differs."""
    from matching.cascade.engine import CascadeConfig, run_cascade
    from matching.notelang import cascade_languages
    from vec.s2b import LakeVecSource

    runs = {}
    for flag in ("off", "on"):
        judge = KeywordJudge(pid_of)
        lang, notes_lang = cascade_languages(language, "zh-TW")  # D-987: the synthetic site writes zh-TW notes
        cfg = CascadeConfig(
            study_id=rs.id,
            language=lang,
            notes_language=notes_lang,
            run_date=REF,
            lookback_months=36,
            index_mode="single",
            purpose="screening",
            step_id=f"vec_parity:{flag}",
            sample_per_stratum=None,
            snapshot=snapshot,
            population=pids,
            absence_semantics=False,  # as SCREEN runs it (screen_cascade.screen_with_cascade)
            max_llm_items=10**6,
        )
        source = LakeVecSource(lk, snapshot) if flag == "on" else None
        res = run_cascade(lk, rs, cfg, judge=judge, embedder=embedder, s2b_source=source)
        runs[flag] = (res, judge)
    (off, j_off), (on, j_on) = runs["off"], runs["on"]
    keys = sorted(set(j_off.seen) | set(j_on.seen))
    final = {
        pid: (
            [off.traces[pid].tier, {c: o.status for c, o in sorted(off.traces[pid].outcomes.items())}],
            [on.traces[pid].tier, {c: o.status for c, o in sorted(on.traces[pid].outcomes.items())}],
        )
        for pid in sorted(off.traces)
    }
    detail = on.stage("S2b").detail
    reasons: dict[str, int] = {}
    for t in on.traces.values():
        for r in (t.s2b_source or {}).get("fallback", []):
            reasons[r] = reasons.get(r, 0) + 1
    return {
        "ruleset": rs.id,
        "ruleset_version": rs.version,
        "s2b_pairs": off.stage("S2b").pairs_in,
        "vec_pairs": detail.get("vec_pairs", 0),
        "fallback_pairs": detail.get("vec_fallback_pairs", 0),
        "fallback_reasons_by_patient": dict(sorted(reasons.items())),
        "judged_excerpt_sets": len(keys),
        "excerpt_sets_differ": sum(1 for k in keys if j_off.seen.get(k) != j_on.seen.get(k)),
        "patients": len(final),
        "final_results_differ": sum(1 for a, b in final.values() if a != b),
        "tiers_differ": sum(1 for a, b in final.values() if a[0] != b[0]),
        "excluded_off": sum(1 for a, _ in final.values() if a[0] == "excluded"),
        "excluded_on": sum(1 for _, b in final.values() if b[0] == "excluded"),
        "excluded_only_on": sum(1 for a, b in final.values() if b[0] == "excluded" and a[0] != "excluded"),
        "excluded_only_off": sum(1 for a, b in final.values() if a[0] == "excluded" and b[0] != "excluded"),
        "tier_changes": dict(sorted(_count(f"{a[0]} -> {b[0]}" for a, b in final.values() if a[0] != b[0]).items())),
    }


def run(db_url: str, patients: int, out: Path, work: Path, language: str = "auto") -> dict[str, Any]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from lake.store import Lake
    from matching.cascade.engine import JUDGED
    from tb_common.db import Database
    from vec.index import index_snapshot
    from vec.store import VecStore

    from tools import omop_parity as parity

    nd, snap, tz = build_site(work, patients)
    embedder = HashEmbedder()  # D-429: the stub until G1 names the embedder; its model is in the record
    lake = Lake(work / "lake", tz)
    lake.rebuild(snap, embedder, nd)
    prefix = f"vp{uuid.uuid4().hex[:8]}_"
    url = f"{db_url}{'&' if '?' in db_url else '?'}tb_prefix={prefix}"
    try:
        with VecStore(url, model=embedder.model, dim=embedder.dim) as st:
            stats = index_snapshot(st, lake, snap, embedder)
            lk = LakeLocal(work / "lake", embedder, tz, vec_store=st)
            docs = lk.query("SELECT did, pid FROM document", [], snap).to_pylist()
            pid_of = {str(r["did"]): str(r["pid"]) for r in docs}
            pids = sorted(str(r["pid"]) for r in lk.query("SELECT pid FROM patient", [], snap).to_pylist())
            rows = []
            for d in parity.RULESETS:
                rs = parity.load_ruleset(d)
                if any(c.class_ in JUDGED for c in rs.active()):
                    rows.append(compare(lk, rs, snap, pids, pid_of, embedder, language))
    finally:
        with Database.connect(db_url, "probe") as db:  # drop only this run's schemas
            for (name,) in db.fetchall("SELECT nspname FROM pg_namespace WHERE nspname LIKE ?", (prefix + "%",)):
                db.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    report = {
        "card": "T-203b",
        "decision": "D-449",
        "what": "S2b excerpt sets and final results, flag vec.s2b off (on the fly) against on (the vector store)",
        "site": {
            "generator": "tools.synth_hospital profile ci",
            "seed": SEED,
            "sites": f"tw-a:TW:{patients}",
            "ref_date": REF.isoformat(),
            "snapshot": snap,
        },
        "embedder_model": embedder.model,
        "embedder_note": "the hash stub of DEV and TEST (D-429): repeat with the G1 embedder before a site's flag "
        "is on",
        "judge": "keyword stand-in (tools.vec_parity.KeywordJudge): answers from the excerpts only, no model",
        "indexed": {"notes": stats.notes, "chunks": stats.chunks, "embedded": stats.embedded_new},
        "rulesets": rows,
        "totals": {
            k: sum(int(r[k]) for r in rows)
            for k in (
                "s2b_pairs",
                "vec_pairs",
                "fallback_pairs",
                "judged_excerpt_sets",
                "excerpt_sets_differ",
                "final_results_differ",
                "tiers_differ",
                "excluded_only_on",
                "excluded_only_off",
            )
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db-url", help="a database whose server offers pgvector (as the tests' TB_TEST_DB_URL)")
    ap.add_argument("--patients", type=int, default=300)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument(
        "--language", default="auto", help="the notes' language: auto (read per patient), en, zh-TW, ja (D-987)"
    )
    a = ap.parse_args(argv)
    if not a.db_url:
        ap.error("--db-url must name a database whose server offers pgvector")
    with tempfile.TemporaryDirectory(prefix="vec_parity.") as tmp:
        rep = run(a.db_url, a.patients, a.out, Path(tmp), a.language)
    print(json.dumps(rep["totals"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
