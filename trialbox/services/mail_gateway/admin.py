"""``trialbox mail status`` and ``trialbox mail resolve`` (T-108c, D-401): the operator's view of the mail outbox.

Run in the mail-gateway container, which has the database and the mail server:
``docker compose exec mail-gateway python -m tools.trialbox mail status``.

* ``status`` lists every send that is not finished: queued (the dispatcher tries again), uncertain (it may have
  arrived), failed (refused for good or too many tries). Exit 1 when one waits for a person.
* ``resolve`` with no key sends the queue now (after an MTA outage), whatever the back-off says. On an empty queue it
  does nothing.
* ``resolve KEY --sent`` (it did arrive: checked in the mailbox), ``--resend`` (send it again now) or ``--drop`` (give
  up). Audited as ``mail.resolved`` with the person.

No mail body or attachment is printed."""

from __future__ import annotations

import getpass
import json
import os
import sys
from dataclasses import asdict
from typing import TextIO

from mail_gateway.gateway import Gateway

WAITS_FOR_A_PERSON = ("uncertain", "failed")


def actor(by: str | None) -> str:
    if by:
        return by
    try:
        return os.environ.get("SUDO_USER") or getpass.getuser()
    except (KeyError, OSError):  # no passwd entry for the container's user id
        return "operator"


def status(gw: Gateway, as_json: bool, out: TextIO) -> int:
    rows = gw.db.open_keys()
    if as_json:
        print(json.dumps([asdict(r) | {"result": None} for r in rows], indent=1, ensure_ascii=False), file=out)
    else:
        for r in rows:
            nxt = f" next {r.next_at[:19]}" if r.next_at else ""
            err = f"  {r.last_error}" if r.last_error else ""
            who = f"job {r.job_id or '-'}  to {r.recipients or '-'}"
            print(f"{r.state:<9} {r.key}  {who}  tries {r.attempts}{nxt}{err}", file=out)
        counts = gw.db.counts()
        print(", ".join(f"{n} {s}" for s, n in counts.items()) + " (mail resolve: see RUNBOOK, mail)", file=out)
    return 1 if any(r.state in WAITS_FOR_A_PERSON for r in rows) else 0


def resolve(gw: Gateway, key: str | None, decision: str | None, by: str | None, out: TextIO) -> int:
    if key is None:
        if decision is not None:
            print("mail resolve: --sent, --resend and --drop need a send key (mail status lists them)", file=sys.stderr)
            return 2
        done = gw.drain(force=True)
        print("sent the queue: " + (", ".join(f"{n} {s}" for s, n in done.items()) or "nothing was queued"), file=out)
        left = gw.db.counts()
        if any(left[s] for s in WAITS_FOR_A_PERSON):
            print(f"{left['uncertain']} uncertain and {left['failed']} failed wait for a decision: "
                  "mail resolve KEY --sent|--resend|--drop", file=out)  # fmt: skip
        return 0 if not left["queued"] else 1
    if decision is None:
        print("mail resolve KEY: say --sent, --resend or --drop", file=sys.stderr)
        return 2
    try:
        before = gw.resolve(key, decision, actor(by))
    except KeyError as exc:
        print(f"mail resolve: {exc.args[0]}", file=sys.stderr)
        return 1
    print(f"{key}: {before} -> {decision}", file=out)
    if decision == "resend":
        done = gw.drain(force=True)
        print("sent the queue: " + (", ".join(f"{n} {s}" for s, n in done.items()) or "nothing"), file=out)
    return 0


def main(
    action: str,
    key: str | None = None,
    decision: str | None = None,
    by: str | None = None,
    as_json: bool = False,
    gw: Gateway | None = None,
    out: TextIO = sys.stdout,
) -> int:
    if gw is None:
        from mail_gateway.app import gateway

        gw = gateway()
    if action == "status":
        return status(gw, as_json, out)
    return resolve(gw, key, decision, by, out)
