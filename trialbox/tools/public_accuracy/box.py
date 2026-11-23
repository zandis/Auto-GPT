"""The plumbing proof: a built public site screened by an in-process box on the stand-in models. NOT an accuracy result.

What is the product here, and what is not:

* **Product path**: the hospital CSV feed read by the adapter (``tests.inproc_box.ingest_site``: the CSV source, the
  ``demo_his.yaml`` mapping, the lake rebuild and the derive batch, as the nightly INGEST job runs them); the
  protocol mailed as a coordinator mails it (``FEAS <RULESET>`` with the file attached), parsed, compiled by the
  product's criteria compiler (``ir_extract``, ``concept_map``), the review mail, the reviewer's approval by replying
  with the review workbook (``APPROVE``), then ``SCREEN <RULESET>`` by mail, scoped by the study's site profile; every
  model call through a tb-gateway built as an installed box builds it (``TB_ENV=PRODUCTION``, the installed pins:
  ``tools.scenarios.gateway_client`` / ``installed_env``), the compiler calling as ``criteria-compiler``, the
  orchestrator as itself, behind ``model_guard`` with the key, to two strict vLLM stand-ins (``tools.vllm_standin``)
  under the compose's served names.
* **Not the product**: the box is one Python process (``tests.inproc_box.make_box``), the embedder is the hash
  stand-in (so S2b cannot rank: #589), the CQL translator is the test fake, and the stand-ins answer from
  ``services/llm_stub`` (the compiler's stub turns most lines into ``human`` criteria; the judge's stub answers
  "unknown" to every question it was not written for). The run proves that the data reach the box, compile, approve,
  screen and come back joinable to the gold; it measures nothing about the models.

Needs, as ``tools.public_e2e``: a local PostgreSQL (``tools.pglocal``), the CQL jar (``python -c "from pathlib import
Path; from tools import fetch_run_data as f; f.fetch_cql(Path('.cache'))"``) and the fonts (``tools/fetch_fonts.py``).
"""

from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import threading
import time
import zipfile
from collections import Counter
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tools.public_accuracy import site as site_mod

TODAY_OFFSET = 1  # the box's day: the snapshot day plus one (as tools.public_e2e)
# The site's per-sender daily limit on heavy jobs (settings ``rate_limit_per_sender_per_day``: 20 FEAS a day) would
# stop the run after 20 protocols; the run sets the site's own per-type override (0 = no limit), as an installed box's
# settings.yaml would for the accuracy run (a setting, not a code change: deploy/settings.example.yaml line 26)
RUN_SETTINGS = {"rate_limits_per_day": {"FEAS": 0, "SCREEN": 0}}
# The mail gateway's outbound limit to one address a day (TB_MAIL_PER_RECIPIENT_PER_DAY, mail_gateway.app; 200)
# held the coordinator's review mails once 200 had gone out (a 30-protocol dry run sends that many); an installed
# box's .env sets it to 0 for the run, as here
MAIL_PER_RECIPIENT_PER_DAY = 0


def _serve(handler: Any) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def standin_pair(key: str) -> tuple[dict[str, str], list[ThreadingHTTPServer]]:
    """Judge and verifier stand-ins under the pinned served names, each behind model-guard with ``key`` (as the
    compose runs them). {endpoint: guard URL}, servers."""
    import model_guard

    from tools import pin_model
    from tools import vllm_standin as vs

    urls, servers = {}, []
    for endpoint, served in (("serving", pin_model.JUDGE_SERVED), ("verifier", pin_model.VERIFIER_SERVED)):
        s, _, _ = vs.build([f"--served-model-name={served}", "--api-key", key], {})
        up = _serve(vs.make_handler(s))
        guard = _serve(
            model_guard.make_handler(model_guard.Guard(key, {"127.0.0.1": ("127.0.0.1", up.server_address[1])}))
        )
        urls[endpoint] = f"http://127.0.0.1:{guard.server_address[1]}/v1"
        servers += [up, guard]
    return urls, servers


def gateway_clients(work: Path, urls: dict[str, str], key: str) -> dict[str, Any]:
    """The judge, the verifier (as the orchestrator) and the compiler's client, through one PRODUCTION gateway."""
    from tb_common.llm import LlmClient

    from tools import pin_model, scenarios

    audit = work / "gw-audit"
    audit.mkdir(parents=True, exist_ok=True)
    os.environ.pop("TB_DATA_CLASS", None)  # as install leaves it
    env = scenarios.installed_env(audit, urls["serving"], urls["verifier"])
    env["TB_LLM_API_KEY"] = key  # the gateway's key to model-guard (a compose secret on a box; a throwaway here)

    def client(served: str, alias: str, caller: str) -> Any:
        c = LlmClient("http://unused/v1", served, gateway=scenarios.gateway_client(env, caller=caller))
        if alias:
            c.gateway.model = alias
        return c

    return {
        "judge": client(pin_model.JUDGE_SERVED, "", "orchestrator"),
        "verifier": client(pin_model.VERIFIER_SERVED, "v-verifier", "orchestrator"),
        "compiler": client(pin_model.JUDGE_SERVED, "", "criteria-compiler"),
        "env": env,
        "audit": audit,
    }


def draft_criteria(zip_bytes: bytes) -> list[dict[str, Any]]:
    """The compiled criteria in a review mail's draft zip (``<RULESET>/ir/<id>.json``, one criterion IR each): id,
    kind, class, text, logic domain, flags."""
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in sorted(n for n in z.namelist() if "/ir/" in n and n.endswith(".json")):
            c = json.loads(z.read(name).decode("utf-8"))
            text = c.get("text")
            out.append(
                {
                    "id": c.get("id"),
                    "kind": c.get("kind"),
                    "class": c.get("class"),
                    "text": text.get("source") if isinstance(text, dict) else text,
                    "domain": (c.get("logic") or {}).get("domain"),
                    "logic": c.get("logic"),
                    "flags": c.get("flags") or [],
                }
            )
    return out


def _verdicts(pv: Any) -> list[dict[str, Any]]:
    out = []
    for v in getattr(pv, "verdicts", []) or []:
        d = v.model_dump(mode="json") if hasattr(v, "model_dump") else dict(getattr(v, "__dict__", {}))
        out.append(
            {k: d.get(k) for k in ("id", "verdict", "stage", "reason", "quote", "confidence", "basis") if k in d}
        )
    return out


def llm_calls(audit_dirs: list[Path]) -> dict[str, int]:
    """Model calls per served prompt (``prompt_version``, e.g. ``ir_extract@2``) in the gateway's audit records
    (``llm.gateway.call``): what the gateway served, not what the caller asked for."""
    n: Counter[str] = Counter()
    for d in audit_dirs:
        for p in sorted(d.glob("**/*.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if '"llm.gateway.call"' in line:
                    rec = json.loads(line)
                    n[str(rec.get("prompt_version") or "?")] += 1
    return dict(sorted(n.items()))


def run(built: Path, work: Path, screen: bool = True, approve: bool = True) -> dict[str, Any]:
    """Screen the site at ``built/site`` (written by :func:`site.build`) on a fresh in-process box under ``work``.
    Writes ``work/answers.json`` (per ruleset: the draft criteria, the job states, the per-patient verdicts keyed by
    pseudonym) and ``work/run.json`` (counts, stage logs, model calls by prompt). The gold is not read."""
    from tb_common.config import adopt_site_tz

    adopt_site_tz()  # D-315: a synthetic site in one process takes its zone from the settings, never from code
    from tests.inproc_box import ingest_site, make_box
    from tools import feas_demo as fd
    from tools import scenarios
    from tools.public_e2e import attach_models

    t0 = time.perf_counter()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    site = built / "site"
    sec = work / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(fd.KEY)  # the synthetic site key of the demo tools (no real patient)
    snapshot = (site_mod.REF - timedelta(days=1)).isoformat()
    rep = ingest_site(site / "hospital", work / "lake", sec, snapshot)
    box = make_box(
        work / "box",
        work / "lake",
        sec,
        site_mod.REF + timedelta(days=TODAY_OFFSET),
        settings_update=RUN_SETTINGS,
        extra_profiles=site / "profiles",
    )
    box.gw.per_recipient_per_day = MAIL_PER_RECIPIENT_PER_DAY
    key = secrets.token_hex(16)  # the stand-ins' key for this run only
    # the run's services call the gateway under their own names, as on a box (D-437): one verified token each, not the
    # old shared one, which the PRODUCTION gateway refuses as caller_unverified
    from orchestrator import app as orch_app

    from tools.role_demo import orch_client

    orch_app._orch = box.orch
    orch_client(orch_app.app)
    urls, servers = standin_pair(key)
    gw = gateway_clients(work, urls, key)
    canary = attach_models(box, gw["judge"], gw["verifier"])
    deps = box.orch.services.compiler.d  # type: ignore[attr-defined]  # the box's compiler calls its gateway as criteria-compiler (defect B13)
    deps.llm = gw["compiler"]
    deps.prompt_environment = gw["compiler"].gateway.prompt_environment
    scenarios.capture_screens()
    answers: dict[str, Any] = {}
    try:
        for proto in sorted((site / "protocols").glob("*.txt")):
            rs = proto.stem
            a: dict[str, Any] = {"ruleset": rs}
            a["mail"] = box.mail(f"FEAS {rs}", ((proto.name, proto.read_bytes()),))
            box.orch.drain()
            feas = box.orch.db.find(type_="FEAS", ruleset=rs, limit=5)
            a["feas"] = feas[0].state if feas else None
            a["feas_error"] = str(feas[0].error) if feas and feas[0].error else None
            rev = box.find(f"APPROVE {rs} ")
            if rev:
                atts = rev[-1].attachments()
                z = next((v for k, v in atts.items() if k.endswith(".zip")), None)
                a["draft"] = draft_criteria(z) if z else []
                if approve:
                    xlsx = next(v for k, v in atts.items() if k.endswith(".xlsx"))
                    box.mail("approved", (("review.xlsx", xlsx),), in_reply_to=str(rev[-1].msg["Message-ID"]))
                    box.orch.drain()
                    appr = box.orch.db.find(type_="APPROVE", ruleset=rs, limit=5)
                    a["approve"] = appr[0].state if appr else None
            if screen and a.get("approve") == "done":
                job, _js, cap = scenarios.screen_once(box, rs)
                a["screen"] = job.state if job else None
                a["screen_error"] = str(job.error) if job is not None and job.error else None
                if cap:
                    a["patients"] = {
                        pid: {"tier": pv.tier, "actions": list(pv.actions), "verdicts": _verdicts(pv)}
                        for pid, pv in cap["results"].items()
                    }
                    a["cascade"] = cap["summary"]
                    a["judging"] = cap["judging"]
            feas = box.orch.db.find(type_="FEAS", ruleset=rs, limit=5)
            a["feas_final"] = feas[0].state if feas else None
            answers[rs] = a
    finally:
        for s in servers:
            s.shutdown()
    calls = llm_calls([gw["audit"]])
    served = sorted({str(c) for c in calls})
    out = {
        "what": "plumbing proof on the stand-in models (services/llm_stub answers): NOT an accuracy result",
        "ingest": {"passed": rep.passed, "counts": rep.counts, "missing_required": rep.missing_required},
        "gateway_env": gw["env"].get("TB_ENV"),
        "canary": canary,
        "protocols": len(answers),
        "model_calls_by_prompt": calls,
        "prompts_seen": served,
        "seconds": round(time.perf_counter() - t0, 1),
        "site_key_pid": "pid_for_mrn(tools.feas_demo.KEY, mrn): the synthetic site key of the demo tools",
    }
    (work / "answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (work / "run.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {**out, "answers": answers}
