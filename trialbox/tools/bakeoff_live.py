"""Live bake-off run (spec v4 §8.10, LLM-33; S1-14): ``judge_ml`` items through a running tb-gateway.

    python -m tools.bakeoff --live --build or-qwen3.6-35b-a3b --langs en --n 0 --out eval/bakeoff/results/<date>
    python -m tools.bakeoff --report eval/bakeoff/results/<date>

The live run is a client of the gateway at ``TB_GATEWAY_URL`` (a DEV gateway whose site override pins the hosted
build under test, ``tools/pin_provider.py``). Every call is caller ``eval``, role ``bakeoff``, class D0, purpose
``evaluation``, so it takes the ``bakeoff`` route; the gateway alone holds the endpoint key, forces sampling, checks the
served model and provider against the pin, and audits each call. This module never reads an API key.

* concurrency: ``--workers`` threads (at most 8);
* retries: an upstream failure (HTTP 5xx, ``upstream_failed``, unreachable) is retried with exponential backoff
  (2, 4, 8, 16 s); a policy refusal is recorded, never retried;
* per call: the label, the gateway build sha, the provider and model the response reports, client latency, tokens
  (reasoning tokens too), and the upstream's reported cost (``usage.cost``);
* budget: ``--budget-usd`` stops scheduling new items once the run's recorded cost reaches it;
* resumable: rows already in the predictions CSV with an answer or a policy refusal are kept; failed rows re-run.

Outputs per build in ``--out``: ``predictions_<build>.csv`` (one row per item and language; no prompt text, no
secret) and ``metrics_<build>.json``. ``--report`` combines every ``metrics_*.json`` into ``summary.json`` and
``summary.md``.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

MAX_WORKERS = 8
BACKOFF_S = (2.0, 4.0, 8.0, 16.0)
MAX_EVIDENCE = 12
VARIANTS = ("", "trialgpt")  # "" = TrialBox prompt (mlbench_judge@1); "trialgpt" = TrialGPT-Matching wording

_TRIALGPT_LABELS = {
    "inclusion": (
        'the label must be chosen from {"not applicable", "not enough information", "included", "not included"}. '
        '"not applicable" should only be used for criteria that are not applicable to the patient. "not enough '
        'information" should be used where the patient note does not contain sufficient information for making the '
        'classification. Try to use as less "not enough information" as possible because if the note does not mention '
        'a medically important fact, you can assume that the fact is not true for the patient. "included" denotes that '
        'the patient meets the inclusion criterion, while "not included" means the reverse.'
    ),
    "exclusion": (
        'the label must be chosen from {"not applicable", "not enough information", "excluded", "not excluded"}. '
        '"not applicable" should only be used for criteria that are not applicable to the patient. "not enough '
        'information" should be used where the patient note does not contain sufficient information for making the '
        'classification. Try to use as less "not enough information" as possible because if the note does not mention '
        'a medically important fact, you can assume that the fact is not true for the patient. "excluded" denotes that '
        'the patient meets the exclusion criterion and should be excluded in the trial, while "not excluded" means the '
        "reverse."
    ),
}


def trialgpt_messages(ctype: str, criterion: str, note: list[str]) -> list[dict[str, str]]:
    """TrialGPT-Matching's criterion-level instructions (NCBI ``trialgpt_matching/TrialGPT.py``, public domain),
    for one criterion at a time and as a JSON object (reasoning, evidence ids, label) instead of the per-trial dict.
    The trial title/summary TrialGPT also shows are not in the annotation set, so they are omitted."""
    system = (
        "You are a helpful assistant for clinical trial recruitment. Your task is to compare a given patient note and "
        f"one {ctype} criterion of a clinical trial to determine the patient's eligibility at the criterion level.\n"
        "Output three elements. Element 1: briefly generate your reasoning process: First, judge whether the criterion "
        "is not applicable (not very common), where the patient does not meet the premise of the criterion. Then, "
        "check if the patient note contains direct evidence. If so, judge whether the patient meets or does not meet "
        "the criterion. If there is no direct evidence, try to infer from existing evidence, and answer one question: "
        "If the criterion is true, is it possible that a good patient note will miss such information? If "
        "impossible, then you can assume that the criterion is not true. Otherwise, there is not enough "
        "information.\nElement 2: if there is relevant information, the list of relevant sentence IDs in the patient "
        "note; otherwise an empty list.\n"
        f"Element 3: classify the patient eligibility for this {ctype} criterion: {_TRIALGPT_LABELS[ctype]}\n"
        'Output only a JSON object: {"reasoning": str, "evidence": [int], "label": str}.'
    )
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(note))
    user = (
        f"Here is the patient note, each sentence is led by a sentence_id:\n{numbered}\n\n"
        f"Here is the {ctype} criterion:\n{criterion}\n\nPlain JSON output:"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def trialgpt_schema(max_evidence: int = MAX_EVIDENCE) -> dict[str, Any]:
    """Reasoning first (TrialGPT's element order), then evidence ids (capped), then the label."""
    return {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string", "maxLength": 1200},
            "evidence": {"type": "array", "items": {"type": "integer"}, "maxItems": max_evidence},
            "label": {"type": "string"},
        },
        "required": ["reasoning", "evidence", "label"],
        "additionalProperties": False,
    }


def stem(build_id: str, variant: str = "") -> str:
    return f"{build_id}__{variant}" if variant else build_id


RETRY_REASONS = frozenset({"upstream_failed"})
_LABEL = re.compile(r'"label"\s*:\s*"([^"]{1,40})"')


@dataclass
class Row:
    """One item × language. ``refused`` is a gateway refusal code; ``error`` an upstream failure after retries."""

    build_id: str
    lang: str
    annotation_id: str
    criterion_type: str
    gold: str
    gpt4: str
    pred: str = ""
    raw_label: str = ""
    lenient_pred: str = ""  # label read from a truncated or malformed answer (secondary metric only)
    valid: bool = False
    evidence: str = ""
    refused: str = ""
    error: str = ""
    model_refusal: bool = False
    finish_reason: str = ""
    served_model: str = ""
    provider: str = ""
    build_sha: str = ""
    call_id: str = ""
    cache: str = ""
    attempts: int = 0
    latency_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def done(self) -> bool:
        return bool(self.call_id or self.refused) and not self.error


def _row_from_csv(d: dict[str, str]) -> Row:
    kw: dict[str, Any] = {}
    for f in fields(Row):
        v = d.get(f.name, "")
        if f.type == "bool":
            kw[f.name] = v == "True"
        elif f.type == "int":
            kw[f.name] = int(v or 0)
        elif f.type == "float":
            kw[f.name] = float(v or 0.0)
        else:
            kw[f.name] = v
    return Row(**kw)


def read_rows(path: Path) -> list[Row]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [_row_from_csv(d) for d in csv.DictReader(fh)]


def write_rows(path: Path, rows: Iterable[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r.lang, int(r.annotation_id)))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[f.name for f in fields(Row)], lineterminator="\n")
        w.writeheader()
        for r in ordered:
            w.writerow(asdict(r))


# ------------------------------------------------------------------------------------------------ one call
def judge_once(
    client: Any,
    row: Row,
    msgs: list[dict[str, str]],
    *,
    max_tokens: int,
    sleep: Callable[[float], None],
    reasoning_effort: str = "",
    variant: str = "",
) -> Row:
    """Fill ``row`` from one gateway call, retrying upstream failures with backoff."""
    from tb_llm import CallLabels, GatewayError, GatewayRefused, json_schema_format

    from tools import mlbench

    labels = CallLabels(
        data_class="D0",
        purpose="evaluation",
        study_id="none",
        context_of_use="bakeoff_judge_ml",
        role="bakeoff",
        prompt="trialgpt_criterion@1" if variant == "trialgpt" else "mlbench_judge@1",
    )
    fmt = json_schema_format("judge", trialgpt_schema() if variant == "trialgpt" else bounded_schema())
    for attempt in range(len(BACKOFF_S) + 1):
        row.attempts = attempt + 1
        row.error = ""
        t0 = time.perf_counter()
        try:
            res = _chat(client, msgs, labels, fmt, max_tokens, reasoning_effort)
        except GatewayRefused as e:
            if e.reason in RETRY_REASONS and attempt < len(BACKOFF_S):
                row.error = e.reason
                sleep(BACKOFF_S[attempt])
                continue
            if e.reason in RETRY_REASONS:
                row.error = e.reason
            else:
                row.refused = e.reason
            return row
        except GatewayError as e:
            row.error = type(e).__name__
            if attempt < len(BACKOFF_S):
                sleep(BACKOFF_S[attempt])
                continue
            return row
        row.latency_s = round(time.perf_counter() - t0, 3)
        payload = res.payload
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = payload.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        row.finish_reason = str(choice.get("finish_reason") or "")
        row.model_refusal = bool(message.get("refusal")) or row.finish_reason == "content_filter"
        row.served_model = res.model
        row.provider = str(payload.get("provider") or "")
        row.build_sha = res.build_sha
        row.call_id = res.call_id
        row.cache = res.cache
        row.tokens_in = res.tokens_in
        row.tokens_out = res.tokens_out
        row.reasoning_tokens = int(details.get("reasoning_tokens") or 0)
        cost = usage.get("cost")
        row.cost_usd = float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else 0.0
        data = res.data if isinstance(res.data, dict) else {}
        if not data:
            found = _LABEL.search(res.content or "")
            row.lenient_pred = (mlbench.norm_label(found.group(1), row.criterion_type) or "") if found else ""
        raw = data.get("label")
        row.raw_label = str(raw) if raw is not None else ""
        label = mlbench.norm_label(raw, row.criterion_type)
        row.pred = label or ""
        row.valid = label is not None
        if label:
            row.lenient_pred = label
        ev = data.get("evidence")
        row.evidence = " ".join(str(int(x)) for x in ev if isinstance(x, int | float)) if isinstance(ev, list) else ""
        return row
    return row  # pragma: no cover - the loop always returns


def bounded_schema(max_evidence: int = MAX_EVIDENCE) -> dict[str, Any]:
    """The judge_public schema with ``evidence`` capped at ``max_evidence`` ids. Greedy decoding (temperature 0, as
    the gateway forces) under a JSON grammar can loop on the evidence array until the token cap; the cap keeps the
    answer valid JSON (seen with gpt-oss-120b on two providers during the 2026-10-25 smoke run)."""
    from tools.trialbox.eval import JUDGE_SCHEMA

    schema: dict[str, Any] = json.loads(json.dumps(JUDGE_SCHEMA))
    schema["properties"]["evidence"]["maxItems"] = max_evidence
    return schema


def _chat(client: Any, msgs: Any, labels: Any, fmt: Any, max_tokens: int, effort: str) -> Any:
    """``GatewayClient.chat``, plus OpenRouter's ``reasoning`` effort when set (the gateway passes it upstream)."""
    from tb_llm import ChatResult

    if not effort:
        return client.chat(msgs, labels, response_format=fmt, max_tokens=max_tokens)
    body = {"messages": msgs, "response_format": fmt, "max_tokens": max_tokens, "reasoning": {"effort": effort}}
    payload = client.complete(body, labels)
    content = str(payload["choices"][0]["message"].get("content") or "")
    tb = payload.get("tb") or {}
    usage = payload.get("usage") or {}
    try:
        data = json.loads(content)
    except ValueError:
        data = None
    return ChatResult(
        content=content,
        payload=payload,
        model=str(payload.get("model") or ""),
        call_id=str(tb.get("call_id") or ""),
        alias=str(tb.get("alias") or ""),
        build_sha=str(tb.get("build_sha") or ""),
        cache=str(tb.get("cache") or ""),
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
        data=data,
    )


def run_live(
    client: Any,
    build_id: str,
    *,
    langs: list[str],
    n: int,
    out: Path,
    workers: int = MAX_WORKERS,
    budget_usd: float = 0.0,
    max_tokens: int = 2048,
    reasoning_effort: str = "",
    variant: str = "",
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> list[Row]:
    """Run (or resume) ``build_id`` over ``n`` items (0: all 1,015) in each of ``langs``; writes the CSV as it goes."""
    from tools import mlbench

    workers = max(1, min(workers, MAX_WORKERS))
    if variant not in VARIANTS:
        raise ValueError(f"unknown prompt variant {variant!r}")
    path = out / f"predictions_{stem(build_id, variant)}.csv"
    pairs = mlbench.sample(mlbench.load_pairs(), n)
    kept = {(r.lang, r.annotation_id): r for r in read_rows(path) if r.done}
    lock = threading.Lock()
    rows: dict[tuple[str, str], Row] = dict(kept)
    spent = sum(r.cost_usd for r in kept.values())
    stop = threading.Event()
    todo: list[tuple[Row, list[dict[str, str]]]] = []
    for lang in langs:
        notes = mlbench.load_notes(lang)
        for p in pairs:
            if (lang, p.annotation_id) in kept:
                continue
            row = Row(build_id, lang, p.annotation_id, p.criterion_type, p.expert_label, p.gpt4_label)
            note = notes[p.patient_id]
            msgs = trialgpt_messages(p.criterion_type, p.criterion, note) if variant else mlbench.messages(p, note)
            todo.append((row, msgs))
    log(f"{build_id}: {len(todo)} calls to make, {len(kept)} kept from {path.name} (${spent:.4f} already recorded)")

    def task(row: Row, msgs: list[dict[str, str]]) -> Row:
        if stop.is_set():
            row.error = "budget_stop"
            return row
        return judge_once(
            client, row, msgs, max_tokens=max_tokens, sleep=sleep, reasoning_effort=reasoning_effort, variant=variant
        )

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(task, r, m) for r, m in todo]
        for fut in as_completed(futures):
            row = fut.result()
            with lock:
                rows[(row.lang, row.annotation_id)] = row
                spent += row.cost_usd
                done += 1
                if budget_usd and spent >= budget_usd and not stop.is_set():
                    stop.set()
                    log(f"{build_id}: budget ${budget_usd:.2f} reached (${spent:.4f}); stopping")
                if done % 100 == 0:
                    write_rows(path, rows.values())
                    log(f"{build_id}: {done}/{len(todo)} calls, ${spent:.4f}")
    write_rows(path, rows.values())
    return list(rows.values())


# ------------------------------------------------------------------------------------------------ metrics
def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, round(q * (len(s) - 1))))
    return s[k]


def absent_as_negative(label: str, ctype: str) -> str:
    """The NCBI annotation convention for exclusion criteria: a condition the note does not mention is "not excluded".
    The TrialBox prompt asks for "not enough information" instead (an absent finding is not a negative one); both
    leave the patient open, so this mapping changes 4-way accuracy only, never a block."""
    if ctype == "exclusion" and label in ("", "not enough information"):
        return "not excluded"
    return label


def _convention_scores(pairs: list[tuple[str, str, str]]) -> dict[str, float]:
    """(pred, gold, ctype) -> screening accuracy (block vs open) and accuracy under :func:`absent_as_negative`."""
    from tools import mlbench

    n = len(pairs)
    if not n:
        return {"screen_accuracy": 0.0, "accuracy_absent_as_negative": 0.0}
    screen = sum((p in mlbench.BLOCKS) == (g in mlbench.BLOCKS) for p, g, _ in pairs)
    conv = sum(absent_as_negative(p, c) == g for p, g, c in pairs)
    return {"screen_accuracy": round(screen / n, 4), "accuracy_absent_as_negative": round(conv / n, 4)}


def metrics(rows: list[Row]) -> dict[str, Any]:
    """Per-language metrics of one build: mlbench.score against the physician labels, agreement with the recorded
    GPT-4 labels, GPT-4's own score on the same items, per-label confusion, invalid/refusal rates, latency, cost."""
    from tools import mlbench

    pairs = {p.annotation_id: p for p in mlbench.load_pairs()}
    out: dict[str, Any] = {}
    for lang in sorted({r.lang for r in rows}):
        rs = [r for r in rows if r.lang == lang]
        scored = [
            {
                "annotation_id": r.annotation_id,
                "label": r.pred or None,
                "valid_json": r.valid,
                "evidence": [int(x) for x in r.evidence.split()],
                "cost": r.cost_usd,
                "seconds": r.latency_s,
                "prompt_tokens": r.tokens_in,
                "completion_tokens": r.tokens_out,
            }
            for r in rs
        ]
        m = mlbench.score(scored, pairs)
        ref = mlbench.gpt4_reference([pairs[r.annotation_id] for r in rs])
        confusion: dict[str, dict[str, dict[str, int]]] = {}
        for ctype in ("inclusion", "exclusion"):
            cols = [*mlbench.LABELS[ctype], "invalid"]
            table = {g: dict.fromkeys(cols, 0) for g in mlbench.LABELS[ctype]}
            for r in rs:
                if r.criterion_type == ctype:
                    table[r.gold][r.pred or "invalid"] += 1
            confusion[ctype] = table
        per_label: dict[str, dict[str, float]] = {}
        for lab in sorted({lab for ls in mlbench.LABELS.values() for lab in ls}):
            tp = sum(1 for r in rs if r.pred == lab and r.gold == lab)
            fp = sum(1 for r in rs if r.pred == lab and r.gold != lab)
            fn = sum(1 for r in rs if r.pred != lab and r.gold == lab)
            per_label[lab] = {
                "support": tp + fn,
                "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
                "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
            }
        answered = [r for r in rs if r.call_id]
        lat = [r.latency_s for r in answered if r.cache != "hit"]
        n = len(rs)
        cost = sum(r.cost_usd for r in rs)
        conv = _convention_scores([(r.pred, r.gold, r.criterion_type) for r in rs])
        conv_ref = _convention_scores([(r.gpt4, r.gold, r.criterion_type) for r in rs])
        out[lang] = {
            "n": n,
            "accuracy": round(m["accuracy"], 4),
            **conv,
            "macro_f1": round(m["macro_f1"], 4),
            "lenient_accuracy": round(sum((r.lenient_pred or "not enough information") == r.gold for r in rs) / n, 4)
            if n
            else 0.0,
            "agreement_with_gpt4": round(sum(r.pred == r.gpt4 for r in rs) / n, 4) if n else 0.0,
            "false_block_rate": round(m["false_block_rate"], 4),
            "false_block_upper95": round(m["false_block_upper95"], 4),
            "block_recall": round(m["block_recall"], 4),
            "trial_false_exclusion": round(m["trial_false_exclusion"], 4),
            "evidence_f1": round(m["evidence_f1"], 4),
            "invalid_rate": round(sum(1 for r in rs if r.call_id and not r.valid) / n, 4) if n else 0.0,
            "gateway_refusals": dict(Counter(r.refused for r in rs if r.refused)),
            "upstream_errors": dict(Counter(r.error for r in rs if r.error)),
            "model_refusals": sum(r.model_refusal for r in rs),
            "truncated": sum(r.finish_reason == "length" for r in rs),
            "latency_p50_s": round(_pct(lat, 0.5), 3),
            "latency_p95_s": round(_pct(lat, 0.95), 3),
            "latency_mean_s": round(statistics.fmean(lat), 3) if lat else 0.0,
            "tokens_in_mean": round(statistics.fmean([r.tokens_in for r in answered]), 1) if answered else 0.0,
            "tokens_out_mean": round(statistics.fmean([r.tokens_out for r in answered]), 1) if answered else 0.0,
            "reasoning_tokens_mean": round(statistics.fmean([r.reasoning_tokens for r in answered]), 1)
            if answered
            else 0.0,
            "cost_usd": round(cost, 6),
            "cost_per_1k_usd": round(1000 * cost / n, 4) if n else 0.0,
            "providers": dict(Counter(r.provider for r in answered)),
            "served_models": dict(Counter(r.served_model for r in answered)),
            "build_shas": sorted({r.build_sha for r in answered}),
            "confusion": confusion,
            "per_label": per_label,
            "gpt4_reference_same_items": {
                k: round(float(ref[k]), 4)
                for k in ("accuracy", "macro_f1", "false_block_rate", "false_block_upper95", "block_recall")
            }
            | conv_ref,
        }
    return out


def write_metrics(out: Path, build_id: str, rows: list[Row], meta: dict[str, Any], variant: str = "") -> Path:
    path = out / f"metrics_{stem(build_id, variant)}.json"
    body = {"build_id": build_id, "variant": variant, **meta, "by_lang": metrics(rows)}
    path.write_text(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------------------------------------ two-model rule
#: (judge, verifier) build pairs scored with :func:`agreement_rows` in the summary (the recommended Spark pairing)
AGREEMENT_PAIRS = (("or-gpt-oss-120b", "or-gemma-4-26b-a4b"),)


def agreement_rows(judge: list[Row], verifier: list[Row]) -> list[Row]:
    """The two-model rule on recorded answers: a criterion blocks only when both builds block it. Where the judge
    blocks and the verifier does not, the combined answer abstains (``not enough information``), as the cascade's
    :class:`matching.cascade.judge.AgreementJudge` makes it ``potential:uncertain``. The verifier is only consulted
    (cost, latency) where the judge blocks. Items missing from either build are left out."""
    from dataclasses import replace

    from tools import mlbench

    v = {(r.lang, r.annotation_id): r for r in verifier}
    out = []
    for j in judge:
        w = v.get((j.lang, j.annotation_id))
        if w is None:
            continue
        r = replace(j, build_id=f"agree:{j.build_id}+{w.build_id}")
        if j.pred in mlbench.BLOCKS:
            r.cost_usd = j.cost_usd + w.cost_usd
            r.latency_s = round(j.latency_s + w.latency_s, 3)
            if w.pred not in mlbench.BLOCKS:
                r.pred = "not enough information"
                r.lenient_pred = r.pred
        out.append(r)
    return out


# ------------------------------------------------------------------------------------------------ report
def report(out: Path) -> tuple[Path, Path]:
    """``summary.json`` and ``summary.md`` from every ``metrics_*.json`` (and ``cascade_*.json``) in ``out``."""
    builds = []
    for p in sorted(out.glob("metrics_*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        csv_path = out / f"predictions_{stem(b['build_id'], b.get('variant') or '')}.csv"
        if csv_path.exists():  # metrics are always re-derived from the recorded predictions
            b["by_lang"] = metrics(read_rows(csv_path))
            p.write_text(json.dumps(b, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        builds.append(b)
    for jb, vb in AGREEMENT_PAIRS:
        jp, vp = out / f"predictions_{jb}.csv", out / f"predictions_{vb}.csv"
        if jp.exists() and vp.exists():
            rows = agreement_rows(read_rows(jp), read_rows(vp))
            builds.append(
                {
                    "build_id": f"agree:{jb}+{vb}",
                    "variant": "",
                    "rule": "block only if both block",
                    "by_lang": metrics(rows),
                }
            )
    cascades = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("cascade_*.json"))]
    extra_path = out / "run_meta.json"
    extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {}
    recorded = [b for b in builds if not str(b["build_id"]).startswith("agree:")]  # derived rows cost nothing new
    total = sum(float(v["cost_usd"]) for b in recorded for v in b["by_lang"].values()) + sum(
        float(c.get("cost_usd") or 0.0) for c in cascades
    )
    summary = {"run": extra, "builds": builds, "cascade": cascades, "total_cost_usd": round(total, 4)}
    js = out / "summary.json"
    js.write_text(json.dumps(summary, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    md = out / "summary.md"
    md.write_text(render_markdown(summary), encoding="utf-8")
    return js, md


def _fmt_ref(b: dict[str, Any], lang: str) -> str:
    v = b["by_lang"][lang]
    return (
        f"| {stem(b['build_id'], b.get('variant') or '')} | {lang} | {v['n']} | {v['accuracy']:.3f} | "
        f"{v.get('screen_accuracy', 0):.3f} | "
        f"{v['agreement_with_gpt4']:.3f} | {v['false_block_rate']:.3f} ({v['false_block_upper95']:.3f}) | "
        f"{v['block_recall']:.3f} | "
        f"{v['invalid_rate']:.3f} | {sum(v['gateway_refusals'].values())}/{v['model_refusals']} | "
        f"{v['latency_p50_s']:.1f} / {v['latency_p95_s']:.1f} | ${v['cost_usd']:.3f} | ${v['cost_per_1k_usd']:.2f} |"
    )


def render_markdown(s: dict[str, Any]) -> str:
    run = s.get("run") or {}
    lines = [
        f"# Bake-off results {run.get('date', '')}".rstrip(),
        "",
        str(run.get("note") or ""),
        "",
        "## judge_ml through the gateway `bakeoff` route",
        "",
        "Accuracy is exact 4-way agreement with the physician label (NCBI TrialGPT-Criterion-Annotations, SIGIR). "
        "False block: the model blocks a patient (`not included` / `excluded`) where the physician does not; in "
        "brackets the one-sided 95% upper bound. An invalid answer counts as `not enough information`. "
        "Screen: agreement on block vs open (the decision the cascade acts on). "
        "Refused: gateway refusals / model refusals.",
        "",
        "| Build | Lang | n | Accuracy | Screen | Agree GPT-4 | False block (UB95) | Block recall | Invalid | "
        "Refused | p50 / p95 s | Cost | Per 1k |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b in s["builds"]:
        for lang in sorted(b["by_lang"]):
            lines.append(_fmt_ref(b, lang))
    refs = {(lang, v["n"]): v["gpt4_reference_same_items"] for b in s["builds"] for lang, v in b["by_lang"].items()}
    lines += ["", "Recorded GPT-4 labels (TrialGPT paper run) on the same items:", ""]
    lines += ["| Items | Accuracy | Screen | False block (UB95) | Block recall |", "| --- | --- | --- | --- | --- |"]
    for (lang, n), r in sorted(refs.items()):
        lines.append(
            f"| {lang}, n={n} | {r['accuracy']:.3f} | {r.get('screen_accuracy', 0):.3f} | "
            f"{r['false_block_rate']:.3f} ({r['false_block_upper95']:.3f}) | {r['block_recall']:.3f} |"
        )
    lines += ["", "## Pins (provider descriptors, sha256)", "", "| Build | Model | Dated version | Provider | sha256 |"]
    lines.append("| --- | --- | --- | --- | --- |")
    for b in s["builds"]:
        pin = b.get("provider_pin") or {}
        lines.append(
            f"| {b['build_id']} | {pin.get('model', '')} | {pin.get('canonical_slug', '')} (created "
            f"{pin.get('created', '')}) | {pin.get('provider_tag', '')} | `{str(b.get('build_sha', ''))[:16]}…` |"
        )
    if s.get("cascade"):
        lines += ["", "## Cascade end to end (synthetic site A, GZQO, D0)", ""]
        lines += ["| Build | Passed | S0→S5 funnel | Final list | Certificate | Model calls | Cost |"]
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for c in s["cascade"]:
            lines.append(
                f"| {c['build_id']} | {c['passed']} | {c['funnel']} | {c['final_list_size']} | "
                f"{c['certificate_status']} | {c['calls']} | ${float(c.get('cost_usd') or 0):.3f} |"
            )
    lines += ["", f"Total recorded cost: ${s['total_cost_usd']:.4f}", ""]
    return "\n".join(lines)
