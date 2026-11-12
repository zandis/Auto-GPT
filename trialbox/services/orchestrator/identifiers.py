"""The one door between a chart number and a pseudonym in the orchestrator (T-719, D-487; trust review F3, TR-8).

Everything in ``services/orchestrator`` (and the console, which holds neither key) that turns a chart number into a
pseudonym, or a pseudonym back into a chart number or a name, does it through this module. Nothing else there
imports ``pid_for_mrn`` or ``PidMap`` or names ``site_hmac.key`` or ``pid_map.key``;
``tests/unit/test_identifiers_door.py`` fails on a new use.

Two kinds of caller:

* the orchestrator's own work (a job that screens, a case, a registry row, a sheet import): :func:`site_key`,
  :func:`pid_of`, :func:`charts_of`, :func:`identity_of`. Who asked for the work was decided when the job or the
  call was admitted.
* a request that gives a chart number and gets the pseudonym *back* (``POST /setup/pseudonym``, ``POST
  /registry/{ruleset}`` with ``mrn``). The site's chart numbers are a small space, so such a route answers whoever
  may walk it: :func:`admit` requires the verified person of the call (the v3 assertion, ``orchestrator.actor``),
  a right of the matrix for it, a cap per person and hour in the store, and writes ``screen.to_pid`` with the
  pseudonym (never the chart number).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from tb_common.authz import permit
from tb_common.crypto import load_key, pid_for_mrn
from tb_common.kek import key_present

from orchestrator import actor as route_actor

_log = logging.getLogger("trialbox.identifiers")
SITE_KEY = "site_hmac.key"
MAP_KEY = "pid_map.key"
#: the matrix rows that may ask for a pseudonym by chart number, each on its own route (:func:`admit` is told
#: which): the opt-out register, a registry row typed by hand, a chart or a sheet given to site set-up
ACTIONS = frozenset({"optout.keep", "request.prepare", "site.setup"})
CAP_ENV = "TB_TO_PID_MAX_PER_HOUR"
NO_PERSON = "a chart number needs a verified person"


# ---------------------------------------------------------------------------- the orchestrator's own work
def has_site_key(secrets_dir: Path | str) -> bool:
    """Whether the box has its site key, plain or wrapped under the KEK (T-210b); none before the first ingest."""
    return key_present(Path(secrets_dir) / SITE_KEY)


def site_key(secrets_dir: Path | str) -> bytes:
    """The site's HMAC key (``OSError`` when the box has none yet)."""
    return load_key(Path(secrets_dir) / SITE_KEY)


def pid_with(key: bytes, chart_no: str) -> str:
    """The pseudonym of a chart number under a key already loaded (a sheet's rows)."""
    return pid_for_mrn(key, chart_no)


def pid_of(secrets_dir: Path | str, chart_no: str) -> str:
    return pid_for_mrn(site_key(secrets_dir), chart_no)


def has_map(secrets_dir: Path | str) -> bool:
    return key_present(Path(secrets_dir) / MAP_KEY)


def _map(secrets_dir: Path | str, url: str | None) -> Any:
    from adapter.pidmap import PidMap

    return PidMap(Path(secrets_dir) / MAP_KEY, url)


def charts_of(secrets_dir: Path | str, pids: list[str], url: str | None = None) -> dict[str, str]:
    """pid -> chart number from the box's pid map; empty when the box has no map (no key: a stub install, no ingest
    yet). ``url``: the trial database (the orchestrator's; ``TB_DB_URL`` when None)."""
    if not pids or not has_map(secrets_dir):
        return {}
    pm = _map(secrets_dir, url)
    try:
        return dict(pm.resolve_many(pids))
    finally:
        pm.close()


def known_pid(secrets_dir: Path | str, url: str | None, pid: str) -> bool | None:
    """NEW-DIN-3 (D-544): whether the pid map knows this pseudonym, so whether it is a patient this box has loaded:
    a row of its own, or a chart number merged into another patient (the opt-out register hides the surviving
    patient for it, ``tb_common.optout.with_survivors``). None: it cannot say (no map key yet, or the map cannot be
    read); never taken for "known". Why it cannot say goes to the log, without the pseudonym."""
    if not has_map(secrets_dir):
        return None
    try:
        pm = _map(secrets_dir, url)
    except Exception as exc:
        _log.warning("known_pid: the pid map cannot be opened: %s", type(exc).__name__)
        return None
    try:
        return pm.resolve(pid) is not None or pid in pm.aliases()
    except Exception as exc:
        _log.warning("known_pid: the pid map cannot be read: %s", type(exc).__name__)
        return None
    finally:
        pm.close()


def identity_of(secrets_dir: Path | str, pid: str, url: str | None = None) -> dict[str, str]:
    """What the map holds of one person (name, birth date, ...) with the chart number as ``mrn``; empty without a
    map."""
    if not has_map(secrets_dir):
        return {}
    pm = _map(secrets_dir, url)
    try:
        out = dict(pm.identity(pid) or {})
        mrn = pm.resolve(pid)
        if mrn:
            out["mrn"] = mrn
        return out
    finally:
        pm.close()


# ---------------------------------------------------------------------------- a request that gets a pseudonym back
def cap() -> int:
    """Lookups by chart number per signed name and rolling hour. Its own setting; unset, it is the cap of the
    opposite direction (``TB_REVEAL_MAX_PER_HOUR``): the two walk the same space."""
    return int(os.environ.get(CAP_ENV) or os.environ.get("TB_REVEAL_MAX_PER_HOUR") or "60")


class Door:
    """One admitted lookup: :func:`admit` decided who; ``record(pid)`` writes the event once the pseudonym is
    known."""

    def __init__(self, audit: Any, claim: Any, via: str) -> None:
        self.audit, self.claim, self.via = audit, claim, via

    def record(self, pid: str) -> None:
        c = self.claim
        self.audit.append("screen.to_pid", actor=c.sub, ruleset=c.study or None,
                          detail={"pid": pid, "role": c.role, "action": c.action, "via": self.via})  # fmt: skip

    def record_input(self, input_id: Any) -> None:
        """A chart or a sheet given to site set-up: the pseudonyms are in that input's rows (one chart: one; a
        sheet: every row), so the event names the input, not a list."""
        c = self.claim
        self.audit.append("screen.to_pid", actor=c.sub, ruleset=c.study or None,
                          detail={"input": str(input_id or ""), "role": c.role, "action": c.action,
                                  "via": self.via})  # fmt: skip


def admit(request: Request, study: str | None, db: Any, audit: Any, at: datetime, *,
          actions: tuple[str, ...], service: bool = False) -> Door:  # fmt: skip
    """Who asks for a pseudonym by chart number on this request, or HTTP 403 (429 at the cap) and one
    ``actor.refused`` event. The claim is the one ``orchestrator.actor`` verified for exactly this request and body;
    a call with none, however good its service token, is refused here.

    ``study``: the route's study (a registry row), which the claim must be for; None on a route of the whole box,
    where a claim for a study is refused. ``actions``: the matrix rows this route admits (one route, one purpose).
    ``service``: the route admits a console timer's principal for those actions (the opt-out check only)."""
    assert set(actions) <= ACTIONS, actions
    via = route_actor.template(request)
    claim = getattr(request.state, "tb_actor", None)
    if claim is None:
        # the stage before this door says why a claim it was sent is not a verified person (its role lacks the
        # right, another study, another body); with no claim at all the reason is that nobody asked
        seen = str(getattr(request.state, "tb_actor_why", "") or "")
        why = seen if seen in ("right", "study", "principal", "action") else NO_PERSON
        raise route_actor.refusal(request, "", why, None, study)
    why = ""
    if claim.action not in actions:
        why = "action"
    elif (study or "") != claim.study:
        why = "study"
    elif claim.is_service:
        if not service or claim.action not in route_actor.TABLE["principals"].get(claim.sub, frozenset()):
            why = "principal"
    elif not permit(claim.role, claim.action, claim.standing()).allowed:
        why = "right"
    if why:
        raise route_actor.refusal(request, claim.action, why, claim.sub, study)
    if not db.take_limit("to_pid", claim.sub, int(at.timestamp() * 1000), 3_600_000, cap()):
        route_actor.refusal(request, claim.action, "rate limit", claim.sub, study)
        raise HTTPException(status_code=429, detail="too many lookups by chart number in the last hour")
    return Door(audit, claim, via)
