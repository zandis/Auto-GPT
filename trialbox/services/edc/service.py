"""The EDC prefill service (D-160): the steps a study team takes, each checked and audited here.

The orchestrator's ``/studies/{rs}/edc/*`` routes call this; the console only shows the pages and re-authenticates
the signer. The rules are enforced here even when a page already checked them (defence in depth):

* the switch must be on (sponsor's written acknowledgement and the re-entry result on file) to draft, decide, sign,
  send or export; it is off by default;
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
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from datacore import forms
from datacore.export import BASE_EVENT
from datacore.store import DataCore
from rc_bridge.client import RcError, RedcapClient
from tb_common.audit import AuditLog
from tb_common.config import environment_name
from tb_common.llm import LlmError

from edc import mapping, odm, prefill
from edc.store import EdcError, EdcStore

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
        self._audit("edc.switch", rs, by, {"on": sw.on, "kind": sw.kind, "reference": sw.reference,
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
        self.store.require_on(rs)
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
        run_id = hashlib.sha256(f"{rs}|{record}|{visit}|{self.stamp()}".encode()).hexdigest()[:16]
        try:
            drafts = prefill.build(pid, vd, items, fields, self.facts(), self.drafter(run_id))
        except LlmError as exc:  # the gateway refused or the model failed: nothing is drafted, and the page says why
            why = model_failure(exc)
            log.error("EDC prefill: the box's model did not draft study %s record %s: %s", rs, record, why)
            self._audit("edc.drafts", rs, by, {"record": record, "visit": visit or BASE_EVENT, "run": run_id,
                                               "refused": "edc.model", "error": why})  # fmt: skip
            raise EdcError("edc.model", f"the box's model did not answer ({why})", 502) from exc
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
               citation: dict[str, Any] | None = None, by: str, unlock: bool = False) -> dict[str, Any]:  # fmt: skip
        """Confirm, edit or reject one draft. ``unlock``: the person re-authenticated just before, so a signed value
        may change (with a reason; D-281, CR-035). Every refusal is audited (SEC-7); the decision's audit line is
        written inside its transaction (SEC-6)."""
        try:
            self.store.require_on(rs)
            d = self.store.draft(rs, draft_id)
            if d is None:
                raise EdcError("edc.no_draft", "no such draft", 404)
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
                                                  if out.get("voided") is not None else {})})  # fmt: skip

        now: dict[str, str] | None = None
        try:
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
                                     built=now if action == "edit" else None)  # fmt: skip
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
            self.store.require_on(rs)
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
            return self.store.sign(rs, record, visit or BASE_EVENT, signer=signer, printed_name=printed_name,
                                   role=role, meaning=meaning, meaning_text=meaning_text, lang=lang,
                                   at=self.stamp(), seen=seen, method=method, before_commit=audited)  # fmt: skip
        except EdcError as exc:
            self._audit("edc.sign", rs, signer, {"record": record, "visit": visit, "refused": exc.code})
            raise

    # ------------------------------------------------------------------ send to REDCap, export ODM
    def send_redcap(self, rs: str, by: str, record: str | None = None) -> dict[str, Any]:
        self.store.require_on(rs)
        target = self.store.target(rs)
        if target is None:
            raise EdcError("edc.target", "no REDCap target is set for this study")
        out: dict[str, list[dict[str, Any]]] = {k: [] for k in SEND_RESULTS}
        at = self.stamp()
        gone = set(self.optouts())
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
                },
            )
            return {**out, "count": 0}
        key, rid = str(target["key_field"]), str(target["id_field"])
        try:
            with self.client(str(target["token_ref"])) as c:
                proj = c.project()
                if int(proj.get("has_repeating_instruments_or_events") or 0):
                    # a flat export has one more row per repeat; the "never overwrite" check cannot hold (E-05)
                    self._audit("edc.sent", rs, by, {"record": record or "*", "refused": "edc.repeating"})
                    raise EdcError("edc.repeating", "the REDCap project has repeating instruments or events; "
                                   "prefill does not send to it")  # fmt: skip
                longitudinal = bool(int(proj.get("is_longitudinal") or 0))
                events = {str(e.get("unique_event_name")) for e in c.events()} if longitudinal else {BASE_EVENT}
                # T-115 (E-15, E-16, STD-061): the project's dictionary of now, the map of now, and the target
                live = {f.name: f for f in (forms.field_of(m) for m in c.metadata())}
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
                found: dict[str, set[str]] = {}
                for r in rows:
                    if str(r.get(key) or "").strip():
                        found.setdefault(str(r[key]).strip().upper(), set()).add(str(r[rid]))
                ids = {k: next(iter(v)) for k, v in found.items() if len(v) == 1}
                twice = {k for k, v in found.items() if len(v) > 1}
                cur = {(str(r[rid]), str(r.get("redcap_event_name") or "") if longitudinal else ""): r for r in rows}
                imports: dict[tuple[str, str], dict[str, str]] = {}
                planned: list[tuple[dict[str, Any], str, str]] = []
                for d in todo:
                    if str(d["record"]).upper() in twice:  # a wrong-subject write is worse than none (E-06)
                        out["duplicate"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", "", "duplicate", "the screening number is on more "
                                               "than one REDCap record; not sent", by, at)  # fmt: skip
                        continue
                    if str(d["visit"]) not in events:  # the visit must be an event of the project (E-04)
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
                    ev = str(d["visit"]) if longitudinal else ""
                    there = str((cur.get((rec, ev)) or {}).get(d["item"]) or "")
                    value = fmt[int(d["id"])]
                    if there == value:
                        out["already_there"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", rec, "already_there", "", by, at)
                        continue
                    last = self.store.last_sent(rs, d["record"], d["visit"], d["item"])
                    lf = live[str(d["item"])]
                    if there and there != (forms.redcap_value(lf, last) if last else ""):
                        out["conflict"].append({**_brief(d), "redcap": there})
                        self.store.record_sent(rs, d, "redcap", rec, "conflict", "REDCap holds another value that "
                                               "TrialBox did not write; not overwritten", by, at)  # fmt: skip
                        continue
                    row = imports.setdefault((rec, ev), {rid: rec, **({"redcap_event_name": ev} if ev else {})})
                    row[str(d["item"])] = value
                    planned.append((d, rec, ev))
                if imports:
                    # re-read each value just before the import: one edited or withdrawn since is not sent (E-17)
                    still = {int(x["id"]) for x in self.store.sendable(rs, record)}
                    stale = [(d, rec, ev) for d, rec, ev in planned if int(d["id"]) not in still]
                    for d, rec, ev in stale:
                        imports[(rec, ev)].pop(str(d["item"]), None)
                        self.store.record_sent(rs, d, "redcap", rec, "changed", "changed since the send began; "
                                               "not sent", by, at)  # fmt: skip
                    planned = [p for p in planned if int(p[0]["id"]) in still]
                    imports = {k: v for k, v in imports.items() if len(v) > (2 if longitudinal else 1)}
                if imports:
                    c.import_records(list(imports.values()))
                    back = {
                        (str(r[rid]), str(r.get("redcap_event_name") or "") if longitudinal else ""): r
                        for r in c.records(fields=[rid, *items], records=sorted({k[0] for k in imports}))
                    }
                    for d, rec, ev in planned:
                        got = str((back.get((rec, ev)) or {}).get(d["item"]) or "")
                        if got == fmt[int(d["id"])]:
                            out["sent"].append(_brief(d))
                            self.store.record_sent(rs, d, "redcap", rec, "sent", "read back equal", by, at)
                        else:
                            out["readback"].append({**_brief(d), "redcap": got})
                            self.store.record_sent(rs, d, "redcap", rec, "readback", "read back differs", by, at)
        except RcError as exc:
            self._audit("edc.sent", rs, by, {"record": record or "*", "refused": exc.code})
            raise EdcError(exc.code, exc.message, 502 if exc.code == "RC-UPSTREAM" else 409) from exc
        self._audit("edc.sent", rs, by, {"record": record or "*", "target": target["token_ref"],
                                         **{k: len(v) for k, v in out.items()}})  # fmt: skip
        return {**out, "count": len(out["sent"])}

    def export_odm(self, rs: str, by: str, meaning_text: str = ODM_MEANING) -> str:
        self.store.require_on(rs)
        gone = set(self.optouts())
        values = [d for d in self.store.signed(rs) if str(d["pid"]) not in gone]  # never an opted-out patient
        mapped, fields = {str(m["item"]) for m in self.store.map(rs)}, self.dc.fields(rs)
        lost = sorted({str(d["item"]) for d in values if str(d["item"]) not in mapped or str(d["item"]) not in fields})
        if lost:  # never a silent gap in the copy of signed records (review E-22)
            self._audit("edc.export", rs, by, {"format": "odm", "refused": "edc.odm_gap", "items": lost})
            err = EdcError("edc.odm_gap", "signed values whose item left the map or the dictionary: " + ", ".join(lost))
            err.problems = [{"item": i, "code": "not_in_map"} for i in lost]  # type: ignore[attr-defined]
            raise err
        sigs = {int(s["id"]): s for s in self.store.signatures(rs)}
        text = odm.build(rs, self.dc.fields(rs), self.store.map(rs), values, sigs, meaning_text, self.stamp())
        self._audit("edc.export", rs, by, {"format": "odm", "values": len(values),
                                           "sha": hashlib.sha256(text.encode()).hexdigest()[:16]})  # fmt: skip
        return text

    def trail(self, rs: str, record: str) -> dict[str, Any]:
        return self.store.trail(rs, record)


#: what the send answers per value: written, or held back with the reason (the last four: T-115, D-368)
SEND_RESULTS = ("sent", "already_there", "conflict", "no_record", "readback", "opted_out", "duplicate", "no_event",
                "target_changed", "stale_map", "dictionary_changed", "format")  # fmt: skip


def _brief(d: dict[str, Any]) -> dict[str, Any]:
    return {"id": int(d["id"]), "record": d["record"], "visit": d["visit"], "item": d["item"]}
