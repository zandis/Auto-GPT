"""Review tests G-4, G-5, G-7 and G-8 of plan v7 §7.1 as parts of the complete run (``tools.complete_run``).

Each is a part of its own, in a run only when ``--only`` names it (as ``chat-template``, G-1), with a row in the
estimate and a section in the report. Synthetic or public data only; the product is called through its own public
functions and the gateway built as an installed box builds it (``tools.scenarios``); no product code changes.

``g4-decoding`` (G-4)
    The structured-output backend, read from the servers (the serving record the VM captures from the running
    containers' command lines; vLLM's ``/server_info`` when the server answers it). Guided decoding on and off: the
    judge prompt (the product's ``judge`` prompt, rendered by ``tb_common.llm.render``) over a fixed synthetic excerpt
    set, sent straight to the judge server with and without the prompt's ``response_format``, at the judge's
    ``max_num_seqs`` in flight; calls per second each way and the answers outside the judge schema (each way: their
    count by ``finish_reason`` and the first few with their completion tokens and opening text, so a cut at
    ``max_tokens`` is told from a fenced or wordy answer). Eager start on and
    off needs the servers restarted (``--enforce-eager`` is a start flag of vLLM): not run, recorded as such; the part
    never restarts a server.
``g5-tokens`` (G-5)
    200 ja, 200 zh-TW and 200 en synthetic excerpts (``tools.synth.notes_ja``, ``tools.synth.notes``,
    ``tools.synth.notes_en``): the judge server's
    real count (``POST /tokenize``) against the product's two estimates (``tb_llm.budget.estimate_tokens`` and the
    cascade's ``matching.cascade.judge.expected_tokens``), and the rendered judge prompt against
    ``tb_llm.budget.estimate_messages``. The ratio real / estimate: p50, p95, max per language and estimator.
``g7-clipped`` (G-7)
    The two LLM-001 cases of the deep review (``docs/reviews/2026-11-12-deep-review/06-llm.md``): family history
    under the wrong heading (ja) and a denied list without its lead-in (zh-TW), as synthetic notes. The product's
    own clip (``matching.cascade.engine._Run.excerpt_set``) gives the excerpt; the judge, the verifier and the pair
    (``orchestrator.scenarios.evaluate.NoteJudge.judge_excerpts``, the SCREEN path) answer on the clipped and on the
    whole note. Recorded: the verdicts per case and view, and whether a final "not met" came from a clipped note.
``g8-protocols`` (G-8)
    Public protocols compiled with the production judge (``criteria_compiler.service.Compiler.compile`` with the
    judge's client through the gateway): class split, ``needs_review`` and ``time_sensitive`` per criterion. The
    protocols are read from ``TB_G8_PROTOCOLS_DIR`` (ClinicalTrials.gov JSON or plain text); master has none of the
    two the plan names (RA, early AD), so without that folder the part says "no fixture on master: not run".
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

G4, G5, G7, G8 = "g4-decoding", "g5-tokens", "g7-clipped", "g8-protocols"
TESTS = {G4: "G-4", G5: "G-5", G7: "G-7", G8: "G-8"}
REPORT_KEYS = {G4: "decoding", G5: "tokens", G7: "clipped", G8: "protocols"}

# OD-10, each with its reason:
# G-5's sample: the plan's own number (plan v7 §7.1 G-5: "200 ja and 200 zh-TW excerpts"), and as many en (the
# owner's addition of 2026-11-13: English notes are budgeted by the same estimators, at another characters-per-token)
N_EXCERPTS = 200
G5_LANGS = ("ja", "zh-TW", "en")
# G-4: each of the judge's slots answers this many calls per setting, so calls per second is a rate over several
# rounds of a full batch, not one round's latency (the slots are the serving record's max_num_seqs)
DECODING_ROUNDS = 4
# G-4: per setting (guided on, guided off), the answers outside the judge schema kept as examples, and how much of each
# answer's text: enough to tell a cut at max_tokens (finish_reason "length", the JSON unclosed) from a whole answer
# in a markdown fence or with prose around it, without copying every answer into the report (the prompts are
# synthetic, so the text is safe to keep); as many calls not answered are kept with their status and why
SCHEMA_FAILURE_EXAMPLES = 5
EXAMPLE_CHARS = 200
# G-5's pass rule (deep review 06-llm.md, test G-05): the largest measured ratio, with 5 % for what the sample did not
# see, must fit in the budget's safety share (1 / tb_llm.budget.SAFETY)
RATIO_MARGIN = 1.05
# the estimate: a part's own start (one process, the gateway built in it, the prompt registry read); not measured,
# so set high, as chat_template_check.SECONDS
PART_START_SECONDS = 120.0
SEED = 20261112


# ---------------------------------------------------------------- shared pure helpers
def percentile(xs: Sequence[float], q: float) -> float | None:
    """The nearest-rank ``q`` percentile (0 < q <= 100) of ``xs``; None when empty."""
    if not xs:
        return None
    s = sorted(xs)
    return float(s[max(0, math.ceil(q / 100 * len(s)) - 1)])


def ratio_stats(pairs: Sequence[tuple[int | None, int]]) -> dict[str, Any]:
    """``(real, estimate)`` pairs -> the ratio real / estimate: n, p50, p95, max, mean (pairs with no real count or a
    zero estimate are counted under ``missing``)."""
    r = [real / est for real, est in pairs if real is not None and est > 0]
    return {"n": len(r), "missing": len(pairs) - len(r),
            "p50": _round(percentile(r, 50)), "p95": _round(percentile(r, 95)), "max": _round(max(r) if r else None),
            "mean": _round(sum(r) / len(r) if r else None)}  # fmt: skip


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def synthetic_excerpts(lang: str, n: int = N_EXCERPTS, seed: int = SEED) -> list[str]:
    """``n`` fictional note excerpts in ``lang`` (ja, zh-TW or en) from the synthetic hospital's sentence sets: filler,
    flares, joint counts, response figures, imaging; 1 to 12 sentences each, so the sizes span short excerpts to
    the long ones the budget clips. Deterministic for a seed."""
    from tools.synth import notes as zh
    from tools.synth import notes_en as en
    from tools.synth import notes_ja as ja

    rng = random.Random(f"{seed}:{lang}")
    m: Any = {"ja": ja, "en": en}.get(lang, zh)
    dates = {"ja": ["2026年3月14日", "令和8年2月3日", "2025年12月1日"], "zh-TW": ["民國115年3月14日", "2026年2月3日"],
             "en": ["14 March 2026", "3 Feb 2026", "1 Dec 2025"]}  # fmt: skip
    when = dates.get(lang, dates["zh-TW"])

    def domain() -> str:
        d, j = rng.choice(when), rng.choice(m.JOINTS)
        pick = rng.randrange(8)
        if pick == 0:
            return str(m.flare_sentence(d, j) if lang in ("ja", "en") else m.flare_sentence(date(2026, 3, 14), j, d))
        if pick == 1:
            return str(m.ra_assessment_sentence(rng.randint(0, 28), rng.randint(0, 28), rng.randint(0, 100)))
        if pick == 2:
            return str(m.response_sentence(rng.uniform(0.2, 2.4), rng.random() < 0.5))
        return str(rng.choice([m.no_flare_sentence(), m.current_flare_sentence(), m.no_current_flare_sentence(),
                               m.ECOG_SENTENCE, m.CXR_CLEAR, m.LUNG_MASS]))  # fmt: skip

    out = []
    for _ in range(n):
        k = rng.randint(1, 12)
        parts = [rng.choice(m.FILLER) if rng.random() < 0.6 else domain() for _ in range(k)]
        if lang == "en":  # English sentences are joined by a space (a few templates end without one)
            parts = [p if p.endswith(" ") else p + " " for p in parts]
        out.append("".join(parts).strip() if lang == "en" else "".join(parts))
    return out


def judge_messages(excerpt: str, lang: str, prompt: Any, case: int = 0) -> list[dict[str, str]]:
    """The product's ``judge`` prompt rendered over one synthetic excerpt (a gout-flare note question)."""
    from tb_common.llm import render

    variables = {
        "criterion_text": "At least two gout flares in the past 12 months",
        "note_question": "Did the patient have two or more gout flares in the 12 months before the index date?",
        "index_date": "2026-06-30",
        "excerpts": [{"date": "2026-06-0" + str(1 + case % 9), "note_type": "progress", "text": excerpt}],
    }
    return render(prompt, variables)


# ---------------------------------------------------------------- HTTP to the VM's own model servers
def _opener() -> Any:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))  # the VM's own servers, never a proxy


def post_json(url: str, body: dict[str, Any], key: str = "", timeout: float = 60.0,
              headers: dict[str, str] | None = None) -> tuple[int, Any]:  # fmt: skip
    """POST ``body``; ``(status, parsed JSON)``, ``(0, error text)`` when the server does not answer."""
    hdr = {"Content-Type": "application/json", **(headers or {})}
    if key:
        hdr["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), headers=hdr)
    try:
        with _opener().open(req, timeout=timeout) as r:
            return int(r.status), json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc.reason)[:200]
    except (OSError, ValueError) as exc:
        return 0, str(exc)[:200]


def tokenize(root: str, served: str, key: str, *, text: str | None = None,
             messages: list[dict[str, str]] | None = None) -> int | None:  # fmt: skip
    """The server's own count (``POST /tokenize``, vLLM's route) of a text or of chat messages; None: no answer."""
    body: dict[str, Any] = {"model": served}
    if messages is not None:
        body.update({"messages": messages, "add_generation_prompt": True})
    else:
        body["prompt"] = text or ""
    status, got = post_json(root + "/tokenize", body, key)
    if status != 200 or not isinstance(got, dict):
        return None
    if isinstance(got.get("count"), int):
        return int(got["count"])
    toks = got.get("tokens")
    return len(toks) if isinstance(toks, list) else None


def _judge_record(a: Any) -> dict[str, Any]:
    from tools.complete_run import VENDOR_RECORD

    path = a.live_record if getattr(a, "live_record", None) and Path(a.live_record).is_file() else VENDOR_RECORD
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    judge: dict[str, Any] = next((s for s in rec.get("servers") or [] if s.get("role") == "judge"), {})
    return {"path": str(path), "judge": judge}


def _no_server(name: str, t0: float) -> dict[str, Any]:
    from tools.complete_run import _one

    checks = [("the judge server's URL is given (--model pair)", False, "no --judge-url: needs the card")]
    return {"stages": _one(name, checks, time.perf_counter() - t0), "not_run": "no judge server"}


# ---------------------------------------------------------------- G-4: the decoding
def backend_from_server_info(text: str) -> str | None:
    """The structured-output backend in vLLM's ``/server_info`` text (its config, printed), None when not there."""
    m = re.search(r"(?:structured_outputs_config|guided_decoding)[^)]*?backend='?\"?([A-Za-z0-9_:-]+)", text or "")
    if not m:
        m = re.search(r"guided_decoding_backend['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_:-]+)", text or "")
    return m.group(1) if m else None


def backend_of(judge: dict[str, Any], server_info: str = "") -> dict[str, Any]:
    """The judge's structured-output backend and where it was read: the server's ``/server_info`` first, then the
    serving record (captured from the running container's command line; vLLM's default ``auto`` when no flag)."""
    live = backend_from_server_info(server_info)
    if live:
        return {"backend": live, "from": "the judge server's /server_info", "named": live != "auto"}
    rec = judge.get("structured_outputs_backend")
    if not rec and isinstance(judge.get("extra_args"), list):  # a record older than the field: its command line
        from tools.serving_config import BACKEND_FLAG

        rec = None if any(str(x).startswith(BACKEND_FLAG.split(".")[0]) for x in judge["extra_args"]) else "auto"
    if rec:
        return {
            "backend": rec,
            "from": "the serving record (the container's command line)",
            "named": rec != "auto",
            "note": "" if rec != "auto" else "auto: vLLM picks the backend per request; not named by a flag",
        }
    return {"backend": None, "from": "neither the server nor the serving record says"}


def n_decoding_prompts(seqs: int) -> int:
    """G-4's fixed prompt set: :data:`DECODING_ROUNDS` full batches of the judge's slots."""
    return DECODING_ROUNDS * max(1, int(seqs))


def answer_in_schema(content: Any, schema_name: str) -> bool:
    """Is a model's text one JSON object inside the product's judge schema (as ``GatewayJudge`` checks it)?"""
    from tb_contracts import load_schema, null_absent, schema_errors

    if not isinstance(content, str):
        return False
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    try:
        data = json.loads(fence.group(1) if fence else text)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    return not schema_errors(schema_name, null_absent(load_schema(schema_name), data))


def failure_example(r: dict[str, Any]) -> dict[str, Any]:
    """One answer outside the schema as the report keeps it: why the model stopped, its tokens, its first
    :data:`EXAMPLE_CHARS` characters."""
    content = r.get("content")
    return {"finish_reason": r.get("finish_reason"), "completion_tokens": r.get("completion_tokens"),
            "content_head": content[:EXAMPLE_CHARS] if isinstance(content, str) else content}  # fmt: skip


def decoding_summary(results: Sequence[dict[str, Any]], seconds: float) -> dict[str, Any]:
    """One setting's calls: answered, errors, schema failures, calls per second over the wall time, p50 / p95; the
    schema failures by finish_reason and the first :data:`SCHEMA_FAILURE_EXAMPLES` of them (:func:`failure_example`).

    Every call is either answered or an error: the schema failures are of the answered calls (an answer that never
    came cannot be judged), so ``answered + errors == calls`` and each error keeps its status and why (the first
    :data:`SCHEMA_FAILURE_EXAMPLES` under ``unanswered``): train 16's CI lost one call to a reset connection and the
    count alone (63 schema failures of 64) did not say so."""
    ok = [r for r in results if r.get("status") == 200]
    lost = [r for r in results if r.get("status") != 200]
    lat = [float(r["seconds"]) for r in ok]
    bad = [r for r in ok if not r.get("in_schema")]
    why: dict[str, int] = {}
    for r in bad:
        k = str(r.get("finish_reason"))
        why[k] = why.get(k, 0) + 1
    return {"calls": len(results), "answered": len(ok), "errors": len(results) - len(ok),
            "schema_failures": len(bad), "seconds": round(seconds, 2),
            "calls_per_second": round(len(ok) / seconds, 3) if seconds > 0 else None,
            "p50_s": _round(percentile(lat, 50)), "p95_s": _round(percentile(lat, 95)),
            "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in ok),
            "schema_failures_by_finish_reason": why,
            "schema_failure_examples": [failure_example(r) for r in bad[:SCHEMA_FAILURE_EXAMPLES]],
            "unanswered": [{"status": r.get("status"), "error": r.get("error")}
                           for r in lost[:SCHEMA_FAILURE_EXAMPLES]]}  # fmt: skip


def faster_setting(on: dict[str, Any], off: dict[str, Any]) -> str:
    """The profile G-4 asks for: the faster setting, unless it gave an answer outside the schema (then guided on)."""
    if off.get("schema_failures") or off.get("errors") or not off.get("calls_per_second"):
        return "guided decoding on"
    return "guided decoding off" if off["calls_per_second"] > (on.get("calls_per_second") or 0) else \
        "guided decoding on"  # fmt: skip


def run_g4(a: Any) -> dict[str, Any]:
    from tb_common.llm import load_prompt
    from tb_contracts import inline_schema
    from tb_llm import json_schema_format
    from tb_llm.timeouts import UPSTREAM_READ_S

    from tools.complete_run import JUDGE, _one, record_max_seqs
    from tools.run_metrics import fetch, server_root

    t0 = time.perf_counter()
    if not getattr(a, "judge_url", ""):
        return _no_server(f"{TESTS[G4]} decoding: no judge server", t0)
    key = os.environ.get("TB_GPU_KEY", "")
    root = server_root(a.judge_url)
    rec = _judge_record(a)
    backend = backend_of(rec["judge"], fetch(root + "/server_info", key))
    seqs = record_max_seqs(Path(rec["path"]))
    p = load_prompt("judge", "PRODUCTION")  # the version an installed box's gateway serves (D-359)
    fmt = json_schema_format(p.meta.id, inline_schema(p.meta.output_schema))
    texts = [t for lang in ("ja", "zh-TW") for t in synthetic_excerpts(lang, n_decoding_prompts(seqs) // 2 + 1)]
    msgs = [judge_messages(t, "ja", p, i) for i, t in enumerate(texts[: n_decoding_prompts(seqs)])]
    headers = {"X-TB-Prompt-Id": p.meta.id, "X-TB-Prompt-Version": str(p.meta.version)}  # the stand-ins' answer key

    def one(m: list[dict[str, str]], guided: bool) -> dict[str, Any]:
        """One call, once. A call the server does not answer (a transport error, or not 200) is recorded with its
        status and why, not retried: G-4 measures the server at its full batch, so a lost call is a finding about the
        server or its network, and the setting's "calls answered" check fails and says so."""
        body: dict[str, Any] = {"model": JUDGE, "messages": m, "max_tokens": p.meta.max_tokens, "temperature": 0}
        if guided:
            body["response_format"] = fmt
        t = time.perf_counter()
        status, got = post_json(root + "/v1/chat/completions", body, key, UPSTREAM_READ_S, headers)
        took = time.perf_counter() - t
        if status != 200 or not isinstance(got, dict):
            return {"status": status, "seconds": took, "error": str(got)[:120]}
        choice = (got.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        ok = answer_in_schema(content, p.meta.output_schema)
        return {"status": 200, "seconds": took, "in_schema": ok, "finish_reason": choice.get("finish_reason"),
                "completion_tokens": (got.get("usage") or {}).get("completion_tokens"),
                "content": None if ok or not isinstance(content, str) else content[:EXAMPLE_CHARS]}  # fmt: skip

    def setting(guided: bool) -> dict[str, Any]:
        t = time.perf_counter()
        with ThreadPoolExecutor(max_workers=seqs, thread_name_prefix="g4") as ex:
            res = list(ex.map(lambda m: one(m, guided), msgs))
        return decoding_summary(res, time.perf_counter() - t)

    on, off = setting(True), setting(False)
    eager = {
        "enforce_eager": rec["judge"].get("enforce_eager"),
        "switched": False,
        "result": "needs a restart: not run (--enforce-eager is a start flag; the part never restarts a server)",
    }
    block = {"backend": backend, "prompts": len(msgs), "in_flight": seqs, "guided_on": on, "guided_off": off,
             "profile": faster_setting(on, off), "eager": eager, "record": rec["path"]}  # fmt: skip
    checks: list[tuple[str, bool, Any]] = [
        ("the structured-output backend is read from the servers", bool(backend.get("backend")), backend),
        (f"guided on: {len(msgs)} calls answered", on["errors"] == 0, {k: on[k] for k in ("answered", "errors")}),
        ("guided on: no answer outside the judge schema", on["answered"] > 0 and on["schema_failures"] == 0,
         on["schema_failures"]),
        (f"guided off: {len(msgs)} calls answered (schema failures recorded, not a pass rule)", off["errors"] == 0,
         {k: off[k] for k in ("answered", "errors", "schema_failures")}),
    ]  # fmt: skip
    return {"stages": _one(f"{TESTS[G4]} structured output: backend, guided decoding on and off, eager start", checks,
                           time.perf_counter() - t0), REPORT_KEYS[G4]: block}  # fmt: skip


# ---------------------------------------------------------------- G-5: the token counts
def count_rows(texts: Sequence[str], real: Callable[[str], int | None]) -> list[dict[str, Any]]:
    """Per excerpt: the server's count and the product's two estimators (the budget's and the cascade's; since D-645
    the cascade counts with the budget's estimate, so the two columns agree, and both stay measured)."""
    from matching.cascade.judge import expected_tokens
    from tb_llm.budget import estimate_tokens

    return [{"chars": len(t), "real": real(t), "budget": estimate_tokens(t),
             "cascade": expected_tokens([{"text": t}]) - 300} for t in texts]  # fmt: skip


def token_summary(rows: dict[str, list[dict[str, Any]]], prompts: dict[str, list[tuple[int | None, int]]],
                  safety: float) -> dict[str, Any]:  # fmt: skip
    """Ratios per language and estimator, the worst one, and whether it fits the budget's safety share."""
    out: dict[str, Any] = {"per_language": {}}
    worst = 0.0
    for lang, rs in rows.items():
        per = {est: ratio_stats([(r["real"], r[est]) for r in rs]) for est in ("budget", "cascade")}
        per["prompt"] = ratio_stats(prompts.get(lang) or [])
        out["per_language"][lang] = per
        worst = max([worst, *(float(s["max"]) for s in per.values() if s["max"] is not None)])
    limit = 1 / safety
    out.update(
        {
            "max_ratio": round(worst, 4),
            "margin": RATIO_MARGIN,
            "safety": safety,
            "limit": round(limit, 4),
            "fits": worst > 0 and worst * RATIO_MARGIN <= limit,
            "safety_from_measurement": round(min(safety, 1 / (worst * RATIO_MARGIN)), 4) if worst else None,
        }
    )
    return out


def run_g5(a: Any) -> dict[str, Any]:
    from tb_common.llm import load_prompt
    from tb_llm.budget import SAFETY, estimate_messages

    from tools.complete_run import JUDGE, _one
    from tools.run_metrics import server_root

    t0 = time.perf_counter()
    if not getattr(a, "judge_url", ""):
        return _no_server(f"{TESTS[G5]} token counts: no judge server", t0)
    key, root = os.environ.get("TB_GPU_KEY", ""), server_root(a.judge_url)
    p = load_prompt("judge", "PRODUCTION")
    rows: dict[str, list[dict[str, Any]]] = {}
    prompts: dict[str, list[tuple[int | None, int]]] = {}
    for lang in G5_LANGS:
        texts = synthetic_excerpts(lang)
        rows[lang] = count_rows(texts, lambda t: tokenize(root, JUDGE, key, text=t))
        msgs = [judge_messages(t, lang, p, i) for i, t in enumerate(texts)]
        prompts[lang] = [(tokenize(root, JUDGE, key, messages=m), estimate_messages(m)) for m in msgs]
    s = token_summary(rows, prompts, SAFETY)
    counted = {lang: sum(1 for r in rs if r["real"] is not None) for lang, rs in rows.items()}
    s.update(
        {
            "excerpts": {lang: len(rs) for lang, rs in rows.items()},
            "counted": counted,
            "chars": {lang: [min(r["chars"] for r in rs), max(r["chars"] for r in rs)] for lang, rs in rows.items()},
        }
    )
    checks: list[tuple[str, bool, Any]] = [
        (f"/tokenize counted all {N_EXCERPTS} excerpts of each language ({', '.join(G5_LANGS)})",
         all(counted[lang] == N_EXCERPTS for lang in counted), counted),
        (f"the largest real / estimated ratio x {RATIO_MARGIN} fits the budget's share (1 / SAFETY = {1 / SAFETY:.3f})",
         bool(s["fits"]), {"max_ratio": s["max_ratio"], "safety_from_measurement": s["safety_from_measurement"]}),
    ]  # fmt: skip
    return {"stages": _one(f"{TESTS[G5]} token counts: /tokenize against the product's estimates", checks,
                           time.perf_counter() - t0), REPORT_KEYS[G5]: s}  # fmt: skip


# ---------------------------------------------------------------- G-7: the clipped note
TB_LEXICON = ("tuberculosis", "結核", "肺結核", "tb")  # the lexicon the review used for a tuberculosis exclusion
TB_CRITERION = ("Active or past tuberculosis",
                "Does the patient have active tuberculosis or a history of tuberculosis?")  # fmt: skip


def _llm001_notes(days: int) -> list[dict[str, Any]]:
    """The two LLM-001 notes with ``days`` lines of ward diary in front of the history sections."""
    from tools.synth import notes as zh
    from tools.synth import notes_ja as ja

    daily_ja = [f"入院{i}日目、{ja.FILLER[i % len(ja.FILLER)]}" for i in range(1, days + 1)]
    note_ja = "\n".join(["【現病歴】", *daily_ja, "【既往歴】", "高血圧症。", "脂質異常症。", "【家族歴】", "肺結核。",
                         "糖尿病。", "【アレルギー】", "なし。"])  # fmt: skip
    daily_zh = [f"住院第{i}天，{zh.FILLER[i % len(zh.FILLER)]}" for i in range(1, days + 1)]
    note_zh = "\n".join(["【現病史】", *daily_zh, "【過去病史】", "高血壓。", "病人否認下列病史：", "肺結核。",
                         "B型肝炎。", "【過敏史】", "無。"])  # fmt: skip
    return [
        {"id": "LLM-001-ja-family-history", "lang": "ja", "text": note_ja, "truth": "not the patient's own (family)",
         "what": "肺結核 only under 【家族歴】"},
        {"id": "LLM-001-zh-TW-denied-list", "lang": "zh-TW", "text": note_zh, "truth": "denied by the patient",
         "what": "肺結核 in a list after 病人否認下列病史："},
    ]  # fmt: skip


def clip_cases() -> list[dict[str, Any]]:
    """The two LLM-001 notes of the deep review (06-llm.md §3.1), synthetic. Truth: tuberculosis is not the patient's
    own history in either (a relative's; a denied disease). The ward diary grows, doubling, until the product's own
    excerpt builder clips both notes: no length is fixed here, so the test still clips when the builder's budget or
    its token estimate changes (run 20261113T044219Z measured a clip at 59 days; master's builder then showed that
    note whole)."""
    days = 60
    while True:
        cases = _llm001_notes(days)
        if all(clipped_view(c)["clipped"] for c in cases):
            return cases
        days *= 2


def clipped_view(case: dict[str, Any], terms: Sequence[str] = TB_LEXICON) -> dict[str, Any]:
    """The cascade's excerpt of one note (``_Run.excerpt_set``, the product's own clip) and what it shows."""
    from matching.cascade.engine import _Note, _Run
    from matching.cascade.judge import norm
    from matching.excerpts import sentences

    text = str(case["text"])
    note = _Note(case["id"], date(2026, 6, 1), "discharge", text, sentences(text))
    ev = [s for s in note.sents if any(t in norm(s).lower() for t in terms)]
    shown, left_out = _Run.excerpt_set([note], {note.did: ev})
    shown_text = "\n".join(str(x["text"]) for x in shown)
    return {
        "excerpts": shown,
        "left_out": left_out,
        "evidence": ev,
        "clipped": shown_text != text,
        "chars_whole": len(text),
        "chars_shown": len(shown_text),
        "kept_heading": {
            h: h in shown_text for h in ("【家族歴】", "【既往歴】", "【過去病史】", "病人否認下列病史") if h in text
        },
    }


def final_outcome(predicate: str, confidence: float, quoted: bool, left_out: int, floor: float,
                  kind: str = "exclusion") -> str:  # fmt: skip
    """What the cascade makes of one pair answer (``engine._Run._map`` with the pair, ``note_block`` on): ``not met
    (final)`` is a hard exclusion; ``review`` goes to a person; ``met`` keeps the patient."""
    if predicate not in ("pass", "fail") or not quoted:
        return "review"
    eligible = (predicate == "pass") == (kind == "inclusion")
    if eligible:
        return "met"
    if left_out or confidence < floor:
        return "review"
    return "not met (final)"


def run_g7(a: Any) -> dict[str, Any]:
    from matching.cascade.engine import CascadeConfig
    from orchestrator.scenarios.evaluate import NoteJudge

    from tools.complete_run import _models, _one

    t0 = time.perf_counter()
    llm, verifier = _models(a)
    if llm is None or verifier is None:
        why = "needs --model pair"
        refused: list[tuple[str, bool, Any]] = [("the pair is wired through the gateway (--model pair)", False, why)]
        return {"stages": _one(f"{TESTS[G7]} clipped notes: no pair", refused, time.perf_counter() - t0),
                "not_run": "no model pair"}  # fmt: skip
    floor = CascadeConfig(study_id="g7", run_date=date(2026, 6, 30)).confidence_floor
    nj = NoteJudge(lake=None, llm=llm, verifier=verifier)
    cases = []
    for case in clip_cases():
        view = clipped_view(case)
        whole = [{"date": "2026-06-01", "note_type": "discharge", "text": case["text"], "did": case["id"]}]
        got: dict[str, Any] = {}
        for name, ex, left in (("clipped_view", view["excerpts"], view["left_out"]), ("whole_view", whole, 0)):
            q, ix = TB_CRITERION, date(2026, 6, 30)
            j = nj.judge_excerpts(q[0], q[1], ix, ex, verify=False)
            v = nj.judge_excerpts(q[0], q[1], ix, ex, verify=False, primary=verifier)
            pair = nj.judge_excerpts(q[0], q[1], ix, ex)
            got[name] = {
                "judge": j.predicate,
                "verifier": v.predicate,
                "pair": pair.predicate,
                "reasons": [j.reason, v.reason, pair.reason],
                "quote": pair.quote,
                "left_out": left,
                "final": final_outcome(pair.predicate, pair.confidence, bool(pair.dids), left, floor),
            }
        cases.append({k: case[k] for k in ("id", "lang", "truth", "what")}
                     | {k: view[k] for k in ("clipped", "left_out", "chars_whole", "chars_shown", "kept_heading")}
                     | got)  # fmt: skip
    finals = clipped_finals(cases)
    block = {"criterion": TB_CRITERION[0], "lexicon": list(TB_LEXICON), "confidence_floor": floor, "cases": cases,
             "final_not_met_from_clipped_note": finals}  # fmt: skip
    down = [c["id"] for c in cases for v in ("clipped_view", "whole_view") if "model_down" in c[v]["reasons"][:2]]
    checks: list[tuple[str, bool, Any]] = [
        (f"{len(cases)} LLM-001 cases: the judge and the verifier answered on the clipped and the whole note",
         not down, {c["id"]: [c["clipped_view"]["pair"], c["whole_view"]["pair"]] for c in cases}),
        ("0 exclusions on a clipped note (no final not met from a clipped note)", not finals, finals),
    ]  # fmt: skip
    return {"stages": _one(f"{TESTS[G7]} clipped against whole note (LLM-001)", checks, time.perf_counter() - t0),
            REPORT_KEYS[G7]: block}  # fmt: skip


def clipped_finals(cases: Sequence[dict[str, Any]]) -> list[str]:
    """The cases whose final "not met" (a hard exclusion) came from a clipped note."""
    return [c["id"] for c in cases if c["clipped"] and c["clipped_view"]["final"] == "not met (final)"]


# ---------------------------------------------------------------- G-8: two public protocols
EXTENSION = re.compile(r"extension|open[- ]label|\bOLE\b|core (?:study|phase)|延長|延伸|継続投与", re.I)
ALTERNATIVE = re.compile(r"one of the following|any of the following|\beither\b|いずれか|下列任一|下列其中|之一", re.I)
PROTOCOL_SUFFIXES = (".json", ".txt", ".md")


def protocols_dir(env: dict[str, str] | None = None) -> Path:
    """``TB_G8_PROTOCOLS_DIR`` (a relative path is under the repository), else the default fixtures folder."""
    e = os.environ if env is None else env
    raw = (e.get("TB_G8_PROTOCOLS_DIR") or "").strip() or "tests/fixtures/public_protocols"
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def protocol_files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.iterdir() if f.suffix in PROTOCOL_SUFFIXES) if folder.is_dir() else []


def read_protocol(path: Path) -> dict[str, Any]:
    """One public protocol: ClinicalTrials.gov v2 JSON (a study, ``{"study": ...}`` or ``{"studies": [...]}``) or
    plain text (the eligibility section as published). ``{"id", "title", "conditions", "text"}``."""
    if path.suffix != ".json":
        return {"id": path.stem, "title": path.stem, "conditions": [], "text": path.read_text(encoding="utf-8")}
    doc = json.loads(path.read_text(encoding="utf-8"))
    study = doc.get("study") or (doc.get("studies") or [doc])[0]
    ps = study.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    return {"id": ident.get("nctId") or doc.get("nct_id") or path.stem, "title": ident.get("briefTitle") or "",
            "conditions": (ps.get("conditionsModule") or {}).get("conditions") or [],
            "text": (ps.get("eligibilityModule") or {}).get("eligibilityCriteria") or ""}  # fmt: skip


def alternative_groups(text: str) -> list[dict[str, Any]]:
    """Lines that open a group of alternatives ("one of the following", いずれか, 下列任一) and the lines under them:
    the lines indented deeper than the opener, else the lines up to the next blank line."""
    lines = text.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if not ALTERNATIVE.search(ln):
            continue
        ind = len(ln) - len(ln.lstrip())
        deeper: list[str] = []
        flat: list[str] = []
        for nxt in lines[i + 1 :]:
            if not nxt.strip():
                break
            if len(nxt) - len(nxt.lstrip()) > ind:
                deeper.append(nxt.strip())
            elif deeper:
                break
            flat.append(nxt.strip())
        members = [re.sub(r"^[*\-•o\d.)\s]+", "", m).strip() for m in (deeper or flat)]
        out.append({"opener": ln.strip(), "members": [m for m in members if m]})
    return out


def _flagged(c: dict[str, Any], warnings: Sequence[str]) -> bool:
    head = c["text"][:30]
    return bool(c["needs_review"]) or any(c["id"] in w or (head and head in w) for w in warnings)


def protocol_findings(criteria: Sequence[dict[str, Any]], warnings: Sequence[str], text: str) -> dict[str, Any]:
    """G-8's record of one compiled protocol: the class split, ``needs_review`` and ``time_sensitive`` per criterion,
    the extension-phase lines active without a warning, and the alternative groups flattened to AND (two or more
    members compiled as separate criteria, none flagged, and no warning naming the group)."""
    split: dict[str, int] = {}
    for c in criteria:
        split[c["class"]] = split.get(c["class"], 0) + 1
    ext = [c for c in criteria if EXTENSION.search(c["text"]) and c["active"]]
    groups = []
    for g in alternative_groups(text):
        mem = [c for c in criteria if any(m[:40] in c["text"] or c["text"][:40] in m for m in g["members"])]
        named = any(g["opener"][:30] in w or re.search(r"alternative|\bOR\b", w) for w in warnings)
        flattened = len(mem) > 1 and not named and not any(_flagged(c, warnings) for c in mem)
        groups.append({"opener": g["opener"][:120], "members": len(g["members"]),
                       "criteria": [c["id"] for c in mem], "flattened_to_and": flattened})  # fmt: skip
    return {"criteria": len(criteria), "class_split": split,
            "needs_review": [c["id"] for c in criteria if c["needs_review"]],
            "time_sensitive": [c["id"] for c in criteria if c["time_sensitive"]],
            "extension_lines": [c["id"] for c in ext],
            "extension_active_without_warning": [c["id"] for c in ext if not _flagged(c, warnings)],
            "alternative_groups": groups, "per_criterion": list(criteria)}  # fmt: skip


def criterion_row(c: Any) -> dict[str, Any]:
    """A compiled ``CriterionIR`` as G-8 records it."""
    text = getattr(c.text, "source", c.text)
    flags = list(c.flags or [])
    rejected = bool(c.review and getattr(c.review, "status", "") == "rejected")
    return {"id": c.id, "kind": c.kind, "class": c.class_, "text": str(text), "needs_review": "needs_review" in flags,
            "time_sensitive": bool(c.time_sensitive), "flags": flags, "active": not rejected}  # fmt: skip


def run_g8(a: Any) -> dict[str, Any]:
    from tools.complete_run import _models, _one

    t0 = time.perf_counter()
    folder = protocols_dir()
    files = protocol_files(folder)
    if not files:
        where = folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder
        checks: list[tuple[str, bool, Any]] = [
            ("public protocol fixtures (RA, early AD) are on this machine", False,
             f"no fixture on master: not run ({where} is empty or missing; TB_G8_PROTOCOLS_DIR names another folder)"),
        ]  # fmt: skip
        return {
            "stages": _one(
                f"{TESTS[G8]} public protocols: no fixture on master: not run", checks, time.perf_counter() - t0
            ),
            "not_run": "no fixture on master",
            REPORT_KEYS[G8]: {"folder": str(where), "protocols": [], "result": "no fixture on master: not run"},
        }
    llm, _ = _models(a, caller="criteria-compiler")  # as the box's compiler calls its gateway (defect B13)
    if llm is None:
        checks = [("the production judge is wired through the gateway (--model pair)", False, "needs --model pair")]
        return {"stages": _one(f"{TESTS[G8]} public protocols: no judge", checks, time.perf_counter() - t0),
                "not_run": "no model pair"}  # fmt: skip
    out = []
    for i, f in enumerate(files):
        proto = read_protocol(f)
        try:
            criteria, warnings = compile_protocol(proto, a.dir / "g8" / f"p{i + 1}", llm, f"G8P{i + 1}")
            rec = {"file": f.name, **{k: proto[k] for k in ("id", "title", "conditions")}, "warnings": warnings,
                   **protocol_findings(criteria, warnings, proto["text"])}  # fmt: skip
        except Exception as exc:  # one protocol that does not compile is a failed row, not a lost part
            rec = {"file": f.name, "id": proto["id"], "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        out.append(rec)
    ok = [r for r in out if "error" not in r]
    checks = [
        (f"{len(files)} protocol(s) compiled with the production judge", len(ok) == len(files),
         [r.get("error") for r in out if "error" in r]),
        ("no extension-phase line active without a warning",
         bool(ok) and not any(r["extension_active_without_warning"] for r in ok),
         {r["id"]: r["extension_active_without_warning"] for r in ok}),
        ("alternative diagnosis groups not flattened to AND",
         bool(ok) and not any(g["flattened_to_and"] for r in ok for g in r["alternative_groups"]),
         {r["id"]: [g["opener"][:40] for g in r["alternative_groups"] if g["flattened_to_and"]] for r in ok}),
    ]  # fmt: skip
    return {
        "stages": _one(
            f"{TESTS[G8]} public protocols compiled with the production judge", checks, time.perf_counter() - t0
        ),
        REPORT_KEYS[G8]: {"folder": str(folder), "protocols": out},
    }


def compile_protocol(proto: dict[str, Any], work: Path, llm: Any, ruleset: str
                     ) -> tuple[list[dict[str, Any]], list[str]]:  # fmt: skip
    """Compile one protocol's eligibility text with the product's compiler and ``llm`` (the judge's client through
    the gateway). G-8 records the criteria the model extracts: the CQL is not translated (no JVM needed) and no
    patient is compared (the equivalence gate reports "not measured", so it flags nothing)."""
    import shutil

    import tb_contracts as c
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.semantics import compiled
    from criteria_compiler.service import Compiler, CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from doc_parser.parser import parse
    from tb_common.audit import AuditLog
    from tb_common.objstore import FsStore

    def not_measured(criteria: list[Any], sql: str, library: str, index_date: date, seed: str) -> Any:
        ids = [x.id for x in compiled(criteria)]
        return c.EquivalenceReport(
            overall_pct=100.0,
            per_criterion=dict.fromkeys(ids, 100.0),
            failing=[],
            sample_size=1,
            engine="not measured (G-8 records the extracted criteria)",
        )

    shutil.rmtree(work, ignore_errors=True)
    store = FsStore(work / "obj")
    deps = CompilerDeps(store=store, repo=RulesetRepo(work / "repo"), llm=llm, term=Terminology(),
                        settings_thresholds={"equivalence_min_pct": 98.0}, translator=None,
                        audit=AuditLog(work / "audit"), equivalence=not_measured,
                        prompt_environment="PRODUCTION")  # fmt: skip
    data = f"{proto['title']}\n\n{proto['text']}\n".encode()
    store.put("attachments/g8/parsed.json", c.dump_json(parse(data, f"{proto['id']}.txt")).encode())
    res = Compiler(deps).compile(c.CompileRequest(job_id=G8_JOB_ID, ruleset=ruleset,
                                                  parsed_doc_key="attachments/g8/parsed.json",
                                                  requested_by="g8@synthetic.test",
                                                  options={"index_date": "2026-06-30"}))  # fmt: skip
    return [criterion_row(x) for x in res.criteria], list(res.warnings or [])


G8_JOB_ID = "01JG8000000000000000000000"  # one compile per work folder: the job id names nothing else


# ---------------------------------------------------------------- the estimate and the report
def estimate_rows(only: Sequence[str], seqs: int, folder: Path | None = None) -> list[dict[str, Any]]:
    """The estimate's rows of the probes ``only`` names. Every request (a chat call or a ``/tokenize``) is counted at
    the measured rate at one call in flight (``complete_run.SINGLE_CALL_CPS``, 0.403/s): an upper bound. Plus
    :data:`PART_START_SECONDS`; G-8 adds the gateway's read limit for each protocol's extraction call and one call per
    eligibility line (its concept mapping) of the protocols in the folder."""
    from tb_llm.timeouts import UPSTREAM_READ_S

    from tools.complete_run import SINGLE_CALL_CPS as RATE

    # G-5: per language, each excerpt and its rendered judge prompt are counted (two /tokenize requests)
    calls = {G4: 2 * n_decoding_prompts(seqs), G5: 2 * len(G5_LANGS) * N_EXCERPTS, G7: len(clip_cases()) * 2 * 4}
    rows = []
    for part in (G4, G5, G7, G8):
        if part not in only:
            continue
        if part == G8:
            protos = [read_protocol(f) for f in protocol_files(folder or protocols_dir())]
            n = sum(len([x for x in p["text"].splitlines() if x.strip()]) for p in protos)
            seconds = PART_START_SECONDS + len(protos) * UPSTREAM_READ_S + n / RATE
            what = f"{TESTS[G8]} {len(protos)} public protocol(s)" if protos else f"{TESTS[G8]} no fixture: not run"
        else:
            n = calls[part]
            seconds = PART_START_SECONDS + n / RATE
            what = {G4: f"{TESTS[G4]} decoding: guided on/off, {seqs} in flight",
                    G5: f"{TESTS[G5]} token counts, {len(G5_LANGS)} x {N_EXCERPTS} excerpts",
                    G7: f"{TESTS[G7]} clipped against whole note"}[part]  # fmt: skip
        rows.append({"scenario": what, "patients": 0, "model_items": n, "seconds": round(seconds, 1),
                     "tags": [part], "hours": round(seconds / 3600, 2)})  # fmt: skip
    return rows


def report_lines(rep: dict[str, Any]) -> list[str]:
    """The report's section for the probes in the run: one table per test."""
    rows = {r["tag"]: r for r in rep.get("parts") or [] if r.get("tag") in REPORT_KEYS}
    if not rows:
        return []
    out = ["", "## Review tests G-4, G-5, G-7, G-8 (plan v7 §7.1)", ""]
    for tag, r in rows.items():
        b = r.get(REPORT_KEYS[tag])
        out += [f"### {TESTS[tag]} ({tag})", ""]
        if r.get("not_run") or not b:
            out += [f"Not run: {r.get('not_run') or r.get('state') or 'no result'}.", ""]
            if not b or tag == G8:
                continue
        out += [*_section(tag, b), ""]
    return out


def _shown(text: Any) -> str:
    """An answer's opening as one JSON string on one line, for a markdown code span (a backtick as \\u0060)."""
    return json.dumps(text, ensure_ascii=False).replace("`", "\\u0060")


def _section(tag: str, b: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if tag == G4:
        be, eg = b["backend"], b["eager"]
        out += [f"Structured-output backend: **{be.get('backend')}** ({be.get('from')}). Eager start: {eg['result']} "
                f"(record: enforce_eager {eg['enforce_eager']}).", "",
                "| setting | calls | answered | calls/s | p50 s | p95 s | schema failures (of answered) |",
                "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
        for k in ("guided_on", "guided_off"):
            s = b[k]
            out.append(f"| {k.replace('_', ' ')} | {s['calls']} | {s['answered']} | {s['calls_per_second']} | "
                       f"{s['p50_s']} | {s['p95_s']} | {s['schema_failures']} |")  # fmt: skip
        out += ["", f"Profile: {b['profile']} ({b['in_flight']} in flight, {b['prompts']} prompts each way)."]
        for k in ("guided_on", "guided_off"):
            lost = b[k].get("unanswered") or []
            if lost:
                out += ["", f"{k.replace('_', ' ')}: {b[k]['errors']} call(s) not answered; the first {len(lost)} "
                        "(status, why):", ""]  # fmt: skip
                out += [f"- {e.get('status')}: `{_shown(e.get('error'))}`" for e in lost]
        for k in ("guided_on", "guided_off"):
            ex = b[k].get("schema_failure_examples") or []
            if not ex:
                continue
            why = ", ".join(f"{r} {n}" for r, n in (b[k].get("schema_failures_by_finish_reason") or {}).items())
            name = k.replace("_", " ")
            out += ["", f"{name}: answers outside the schema by finish_reason: {why or '?'}; the first {len(ex)} "
                    f"(finish_reason, completion tokens, the first {EXAMPLE_CHARS} characters):", ""]  # fmt: skip
            for e in ex:
                head = _shown(e.get("content_head"))
                out.append(f"- {e.get('finish_reason')}, {e.get('completion_tokens')} tokens: `{head}`")
    elif tag == G5:
        out += ["| language | estimator | n | p50 | p95 | max |", "| --- | --- | --- | --- | --- | --- |"]
        langs = [*[x for x in G5_LANGS if x in b["per_language"]], *[x for x in b["per_language"] if x not in G5_LANGS]]
        for lang in langs:
            per = b["per_language"][lang]
            out += [f"| {lang} | {est} | {s['n']} | {s['p50']} | {s['p95']} | {s['max']} |" for est, s in per.items()]
        out += [f"| {lang} | - | not measured | - | - | - |" for lang in G5_LANGS if lang not in b["per_language"]]
        out += ["", f"Largest ratio {b['max_ratio']} x {b['margin']} against 1 / SAFETY = {b['limit']}: "
                f"**{'fits' if b['fits'] else 'DOES NOT FIT'}**; SAFETY from this measurement: "
                f"{b['safety_from_measurement']}."]  # fmt: skip
    elif tag == G7:
        out += ["| case | clipped | left out | view | judge | verifier | pair | final |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
        for c in b["cases"]:
            for v in ("clipped_view", "whole_view"):
                x = c[v]
                out.append(f"| {c['id']} | {c['clipped']} | {x['left_out']} | {v.split('_')[0]} | {x['judge']} | "
                           f"{x['verifier']} | {x['pair']} | {x['final']} |")  # fmt: skip
        fin = b["final_not_met_from_clipped_note"]
        out += ["", f"Final not met from a clipped note: **{', '.join(fin) if fin else 'none'}**."]
    elif tag == G8:
        out += ["| protocol | criteria | classes | needs_review | time_sensitive | extension, no warning | "
                "groups flattened |", "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
        for p in b.get("protocols") or []:
            if "error" in p:
                out.append(f"| {p['id']} | error: {p['error'][:80]} | | | | | |")
                continue
            flat = sum(1 for g in p["alternative_groups"] if g["flattened_to_and"])
            out.append(
                f"| {p['id']} | {p['criteria']} | {p['class_split']} | {len(p['needs_review'])} | "
                f"{len(p['time_sensitive'])} | {len(p['extension_active_without_warning'])} | {flat} |"
            )
    return out


PARTS: dict[str, Callable[[Any], dict[str, Any]]] = {G4: run_g4, G5: run_g5, G7: run_g7, G8: run_g8}
