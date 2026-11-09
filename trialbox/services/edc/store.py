"""Schema ``edc`` of the trial database (D-160): the prefill switch, the item map, drafts and their fate, decisions,
electronic signatures and what was sent.

* ``switch``: per study, prefill **off by default**. It goes on only with the sponsor's written acknowledgement on
  file (or, for an investigator-initiated study, the PI as sponsor) and the site's blind re-entry result at or above
  the threshold (TB-PLAN-05 WS-07.7, WS-16.4). Every change is kept in ``switch_event``.
* ``item_map`` and ``target``: the study's map (``edc.mapping``) and the REDCap project it sends to; ``map_event``
  keeps every version of the map.
* ``draft``: one row per drafted item, never deleted. Its *fate*: ``open``, ``confirmed``, ``edited``, ``rejected``
  or ``superseded`` (a newer draft run replaced an open one). ``final`` is the value a person decided.
* ``decision``: append-only, one row per action (old value, new value, reason, who, when).
* ``signature``: the electronic signature: printed name, role, meaning, time, and a hash over what was signed. Each
  signed draft keeps its own ``signed_sha``; a value that changed after signing no longer matches and is never sent.
* ``sent``: append-only, every value sent or refused, with the target and the REDCap record.

Rules here, not only on the page: a draft without a citation cannot be confirmed; an edit needs a reason and a
citation (the draft's, or one the person gives); a value is sendable only when confirmed, signed and unchanged since.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from tb_common.db import ENV, Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS switch (study TEXT PRIMARY KEY, state TEXT NOT NULL, kind TEXT NOT NULL DEFAULT '',
  reference TEXT NOT NULL DEFAULT '', ack_date TEXT NOT NULL DEFAULT '', reentry_pages INTEGER NOT NULL DEFAULT 0,
  reentry_accuracy DOUBLE PRECISION NOT NULL DEFAULT 0, by_user TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS switch_event (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  state TEXT NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL, ack_date TEXT NOT NULL,
  reentry_pages INTEGER NOT NULL, reentry_accuracy DOUBLE PRECISION NOT NULL, reason TEXT NOT NULL DEFAULT '',
  by_user TEXT NOT NULL, role TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS item_map (study TEXT NOT NULL, item TEXT NOT NULL, seq INTEGER NOT NULL,
  body TEXT NOT NULL, PRIMARY KEY (study, item));
CREATE TABLE IF NOT EXISTS map_event (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  body TEXT NOT NULL, by_user TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS target (study TEXT PRIMARY KEY, token_ref TEXT NOT NULL, key_field TEXT NOT NULL,
  id_field TEXT NOT NULL, by_user TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS draft (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  record TEXT NOT NULL, pid TEXT NOT NULL, visit TEXT NOT NULL, visit_date TEXT NOT NULL, item TEXT NOT NULL,
  form TEXT NOT NULL, cdash TEXT NOT NULL, test TEXT NOT NULL, value TEXT NOT NULL, state TEXT NOT NULL,
  why TEXT NOT NULL, citation TEXT, version TEXT NOT NULL, run_id TEXT NOT NULL, built_by TEXT NOT NULL,
  built_at TEXT NOT NULL, fate TEXT NOT NULL DEFAULT 'open', final TEXT, final_citation TEXT, reason TEXT,
  decided_by TEXT, decided_at TEXT, signature_id BIGINT, signed_sha TEXT, sent_value TEXT, sent_at TEXT);
CREATE INDEX IF NOT EXISTS draft_rec ON draft (study, record, visit);
CREATE TABLE IF NOT EXISTS decision (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, draft_id BIGINT NOT NULL,
  study TEXT NOT NULL, record TEXT NOT NULL, visit TEXT NOT NULL, item TEXT NOT NULL, action TEXT NOT NULL,
  old TEXT, new TEXT, reason TEXT NOT NULL DEFAULT '', citation TEXT, by_user TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signature (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  record TEXT NOT NULL, visit TEXT NOT NULL, signer TEXT NOT NULL, printed_name TEXT NOT NULL, role TEXT NOT NULL,
  meaning TEXT NOT NULL, meaning_text TEXT NOT NULL, lang TEXT NOT NULL, method TEXT NOT NULL, at TEXT NOT NULL,
  content_sha TEXT NOT NULL, drafts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sent (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  record TEXT NOT NULL, visit TEXT NOT NULL, item TEXT NOT NULL, draft_id BIGINT NOT NULL, value TEXT NOT NULL,
  target TEXT NOT NULL, target_record TEXT NOT NULL DEFAULT '', result TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
  by_user TEXT NOT NULL, at TEXT NOT NULL)
"""
FATES = ("open", "confirmed", "edited", "rejected", "superseded")
DECIDED = ("confirmed", "edited")
ACTIONS = ("confirm", "edit", "reject")
ACK_KINDS = ("sponsor_letter", "iit_pi_sponsor")
REENTRY_PAGES = 30  # WS-16.4: 30 real CRF pages double-entered blind against the drafts
REENTRY_ACCURACY = 0.98  # post-confirmation field accuracy before prefill is enabled for the study
MEANINGS = ("transcribed",)  # the one meaning of a CRC's signature in v1 (D-160)


class EdcError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Switch:
    study: str
    state: str = "off"
    kind: str = ""
    reference: str = ""
    ack_date: str = ""
    reentry_pages: int = 0
    reentry_accuracy: float = 0.0
    by: str = ""
    at: str = ""

    @property
    def on(self) -> bool:
        return self.state == "on"

    def as_dict(self) -> dict[str, Any]:
        return {"study": self.study, "state": self.state, "kind": self.kind, "reference": self.reference,
                "ack_date": self.ack_date, "reentry_pages": self.reentry_pages,
                "reentry_accuracy": self.reentry_accuracy, "by": self.by, "at": self.at}  # fmt: skip


def draft_sha(d: dict[str, Any]) -> str:
    """What a signature covers for one value: the draft, the subject (record and pseudonym), the item, the decided
    value and its citation."""
    body = {"id": int(d["id"]), "study": d["study"], "record": d["record"], "pid": d["pid"], "visit": d["visit"],
            "item": d["item"], "final": d["final"], "citation": d["final_citation"]}  # fmt: skip
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _cit(raw: Any) -> dict[str, Any] | None:
    if raw in (None, ""):
        return None
    return dict(json.loads(raw)) if isinstance(raw, str) else dict(raw)


class EdcStore:
    def __init__(self, url: str | None = None) -> None:
        self._db = Database.connect(url or os.environ.get(ENV), "edc")
        self._db.migrate([SCHEMA])

    @property
    def db(self) -> Database:
        return self._db

    def close(self) -> None:
        self._db.close()

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return self._db.fetchdicts(sql, args)

    # ------------------------------------------------------------------ the switch (sponsor acknowledgement)
    def switch(self, study: str) -> Switch:
        rows = self._all("SELECT * FROM switch WHERE study = ?", (study,))
        if not rows:
            return Switch(study)
        r = rows[0]
        return Switch(study, r["state"], r["kind"], r["reference"], r["ack_date"], int(r["reentry_pages"]),
                      float(r["reentry_accuracy"]), r["by_user"], r["at"])  # fmt: skip

    def set_switch(self, study: str, on: bool, *, kind: str = "", reference: str = "", ack_date: str = "",
                   reentry_pages: int = 0, reentry_accuracy: float = 0.0, reason: str = "", by: str, role: str,
                   at: str, today: date) -> Switch:  # fmt: skip
        """Turn prefill on (every condition checked here) or off (always allowed). Kept in ``switch_event``."""
        if on:
            if kind not in ACK_KINDS:
                raise EdcError("edc.ack_kind", "say how the sponsor acknowledged (letter, or the PI is the sponsor)")
            if not reference.strip():
                raise EdcError("edc.ack_reference", "the acknowledgement's reference (letter number or file) is needed")
            try:
                ack = date.fromisoformat(ack_date)
            except ValueError as exc:
                raise EdcError("edc.ack_date", "the acknowledgement's date is needed") from exc
            if ack > today:
                raise EdcError("edc.ack_date", "the acknowledgement's date is in the future")
            if reentry_pages < REENTRY_PAGES or reentry_accuracy < REENTRY_ACCURACY:
                raise EdcError("edc.reentry", f"the blind re-entry needs at least {REENTRY_PAGES} pages at "
                                              f"{REENTRY_ACCURACY:.0%} or better")  # fmt: skip
        state = "on" if on else "off"
        cur = self.switch(study)
        if not on:  # off keeps the acknowledgement on record; only the state changes
            kind, reference, ack_date = cur.kind, cur.reference, cur.ack_date
            reentry_pages, reentry_accuracy = cur.reentry_pages, cur.reentry_accuracy
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO switch (study, state, kind, reference, ack_date, reentry_pages, reentry_accuracy, "
                       "by_user, at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(study) DO UPDATE SET "
                       "state = excluded.state, "
                       "kind = excluded.kind, reference = excluded.reference, ack_date = excluded.ack_date, "
                       "reentry_pages = excluded.reentry_pages, reentry_accuracy = excluded.reentry_accuracy, "
                       "by_user = excluded.by_user, at = excluded.at",
                       (study, state, kind, reference.strip()[:120], ack_date, int(reentry_pages),
                        float(reentry_accuracy), by, at))  # fmt: skip
            tx.execute("INSERT INTO switch_event (study, state, kind, reference, ack_date, reentry_pages, "
                       "reentry_accuracy, reason, by_user, role, at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (study, state, kind, reference.strip()[:120], ack_date, int(reentry_pages),
                        float(reentry_accuracy), reason[:300], by, role, at))  # fmt: skip
        return self.switch(study)

    def switch_events(self, study: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM switch_event WHERE study = ? ORDER BY id", (study,))

    def require_on(self, study: str) -> None:
        if not self.switch(study).on:
            raise EdcError("edc.off", "prefill is off for this study (no sponsor acknowledgement on file)")

    # ------------------------------------------------------------------ the map and the target
    def put_map(self, study: str, items: list[dict[str, Any]], by: str, at: str) -> None:
        with self._db.transaction() as tx:
            tx.execute("DELETE FROM item_map WHERE study = ?", (study,))
            for i, it in enumerate(items):
                tx.execute("INSERT INTO item_map (study, item, seq, body) VALUES (?,?,?,?)",
                           (study, it["item"], i, json.dumps(it, ensure_ascii=False, sort_keys=True)))  # fmt: skip
            tx.execute("INSERT INTO map_event (study, body, by_user, at) VALUES (?,?,?,?)",
                       (study, json.dumps(items, ensure_ascii=False, sort_keys=True), by, at))  # fmt: skip

    def map(self, study: str) -> list[dict[str, Any]]:
        return [json.loads(r["body"]) for r in self._all("SELECT body FROM item_map WHERE study = ? ORDER BY seq",
                                                         (study,))]  # fmt: skip

    def map_events(self, study: str) -> list[dict[str, Any]]:
        return self._all("SELECT id, by_user, at FROM map_event WHERE study = ? ORDER BY id", (study,))

    def put_target(self, study: str, token_ref: str, key_field: str, id_field: str, by: str, at: str) -> None:
        self._db.execute("INSERT INTO target (study, token_ref, key_field, id_field, by_user, at) VALUES "
                         "(?,?,?,?,?,?) ON CONFLICT(study) DO UPDATE SET token_ref = excluded.token_ref, "
                         "key_field = excluded.key_field, id_field = excluded.id_field, by_user = excluded.by_user, "
                         "at = excluded.at", (study, token_ref, key_field, id_field, by, at))  # fmt: skip

    def target(self, study: str) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM target WHERE study = ?", (study,))
        return rows[0] if rows else None

    # ------------------------------------------------------------------ drafts
    def add_drafts(self, study: str, record: str, pid: str, visit: str, visit_date: str, drafts: list[dict[str, Any]],
                   run_id: str, by: str, at: str) -> list[int]:  # fmt: skip
        """A new draft run: open and rejected drafts of the same subject and visit are superseded, so each item has
        one current draft; an item a person already confirmed or edited keeps its decision and gets no new draft.
        A record key stays bound to the one subject it was first drafted for (D-162, review E-02)."""
        ids: list[int] = []
        with self._db.transaction() as tx:
            other = tx.fetchval("SELECT pid FROM draft WHERE study = ? AND record = ? AND pid <> ? LIMIT 1",
                                (study, record, pid))  # fmt: skip
            if other is not None:
                raise EdcError("edc.pid_mismatch", "this record key was drafted for another subject")
            decided = {r["item"] for r in tx.fetchdicts(
                "SELECT item FROM draft WHERE study = ? AND record = ? AND visit = ? "
                "AND fate IN ('confirmed', 'edited')",
                (study, record, visit))}  # fmt: skip
            tx.execute("UPDATE draft SET fate = 'superseded' WHERE study = ? AND record = ? AND visit = ? AND "
                       "fate IN ('open', 'rejected')", (study, record, visit))  # fmt: skip
            for d in drafts:
                if d["item"] in decided:
                    continue
                ids.append(int(tx.fetchval(
                    "INSERT INTO draft (study, record, pid, visit, visit_date, item, form, cdash, test, value, state, "
                    "why, citation, version, run_id, built_by, built_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "RETURNING id",
                    (study, record, pid, visit, visit_date, d["item"], d["form"], d["cdash"], d["test"], d["value"],
                     d["state"], d["why"], json.dumps(d["citation"], ensure_ascii=False) if d["citation"] else None,
                     d["version"], run_id, by, at))))  # fmt: skip
        return ids

    def _row(self, r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        r["citation"] = _cit(r.get("citation"))
        r["final_citation"] = _cit(r.get("final_citation"))
        r["sha"] = draft_sha(r) if r.get("fate") in DECIDED else ""  # what a signature would cover now
        return r

    def draft(self, study: str, draft_id: int) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM draft WHERE study = ? AND id = ?", (study, draft_id))
        return self._row(rows[0]) if rows else None

    def drafts(self, study: str, record: str | None = None, visit: str | None = None,
               current: bool = True) -> list[dict[str, Any]]:  # fmt: skip
        """The study's drafts (``current``: without superseded ones), by subject, visit and map order."""
        sql = "SELECT * FROM draft WHERE study = ?"
        args: list[Any] = [study]
        if record is not None:
            sql += " AND record = ?"
            args.append(record)
        if visit is not None:
            sql += " AND visit = ?"
            args.append(visit)
        if current:
            sql += " AND fate <> 'superseded'"
        return [self._row(r) for r in self._all(sql + " ORDER BY record, visit, id", tuple(args))]

    def subjects(self, study: str) -> list[dict[str, Any]]:
        """Per subject and visit: how many drafts are open, decided, signed and sent."""
        return self._all(
            "SELECT record, visit, max(visit_date) AS visit_date, "
            "sum(CASE WHEN fate = 'open' THEN 1 ELSE 0 END) AS open, "
            "sum(CASE WHEN fate IN ('confirmed', 'edited') THEN 1 ELSE 0 END) AS decided, "
            "sum(CASE WHEN fate IN ('confirmed', 'edited') AND signature_id IS NOT NULL THEN 1 ELSE 0 END) AS signed, "
            "sum(CASE WHEN sent_at IS NOT NULL AND sent_value = final THEN 1 ELSE 0 END) AS sent "
            "FROM draft WHERE study = ? AND fate <> 'superseded' GROUP BY record, visit ORDER BY record, visit",
            (study,),
        )

    def decide(self, study: str, draft_id: int, action: str, *, value: str = "", reason: str = "",
               citation: dict[str, Any] | None = None, by: str, at: str) -> dict[str, Any]:  # fmt: skip
        """Confirm, edit (with a reason) or reject one draft. The value's check against the field is the caller's
        (it knows the dictionary); the rules on citations, reasons and order are here."""
        if action not in ACTIONS:
            raise EdcError("edc.action", "confirm, edit or reject", 400)
        with self._db.transaction() as tx:
            rows = tx.fetchdicts("SELECT * FROM draft WHERE study = ? AND id = ? FOR UPDATE", (study, draft_id))
            if not rows:
                raise EdcError("edc.no_draft", "no such draft", 404)
            d = self._row(rows[0])
            if d["fate"] == "superseded":
                raise EdcError("edc.superseded", "a newer draft replaced this one; open the subject again")
            old = d["final"] if d["fate"] in DECIDED else None
            cite = d["citation"]
            if action == "confirm":
                if d["fate"] in DECIDED:
                    raise EdcError("edc.decided", "already decided; change it with a reason instead")
                if d["state"] != "drafted" or not d["value"] or not cite:
                    raise EdcError("edc.no_citation", "a value without a citation cannot be confirmed")
                fate, final, final_cite = "confirmed", d["value"], cite
            elif action == "edit":
                if not reason.strip():
                    raise EdcError("edc.reason", "say why the value is changed", 400)
                if not value.strip():
                    raise EdcError("edc.value", "type the value", 400)
                final_cite = cite
                if citation and str(citation.get("text") or "").strip():
                    final_cite = {"kind": "manual", "text": str(citation["text"]).strip()[:300],
                                  "day": str(citation.get("day") or "")[:10], "by": by,
                                  **({"replaces": cite} if cite else {})}  # fmt: skip
                elif value.strip() != (d["value"] or ""):
                    # a changed value never keeps the machine's citation of the old one (review E-08)
                    raise EdcError("edc.edit_source", "a changed value needs its own source: say where it comes from",
                                   400)  # fmt: skip
                if not final_cite:
                    raise EdcError("edc.no_citation", "a value without a citation cannot be confirmed: name the source")
                if d["fate"] in DECIDED and final_cite == d["final_citation"] and value.strip() == d["final"]:
                    raise EdcError("edc.same", "the value and its source are unchanged")  # compared by value (E-28)
                fate, final = "edited", value.strip()
            else:  # reject
                if d["sent_at"]:
                    raise EdcError("edc.sent", "a sent value is changed with a reason, not rejected")
                if d["fate"] in DECIDED and not reason.strip():
                    raise EdcError("edc.reason", "say why a decided value is withdrawn", 400)
                fate, final, final_cite = "rejected", None, None
            if d["signature_id"] is not None:  # the change withdraws the signature over this value: keep that visible
                tx.execute("INSERT INTO decision (draft_id, study, record, visit, item, action, old, new, reason, "
                           "citation, by_user, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (draft_id, study, d["record"], d["visit"], d["item"], "signature_void", old, old,
                            f"signature {d['signature_id']} no longer covers this value", None, by, at))  # fmt: skip
            tx.execute("UPDATE draft SET fate = ?, final = ?, final_citation = ?, reason = ?, decided_by = ?, "
                       "decided_at = ?, signature_id = NULL, signed_sha = NULL WHERE id = ?",
                       (fate, final, json.dumps(final_cite, ensure_ascii=False) if final_cite else None,
                        reason.strip()[:300], by, at, draft_id))  # fmt: skip
            tx.execute("INSERT INTO decision (draft_id, study, record, visit, item, action, old, new, reason, "
                       "citation, "
                       "by_user, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (draft_id, study, d["record"], d["visit"], d["item"], action, old, final, reason.strip()[:300],
                        json.dumps(final_cite, ensure_ascii=False) if final_cite else None, by, at))  # fmt: skip
        out = self.draft(study, draft_id)
        assert out is not None
        return out

    # ------------------------------------------------------------------ signature
    def sign(self, study: str, record: str, visit: str, *, signer: str, printed_name: str, role: str, meaning: str,
             meaning_text: str, lang: str, at: str, seen: dict[int, str]) -> dict[str, Any]:  # fmt: skip
        """Sign the decided, unsigned values of one subject and visit. The caller has re-authenticated the signer.
        ``seen`` is what the signer's screen showed (draft id -> hash); the set and every hash must still be what is
        in the database now, or nothing is signed (review E-11)."""
        if meaning not in MEANINGS:
            raise EdcError("edc.meaning", "unknown signature meaning", 400)
        with self._db.transaction() as tx:
            rows = [self._row(r) for r in tx.fetchdicts(
                "SELECT * FROM draft WHERE study = ? AND record = ? AND visit = ? AND fate IN ('confirmed', 'edited') "
                "AND signature_id IS NULL ORDER BY id FOR UPDATE", (study, record, visit))]  # fmt: skip
            if not rows:
                raise EdcError("edc.nothing_to_sign", "no confirmed value waits for a signature")
            shas = {int(r["id"]): draft_sha(r) for r in rows}
            if {int(k): str(v) for k, v in seen.items()} != shas:
                raise EdcError("edc.sign_changed", "the values changed since the page was shown; open it again")
            content = hashlib.sha256(json.dumps(sorted(shas.items())).encode()).hexdigest()
            sid = int(tx.fetchval(
                "INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, "
                "method, at, content_sha, drafts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, "password", at,
                 content, json.dumps({str(k): v for k, v in sorted(shas.items())}))))  # fmt: skip
            for did, sha in shas.items():
                tx.execute("UPDATE draft SET signature_id = ?, signed_sha = ? WHERE id = ?", (sid, sha, did))
        sig = self.signature(sid)
        assert sig is not None
        return sig

    def signature(self, sid: int) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM signature WHERE id = ?", (sid,))
        return rows[0] if rows else None

    def signatures(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        if record is None:
            return self._all("SELECT * FROM signature WHERE study = ? ORDER BY id", (study,))
        return self._all("SELECT * FROM signature WHERE study = ? AND record = ? ORDER BY id", (study, record))

    # ------------------------------------------------------------------ what may be sent, and what was
    def _current(self, study: str, record: str | None = None, visit: str | None = None) -> list[dict[str, Any]]:
        """The current drafts; more than one for an item of a subject and visit is a broken store: refuse."""
        rows = self.drafts(study, record, visit)
        keys = [(d["record"], d["visit"], d["item"]) for d in rows]
        if len(keys) != len(set(keys)):
            raise EdcError("edc.duplicate", "an item has more than one current draft; nothing is sent or exported")
        return rows

    def sendable(self, study: str, record: str | None = None, visit: str | None = None) -> list[dict[str, Any]]:
        """Decided, signed values whose content still matches the signature and that are not sent as they are."""
        out = []
        for d in self._current(study, record, visit):
            if d["fate"] not in DECIDED or d["signature_id"] is None or not d["final"]:
                continue
            if d["signed_sha"] != draft_sha(d):
                continue  # changed after signing (or tampered with): never sent
            if d["sent_at"] and d["sent_value"] == d["final"]:
                continue
            out.append(d)
        return out

    def signed(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        """Decided, signed values whose content still matches the signature (the ODM export)."""
        return [d for d in self._current(study, record) if d["fate"] in DECIDED and d["signature_id"] is not None
                and d["final"] and d["signed_sha"] == draft_sha(d)]  # fmt: skip

    def record_sent(self, study: str, d: dict[str, Any], target: str, target_record: str, result: str, detail: str,
                    by: str, at: str) -> None:  # fmt: skip
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO sent (study, record, visit, item, draft_id, value, target, target_record, result, "
                       "detail, by_user, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (study, d["record"], d["visit"], d["item"], int(d["id"]), d["final"] or "", target,
                        target_record, result, detail[:300], by, at))  # fmt: skip
            if result in ("sent", "already_there"):
                tx.execute("UPDATE draft SET sent_value = ?, sent_at = ? WHERE id = ?", (d["final"], at, int(d["id"])))

    def sent_rows(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        if record is None:
            return self._all("SELECT * FROM sent WHERE study = ? ORDER BY id", (study,))
        return self._all("SELECT * FROM sent WHERE study = ? AND record = ? ORDER BY id", (study, record))

    def last_sent(self, study: str, record: str, visit: str, item: str) -> str | None:
        """The value TrialBox last wrote to the EDC for this item (None: never written)."""
        rows = self._all("SELECT value FROM sent WHERE study = ? AND record = ? AND visit = ? AND item = ? AND "
                         "target = 'redcap' AND result IN ('sent', 'already_there') ORDER BY id DESC LIMIT 1",
                         (study, record, visit, item))  # fmt: skip
        return str(rows[0]["value"]) if rows else None

    # ------------------------------------------------------------------ the per-record trail
    def trail(self, study: str, record: str) -> dict[str, Any]:
        return {
            "drafts": self._all("SELECT id, visit, item, value, state, why, fate, final, built_by, built_at, version, "
                                "run_id FROM draft WHERE study = ? AND record = ? ORDER BY id", (study, record)),
            "decisions": self._all("SELECT * FROM decision WHERE study = ? AND record = ? ORDER BY id",
                                   (study, record)),
            "signatures": self.signatures(study, record),
            "sent": self.sent_rows(study, record),
        }  # fmt: skip
