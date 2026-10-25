"""Requests in state ``proposed`` and their confirmation (spec v4 §3.4.2, HER-11, FR-CONV-2, FR-CONV-3, FR-CONV-6).

``tb.submit_request`` stores a typed intent here; the orchestrator, not the conversation engine, renders the exact
grammar lines (:func:`render_commands`) and the restatement. Nothing executes until the sender confirms with ``OK``
through deterministic intake (:meth:`RequestStore.confirm`): ``OK`` binds to one open, unchanged, unexpired proposal
of the same sender in the replied-to conversation. A new proposal in the same conversation supersedes the open one.

The table lives on the orchestrator's SQL backend (``orchestrator.db_pg``: PostgreSQL in production, SQLite in
tests), so a conversation survives a switch between the Hermes and native engines (FR-CONV-6).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from orchestrator.db_pg import SqlBackend, apply_schema, canonical_json, sha256_text
from tb_common.ulid import new_ulid
from tb_contracts.frontdoor import RequestState, RequestType

Clock = Callable[[], datetime]
PROPOSAL_TTL = timedelta(hours=72)

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_request (
  ticket_id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  study TEXT,
  params TEXT NOT NULL,
  commands TEXT NOT NULL,
  defaults TEXT NOT NULL,
  restatement TEXT NOT NULL,
  language TEXT NOT NULL,
  sender TEXT NOT NULL,
  channel TEXT NOT NULL,
  conv TEXT NOT NULL,
  msg TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  state TEXT NOT NULL,
  created TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  confirmed_at TEXT,
  job_id TEXT,
  refs TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversation_request_conv ON conversation_request (conv, sender, state)
"""

# site conventions applied when the intent leaves a parameter out (each default is listed in the restatement)
DEFAULTS: dict[RequestType, dict[str, str]] = {
    RequestType.FEAS: {"scope": "hospital", "lookback": "24m"},
    RequestType.SCREEN: {"cadence": "weekly"},
}
KEY_ORDER = ("scope", "lookback", "deadline", "cadence", "variant", "version")
# read-only requests are answered without a confirmation step (§3.4.2)
READ_ONLY = frozenset({RequestType.ASK})

_RESTATE: dict[str, dict[str, str]] = {
    "zh-TW": {
        "FEAS": "我理解為：為研究 {study} 做院內可行性評估，範圍 {scope}，回溯 {lookback}{deadline}。",
        "_generic": "我理解為：{type} 請求（研究 {study}）。",
        "_defaults": "預設值：{items}。",
        "_confirm": "請回覆「OK」確認，或修改上面的行後回覆。",
        "_deadline": "，期限 {deadline}",
    },
    "en": {
        "FEAS": "I understand: a site feasibility assessment for study {study}, scope {scope}, look-back {lookback}"
        "{deadline}.",
        "_generic": "I understand: a {type} request (study {study}).",
        "_defaults": "Defaults applied: {items}.",
        "_confirm": "Reply OK to confirm, or edit the line above and reply.",
        "_deadline": ", deadline {deadline}",
    },
    "ja": {
        "FEAS": "理解した内容：試験 {study} の院内実施可能性評価、範囲 {scope}、遡及期間 {lookback}{deadline}。",
        "_generic": "理解した内容：{type} リクエスト（試験 {study}）。",
        "_defaults": "既定値：{items}。",
        "_confirm": "「OK」と返信して確定するか、上の行を修正して返信してください。",
        "_deadline": "、期限 {deadline}",
    },
}
_RESTATE["mixed"] = _RESTATE["zh-TW"]


class ConfirmRefused(PermissionError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Proposal:
    ticket_id: str
    type: RequestType
    study: str | None
    params: dict[str, str]
    commands: list[str]
    defaults: list[str]
    restatement: str
    confirm_instruction: str
    language: str
    sender: str
    channel: str
    conv: str
    msg: str
    actor_type: str
    sha256: str
    state: RequestState
    created: datetime
    expires_at: datetime
    job_id: str | None = None


def _value(v: str | int) -> str:
    return str(v)


def render_commands(rtype: RequestType, study: str | None, params: Mapping[str, str]) -> list[str]:
    """The exact grammar line for a resolved intent (App. D). Rendered here, never by the engine (FR-CONV-2)."""
    keys = [k for k in KEY_ORDER if k in params] + sorted(k for k in params if k not in KEY_ORDER)
    parts = [rtype.value]
    if study:
        parts.append(study)
    parts += [f"{k}={params[k]}" for k in keys]
    return [" ".join(parts)]


def _restate(lang: str, rtype: RequestType, study: str | None, params: Mapping[str, str], defaults: list[str]) -> str:
    t = _RESTATE.get(lang, _RESTATE["en"])
    deadline = t["_deadline"].format(deadline=params["deadline"]) if params.get("deadline") else ""
    fields = {"study": study or "NEW", "type": rtype.value, "deadline": deadline}
    fields |= {k: params.get(k, "") for k in ("scope", "lookback")}
    text = t.get(rtype.value, t["_generic"]).format(**fields)
    if defaults:
        text += " " + t["_defaults"].format(items=", ".join(defaults))
    return text


def _row(r: tuple[Any, ...]) -> Proposal:
    lang = str(r[7])
    return Proposal(
        ticket_id=str(r[0]),
        type=RequestType(str(r[1])),
        study=r[2],
        params=dict(json.loads(r[3])),
        commands=list(json.loads(r[4])),
        defaults=list(json.loads(r[5])),
        restatement=str(r[6]),
        confirm_instruction=_RESTATE.get(lang, _RESTATE["en"])["_confirm"],
        language=lang,
        sender=str(r[8]),
        channel=str(r[9]),
        conv=str(r[10]),
        msg=str(r[11]),
        actor_type=str(r[12]),
        sha256=str(r[13]),
        state=RequestState(str(r[14])),
        created=datetime.fromisoformat(str(r[15])),
        expires_at=datetime.fromisoformat(str(r[16])),
        job_id=r[18],
    )


_COLS = (
    "ticket_id, type, study, params, commands, defaults, restatement, language, sender, channel, conv, msg,"
    " actor_type, sha256, state, created, expires_at, confirmed_at, job_id"
)


class RequestStore:
    def __init__(self, backend: SqlBackend, clock: Clock, id_factory: Callable[[], str] = new_ulid) -> None:
        self.backend = backend
        self.clock = clock
        self.id_factory = id_factory
        apply_schema(backend, SCHEMA)

    def propose(
        self,
        rtype: RequestType,
        study: str | None,
        params: Mapping[str, str | int],
        *,
        language: str,
        sender: str,
        channel: str,
        conv: str,
        msg: str,
        actor_type: str = "agent",
        refs: Mapping[str, str] | None = None,
    ) -> Proposal:
        """``refs`` maps relay tokens in ``params`` to the values the server resolved (D4, kept inside the
        orchestrator; never returned by a tool)."""
        now = self.clock()
        p = {k: _value(v) for k, v in params.items()}
        applied: list[str] = []
        for k, v in DEFAULTS.get(rtype, {}).items():
            if k not in p:
                p[k] = v
                applied.append(f"{k}={v}")
        commands = render_commands(rtype, study, p)
        restatement = _restate(language, rtype, study, p, applied)
        body = {"type": rtype.value, "study": study, "params": p, "commands": commands, "sender": sender, "conv": conv}
        digest = sha256_text(canonical_json(body))
        ticket = self.id_factory()
        state = RequestState.CONFIRMED if rtype in READ_ONLY else RequestState.PROPOSED
        with self.backend.transaction() as tx:
            tx.execute(
                "UPDATE conversation_request SET state = ? WHERE conv = ? AND sender = ? AND state = ?",
                (RequestState.SUPERSEDED.value, conv, sender, RequestState.PROPOSED.value),
            )
            tx.execute(
                f"INSERT INTO conversation_request ({_COLS}, refs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, NULL, NULL, ?)",
                (
                    ticket,
                    rtype.value,
                    study,
                    canonical_json(p),
                    json.dumps(commands, ensure_ascii=False),
                    json.dumps(applied, ensure_ascii=False),
                    restatement,
                    language,
                    sender,
                    channel,
                    conv,
                    msg,
                    actor_type,
                    digest,
                    state.value,
                    now.isoformat(),
                    (now + PROPOSAL_TTL).isoformat(),
                    canonical_json(dict(refs or {})),
                ),
            )
        got = self.get(ticket)
        assert got is not None
        return got

    def get(self, ticket_id: str) -> Proposal | None:
        with self.backend.transaction() as tx:
            r = tx.fetchone(f"SELECT {_COLS} FROM conversation_request WHERE ticket_id = ?", (ticket_id,))
        return _row(tuple(r)) if r is not None else None

    def for_sender(self, sender: str, study: str | None = None) -> list[Proposal]:
        sql = f"SELECT {_COLS} FROM conversation_request WHERE sender = ?"
        params: tuple[Any, ...] = (sender,)
        if study:
            sql += " AND study = ?"
            params += (study,)
        with self.backend.transaction() as tx:
            rows = tx.fetchall(sql + " ORDER BY created, ticket_id", params)
        return [_row(tuple(r)) for r in rows]

    def open_in(self, conv: str, sender: str) -> list[Proposal]:
        with self.backend.transaction() as tx:
            rows = tx.fetchall(
                f"SELECT {_COLS} FROM conversation_request WHERE conv = ? AND sender = ? AND state = ?"
                " ORDER BY created, ticket_id",
                (conv, sender, RequestState.PROPOSED.value),
            )
        return [_row(tuple(r)) for r in rows]

    def confirm(self, *, conv: str, sender: str, ticket_id: str | None = None) -> Proposal:
        """Deterministic ``OK`` (FR-CONV-3): exactly one open, unchanged, unexpired proposal of this sender here."""
        now = self.clock()
        cands = self.open_in(conv, sender)
        if ticket_id is not None:
            cands = [p for p in cands if p.ticket_id == ticket_id]
        if not cands:
            raise ConfirmRefused("no_open_proposal", "there is no open proposal from you in this conversation")
        if len(cands) > 1:
            raise ConfirmRefused("ambiguous", "more than one open proposal; reply to the one you mean")
        p = cands[0]
        if now > p.expires_at:
            with self.backend.transaction() as tx:
                tx.execute(
                    "UPDATE conversation_request SET state = ? WHERE ticket_id = ?",
                    (RequestState.EXPIRED.value, p.ticket_id),
                )
            raise ConfirmRefused("expired", "the proposal expired; send the request again")
        body = {
            "type": p.type.value,
            "study": p.study,
            "params": p.params,
            "commands": p.commands,
            "sender": p.sender,
            "conv": p.conv,
        }
        if sha256_text(canonical_json(body)) != p.sha256:
            raise ConfirmRefused("changed", "the proposal changed after it was sent")
        with self.backend.transaction() as tx:
            n = tx.execute(
                "UPDATE conversation_request SET state = ?, confirmed_at = ? WHERE ticket_id = ? AND state = ?",
                (RequestState.CONFIRMED.value, now.isoformat(), p.ticket_id, RequestState.PROPOSED.value),
            )
        if n != 1:
            raise ConfirmRefused("no_open_proposal", "the proposal is no longer open")
        got = self.get(p.ticket_id)
        assert got is not None
        return got

    def refs(self, ticket_id: str) -> dict[str, str]:
        """Resolved token values for the orchestrator's workflow start (inside the perimeter only)."""
        with self.backend.transaction() as tx:
            r = tx.fetchone("SELECT refs FROM conversation_request WHERE ticket_id = ?", (ticket_id,))
        return dict(json.loads(r[0])) if r is not None else {}

    def attach_job(self, ticket_id: str, job_id: str) -> None:
        with self.backend.transaction() as tx:
            tx.execute("UPDATE conversation_request SET job_id = ? WHERE ticket_id = ?", (job_id, ticket_id))
