"""Judge bake-off for screening (D-181): any OpenAI-compatible endpoint, the product's judge prompt and parser.

    python -m tools.judge_bakeoff --stub --out /tmp/jb-stub                     # offline: the built-in stub server
    python -m tools.judge_bakeoff --write-set eval/judge_bakeoff/set.jsonl      # freeze the item set (no model call)
    TB_BAKEOFF_API_KEY=... python -m tools.judge_bakeoff --base-url http://127.0.0.1:8000/v1 \\
        --served-name gemma-4-31b-it --expect-root google/gemma-4-31B-it --set <set.jsonl> --out <dir>
    python -m tools.judge_bakeoff --compare <dirA> <dirB>                       # side by side, from metrics.json

Every item goes through ``orchestrator.scenarios.evaluate.NoteJudge.judge_excerpts`` with one judge and no verifier:
the registry prompt ``judge`` (newest version), ``tb_common.llm.chat_json`` (structured output, schema check, one
retry) and ``postprocess`` (the quote must be in an excerpt, else ``unknown``), then ``eligibility(kind, verdict)``.
So the harness scores what the box would do with that model, not a separate prompt.

The items (``--sources``):

* ``synthetic``: ``tests/fixtures/llm/judge_set.jsonl`` from :mod:`tools.make_judge_set` (the synthetic hospital,
  planted note truth: pass, fail or unknown per criterion); the criterion kind from the ruleset IR.
* ``medtxt``: :mod:`tools.medtxt_eval`'s items (real Japanese reports, CC BY 4.0), the ``strict`` slice only, ja and
  en; "Patients with <finding>." is an exclusion: positive -> pass, stated absent -> fail, suspected and not
  mentioned -> unknown. Needs ``python -m tools.medtxt_eval fetch`` first.
* ``trec_ct``: :mod:`tools.trec_ct_eval`'s NIST-eligible pairs (``--trec-pairs`` of them, seeded): every criterion of
  an eligible pair should not exclude (gold ``not_excluded``). The label is per pair and noisy
  (``eval/trec_ct/AUDIT.md``), so these items are reported, with eligible pairs lost, but not in the gate. Needs
  ``python -m tools.trec_ct_eval fetch``.

What is scored (``metrics.json``, per source and for the gated sources together):

* **wrong exclusions**: the judge excluded (eligibility ``fail``) where the gold does not exclude. The rate is over
  the judge's exclusions (Study A's "among note-excluded"), with a Wilson 95 % interval and a patient-cluster bootstrap
  interval; also over the items whose gold does not exclude. **Gate: rate <= 2 %.**
* **precision of "fits"**: of the judge's ``pass`` eligibilities, the share the gold also passes.
* **unknown handling**: an ``unknown`` answer never excludes (gate: 0); how often the judge abstains when the gold is
  unknown, and how often it excludes there.
* **citation validity**: of the model's decided answers, the share whose quote occurs in an excerpt (the product's
  ``quote_in``) and whose ``quote_date`` is that excerpt's date. An invalid quote becomes ``unknown`` (never excludes).
* **latency and tokens** per call (p50, p95, max; prompt and completion tokens).
* **served-name pin**: before any item, ``/v1/models`` must list ``--served-name`` (and its ``root`` must equal
  ``--expect-root`` when given); every response must report that name (gate: 0 mismatches).
* the product's model-down rule: more than 10 % calls without an answer fails the run.

Relation to :mod:`tools.bakeoff` / :mod:`tools.bakeoff_live`: those choose a hosted model for the ``judge_ml`` task
through a tb-gateway with the ``mlbench`` prompt and the SIGIR annotations, scored by agreement and cost. This tool
is the screening-safety gate of one served model, for example a local vLLM on a GPU VM, with the box's own judge
prompt and parser, scored by wrong exclusions. It reuses their pieces: ``_pct`` and the retry backoff from
:mod:`tools.bakeoff_live`, ``rate`` / ``wilson`` / ``cluster_ci`` from :mod:`tools.trec_ct_eval`, the item builders of
:mod:`tools.medtxt_eval` and :mod:`tools.trec_ct_eval`, the judge stub of ``services/llm_stub``.

The endpoint key is read from the environment variable named by ``--key-env`` (default ``TB_BAKEOFF_API_KEY``) and
sent as a bearer token; it is never printed and never written to the results. Outputs in ``--out``: ``rows.jsonl``
(per item: ids, gold, the answer's verdict, reason codes, latency, tokens; no note text, no quote), ``metrics.json``
and ``metrics.md``. Exit 0 gate passed, 1 gate failed, 2 usage error, 3 the served-name pin refused the endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from tb_common.llm import LlmClient, LlmError, LlmResult, LlmSchemaError  # noqa: E402
from tb_common.quotes import quote_in  # noqa: E402

from tools.bakeoff_live import BACKOFF_S, MAX_WORKERS, _pct  # noqa: E402
from tools.trec_ct_eval import rate  # noqa: E402

SYNTH_SET = ROOT / "tests" / "fixtures" / "llm" / "judge_set.jsonl"
SOURCES = ("synthetic", "medtxt", "trec_ct")
GATED = {"synthetic": True, "medtxt": True, "trec_ct": False}
WRONG_EXCLUSION_MAX = 0.02
SEED = 20261109
# MedTxt reports and TREC topics carry no dates: one fixed date for the excerpts and the index date, so a time window
# in the prompt never hides them
UNDATED = "2020-01-01"
DEFAULT_KEY_ENV = "TB_BAKEOFF_API_KEY"
STUB_NAME = "trialbox-stub"
FETCH = {"medtxt": "python -m tools.medtxt_eval fetch", "trec_ct": "python -m tools.trec_ct_eval fetch"}


# ---------------------------------------------------------------------------------------------------------- items
@dataclass
class Item:
    id: str
    source: str
    cluster: str  # the patient or report: bootstrap unit
    kind: str  # inclusion | exclusion
    criterion_text: str
    note_question: str
    index_date: str
    excerpts: list[dict[str, Any]]
    gold: str  # pass | fail | unknown (answer to note_question) | not_excluded (eligibility is not fail)
    gated: bool
    pair: str = ""  # trec_ct: patient|trial


def eligibility(kind: str, predicate: str) -> str:
    """The product's mapping (``evaluate.eligibility``) from a note answer to the criterion's eligibility."""
    from orchestrator.scenarios.evaluate import eligibility as _elig

    return str(_elig(kind, {"pass": True, "fail": False}.get(predicate)))


def gold_eligibility(it: Item) -> str:
    return "not_fail" if it.gold == "not_excluded" else eligibility(it.kind, it.gold)


def _ir_kind(criterion_id: str) -> str:
    path = ROOT / "rulesets" / criterion_id.rsplit("-", 2)[0] / "ir" / f"{criterion_id}.json"
    return str(json.loads(path.read_text(encoding="utf-8"))["kind"])


def synthetic_items(path: Path = SYNTH_SET) -> list[Item]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        site, mrn, _ = str(d["id"]).split(":", 2)
        out.append(
            Item(
                id=f"synthetic:{d['id']}",
                source="synthetic",
                cluster=f"{site}:{mrn}",
                kind=_ir_kind(d["criterion_id"]),
                criterion_text=d["criterion_text"],
                note_question=d["note_question"],
                index_date=d["index_date"],
                excerpts=d["excerpts"],
                gold=d["gold"],
                gated=GATED["synthetic"],
            )
        )
    return out


MEDTXT_GOLD = {"positive": "pass", "negative": "fail", "suspicious": "unknown", "absent": "unknown"}


def medtxt_items(langs: tuple[str, ...] = ("ja", "en")) -> list[Item]:
    from tools import medtxt_eval

    items, notes = medtxt_eval.dataset()
    out = []
    for it in items:
        if not it["strict"]:
            continue  # a negative or suspicious tag contradicted elsewhere in the report: no report-level truth
        crit = f"Patients with {it['finding']}."
        for lang in langs:
            text = " ".join(notes[lang][it["report"]])
            out.append(
                Item(
                    id=f"medtxt:{lang}:{it['id']}",
                    source="medtxt",
                    cluster=str(it["report"]),
                    kind="exclusion",
                    criterion_text=crit,
                    note_question=crit,
                    index_date=UNDATED,
                    excerpts=[{"date": UNDATED, "note_type": "report", "text": text}],
                    gold=MEDTXT_GOLD[str(it["certainty"])],
                    gated=GATED["medtxt"],
                )
            )
    return out


def trec_items(pairs: int = 200, seed: int = SEED) -> list[Item]:
    from tools import trec_ct_eval

    sampled, notes, _, _ = trec_ct_eval.dataset()
    eligible = [p for p in sampled if p["label"] == "2"]
    random.Random(seed).shuffle(eligible)
    out = []
    for p in sorted(eligible[:pairs] if pairs > 0 else eligible, key=lambda p: (p["patient"], p["trial"])):
        text = " ".join(notes[p["patient"]])
        for i, (kind, crit) in enumerate(p["criteria"]):
            out.append(
                Item(
                    id=f"trec_ct:{p['patient']}|{p['trial']}|{i}",
                    source="trec_ct",
                    cluster=str(p["patient"]),
                    kind=str(kind),
                    criterion_text=str(crit),
                    note_question=str(crit),
                    index_date=UNDATED,
                    excerpts=[{"date": UNDATED, "note_type": "topic", "text": text}],
                    gold="not_excluded",
                    gated=GATED["trec_ct"],
                    pair=f"{p['patient']}|{p['trial']}",
                )
            )
    return out


def build_set(
    sources: tuple[str, ...], *, n_per_source: int = 0, trec_pairs: int = 200, seed: int = SEED
) -> tuple[list[Item], dict[str, str]]:
    """Items from each source (``n_per_source`` > 0: a seeded sample of that many) and a note per skipped source."""
    items: list[Item] = []
    skipped: dict[str, str] = {}
    for s in sources:
        try:
            got = (
                trec_items(trec_pairs) if s == "trec_ct" else synthetic_items() if s == "synthetic" else medtxt_items()
            )
        except FileNotFoundError:
            skipped[s] = f"data not fetched: {FETCH.get(s, 'missing file')}"
            continue
        if n_per_source > 0 and s != "trec_ct" and len(got) > n_per_source:
            got = sorted(random.Random(f"{seed}:{s}").sample(got, n_per_source), key=lambda i: i.id)
        items.extend(got)
    return items, skipped


def write_set(items: list[Item], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(asdict(i), ensure_ascii=False, sort_keys=True) + "\n" for i in items)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


def read_set(path: Path) -> tuple[list[Item], str]:
    text = path.read_text(encoding="utf-8")
    items = [Item(**json.loads(x)) for x in text.splitlines() if x.strip()]
    return items, hashlib.sha256(text.encode()).hexdigest()


def set_sha(items: list[Item]) -> str:
    text = "".join(json.dumps(asdict(i), ensure_ascii=False, sort_keys=True) + "\n" for i in items)
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------------------------- client and pin
class PinRefused(RuntimeError):
    pass


_local = threading.local()


class BakeoffClient(LlmClient):
    """``LlmClient`` (the product's only LLM entry point) plus what the bake-off measures: the parsed answer before
    post-processing, the model name each response reports, latency, and retries of transport errors (not of
    schema errors: those count as the model not answering, as in the product)."""

    def __init__(self, base_url: str, served_name: str, *, key: str = "", backoff: tuple[float, ...] = BACKOFF_S):
        super().__init__(base_url, served_name)
        if key:
            self.http.headers["Authorization"] = f"Bearer {key}"
        self.http.event_hooks["response"].append(self._seen)
        self.backoff = backoff

    @staticmethod
    def _seen(resp: httpx.Response) -> None:
        if resp.request.method == "POST" and resp.status_code < 400:
            resp.read()
            try:
                _local.served = str(resp.json().get("model") or "")
            except ValueError:
                _local.served = ""

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        _local.raw = None
        _local.served = ""
        _local.attempts = 0
        t0 = time.perf_counter()
        try:
            for i in range(len(self.backoff) + 1):
                _local.attempts = i + 1
                try:
                    res = super().chat_json(prompt_id, variables, schema, **kw)
                    break
                except LlmSchemaError:
                    raise
                except LlmError:
                    if i == len(self.backoff):
                        raise
                    time.sleep(self.backoff[i])
            _local.raw = res
            return res
        finally:
            _local.latency = time.perf_counter() - t0


def pin_check(http: httpx.Client, base_url: str, served_name: str, expect_root: str = "") -> dict[str, Any]:
    """``/v1/models`` must list ``served_name``; with ``expect_root`` its ``root`` (vLLM: the weights it loaded) must
    equal it. Returns that entry (id, root, max_model_len) for the results."""
    try:
        resp = http.get(f"{base_url.rstrip('/')}/models")
        resp.raise_for_status()
        listed = {str(m.get("id")): m for m in resp.json().get("data", [])}
    except (httpx.HTTPError, ValueError) as e:
        raise PinRefused(f"pin refused: {base_url}/models did not answer ({type(e).__name__})") from e
    m = listed.get(served_name)
    if m is None:
        raise PinRefused(f"pin refused: served name {served_name!r} not in /v1/models ({sorted(listed)})")
    if expect_root and str(m.get("root") or "") != expect_root:
        raise PinRefused(f"pin refused: {served_name!r} serves root {m.get('root')!r}, expected {expect_root!r}")
    return {k: m.get(k) for k in ("id", "root", "max_model_len", "owned_by")}


# ------------------------------------------------------------------------------------------------------- run
@dataclass
class Row:
    id: str
    source: str
    cluster: str
    pair: str
    kind: str
    gold: str
    gated: bool
    raw_verdict: str = ""  # the model's parsed answer before the quote check ("" = no answer)
    quote_found: bool | None = None  # decided answers only
    quote_date_ok: bool | None = None
    predicate: str = "unknown"  # after the product's post-processing
    reason: str = ""
    eligibility: str = "unknown"
    gold_eligibility: str = "unknown"
    served_model: str = ""
    latency_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: int = 0
    error: str = ""  # exception class only, never its text


def judge_item(client: BakeoffClient, it: Item) -> Row:
    from orchestrator.scenarios.evaluate import NoteJudge

    for k in ("raw", "served", "attempts", "latency"):
        _local.__dict__.pop(k, None)
    row = Row(it.id, it.source, it.cluster, it.pair, it.kind, it.gold, it.gated, gold_eligibility=gold_eligibility(it))
    if not it.excerpts:  # the product asks no model then (``judge_patient``: no notes -> unknown)
        row.reason = "no_notes"
        return row
    judge = NoteJudge(lake=None, llm=client)
    r = judge.judge_excerpts(
        it.criterion_text, it.note_question, date.fromisoformat(it.index_date[:10]), it.excerpts, "full_record"
    )
    row.predicate, row.reason = r.predicate, str(r.reason or "")
    row.eligibility = eligibility(it.kind, r.predicate)
    row.latency_s = round(float(getattr(_local, "latency", 0.0)), 4)
    row.attempts = int(getattr(_local, "attempts", 0))
    row.served_model = str(getattr(_local, "served", ""))
    raw: LlmResult | None = getattr(_local, "raw", None)
    if raw is None:
        row.error = "no_answer" if judge.failures else ""
        return row
    row.tokens_in, row.tokens_out = raw.tokens_in, raw.tokens_out
    row.raw_verdict = str(raw.data.get("verdict", "unknown"))
    if row.raw_verdict in ("pass", "fail"):
        q = str(raw.data.get("quote") or "")
        hit = next((e for e in it.excerpts if quote_in(q, str(e["text"]))), None)
        row.quote_found = hit is not None
        row.quote_date_ok = hit is not None and str(raw.data.get("quote_date") or "")[:10] == str(hit["date"])[:10]
    return row


def run(client: BakeoffClient, items: list[Item], workers: int = 4) -> list[Row]:
    with ThreadPoolExecutor(max(1, min(workers, MAX_WORKERS))) as ex:
        return list(ex.map(lambda it: judge_item(client, it), items))


# --------------------------------------------------------------------------------------------------- scoring
def _share(k: int, n: int) -> dict[str, Any]:
    from tools.trec_ct_eval import wilson

    return {"k": k, "n": n, "rate": round(k / n, 4) if n else 0.0, "wilson95": [round(x, 4) for x in wilson(k, n)]}


def _rate(flags: list[tuple[str, bool]]) -> dict[str, Any]:
    r = rate(flags)
    return {
        "k": r["k"],
        "n": r["n"],
        "rate": round(r["rate"], 4),
        "wilson95": [round(x, 4) for x in r["wilson95"]],
        "cluster95": [round(x, 4) for x in r["cluster95"]],
    }


def score(rows: list[Row], served_name: str = "") -> dict[str, Any]:
    answered = [r for r in rows if r.raw_verdict]
    asked = [r for r in rows if r.reason != "no_notes"]
    excluded = [r for r in rows if r.eligibility == "fail"]
    wrong = [(r.cluster, r.gold_eligibility != "fail") for r in excluded]
    not_fail_gold = [r for r in rows if r.gold_eligibility != "fail"]
    fits = [r for r in rows if r.eligibility == "pass" and r.gold != "not_excluded"]
    decided = [r for r in answered if r.quote_found is not None]
    model_unknown = [r for r in rows if r.predicate == "unknown"]
    gold_unknown = [r for r in rows if r.gold == "unknown"]
    determinate = [r for r in rows if r.gold in ("pass", "fail", "unknown")]
    lat = [r.latency_s for r in answered]
    out: dict[str, Any] = {
        "n": len(rows),
        "answered": len(answered),
        "no_notes": len(rows) - len(asked),
        "no_answer": _share(sum(bool(r.error) for r in asked), len(asked)),
        "wrong_exclusion": {
            **_rate(wrong),
            "of_not_excluding_gold": _share(sum(r.eligibility == "fail" for r in not_fail_gold), len(not_fail_gold)),
        },
        "fits_precision": _share(sum(r.gold_eligibility == "pass" for r in fits), len(fits)),
        "unknown": {
            "model_unknown": len(model_unknown),
            "model_unknown_excluded": sum(r.eligibility == "fail" for r in model_unknown),
            "gold_unknown_abstained": _share(sum(r.predicate == "unknown" for r in gold_unknown), len(gold_unknown)),
            "gold_unknown_excluded": sum(r.eligibility == "fail" for r in gold_unknown),
        },
        "citation": {
            "quote_found": _share(sum(bool(r.quote_found) for r in decided), len(decided)),
            "quote_date_ok": _share(sum(bool(r.quote_date_ok) for r in decided), len(decided)),
        },
        "agreement": _share(sum(r.predicate == r.gold for r in determinate), len(determinate)),
        "latency_s": {
            "p50": round(_pct(lat, 0.5), 3),
            "p95": round(_pct(lat, 0.95), 3),
            "max": round(max(lat), 3) if lat else 0.0,
        },
        "tokens": {
            "in": sum(r.tokens_in for r in rows),
            "out": sum(r.tokens_out for r in rows),
            "in_per_call": round(sum(r.tokens_in for r in answered) / len(answered), 1) if answered else 0.0,
            "out_per_call": round(sum(r.tokens_out for r in answered) / len(answered), 1) if answered else 0.0,
        },
        "served_models": dict(Counter(r.served_model for r in answered)),
        "served_mismatch": sum(r.served_model != served_name for r in answered) if served_name else 0,
    }
    pairs: dict[str, list[Row]] = {}
    for r in rows:
        if r.pair:
            pairs.setdefault(r.pair, []).append(r)
    if pairs:
        out["eligible_pairs_lost"] = _rate(
            [(p.split("|")[0], any(r.eligibility == "fail" for r in rs)) for p, rs in sorted(pairs.items())]
        )
    return out


def metrics(rows: list[Row], served_name: str = "", max_upper_ci: float | None = None) -> dict[str, Any]:
    gated = [r for r in rows if r.gated]
    m: dict[str, Any] = {
        "gated": score(gated, served_name),
        "all": score(rows, served_name),
        "by_source": {
            s: score([r for r in rows if r.source == s], served_name) for s in sorted({r.source for r in rows})
        },
    }
    g, a = m["gated"], m["all"]
    checks = {
        "wrong_exclusion_rate_le_2pct": g["wrong_exclusion"]["rate"] <= WRONG_EXCLUSION_MAX,
        "unknown_never_excludes": a["unknown"]["model_unknown_excluded"] == 0,
        "served_name_pinned": a["served_mismatch"] == 0,
        "model_answered_90pct": a["no_answer"]["rate"] <= 0.10,
        "gated_items_present": g["n"] > 0,
    }
    if max_upper_ci is not None:
        checks["wrong_exclusion_upper95_le_max"] = g["wrong_exclusion"]["wilson95"][1] <= max_upper_ci
    m["gate"] = {"passed": all(checks.values()), "checks": checks, "wrong_exclusion_max": WRONG_EXCLUSION_MAX}
    return m


def _pc(d: dict[str, Any]) -> str:
    lo, hi = d["wilson95"]
    return f"{100 * d['rate']:.1f} % ({d['k']}/{d['n']}; 95 % CI {100 * lo:.1f}-{100 * hi:.1f})"


def render_md(meta: dict[str, Any], m: dict[str, Any]) -> str:
    g = m["gated"]
    lines = [
        f"# Judge bake-off: {meta['served_name']}",
        "",
        f"Endpoint root `{(meta.get('pin') or {}).get('root')}`, prompt `{meta['prompt']}`, "
        f"set `{meta['set_sha256'][:12]}` ({meta['items']} items), {meta['started']}.",
        "",
        f"**Gate: {'PASSED' if m['gate']['passed'] else 'FAILED'}** "
        + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in m["gate"]["checks"].items()),
        "",
        f"- wrong exclusions (gated sources, among the judge's exclusions): {_pc(g['wrong_exclusion'])}; "
        f"patient-cluster 95 % {100 * g['wrong_exclusion']['cluster95'][0]:.1f}-"
        f"{100 * g['wrong_exclusion']['cluster95'][1]:.1f}",
        "- wrong exclusions among items the gold does not exclude: "
        f"{_pc(g['wrong_exclusion']['of_not_excluding_gold'])}",
        f"- precision of fits: {_pc(g['fits_precision'])}",
        f"- unknown answers that excluded: {m['all']['unknown']['model_unknown_excluded']}; gold-unknown abstained: "
        f"{_pc(g['unknown']['gold_unknown_abstained'])}",
        f"- citations found: {_pc(g['citation']['quote_found'])}; dated right: {_pc(g['citation']['quote_date_ok'])}",
        "",
        "| source | n | wrong excl. | fits precision | quote found | agreement | p50 s | p95 s | tokens in/out |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s, v in m["by_source"].items():
        lines.append(
            f"| {s} | {v['n']} | {_pc(v['wrong_exclusion'])} | {_pc(v['fits_precision'])} | "
            f"{_pc(v['citation']['quote_found'])} | {_pc(v['agreement'])} | {v['latency_s']['p50']} | "
            f"{v['latency_s']['p95']} | {v['tokens']['in_per_call']}/{v['tokens']['out_per_call']} |"
        )
    if "eligible_pairs_lost" in m["all"]:
        lines += ["", f"TREC CT eligible pairs lost (not gated): {_pc(m['all']['eligible_pairs_lost'])}"]
    if meta.get("skipped"):
        lines += ["", "Skipped sources: " + "; ".join(f"{k} ({v})" for k, v in meta["skipped"].items())]
    return "\n".join(lines) + "\n"


def write_results(out: Path, rows: list[Row], meta: dict[str, Any], m: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.jsonl").write_text(
        "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    (out / "metrics.json").write_text(json.dumps({"meta": meta, **m}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "metrics.md").write_text(render_md(meta, m), encoding="utf-8")


def compare(paths: list[Path]) -> str:
    """Side by side from each run's ``metrics.json`` (the same set sha is required to compare)."""
    docs = [json.loads((p / "metrics.json").read_text(encoding="utf-8")) for p in paths]
    shas = {d["meta"]["set_sha256"] for d in docs}
    head = "| metric | " + " | ".join(d["meta"]["served_name"] for d in docs) + " |"
    rows_ = [head, "| --- |" + " --- |" * len(docs)]

    def cell(f: Callable[[dict[str, Any]], Any]) -> str:
        return " | ".join(str(f(d)) for d in docs)

    rows_ += [
        f"| gate | {cell(lambda d: 'PASSED' if d['gate']['passed'] else 'FAILED')} |",
        f"| wrong exclusions (gated) | {cell(lambda d: _pc(d['gated']['wrong_exclusion']))} |",
        f"| fits precision (gated) | {cell(lambda d: _pc(d['gated']['fits_precision']))} |",
        f"| unknown answers that excluded | {cell(lambda d: d['all']['unknown']['model_unknown_excluded'])} |",
        f"| gold-unknown abstained | {cell(lambda d: _pc(d['gated']['unknown']['gold_unknown_abstained']))} |",
        f"| quote found | {cell(lambda d: _pc(d['all']['citation']['quote_found']))} |",
        f"| agreement | {cell(lambda d: _pc(d['all']['agreement']))} |",
        f"| no answer | {cell(lambda d: _pc(d['all']['no_answer']))} |",
        f"| latency p50 / p95 s | {cell(lambda d: '{p50} / {p95}'.format(**d['all']['latency_s']))} |",
        f"| tokens in / out per call | "
        f"{cell(lambda d: '{in_per_call} / {out_per_call}'.format(**d['all']['tokens']))} |",
    ]
    if len(shas) > 1:
        rows_.append("\nWARNING: the runs used different item sets; the numbers are not comparable.")
    return "\n".join(rows_)


# ---------------------------------------------------------------------------------------------- stub server
Answer = Callable[[dict[str, Any]], dict[str, Any]]


def stub_answer(inp: dict[str, Any]) -> dict[str, Any]:
    from llm_stub.handlers import judge

    return judge(inp)


@contextmanager
def stub_server(
    served_name: str = STUB_NAME,
    root: str = "stub/trialbox-stub",
    answer: Answer = stub_answer,
    report_model: str | None = None,
    seen_auth: list[str] | None = None,
) -> Iterator[str]:
    """A local OpenAI-compatible server on 127.0.0.1 (``/v1/models``, ``/v1/chat/completions``) answering the
    judge prompt with ``answer(input)``. Yields the base URL. For the offline run and the tests; no network."""
    block = re.compile(r"```json\s*(.*?)```", re.S)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _send(self, code: int, doc: dict[str, Any]) -> None:
            body = json.dumps(doc, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/v1/models":
                data = [{"id": served_name, "object": "model", "root": root, "max_model_len": 32768}]
                self._send(200, {"object": "list", "data": data})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            if seen_auth is not None:
                seen_auth.append(self.headers.get("Authorization", ""))
            user = next((m["content"] for m in body.get("messages", []) if m.get("role") == "user"), "")
            mt = block.search(user)
            if not mt:
                self._send(400, {"error": "no json block"})
                return
            content = json.dumps(answer(json.loads(mt.group(1))), ensure_ascii=False)
            n_in, n_out = len(user) // 4, len(content) // 4
            self._send(
                200,
                {
                    "id": "stub",
                    "object": "chat.completion",
                    "model": report_model if report_model is not None else body.get("model"),
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out},
                },
            )

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    finally:
        srv.shutdown()
        srv.server_close()


# ------------------------------------------------------------------------------------------------------ main
def bake(
    base_url: str,
    served_name: str,
    items: list[Item],
    out: Path,
    *,
    sha: str,
    key_env: str = DEFAULT_KEY_ENV,
    expect_root: str = "",
    workers: int = 4,
    skipped: dict[str, str] | None = None,
    max_upper_ci: float | None = None,
    backoff: tuple[float, ...] = BACKOFF_S,
) -> dict[str, Any]:
    from tb_common.llm import load_prompt

    key = os.environ.get(key_env, "")
    client = BakeoffClient(base_url, served_name, key=key, backoff=backoff)
    pin = pin_check(client.http, base_url, served_name, expect_root)
    p = load_prompt("judge")
    meta = {
        "served_name": served_name,
        "expect_root": expect_root or None,
        "pin": pin,
        "auth": f"env:{key_env}" if key else "none",
        "prompt": f"{p.meta.id}@{p.meta.version}",
        "set_sha256": sha,
        "items": len(items),
        "workers": max(1, min(workers, MAX_WORKERS)),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skipped": skipped or {},
    }
    rows = run(client, items, workers)
    m = metrics(rows, served_name, max_upper_ci)
    write_results(out, rows, meta, m)
    return {"meta": meta, **m}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="judge_bakeoff", description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default="", help="OpenAI-compatible base URL, e.g. http://127.0.0.1:8000/v1")
    ap.add_argument("--served-name", default="", help="the model name the endpoint must serve and report")
    ap.add_argument("--expect-root", default="", help="the /v1/models root the served name must have (the weights)")
    ap.add_argument("--key-env", default=DEFAULT_KEY_ENV, help="environment variable holding the endpoint key")
    ap.add_argument("--stub", action="store_true", help="run against the built-in local stub server")
    ap.add_argument("--set", type=Path, default=None, help="a frozen item set (from --write-set)")
    ap.add_argument("--write-set", type=Path, default=None, help="write the item set and exit (no model call)")
    ap.add_argument("--sources", nargs="+", default=list(SOURCES), choices=SOURCES)
    ap.add_argument("--n-per-source", type=int, default=0, help="seeded sample per source (0 = all)")
    ap.add_argument("--trec-pairs", type=int, default=200, help="NIST-eligible TREC CT pairs to sample")
    ap.add_argument("--workers", type=int, default=4, help=f"concurrent calls (at most {MAX_WORKERS})")
    ap.add_argument("--max-upper-ci", type=float, default=None, help="also gate the upper Wilson 95 %% bound")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--compare", nargs="+", type=Path, default=None, metavar="DIR")
    a = ap.parse_args(argv)
    if a.compare:
        print(compare(a.compare))
        return 0
    if a.set is not None:
        items, sha = read_set(a.set)
        skipped: dict[str, str] = {}
    else:
        items, skipped = build_set(tuple(a.sources), n_per_source=a.n_per_source, trec_pairs=a.trec_pairs)
        sha = set_sha(items)
    for s, why in skipped.items():
        print(f"skipped {s}: {why}", file=sys.stderr)
    if a.write_set is not None:
        print(f"wrote {len(items)} items to {a.write_set} (sha256 {write_set(items, a.write_set)})")
        return 0
    if a.out is None or not (a.stub or (a.base_url and a.served_name)):
        print("need --out and either --stub or --base-url with --served-name", file=sys.stderr)
        return 2
    try:
        if a.stub:
            with stub_server() as url:
                res = bake(
                    url,
                    STUB_NAME,
                    items,
                    a.out,
                    sha=sha,
                    key_env=a.key_env,
                    workers=a.workers,
                    skipped=skipped,
                    max_upper_ci=a.max_upper_ci,
                )
        else:
            res = bake(
                a.base_url,
                a.served_name,
                items,
                a.out,
                sha=sha,
                key_env=a.key_env,
                expect_root=a.expect_root,
                workers=a.workers,
                skipped=skipped,
                max_upper_ci=a.max_upper_ci,
            )
    except PinRefused as e:
        print(str(e), file=sys.stderr)
        return 3
    print((a.out / "metrics.md").read_text(encoding="utf-8"), end="")
    return 0 if res["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
