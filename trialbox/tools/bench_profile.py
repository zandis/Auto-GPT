"""Profile cost stand-in (owner's approval of 2026-11-09, D-148): what a nightly patient profile would cost on the card.

The profile writer is not built yet. Until it is, the judge model writes a short cited summary per synthetic patient
from that patient's facts (diagnoses, latest labs, medicines, vitals, procedures, reports and the latest notes, each
with a fact id), and this measures what that costs: tokens in and out, seconds per patient (one at a time, and on the
card's batch of 16 sequences), GPU-hours per 1,000 patients, and the extrapolations to 50,000 patients nightly and to
the study patients only.

    python -m tools.complete_run part profile ...        # in a run (the VM: --model pair, the judge on the card)
    python -m tools.bench_profile --synth <hospital> --out result.json            # the stub, anywhere

The call goes through the gateway built as an installed box builds it (``tools.scenarios.gateway_client``: role
``abstract_field``, purpose ``screening``, D3, caller ``orchestrator``), as every model call of the complete run does;
if the gateway refuses, the reason is recorded and the bench goes straight to the judge server (``direct``), so the
cost is still measured. Synthetic patients only (``tools.synth_hospital``); no names, chart numbers or phone numbers
are sent: the patient table's identity columns are left out and the notes' planted PHI spans are masked.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

SYNTH_SITES = "jp-a:JP:400,tw-a:TW:400"
LANG_OF_STYLE = {"JP": ("ja", "Japanese"), "TW": ("zh-TW", "Traditional Chinese (Taiwan)")}
MAX_FACTS = 60
NOTES = 3  # the latest notes per patient, whole
NOTE_CHARS = 800
SEQUENTIAL = 16  # patients timed one at a time (latency) before the batch
PRICE_PER_HOUR = 2.74  # g4-standard-48 spot with the RTX PRO 6000 (tools.complete_run.PRICE_PER_HOUR)
NIGHT_HOURS = 8.0  # the night window (TB-PLAN-03 §8)
S3_SHARE = 92 / 5000  # GZQO patients at the note stage (tools.complete_run.S3_SHARE)
MAX_TOKENS = 1500
JUDGE = "local/gemma-4-26b-a4b-nvfp4"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "cites"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}
PROMPT = "profile_summary_v1"  # libs/tb_llm/prompts/profile_summary_v1.md (the prompt registry, D-201)


# ------------------------------------------------------------------------------------------------ the facts
def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_patients(synth: Path) -> list[dict[str, Any]]:
    """Every patient of every site with an id-numbered fact list (clinical facts only: no name, id or phone)."""
    csv.field_size_limit(10_000_000)
    summary = json.loads((synth / "summary.json").read_text(encoding="utf-8"))
    ref = summary.get("ref_date", "2026-11-01")
    out = []
    for site in summary["sites"]:
        d = synth / site["dir"]
        lang, language = LANG_OF_STYLE.get(site["style"], ("en", "English"))
        states = json.loads((d / "states.json").read_text(encoding="utf-8")) if (d / "states.json").exists() else {}
        phi = _phi_spans(d)
        rows: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
        for table in ("diagnosis", "lab", "medication", "vital", "procedure", "report", "note"):
            for r in _read(d / f"{table}.csv"):
                if table == "note":  # the generator's planted names, dates, numbers: masked as the box's guard would
                    r = {**r, "text": redact(r["text"], phi.get(r["note_no"], []))}
                rows[r["mrn"]][table].append(r)
        for p in _read(d / "patient.csv"):
            facts = _facts(p, rows[p["mrn"]], ref)
            if len(facts) < 3:
                continue
            arche = (states.get(p["mrn"]) or {}).get("archetype", "general")
            out.append({"pid": f"{site['dir']}/{p['mrn']}", "lang": lang, "language": language,
                        "study": arche != "general", "facts": facts})  # fmt: skip
    return out


def _phi_spans(site: Path) -> dict[str, list[dict[str, Any]]]:
    gold = site / "gold" / "notes.jsonl"
    if not gold.exists():
        return {}
    out = {}
    for line in gold.read_text(encoding="utf-8").splitlines():
        g = json.loads(line)
        out[g["note_no"]] = g.get("phi") or []
    return out


def redact(text: str, spans: list[dict[str, Any]]) -> str:
    """Each planted PHI span (``gold/notes.jsonl``: start, end, type) replaced by ``[type]``, last first."""
    for sp in sorted(spans, key=lambda x: x["start"], reverse=True):
        text = text[: sp["start"]] + f"[{sp['type']}]" + text[sp["end"] :]
    return text


def _facts(p: dict[str, str], r: dict[str, list[dict[str, str]]], ref: str) -> list[dict[str, str]]:
    facts: list[str] = []
    age = int(ref[:4]) - int(p["birth_date"][:4]) - (ref[5:] < p["birth_date"][5:])
    facts.append(f"sex {p['sex']}, age {age}" + (f", died {p['death_date']}" if p.get("death_date") else ""))
    for x in sorted(r["diagnosis"], key=lambda x: x["diag_date"], reverse=True):
        facts.append(f"diagnosis {x['icd10']} on {x['diag_date']} (status {x['status']})")
    latest: dict[str, dict[str, str]] = {}
    for x in r["lab"]:
        if x["item_name"] not in latest or x["sample_datetime"] > latest[x["item_name"]]["sample_datetime"]:
            latest[x["item_name"]] = x
    for x in latest.values():
        facts.append(f"lab {x['item_name']} {x['result_value']} {x['unit']} on {x['sample_datetime'][:10]}")
    meds: dict[str, dict[str, str]] = {}
    for x in r["medication"]:
        if x["drug_name"] not in meds or x["start_date"] > meds[x["drug_name"]]["start_date"]:
            meds[x["drug_name"]] = x
    for x in meds.values():
        facts.append(f"medicine {x['drug_name']} {x['daily_dose']} {x['dose_unit']}/day from {x['start_date']} "
                     f"({x['status']})")  # fmt: skip
    for k in ("height_cm", "weight_kg", "sbp", "dbp"):
        v = [x for x in r["vital"] if x.get(k)]
        if v:
            x = max(v, key=lambda x: x["measure_datetime"])
            facts.append(f"vital {k} {x[k]} on {x['measure_datetime'][:10]}")
    facts += [f"procedure {x['proc_name']} on {x['proc_date']}" for x in r["procedure"]]
    facts += [f"report {x['exam_name']} on {x['exam_date']}: {x['conclusion']}" for x in r["report"]]
    notes = sorted(r["note"], key=lambda x: x["note_datetime"], reverse=True)[:NOTES]
    facts += [f"note {x['note_type']} on {x['note_datetime'][:10]}: {x['text'][:NOTE_CHARS]}" for x in notes]
    return [{"id": f"F{i + 1}", "text": t} for i, t in enumerate(facts[:MAX_FACTS])]


def messages(p: dict[str, Any]) -> list[dict[str, str]]:
    """The registered ``profile_summary`` prompt rendered for one patient (the gateway checks the text against it)."""
    from tb_common.llm import load_prompt, render

    facts = "\n".join(f"{f['id']}: {f['text']}" for f in p["facts"])
    return render(load_prompt(PROMPT), {"language": p["language"], "facts": facts})


def check_citations(p: dict[str, Any], data: dict[str, Any]) -> tuple[int, int]:
    """(sentences, sentences whose citations are non-empty and all this patient's fact ids)."""
    ids = {f["id"] for f in p["facts"]}
    sents = data.get("sentences") or []
    ok = sum(1 for s in sents if s.get("cites") and set(s["cites"]) <= ids and str(s.get("text", "")).strip())
    return len(sents), ok


# ------------------------------------------------------------------------------------------------ the callers
def body(msgs: list[dict[str, str]]) -> dict[str, Any]:
    return {"messages": msgs, "temperature": 0.0, "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_schema", "json_schema": {"name": "profile_summary", "schema": SCHEMA,
                                                                       "strict": True}}}  # fmt: skip


def _prompt_sha() -> str:
    from tb_common.llm import load_prompt

    return load_prompt(PROMPT).sha256


def stub_call(msgs: list[dict[str, str]]) -> dict[str, Any]:
    """The laptop's stand-in for the judge: one sentence per fact, citing it (tokens counted as characters / 4)."""
    ids = re.findall(r"^(F\d+): (.*)$", msgs[-1]["content"], re.M)
    sents = [{"text": text[:60], "cites": [fid]} for fid, text in ids[:6]]
    content = json.dumps({"sentences": sents}, ensure_ascii=False)
    n_in = sum(len(m["content"]) for m in msgs) // 4
    return {"id": "stub", "object": "chat.completion", "model": "stub",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": n_in, "completion_tokens": len(content) // 4}}  # fmt: skip


class Caller:
    """One chat call: the installed box's gateway (one in-process gateway per thread), else direct to the judge."""

    def __init__(self, gateway: Any = None, direct: Any = None, stub: bool = False) -> None:
        self.make_gateway, self.direct, self.stub = gateway, direct, stub
        self.path = "stub" if stub else ("gateway (installed box)" if gateway else "direct")
        self.refused = ""
        self.local = threading.local()
        self.lock = threading.Lock()

    def __call__(self, msgs: list[dict[str, str]]) -> dict[str, Any]:
        if self.stub:
            return stub_call(msgs)
        if self.make_gateway is not None and not self.refused:
            from tb_llm import GatewayError
            from tb_llm.client import CallLabels

            gw = getattr(self.local, "gw", None)
            if gw is None:
                gw = self.local.gw = self.make_gateway()
            labels = CallLabels(data_class="D3", purpose="screening", study_id="none",
                                context_of_use="patient_profile_summary", role="abstract_field",
                                prompt="profile_summary@1", prompt_sha=_prompt_sha())  # fmt: skip
            try:
                payload: dict[str, Any] = gw.complete(body(msgs), labels)
                return payload
            except (GatewayError, ValueError) as exc:
                with self.lock:
                    if not self.refused:
                        self.refused = str(exc)[:300]
                        self.path = f"direct (the gateway refused: {self.refused[:120]})"
        payload = self.direct(msgs)
        return payload


def make_call(a: Any, work: Path) -> Caller:
    """The bench's caller for a ``tools.complete_run`` part: the stub, or with ``--model pair`` the judge through the
    installed box's gateway (``--direct``: straight to the judge server)."""
    if getattr(a, "model", "stub") != "pair":
        return Caller(stub=True)
    import httpx

    key = os.environ["TB_GPU_KEY"]
    http = httpx.Client(timeout=600.0, headers={"Authorization": f"Bearer {key}"})

    def direct(msgs: list[dict[str, str]]) -> dict[str, Any]:
        r = http.post(f"{a.judge_url.rstrip('/')}/chat/completions", json={"model": JUDGE, **body(msgs)})
        r.raise_for_status()
        out: dict[str, Any] = r.json()
        return out

    if getattr(a, "direct", False):
        return Caller(direct=direct)
    from tools import scenarios

    os.environ.pop("TB_DATA_CLASS", None)  # as install leaves it
    count = iter(range(10_000))

    def gateway() -> Any:
        env = scenarios.installed_env(work / f"gw-audit-{next(count)}", a.judge_url, a.verifier_url)
        return scenarios.gateway_client(env)

    return Caller(gateway=gateway, direct=direct)


# ------------------------------------------------------------------------------------------------ the bench
def _one(call: Caller, p: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        payload = call(messages(p))
        content = payload["choices"][0]["message"].get("content") or ""
        m = re.search(r"\{.*\}", content, re.S)
        data = json.loads(m.group(0) if m else content)
        n, ok = check_citations(p, data)
        usage = payload.get("usage") or {}
        return {"pid": p["pid"], "lang": p["lang"], "ok": True, "seconds": time.perf_counter() - t0,
                "tokens_in": int(usage.get("prompt_tokens", 0)), "tokens_out": int(usage.get("completion_tokens", 0)),
                "facts": len(p["facts"]), "sentences": n, "cited_ok": ok,
                "truncated": payload["choices"][0].get("finish_reason") == "length"}  # fmt: skip
    except Exception as exc:  # a failed patient is counted, not a lost bench
        return {"pid": p["pid"], "lang": p["lang"], "ok": False, "seconds": time.perf_counter() - t0,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}  # fmt: skip


def _stats(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    s = sorted(xs)
    return {"mean": round(statistics.fmean(s), 2), "p50": round(s[len(s) // 2], 2),
            "p95": round(s[min(len(s) - 1, int(len(s) * 0.95))], 2), "max": round(s[-1], 2)}  # fmt: skip


def _sample(pats: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """``n`` patients, both languages alike, study patients and the others in the hospital's own proportion."""
    by = [[p for p in pats if p["lang"] == lg] for lg in sorted({p["lang"] for p in pats})]
    out: list[dict[str, Any]] = []
    i = 0
    while len(out) < n and any(i < len(b) for b in by):
        out += [b[i] for b in by if i < len(b)]
        i += 1
    return out[:n]


def run(synth: Path, call: Caller, patients: int = 400, workers: int = 16, nightly: int = 50000) -> dict[str, Any]:
    pats = load_patients(synth)
    sample = _sample(pats, patients)
    seq = sample[: min(SEQUENTIAL, len(sample))]
    rest = sample[len(seq) :]
    seq_rows = [_one(call, p) for p in seq]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        batch_rows = list(ex.map(lambda p: _one(call, p), rest))
    wall = time.perf_counter() - t0
    rows = seq_rows + batch_rows
    good = [r for r in rows if r["ok"]]
    sents = sum(r["sentences"] for r in good)
    eff = wall / len(rest) if rest else statistics.fmean([r["seconds"] for r in seq_rows] or [0.0])
    seq_s = statistics.fmean([r["seconds"] for r in seq_rows if r["ok"]] or [0.0])
    study_share = sum(1 for p in pats if p["study"]) / max(1, len(pats))

    def cost(n: float, s: float) -> dict[str, Any]:
        h = n * s / 3600
        return {"patients": round(n), "gpu_hours": round(h, 2), "usd": round(h * PRICE_PER_HOUR, 2),
                "fits_night": h <= NIGHT_HOURS}  # fmt: skip

    measured = {
        "patients": len(rows),
        "answered": len(good),
        "by_lang": {lg: sum(1 for r in good if r["lang"] == lg) for lg in sorted({r["lang"] for r in rows})},
        "facts": _stats([r["facts"] for r in good]),
        "tokens_in": _stats([r["tokens_in"] for r in good]),
        "tokens_out": _stats([r["tokens_out"] for r in good]),
        "sentences": _stats([r["sentences"] for r in good]),
        "citations_valid": round(sum(r["cited_ok"] for r in good) / sents, 4) if sents else 0.0,
        "truncated": sum(1 for r in good if r.get("truncated")),
        "seconds_sequential": _stats([r["seconds"] for r in seq_rows if r["ok"]]),
        "batch": {
            "patients": len(rest),
            "workers": workers,
            "wall_seconds": round(wall, 1),
            "seconds_per_patient": round(eff, 3),
            "latency": _stats([r["seconds"] for r in batch_rows if r["ok"]]),
        },
        "gpu_hours_per_1000": {"batched": round(1000 * eff / 3600, 3), "one_at_a_time": round(1000 * seq_s / 3600, 3)},
    }
    study_n = nightly * study_share
    return {
        "path": call.path,
        "gateway_refused": call.refused,
        "source": "tools.synth_hospital (fictional patients only)",
        "hospital_patients": len(pats),
        "measured": measured,
        "extrapolation": {
            "basis": f"batched {eff:.3f} s per patient on one RTX PRO 6000 (judge resident with the verifier), "
            f"US${PRICE_PER_HOUR}/h, night window {NIGHT_HOURS} h",
            "nightly_all": cost(nightly, eff),
            "nightly_study_archetypes": cost(study_n, eff)
            | {
                "share": round(study_share, 3),
                "note": "the generator's study archetypes (a test hospital: far more than a real one)",
            },
            "nightly_note_stage": cost(nightly * S3_SHARE, eff)
            | {"share": round(S3_SHARE, 4), "note": "patients reaching the note stage S3 (GZQO, 92 of 5,000; D-139)"},
            "per_1000_study_patients": cost(1000, eff),
        },
        "errors": [r["error"] for r in rows if not r["ok"]][:10],
        "rows": rows,
    }


def summary(res: dict[str, Any]) -> dict[str, Any]:
    return {k: res[k] for k in ("path", "gateway_refused", "measured", "extrapolation", "errors")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--synth", type=Path, required=True, help="a synthetic hospital (tools.synth_hospital)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--patients", type=int, default=400)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--nightly", type=int, default=50000)
    a = ap.parse_args(argv)
    res = run(a.synth, Caller(stub=True), a.patients, a.workers, a.nightly)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary(res), ensure_ascii=False, indent=1))
    return 0 if res["measured"]["answered"] == res["measured"]["patients"] else 1


if __name__ == "__main__":
    sys.exit(main())
