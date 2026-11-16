"""The EDC prefill service (D-160): the steps a study team takes, each checked and audited here.

The orchestrator's ``/studies/{rs}/edc/*`` routes call this; the console only shows the pages and re-authenticates
the signer. The rules are enforced here even when a page already checked them (defence in depth):

* the switch must be on (sponsor's written acknowledgement and the re-entry result on file) to send or export; on
  or ``copy`` (copy-assist, D-434: the re-entry result, no acknowledgement, never a write to the sponsor's EDC) to
  draft, import, decide and sign; it is off by default;
* the map must pass :func:`edc.mapping.check` before it is saved;
* a value without a citation cannot be confirmed; an edit needs a reason and passes the field's own checks;
* only confirmed, signed values whose content still matches the signature, under a signature row that still verifies
  with the key (D-281), are sent or exported; a signed value is locked: it changes only right after the person typed
  their password again, with a reason (D-281);
* the REDCap send never overwrites a value someone else wrote in REDCap: it is listed as a conflict and skipped;
  every value sent is read back and compared. A screening number on two REDCap records, a visit that is not an
  event of the project, and a project with repeating instruments are refused (D-162);
* each draft carries the hash of its item's map row, of its dictionary entry and the REDCap target it was built
  for, all three inside what a signature covers. A map change supersedes the drafts not yet signed; the send
  re-reads the project's dictionary and holds back a value whose map row, dictionary entry or target changed since,
  and one REDCap's import would refuse, each listed with its reason; values go in the format of the field's
  validation (``number_1dp``, decimal comma). A REDCap connection is one study's target (T-115, D-368);
* the switch goes on with the stored blind re-entry result, recorded by another person (T-115, E-14);
* a patient on the opt-out register is never drafted, decided, signed, sent or exported (D-162).

Every step writes one audit event (``edc.*``) with who, the study and what changed (never a clinical value); a refusal
writes one too, with its code. The decision and the signature write theirs inside their transaction (D-281).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from typing import Any

from datacore import forms
from datacore.export import BASE_EVENT
from datacore.store import DataCore
from rc_bridge.client import RcError, RedcapClient
from tb_common.audit import AuditLog
from tb_common.config import environment_name
from tb_common.llm import LlmError

from edc import mapping, odm, prefill
from edc.layout import Layout, Slot, split_visit
from edc.logic import LogicError
from edc.rows import Key, Rows, watched
from edc.store import CHANGED_SAYS, EdcError, EdcStore

log = logging.getLogger("edc")


def model_failure(exc: LlmError) -> str:
    """Why the note drafter failed, without any text the model or the notes gave: the gateway's refusal code
    (``purpose_not_allowed``, ``no_route``...) or the kind of failure."""
    cause = exc.__cause__
    reason = getattr(cause, "reason", "")
    if reason:
        return f"gateway refused: {reason}"
    return type(cause or exc).__name__


# The words of a CRC's signature (T-205, D-391; REG-021, REG-024): what the signer really did (compared each value with
# the source the page cites) and no more. No claim that the values are correct, no regulation named, and a quote is
# said to be a copy. Equal to ``edc.sign.meaning`` in English (the console's three languages are pinned by a test).
ODM_MEANING = ("With this electronic signature I confirm that I compared each value with the source cited beside it "
               "on this page, and that these are the values I confirmed for this subject and visit. A passage quoted "
               "by TrialBox is a copy of the hospital record, not the record itself.")  # fmt: skip


@dataclass
class EdcService:
    store: EdcStore
    dc: DataCore
    audit: AuditLog
    now: Callable[[], datetime]
    today: Callable[[], date]
    client: Callable[[str], RedcapClient]  # token_ref -> client (the study store's tokens)
    facts: Callable[[], prefill.Facts]  # the box's record (the lake), read at the snapshot of the moment
    drafter: Callable[[str], prefill.NoteDrafter | None] = lambda _job: None  # the note drafter, or none
    optouts: Callable[[], frozenset[str]] = frozenset  # the opt-out register's pseudonyms (fails closed)
    #: a DEV or TEST box with no stored re-entry result may switch on with the typed numbers (demos; E-14)
    typed_reentry: Callable[[], bool] = lambda: environment_name(os.environ) in ("DEV", "TEST")

    def stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def _audit(self, event: str, rs: str, by: str, detail: dict[str, Any]) -> None:
        self.audit.append(event, ruleset=rs, actor=by, detail=detail)

    def _not_opted_out(self, rs: str, by: str, event: str, pids: set[str], detail: dict[str, Any]) -> None:
        if pids & set(self.optouts()):
            self._audit(event, rs, by, {**detail, "refused": "edc.opted_out"})
            raise EdcError("edc.opted_out", "the patient opted out; nothing is drafted, signed or sent")

    # ------------------------------------------------------------------ status and switch
    def status(self, rs: str) -> dict[str, Any]:
        sw = self.store.switch(rs)
        items = self.store.map(rs)
        return {"switch": sw.as_dict(), "events": self.store.switch_events(rs)[-10:], "map": items,
                "target": self.store.target(rs), "mapped": sum(1 for i in items if i.get("source", "none") != "none"),
                "subjects": self.store.subjects(rs), "fields": len(self.dc.fields(rs))}  # fmt: skip

    def set_switch(self, rs: str, on: bool, *, by: str, role: str, **ack: Any) -> dict[str, Any]:
        try:
            sw = self.store.set_switch(rs, on, by=by, role=role, at=self.stamp(), today=self.today(),
                                       typed_reentry=self.typed_reentry(), **ack)  # fmt: skip
        except EdcError as exc:
            self._audit("edc.switch", rs, by, {"on": on, "refused": exc.code})
            raise
        self._audit("edc.switch", rs, by, {"on": sw.on, "state": sw.state, "kind": sw.kind, "reference": sw.reference,
                                           "ack_date": sw.ack_date, "reentry_pages": sw.reentry_pages,
                                           "reentry_accuracy": sw.reentry_accuracy, "reentry_id": sw.reentry_id,
                                           "role": role})  # fmt: skip
        return sw.as_dict()

    def record_reentry(self, rs: str, *, pages: int, accuracy: float, document: str, by: str,
                       source: str = "admin") -> dict[str, Any]:  # fmt: skip
        """Keep the blind re-entry result with the id of its filed report (E-14); audited, refusals too."""
        try:
            rec = self.store.add_reentry(rs, pages=pages, accuracy=accuracy, document=document, source=source, by=by,
                                         at=self.stamp())  # fmt: skip
        except EdcError as exc:
            self._audit("edc.reentry", rs, by, {"refused": exc.code})
            raise
        self._audit("edc.reentry", rs, by, {"id": rec["id"], "pages": rec["pages"], "accuracy": rec["accuracy"],
                                            "document": rec["document"], "source": source})  # fmt: skip
        return rec

    def _bound(self, rs: str, token_ref: str, by: str, event: str) -> None:
        """A REDCap connection is one study's target (E-15): refused, and audited, for any other study."""
        other = self.store.token_owner(token_ref, rs)
        if other is not None:
            self._audit(event, rs, by, {"token_ref": token_ref, "refused": "edc.token_bound"})
            raise EdcError("edc.token_bound", "this REDCap connection is another study's target")

    # ------------------------------------------------------------------ dictionary and map
    def import_dictionary(self, rs: str, token_ref: str, by: str, record_field: str = "") -> dict[str, Any]:
        """Read the REDCap project's data dictionary through the API into the study's forms (identifiers dropped)."""
        self._bound(rs, token_ref, by, "edc.dictionary")
        try:
            with self.client(token_ref) as c:
                rows = c.metadata()
        except RcError as exc:
            raise EdcError(exc.code, exc.message, 502 if exc.code == "RC-UPSTREAM" else 409) from exc
        if not rows:
            raise EdcError("edc.dictionary", "the REDCap project has no fields")
        fields = [forms.field_of(r) for r in rows]
        rec = record_field or fields[0].name
        qs = forms.questionnaires(rs, fields, record_field=rec)
        for q in qs:
            self.dc.put_form(rs, q, "redcap-api", self.stamp())
        dropped = [f.name for f in fields if f.identifier]
        self._audit("edc.dictionary", rs, by, {"token_ref": token_ref, "forms": [q["name"] for q in qs],
                                               "dropped": dropped})  # fmt: skip
        return {"forms": [q["name"] for q in qs], "fields": sum(len(q["item"]) for q in qs), "dropped": dropped,
                "record_field": rec}  # fmt: skip

    def _protected(self, rs: str, target: dict[str, Any] | None) -> set[str]:
        return {str(target["key_field"]), str(target["id_field"])} if target else set()

    def suggest(self, rs: str) -> list[dict[str, Any]]:
        fields = list(self.dc.fields(rs).values())
        return [m.as_dict() for m in mapping.suggest(fields, self._protected(rs, self.store.target(rs)))]

    def put_map(self, rs: str, items: list[dict[str, Any]], target: dict[str, str], by: str) -> dict[str, Any]:
        for k in ("token_ref", "key_field", "id_field"):
            if not str(target.get(k) or "").strip():
                raise EdcError("edc.target", f"the REDCap target needs {k}", 400)
        self._bound(rs, str(target["token_ref"]), by, "edc.map")
        maps = [mapping.ItemMap.from_dict(i) for i in items]
        fields = self.dc.fields(rs)
        bad = mapping.check(maps, fields, self._protected(rs, target))
        if bad:
            err = EdcError("edc.map", "the map has problems")
            err.problems = bad  # type: ignore[attr-defined]
            raise err
        body = [m.as_dict() for m in maps]
        at = self.stamp()
        self.store.put_target(rs, target["token_ref"], target["key_field"], target["id_field"], by, at)
        gone = self.store.put_map(rs, body, by, at)
        self._audit(
            "edc.map",
            rs,
            by,
            {
                "items": len(body),
                "drafted": sum(1 for m in maps if m.drafted),
                "target": target["token_ref"],
                "sha": hashlib.sha256(mapping.dumps(maps).encode()).hexdigest()[:16],
                "superseded": len(gone),
            },
        )
        return {"items": len(body), "drafted": sum(1 for m in maps if m.drafted), "superseded": len(gone)}

    def _built(self, rs: str, item: str) -> dict[str, str]:
        """What a value of ``item`` is decided under now (E-15, E-16): its map row, its dictionary entry, the
        target."""
        row = next((m for m in self.store.map(rs) if str(m["item"]) == item), None)
        f = self.dc.fields(rs).get(item)
        target = self.store.target(rs)
        return {"map_sha": mapping.item_sha(row) if row is not None else "",
                "dict_sha": forms.field_sha(f) if f is not None else "",
                "target": str(target["token_ref"]) if target else ""}  # fmt: skip

    # ------------------------------------------------------------------ drafts
    def build(self, rs: str, record: str, pid: str, visit: str, visit_date: str, by: str) -> list[dict[str, Any]]:
        self.store.require_drafting(rs)  # prefill on, or copy-assist (D-434)
        self._not_opted_out(rs, by, "edc.drafts", {pid}, {"record": record})
        try:
            vd = date.fromisoformat(visit_date)
        except ValueError as exc:
            raise EdcError("edc.visit_date", "the visit date is YYYY-MM-DD", 400) from exc
        if vd > self.today():
            raise EdcError("edc.visit_date", "the visit date is in the future", 400)
        items = [mapping.ItemMap.from_dict(i) for i in self.store.map(rs)]
        if not items:
            raise EdcError("edc.no_map", "save the item map first")
        fields = self.dc.fields(rs)
        bad = mapping.check(items, fields, self._protected(rs, self.store.target(rs)))
        if bad:  # the dictionary changed under the map: never draft against a stale map
            err = EdcError("edc.map", "the map no longer fits the data dictionary")
            err.problems = bad  # type: ignore[attr-defined]
            raise err
        slot = split_visit(visit or BASE_EVENT, {f.form for f in fields.values()})
        if slot.instrument:  # an instance of a repeating instrument: only that instrument's items (T-302b)
            items = [m for m in items if m.item in fields and fields[m.item].form == slot.instrument]
            if not items:
                raise EdcError("edc.no_map", f"no item of the map is on the instrument {slot.instrument}")
        run_id = hashlib.sha256(f"{rs}|{record}|{visit}|{self.stamp()}".encode()).hexdigest()[:16]
        try:
            drafts = prefill.build(pid, vd, items, fields, self.facts(), self.drafter(run_id))
        except LlmError as exc:  # the gateway refused or the model failed: nothing is drafted, and the page says why
            why = model_failure(exc)
            log.error("EDC prefill: the box's model did not draft study %s record %s: %s", rs, record, why)
            self._audit("edc.drafts", rs, by, {"record": record, "visit": visit or BASE_EVENT, "run": run_id,
                                               "refused": "edc.model", "error": why})  # fmt: skip
            raise EdcError("edc.model", f"the box's model did not answer ({why})", 502) from exc
        except EdcError:
            raise
        except Exception as exc:  # D-684: the box's record could not be read: a coded refusal, audited, no draft
            kind = type(exc).__name__  # the type only: a lake's error text can quote what it read
            log.error("EDC prefill: the box's record was not read for study %s record %s (%s)", rs, record, kind)
            self._audit("edc.drafts", rs, by, {"record": record, "visit": visit or BASE_EVENT, "run": run_id,
                                               "refused": "edc.lake", "error": kind})  # fmt: skip
            raise EdcError("edc.lake", "the box's record could not be read; nothing was drafted", 503) from exc
        target = self.store.target(rs)
        built = {"target": str(target["token_ref"]) if target else ""}
        shas = {m.item: mapping.item_sha(m) for m in items}
        rows = [{**d.as_dict(), **built, "map_sha": shas.get(d.item, ""),
                 "dict_sha": forms.field_sha(fields[d.item]) if d.item in fields else ""} for d in drafts]  # fmt: skip
        ids = self.store.add_drafts(rs, record, pid, visit or BASE_EVENT, vd.isoformat(), rows, run_id, by,
                                    self.stamp())  # fmt: skip
        self._audit(
            "edc.drafts",
            rs,
            by,
            {
                "record": record,
                "visit": visit or BASE_EVENT,
                "run": run_id,
                "drafted": sum(1 for d in drafts if d.state == "drafted"),
                "unknown": sum(1 for d in drafts if d.state == "unknown"),
                "new": len(ids),
                "snapshot": drafts[0].version if drafts else "",
            },
        )
        return self.store.drafts(rs, record, visit or BASE_EVENT)

    def decide(self, rs: str, draft_id: int, action: str, *, value: str = "", reason: str = "",
               citation: dict[str, Any] | None = None, by: str, unlock: bool = False,
               mark: str = "") -> dict[str, Any]:  # fmt: skip
        """Confirm, edit or reject one draft. ``unlock``: the person re-authenticated just before, so a signed value
        may change (with a reason; D-281, CR-035). Every refusal is audited (SEC-7); the decision's audit line is
        written inside its transaction (SEC-6)."""
        try:
            self.store.require_drafting(rs)
            d = self.store.draft(rs, draft_id)
            if d is None:
                raise EdcError("edc.no_draft", "no such draft", 404)
            if d["fate"] == "retired":  # NEW-EDC-6: final until the item is in the study again
                raise EdcError("edc.retired", "this value is retired: its item left the study")
        except EdcError as exc:
            self._audit("edc.decide", rs, by, {"draft": draft_id, "action": action, "refused": exc.code})
            raise
        self._not_opted_out(rs, by, "edc.decide", {str(d["pid"])}, {"draft": draft_id})

        def audited(out: dict[str, Any]) -> None:
            self._audit("edc.decide", rs, by, {"draft": draft_id, "record": out["record"], "visit": out["visit"],
                                               "item": out["item"], "action": action, "fate": out["fate"],
                                               "reason": bool(reason.strip()),
                                               "citation": (out["final_citation"] or {}).get("kind", ""),
                                               **({"signature_void": out["voided"], "unlocked": True}
                                                  if out.get("voided") is not None else {}),
                                               **({"unlocked": True} if out.get("kept_signed") is not None
                                                  else {})})  # fmt: skip

        now: dict[str, str] | None = None
        try:
            # EDC-010 (D-581): the reason and the citation's words go into the trail and the ODM file
            texts = [("reason", reason), *((f"citation {k}", str(v)) for k, v in (citation or {}).items())]
            for what, text in texts:
                if forms.XML_ILLEGAL.search(text):
                    raise EdcError("edc.chars", f"the {what} holds a character that cannot be stored (a control "
                                   "character from pasted text)", 400)  # fmt: skip
            # NEW-EDC-6 (EDC-006): only a value whose item an amendment removed is retired; the study's map says (an
            # amendment is saved as a map), a dictionary gap alone may be a bad re-read
            if action == "retire" and str(d["item"]) in {str(m["item"]) for m in self.store.map(rs)}:
                raise EdcError("edc.not_removed", "the item is still in the study's map: change or withdraw the "
                                   "value instead")  # fmt: skip
            if action in ("confirm", "edit"):
                now = self._built(rs, str(d["item"]))
            if action == "confirm":  # a draft is confirmed only under the map row and dictionary entry of now (E-16)
                if d.get("map_sha") and d["map_sha"] != now["map_sha"]:  # type: ignore[index]
                    raise EdcError("edc.stale_map", "the item map changed since this draft; draft the item again")
                f0 = self.dc.fields(rs).get(str(d["item"]))
                if f0 is None or (d.get("dict_sha") and d["dict_sha"] != forms.field_sha(f0)):
                    raise EdcError("edc.stale_dictionary", "the data dictionary changed since this draft; draft the "
                                   "item again")  # fmt: skip
                p0 = forms.problem(f0, str(d.get("value") or ""))
                if p0 is not None:
                    err = EdcError("edc.invalid", forms.reason(p0, str(d.get("value") or "")), 400)
                    err.problems = [{"field": f0.name, **p0}]  # type: ignore[attr-defined]
                    raise err
            if action == "edit":
                f = self.dc.fields(rs).get(str(d["item"]))
                if f is None:
                    raise EdcError("edc.not_in_dictionary", "the item is no longer in the data dictionary")
                p = forms.problem(f, value.strip())
                if p is not None:
                    err = EdcError("edc.invalid", forms.reason(p, value), 400)
                    err.problems = [{"field": f.name, **p}]  # type: ignore[attr-defined]
                    raise err
            return self.store.decide(rs, draft_id, action, value=value, reason=reason, citation=citation, by=by,
                                     at=self.stamp(), unlock=unlock, before_commit=audited,
                                     built=now if action == "edit" else None, mark=mark)  # fmt: skip
        except EdcError as exc:
            self._audit("edc.decide", rs, by, {"draft": draft_id, "action": action, "refused": exc.code})
            raise

    def sign(self, rs: str, record: str, visit: str, *, signer: str, printed_name: str, role: str, meaning: str,
             meaning_text: str, lang: str, seen: dict[int, str],
             method: str = "password") -> dict[str, Any]:  # fmt: skip
        """The console re-authenticated ``signer`` just before this call (``method``: how); ``seen`` is what their
        screen showed. The audit line is written inside the signature's transaction (D-281, SEC-6): if it cannot be
        written, nothing is signed. Every refusal is audited (SEC-7)."""
        try:
            self.store.require_drafting(rs)
        except EdcError as exc:
            self._audit("edc.sign", rs, signer, {"record": record, "visit": visit, "refused": exc.code})
            raise
        pids = {str(d["pid"]) for d in self.store.drafts(rs, record, visit or BASE_EVENT)}
        self._not_opted_out(rs, signer, "edc.sign", pids, {"record": record})

        def audited(s: dict[str, Any]) -> None:
            self._audit("edc.sign", rs, signer, {"record": record, "visit": s["visit"], "signature": s["id"],
                                                 "meaning": meaning, "printed_name": printed_name, "role": role,
                                                 "method": s["method"], "values": s["values"],
                                                 "content_sha": s["content_sha"]})  # fmt: skip

        try:
            # EDC-010 (D-581): the name and the meaning's words are under the signature and go into the ODM file
            for what, text in (("printed name", printed_name), ("meaning", meaning_text), ("role", role)):
                if forms.XML_ILLEGAL.search(text):
                    raise EdcError("edc.chars", f"the {what} holds a character that cannot be stored (a control "
                                   "character from pasted text)", 400)  # fmt: skip
            return self.store.sign(rs, record, visit or BASE_EVENT, signer=signer, printed_name=printed_name,
                                   role=role, meaning=meaning, meaning_text=meaning_text, lang=lang,
                                   at=self.stamp(), seen=seen, method=method, before_commit=audited)  # fmt: skip
        except EdcError as exc:
            self._audit("edc.sign", rs, signer, {"record": record, "visit": visit, "refused": exc.code})
            raise

    # ------------------------------------------------------------------ send to REDCap, export ODM
    def _layout(self, c: RedcapClient, rs: str, by: str, record: str | None) -> Layout:
        """The project's arms, events, designations and repeating set (T-302b). A project that repeats something
        but does not say what is refused: a value could land on the wrong instance (E-05)."""
        proj = c.project()
        longitudinal = bool(int(proj.get("is_longitudinal") or 0))
        events = c.events() if longitudinal else []
        designations = c.form_event_mapping() if longitudinal else []
        repeating: list[dict[str, Any]] = []
        if int(proj.get("has_repeating_instruments_or_events") or 0):
            try:
                repeating = c.repeating_forms_events()
            except RcError:
                repeating = []
            if not repeating:
                self._audit("edc.sent", rs, by, {"record": record or "*", "refused": "edc.repeating"})
                raise EdcError("edc.repeating", "the REDCap project repeats instruments or events but did not say "
                               "which; prefill does not send to it")  # fmt: skip
        return Layout.read(proj, events, designations, repeating)

    def send_redcap(self, rs: str, by: str, record: str | None = None) -> dict[str, Any]:
        self.store.require_on(rs)
        target = self.store.target(rs)
        if target is None:
            raise EdcError("edc.target", "no REDCap target is set for this study")
        out: dict[str, list[dict[str, Any]]] = {k: [] for k in SEND_RESULTS}
        attempted = 0  # NEW-EDC-8: values whose write was ledgered before the import
        calc_out: list[dict[str, Any]] = []
        hidden_out: list[dict[str, Any]] = []
        at = self.stamp()
        gone = set(self.optouts())
        for d in self.store.held_source_changed(rs, record):  # NEW-EDC-4: a person keeps or changes it first
            if str(d["pid"]) in gone:
                out["opted_out"].append(_brief(d))
                self.store.record_sent(rs, d, "redcap", "", "opted_out", "the patient opted out; not sent", by, at)
                continue
            out["source_changed"].append(_brief(d))
            self.store.record_sent(rs, d, "redcap", "", "source_changed", "the source changed since the value was "
                                   "decided; not sent until a person keeps or changes it", by, at)  # fmt: skip
        todo = []
        for d in self.store.sendable(rs, record):
            if str(d["pid"]) in gone:
                out["opted_out"].append(_brief(d))
                self.store.record_sent(rs, d, "redcap", "", "opted_out", "the patient opted out; not sent", by, at)
            else:
                todo.append(d)
        if not todo:
            self._audit(
                "edc.sent",
                rs,
                by,
                {
                    "record": record or "*",
                    "sent": 0,
                    **({"opted_out": len(out["opted_out"])} if out["opted_out"] else {}),
                    **({"source_changed": len(out["source_changed"])} if out["source_changed"] else {}),
                },
            )
            drift, unread = self._reread(rs, by, record)
            return {**out, "changed_in_redcap": drift, "reread": unread, "count": 0, "calc": [],
                    "hidden_in_redcap": []}  # fmt: skip
        key, rid = str(target["key_field"]), str(target["id_field"])
        try:
            with self.client(str(target["token_ref"])) as c:
                lay = self._layout(c, rs, by, record)
                # T-115 (E-15, E-16, STD-061): the project's dictionary of now, the map of now, and the target
                meta = {str(m.get("field_name")): m for m in c.metadata()}
                live = {f.name: f for f in (forms.field_of(m) for m in meta.values())}
                local = self.dc.fields(rs)
                rows_now = {str(m["item"]): mapping.item_sha(m) for m in self.store.map(rs)}
                held = []
                for d in todo:
                    item = str(d["item"])
                    lf = live.get(item)
                    want = str(d.get("dict_sha") or "") or (forms.field_sha(local[item]) if item in local else "")
                    why = ""
                    if d.get("target") and d["target"] != str(target["token_ref"]):
                        why, text = "target_changed", "built for another REDCap target; not sent"
                    elif d.get("map_sha") and rows_now.get(item) != d["map_sha"]:
                        why, text = "stale_map", "the item's map row changed since it was signed; not sent"
                    elif lf is None or forms.field_sha(lf) != want:
                        why, text = "dictionary_changed", "the REDCap dictionary entry changed since; not sent"
                    elif forms.problem(lf, str(d["final"])) is not None:
                        p = forms.problem(lf, str(d["final"])) or {}
                        why, text = "format", "REDCap would refuse it: " + forms.reason(p, str(d["final"]))
                    if why:
                        out[why].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", "", why, text, by, at)
                        held.append(d)
                todo = [d for d in todo if d not in held]
                fmt = {int(d["id"]): forms.redcap_value(live[str(d["item"])], str(d["final"])) for d in todo}
                items = sorted({str(d["item"]) for d in todo})
                rows = c.records(fields=[rid, key, *items])
                if lay.repeats and rows and any("redcap_repeat_instance" not in r for r in rows):
                    self._audit("edc.sent", rs, by, {"record": record or "*", "refused": "edc.repeat_keys"})
                    raise EdcError("edc.repeat_keys", "the project repeats instruments or events, but REDCap's export "
                                   "has no redcap_repeat_instance: a value cannot be put on its instance; nothing "
                                   "is sent")  # fmt: skip
                found: dict[str, set[str]] = {}
                for r in rows:
                    if str(r.get(key) or "").strip():
                        found.setdefault(str(r[key]).strip().upper(), set()).add(str(r[rid]))
                ids = {k: next(iter(v)) for k, v in found.items() if len(v) == 1}
                twice = {k for k, v in found.items() if len(v) > 1}
                # the touched records' rows, with every field their branching logic and calculations read (T-302b)
                recs = sorted({ids[str(d["record"]).upper()] for d in todo if str(d["record"]).upper() in ids})
                look = watched(meta, {live[i].form for i in items}, items)
                # NEW-EDC-2 (EDC-002): a repeat instance is judged whole, so every field of its row is read
                look |= self._instance_fields(lay, meta, todo)
                cur = Rows(lay, meta, rid, c.records(fields=[rid, *items, *sorted(look - set(items))], records=recs)
                           if recs else [], self.today())  # fmt: skip
                if recs and lay.longitudinal:  # CGRD-B3 (D-841): the record's arms from every row it has
                    cur.know_events(c.records(fields=[rid], records=recs))
                imports: dict[Key, dict[str, str]] = {}
                planned: list[tuple[dict[str, Any], str, Slot]] = []
                taken: set[Key] = set()  # NEW-EDC-2: repeat instances that hold a value TrialBox did not write
                judged: dict[Key, bool] = {}
                for d in todo:
                    if str(d["record"]).upper() in twice:  # a wrong-subject write is worse than none (E-06)
                        out["duplicate"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", "", "duplicate", "the screening number is on more "
                                               "than one REDCap record; not sent", by, at)  # fmt: skip
                        continue
                    slot = lay.slot(str(d["visit"]))
                    if slot is None:  # the visit must be an event (or a repeat instance) of the project (E-04)
                        out["no_event"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", "", "no_event", "the visit is not an event of the "
                                               "REDCap project; not sent", by, at)  # fmt: skip
                        continue
                    rec = ids.get(str(d["record"]).upper())
                    if rec is None:
                        out["no_record"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", "", "no_record", "no REDCap record with this "
                                               "screening number", by, at)  # fmt: skip
                        continue
                    lf = live[str(d["item"])]
                    where = lay.misplaced(slot, lf.form, cur.arms(rec))
                    if where:  # T-302b: the arm, the event's instruments, the repeating instrument's own rows
                        out[where].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", rec, where, PLACEMENT[where], by, at)
                        continue
                    there = cur.value(rec, slot, str(d["item"]))
                    value = fmt[int(d["id"])]
                    # NEW-EDC-8 (EDC-008): TrialBox's own write whose answer never came back; REDCap holding its value
                    # means it landed, under the person who sent it then
                    att = self.store.open_attempt(rs, d["record"], d["visit"], d["item"])
                    # NEW-EDC-8c: an erase attempt (a blank value) is never a landed write of TrialBox's value
                    landed = att is not None and bool(att["value"]) and there == forms.redcap_value(lf, att["value"])
                    if slot.repeat:  # NEW-EDC-2: the instance is judged whole, at its first value, on REDCap's rows
                        k = lay.key(rec, slot)
                        if k not in judged:
                            judged[k] = self._not_ours(rs, cur, live, rec, slot, str(d["record"]))
                        if judged[k]:
                            taken.add(k)
                            if landed and att is not None:  # TrialBox's write landed then; the instance changed since
                                self._landed(rs, {**d, "id": att["draft_id"], "final": att["value"]}, rec, att, by, at)
                            wrote = self.store.last_written(rs, d["record"], d["visit"], d["item"])
                            ours = forms.redcap_value(lf, wrote) if wrote else ""
                            if there and there not in (value, ours) and not landed:
                                out["conflict"].append({**_brief(d), "redcap": there})
                                self.store.record_sent(rs, d, "redcap", rec, "conflict", CONFLICT, by, at)
                            else:
                                out["instance_taken"].append(_brief(d))
                                self.store.record_sent(rs, d, "redcap", rec, "instance_taken", INSTANCE_TAKEN, by, at)
                            continue
                    if there == value and landed and att is not None:
                        out["sent"].append(_brief(d))
                        self._landed(rs, {**d, "id": att["draft_id"], "final": att["value"]}, rec, att, by, at)
                        if int(att["draft_id"]) != int(d["id"]):  # signed again since, the same value: already there
                            self.store.record_sent(rs, d, "redcap", rec, "already_there", "", by, at)
                        continue
                    if there == value:
                        out["already_there"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", rec, "already_there", "", by, at)
                        continue
                    # NEW-EDC-8b (EDC-012): ownership from TrialBox's own writes; `already_there` is the person's
                    last = self.store.last_written(rs, d["record"], d["visit"], d["item"])
                    if landed and there:  # review finding: TrialBox's lost write, or a person's equal entry
                        if slot.repeat:
                            taken.add(lay.key(rec, slot))
                        out["conflict"].append({**_brief(d), "redcap": there})
                        self.store.record_sent(rs, d, "redcap", rec, "conflict", ATTEMPT_HELD, by, at)
                        continue
                    if there and there != (forms.redcap_value(lf, last) if last else ""):
                        if slot.repeat:  # NEW-EDC-2: the instance is someone else's; nothing of TrialBox's goes in
                            taken.add(lay.key(rec, slot))
                        out["conflict"].append({**_brief(d), "redcap": there})
                        self.store.record_sent(rs, d, "redcap", rec, "conflict", "REDCap holds another value that "
                                               "TrialBox did not write; not overwritten", by, at)  # fmt: skip
                        continue
                    planned.append((d, rec, slot))
                    cur.lay(rec, slot, str(d["item"]), value)
                # NEW-EDC-2 (EDC-002): a repeat instance is written whole or not at all. One that holds a value on any
                # of its fields that TrialBox did not write is another person's entry or another event: every value
                # of TrialBox's for it is held, never merged into it field by field
                for d, rec, slot in list(planned):
                    k = lay.key(rec, slot)
                    if slot.repeat and k in taken:
                        taken.add(k)
                        planned.remove((d, rec, slot))
                        cur.unlay(rec, slot, str(d["item"]))
                        out["instance_taken"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", rec, "instance_taken", INSTANCE_TAKEN, by, at)
                # T-302b: a value for a field REDCap would hide (with what is about to be sent laid over the row) is
                # not sent; holding one back can hide another, so this runs until nothing changes
                changed = True
                while changed:
                    changed = False
                    for d, rec, slot in list(planned):
                        try:
                            ok, why = cur.shown(rec, slot, str(d["item"])), "hidden"
                        except LogicError:
                            ok, why = False, "logic"
                        if not ok:
                            planned.remove((d, rec, slot))
                            cur.unlay(rec, slot, str(d["item"]))
                            out[why].append(_brief(d))
                            self.store.record_sent(rs, d, "redcap", rec, why, PLACEMENT[why], by, at)
                            changed = True
                for d, rec, slot in planned:
                    row = imports.setdefault(lay.key(rec, slot), lay.import_row(rid, rec, slot))
                    row[str(d["item"])] = fmt[int(d["id"])]
                if imports:
                    # re-read each value just before the import: one edited or withdrawn since is not sent (E-17)
                    still = {int(x["id"]) for x in self.store.sendable(rs, record)}
                    stale = [(d, rec, slot) for d, rec, slot in planned if int(d["id"]) not in still]
                    for d, rec, slot in stale:
                        imports[lay.key(rec, slot)].pop(str(d["item"]), None)
                        self.store.record_sent(rs, d, "redcap", rec, "changed", "changed since the send began; "
                                               "not sent", by, at)  # fmt: skip
                    planned = [p for p in planned if int(p[0]["id"]) in still]
                    imports = {k: v for k, v in imports.items() if set(v) - KEY_COLS - {rid}}
                if imports:
                    # NEW-EDC-8 (EDC-008): the ledger says what is about to be written, and by whom, before REDCap is
                    # asked: an import REDCap applies whose answer is lost still has its line, read back next send
                    for d, rec, _slot in planned:
                        self.store.record_sent(rs, d, "redcap", rec, "attempt", ATTEMPT, by, at)
                        attempted += 1
                    # NEW-EDC-7 (EDC-007): one record REDCap refuses does not stop the others
                    imports = {key: flat(row, live, partial(cur.held_at, key))  # NEW-EDC-3b: checkbox columns
                               for key, row in imports.items()}  # fmt: skip
                    refused, first, unanswered = self._import(c, imports)
                    for d, rec, slot in planned:
                        if lay.key(rec, slot) in refused:
                            out["refused"].append(_brief(d))
                            self.store.record_sent(rs, d, "redcap", rec, "refused", "REDCap refused the import of "
                                                   f"this row: {refused[lay.key(rec, slot)]}", by, at)  # fmt: skip
                    if unanswered is not None:
                        raise unanswered
                    planned = [p for p in planned if lay.key(p[1], p[2]) not in refused]
                    if first is not None and not planned:
                        raise first
                    touched = sorted({k[0] for k in imports if k not in refused})
                    back = Rows(lay, meta, rid, c.records(fields=[rid, *items, *sorted(look - set(items))],
                                                          records=touched), self.today())  # fmt: skip
                    for d, rec, slot in planned:
                        got = back.value(rec, slot, str(d["item"]))
                        if got == fmt[int(d["id"])]:
                            out["sent"].append(_brief(d))
                            self.store.record_sent(rs, d, "redcap", rec, "sent", "read back equal", by, at)
                        else:
                            out["readback"].append({**_brief(d), "redcap": got})
                            self.store.record_sent(rs, d, "redcap", rec, "readback", "read back differs", by, at)
                    # T-302b: what REDCap computed beside TrialBox's own reading of the equation, and values REDCap
                    # now hides (never erased here: see erase_hidden)
                    names = {(rec, slot): str(d["record"]) for d, rec, slot in planned}
                    for (rec, slot), name in sorted(names.items(), key=lambda x: (x[0][0], x[0][1].visit)):
                        for cv in back.calcs(rec, slot):
                            calc_out.append({"record": name, "visit": slot.visit, **cv})
                        for f in back.hidden_values(rec, slot):
                            last = self.store.last_written(rs, name, slot.visit, f)  # NEW-EDC-8b
                            mine = last is not None and last != "" and f in live and forms.redcap_value(
                                live[f], last) == back.value(rec, slot, f)  # fmt: skip
                            hidden_out.append({"record": name, "visit": slot.visit, "item": f, "trialbox": mine})
        except RcError as exc:
            self._audit("edc.sent", rs, by, {"record": record or "*", "refused": exc.code, "attempted": attempted})
            raise EdcError(exc.code, exc.message, 502 if exc.code == "RC-UPSTREAM" else 409) from exc
        self._audit("edc.sent", rs, by, {"record": record or "*", "target": target["token_ref"],
                                         # NEW-EDC-7: an audit line's "refused" is a refused send's code
                                         **{("records_refused" if k == "refused" else k): len(v)
                                            for k, v in out.items()},
                                         "calc_differs": sum(1 for x in calc_out if x["equal"] is False),
                                         "hidden_in_redcap": len(hidden_out)})  # fmt: skip
        drift, unread = self._reread(rs, by, record)  # NEW-EDC-5: after the send's own audit line
        return {**out, "changed_in_redcap": drift, "reread": unread, "count": len(out["sent"]), "calc": calc_out,
                "hidden_in_redcap": hidden_out}  # fmt: skip

    def _reread(self, rs: str, by: str, record: str | None) -> tuple[list[dict[str, Any]], str]:
        """The send's re-read (NEW-EDC-5): the changes in REDCap and "", or none and why REDCap could not be read now
        (the send itself is done and audited; the next send or a reconcile reads again)."""
        try:
            return self.reconcile(rs, by, record), ""
        except EdcError as exc:
            return [], exc.code
        except Exception as exc:  # the values are written: the send answers, and the re-read says why not
            log.error("EDC re-read after the send failed for study %s (%s)", rs, type(exc).__name__)
            return [], "edc.reread"

    def reconcile(self, rs: str, by: str, record: str | None = None) -> list[dict[str, Any]]:
        """NEW-EDC-5 (EDC-005): read REDCap for every value TrialBox delivered (signed, sent as it is, and written by
        TrialBox itself at least once: a value only ever found already there is the person's, D-693) and list each
        one REDCap now holds differently, with both values. Each change gets one `changed_in_redcap` line in the
        ledger (the same change read again adds none). Taking REDCap's value is an edit with a reason; keeping
        TrialBox's leaves it listed. Audited."""
        self.store.require_on(rs)
        target = self.store.target(rs)
        if target is None:
            raise EdcError("edc.target", "no REDCap target is set for this study")
        gone = set(self.optouts())
        delivered = [d for d in self.store.signed(rs, record) if d["sent_at"] and d["sent_value"] == d["final"]
                     and str(d["pid"]) not in gone
                     and self.store.last_written(rs, d["record"], d["visit"], d["item"]) is not None]  # fmt: skip
        compared = 0
        drift: list[dict[str, Any]] = []
        if delivered:
            key, rid, at = str(target["key_field"]), str(target["id_field"]), self.stamp()
            try:
                with self.client(str(target["token_ref"])) as c:
                    lay = self._layout(c, rs, by, record)
                    meta = {str(m.get("field_name")): m for m in c.metadata()}
                    live = {f.name: f for f in (forms.field_of(m) for m in meta.values())}
                    items = sorted({str(d["item"]) for d in delivered if str(d["item"]) in live})
                    found: dict[str, set[str]] = {}
                    keys = c.records(fields=[rid, key])
                    if lay.repeats and keys and any("redcap_repeat_instance" not in r for r in keys):
                        raise EdcError("edc.repeat_keys", "the project repeats instruments or events, but REDCap's "
                                       "export has no redcap_repeat_instance: nothing is compared")  # fmt: skip
                    for r in keys:
                        if str(r.get(key) or "").strip():
                            found.setdefault(str(r[key]).strip().upper(), set()).add(str(r[rid]))
                    ids = {k: next(iter(v)) for k, v in found.items() if len(v) == 1}
                    recs = sorted({ids[str(d["record"]).upper()] for d in delivered
                                   if str(d["record"]).upper() in ids})  # fmt: skip
                    cur = Rows(lay, meta, rid, c.records(fields=[rid, *items], records=recs) if recs and items
                               else [], self.today())  # fmt: skip
                    for d in delivered:
                        rec, slot, item = ids.get(str(d["record"]).upper()), lay.slot(str(d["visit"])), str(d["item"])
                        if rec is None or slot is None or item not in live:
                            continue
                        if d.get("dict_sha") and forms.field_sha(live[item]) != d["dict_sha"]:
                            continue  # the entry changed since: the value is not formatted as REDCap holds it now
                        compared += 1
                        # what TrialBox last delivered there: its value, or "" after its own erase (D-414)
                        there = cur.value(rec, slot, item)
                        wrote = self.store.last_delivered(rs, d["record"], d["visit"], item)
                        ours = forms.redcap_value(live[item], wrote) if wrote else ""
                        last = self.store.last_redcap_line(rs, d["record"], d["visit"], item)
                        open_ = last is not None and last["result"] == "changed_in_redcap"
                        if there == ours:
                            if open_:  # equal again: the change is closed, with a line
                                self.store.record_sent(rs, d, "redcap", rec, "equal_again", "REDCap holds the "
                                                       "value TrialBox sent again", by, at)  # fmt: skip
                            continue
                        drift.append({**_brief(d), "trialbox": ours, "redcap": there})
                        mark = hashlib.sha256(there.encode("utf-8")).hexdigest()[:12]
                        if open_ and last is not None and f"[{mark}]" in last["detail"]:
                            continue  # the same change read again
                        self.store.record_sent(
                            rs, d, "redcap", rec, "changed_in_redcap", f"[{mark}] {CHANGED_SAYS}{there}", by, at
                        )
            except RcError as exc:
                self._audit("edc.reconciled", rs, by, {"record": record or "*", "refused": exc.code})
                raise EdcError(exc.code, exc.message, 502 if exc.code == "RC-UPSTREAM" else 409) from exc
        self._audit("edc.reconciled", rs, by, {"record": record or "*", "read": compared,
                                               "changed_in_redcap": len(drift)})  # fmt: skip
        return drift

    def _one_record(self, c: RedcapClient, target: dict[str, Any], record: str) -> str:
        key, rid = str(target["key_field"]), str(target["id_field"])
        rows = c.records(fields=[rid, key])
        hits = {str(r[rid]) for r in rows if str(r.get(key) or "").strip().upper() == record.upper()}
        if len(hits) > 1:
            raise EdcError("edc.duplicate_record", "the screening number is on more than one REDCap record")
        if not hits:
            raise EdcError("edc.no_record", "no REDCap record with this screening number")
        return next(iter(hits))

    def _row_of(self, c: RedcapClient, lay: Layout, visit: str) -> Slot:
        slot = lay.slot(visit or BASE_EVENT)
        if slot is None:
            raise EdcError("edc.no_slot", "the visit is not an event, or a repeat instance, of the REDCap project", 400)
        return slot

    def preview(self, rs: str, record: str, visit: str, by: str) -> dict[str, Any]:
        """What REDCap would make of one subject and visit's decided values, before they are sent (T-302b): the
        row they go to, the values that would not be written there and why (``misplaced``, ``hidden``, ``logic``),
        and each calculated field of the row as TrialBox computes it beside what REDCap holds now. Reads REDCap;
        writes nothing there. Audited (no value in the audit)."""
        self.store.require_on(rs)
        target = self.store.target(rs)
        if target is None:
            raise EdcError("edc.target", "no REDCap target is set for this study")
        vis = visit or BASE_EVENT
        decided = [d for d in self.store.drafts(rs, record, vis) if d["fate"] in ("confirmed", "edited")]
        self._not_opted_out(rs, by, "edc.preview", {str(d["pid"]) for d in decided}, {"record": record})
        rid = str(target["id_field"])
        try:
            with self.client(str(target["token_ref"])) as c:
                lay = self._layout(c, rs, by, record)
                slot = self._row_of(c, lay, vis)
                meta = {str(m.get("field_name")): m for m in c.metadata()}
                live = {f.name: f for f in (forms.field_of(m) for m in meta.values())}
                rec = self._one_record(c, target, record)
                items = sorted({str(d["item"]) for d in decided if str(d["item"]) in live})
                on_row = {str(m.get("form_name")) for m in meta.values()
                          if not lay.misplaced(slot, str(m.get("form_name")), set())}  # fmt: skip
                look = watched(meta, on_row | {live[i].form for i in items}, items) | self._slot_fields(lay, meta, slot)
                cur = Rows(lay, meta, rid, c.records(fields=[rid, *items, *sorted(look - set(items))], records=[rec]),
                           self.today())  # fmt: skip
                if lay.longitudinal:  # CGRD-B3 (D-841): the record's arms from every row it has
                    cur.know_events(c.records(fields=[rid], records=[rec]))
                taken = bool(slot.repeat and self._not_ours(rs, cur, live, rec, slot, record))
        except RcError as exc:
            raise EdcError(exc.code, exc.message, 502 if exc.code == "RC-UPSTREAM" else 409) from exc
        misplaced, hidden = [], []
        arms = cur.arms(rec)
        for d in decided:
            item = str(d["item"])
            if item not in live:
                misplaced.append({"item": item, "why": "dictionary_changed"})
                continue
            where = lay.misplaced(slot, live[item].form, arms)
            if where:
                misplaced.append({"item": item, "why": where})
            else:
                cur.lay(rec, slot, item, forms.redcap_value(live[item], str(d["final"])))
        for d in decided:
            item = str(d["item"])
            if item in live and not lay.misplaced(slot, live[item].form, arms):
                try:
                    if not cur.shown(rec, slot, item):
                        hidden.append({"item": item, "why": "hidden"})
                except LogicError:
                    hidden.append({"item": item, "why": "logic"})
        calcs = cur.calcs(rec, slot)
        out = {"visit": vis, "event": slot.event, "instrument": slot.instrument, "instance": slot.instance,
               "misplaced": misplaced, "hidden": hidden, "calc": calcs,
               "instance_taken": taken}  # fmt: skip  # NEW-EDC-2: every value would be held
        self._audit("edc.preview", rs, by, {"record": record, "visit": vis, "misplaced": len(misplaced),
                                            "hidden": len(hidden), "calc": len(calcs)})  # fmt: skip
        return out

    def erase_hidden(self, rs: str, record: str, visit: str, by: str) -> dict[str, Any]:
        """REDCap's "erase hidden values" for what TrialBox wrote (T-302b): on one subject's row, a field whose
        branching logic now hides it and that still holds the value TrialBox last sent there is erased in REDCap
        (``overwriteBehavior=overwrite`` with that field alone). A hidden value someone else wrote is listed, never
        erased: the coordinator decides on it in REDCap. Each erase is kept in ``sent`` (``erased``) and read back;
        the call is audited, refusals too."""
        vis = visit or BASE_EVENT
        try:
            self.store.require_on(rs)
            target = self.store.target(rs)
            if target is None:
                raise EdcError("edc.target", "no REDCap target is set for this study")
        except EdcError as exc:
            self._audit("edc.erase_hidden", rs, by, {"record": record, "visit": vis, "refused": exc.code})
            raise
        mine = self.store.drafts(rs, record, vis)
        self._not_opted_out(rs, by, "edc.erase_hidden", {str(d["pid"]) for d in mine}, {"record": record})
        rid, at = str(target["id_field"]), self.stamp()
        erased: list[str] = []
        kept: list[dict[str, str]] = []
        unread: list[str] = []  # erased, but the read-back was not blank
        try:
            with self.client(str(target["token_ref"])) as c:
                lay = self._layout(c, rs, by, record)
                slot = self._row_of(c, lay, vis)
                meta = {str(m.get("field_name")): m for m in c.metadata()}
                live = {f.name: f for f in (forms.field_of(m) for m in meta.values())}
                rec = self._one_record(c, target, record)
                on_row = {str(m.get("form_name")) for m in meta.values()
                          if not lay.misplaced(slot, str(m.get("form_name")), set())}  # fmt: skip
                look = sorted(watched(meta, on_row, []))
                cur = Rows(lay, meta, rid, c.records(fields=[rid, *look], records=[rec]), self.today())
                for f in cur.hidden_values(rec, slot):
                    last = self.store.last_written(rs, record, vis, f)  # NEW-EDC-8b: never a person's value
                    if last and f in live and forms.redcap_value(live[f], last) == cur.value(rec, slot, f):
                        erased.append(f)
                    else:
                        kept.append({"item": f, "why": "not_written_by_trialbox"})
                if erased:
                    # NEW-EDC-8c: the erase is ledgered as an attempt first, as the send is (D-691)
                    drafts_of = {f: next((x for x in reversed(mine) if str(x["item"]) == f and x.get("sent_at")),
                                         None) for f in erased}  # fmt: skip
                    for d in drafts_of.values():
                        if d is not None:
                            self.store.record_sent(rs, {**d, "final": ""}, "redcap", rec, "attempt", ATTEMPT, by, at)
                    try:
                        c.import_records([flat({**lay.import_row(rid, rec, slot), **dict.fromkeys(erased, "")}, live,
                                               lambda f: cur.held(rec, slot, f))],
                                         erase=True)  # fmt: skip
                    except RcError as exc:
                        if exc.refused:  # REDCap said no: nothing was erased, and the attempt is closed
                            for d in drafts_of.values():
                                if d is not None:
                                    self.store.record_sent(
                                        rs,
                                        {**d, "final": ""},
                                        "redcap",
                                        rec,
                                        "refused",
                                        f"REDCap refused the erase: {exc.message}",
                                        by,
                                        at,
                                    )
                        raise
                    back = Rows(lay, meta, rid, c.records(fields=[rid, *look], records=[rec]), self.today())
                    for f in erased:
                        d = next((x for x in reversed(mine) if str(x["item"]) == f and x.get("sent_at")), None)
                        if d is None:  # pragma: no cover - last_written found a send, so its draft exists
                            continue
                        ok = back.value(rec, slot, f) == ""
                        if not ok:  # NEW-EDC-3b review: what did not read back blank is not called erased
                            unread.append(f)
                        self.store.record_sent(rs, {**d, "final": ""}, "redcap", rec, "erased" if ok else "readback",
                                               "hidden by REDCap's branching logic; erased" if ok else
                                               "the erase did not read back blank", by, at)  # fmt: skip
        except RcError as exc:
            self._audit("edc.erase_hidden", rs, by, {"record": record, "visit": vis, "refused": exc.code})
            raise EdcError(exc.code, exc.message, 502 if exc.code == "RC-UPSTREAM" else 409) from exc
        except EdcError as exc:
            self._audit("edc.erase_hidden", rs, by, {"record": record, "visit": vis, "refused": exc.code})
            raise
        kept += [{"item": f, "why": "erase_did_not_read_back"} for f in unread]
        erased = [f for f in erased if f not in unread]
        self._audit("edc.erase_hidden", rs, by, {"record": record, "visit": vis, "erased": erased,
                                                 "kept": [k["item"] for k in kept]})  # fmt: skip
        return {"erased": erased, "kept": kept}

    def export_odm(self, rs: str, by: str, meaning_text: str = ODM_MEANING) -> str:
        self.store.require_on(rs)
        gone = set(self.optouts())
        values = [d for d in self.store.signed(rs) if str(d["pid"]) not in gone]  # never an opted-out patient
        changed = sorted({f"{d['record']} {d['item']}" for d in values if d.get("source_changed")})
        if changed:  # NEW-EDC-4: a copy a person can import into REDCap waits, never a silent gap (E-22)
            self._audit("edc.export", rs, by, {"format": "odm", "refused": "edc.source_changed", "items": changed})
            raise EdcError("edc.source_changed", "the source changed since these signed values were decided; keep or "
                           "change each first: " + ", ".join(changed))  # fmt: skip
        mapped, fields = {str(m["item"]) for m in self.store.map(rs)}, self.dc.fields(rs)
        lost = sorted({str(d["item"]) for d in values if str(d["item"]) not in mapped or str(d["item"]) not in fields})
        if lost:  # never a silent gap in the copy of signed records (review E-22)
            self._audit("edc.export", rs, by, {"format": "odm", "refused": "edc.odm_gap", "items": lost})
            err = EdcError("edc.odm_gap", "signed values whose item left the map or the dictionary: " + ", ".join(lost))
            err.problems = [{"item": i, "code": "not_in_map"} for i in lost]  # type: ignore[attr-defined]
            raise err
        sigs_now = {int(s["id"]): s for s in self.store.signatures(rs)}
        used = {int(d["signature_id"]) for d in values if d.get("signature_id") is not None}

        def texts(v: Any) -> list[str]:
            if isinstance(v, dict):
                return [t for x in v.values() for t in texts(x)]
            if isinstance(v, str) and v[:1] in "{[":  # a citation is stored as JSON text
                try:
                    return texts(json.loads(v))
                except ValueError:
                    return [v]
            return [] if v is None else [str(v)]

        def unfit(row: dict[str, Any], names: tuple[str, ...]) -> bool:
            return any(forms.XML_ILLEGAL.search(t) for n in names for t in texts(row.get(n)))

        # every text of a signed row that the file carries: the value, its reason, its citation, its keys and who
        # decided; and the signature's own words. Nothing under a signature is ever rewritten to make it fit
        chars = sorted(
            {str(d["item"]) for d in values
             if unfit(d, ("final", "reason", "final_citation", "citation", "record", "visit", "decided_by"))}
            | {f"signature {i}" for i in sorted(used)
               if i in sigs_now and unfit(sigs_now[i], ("signer", "printed_name", "role", "meaning", "meaning_text"))}
        )  # fmt: skip
        if chars:  # EDC-010 (D-581): a row from before the rule; never written broken, never altered
            self._audit("edc.export", rs, by, {"format": "odm", "refused": "edc.odm_chars", "items": chars})
            err = EdcError("edc.odm_chars", "signed values that hold a character an XML file cannot carry: "
                           + ", ".join(chars))  # fmt: skip
            err.problems = [{"item": i, "code": "chars"} for i in chars]  # type: ignore[attr-defined]
            raise err
        sigs = {int(s["id"]): s for s in self.store.signatures(rs)}
        text = odm.build(rs, self.dc.fields(rs), self.store.map(rs), values, sigs, meaning_text, self.stamp())
        retired = sorted(f"{d['record']} {d['visit']} {d['item']}" for d in self.store.drafts(rs)
                         if d["fate"] == "retired" and str(d["pid"]) not in gone)  # fmt: skip
        self._audit("edc.export", rs, by, {"format": "odm", "values": len(values),
                                           "sha": hashlib.sha256(text.encode()).hexdigest()[:16],
                                           **({"retired": retired} if retired else {})})  # fmt: skip
        return text

    def _pid_of(self, rs: str, record: str) -> str | None:
        """The pseudonym a record key is bound to: its drafts', else the lifecycle subject's (D-435)."""
        for d in self.store.drafts(rs, record, current=False):
            return str(d["pid"])
        from datacore.lifecycle import Lifecycle

        sub = Lifecycle(self.dc).subject(rs, record)
        return str(sub["pid"]) if sub is not None and sub.get("pid") else None

    def import_odm(self, rs: str, data: bytes, by: str, name: str = "") -> dict[str, Any]:
        """Read a CDISC ODM file into open drafts that cite it (D-435): proposals a person confirms, edits or rejects
        and signs, never a decided or signed value. The file is refused whole on any problem (``odm.*``), and so
        when a record is unknown, opted out, or drafted for another subject. Audited, refusals too (the file's
        sha256 and counts, never a value)."""
        from edc import odm_import as oi

        sha = hashlib.sha256(data).hexdigest()
        detail: dict[str, Any] = {"file": sha[:16], "bytes": len(data)}
        try:
            self.store.require_drafting(rs)
            items = [mapping.ItemMap.from_dict(i) for i in self.store.map(rs)]
            if not items:
                raise EdcError("edc.no_map", "save the item map first")
            fields = self.dc.fields(rs)
            target = self.store.target(rs)
            try:
                f = oi.read(data, f"Project.{odm._oid(rs)}")
                props = oi.proposals(f, fields, [m.item for m in items], protected=self._protected(rs, target))
            except oi.OdmRefused as exc:
                err = EdcError(exc.code, exc.message + (f" ({exc.where})" if exc.where else ""), 422)
                err.problems = [{"code": exc.code, "where": exc.where}]  # type: ignore[attr-defined]
                raise err from exc
            if not props:
                raise EdcError("odm.empty", "the file holds no value for an item of the study's map", 422)
            pids: dict[str, str] = {}
            for rec in sorted({p.record for p in props}):
                pid = self._pid_of(rs, rec)
                if pid is None:
                    raise EdcError("odm.unknown_subject", f"record {rec} is not a subject of this study", 422)
                pids[rec] = pid
        except EdcError as exc:
            self._audit("edc.odm_import", rs, by, {**detail, "refused": exc.code})
            raise
        self._not_opted_out(rs, by, "edc.odm_import", set(pids.values()), detail)
        by_item = {m.item: m for m in items}
        shas = {m.item: mapping.item_sha(m) for m in items}
        at = self.stamp()
        dates = {(str(d["record"]), str(d["visit"])): str(d["visit_date"]) for r in pids
                 for d in self.store.drafts(rs, r)}  # fmt: skip
        rows = [{"record": p.record, "pid": pids[p.record], "visit": p.visit,
                 "visit_date": dates.get((p.record, p.visit), at[:10]), "item": p.item, "form": p.form,
                 "cdash": by_item[p.item].cdash, "test": by_item[p.item].test, "value": p.value,
                 "why": "", "citation": oi.citation(f, p, name), "version": f"odm:{sha[:16]}",
                 "map_sha": shas[p.item], "dict_sha": forms.field_sha(fields[p.item]),
                 "target": str(target["token_ref"]) if target else ""} for p in props]  # fmt: skip
        try:
            out = self.store.add_proposals(rs, rows, f"odm-{sha[:12]}", by, at)
        except EdcError as exc:
            self._audit("edc.odm_import", rs, by, {**detail, "refused": exc.code})
            raise
        counts = {k: len(v) for k, v in out.items()}
        self._audit("edc.odm_import", rs, by, {**detail, "name": name[:120], "file_oid": f.file_oid[:80],
                                               "records": len(pids), **counts})  # fmt: skip
        return {"file": sha, "name": name[:120], "file_oid": f.file_oid, **out}

    @staticmethod
    def _slot_fields(lay: Any, meta: dict[str, Any], slot: Any) -> set[str]:
        """Every field that lives on a repeat instance (NEW-EDC-2): the repeating instrument's, or for a repeating
        event every instrument designated for it."""
        if slot is None or not slot.repeat:
            return set()
        on = {slot.instrument} if slot.instrument else (lay.designated.get(slot.event) or set())
        return {f for f, m in meta.items() if str(m.get("form_name") or "") in on or not on}

    def _instance_fields(self, lay: Any, meta: dict[str, Any], todo: list[dict[str, Any]]) -> set[str]:
        """Every field on the repeat instances the send touches."""
        out: set[str] = set()
        for d in todo:
            out |= self._slot_fields(lay, meta, lay.slot(str(d["visit"])))
        return out

    @staticmethod
    def _import(
        c: RedcapClient, imports: dict[Any, dict[str, str]]
    ) -> tuple[dict[Any, str], RcError | None, RcError | None]:
        """Import the rows; when REDCap refuses an import of several rows (it refuses an import whole), send again
        one row at a time (NEW-EDC-7). Returns the rows REDCap refused (by row key), each with the kind of error
        (never REDCap's text, D-555); the first refusal; and an error that was not a refusal met on the way (REDCap
        did not answer: the caller ledgers the refusals before raising it; what was not answered may have applied,
        D-691 reads it back next send)."""
        try:
            c.import_records(list(imports.values()))
            return {}, None, None
        except RcError as exc:
            if not exc.refused:
                raise
            first = exc
        if len(imports) == 1:
            return dict.fromkeys(imports, first.message), first, None
        refused: dict[Any, str] = {}
        for key, row in imports.items():
            try:
                c.import_records([row])
            except RcError as exc:
                if not exc.refused:
                    return refused, first, exc
                refused[key] = exc.message
        return refused, first, None

    def _landed(self, rs: str, d: dict[str, Any], rec: str, att: dict[str, Any], by: str, at: str) -> None:
        """An attempt read back equal (NEW-EDC-8): ``sent`` under the person and time of the attempt, which is when
        REDCap took the value; the line names who read it back, and when."""
        self.store.record_sent(rs, d, "redcap", rec, "sent", f"written by the send of {att['by_user']} at "
                               f"{att['at']}, whose answer from REDCap was lost; read back equal by {by} at {at}",
                               str(att["by_user"]), str(att["at"]))  # fmt: skip

    def _not_ours(self, rs: str, cur: Any, live: dict[str, Any], rec: str, slot: Any, record: str) -> bool:
        """Whether a repeat instance holds, on any field a person can enter, something other than what TrialBox
        itself last wrote there (NEW-EDC-2): a value TrialBox never wrote (an ``already_there`` is not TrialBox's),
        a value changed since, or a value of TrialBox's that a person cleared. What REDCap holds is read, never
        what the send is about to lay over it. A calculated or descriptive field is REDCap's own and is not judged;
        a checkbox is the codes ticked in its ``field___code`` columns (NEW-EDC-3b), judged as any value."""
        for f in cur.on_row(rec, slot):
            kind = str((cur.meta.get(f) or {}).get("field_type") or "")
            if kind in ("calc", "descriptive"):
                continue
            there = cur.held(rec, slot, f)  # a checkbox is its ticked codes (NEW-EDC-3b): judged as any value
            att = self.store.open_attempt(rs, record, slot.visit, f)  # NEW-EDC-8: TrialBox's write, answer lost
            if att is not None and f in live and there and there == forms.redcap_value(live[f], att["value"]):
                continue
            wrote = self.store.last_written(rs, record, slot.visit, f)
            if wrote is None:
                if there:
                    return True
                continue
            if f not in live or (forms.redcap_value(live[f], wrote) if wrote else "") != there:
                return True
        return False

    def trail(self, rs: str, record: str) -> dict[str, Any]:
        return self.store.trail(rs, record)


#: what the send answers per value: written, or held back with the reason (T-115, D-368, D-690; NEW-EDC-7: refused)
SEND_RESULTS = ("sent", "already_there", "conflict", "no_record", "readback", "opted_out", "duplicate", "no_event",
                "target_changed", "stale_map", "dictionary_changed", "format", "not_on_event", "wrong_arm",
                "repeating_form", "not_repeating_form", "hidden", "logic", "instance_taken", "refused",
                "source_changed", "changed_in_redcap")  # fmt: skip
#: NEW-EDC-2 (EDC-002): why every value for a repeat instance is held
ATTEMPT = "about to be written; REDCap's answer not read yet"  # NEW-EDC-8: closed by the next read-back
ATTEMPT_HELD = ("REDCap holds the value of a TrialBox send whose answer was lost, or a person's equal entry; TrialBox "
                "cannot tell which: not overwritten")  # fmt: skip
CONFLICT = "REDCap holds another value that TrialBox did not write; not overwritten"
INSTANCE_TAKEN = (
    "the repeat instance holds a value TrialBox did not write (a person's entry or another event); "
    "nothing of TrialBox's is written into it: choose another instance"
)
#: why a value is not written to the row its visit names (T-302b, D-414), and the words kept in ``sent``
PLACEMENT = {
    "not_on_event": "the item's instrument is not designated for this event; not sent",
    "wrong_arm": "the record is on another arm of the project; not sent",
    "repeating_form": "the item is on a repeating instrument: it goes on an instance, not the base row; not sent",
    "not_repeating_form": "the item is not on this repeat instance's instrument; not sent",
    "hidden": "REDCap's branching logic hides the field on this row; not sent",
    "logic": "TrialBox cannot read the field's branching logic, so it cannot tell whether REDCap hides it; not sent",
}
#: the key columns of an import row
KEY_COLS = {"redcap_event_name", "redcap_repeat_instrument", "redcap_repeat_instance"}


def flat(row: dict[str, str], live: dict[str, Any], held: Callable[[str], str]) -> dict[str, str]:
    """An import row in REDCap's flat form (NEW-EDC-3b, EDC-003): a checkbox item becomes its choices' columns, named
    as REDCap names them (:func:`datacore.forms.checkbox_column`): ``1`` for each code chosen, and ``0`` only for a
    code REDCap held ticked when the row was read (``held``, the field's codes then). A code neither chosen nor held
    is not written: a box a person ticks after the read stays, and the read-back then differs (review F2). A blank (an
    erase) is ``0`` for each code held, never a blank REDCap could read as "leave it". Every other column is as it
    was."""
    out: dict[str, str] = {}
    for col, value in row.items():
        f = live.get(col)
        if f is None or f.kind != "multi":
            out[col] = value
            continue
        chosen = {c.strip() for c in str(value).split(",") if c.strip()}
        had = {c.strip() for c in held(col).split(",") if c.strip()}
        for code in f.options:
            if code in chosen:
                out[forms.checkbox_column(col, code)] = "1"
            elif code in had:
                out[forms.checkbox_column(col, code)] = "0"
    return out


def _brief(d: dict[str, Any]) -> dict[str, Any]:
    return {"id": int(d["id"]), "record": d["record"], "visit": d["visit"], "item": d["item"]}
