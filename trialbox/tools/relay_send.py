#!/usr/bin/env python3
"""Send one message to a running channel-relay (Hermes fragment test overlay, DEV/TEST only).

    python tools/relay_send.py "FEAS GZQO"                                # email, subject line = grammar line
    python tools/relay_send.py --body "Could we run GZQO here? How many patients over the last 3 years?"
    python tools/relay_send.py --body OK --subject "Re: request" --in-reply-to "<reply-id@hospa.test>"
    python tools/relay_send.py --teams "what is the status of my requests?"

Email: an RFC 822 message from ``--sender`` (default the POC administrator) with the ``Authentication-Results``
header the hospital MX adds (``dmarc=pass``, authserv-id ``mx.hospa.test``), posted to ``/inbound/email``; the reply
is in MailHog (http://127.0.0.1:8025). Teams: a fake Bot Framework activity (MS0) posted to ``/inbound/teams``; the
reply is listed at ``/outbox/teams``. Prints the relay's result (action, conversation, reply id, ticket, job).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any


def email_bytes(subject: str, body: str, sender: str, to: str, in_reply_to: str | None, authserv: str) -> bytes:
    m = EmailMessage()
    m["Authentication-Results"] = f"{authserv}; dmarc=pass header.from={sender.rsplit('@', 1)[-1]}"
    m["From"] = sender
    m["To"] = to
    m["Subject"] = subject
    m["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = in_reply_to
    m.set_content(body or "")
    return m.as_bytes()


def post(url: str, data: bytes, ctype: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, data=data, headers={"content-type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out: dict[str, Any] = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        out = {"http_status": e.code, **json.loads(e.read() or b"{}")}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("subject", nargs="?", default="TrialBox request")
    ap.add_argument("--body", default="")
    ap.add_argument("--sender", default="admin@hospa.test")
    ap.add_argument("--to", default="trialbox@hospa.test")
    ap.add_argument("--in-reply-to")
    ap.add_argument("--authserv-id", default="mx.hospa.test")
    ap.add_argument("--teams", metavar="TEXT", help="send a fake Teams activity instead of an email")
    ap.add_argument("--teams-conversation", default="poc-teams-1")
    ap.add_argument("--teams-user", default="aad-poc-admin")
    ap.add_argument("--teams-token", default="poc-teams-token")
    ap.add_argument("--relay", default="http://127.0.0.1:8095")
    ap.add_argument("--timeout", type=float, default=240.0)
    a = ap.parse_args(argv)
    if a.teams:
        activity = {
            "type": "message",
            "id": make_msgid(domain="teams.invalid").strip("<>"),
            "text": a.teams,
            "tenantId": "tenant-1",
            "token": a.teams_token,
            "from": {"aadObjectId": a.teams_user},
            "conversation": {"id": a.teams_conversation},
        }
        out = post(f"{a.relay}/inbound/teams", json.dumps(activity).encode(), "application/json", a.timeout)
    else:
        raw = email_bytes(a.subject, a.body, a.sender, a.to, a.in_reply_to, a.authserv_id)
        out = post(f"{a.relay}/inbound/email", raw, "message/rfc822", a.timeout)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if "http_status" not in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
