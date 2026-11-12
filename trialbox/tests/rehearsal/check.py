"""The rehearsal's pass criteria (D-150; review of 2026-11-09 §5.2), one case at a time, from its evidence folder:

    python tests/rehearsal/check.py run-a <evidence> --only TAG,TAG --head <sha>
    python tests/rehearsal/check.py run-b <evidence> --only ... --head <sha> --previous <run id of run-a>
    python tests/rehearsal/check.py bucket <evidence> --only ... --head <sha>
    python tests/rehearsal/check.py served|no-upload|hang|busy <evidence>
    python tests/rehearsal/check.py preempt <evidence> --only TAG,TAG

The evidence (rehearse.sh ``end_case``): ``console.log`` (the VM's serial console of this case), ``POWEROFF`` (each
power-off and why), ``standin-judge.log`` / ``standin-verifier.log`` (one line per call: status, path, model),
``vm-results.tgz`` (the VM's ``results.tgz`` as it is on its disk), ``out/`` (the driver's run folder: plan, shard-1
with the collected results, the merged parts and the report), ``driver.log``; ``metadata-keys`` (the names of the VM's
metadata), ``secrets-left`` (the door versions still in "Secret Manager"), ``gcloud.log`` and ``vm-gcloud.log`` (the
driver's and the VM's cloud calls; T-119).

Model quality is not rehearsed: the stand-ins answer with the repository's deterministic stub, so the checks that
judge the pair's answers (:data:`MODEL_QUALITY`) may fail; every other check must pass. Plumbing, names, keys, setup,
state and timing are what the rehearsal holds, the layer the cloud run's failures were in.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

# (part, check) of the checks about the models' answers, which the deterministic stub cannot pass: allowed to fail
# here, nowhere else. The pair canary (54 cases with known answers) fails on the stub, so the checks that need a passed
# canary fail with it; TREC's criteria go straight to the model with a prompt the stub has no handler for (the
# stand-in answers "OK", which is no verdict). A failed check outside this list fails the rehearsal.
MODEL_QUALITY = [
    (r".", r"canary"),
    (r"^(hospital|public)-", r"only when (both|two) models agree"),
    (r"^scenario-", r"^the pair judged: judge and verifier both named"),
    (r"^scenario-public-trec$", r"^every criterion answered$"),
]


class Result:
    def __init__(self, case: str) -> None:
        self.case, self.bad, self.n = case, 0, 0

    def ok(self, what: str, cond: bool, detail: Any = "") -> None:
        self.n += 1
        if not cond:
            self.bad += 1
        print(f"  {'pass' if cond else 'FAIL'}  {what}" + (f"  [{str(detail)[:300]}]" if detail != "" else ""))

    def done(self) -> int:
        print(f"{self.case}: {'PASSED' if not self.bad else 'FAILED'} ({self.n - self.bad}/{self.n})")
        return 1 if self.bad else 0


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def members(tgz: Path) -> dict[str, bytes]:
    if not tgz.exists():
        return {}
    out: dict[str, bytes] = {}
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            if m.isfile():
                f = t.extractfile(m)
                out[m.name.removeprefix("./")] = f.read() if f else b""
    return out


def calls(log: str) -> dict[str, int]:
    """Stand-in calls by status, the pre-flight's no-key 401 on /v1/models apart."""
    n = {"200": 0, "401": 0, "401-models": 0, "404": 0, "other": 0}
    for m in re.finditer(r"^\[\w+\] (\d{3}) (\S+)", log, re.M):
        st, path = m.group(1), m.group(2)
        key = "401-models" if st == "401" and path == "/v1/models" else st if st in n else "other"
        n[key] += 1
    return n


def poweroffs(e: Path, name: str = "POWEROFF") -> list[str]:
    return [ln for ln in text(e / name).splitlines() if ln.strip()]


def check_servers(r: Result, e: Path, chats: bool = True) -> None:
    for s in ("judge", "verifier"):
        n = calls(text(e / f"standin-{s}.log"))
        r.ok(f"{s} stand-in: no 404 (every call asked for the served name)", n["404"] == 0, n)
        r.ok(f"{s} stand-in: no call without the key but the pre-flight's own refusal check", n["401"] == 0, n)
        r.ok(f"{s} stand-in: the pre-flight's no-key call was refused (401) once", n["401-models"] == 1, n)
        if chats:
            r.ok(f"{s} stand-in: answered calls", n["200"] > 0, n)


def check_door(r: Result, e: Path, collected: bool = True) -> None:
    """T-119 (CR-048): the key never in the metadata, the door on TLS 443, its secret version gone once collected."""
    keys = text(e / "metadata-keys").split()
    r.ok("metadata: no tb-key (the door comes from Secret Manager)", "tb-key" not in keys, keys)
    r.ok("metadata: the door's secret and certificate named", {"tb-door-secret", "tb-door-version", "tb-door-cert"}
         <= set(keys), keys)  # fmt: skip
    con = text(e / "console.log")
    r.ok("console: no TB-NO-KEY", "TB-NO-KEY" not in con)
    r.ok("console: the door is up on 443 (TLS), no port 80", "behind nginx :443 (TLS" in con)
    if collected:
        left = text(e / "secrets-left").split()
        r.ok("Secret Manager: the door's version was destroyed once collected", not left, left)


def check_record(r: Result, res: dict[str, bytes]) -> None:
    """T-119: the serving record is captured on the VM (``docker inspect`` of the two servers, the weight hashes)."""
    raw = res.get("serving_config.rtxpro6000.live.json")
    r.ok("results.tgz has the serving record", raw is not None, sorted(res)[:8])
    rec = json.loads(raw) if raw else {}
    srv = {s.get("role"): s for s in rec.get("servers") or []}
    for role, served in (("judge", "local/gemma-4-26b-a4b-nvfp4"), ("verifier", "local/qwen3.5-9b-awq")):
        s = srv.get(role) or {}
        r.ok(
            f"serving record: {role} serves {served}", s.get("served_model_name") == served, s.get("served_model_name")
        )
        r.ok(f"serving record: {role} has its weight files' sha256", bool(s.get("model_files_sha256")))
        r.ok(
            f"serving record: {role} names the vLLM image and version",
            bool(s.get("image")) and bool(s.get("vllm_version")),
        )
    r.ok("serving record: no API key in it", "api-key" not in json.dumps(rec), "")


def check_measured(r: Result, rep: dict[str, Any], res: dict[str, bytes], vm: str) -> None:
    """Review test G-3's plumbing (2026-11-12): the calls in flight reach the parts (not given: the serving record's
    max_num_seqs, 16) and a hospital part is measured: both servers' ``/metrics``, the card every 10 s, its calls."""
    hosp = next((p for p in rep.get("parts") or [] if p["tag"].startswith("hospital-") and not p.get("state")), None)
    if hosp is None:
        return
    tag = hosp["tag"]
    r.ok("vm.log: the run says its model calls in flight (the record's max_num_seqs)",
         "model calls in flight (TB_SCREEN_LLM_CONCURRENCY): 16" in vm)  # fmt: skip
    r.ok(f"{tag}: ran with 16 calls in flight", hosp.get("llm_concurrency") == 16, hosp.get("llm_concurrency"))
    m = hosp.get("metrics") or {}
    scraped = {s: bool(((m.get("servers") or {}).get(s) or {}).get("scraped")) for s in ("judge", "verifier")}
    r.ok(f"{tag}: both servers' /metrics scraped before and after", all(scraped.values()), scraped)
    r.ok(f"{tag}: the card sampled (gpu.csv)", int((m.get("gpu") or {}).get("samples") or 0) >= 2, m.get("gpu"))
    r.ok(f"results.tgz has parts/{tag}/gpu.csv and the servers' metrics",
         {f"parts/{tag}/gpu.csv", f"parts/{tag}/vllm-judge-after.prom"} <= set(res),
         sorted(k for k in res if k.startswith(f"parts/{tag}/")))  # fmt: skip
    t = hosp.get("throughput") or {}
    r.ok(f"{tag}: calls per second from the gateway's audit", int(t.get("calls") or 0) + int(t.get("cached") or 0) > 0,
         {k: t.get(k) for k in ("calls", "cached", "calls_per_second", "p95_s")})  # fmt: skip
    r.ok(f"{tag}: the candidate list has a hash", bool((hosp.get("candidates") or {}).get("sha256")))


def report_of(e: Path) -> dict[str, Any]:
    p = e / "out" / "report" / "report.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def failing(rep: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(r["tag"], st["name"], str(c[0])) for r in rep.get("parts") or [] for st in r["stages"] for c in st["checks"]
            if not c[1]]  # fmt: skip


def run_case(a: argparse.Namespace) -> int:
    r = Result(a.case)
    e = a.evidence
    con = text(e / "console.log")
    only = [t for t in a.only.split(",") if t]
    for marker in ("TB-DOOR-UP", "TB-PREFLIGHT ok", "TB-SERVING ok: judge", "TB-SERVING ok: verifier",
                   "PRO6000-RUN-READY", "TB-PHASE run", "COMPLETE-RUN-DONE"):  # fmt: skip
        r.ok(f"console: {marker}", marker in con)
    for marker in ("TB-SETUP-FAILED", "TB-SERVING-FAILED", "TB-PREFLIGHT-FAILED", "TB-NO-CODE", "TB-UPLOAD-REJECTED"):
        r.ok(f"console: no {marker}", marker not in con, [ln for ln in con.splitlines() if marker in ln][:2])
    check_servers(r, e)
    res = members(e / "out" / "shard-1" / "results.tgz")
    vm = res.get("vm.log", b"").decode("utf-8", "replace")
    r.ok(
        "the driver collected results.tgz with vm.log and parts/", bool(vm) and any(k.startswith("parts/") for k in res)
    )
    r.ok("vm.log: the run ended (TB-RUN-EXIT)", "TB-RUN-EXIT" in vm)
    check_door(r, e)
    check_record(r, res)
    if a.case == "bucket":
        gl, vl = text(e / "gcloud.log"), text(e / "vm-gcloud.log")
        r.ok(
            "bucket: the driver put the code in the bucket", re.search(r"storage cp \S*src\.tgz gs://", gl) is not None
        )
        r.ok(
            "bucket: the VM took the code from the bucket", "storage cp" in vl and "TB-BUCKET: no" not in con, vl[-300:]
        )
        r.ok("bucket: the driver took the results from the bucket",
             re.search(r"storage cp gs://\S*results\.tgz", gl) is not None)  # fmt: skip
    r.ok("vm.log: nothing kept from another run (--resume)", "kept (--resume)" not in vm and "another run" not in vm,
         [ln for ln in vm.splitlines() if "kept" in ln or "another run" in ln][:3])  # fmt: skip
    r.ok("vm.log: this boot's log only (one '== boot' line)", vm.count("== boot ") == 1, vm.count("== boot "))
    if a.previous:
        r.ok("vm.log and console: nothing of the previous run", a.previous not in vm and a.previous not in con)
    for tag, data in (("hospital-", "cql"), ("public-", "medtxt"), ("scenario-public-medtxt", "medtxt"),
                      ("scenario-public-trec", "trec")):  # fmt: skip
        if any(t.startswith(tag) for t in only):
            r.ok(f"vm.log: the data '{data}' was fetched (TB-DATA {data}: ready)", f"TB-DATA {data}: ready" in vm,
                 [ln for ln in vm.splitlines() if ln.startswith("TB-DATA")])  # fmt: skip
    rep = report_of(e)
    r.ok("the report was written", bool(rep))
    tags = [p["tag"] for p in rep.get("parts") or []]
    want = {t for t in only} | ({"prepare"} if any(t.startswith("hospital-") for t in only) else set())
    r.ok("the report has every planned part", want <= set(tags), sorted(want - set(tags)))
    r.ok("no part crashed, did not report or lacked its data", not rep.get("not_run"), rep.get("not_run"))
    r.ok("the report's HEAD is the launched commit", (rep.get("git") or {}).get("head") == a.head,
         (rep.get("git") or {}).get("head"))  # fmt: skip
    r.ok("the report's host is the VM's (from the parts)", (rep.get("host") or {}).get("node") not in ("", None))
    r.ok(
        "the report says the weight pins are synthetic",
        "synthetic weight pins" in str(rep.get("path")),
        rep.get("path"),
    )
    check_measured(r, rep, res, vm)
    bad = failing(rep)
    other = [b for b in bad if not any(re.search(t, b[0]) and re.search(c, b[2]) for t, c in MODEL_QUALITY)]
    r.ok("every failed check is about model quality (the stub's answers)", not other, other[:8])
    print(
        f"  info  model-quality checks failing on the stub: {len(bad) - len(other)}: "
        f"{sorted({b[2][:60] for b in bad if b not in other})[:8]}"
    )
    offs = poweroffs(e)
    r.ok("the VM powered off once the driver collected", bool(offs) and "results collected" in offs[-1], offs[-1:])
    return r.done()


def served_case(a: argparse.Namespace) -> int:
    r = Result(a.case)
    e = a.evidence
    con = text(e / "console.log")
    r.ok("console: TB-SERVING-FAILED names the wrong served name", re.search(r"TB-SERVING-FAILED: judge serves", con)
         is not None, [ln for ln in con.splitlines() if "TB-SERVING" in ln][:2])  # fmt: skip
    r.ok("console: no PRO6000-RUN-READY", "PRO6000-RUN-READY" not in con)
    r.ok("console: no part ran (no TB-PHASE run)", "TB-PHASE run" not in con)
    res = members(e / "out" / "shard-1" / "results.tgz")
    vm = res.get("vm.log", b"").decode("utf-8", "replace")
    r.ok("the driver collected results.tgz saying why", "TB-SERVING-FAILED" in vm, sorted(res)[:6])
    r.ok("results.tgz has the servers' logs", "serving-logs/judge.log" in res, sorted(res)[:6])
    r.ok("results.tgz has no parts", not any(k.startswith("parts/") for k in res))
    check_door(r, e)
    offs = poweroffs(e)
    r.ok("the VM powered off once the driver collected", bool(offs) and "results collected" in offs[-1], offs[-1:])
    return r.done()


def no_upload_case(a: argparse.Namespace) -> int:
    r = Result(a.case)
    e = a.evidence
    con = text(e / "console.log")
    r.ok("console: PRO6000-RUN-READY (the servers were fine)", "PRO6000-RUN-READY" in con)
    r.ok("console: TB-NO-CODE after the wait", "TB-NO-CODE" in con)
    res = members(e / "vm-results.tgz")
    vm = res.get("vm.log", b"").decode("utf-8", "replace")
    r.ok("results.tgz on the disk says TB-NO-CODE", "TB-NO-CODE" in vm, sorted(res))
    r.ok("results.tgz: this boot's log only, no earlier run", vm.count("== boot ") == 1 and "rehearsal-run" not in vm)
    check_door(r, e)
    offs = poweroffs(e)
    r.ok("the VM powered off after the grace (nobody collected)", bool(offs) and "grace" in offs[-1], offs[-1:])
    return r.done()


def silent_case(a: argparse.Namespace, hang: bool) -> int:
    r = Result(a.case)
    e = a.evidence
    con = text(e / "console.log")
    run_offs = poweroffs(e, "POWEROFF.run")
    if hang:
        r.ok("the stuck part was powered off by the idle watchdog", bool(run_offs) and "no heartbeat" in run_offs[0],
             run_offs[:1])  # fmt: skip
    else:
        r.ok("the busy silent part was never powered off as idle", not any("no heartbeat" in x for x in run_offs),
             run_offs)  # fmt: skip
        r.ok("it finished and powered off after the grace", bool(run_offs) and "grace" in run_offs[0], run_offs[:1])
    r.ok("--collect started the stopped VM results-only", "TB-COLLECT-ONLY: results.tgz" in con)
    check_door(r, e)
    offs = poweroffs(e)
    r.ok("the results-only boot powered off once collected", bool(offs) and "results collected" in offs[-1], offs[-1:])
    res = members(e / "out" / "shard-1" / "results.tgz")
    vm = res.get("vm.log", b"").decode("utf-8", "replace")
    tag = "selftest-hang" if hang else "selftest-busy"
    r.ok(f"the driver has results.tgz with the run log ({tag} started)", f"] {tag}" in vm, vm[-300:])
    part = res.get(f"parts/{tag}.json")
    if hang:
        r.ok("the stuck part has no result (it never finished)", part is None)
        rep = report_of(e)
        named = [x["tag"] for x in (rep.get("not_run") or []) + (rep.get("not_started") or [])]
        r.ok("the report names it as not run (no result: not run, VM stopped)", tag in named, named)
    else:
        ok = part is not None and all(c[1] for st in json.load(io.BytesIO(part))["stages"] for c in st["checks"])
        r.ok("the busy part passed", ok)
        hb = text(e / "standin-tb-watchdog.log")
        r.ok("the watchdog log has no error", "rror" not in hb, hb[-200:])
    return r.done()


def preempt_case(a: argparse.Namespace) -> int:
    """G1 bug A1: pre-empted after part 3, collected, resumed. The parts done before the pre-emption reach the driver,
    no collect removes them, and the resumed VM keeps them (``--resume``) and runs only the part that was cut."""
    r = Result(a.case)
    e = a.evidence
    only = [t for t in a.only.split(",") if t]
    done, cut = only[:-1], only[-1]
    r.ok("the VM was pre-empted (stopped from outside, mid-run)", bool(poweroffs(e, "POWEROFF.preempt")))
    r.ok("--collect started the stopped VM results-only", "TB-COLLECT-ONLY: results.tgz" in text(e / "console.log"))
    early = {p.stem: p.read_bytes() for p in (e / "parts-after-collect").glob("*.json")}
    r.ok("the collect after the pre-emption has the finished parts", set(done) <= set(early), sorted(early))
    r.ok("the part that was cut has no result after the pre-emption", cut not in early, sorted(early))
    drv = text(e / "driver.log")
    r.ok("no collect removed a part result", "HEAD removed" not in drv,
         [ln for ln in drv.splitlines() if "removed" in ln][:3])  # fmt: skip
    res = members(e / "out" / "shard-1" / "results.tgz")
    vm = res.get("vm.log", b"").decode("utf-8", "replace")
    for tag in done:
        r.ok(f"the resumed VM kept {tag} (--resume)", f"{tag}: done earlier in this run at this HEAD, kept" in vm)
        final = e / "out" / "parts" / f"{tag}.json"
        r.ok(f"{tag}: the result is the one made before the pre-emption", final.exists() and
             final.read_bytes() == early.get(tag))  # fmt: skip
    part = res.get(f"parts/{cut}.json")
    r.ok(
        f"the resumed VM ran {cut} to its end",
        part is not None and all(c[1] for st in json.load(io.BytesIO(part))["stages"] for c in st["checks"]),
    )
    rep = report_of(e)
    r.ok("the report has every planned part", set(only) <= {p["tag"] for p in rep.get("parts") or []})
    r.ok("no part crashed, did not report or lacked its data", not rep.get("not_run"), rep.get("not_run"))
    offs = poweroffs(e)
    r.ok("the VM powered off once the driver collected", bool(offs) and "results collected" in offs[-1], offs[-1:])
    return r.done()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("case", choices=["run-a", "run-b", "bucket", "served", "no-upload", "hang", "busy", "preempt"])
    ap.add_argument("evidence", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--head", default="")
    ap.add_argument("--previous", default="")
    a = ap.parse_args()
    print(f"== check {a.case} ({a.evidence})")
    if a.case in ("run-a", "run-b", "bucket"):
        return run_case(a)
    if a.case == "served":
        return served_case(a)
    if a.case == "no-upload":
        return no_upload_case(a)
    if a.case == "preempt":
        return preempt_case(a)
    return silent_case(a, a.case == "hang")


if __name__ == "__main__":
    sys.exit(main())
