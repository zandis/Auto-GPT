"""Hermes behind channel-relay and frontdoor-mcp, end to end on the running POC stack (spec v4 §9.2-§9.4; S1-11).

Needs the POC (``make poc``) plus the Hermes fragment and its test overlay (``make poc-hermes``), and
``TB_INTEGRATION=1``. Through the relay's intake, as the POC administrator by email:

1. a plain-language feasibility request reaches Hermes only through ``tb_relay_adapter`` (HER-6); Hermes calls
   ``tb.submit_request`` on frontdoor-mcp over mTLS with the relay-minted assertion attached by ``tb_policy_audit``
   (HER-15); the orchestrator renders the proposal and the reply arrives in MailHog;
2. ``OK`` on that reply is deterministic intake (no model) and starts the FEAS job in the orchestrator;
3. a status question makes Hermes call ``tb.status``;
4. the audit chain holds, per conversation and in order: the hook decision, the front door's intent and result
   events, then the relay's turn (HER-14, FR-CONV-16);
5. a front-door call without an assertion is refused, even over a valid client certificate (HER-15).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

import pytest

pytestmark = pytest.mark.e2e

ADMIN = os.environ.get("TB_POC_ADMIN_EMAIL", "admin@hospa.test")
RELAY = f"http://127.0.0.1:{os.environ.get('TB_HOST_RELAY_PORT', '8095')}"
MAILHOG = f"http://127.0.0.1:{os.environ.get('TB_HOST_MAILHOG_PORT', '8025')}"
ORCH = f"http://127.0.0.1:{os.environ.get('TB_HOST_ORCH_PORT', '8010')}"


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _send(subject: str, body: str, in_reply_to: str | None = None, sender: str = ADMIN) -> dict[str, Any]:
    m = EmailMessage()
    m["Authentication-Results"] = f"mx.hospa.test; dmarc=pass header.from={sender.rsplit('@', 1)[1]}"
    m["From"], m["To"], m["Subject"] = sender, "trialbox@hospa.test", subject
    m["Message-ID"] = make_msgid(domain="hospa.test")
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(body)
    req = urllib.request.Request(
        f"{RELAY}/inbound/email", data=m.as_bytes(), headers={"content-type": "message/rfc822"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        out: dict[str, Any] = json.loads(r.read())
    return out


def _mail_body(message_id: str) -> str:
    q = urllib.parse.quote(message_id.strip("<>"))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        items = _get(f"{MAILHOG}/api/v2/search?kind=containing&query={q}&limit=5")["items"]
        for it in items:
            mids = it["Content"]["Headers"].get("Message-ID") or it["Content"]["Headers"].get("Message-Id") or []
            if message_id in mids:
                import quopri

                body = it["Content"]["Body"]
                cte = " ".join(it["Content"]["Headers"].get("Content-Transfer-Encoding", [])).lower()
                if "quoted-printable" not in cte:  # a model reply with non-ASCII text goes out 8bit
                    return str(body)
                return quopri.decodestring(body.encode("utf-8")).decode("utf-8", "replace")
        time.sleep(1)
    raise AssertionError(f"no reply {message_id} in MailHog")


def _container(service: str) -> str:
    out = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.service={service}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if not out:
        pytest.skip(f"{service} is not running (make poc-hermes)")
    return out[0]


def _audit() -> list[dict[str, Any]]:
    cid = _container("frontdoor-mcp")
    raw = subprocess.run(
        ["docker", "exec", cid, "sh", "-c", "cat /data/audit/*.jsonl"], capture_output=True, text=True, check=True
    ).stdout
    return [json.loads(x) for x in raw.splitlines() if x.strip()]


@pytest.fixture(scope="module", autouse=True)
def _stack_up() -> None:
    try:
        health = _get(f"{RELAY}/healthz")
    except (urllib.error.URLError, OSError):
        pytest.skip("channel-relay intake not reachable (make poc-hermes)")
    if health.get("engine") != "hermes":
        pytest.skip(f"channel-relay engine is {health.get('engine')!r}, not hermes")


@pytest.mark.req("S1-11", "HER-6", "HER-15", "HER-14", "HER-11", "FR-CONV-16", "FR-CONV-2")
def test_free_text_reaches_hermes_tools_through_the_front_door_and_ok_starts_the_job() -> None:
    res = _send("Feasibility question", "Could we run study GZQO here? How many patients over the last 3 years?")
    assert res["action"] == "proposal" and res["engine"] == "hermes" and res["ticket_id"], res
    body = _mail_body(res["reply_id"])
    assert "FEAS GZQO scope=hospital lookback=36m" in body and "OK" in body

    ok = _send("Re: Feasibility question", "OK", in_reply_to=res["reply_id"])
    assert ok["action"] == "confirmed" and ok["ticket_id"] == res["ticket_id"] and ok["job_id"], ok
    job: dict[str, Any] = {}
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        job = _get(f"{ORCH}/jobs/{ok['job_id']}")
        if job["state"] in ("done", "failed", "rejected", "cancelled"):
            break
        time.sleep(2)
    assert job["type"] == "FEAS" and job["ruleset"] == "GZQO" and job["requested_by"] == ADMIN
    assert job["options"].get("lookback") == "36" and job["state"] == "done", job

    st = _send("Status", "What is the status of my requests?")
    assert st["action"] == "answer" and st["engine"] == "hermes", st
    status = _mail_body(
        st["reply_id"]
    )  # wording is the model's (it may summarise many tickets); the state must be there
    assert "FEAS" in status and "confirmed" in status.lower(), status

    events = _audit()
    for conv, tool, action in ((res["conv"], "tb.submit_request", "proposal"), (st["conv"], "tb.status", "answer")):
        seq = [
            e["event"]
            for e in events
            if (e.get("detail") or {}).get("conv") == conv
            and e["event"] in ("frontdoor.policy.decide", "frontdoor.call.intent", "frontdoor.call", "channel.turn")
            and ((e.get("detail") or {}).get("tool") in (tool, None))
            and (e["event"] != "channel.turn" or e["detail"].get("actor_type") == "hermes")  # not the OK turn
        ]
        assert seq == ["frontdoor.policy.decide", "frontdoor.call.intent", "frontdoor.call", "channel.turn"], seq
        turn = next(e for e in events if e["event"] == "channel.turn" and e["detail"].get("conv") == conv)
        assert turn["detail"]["actor_type"] == "hermes" and turn["detail"]["action"] == action
        assert turn["actor"] == ADMIN


@pytest.mark.req("HER-15", "HER-6")
def test_front_door_refuses_a_call_without_assertion_over_a_valid_certificate() -> None:
    cid = _container("channel-relay")
    probe = (
        "import json,urllib.request;from tb_common.mtls import client_context as c;"
        "s='/run/secrets/tb/';x=c(s+'channel-relay.pem',s+'channel-relay.key',s+'tb-ca.pem');"
        "m={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'tb.status','arguments':{}}};"
        "r=urllib.request.Request('https://frontdoor-mcp:8443/mcp',data=json.dumps(m).encode(),"
        "headers={'content-type':'application/json'},method='POST');"
        "print(urllib.request.urlopen(r,context=x,timeout=10).read().decode())"
    )
    out = subprocess.run(
        ["docker", "exec", cid, "python", "-c", probe], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(out)["error"]["code"] == -32001 and "assertion_missing" in out
    alarms = [e for e in _audit() if e["event"] == "frontdoor.auth.refuse"]
    assert alarms and alarms[-1]["detail"]["alarm"] is True


@pytest.mark.req("FR-CONV-14", "HER-6")
def test_unknown_sender_never_reaches_hermes() -> None:
    res = _send("Feasibility", "how many patients for GZQO?", sender="intruder@evil.test")
    assert res == {"action": "dropped", "reason": "sender_not_authenticated"}
