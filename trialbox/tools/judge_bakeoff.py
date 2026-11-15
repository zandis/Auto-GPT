"""Judge bake-off for screening (D-181): any OpenAI-compatible endpoint, the product's judge prompt and parser.

    python -m tools.judge_bakeoff --stub --sources synthetic --require-sources synthetic --out /tmp/jb-stub
    python -m tools.judge_bakeoff --write-set /tmp/jb-set.jsonl                 # freeze the item set (no model call)
    python -m tools.judge_bakeoff --base-url http://127.0.0.1:8000/v1 --served-name gemma-4-31b-it \\
        --expect-root google/gemma-4-31B-it --revision <commit> --model-dir <weights> \\
        --set /tmp/jb-set.jsonl --expect-set-sha <sha> --max-upper-ci 0.05 --out <dir>
    python -m tools.judge_bakeoff --compare <dirA> <dirB>     # side by side; exit 1 when not comparable

Every item goes through ``orchestrator.scenarios.evaluate.NoteJudge.judge_excerpts`` with one judge and no verifier:
the registry prompt ``judge`` (newest version), ``tb_common.llm.chat_json`` (structured output, schema check, one
retry) and ``postprocess`` (the quote must be in an excerpt, else ``unknown``), then ``eligibility(kind, verdict)``.
So the harness scores what the box would do with that model, not a separate prompt.

The items (``--sources``):

* ``synthetic``: ``eval/qualification/judge_set.jsonl`` from :mod:`tools.make_judge_set` (the synthetic hospital,
  planted note truth: pass, fail or unknown per criterion); the criterion kind from the ruleset IR. 39 of the 300
  items have no note in the criterion's window: the product asks no model then (unknown), so they count in ``n`` but
  not in ``asked``. 100 are kind ``renewal``, which the product's ``eligibility`` scores like an inclusion.
* ``medtxt``: :mod:`tools.medtxt_eval`'s items (real Japanese reports, CC BY 4.0), the ``strict`` slice only, ja and
  en; "Patients with <finding>." is an exclusion: positive -> pass, stated absent -> fail, suspected and not
  mentioned -> unknown. Needs ``python -m tools.medtxt_eval fetch`` first.
* ``trec_ct``: :mod:`tools.trec_ct_eval`'s NIST-eligible pairs (``--trec-pairs`` of them, seeded): every criterion of
  an eligible pair should not exclude (gold ``not_excluded``). The label is per pair and noisy
  (``eval/trec_ct/AUDIT.md``), so these items are reported, with eligible pairs lost, but not in the gate. Needs
  ``python -m tools.trec_ct_eval fetch``.

The gate (``metrics.json`` ``gate.checks``), **for each gated source separately** (synthetic, medtxt; pooling would
let the larger set hide a failure on the other), plus run-wide checks:

* **wrong exclusions <= 2 %**: the judge excluded (eligibility ``fail``) where the gold does not exclude, over the
  judge's exclusions (Study A's "among note-excluded"), compared exactly (no rounding); Wilson and patient-cluster
  bootstrap 95 % intervals are reported; ``--max-upper-ci`` also gates the pooled upper Wilson bound;
* **at least ``--min-exclusions`` exclusions** (default 20) and **``--min-answered`` answers** (default 50) per gated
  source, and at most 10 % unanswered per source and in the run (the product's model-down rule): a judge that never
  decides, or a model that cannot read the long records, fails instead of passing on 0 of 0;
* every source in ``--require-sources`` (default synthetic and medtxt) is in the run;
* the pin: ``/v1/models`` lists ``--served-name`` with ``root == --expect-root`` before the first item (else exit 3)
  and again after the last (a restart or swap during the run fails the gate). ``root`` is the name vLLM was started
  with, not a hash: ``--model-dir`` records the weight manifest hash (``tools/pin_model.py`` format) and
  ``--expect-manifest`` refuses other weights; ``--revision`` is recorded. vLLM copies the request's model name into
  each response, so the per-response name check only catches a renaming proxy;
* ``product:unknown_never_excludes`` is a self-check of the product's mapping (it fails only on a product
  regression); what says something about the model is ``gold_unknown_excluded`` (reported, and inside the wrong
  exclusions).

Also reported: precision of "fits", abstention on gold-unknown items, citation validity (quote found in an excerpt
with the product's ``quote_in``, and ``quote_date`` equal to the date of an excerpt that holds it), latency per item
put to the model (retries and backoff included, unanswered items too) and per HTTP call, tokens per call (failed
attempts included). Only transport errors, HTTP 429 and 5xx are retried (2, 4, 8, 16 s); a 4xx, a schema error and a
malformed 200 count as no answer, as in the product.

Relation to :mod:`tools.bakeoff` / :mod:`tools.bakeoff_live`: those choose a hosted model for the ``judge_ml`` task
through a tb-gateway with the ``mlbench`` prompt and the SIGIR annotations, scored by agreement and cost. This tool
is the screening-safety gate of one served model, for example a local vLLM on a GPU VM, with the box's own judge
prompt and parser, scored by wrong exclusions. It reuses their pieces: ``_pct``, the worker cap and the retry backoff
from :mod:`tools.bakeoff_live`, ``wilson`` from :mod:`tools.trec_ct_eval`, the item builders of
:mod:`tools.medtxt_eval` and :mod:`tools.trec_ct_eval`, the judge stub of ``services/llm_stub``, the weight manifest
of :mod:`tools.pin_model`.

The endpoint key is read from the environment variable named by ``--key-env`` (default ``TB_BAKEOFF_API_KEY``) and
sent as a bearer token to ``--base-url`` only (no proxy from the environment; plain http only to loopback); it is
never printed and never written to the results. Outputs in ``--out``: ``rows.jsonl`` (per item: ids, gold, the
answer's verdict, reason codes, latency, tokens; no note text, no quote; appended as items complete, ``--resume``
keeps the answered ones), ``metrics.json`` and ``metrics.md``. Exit 0 gate passed, 1 gate failed, 2 usage error or a
refused set or key, 3 the pin refused the endpoint. Keep frozen sets and results outside the repository: they hold
MedTxt and TREC text.
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
from dataclasses import asdict, dataclass, field
from datetime import date
from fractions import Fraction
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

SYNTH_SET = ROOT / "eval" / "qualification" / "judge_set.jsonl"
SOURCES = ("synthetic", "medtxt", "trec_ct")
GATED = {"synthetic": True, "medtxt": True, "trec_ct": False}
WRONG_EXCLUSION_MAX = 0.02
SEED = 20261109
# MedTxt reports and TREC topics carry no dates: one fixed date for the excerpts and the index date, so a time window
# in the prompt never hides them
UNDATED = "2020-01-01"
GOLDS = frozenset({"pass", "fail", "unknown", "not_excluded"})
KINDS = frozenset({"inclusion", "exclusion", "renewal", "documentation"})
DEFAULT_KEY_ENV = "TB_BAKEOFF_API_KEY"
STUB_NAME = "trialbox-stub"
STUB_ROOT = "stub/trialbox-stub"
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
    for line in path.read_text(encoding="utf-8").split("\n"):
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


def read_set(path: Path, expect_sha: str = "") -> tuple[list[Item], str]:
    """A frozen set. ``gated`` is set from the source here, never trusted from the file; an unknown source, kind or
    gold value, or a SHA-256 other than ``expect_sha``, is refused (``ValueError``)."""
    text = path.read_text(encoding="utf-8")
    sha = hashlib.sha256(text.encode()).hexdigest()
    if expect_sha and sha != expect_sha:
        raise ValueError(f"set {path} has sha256 {sha[:12]}, expected {expect_sha[:12]}")
    items = []
    for x in text.split("\n"):  # not splitlines(): a note may hold U+2028
        if not x.strip():
            continue
        it = Item(**json.loads(x))
        if it.source not in GATED or it.gold not in GOLDS or it.kind not in KINDS:
            raise ValueError(f"set {path}: item {it.id} has source/kind/gold {it.source}/{it.kind}/{it.gold}")
        it.gated = GATED[it.source]
        items.append(it)
    return items, sha


def set_sha(items: list[Item]) -> str:
    text = "".join(json.dumps(asdict(i), ensure_ascii=False, sort_keys=True) + "\n" for i in items)
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------------------------- client and pin
class PinRefused(RuntimeError):
    pass


_local = threading.local()
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MALFORMED = (KeyError, ValueError, TypeError, IndexError, AttributeError)


class BakeoffClient(LlmClient):
    """``LlmClient`` (the product's only LLM entry point) plus what the bake-off measures: the parsed answer before
    post-processing, per HTTP call the model name the response reports, its latency and its tokens (failed attempts
    too), and retries of transport errors, HTTP 429 and 5xx only. A 4xx, a schema error and a malformed 200 are not
    retried: they count as the model not answering, as in the product."""

    def __init__(
        self, base_url: str, served_name: str, *, key: str = "", backoff: tuple[float, ...] = BACKOFF_S
    ) -> None:
        super().__init__(base_url, served_name)
        # no proxy from the environment: the key and the note text go to --base-url only
        self.http = httpx.Client(timeout=600.0, trust_env=False)
        if key:
            self.http.headers["Authorization"] = f"Bearer {key}"
        self.http.event_hooks["response"].append(self._seen)
        self.backoff = backoff

    @staticmethod
    def _seen(resp: httpx.Response) -> None:
        if resp.request.method != "POST":
            return
        resp.read()
        _local.status = resp.status_code
        doc: dict[str, Any] = {}
        try:
            got = resp.json()
            doc = got if isinstance(got, dict) else {}
        except ValueError:
            pass
        usage = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
        calls: list[dict[str, Any]] = getattr(_local, "calls", [])
        calls.append(
            {
                "s": resp.elapsed.total_seconds(),
                "in": int((usage or {}).get("prompt_tokens") or 0),
                "out": int((usage or {}).get("completion_tokens") or 0),
            }
        )
        _local.calls = calls
        if resp.status_code < 400:
            _local.served = str(doc.get("model") or "")

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        _local.raw = None
        t0 = time.perf_counter()
        try:
            for i in range(len(self.backoff) + 1):
                _local.attempts = i + 1
                _local.status = None
                try:
                    res = super().chat_json(prompt_id, variables, schema, **kw)
                    break
                except LlmSchemaError:
                    raise
                except LlmError:
                    status = getattr(_local, "status", None)
                    if i == len(self.backoff) or not (status is None or status in RETRY_STATUS):
                        raise
                    time.sleep(self.backoff[i])
                except _MALFORMED as e:  # a 200 without choices, a non-JSON body: no answer, never a crash
                    raise LlmError(f"malformed response ({type(e).__name__})") from None
            _local.raw = res
            return res
        finally:
            _local.latency = time.perf_counter() - t0


def models_entry(http: httpx.Client, base_url: str, served_name: str, expect_root: str = "") -> dict[str, Any]:
    """``/v1/models`` must list ``served_name``; with ``expect_root`` its ``root`` (vLLM: the ``--model`` argument it
    was started with, a repository id or a folder, not a hash) must equal it. Returns that entry for the results."""
    try:
        resp = http.get(f"{base_url.rstrip('/')}/models")
        resp.raise_for_status()
        listed = {str(m.get("id")): m for m in resp.json().get("data", [])}
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        raise PinRefused(f"pin refused: {base_url}/models did not answer ({type(e).__name__})") from None
    m = listed.get(served_name)
    if m is None:
        raise PinRefused(f"pin refused: served name {served_name!r} not in /v1/models ({sorted(listed)})")
    if expect_root and str(m.get("root") or "") != expect_root:
        raise PinRefused(f"pin refused: {served_name!r} serves root {m.get('root')!r}, expected {expect_root!r}")
    return {k: m.get(k) for k in ("id", "root", "max_model_len", "owned_by", "created")}


pin_check = models_entry


def weights_record(model_dir: Path | None, expect_manifest: str = "", revision: str = "") -> dict[str, Any]:
    """The weight manifest hash of the served folder (``tools/pin_model.py`` format) and the repository revision.
    ``expect_manifest`` given and different: refused. No folder: recorded as not hashed."""
    rec: dict[str, Any] = {"revision": revision or None, "model_dir": None, "manifest_sha256": None}
    if model_dir is None:
        if expect_manifest:
            raise PinRefused("pin refused: --expect-manifest needs --model-dir (the folder the server loaded)")
        return rec
    from tools.pin_model import PinError, weight_manifest

    try:
        man = weight_manifest(model_dir)
    except PinError as e:
        raise PinRefused(f"pin refused: {e}") from None
    if expect_manifest and man.sha256 != expect_manifest:
        raise PinRefused(f"pin refused: weight manifest {man.sha256[:12]} != expected {expect_manifest[:12]}")
    rec.update(model_dir=str(model_dir), manifest_sha256=man.sha256, files=man.files, bytes=man.bytes)
    return rec


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
    latency_s: float = 0.0  # the item: every attempt and the backoff between them
    call_latency_s: list[float] = field(default_factory=list)  # each HTTP response
    tokens_in: int = 0  # every call, failed attempts included
    tokens_out: int = 0
    attempts: int = 0
    error: str = ""  # a fixed code, never exception text


def judge_item(client: BakeoffClient, it: Item) -> Row:
    from orchestrator.scenarios.evaluate import NoteJudge

    _local.__dict__.clear()
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
    calls: list[dict[str, Any]] = getattr(_local, "calls", [])
    row.call_latency_s = [round(float(c["s"]), 4) for c in calls]
    row.tokens_in, row.tokens_out = sum(c["in"] for c in calls), sum(c["out"] for c in calls)
    raw: LlmResult | None = getattr(_local, "raw", None)
    if raw is None:
        row.error = "no_answer" if judge.failures else ""
        return row
    row.served_model = str(getattr(_local, "served", ""))
    row.raw_verdict = str(raw.data.get("verdict", "unknown"))
    if row.raw_verdict in ("pass", "fail"):
        q = str(raw.data.get("quote") or "")
        hits = [e for e in it.excerpts if quote_in(q, str(e["text"]))]
        qd = str(raw.data.get("quote_date") or "")[:10]
        row.quote_found = bool(hits)
        row.quote_date_ok = any(qd == str(e["date"])[:10] for e in hits)  # a sentence repeated in several notes
    return row


def run(
    client: BakeoffClient, items: list[Item], workers: int = 4, out: Path | None = None, resume: bool = False
) -> list[Row]:
    """Judge every item. With ``out``, each row is appended to ``rows.jsonl`` as it completes (a preempted VM keeps
    what it paid for); ``resume`` keeps the rows already there that have an answer and judges the rest."""
    done: dict[str, Row] = {}
    path = out / "rows.jsonl" if out is not None else None
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if resume and path.exists():
            for x in path.read_text(encoding="utf-8").split("\n"):
                if x.strip():
                    r = Row(**json.loads(x))
                    if not r.error:
                        done[r.id] = r
        path.write_text("".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in done.values()), "utf-8")
    lock = threading.Lock()

    def one(it: Item) -> Row:
        r = judge_item(client, it)
        if path is not None:
            with lock, path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
        return r

    todo = [it for it in items if it.id not in done]
    with ThreadPoolExecutor(max(1, min(workers, MAX_WORKERS))) as ex:
        for r in ex.map(one, todo):
            done[r.id] = r
    return [done[it.id] for it in items]


# --------------------------------------------------------------------------------------------------- scoring
@dataclass(frozen=True)
class GateConfig:
    max_wrong: float = WRONG_EXCLUSION_MAX  # per gated source, over the judge's exclusions
    min_exclusions: int = 20  # per gated source: fewer is no evidence, the gate fails
    min_answered: int = 50  # per gated source
    max_no_answer: float = 0.10  # the product's model-down rule (MAX_JUDGE_FAILURE_SHARE)
    max_upper_ci: float | None = None  # optional: the pooled gated upper Wilson bound (Study A: 0.05)
    require: tuple[str, ...] = ("synthetic", "medtxt")  # gated sources that must be in the run


def _share(k: int, n: int) -> dict[str, Any]:
    from tools.trec_ct_eval import wilson

    return {"k": k, "n": n, "rate": round(k / n, 4) if n else 0.0, "wilson95": [round(x, 4) for x in wilson(k, n)]}


def _cluster_ci(by: dict[str, list[bool]], reps: int = 2000, seed: int = SEED) -> list[float]:
    """Percentile 95 % interval of a rate, resampling every cluster (patients with no flagged item included)."""
    ids = sorted(by)
    if not ids:
        return [0.0, 1.0]
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        k = n = 0
        for c in (rng.choice(ids) for _ in ids):
            k += sum(by[c])
            n += len(by[c])
        vals.append(k / n if n else 0.0)
    vals.sort()
    return [round(vals[int(0.025 * reps)], 4), round(vals[int(0.975 * reps) - 1], 4)]


def _within(k: int, n: int, limit: float) -> bool:
    """``k / n <= limit`` exactly (no rounding); ``n == 0`` is not within (no evidence)."""
    return n > 0 and Fraction(k, n) <= Fraction(str(limit))


def score(rows: list[Row], served_name: str = "") -> dict[str, Any]:
    answered = [r for r in rows if r.raw_verdict]
    asked = [r for r in rows if r.reason != "no_notes"]
    excluded = [r for r in rows if r.eligibility == "fail"]
    by_cluster: dict[str, list[bool]] = {r.cluster: [] for r in rows}
    for r in excluded:
        by_cluster[r.cluster].append(r.gold_eligibility != "fail")
    k_wrong = sum(r.gold_eligibility != "fail" for r in excluded)
    not_fail_gold = [r for r in rows if r.gold_eligibility != "fail"]
    fits = [r for r in rows if r.eligibility == "pass" and r.gold != "not_excluded"]
    decided = [r for r in answered if r.quote_found is not None]
    model_unknown = [r for r in rows if r.predicate == "unknown"]
    gold_unknown = [r for r in rows if r.gold == "unknown"]
    determinate = [r for r in rows if r.gold in ("pass", "fail", "unknown")]
    item_lat = [r.latency_s for r in asked]
    call_lat = [x for r in asked for x in r.call_latency_s]
    n_calls = len(call_lat)
    out: dict[str, Any] = {
        "n": len(rows),
        "asked": len(asked),  # put to the model (items without notes are not: the product asks nothing then)
        "answered": len(answered),
        "no_notes": len(rows) - len(asked),
        "no_answer": _share(sum(bool(r.error) for r in asked), len(asked)),
        "wrong_exclusion": {
            **_share(k_wrong, len(excluded)),
            "exact": [k_wrong, len(excluded)],
            "cluster95": _cluster_ci(by_cluster),
            "of_not_excluding_gold": _share(sum(r.eligibility == "fail" for r in not_fail_gold), len(not_fail_gold)),
        },
        "correct_exclusions": len(excluded) - k_wrong,
        "fits_precision": _share(sum(r.gold_eligibility == "pass" for r in fits), len(fits)),
        "unknown": {
            "model_unknown": len(model_unknown),
            "model_unknown_excluded": sum(r.eligibility == "fail" for r in model_unknown),
            "gold_unknown_abstained": _share(sum(r.predicate == "unknown" for r in gold_unknown), len(gold_unknown)),
            "gold_unknown_excluded": _share(sum(r.eligibility == "fail" for r in gold_unknown), len(gold_unknown)),
        },
        "citation": {
            "quote_found": _share(sum(bool(r.quote_found) for r in decided), len(decided)),
            "quote_date_ok": _share(sum(bool(r.quote_date_ok) for r in decided), len(decided)),
        },
        "agreement": _share(sum(r.predicate == r.gold for r in determinate), len(determinate)),
        "latency_s": {  # per item put to the model (answered or not: retries and backoff included)
            "p50": round(_pct(item_lat, 0.5), 3),
            "p95": round(_pct(item_lat, 0.95), 3),
            "max": round(max(item_lat), 3) if item_lat else 0.0,
        },
        "call_latency_s": {  # per HTTP call
            "calls": n_calls,
            "p50": round(_pct(call_lat, 0.5), 3),
            "p95": round(_pct(call_lat, 0.95), 3),
            "max": round(max(call_lat), 3) if call_lat else 0.0,
        },
        "tokens": {
            "in": sum(r.tokens_in for r in rows),
            "out": sum(r.tokens_out for r in rows),
            "in_per_call": round(sum(r.tokens_in for r in rows) / n_calls, 1) if n_calls else 0.0,
            "out_per_call": round(sum(r.tokens_out for r in rows) / n_calls, 1) if n_calls else 0.0,
        },
        "served_models": dict(Counter(r.served_model for r in answered)),
        "served_mismatch": sum(r.served_model != served_name for r in answered) if served_name else 0,
    }
    pairs: dict[str, list[Row]] = {}
    for r in rows:
        if r.pair:
            pairs.setdefault(r.pair, []).append(r)
    if pairs:
        lost = [(p.split("|")[0], any(r.eligibility == "fail" for r in rs)) for p, rs in sorted(pairs.items())]
        by_p: dict[str, list[bool]] = {}
        for c, f in lost:
            by_p.setdefault(c, []).append(f)
        out["eligible_pairs_lost"] = {**_share(sum(f for _, f in lost), len(lost)), "cluster95": _cluster_ci(by_p)}
    return out


def metrics(
    rows: list[Row],
    served_name: str = "",
    gate: GateConfig | None = None,
    pin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scores and the gate. ``pin``: ``root_verified`` and ``unchanged`` from the run (absent = not checked)."""
    cfg = gate or GateConfig()
    gated = [r for r in rows if r.gated]
    m: dict[str, Any] = {
        "gated": score(gated, served_name),
        "all": score(rows, served_name),
        "by_source": {
            s: score([r for r in rows if r.source == s], served_name) for s in sorted({r.source for r in rows})
        },
    }
    a = m["all"]
    checks: dict[str, bool] = {}
    gated_sources = sorted({r.source for r in gated})
    for s in sorted(set(cfg.require) | set(gated_sources)):
        v = m["by_source"].get(s)
        if v is None or not any(r.gated for r in rows if r.source == s):
            checks[f"{s}:present"] = False
            continue
        we = v["wrong_exclusion"]
        checks[f"{s}:wrong_exclusion_le_{100 * cfg.max_wrong:g}pct"] = _within(
            we["exact"][0], we["exact"][1], cfg.max_wrong
        )
        checks[f"{s}:exclusions_ge_{cfg.min_exclusions}"] = we["n"] >= cfg.min_exclusions and we["n"] > 0
        checks[f"{s}:answered_ge_{cfg.min_answered}"] = v["answered"] >= cfg.min_answered and v["answered"] > 0
        checks[f"{s}:no_answer_le_{100 * cfg.max_no_answer:g}pct"] = v["no_answer"]["n"] > 0 and Fraction(
            v["no_answer"]["k"], v["no_answer"]["n"]
        ) <= Fraction(str(cfg.max_no_answer))
    if cfg.max_upper_ci is not None:
        checks["gated:wrong_exclusion_upper95_le_max"] = (
            m["gated"]["wrong_exclusion"]["n"] > 0 and m["gated"]["wrong_exclusion"]["wilson95"][1] <= cfg.max_upper_ci
        )
    checks["run:no_answer_le_10pct"] = a["no_answer"]["n"] == 0 or Fraction(
        a["no_answer"]["k"], a["no_answer"]["n"]
    ) <= Fraction(str(cfg.max_no_answer))
    # a self-check of the product's mapping: an unknown answer cannot exclude (it fails only on a product regression)
    checks["product:unknown_never_excludes"] = a["unknown"]["model_unknown_excluded"] == 0
    # vLLM copies the request's model name into the response, so this catches a renaming proxy, not other weights
    checks["pin:responses_report_served_name"] = a["served_mismatch"] == 0
    if pin is not None:
        checks["pin:root_verified"] = bool(pin.get("root_verified"))
        checks["pin:unchanged_at_end"] = bool(pin.get("unchanged"))
    m["gate"] = {"passed": bool(checks) and all(checks.values()), "checks": checks, "config": asdict(cfg)}
    return m


def _pc(d: dict[str, Any]) -> str:
    lo, hi = d["wilson95"]
    return f"{100 * d['rate']:.1f} % ({d['k']}/{d['n']}; 95 % CI {100 * lo:.1f}-{100 * hi:.1f})"


def render_md(meta: dict[str, Any], m: dict[str, Any]) -> str:
    g = m["gated"]
    w = meta.get("weights") or {}
    pin = meta.get("pin") or {}
    verified = "verified against --expect-root" if meta.get("expect_root") else "UNVERIFIED"
    lines = [
        f"# Judge bake-off: {meta['served_name']}",
        "",
        f"Endpoint root `{pin.get('root')}` ({verified}), "
        f"revision `{w.get('revision')}`, weight manifest `{(w.get('manifest_sha256') or 'not hashed')[:16]}`, "
        f"prompt `{meta['prompt']}`, set `{meta['set_sha256'][:12]}` ({meta['items']} items, "
        f"{m['all']['asked']} put to the model), {meta['started']}.",
        "",
        f"**Gate: {'PASSED' if m['gate']['passed'] else 'FAILED'}** "
        + ", ".join(f"{k} {'ok' if v else 'FAIL'}" for k, v in m["gate"]["checks"].items()),
        "",
        f"- wrong exclusions, gated sources pooled (among the judge's exclusions): {_pc(g['wrong_exclusion'])}; "
        f"patient-cluster 95 % {100 * g['wrong_exclusion']['cluster95'][0]:.1f}-"
        f"{100 * g['wrong_exclusion']['cluster95'][1]:.1f}",
        "- wrong exclusions among items the gold does not exclude: "
        f"{_pc(g['wrong_exclusion']['of_not_excluding_gold'])}",
        f"- precision of fits: {_pc(g['fits_precision'])}",
        f"- gold-unknown excluded: {_pc(g['unknown']['gold_unknown_excluded'])}; abstained: "
        f"{_pc(g['unknown']['gold_unknown_abstained'])}",
        f"- citations found: {_pc(g['citation']['quote_found'])}; dated right: {_pc(g['citation']['quote_date_ok'])}",
        f"- per HTTP call: {m['all']['call_latency_s']['calls']} calls, p50 {m['all']['call_latency_s']['p50']} s, "
        f"p95 {m['all']['call_latency_s']['p95']} s; tokens in/out per call {m['all']['tokens']['in_per_call']}/"
        f"{m['all']['tokens']['out_per_call']}",
        "",
        "| source | gated | n (asked) | wrong excl. | fits precision | quote found | agreement | item p50 / p95 s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s, v in m["by_source"].items():
        lines.append(
            f"| {s} | {'yes' if GATED.get(s) else 'no'} | {v['n']} ({v['asked']}) | {_pc(v['wrong_exclusion'])} | "
            f"{_pc(v['fits_precision'])} | {_pc(v['citation']['quote_found'])} | {_pc(v['agreement'])} | "
            f"{v['latency_s']['p50']} / {v['latency_s']['p95']} |"
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


def _setup(d: dict[str, Any]) -> str:
    return f"{d['meta']['set_sha256'][:12]} / {d['meta']['prompt']} / {d['meta']['workers']}"


def _weights(d: dict[str, Any]) -> str:
    man = (d["meta"].get("weights") or {}).get("manifest_sha256") or "not hashed"
    return f"{(d['meta'].get('pin') or {}).get('root')} / {man[:12]}"


def _source_we(d: dict[str, Any], s: str) -> str:
    return _pc(d["by_source"][s]["wrong_exclusion"]) if s in d["by_source"] else "-"


def compare(paths: list[Path]) -> tuple[str, bool]:
    """Side by side from each run's ``metrics.json``. Comparable (the bool) only when the runs used the same item
    set and the same prompt version."""
    docs = [json.loads((p / "metrics.json").read_text(encoding="utf-8")) for p in paths]
    head = "| metric | " + " | ".join(d["meta"]["served_name"] for d in docs) + " |"
    rows_ = [head, "| --- |" + " --- |" * len(docs)]

    def cell(f: Callable[[dict[str, Any]], Any]) -> str:
        return " | ".join(str(f(d)) for d in docs)

    rows_ += [
        f"| gate | {cell(lambda d: 'PASSED' if d['gate']['passed'] else 'FAILED')} |",
        f"| failed checks | {cell(lambda d: ', '.join(k for k, v in d['gate']['checks'].items() if not v) or '-')} |",
        f"| set / prompt / workers | {cell(_setup)} |",
        f"| skipped sources | {cell(lambda d: ', '.join(d['meta'].get('skipped') or {}) or '-')} |",
        f"| root / manifest | {cell(_weights)} |",
    ]
    for s in sorted({s for d in docs for s in d["by_source"]}):
        rows_.append(f"| wrong exclusions, {s} | {' | '.join(_source_we(d, s) for d in docs)} |")
    rows_ += [
        f"| wrong exclusions (gated pooled) | {cell(lambda d: _pc(d['gated']['wrong_exclusion']))} |",
        f"| fits precision (gated) | {cell(lambda d: _pc(d['gated']['fits_precision']))} |",
        f"| gold-unknown excluded | {cell(lambda d: _pc(d['gated']['unknown']['gold_unknown_excluded']))} |",
        f"| gold-unknown abstained | {cell(lambda d: _pc(d['gated']['unknown']['gold_unknown_abstained']))} |",
        f"| quote found | {cell(lambda d: _pc(d['all']['citation']['quote_found']))} |",
        f"| agreement | {cell(lambda d: _pc(d['all']['agreement']))} |",
        f"| no answer | {cell(lambda d: _pc(d['all']['no_answer']))} |",
        f"| call latency p50 / p95 s | {cell(lambda d: '{p50} / {p95}'.format(**d['all']['call_latency_s']))} |",
        f"| tokens in / out per call | "
        f"{cell(lambda d: '{in_per_call} / {out_per_call}'.format(**d['all']['tokens']))} |",
    ]
    ok = len({d["meta"]["set_sha256"] for d in docs}) == 1 and len({d["meta"]["prompt"] for d in docs}) == 1
    if not ok:
        rows_.append("\nNOT COMPARABLE: the runs used different item sets or prompt versions.")
    return "\n".join(rows_), ok


# ---------------------------------------------------------------------------------------------- stub server
Answer = Callable[[dict[str, Any]], dict[str, Any]]


def stub_answer(inp: dict[str, Any]) -> dict[str, Any]:
    from llm_stub.handlers import judge

    return judge(inp)


@contextmanager
def stub_server(
    served_name: str = STUB_NAME,
    root: str = STUB_ROOT,
    answer: Answer = stub_answer,
    report_model: str | None = None,
    seen_auth: list[str] | None = None,
    raw: Callable[[dict[str, Any]], tuple[int, Any]] | None = None,
) -> Iterator[str]:
    """A local OpenAI-compatible server on 127.0.0.1 (``/v1/models``, ``/v1/chat/completions``) answering the
    judge prompt with ``answer(input)``. Yields the base URL. For the offline run and the tests; no network."""
    block = re.compile(r"```json\s*(.*?)```", re.S)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _send(self, code: int, doc: Any) -> None:
            body = doc.encode() if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False).encode()
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
            if raw is not None:  # tests: a fixed status and body (errors, malformed answers)
                code, doc = raw(body)
                self._send(code, doc)
                return
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
def _loopback(url: str) -> bool:
    host = httpx.URL(url).host
    return host in ("127.0.0.1", "localhost", "::1")


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
    gate: GateConfig | None = None,
    backoff: tuple[float, ...] = BACKOFF_S,
    model_dir: Path | None = None,
    expect_manifest: str = "",
    revision: str = "",
    resume: bool = False,
) -> dict[str, Any]:
    """Pin, judge, score, write. :class:`PinRefused` before any item when the pin does not hold; ``ValueError`` when a
    key would go over plain http to another host."""
    from tb_common.llm import load_prompt

    key = os.environ.get(key_env, "")
    if key and httpx.URL(base_url).scheme != "https" and not _loopback(base_url):
        raise ValueError("refused: an endpoint key over plain http to a non-loopback host (use https or a tunnel)")
    client = BakeoffClient(base_url, served_name, key=key, backoff=backoff)
    pin = models_entry(client.http, base_url, served_name, expect_root)
    weights = weights_record(model_dir, expect_manifest, revision)
    p = load_prompt("judge")
    meta = {
        "served_name": served_name,
        "expect_root": expect_root or None,
        "pin": pin,
        "weights": weights,
        "auth": f"env:{key_env}" if key else "none",
        "prompt": f"{p.meta.id}@{p.meta.version}",
        "set_sha256": sha,
        "items": len(items),
        "workers": max(1, min(workers, MAX_WORKERS)),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skipped": skipped or {},
    }
    rows = run(client, items, workers, out=out, resume=resume)
    try:  # the same server and weights at the end: a restart or a swap during the run is seen
        unchanged = models_entry(client.http, base_url, served_name, expect_root) == pin
    except PinRefused:
        unchanged = False
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    m = metrics(rows, served_name, gate, {"root_verified": bool(expect_root), "unchanged": unchanged})
    write_results(out, rows, meta, m)
    return {"meta": meta, **m}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="judge_bakeoff", description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default="", help="OpenAI-compatible base URL, e.g. http://127.0.0.1:8000/v1")
    ap.add_argument("--served-name", default="", help="the model name the endpoint must serve")
    ap.add_argument("--expect-root", default="", help="the /v1/models root of the served name (required, not --stub)")
    ap.add_argument("--revision", default="", help="the weights' repository commit (recorded)")
    ap.add_argument("--model-dir", type=Path, default=None, help="the folder the server loaded: hashed and recorded")
    ap.add_argument("--expect-manifest", default="", help="the weight manifest sha256 the folder must have")
    ap.add_argument("--key-env", default=DEFAULT_KEY_ENV, help="environment variable holding the endpoint key")
    ap.add_argument("--stub", action="store_true", help="run against the built-in local stub server")
    ap.add_argument("--set", type=Path, default=None, help="a frozen item set (from --write-set)")
    ap.add_argument("--expect-set-sha", default="", help="the frozen set's sha256 (refused when different)")
    ap.add_argument("--write-set", type=Path, default=None, help="write the item set and exit (no model call)")
    ap.add_argument("--sources", nargs="+", default=list(SOURCES), choices=SOURCES)
    ap.add_argument("--require-sources", nargs="+", default=["synthetic", "medtxt"], choices=sorted(GATED))
    ap.add_argument("--n-per-source", type=int, default=0, help="seeded sample per source (0 = all)")
    ap.add_argument("--trec-pairs", type=int, default=200, help="NIST-eligible TREC CT pairs to sample")
    ap.add_argument("--workers", type=int, default=4, help=f"concurrent calls (at most {MAX_WORKERS})")
    ap.add_argument("--min-exclusions", type=int, default=GateConfig.min_exclusions, help="per gated source")
    ap.add_argument("--min-answered", type=int, default=GateConfig.min_answered, help="per gated source")
    ap.add_argument("--max-upper-ci", type=float, default=None, help="also gate the pooled upper Wilson 95 %% bound")
    ap.add_argument("--resume", action="store_true", help="keep answered rows already in --out/rows.jsonl")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--compare", nargs="+", type=Path, default=None, metavar="DIR")
    a = ap.parse_args(argv)
    if a.compare:
        text, ok = compare(a.compare)
        print(text)
        return 0 if ok else 1
    try:
        if a.set is not None:
            items, sha = read_set(a.set, a.expect_set_sha)
            skipped: dict[str, str] = {}
        else:
            items, skipped = build_set(tuple(a.sources), n_per_source=a.n_per_source, trec_pairs=a.trec_pairs)
            sha = set_sha(items)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    for s, why in skipped.items():
        print(f"skipped {s}: {why}", file=sys.stderr)
    if a.write_set is not None:
        print(f"wrote {len(items)} items to {a.write_set} (sha256 {write_set(items, a.write_set)})")
        return 0
    if a.out is None or not (a.stub or (a.base_url and a.served_name and a.expect_root)):
        print("need --out and either --stub or --base-url, --served-name and --expect-root", file=sys.stderr)
        return 2
    gate = GateConfig(
        min_exclusions=a.min_exclusions,
        min_answered=a.min_answered,
        max_upper_ci=a.max_upper_ci,
        require=tuple(a.require_sources),
    )
    common: dict[str, Any] = {
        "sha": sha,
        "key_env": a.key_env,
        "workers": a.workers,
        "skipped": skipped,
        "gate": gate,
        "resume": a.resume,
    }
    try:
        if a.stub:
            with stub_server() as url:
                res = bake(url, STUB_NAME, items, a.out, expect_root=STUB_ROOT, **common)
        else:
            res = bake(
                a.base_url,
                a.served_name,
                items,
                a.out,
                expect_root=a.expect_root,
                model_dir=a.model_dir,
                expect_manifest=a.expect_manifest,
                revision=a.revision,
                **common,
            )
    except PinRefused as e:
        print(str(e), file=sys.stderr)
        return 3
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print((a.out / "metrics.md").read_text(encoding="utf-8"), end="")
    return 0 if res["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
