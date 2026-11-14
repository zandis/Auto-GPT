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
* ``signature``: the electronic signature: printed name, role, meaning, time, method, and a keyed hash
  (``content_sha``, D-281) over the whole act: who signed, as what, with which meaning, when, how, and every value's
  hash. Each signed draft keeps its own ``signed_sha``; a value that changed after signing, or whose signature row no
  longer verifies, is never sent or exported.
* ``signature_void``: append-only, one row per signed value that a person changed or withdrew after signing (D-281).
* ``sent``: append-only, every value sent or refused, with the target and the REDCap record.

The trail tables (``decision``, ``signature``, ``signature_void``, ``sent``, ``switch_event``, ``map_event``) refuse
UPDATE, DELETE and TRUNCATE by trigger (D-281). A signed value is locked: it changes only with a reason, right after
the person typed their password (and code) again (D-281, CR-035).

Rules here, not only on the page: a draft without a citation cannot be confirmed; an edit needs a reason and a
citation (the draft's, or one the person gives); a value is sendable only when confirmed, signed and unchanged since.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from datacore import pgfunc
from tb_common.config import environment_name
from tb_common.crypto import key_fingerprint
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
# D-281: the signature's version (1: the old unkeyed hash over the value hashes; 2: the keyed hash over the whole act),
# the fingerprint of the key that made it, and the record of each signed value changed or withdrawn after signing
SCHEMA_V2 = """
ALTER TABLE signature ADD COLUMN IF NOT EXISTS sig_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE signature ADD COLUMN IF NOT EXISTS key_id TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS signature_void (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  signature_id BIGINT NOT NULL, study TEXT NOT NULL, record TEXT NOT NULL, visit TEXT NOT NULL,
  draft_id BIGINT NOT NULL, item TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, by_user TEXT NOT NULL,
  at TEXT NOT NULL)
"""
# T-115 (D-368): what each draft was built under (the item's map row, its dictionary entry, the REDCap target), all
# three in what a signature covers (E-15, E-16); the stored blind re-entry result the switch reads (E-14)
SCHEMA_V3 = """
ALTER TABLE draft ADD COLUMN IF NOT EXISTS map_sha TEXT NOT NULL DEFAULT '';
ALTER TABLE draft ADD COLUMN IF NOT EXISTS dict_sha TEXT NOT NULL DEFAULT '';
ALTER TABLE draft ADD COLUMN IF NOT EXISTS target TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS reentry_record (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  pages INTEGER NOT NULL, accuracy DOUBLE PRECISION NOT NULL, document TEXT NOT NULL, source TEXT NOT NULL,
  by_user TEXT NOT NULL, at TEXT NOT NULL);
ALTER TABLE switch ADD COLUMN IF NOT EXISTS reentry_id BIGINT NOT NULL DEFAULT 0;
ALTER TABLE switch_event ADD COLUMN IF NOT EXISTS reentry_id BIGINT NOT NULL DEFAULT 0
"""
# T-302c (D-434): copy-assist, a person's "copied" tick on a signed value (or its undo, with a reason), bound to the
# hash of the value as it was signed
SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS copy_tick (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  record TEXT NOT NULL, visit TEXT NOT NULL, item TEXT NOT NULL, draft_id BIGINT NOT NULL, signed_sha TEXT NOT NULL,
  action TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', by_user TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS copy_tick_rec ON copy_tick (study, record)
"""
# T-720 (D-461): version 1 (the unkeyed hash) is refused; a row inserted without a version is checked by the keyed
# rule, and a new row must say version 2 (NOT VALID: an existing version-1 row stays, covering nothing)
SCHEMA_V5 = """
ALTER TABLE signature ALTER COLUMN sig_version SET DEFAULT 2;
ALTER TABLE signature DROP CONSTRAINT IF EXISTS signature_v2_only;
ALTER TABLE signature ADD CONSTRAINT signature_v2_only CHECK (sig_version = 2) NOT VALID
"""
MIGRATIONS = (SCHEMA, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5)
#: tables that only ever grow (D-281): a trigger refuses UPDATE, DELETE and TRUNCATE on each
APPEND_ONLY = ("decision", "signature", "signature_void", "sent", "switch_event", "map_event", "reentry_record",
               "copy_tick")  # fmt: skip
REENTRY_SOURCES = ("admin", "pq")  # who wrote the record: an administrator with the filed report, or the PQ tooling
SIG_VERSION = 2
METHODS = ("password", "password+totp", "oidc+mfa")  # how the signer re-authenticated (D-279; T-205: at the directory)
KEY_ENV = "TB_EDC_SIGN_KEY_FILE"
KEY_FILE = "edc_sign.key"  # in the orchestrator's secrets folder when TB_EDC_SIGN_KEY_FILE is not set
_DEV_KEY = b"trialbox DEV/TEST EDC signature key, never on a box"
FATES = ("open", "confirmed", "edited", "rejected", "superseded")
DECIDED = ("confirmed", "edited")
ACTIONS = ("confirm", "edit", "reject")
ACK_KINDS = ("sponsor_letter", "iit_pi_sponsor")
REENTRY_PAGES = 30  # WS-16.4: 30 real CRF pages double-entered blind against the drafts
REENTRY_ACCURACY = 0.98  # post-confirmation field accuracy before prefill is enabled for the study
TICKS = ("copied", "undone")  # copy-assist (D-434): a value typed into the sponsor's EDC by hand, or that tick undone
STATES = ("off", "on", "copy")  # D-434: ``copy`` drafts, reviews and signs, but never writes to the sponsor's EDC
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
    reentry_id: int = 0  # the stored re-entry record the switch went on with (E-14); 0: typed (DEV or TEST only)

    @property
    def on(self) -> bool:
        """Prefill to the sponsor's EDC (the REDCap send, its preview, the ODM export): acknowledgement on file."""
        return self.state == "on"

    @property
    def drafting(self) -> bool:
        """Drafts, the ODM import, review and signatures: prefill on, or copy-assist (D-434)."""
        return self.state in ("on", "copy")

    def as_dict(self) -> dict[str, Any]:
        return {"study": self.study, "state": self.state, "kind": self.kind, "reference": self.reference,
                "ack_date": self.ack_date, "reentry_pages": self.reentry_pages,
                "reentry_accuracy": self.reentry_accuracy, "by": self.by, "at": self.at,
                "reentry_id": self.reentry_id}  # fmt: skip


#: what a draft was built under (T-115, E-15, E-16): in the value's hash when set, so a draft from before keeps its
#: hash and its signature
BUILT_UNDER = ("map_sha", "dict_sha", "target")


def draft_sha(d: dict[str, Any]) -> str:
    """What a signature covers for one value: the draft, the subject (record and pseudonym), the item, the decided
    value and its citation; and the item's map row, its dictionary entry and the REDCap target it was built for
    (E-15, E-16)."""
    body = {"id": int(d["id"]), "study": d["study"], "record": d["record"], "pid": d["pid"], "visit": d["visit"],
            "item": d["item"], "final": d["final"], "citation": d["final_citation"]}  # fmt: skip
    body.update({k: str(d[k]) for k in BUILT_UNDER if d.get(k)})
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _open_sign_key(path: Path, env: Mapping[str, str]) -> bytes:
    """T-210d: the key of ``path``, opened under the KEK when ``<path>.wrapped`` is there (``tb_common.kek``), else
    read plain. Made when absent in either form (32 random bytes): wrapped when the folder has a KEK; plain only
    outside VALIDATION and PRODUCTION. A wrapped key that cannot be opened (the KEK not unsealed, another box's KEK,
    a damaged file, a plain copy beside it) is refused in every environment: no key is made in its place."""
    from tb_common import kek as K
    from tb_common.crypto import KeyMissingError

    def refuse(why: str) -> EdcError:
        return EdcError("edc.sign_key", f"the signature key {path}: {why}", 500)

    try:
        try:
            return K.load_key_file(path, env)
        except KeyMissingError:
            if K.key_present(path):
                raise refuse("the file is empty; put the key back from the backup") from None
        if K.read_meta(path.parent) is None and environment_name(env) in K.STRICT_ENVS:
            raise refuse(f"{path.parent} has no KEK: in {environment_name(env)} this key is made only wrapped under "
                         "it (`python -m tools.keys init`)")  # fmt: skip
        K.create_key_file(path, 32, env)
        return K.load_key_file(path, env)
    except K.KekError as exc:
        raise refuse(f"cannot be opened ({exc})") from None


def sign_key_of(env: Mapping[str, str], secrets_dir: Path | None = None) -> bytes:
    """The key of the signature binding (D-281): the file ``TB_EDC_SIGN_KEY_FILE``, else ``edc_sign.key`` in the
    secrets folder, wrapped under the KEK of its folder (T-210d) or plain, and made when absent
    (:func:`_open_sign_key`). Without either, a fixed key on a DEV or TEST box only; anywhere else this refuses. A
    lost key is not silent: the old signatures stop verifying and their values are not sent until signed again."""
    named = (env.get(KEY_ENV) or "").strip()
    path = Path(named) if named else (secrets_dir / KEY_FILE if secrets_dir is not None else None)
    if path is not None:
        key = _open_sign_key(path, env)
        if len(key) < 16:
            raise EdcError("edc.sign_key", f"the signature key file {path} is shorter than 16 bytes", 500)
        return key
    if environment_name(env) in ("DEV", "TEST"):
        return _DEV_KEY
    raise EdcError("edc.sign_key", f"{KEY_ENV} is not set and no secrets folder is given", 500)


def signature_sha(key: bytes, s: Mapping[str, Any], shas: Mapping[int, str]) -> str:
    """What ``content_sha`` covers (version 2, D-281, CR-036): the study, subject and visit; who signed, their printed
    name and role; the meaning and its words in the signer's language; how they re-authenticated; when; and every
    value's hash. HMAC-SHA256 with the orchestrator's key, so a database writer without the key cannot re-make it."""
    keys = (
        "study",
        "record",
        "visit",
        "signer",
        "printed_name",
        "role",
        "meaning",
        "meaning_text",
        "lang",
        "method",
        "at",
    )
    body: dict[str, Any] = {k: str(s[k]) for k in keys}
    body["values"] = [[int(k), str(v)] for k, v in sorted((int(k), str(v)) for k, v in shas.items())]
    msg = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(key, b"trialbox edc signature v2\x00" + msg, hashlib.sha256).hexdigest()


def _cit(raw: Any) -> dict[str, Any] | None:
    if raw in (None, ""):
        return None
    return dict(json.loads(raw)) if isinstance(raw, str) else dict(raw)


def prepare(db: Database) -> int:
    """The schema as this release needs it; the version. Whoever owns the schema makes it: the versions, then the
    trail triggers. D-486 (T-718): on a box the owner is ``tbo_edc`` and only the install step is it
    (:func:`install`); the orchestrator's role is a writer, so here it checks the versions and that every trail
    trigger is in place, and refuses a schema that lacks one. It can make none and drop none."""
    version = db.migrate(list(MIGRATIONS))
    owner = db.owner_role()
    if owner is None:
        _append_only(db)
        return version
    missing = sorted(set(_trail_triggers()) - _triggers(db))
    if missing:
        raise EdcError(
            "edc.schema", f"the trail triggers {missing} are missing: {owner} makes them; run `trialbox migrate`", 500
        )
    return version


def install(url: str | None = None) -> int:
    """The install step for this schema (``python -m orchestrator.migrate``, as the box's admin): the versions, the
    trail triggers and the writer's rights. Needs no signature key."""
    with Database.connect(url or os.environ.get(ENV), "edc") as db:
        db.adopt()  # what a restore left under the admin's name is the owner role's again
        return prepare(db)


def _trail_triggers() -> list[str]:
    return [f"{t}_{kind}" for t in APPEND_ONLY for kind in ("append_only", "no_truncate")]


def _triggers(db: Any) -> set[str]:
    """The user triggers of this schema that are enabled."""
    rows = db.fetchall(
        "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON "
        "n.oid = c.relnamespace WHERE n.nspname = current_schema() AND NOT t.tgisinternal AND t.tgenabled <> 'D'"
    )
    return {str(r[0]) for r in rows}


def _append_only(db: Database) -> None:
    """A trigger on each trail table refuses UPDATE, DELETE and TRUNCATE (D-281, CR-036). Made here, not in a
    migration, because a plpgsql body holds ``;`` (``Database.migrate`` splits on it); idempotent, one maker at a
    time. It holds against any role but the tables' owner. D-486 (T-718): on a box that owner is ``tbo_edc``, which
    no service is; the writer's role then also loses UPDATE, DELETE and TRUNCATE on the trail tables and every
    write on the version table."""
    fn = ("CREATE OR REPLACE FUNCTION edc_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
          "RAISE EXCEPTION USING MESSAGE = 'edc.' || TG_TABLE_NAME || ' is append-only', "
          "ERRCODE = 'insufficient_privilege'; END $$")  # fmt: skip
    triggers = {
        **{f"{t}_append_only": f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
           "FOR EACH ROW EXECUTE FUNCTION edc_append_only()" for t in APPEND_ONLY},
        **{f"{t}_no_truncate": f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t} "
           "FOR EACH STATEMENT EXECUTE FUNCTION edc_append_only()" for t in APPEND_ONLY},
    }  # fmt: skip
    with db.transaction() as tx:  # EDC-009 (D-582): made only when absent, so a restored box opens
        pgfunc.ensure(tx, "edc_append_only", (fn,), triggers)
    writer = db.writer_role()
    if writer:
        with db.transaction() as tx:
            for table in APPEND_ONLY:
                tx.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM "{writer}"')
            tx.execute(f'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON _schema_version FROM "{writer}"')


class EdcStore:
    def __init__(self, url: str | None = None, sign_key: bytes | None = None) -> None:
        self._key = sign_key if sign_key is not None else sign_key_of(os.environ)
        if len(self._key) < 16:
            raise EdcError("edc.sign_key", "the signature key is shorter than 16 bytes", 500)
        self.key_id = key_fingerprint(self._key)[:16]
        self._db = Database.connect(url or os.environ.get(ENV), "edc")
        prepare(self._db)

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
                      float(r["reentry_accuracy"]), r["by_user"], r["at"], int(r.get("reentry_id") or 0))  # fmt: skip

    # ------------------------------------------------------------------ the blind re-entry result (E-14)
    def add_reentry(self, study: str, *, pages: int, accuracy: float, document: str, source: str, by: str,
                    at: str) -> dict[str, Any]:  # fmt: skip
        """Keep a blind re-entry result (TB-PLAN-05 WS-16.4) with the id of the filed report it comes from. The
        switch reads the newest one; it is never typed at switch-on (review E-14)."""
        if source not in REENTRY_SOURCES:
            raise EdcError("edc.reentry_source", "an administrator or the PQ tooling records the re-entry result", 400)
        if not document.strip():
            raise EdcError("edc.reentry_document", "the id of the filed re-entry report is needed", 400)
        if pages < 0 or not 0.0 <= accuracy <= 1.0:
            raise EdcError("edc.reentry", "pages are a count and the accuracy is between 0 and 1", 400)
        rid = int(self._db.fetchval(
            "INSERT INTO reentry_record (study, pages, accuracy, document, source, by_user, at) VALUES "
            "(?,?,?,?,?,?,?) RETURNING id", (study, int(pages), float(accuracy), document.strip()[:120], source, by,
                                             at)))  # fmt: skip
        rec = self.reentry(study)
        assert rec is not None and int(rec["id"]) == rid
        return rec

    def reentry(self, study: str) -> dict[str, Any] | None:
        """The newest stored re-entry result of the study, or None."""
        rows = self._all("SELECT * FROM reentry_record WHERE study = ? ORDER BY id DESC LIMIT 1", (study,))
        return rows[0] if rows else None

    def set_switch(self, study: str, on: bool, *, kind: str = "", reference: str = "", ack_date: str = "",
                   reentry_pages: int = 0, reentry_accuracy: float = 0.0, reason: str = "", by: str, role: str,
                   at: str, today: date, typed_reentry: bool = False, copy: bool = False) -> Switch:  # fmt: skip
        """Turn prefill on (every condition checked here) or off (always allowed). Kept in ``switch_event``.

        The re-entry result is the newest stored record (E-14), never the numbers typed with the switch, and the
        person who recorded it is not the one who turns the switch on. ``typed_reentry`` (the caller's DEV or TEST
        box with no record yet) lets the typed numbers stand, as before T-115; the switch then says reentry_id 0.

        ``copy`` (with ``on``, D-434): copy-assist. The re-entry result is needed as for prefill; the sponsor's
        acknowledgement is not, because nothing is written to the sponsor's EDC (the send and the export refuse)."""
        reentry_id = 0
        if on:
            rec = self.reentry(study)
            if rec is not None:
                if str(rec["by_user"]) == by:
                    raise EdcError("edc.reentry_same_person", "the re-entry result was recorded by the person who "
                                   "turns prefill on; a second person records it")  # fmt: skip
                reentry_id = int(rec["id"])
                reentry_pages, reentry_accuracy = int(rec["pages"]), float(rec["accuracy"])
            elif not typed_reentry:
                raise EdcError("edc.reentry_record", "no blind re-entry result is on record for this study")
        if on and copy:  # no acknowledgement is needed; one already on record stays there, as with off
            cur0 = self.switch(study)
            kind, reference, ack_date = cur0.kind, cur0.reference, cur0.ack_date
        elif on:
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
        if on and (reentry_pages < REENTRY_PAGES or reentry_accuracy < REENTRY_ACCURACY):
            raise EdcError("edc.reentry", f"the blind re-entry needs at least {REENTRY_PAGES} pages at "
                                          f"{REENTRY_ACCURACY:.0%} or better")  # fmt: skip
        state = ("copy" if copy else "on") if on else "off"
        cur = self.switch(study)
        if not on:  # off keeps the acknowledgement on record; only the state changes
            kind, reference, ack_date = cur.kind, cur.reference, cur.ack_date
            reentry_pages, reentry_accuracy, reentry_id = cur.reentry_pages, cur.reentry_accuracy, cur.reentry_id
        with self._db.transaction() as tx:
            tx.execute("INSERT INTO switch (study, state, kind, reference, ack_date, reentry_pages, reentry_accuracy, "
                       "by_user, at, reentry_id) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(study) DO UPDATE SET "
                       "state = excluded.state, "
                       "kind = excluded.kind, reference = excluded.reference, ack_date = excluded.ack_date, "
                       "reentry_pages = excluded.reentry_pages, reentry_accuracy = excluded.reentry_accuracy, "
                       "by_user = excluded.by_user, at = excluded.at, reentry_id = excluded.reentry_id",
                       (study, state, kind, reference.strip()[:120], ack_date, int(reentry_pages),
                        float(reentry_accuracy), by, at, reentry_id))  # fmt: skip
            tx.execute("INSERT INTO switch_event (study, state, kind, reference, ack_date, reentry_pages, "
                       "reentry_accuracy, reason, by_user, role, at, reentry_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (study, state, kind, reference.strip()[:120], ack_date, int(reentry_pages),
                        float(reentry_accuracy), reason[:300], by, role, at, reentry_id))  # fmt: skip
        return self.switch(study)

    def switch_events(self, study: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM switch_event WHERE study = ? ORDER BY id", (study,))

    def require_on(self, study: str) -> None:
        if not self.switch(study).on:
            raise EdcError("edc.off", "prefill is off for this study (no sponsor acknowledgement on file)")

    def require_drafting(self, study: str) -> None:
        """Prefill on or copy-assist (D-434): drafts, the ODM import, review and signatures."""
        if not self.switch(study).drafting:
            raise EdcError("edc.off", "prefill and copy-assist are off for this study")

    # ------------------------------------------------------------------ the map and the target
    def put_map(self, study: str, items: list[dict[str, Any]], by: str, at: str) -> list[int]:
        """Save the map. A draft built under another row of its item (or for an item that left the map) and not yet
        signed is superseded: it is drafted again under the new row (E-15, T-115). A decided one keeps a
        ``superseded`` decision row. A signed one stays as signed, and the send lists it as ``stale_map``. Answers
        the ids superseded."""
        from edc.mapping import item_sha

        shas = {str(it["item"]): item_sha(it) for it in items}
        gone: list[int] = []
        with self._db.transaction() as tx:
            tx.execute("DELETE FROM item_map WHERE study = ?", (study,))
            for i, it in enumerate(items):
                tx.execute("INSERT INTO item_map (study, item, seq, body) VALUES (?,?,?,?)",
                           (study, it["item"], i, json.dumps(it, ensure_ascii=False, sort_keys=True)))  # fmt: skip
            tx.execute("INSERT INTO map_event (study, body, by_user, at) VALUES (?,?,?,?)",
                       (study, json.dumps(items, ensure_ascii=False, sort_keys=True), by, at))  # fmt: skip
            for d in tx.fetchdicts("SELECT id, record, visit, item, fate, final, map_sha FROM draft WHERE study = ? "
                                   "AND fate IN ('open', 'confirmed', 'edited') AND signature_id IS NULL AND "
                                   "map_sha <> '' ORDER BY id FOR UPDATE", (study,)):  # fmt: skip
                if shas.get(str(d["item"])) == d["map_sha"]:
                    continue
                tx.execute("UPDATE draft SET fate = 'superseded' WHERE id = ?", (int(d["id"]),))
                if d["fate"] in DECIDED:
                    tx.execute("INSERT INTO decision (draft_id, study, record, visit, item, action, old, new, reason, "
                               "citation, by_user, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (int(d["id"]), study, d["record"], d["visit"], d["item"], "superseded", d["final"],
                                None, "the item map changed; draft the item again", None, by, at))  # fmt: skip
                gone.append(int(d["id"]))
        return gone

    def token_owner(self, token_ref: str, study: str) -> str | None:
        """The other study whose REDCap target is this token, if any: a token belongs to one study (E-15)."""
        v = self._db.fetchval("SELECT study FROM target WHERE token_ref = ? AND study <> ? ORDER BY study LIMIT 1",
                              (token_ref, study))  # fmt: skip
        return None if v is None else str(v)

    def map(self, study: str) -> list[dict[str, Any]]:
        return [json.loads(r["body"]) for r in self._all("SELECT body FROM item_map WHERE study = ? ORDER BY seq",
                                                         (study,))]  # fmt: skip

    def map_events(self, study: str) -> list[dict[str, Any]]:
        return self._all("SELECT id, by_user, at FROM map_event WHERE study = ? ORDER BY id", (study,))

    def put_target(self, study: str, token_ref: str, key_field: str, id_field: str, by: str, at: str) -> None:
        if self.token_owner(token_ref, study) is not None:
            raise EdcError("edc.token_bound", "this REDCap connection is another study's target")
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
                    "why, citation, version, run_id, built_by, built_at, map_sha, dict_sha, target) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (study, record, pid, visit, visit_date, d["item"], d["form"], d["cdash"], d["test"], d["value"],
                     d["state"], d["why"], json.dumps(d["citation"], ensure_ascii=False) if d["citation"] else None,
                     d["version"], run_id, by, at, str(d.get("map_sha") or ""), str(d.get("dict_sha") or ""),
                     str(d.get("target") or "")))))  # fmt: skip
        return ids

    def add_proposals(self, study: str, proposals: list[dict[str, Any]], run_id: str, by: str,
                      at: str) -> dict[str, list[dict[str, Any]]]:  # fmt: skip
        """Values read from an outside file (an ODM import, D-435) as open drafts, in one transaction. Unlike a draft
        run, only the open or rejected draft of the **same** record, visit and item is superseded; an item a person
        confirmed or edited keeps its decision (``decided``), and the same value from the same file is not drafted
        again (``same``). Each proposal: ``record``, ``pid``, ``visit``, ``visit_date`` and a draft row as in
        :meth:`add_drafts`. A record key stays bound to its one subject (D-162). Nothing is decided or signed."""
        out: dict[str, list[dict[str, Any]]] = {"drafted": [], "decided": [], "same": []}
        with self._db.transaction() as tx:
            for rec, pid in sorted({(str(p["record"]), str(p["pid"])) for p in proposals}):
                other = tx.fetchval("SELECT pid FROM draft WHERE study = ? AND record = ? AND pid <> ? LIMIT 1",
                                    (study, rec, pid))  # fmt: skip
                if other is not None:
                    raise EdcError("edc.pid_mismatch", "this record key was drafted for another subject")
            for p in proposals:
                key = (study, p["record"], p["visit"], p["item"])
                cur = tx.fetchdicts("SELECT id, fate, value, citation FROM draft WHERE study = ? AND record = ? AND "
                                    "visit = ? AND item = ? AND fate <> 'superseded' ORDER BY id FOR UPDATE",
                                    key)  # fmt: skip
                brief = {"record": p["record"], "visit": p["visit"], "item": p["item"]}
                if any(r["fate"] in DECIDED for r in cur):
                    out["decided"].append(brief)
                    continue
                last = cur[-1] if cur else None
                if (last is not None and last["fate"] == "open" and last["value"] == p["value"]
                        and (_cit(last["citation"]) or {}).get("file") == p["citation"]["file"]):  # fmt: skip
                    out["same"].append(brief)
                    continue
                tx.execute("UPDATE draft SET fate = 'superseded' WHERE study = ? AND record = ? AND visit = ? AND "
                           "item = ? AND fate IN ('open', 'rejected')", key)  # fmt: skip
                did = int(tx.fetchval(
                    "INSERT INTO draft (study, record, pid, visit, visit_date, item, form, cdash, test, value, state, "
                    "why, citation, version, run_id, built_by, built_at, map_sha, dict_sha, target) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (study, p["record"], p["pid"], p["visit"], p["visit_date"], p["item"], p["form"], p["cdash"],
                     p["test"], p["value"], "drafted", p["why"], json.dumps(p["citation"], ensure_ascii=False),
                     p["version"], run_id, by, at, str(p.get("map_sha") or ""), str(p.get("dict_sha") or ""),
                     str(p.get("target") or ""))))  # fmt: skip
                out["drafted"].append({**brief, "id": did})
        return out

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
               citation: dict[str, Any] | None = None, by: str, at: str, unlock: bool = False,
               before_commit: Callable[[dict[str, Any]], None] | None = None,
               built: Mapping[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
        """Confirm, edit (with a reason) or reject one draft. The value's check against the field is the caller's
        (it knows the dictionary); the rules on citations, reasons and order are here.

        A signed value is locked (D-281, CR-035): it changes only with ``unlock`` (the caller re-authenticated the
        person just before) and a reason; the change is kept in ``signature_void``. ``before_commit`` runs inside
        the transaction with the new row: when it raises (the audit line could not be written), nothing changes.
        ``built``: on an edit, the item's map row, dictionary entry and target of now (T-115): the person decided the
        value under them."""
        if action not in ACTIONS:
            raise EdcError("edc.action", "confirm, edit or reject", 400)
        with self._db.transaction() as tx:
            rows = tx.fetchdicts("SELECT * FROM draft WHERE study = ? AND id = ? FOR UPDATE", (study, draft_id))
            if not rows:
                raise EdcError("edc.no_draft", "no such draft", 404)
            d = self._row(rows[0])
            if d["fate"] == "superseded":
                raise EdcError("edc.superseded", "a newer draft replaced this one; open the subject again")
            if d["signature_id"] is not None:
                if not unlock:
                    raise EdcError("edc.locked", "this value is signed; type your password again to change it", 423)
                if not reason.strip():
                    raise EdcError("edc.reason", "say why a signed value is changed", 400)
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
                rebuilt = bool(built) and any(str((built or {}).get(k) or "") != str(d.get(k) or "")
                                              for k in BUILT_UNDER)  # fmt: skip
                if (d["fate"] in DECIDED and final_cite == d["final_citation"] and value.strip() == d["final"]
                        and not rebuilt):  # fmt: skip
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
                tx.execute("INSERT INTO signature_void (signature_id, study, record, visit, draft_id, item, action, "
                           "reason, by_user, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (int(d["signature_id"]), study, d["record"], d["visit"], draft_id, d["item"], action,
                            reason.strip()[:300], by, at))  # fmt: skip
            tx.execute("UPDATE draft SET fate = ?, final = ?, final_citation = ?, reason = ?, decided_by = ?, "
                       "decided_at = ?, signature_id = NULL, signed_sha = NULL WHERE id = ?",
                       (fate, final, json.dumps(final_cite, ensure_ascii=False) if final_cite else None,
                        reason.strip()[:300], by, at, draft_id))  # fmt: skip
            if action == "edit" and built:
                tx.execute("UPDATE draft SET map_sha = ?, dict_sha = ?, target = ? WHERE id = ?",
                           (*(str(built.get(k) or "") for k in BUILT_UNDER), draft_id))  # fmt: skip
            tx.execute("INSERT INTO decision (draft_id, study, record, visit, item, action, old, new, reason, "
                       "citation, "
                       "by_user, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (draft_id, study, d["record"], d["visit"], d["item"], action, old, final, reason.strip()[:300],
                        json.dumps(final_cite, ensure_ascii=False) if final_cite else None, by, at))  # fmt: skip
            if before_commit is not None:
                row = self._row(tx.fetchdicts("SELECT * FROM draft WHERE id = ?", (draft_id,))[0])
                before_commit({**row, "voided": d["signature_id"]})
        out = self.draft(study, draft_id)
        assert out is not None
        return out

    # ------------------------------------------------------------------ signature
    def sign(self, study: str, record: str, visit: str, *, signer: str, printed_name: str, role: str, meaning: str,
             meaning_text: str, lang: str, at: str, seen: dict[int, str], method: str = "password",
             before_commit: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:  # fmt: skip
        """Sign the decided, unsigned values of one subject and visit. The caller has re-authenticated the signer
        (``method``: how). ``seen`` is what the signer's screen showed (draft id -> hash); the set and every hash must
        still be what is in the database now, or nothing is signed (review E-11). ``before_commit`` runs inside the
        transaction (D-281, SEC-6): when the audit line cannot be written, nothing is signed."""
        if meaning not in MEANINGS:
            raise EdcError("edc.meaning", "unknown signature meaning", 400)
        if method not in METHODS:
            raise EdcError("edc.method", "unknown way of re-authenticating", 400)
        with self._db.transaction() as tx:
            rows = [self._row(r) for r in tx.fetchdicts(
                "SELECT * FROM draft WHERE study = ? AND record = ? AND visit = ? AND fate IN ('confirmed', 'edited') "
                "AND signature_id IS NULL ORDER BY id FOR UPDATE", (study, record, visit))]  # fmt: skip
            if not rows:
                raise EdcError("edc.nothing_to_sign", "no confirmed value waits for a signature")
            shas = {int(r["id"]): draft_sha(r) for r in rows}
            if {int(k): str(v) for k, v in seen.items()} != shas:
                raise EdcError("edc.sign_changed", "the values changed since the page was shown; open it again")
            act = {"study": study, "record": record, "visit": visit, "signer": signer, "printed_name": printed_name,
                   "role": role, "meaning": meaning, "meaning_text": meaning_text, "lang": lang, "method": method,
                   "at": at}  # fmt: skip
            content = signature_sha(self._key, act, shas)
            sid = int(tx.fetchval(
                "INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, "
                "method, at, content_sha, drafts, sig_version, key_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "RETURNING id",
                (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, method, at,
                 content, json.dumps({str(k): v for k, v in sorted(shas.items())}), SIG_VERSION,
                 self.key_id)))  # fmt: skip
            for did, sha in shas.items():
                tx.execute("UPDATE draft SET signature_id = ?, signed_sha = ? WHERE id = ?", (sid, sha, did))
            if before_commit is not None:
                before_commit({"id": sid, "visit": visit, "content_sha": content, "values": len(shas),
                               "method": method})  # fmt: skip
        sig = self.signature(sid)
        assert sig is not None
        return sig

    def intact(self, s: Mapping[str, Any]) -> bool:
        """The signature row is what was signed: its ``content_sha`` is re-made from the row with the key (D-281,
        CR-036). Only version 2 counts (D-461): the unkeyed version 1 needs no key to re-make, so a version-1 row
        covers nothing and its values wait for a new signature."""
        try:
            shas = {int(k): str(v) for k, v in json.loads(s["drafts"]).items()}
            version = int(s.get("sig_version") or 0)
        except (TypeError, ValueError, AttributeError):
            return False
        if version != SIG_VERSION:
            return False
        return hmac.compare_digest(str(s["content_sha"]), signature_sha(self._key, s, shas))

    def _covered(self, d: Mapping[str, Any], sigs: Mapping[int, Mapping[str, Any]]) -> bool:
        """The value is still exactly what its signature row says was signed, and that row is itself intact."""
        s = sigs.get(int(d["signature_id"]))
        if s is None or d["signed_sha"] != draft_sha(dict(d)):
            return False
        try:
            listed = {int(k): str(v) for k, v in json.loads(s["drafts"]).items()}
        except (TypeError, ValueError, AttributeError):
            return False
        return listed.get(int(d["id"])) == d["signed_sha"] and self.intact(s)

    def covered_ids(self, study: str, rows: list[dict[str, Any]]) -> set[int]:
        """The ids of ``rows`` (drafts of ``study``) whose value is still covered by an intact signature: what the
        review page may show as signed (D-461)."""
        sigs = {int(s["id"]): s for s in self.signatures(study)}
        return {int(d["id"]) for d in rows if d.get("signature_id") is not None and self._covered(d, sigs)}

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
        sigs = {int(s["id"]): s for s in self.signatures(study)}
        out = []
        for d in self._current(study, record, visit):
            if d["fate"] not in DECIDED or d["signature_id"] is None or not d["final"]:
                continue
            if not self._covered(d, sigs):
                continue  # changed after signing, or the signature row was tampered with: never sent
            if d["sent_at"] and d["sent_value"] == d["final"]:
                continue
            out.append(d)
        return out

    def signed(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        """Decided, signed values whose content still matches the signature (the ODM export)."""
        sigs = {int(s["id"]): s for s in self.signatures(study, record)}
        return [d for d in self._current(study, record) if d["fate"] in DECIDED and d["signature_id"] is not None
                and d["final"] and self._covered(d, sigs)]  # fmt: skip

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

    def last_written(self, study: str, record: str, visit: str, item: str) -> str | None:
        """The value TrialBox itself last wrote into REDCap for this item (NEW-EDC-2): ``sent`` (written and read
        back) or ``erased`` (written empty). An ``already_there`` line is not a write: the value was someone's
        before TrialBox came. None: TrialBox never wrote it."""
        rows = self._all("SELECT value, result FROM sent WHERE study = ? AND record = ? AND visit = ? AND item = ? AND "
                         "target = 'redcap' AND result IN ('sent', 'erased') ORDER BY id DESC LIMIT 1",
                         (study, record, visit, item))  # fmt: skip
        if not rows:
            return None
        return "" if rows[0]["result"] == "erased" else str(rows[0]["value"])

    # ------------------------------------------------------------------ copy-assist (D-434)
    def add_ticks(self, study: str, values: list[dict[str, Any]], action: str, *, reason: str = "", by: str, at: str,
                  before_commit: Callable[[list[int]], None] | None = None) -> list[int]:  # fmt: skip
        """One ``copy_tick`` row per value (each a signed draft row, as :meth:`signed` gives it), bound to the hash
        of the value as signed. ``undone`` needs a reason. ``before_commit`` runs inside the transaction: when the
        audit line cannot be written, nothing is ticked."""
        if action not in TICKS:
            raise EdcError("edc.tick_action", "a tick is copied or undone", 400)
        if action == "undone" and not reason.strip():
            raise EdcError("edc.reason", "say why the tick is undone", 400)
        if not values:
            raise EdcError("edc.tick_none", "no value to tick", 400)
        ids: list[int] = []
        with self._db.transaction() as tx:
            for d in values:
                ids.append(int(tx.fetchval(
                    "INSERT INTO copy_tick (study, record, visit, item, draft_id, signed_sha, action, reason, by_user, "
                    "at) VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (study, d["record"], d["visit"], d["item"], int(d["id"]), str(d["signed_sha"]), action,
                     reason.strip()[:300], by, at))))  # fmt: skip
            if before_commit is not None:
                before_commit(ids)
        return ids

    def ticks(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        """Every copy tick of the study (or one subject), oldest first."""
        if record is None:
            return self._all("SELECT * FROM copy_tick WHERE study = ? ORDER BY id", (study,))
        return self._all("SELECT * FROM copy_tick WHERE study = ? AND record = ? ORDER BY id", (study, record))

    # ------------------------------------------------------------------ the per-record trail
    def trail(self, study: str, record: str) -> dict[str, Any]:
        """Every draft, decision, signature (with the items it covers, E-12), withdrawn signature and send of one
        subject."""
        items = {int(r["id"]): str(r["item"]) for r in self._all("SELECT id, item FROM draft WHERE study = ? AND "
                                                                  "record = ?", (study, record))}  # fmt: skip

        def covers(s: Mapping[str, Any]) -> list[str]:
            try:
                return [items.get(int(k), "?") for k in sorted(json.loads(s["drafts"]), key=int)]
            except (TypeError, ValueError, AttributeError):
                return []

        return {
            "drafts": self._all("SELECT id, visit, item, value, state, why, fate, final, built_by, built_at, version, "
                                "run_id FROM draft WHERE study = ? AND record = ? ORDER BY id", (study, record)),
            "decisions": self._all("SELECT * FROM decision WHERE study = ? AND record = ? ORDER BY id",
                                   (study, record)),
            "signatures": [{**s, "intact": self.intact(s), "items": covers(s)} for s in self.signatures(study, record)],
            "voids": self._all("SELECT * FROM signature_void WHERE study = ? AND record = ? ORDER BY id",
                               (study, record)),
            "sent": self.sent_rows(study, record),
        }  # fmt: skip
