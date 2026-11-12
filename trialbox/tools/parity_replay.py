"""Offline model-gate replay (NFR-PERF-08 / N-11, NFR-PERF-09 / N-12; D-111). Calls no model and no network.

N-11 (SIGIR, TrialGPT's physician labels): eligible patient x trial pairs lost when the judge and the verifier must
both block a criterion and the deterministic filters decide the ``filter`` criteria first
(:func:`tools.trialgpt_compare.filter_first`). Scored from the recorded answers in
``eval/trialgpt_compare/results/raw``. Gate: EN <= 5, JA <= 4, zh-TW <= 2 (provisional), never above 8 of 79.

N-12 (TREC CT 2021/22): eligible pairs wrongly dropped under filter-first <= 5 %, gated on the UNADJUSTED figure
(D-343):
``1 - (1 - q) ** (llm_share * criteria_per_trial)`` from the measured inputs recorded by ``tools.hospital_sim project``
(``eval/hospital_sim/results/``). The audit-adjusted figure (that times the audited share of drops that are model
errors, ``eval/trec_ct/AUDIT.md``) is printed as a labelled note and never sets the status: the label check was by an AI
assistant, not a clinician.

For each build the replay says which recordings exist and, when one is missing, exactly which file a GPU run must
produce (``python -m tools.trialgpt_compare run --pipelines trialbox ...`` on the card, see
``docs/VALIDATION.md`` §3).

    python -m tools.parity_replay                   # table + eval/parity/replay.json
    python -m tools.parity_replay --check           # exit 1 when a recorded number does not reproduce
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import mlbench  # noqa: E402
from tools import trialgpt_compare as tc  # noqa: E402

RAW = ROOT / "eval" / "trialgpt_compare" / "results" / "raw"
RESULTS = ROOT / "eval" / "trialgpt_compare" / "results"
PROJECTION = ROOT / "eval" / "hospital_sim" / "results" / "project_50000.json"
OUT = ROOT / "eval" / "parity" / "replay.json"
LANGS = ("en", "ja", "zh-TW")
GATE_N11 = {"en": 5, "ja": 4, "zh-TW": 2}  # NFR-PERF-08: measured baseline + 1; zh-TW provisional
N11_CAP = 8  # never above 8 of 79
GATE_N12 = 0.05


@dataclass(frozen=True)
class Build:
    name: str
    judge: str  # recorded run name, as in ``trialbox__<org>__<model>__<lang>.jsonl.gz``
    verifier: str
    note: str


BUILDS = (
    Build(
        "deployed files (CON-12, on a card)",
        "local/gemma-4-26b-a4b-nvfp4",
        "local/qwen3.5-9b-awq",
        "nvidia/Gemma-4-26B-A4B-NVFP4 + cyankiwi/Qwen3.5-9B-AWQ-4bit on vLLM v0.32.0, "
        "RTX PRO 6000 capped to 5090 limits, 2026-11-06",
    ),
    Build(
        "same models, API 4-bit (proxy)",
        "google/gemma-4-26b-a4b-it@fp4",
        "qwen/qwen3.5-9b",
        "OpenRouter provider precision, 2026-11-05/07; not the deployed files",
    ),
)


def raw_file(run: str, lang: str) -> Path:
    org, model = run.split("/", 1)
    return RAW / f"trialbox__{org}__{model}__{lang}.jsonl.gz"


def _load(p: Path) -> list[dict[str, Any]]:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def criteria() -> tuple[dict[str, mlbench.Pair], str]:
    """The scored criteria: the 1,000 that are in NCBI's ``trial_info.json`` word for word when that cache exists
    (as ``trialgpt_compare score`` does), else all 1,015 annotated ones. On every recorded run both sets give the same
    lost-pair count (the 15 extra criteria never decide a pair); ``--check`` verifies it against the recorded
    tables."""
    pairs = mlbench.load_pairs()
    if tc.TRIALS_FILE.exists():
        comp = tc.comparable(pairs, tc.trials())
        return {p.annotation_id: p for p in comp}, f"{len(comp)} criteria (trial_info.json)"
    return {p.annotation_id: p for p in pairs}, f"{len(pairs)} criteria (all annotated; trial_info.json not cached)"


def both_must_block(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same rule as :func:`tools.trialgpt_compare.filter_first_table`: a criterion blocks only when both block."""
    rb = {r["annotation_id"]: r for r in b}
    out = []
    for r in a:
        o = rb.get(r["annotation_id"]) or {"label": None}
        block = (r["label"] or "") in mlbench.BLOCKS and (o["label"] or "") in mlbench.BLOCKS
        lab = r["label"] if block or (r["label"] or "") not in mlbench.BLOCKS else "not enough information"
        out.append(r | {"label": lab})
    return out


def n11(build: Build, lang: str, by_id: dict[str, mlbench.Pair], rt: dict[tuple[str, str], str]) -> dict[str, Any]:
    need = [raw_file(build.judge, lang), raw_file(build.verifier, lang)]
    missing = [str(p.relative_to(ROOT)) for p in need if not p.exists()]
    if missing:
        return {"lang": lang, "status": "missing", "missing": missing}
    a, b = (_load(p) for p in need)
    a = [r for r in a if r["annotation_id"] in by_id]
    rows = tc.filter_first(both_must_block(a, b), by_id, rt)
    m = mlbench.score(rows, by_id)
    lost = round(m["trial_false_exclusion"] * m["trials_open"])
    gate = GATE_N11[lang]
    return {
        "lang": lang,
        "status": "pass" if lost <= gate and lost <= N11_CAP else "fail",
        "lost": lost,
        "of": m["trials_open"],
        "gate": gate,
        "block_recall": round(m["block_recall"], 3),
        "false_block_rate": round(m["false_block_rate"], 4),
        "criteria": m["n"],
        "llm_share": round(sum(r["route"] in ("notes", "mixed") for r in rows) / max(1, len(rows)), 3),
    }


def recorded_n11(build: Build, lang: str) -> int | None:
    """The lost-pair count in the committed ``filter_first_<lang>.json`` table, when the pair is there."""
    p = RESULTS / f"filter_first_{lang}.json"
    if not p.exists():
        return None
    t = json.loads(p.read_text(encoding="utf-8"))
    for key in (f"{build.judge}+{build.verifier}", f"{build.verifier}+{build.judge}"):
        if key in t:
            v: float = t[key]["trial_false_exclusion"] * t[key]["trials_open"]
            return round(v)
    return None


def n12() -> dict[str, Any]:
    if not PROJECTION.exists():
        return {"status": "missing", "missing": [str(PROJECTION.relative_to(ROOT))]}
    rec = json.loads(PROJECTION.read_text(encoding="utf-8"))
    par, inp = rec["parameters"], rec["measured_inputs"]
    q = inp["trec_per_criterion_false_block"]
    k = par["llm_share_of_criteria"] * inp["criteria_per_trial (TREC sample)"]
    hit, sampled = par["audit_model_errors_of_sampled"]

    def lost(qq: float) -> float:
        return float(1 - (1 - qq) ** k)

    unadjusted = lost(q["point"])
    point = unadjusted * hit / sampled
    rows = {r["kind"]: r["share_dropped"] for r in rec["per_year"]["wrongly_dropped"] if r["lang"] == "en"}
    recorded, recorded_adj = rows["raw"], rows["audit_adjusted"]
    return {
        # D-343: the gate is the unadjusted figure. The audit-adjusted one rests on a model's check of the labels, not a
        # clinician's, and is a note only: it never sets the status.
        "status": "pass" if unadjusted <= GATE_N12 else "fail",
        "basis": "unadjusted",
        "models": par["models"],
        "unadjusted_loss": round(unadjusted, 4),
        "recorded_point": recorded["point"],
        "recorded_95": [recorded["p2.5"], recorded["p97.5"]],
        "gate": GATE_N12,
        "note_audit_adjusted": {
            "projected_true_loss": round(point, 4),
            "recorded_point": recorded_adj["point"],
            "recorded_95": [recorded_adj["p2.5"], recorded_adj["p97.5"]],
            "label": "note only, not a gate (D-343): the label check was by an AI assistant, not a clinician",
        },
        "inputs": {
            "per_criterion_false_block_q": q["point"],
            "llm_share": par["llm_share_of_criteria"],
            "criteria_per_trial": inp["criteria_per_trial (TREC sample)"],
            "audit_model_errors": f"{hit}/{sampled} (Claude, not a clinician)",
        },
        "measured_on": "OpenRouter provider precision (API 4-bit), not the deployed files",
        "missing_for_deployed_files": [
            "eval/trec_ct/results/raw/local__gemma-4-26b-a4b-nvfp4.jsonl.gz",
            "eval/trec_ct/results/raw/local__qwen3.5-9b-awq.jsonl.gz",
            ".cache/trec_ct/qrels2021.txt, qrels2022.txt, sample_trials.json (NIST/NCBI, to recompute q from them)",
        ],
    }


def replay() -> dict[str, Any]:
    by_id, basis = criteria()
    rt = tc.routes()
    out: dict[str, Any] = {"basis": basis, "n11": [], "n12": n12()}
    for b in BUILDS:
        rows = []
        for lang in LANGS:
            r = n11(b, lang, by_id, rt)
            r["recorded"] = recorded_n11(b, lang)
            rows.append(r)
        out["n11"].append({"build": b.name, "judge": b.judge, "verifier": b.verifier, "note": b.note, "langs": rows})
    return out


def table(res: dict[str, Any]) -> str:
    lines = [f"N-11 SIGIR filter-first, eligible pairs lost of 79 ({res['basis']})"]
    for b in res["n11"]:
        lines.append(f"  {b['build']}: {b['judge']} + {b['verifier']}")
        for r in b["langs"]:
            if r["status"] == "missing":
                lines.append(f"    {r['lang']:6} MISSING  {', '.join(r['missing'])}")
            else:
                rec = "" if r["recorded"] is None else f" (recorded {r['recorded']})"
                lines.append(
                    f"    {r['lang']:6} {r['lost']} / {r['of']}  gate <= {r['gate']}  {r['status'].upper()}{rec}  "
                    f"block recall {r['block_recall']}"
                )
    m = res["n12"]
    if m["status"] == "missing":
        lines.append(f"N-12 MISSING {m['missing']}")
    else:
        lines.append(
            f"N-12 TREC CT unadjusted loss {m['unadjusted_loss']:.1%} (recorded {m['recorded_point']:.1%}, "
            f"95 % {m['recorded_95'][0]:.1%}-{m['recorded_95'][1]:.1%}), gate <= {m['gate']:.0%}: {m['status'].upper()}"
            f"  [{m['measured_on']}]"
        )
        a = m["note_audit_adjusted"]
        lines.append(
            f"  note (not a gate): audit-adjusted {a['projected_true_loss']:.1%} (recorded {a['recorded_point']:.1%}); "
            f"{a['label']}"
        )
    return "\n".join(lines)


def reproduces(res: dict[str, Any]) -> list[str]:
    bad = []
    for b in res["n11"]:
        for r in b["langs"]:
            if r["status"] != "missing" and r["recorded"] is not None and r["recorded"] != r["lost"]:
                bad.append(f"{b['build']} {r['lang']}: replay {r['lost']} vs recorded {r['recorded']}")
    m = res["n12"]
    if m["status"] != "missing":
        if abs(m["unadjusted_loss"] - m["recorded_point"]) > 0.0005:
            bad.append(f"N-12: replay {m['unadjusted_loss']} vs recorded {m['recorded_point']}")
        a = m["note_audit_adjusted"]
        if abs(a["projected_true_loss"] - a["recorded_point"]) > 0.0005:
            bad.append(f"N-12 adjusted note: replay {a['projected_true_loss']} vs recorded {a['recorded_point']}")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true", help="exit 1 when a recorded number does not reproduce")
    a = ap.parse_args(argv)
    res = replay()
    res["reproduces"] = not reproduces(res)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(table(res))
    for line in reproduces(res):
        print("DOES NOT REPRODUCE:", line)
    return 1 if a.check and not res["reproduces"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
