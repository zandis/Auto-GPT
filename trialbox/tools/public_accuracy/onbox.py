# tb-boxrun: acc
"""The accuracy run's calls INTO an installed box: one program, piped into a service's container by the VM's helper
(``deploy/gcp/box_vm.py acc-set``: ``docker compose exec -T <service> python - <command> <json>``). It imports only
the box's own packages, never ``tools``: the box's image does not carry lane G's tools.

What each command uses, and in which container (the product path, and where it is not):

* ``send`` (mail-gateway): a request mail as the hospital's mail server hands it over: From the coordinator or the
  reviewer of the box's own settings, an ``Authentication-Results`` line of the box's own ``TB_MAIL_AUTHSERV_ID``
  (the hospital MTA's stamp), the protocol or the review workbook attached, through the mail gateway's own intake
  (``Gateway.handle``: allowlist, sender check, subject grammar, permissions, the daily limits, attachments to the
  store, the job to the orchestrator). Only the IMAP transport is not used: the VM has no hospital mail server.
* ``wait``, ``fetch`` (mail-gateway): the job as the mail gateway reads its own mailed jobs (``GET /jobs/{id}``, its
  service token) and the job's files from the box's object store (what the gateway attaches to its mails).
* ``env`` (mail-gateway): the box's environment and the settings the run depends on (limits, the tripwire's setting
  if the tree declares one), read as the services read them.
* ``routes`` (gateway): would the box's gateway route the compile's and the screen's calls in its environment, and
  to which builds (the routing policy and the registry the gateway loads); the prompt versions it serves there.
* ``embedder`` (orchestrator): which embedder SCREEN's cascade ranks with in this build (#589).
* ``pidmap`` (adapter): the box's pseudonym of each public chart number, with the box's site key, so the scorer can
  join the answers to the gold by ids outside the box. Only placed chart numbers of public data are mapped.
* ``audit`` (gateway): the gateway's own audit of the model calls since a time: counts per served prompt version and
  per refusal code, per job (no text: the audit holds none).
* ``traces`` (gateway): the raw model answers of the run since a time, as the box's own trace store keeps them (the
  prompt and the output of each call, redacted at write by the box's guard; TB_TRACESTORE on), read through the
  store's read API with a user and a purpose, so each read is in its access log. Public data only (a VALIDATION
  box); they stay in the run's results and are never committed.

Every command prints one JSON line last; ``wait`` prints a line whenever the job's state changes (the VM's watchdog
reads a growing log as a heartbeat).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from typing import Any


def out(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str), flush=True)


def _orch_get(path: str) -> Any:
    import httpx
    from tb_common.config import get_config
    from tb_common.service_auth import auth_headers

    url = get_config().env.orchestrator_url  # as the mail gateway's own job sink reaches the orchestrator
    r = httpx.get(f"{url.rstrip('/')}{path}", headers=auth_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def cmd_env(_: dict[str, Any]) -> None:
    from tb_common.config import DECLARED, environment_name, get_config

    cfg = get_config()
    st = cfg.settings
    reviewers = list(getattr(st, "reviewers", None) or [])
    senders = list(st.allowlist.senders or []) if st.allowlist else []
    out(
        {
            "environment": environment_name(os.environ),
            "senders": senders,
            "reviewers": reviewers,
            "intake": cfg.env.mail_intake_addr,
            "authserv": os.environ.get("TB_MAIL_AUTHSERV_ID", ""),
            "require_spf_dkim": st.require_spf_dkim,
            "rate_limit_per_sender_per_day": st.rate_limit_per_sender_per_day,
            "rate_limits_per_day": dict(st.rate_limits_per_day or {}),
            "mail_per_recipient_per_day": os.environ.get("TB_MAIL_PER_RECIPIENT_PER_DAY", ""),
            "jobs_per_sender_per_day": os.environ.get("TB_JOBS_PER_SENDER_PER_DAY", ""),
            "tripwire_settings": {k: os.environ.get(k, "") for k in DECLARED if "TRIPWIRE" in k},
            "data_class": os.environ.get("TB_DATA_CLASS", ""),
        }
    )


def cmd_send(a: dict[str, Any]) -> None:
    from email.message import EmailMessage
    from email.utils import format_datetime, make_msgid  # noqa: F401  (make_msgid: the format the id follows)

    from mail_gateway.app import gateway

    gw = gateway()
    sender = str(a["from"])
    domain = sender.rsplit("@", 1)[-1]
    authserv = gw.authserv_id or os.environ.get("TB_MAIL_AUTHSERV_ID", "")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = gw.cfg.env.mail_intake_addr or f"trialbox@{domain}"
    msg["Subject"] = str(a["subject"])
    msg["Message-ID"] = str(a["mid"])
    msg["Date"] = format_datetime(__import__("datetime").datetime.now(__import__("datetime").UTC))
    # the hospital MTA's stamp, as it writes it first in the header (D-369): the box's own authserv-id
    msg["Authentication-Results"] = (
        f"{authserv}; spf=pass smtp.mailfrom={domain}; dkim=pass header.d={domain}; dmarc=pass header.from={domain}"
    )
    msg.set_content(str(a.get("body") or "Public accuracy run (synthetic site).") + "\n")
    for name, b64 in (a.get("attach") or {}).items():
        data = base64.b64decode(b64)
        if name.endswith(".xlsx"):
            maintype, subtype = "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            maintype, subtype = "text", "plain"
        if maintype == "text":
            msg.add_attachment(data.decode("utf-8"), subtype=subtype, filename=name)
        else:
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    folder = gw.handle(bytes(msg))
    row = gw.db.db.fetchone(
        "SELECT action, job_id, COALESCE(reason, '') FROM intake WHERE message_id = ?", (str(a["mid"]),)
    )
    out({"folder": folder, "action": row[0] if row else None, "job": row[1] if row else None,
         "reason": row[2] if row else None})  # fmt: skip


def _job(job_id: str) -> dict[str, Any]:
    j = _orch_get(f"/jobs/{job_id}")
    return {
        "job": job_id,
        "type": j.get("type"),
        "ruleset": j.get("ruleset"),
        "ruleset_version": j.get("ruleset_version"),
        "state": j.get("state"),
        "error": j.get("error"),
        "outputs": [{"filename": f.get("filename"), "key": f.get("minio_key")} for f in j.get("outputs") or []],
        "metrics": {k: v for k, v in (j.get("metrics") or {}).items() if not isinstance(v, (dict, list))},
    }


def cmd_wait(a: dict[str, Any]) -> None:
    until = set(a["until"])
    end = time.time() + float(a["timeout_s"])
    last = None
    while True:
        j = _job(str(a["job"]))
        now = (j["state"], json.dumps(j["metrics"], sort_keys=True))
        if now != last:
            print(f"job {j['job']} {j['state']}", flush=True)
            last = now
        if j["state"] in until:
            out({**j, "waited": "ended"})
            return
        if time.time() > end:
            out({**j, "waited": "timeout"})
            return
        time.sleep(float(a.get("poll_s") or 5))


def cmd_fetch(a: dict[str, Any]) -> None:
    from mail_gateway.app import gateway

    j = _job(str(a["job"]))
    want = tuple(a["suffixes"])
    pre = tuple(a.get("prefixes") or ("",))
    got = {}
    for f in j["outputs"]:
        name = str(f["filename"] or "")
        if name.endswith(want) and name.startswith(pre) and f["key"]:
            got[name] = base64.b64encode(gateway().store.get(f["key"])).decode("ascii")
    out({"job": j["job"], "files": got})


def cmd_routes(a: dict[str, Any]) -> None:
    from gateway.core import GatewayConfig
    from gateway.policy import RoutingPolicy
    from registry.registry import Registry
    from tb_contracts.dataclass import ClassLabel
    from tb_llm.prompt_registry import default_registry

    cfg = GatewayConfig.from_env()
    policy = RoutingPolicy.load()
    reg = Registry.from_env()
    from gateway.policy import parse_label  # the gateway's own label parser (D2-L, +sc)

    rows = []
    for role, dc in a["calls"]:
        r: dict[str, Any] = {"role": role, "class": dc}
        try:
            label: ClassLabel = parse_label(dc)
            route, cands = policy.candidates(role, label, cfg.topology, cfg.environment, cfg.profile)
            r["route"] = route.id
            r["builds"] = []
            for c in cands:
                try:
                    res = reg.resolve(c.alias, c.endpoint.name, role=role, env=cfg.environment)
                    r["builds"].append({"alias": c.alias, "build": res.build.build_id, "routes": True})
                except Exception as exc:  # the registry's refusal, as the gateway would meet it
                    r["builds"].append({"alias": c.alias, "routes": False, "why": str(exc)[:300]})
            r["routes"] = any(b["routes"] for b in r["builds"])
        except Exception as exc:  # the policy's refusal (no route, the environment's ceiling)
            r["routes"] = False
            r["why"] = str(exc)[:300]
        rows.append(r)
    served = []
    for e in default_registry().served_set(cfg.environment.value):
        served.append(f"{e.id}@{e.version}")
    out({"environment": cfg.environment.value, "profile": cfg.profile, "routes": rows, "served_prompts": served})


def cmd_embedder(_: dict[str, Any]) -> None:
    import inspect

    from orchestrator.scenarios import screen_cascade

    src = inspect.getsource(screen_cascade)
    hashed = "embedder=HashEmbedder()" in src
    out(
        {
            "embedder": "hash stand-in (HashEmbedder): S2b cannot rank; #589 is not in this build"
            if hashed
            else "not the hash stand-in in screen_cascade (#589 or later): the embed service",
            "hash_in_screen": hashed,
        }
    )


def cmd_pidmap(a: dict[str, Any]) -> None:
    from pathlib import Path

    from tb_common.config import get_config
    from tb_common.crypto import SITE_KEY_FILE, load_key, pid_for_mrn

    key = load_key(Path(get_config().env.secrets_dir) / SITE_KEY_FILE)
    out({str(m): pid_for_mrn(key, str(m)) for m in a["mrns"]})


def cmd_audit(a: dict[str, Any]) -> None:
    from pathlib import Path

    from tb_common.config import get_config

    since = str(a.get("since") or "")
    d = Path(get_config().env.audit_path)
    by_prompt: dict[str, int] = {}
    refusals: dict[str, int] = {}
    per_job: dict[str, dict[str, int]] = {}
    for p in sorted(d.glob("**/*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"llm.gateway.' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if since and str(rec.get("ts") or "") < since:
                continue
            ev = str(rec.get("event") or rec.get("type") or "")
            det = rec.get("detail") or {}
            job = str(rec.get("job_id") or det.get("job_id") or "")
            code = str(det.get("reason") or det.get("code") or rec.get("refusal") or "")
            if ev.endswith(".call"):
                pv = str(rec.get("prompt_version") or det.get("prompt_version") or "?")
                by_prompt[pv] = by_prompt.get(pv, 0) + 1
            if code:
                refusals[code] = refusals.get(code, 0) + 1
                if job:
                    per_job.setdefault(job, {})[code] = per_job.setdefault(job, {}).get(code, 0) + 1
    out({"since": since, "calls_by_prompt": by_prompt, "refusals": refusals, "refusals_by_job": per_job})


def cmd_traces(a: dict[str, Any]) -> None:
    from tracestore.store import TraceStore

    since = str(a.get("since") or "")
    store = TraceStore()
    roles = frozenset({store.settings.read_role})
    ids = [
        r[0] for r in store.db.fetchall("SELECT DISTINCT call_id FROM traces WHERE ts >= ? ORDER BY call_id", (since,))
    ]
    rows: list[Any] = []
    for cid in ids:
        rows += store.read(
            cid, user="lane-g-accuracy-run", purpose="public-data accuracy run: raw answers", roles=roles
        )
    out({"since": since, "calls": len(ids), "traces": rows})


COMMANDS = {
    "env": cmd_env,
    "send": cmd_send,
    "wait": cmd_wait,
    "fetch": cmd_fetch,
    "routes": cmd_routes,
    "embedder": cmd_embedder,
    "pidmap": cmd_pidmap,
    "audit": cmd_audit,
    "traces": cmd_traces,
}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in COMMANDS:
        print(f"onbox: one of {', '.join(COMMANDS)}", file=sys.stderr)
        raise SystemExit(2)
    COMMANDS[name](json.loads(base64.b64decode(sys.argv[2]).decode("utf-8")) if len(sys.argv) > 2 else {})
