"""The verifier's stored calls sent again to a live verifier server, with and without a server flag (lane H, card
H-47's optional stage; H-49's option 1, ``--structured-outputs-config`` with ``disable_any_whitespace``). A
measurement, never a serving change.

    python3 -m tools.verifier_replay plan RUN                                   # free: the calls it would send
    python3 -m tools.verifier_replay run RUN --url http://<verifier>:8000/v1 --label off --out DIR
    python3 -m tools.verifier_replay compare DIR/off DIR/on --json DIR/compare.json

``RUN`` is a stored set as :mod:`tools.public_accuracy.replay` reads it (a driver's ``.tgz``, unpacked by its safe
extractor into a new empty folder; or an extracted folder); ``--set`` names the set (default ``tcga``). The calls are
its ``work/raw-traces.json`` records of the verifier (alias ``v-verifier``) on prompt ``judge@5`` that got an answer:
each one's stored messages are sent once more, straight to the server's ``/chat/completions`` (not through the
gateway), with the body the box's client builds (``libs/tb_common/llm.py``: the served model, the prompt's temperature
and ``max_tokens``, ``response_format`` ``json_schema`` with the registered schema, strict), one call at a time, so the
seconds are a call's own. No retry with more room: the finish reason is recorded instead (the stored traces lack it).

``run`` writes ``DIR/<label>/`` as a stored set (``built/gold/ids.json`` naming the set ``<set>-<label>``,
``work/raw-traces.json`` in the stored form with the new answers), so ``python -m tools.public_accuracy.waste
DIR/<label>`` counts its flagged calls as it counts a launch's; and ``work/replay.json`` with each call's seconds,
finish reason and completion tokens. ``compare`` gives, per label, the flagged calls (``waste``'s rules), seconds per
call (mean and median), and the verdicts that differ between the two on the calls neither run flagged. The key comes
from ``TB_GPU_KEY`` only and is never written. Synthetic or public data only: the stored sets are public (TCGA).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools.public_accuracy import waste  # noqa: E402
from tools.public_accuracy.replay import Refused, collect  # noqa: E402

ALIAS = "v-verifier"
PROMPT = "judge@5"
SERVED = "local/qwen3.5-9b-awq"  # tools/dgpu48.py PIN_BUILD["verifier"]; deploy/docker-compose.dgpu48.yml
FLAG = '--structured-outputs-config={"backend":"xgrammar","disable_any_whitespace":true}'  # H-49, option 1
Post = Callable[[str, dict[str, Any], str, float], dict[str, Any]]


def temperature_of(prompt: str) -> float:
    from tb_llm.prompt_registry import default_registry

    pid, ver = prompt.split("@", 1)
    text = default_registry().get(pid, int(ver), environment="sandbox").text
    return next((float(ln.split(":", 1)[1]) for ln in text.splitlines() if ln.startswith("temperature:")), 0.0)


def load_calls(run: Path, scratch: Path, name: str = "tcga", prompt: str = PROMPT) -> list[dict[str, Any]]:
    found = collect([run], scratch)
    if name not in found:
        raise Refused(f"{run}: no set {name!r} (sets: {', '.join(sorted(found)) or 'none'})")
    raw = json.loads((found[name] / "work" / "raw-traces.json").read_text(encoding="utf-8"))
    rows = raw.get("traces") if isinstance(raw, dict) else raw
    out = []
    for t in rows or []:
        a = t.get("attributes") or {}
        if t.get("span") != "chat" or a.get("tb.model_alias") != ALIAS or a.get("tb.prompt") != prompt:
            continue
        if not isinstance(t.get("output"), str) or not isinstance(t.get("prompt"), list):
            continue
        out.append(t)
    return out


def body(trace: dict[str, Any], schema: dict[str, Any], cap: int, temperature: float) -> dict[str, Any]:
    pid = PROMPT.split("@", 1)[0]
    msgs = [{"role": m["role"], "content": m["content"]} for m in trace["prompt"] if isinstance(m, dict)]
    return {
        "model": SERVED,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": cap,
        "response_format": {"type": "json_schema", "json_schema": {"name": pid, "schema": schema, "strict": True}},
    }


def http_post(url: str, payload: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        got: dict[str, Any] = json.loads(r.read().decode("utf-8"))
        return got


def replay(
    calls: list[dict[str, Any]],
    url: str,
    key: str,
    out: Path,
    label: str,
    name: str = "tcga",
    post: Post = http_post,
    timeout: float = 900.0,
    say: Callable[[str], None] = print,
) -> dict[str, Any]:
    schema, cap = waste.schema_of(PROMPT)
    if schema is None or cap is None:
        raise Refused(f"{PROMPT}: no registered schema or max_tokens")
    temp = temperature_of(PROMPT)
    traces, rows = [], []
    for i, t in enumerate(calls):
        t0 = time.monotonic()
        try:
            res = post(url, body(t, schema, cap, temp), key, timeout)
            choice = (res.get("choices") or [{}])[0]
            text = str((choice.get("message") or {}).get("content") or "")
            row = {"i": i, "finish_reason": choice.get("finish_reason"),
                   "completion_tokens": (res.get("usage") or {}).get("completion_tokens")}  # fmt: skip
            traces.append({"span": "chat", "attributes": dict(t.get("attributes") or {}), "prompt": t["prompt"],
                           "output": text})  # fmt: skip
        except Exception as exc:  # a failed call is a row, not the end of the run
            row = {"i": i, "error": type(exc).__name__}
            traces.append({"span": "refusal", "attributes": dict(t.get("attributes") or {}), "prompt": t["prompt"],
                           "output": None})  # fmt: skip
        row["seconds"] = round(time.monotonic() - t0, 3)
        rows.append(row)
        if (i + 1) % 25 == 0:
            say(f"  {label}: {i + 1} of {len(calls)} calls")
    d = out / label
    (d / "built" / "gold").mkdir(parents=True, exist_ok=True)
    (d / "work").mkdir(parents=True, exist_ok=True)
    (d / "built" / "gold" / "ids.json").write_text(json.dumps({"set": f"{name}-{label}"}) + "\n", encoding="utf-8")
    (d / "work" / "raw-traces.json").write_text(json.dumps({"traces": traces}) + "\n", encoding="utf-8")
    rep = {"schema": "tb-verifier-replay/1", "label": label, "set": name, "prompt": PROMPT, "served": SERVED,
           "calls": len(calls), "errors": sum("error" in r for r in rows), "rows": rows,
           "note": "a measurement, not a serving change; under the ballast: never a tier record"}  # fmt: skip
    (d / "work" / "replay.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    return rep


def _verdict(text: Any) -> str | None:
    try:
        v = json.loads(text).get("verdict") if isinstance(text, str) else None
    except (ValueError, AttributeError):
        return None
    return v if isinstance(v, str) else None


def _side(d: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    traces = json.loads((d / "work" / "raw-traces.json").read_text(encoding="utf-8"))["traces"]
    return traces, json.loads((d / "work" / "replay.json").read_text(encoding="utf-8"))


def _flagged(t: dict[str, Any]) -> bool:
    r = waste.classify(t)
    return bool(r.get("cut") or waste.is_loop(r.get("repeat", (0, 0))) or r.get("outside_schema"))


def compare(a: Path, b: Path) -> dict[str, Any]:
    (ta, ra), (tb, rb) = _side(a), _side(b)
    if len(ta) != len(tb):
        raise Refused(f"{a} has {len(ta)} calls, {b} {len(tb)}: not the same call set")
    out: dict[str, Any] = {"schema": "tb-verifier-replay-compare/1", "calls": len(ta), "labels": {}}
    for label, ts, rep in ((ra["label"], ta, ra), (rb["label"], tb, rb)):
        secs = [r["seconds"] for r in rep["rows"] if "error" not in r]
        counts = waste.count(ts).get(ALIAS, {})
        out["labels"][label] = {
            "flagged": counts.get("flagged", 0), "cut": counts.get("cut", 0), "loop": counts.get("loop", 0),
            "outside_schema": counts.get("outside_schema", 0), "errors": rep["errors"],
            "finish_length": sum(r.get("finish_reason") == "length" for r in rep["rows"]),
            "seconds_mean": round(statistics.fmean(secs), 3) if secs else None,
            "seconds_median": round(statistics.median(secs), 3) if secs else None,
            "seconds_total": round(sum(secs), 1),
        }  # fmt: skip
    both = [i for i in range(len(ta)) if ta[i]["span"] == tb[i]["span"] == "chat"
            and not _flagged(ta[i]) and not _flagged(tb[i])]  # fmt: skip
    diff = [i for i in both if _verdict(ta[i]["output"]) != _verdict(tb[i]["output"])]
    out["unflagged_in_both"] = len(both)
    out["verdicts_differ"] = len(diff)
    out["differ_at"] = diff
    out["note"] = "a measurement, not a serving change; under the ballast: never a tier record"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m tools.verifier_replay", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("run_path", type=Path, metavar="RUN")
        p.add_argument("--set", default="tcga")
        if name == "run":
            p.add_argument("--url", required=True, help="the verifier server, http://<address>:8000/v1")
            p.add_argument("--label", required=True, help="off or on (the server flag)")
            p.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    c.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "compare":
            res = compare(a.a, a.b)
            if a.json:
                a.json.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({k: v for k, v in res.items() if k != "differ_at"}, indent=1, sort_keys=True))
            return 0
        with tempfile.TemporaryDirectory(prefix="tb-vreplay-") as t:
            calls = load_calls(a.run_path, Path(t), a.set)
            flagged = sum(_flagged(x) for x in calls)
            if a.cmd == "plan":
                print(f"set {a.set}: {len(calls)} verifier calls on {PROMPT} to send, {flagged} flagged as stored")
                return 0
            key = os.environ.get("TB_GPU_KEY", "")
            rep = replay(calls, a.url, key, a.out, a.label, a.set)
        print(f"{a.label}: {rep['calls']} calls, {rep['errors']} failed; {a.out / a.label}")
        return 0
    except (Refused, OSError, ValueError, KeyError) as exc:
        print(f"verifier_replay: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
