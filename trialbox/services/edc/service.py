"""The EDC prefill service (D-160): the steps a study team takes, each checked and audited here.

The orchestrator's ``/studies/{rs}/edc/*`` routes call this; the console only shows the pages and re-authenticates
the signer. The rules are enforced here even when a page already checked them (defence in depth):

* the switch must be on (sponsor's written acknowledgement and the re-entry result on file) to draft, decide, sign,
  send or export; it is off by default;
* the map must pass :func:`edc.mapping.check` before it is saved;
* a value without a citation cannot be confirmed; an edit needs a reason and passes the field's own checks;
* only confirmed, signed values whose content still matches the signature are sent or exported;
* the REDCap send never overwrites a value someone else wrote in REDCap: it is listed as a conflict and skipped;
  every value sent is read back and compared.

Every step writes one audit event (``edc.*``) with who, the study and what changed (never a clinical value).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from datacore import forms
from datacore.export import BASE_EVENT
from datacore.store import DataCore
from rc_bridge.client import RcError, RedcapClient
from tb_common.audit import AuditLog

from edc import mapping, odm, prefill
from edc.store import EdcError, EdcStore

ODM_MEANING = ("By my electronic signature I confirm that I checked each value against the cited hospital record "
               "and that the values are correct for this subject and visit.")  # fmt: skip


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

    def stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def _audit(self, event: str, rs: str, by: str, detail: dict[str, Any]) -> None:
        self.audit.append(event, ruleset=rs, actor=by, detail=detail)

    # ------------------------------------------------------------------ status and switch
    def status(self, rs: str) -> dict[str, Any]:
        sw = self.store.switch(rs)
        items = self.store.map(rs)
        return {"switch": sw.as_dict(), "events": self.store.switch_events(rs)[-10:], "map": items,
                "target": self.store.target(rs), "mapped": sum(1 for i in items if i.get("source", "none") != "none"),
                "subjects": self.store.subjects(rs), "fields": len(self.dc.fields(rs))}  # fmt: skip

    def set_switch(self, rs: str, on: bool, *, by: str, role: str, **ack: Any) -> dict[str, Any]:
        try:
            sw = self.store.set_switch(rs, on, by=by, role=role, at=self.stamp(), today=self.today(), **ack)
        except EdcError as exc:
            self._audit("edc.switch", rs, by, {"on": on, "refused": exc.code})
            raise
        self._audit("edc.switch", rs, by, {"on": sw.on, "kind": sw.kind, "reference": sw.reference,
                                           "ack_date": sw.ack_date, "reentry_pages": sw.reentry_pages,
                                           "reentry_accuracy": sw.reentry_accuracy, "role": role})  # fmt: skip
        return sw.as_dict()

    # ------------------------------------------------------------------ dictionary and map
    def import_dictionary(self, rs: str, token_ref: str, by: str, record_field: str = "") -> dict[str, Any]:
        """Read the REDCap project's data dictionary through the API into the study's forms (identifiers dropped)."""
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
        maps = [mapping.ItemMap.from_dict(i) for i in items]
        fields = self.dc.fields(rs)
        bad = mapping.check(maps, fields, self._protected(rs, target))
        if bad:
            err = EdcError("edc.map", "the map has problems")
            err.problems = bad  # type: ignore[attr-defined]
            raise err
        body = [m.as_dict() for m in maps]
        at = self.stamp()
        self.store.put_map(rs, body, by, at)
        self.store.put_target(rs, target["token_ref"], target["key_field"], target["id_field"], by, at)
        self._audit(
            "edc.map",
            rs,
            by,
            {
                "items": len(body),
                "drafted": sum(1 for m in maps if m.drafted),
                "target": target["token_ref"],
                "sha": hashlib.sha256(mapping.dumps(maps).encode()).hexdigest()[:16],
            },
        )
        return {"items": len(body), "drafted": sum(1 for m in maps if m.drafted)}

    # ------------------------------------------------------------------ drafts
    def build(self, rs: str, record: str, pid: str, visit: str, visit_date: str, by: str) -> list[dict[str, Any]]:
        self.store.require_on(rs)
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
        drafts = prefill.build(pid, vd, items, fields, self.facts(), self.drafter(run_id))
        rows = [d.as_dict() for d in drafts]
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
               citation: dict[str, Any] | None = None, by: str) -> dict[str, Any]:  # fmt: skip
        self.store.require_on(rs)
        d = self.store.draft(rs, draft_id)
        if d is None:
            raise EdcError("edc.no_draft", "no such draft", 404)
        if action == "edit":
            f = self.dc.fields(rs).get(str(d["item"]))
            if f is None:
                raise EdcError("edc.not_in_dictionary", "the item is no longer in the data dictionary")
            p = forms.problem(f, value.strip())
            if p is not None:
                err = EdcError("edc.invalid", forms.reason(p, value), 400)
                err.problems = [{"field": f.name, **p}]  # type: ignore[attr-defined]
                raise err
        try:
            out = self.store.decide(rs, draft_id, action, value=value, reason=reason, citation=citation, by=by,
                                    at=self.stamp())  # fmt: skip
        except EdcError as exc:
            self._audit("edc.decide", rs, by, {"draft": draft_id, "action": action, "refused": exc.code})
            raise
        self._audit("edc.decide", rs, by, {"draft": draft_id, "record": out["record"], "visit": out["visit"],
                                           "item": out["item"], "action": action, "fate": out["fate"],
                                           "reason": bool(reason.strip()),
                                           "citation": (out["final_citation"] or {}).get("kind", "")})  # fmt: skip
        return out

    def sign(self, rs: str, record: str, visit: str, *, signer: str, printed_name: str, role: str, meaning: str,
             meaning_text: str, lang: str) -> dict[str, Any]:  # fmt: skip
        """The console re-authenticated ``signer`` just before this call."""
        self.store.require_on(rs)
        try:
            sig = self.store.sign(rs, record, visit or BASE_EVENT, signer=signer, printed_name=printed_name,
                                  role=role, meaning=meaning, meaning_text=meaning_text, lang=lang,
                                  at=self.stamp())  # fmt: skip
        except EdcError as exc:
            self._audit("edc.sign", rs, signer, {"record": record, "visit": visit, "refused": exc.code})
            raise
        self._audit("edc.sign", rs, signer, {"record": record, "visit": sig["visit"], "signature": sig["id"],
                                             "meaning": meaning, "printed_name": printed_name, "role": role,
                                             "values": len(json.loads(sig["drafts"])),
                                             "content_sha": sig["content_sha"]})  # fmt: skip
        return sig

    # ------------------------------------------------------------------ send to REDCap, export ODM
    def send_redcap(self, rs: str, by: str, record: str | None = None) -> dict[str, Any]:
        self.store.require_on(rs)
        target = self.store.target(rs)
        if target is None:
            raise EdcError("edc.target", "no REDCap target is set for this study")
        todo = self.store.sendable(rs, record)
        out: dict[str, list[dict[str, Any]]] = {"sent": [], "already_there": [], "conflict": [], "no_record": [],
                                                "readback": []}  # fmt: skip
        if not todo:
            self._audit("edc.sent", rs, by, {"record": record or "*", "sent": 0})
            return {**out, "count": 0}
        key, rid = str(target["key_field"]), str(target["id_field"])
        at = self.stamp()
        try:
            with self.client(str(target["token_ref"])) as c:
                longitudinal = bool(int(c.project().get("is_longitudinal") or 0))
                items = sorted({str(d["item"]) for d in todo})
                rows = c.records(fields=[rid, key, *items])
                ids: dict[str, str] = {}
                for r in rows:
                    if str(r.get(key) or "").strip():
                        ids.setdefault(str(r[key]).strip().upper(), str(r[rid]))
                cur = {(str(r[rid]), str(r.get("redcap_event_name") or "") if longitudinal else ""): r for r in rows}
                imports: dict[tuple[str, str], dict[str, str]] = {}
                planned: list[tuple[dict[str, Any], str, str]] = []
                for d in todo:
                    rec = ids.get(str(d["record"]).upper())
                    if rec is None:
                        out["no_record"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", "", "no_record", "no REDCap record with this "
                                               "screening number", by, at)  # fmt: skip
                        continue
                    ev = str(d["visit"]) if longitudinal else ""
                    there = str((cur.get((rec, ev)) or {}).get(d["item"]) or "")
                    if there == d["final"]:
                        out["already_there"].append(_brief(d))
                        self.store.record_sent(rs, d, "redcap", rec, "already_there", "", by, at)
                        continue
                    if there and there != (self.store.last_sent(rs, d["record"], d["visit"], d["item"]) or ""):
                        out["conflict"].append({**_brief(d), "redcap": there})
                        self.store.record_sent(rs, d, "redcap", rec, "conflict", "REDCap holds another value that "
                                               "TrialBox did not write; not overwritten", by, at)  # fmt: skip
                        continue
                    row = imports.setdefault((rec, ev), {rid: rec, **({"redcap_event_name": ev} if ev else {})})
                    row[str(d["item"])] = str(d["final"])
                    planned.append((d, rec, ev))
                if imports:
                    c.import_records(list(imports.values()))
                    back = {
                        (str(r[rid]), str(r.get("redcap_event_name") or "") if longitudinal else ""): r
                        for r in c.records(fields=[rid, *items], records=sorted({k[0] for k in imports}))
                    }
                    for d, rec, ev in planned:
                        got = str((back.get((rec, ev)) or {}).get(d["item"]) or "")
                        if got == d["final"]:
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
        values = self.store.signed(rs)
        sigs = {int(s["id"]): s for s in self.store.signatures(rs)}
        text = odm.build(rs, self.dc.fields(rs), self.store.map(rs), values, sigs, meaning_text, self.stamp())
        self._audit("edc.export", rs, by, {"format": "odm", "values": len(values),
                                           "sha": hashlib.sha256(text.encode()).hexdigest()[:16]})  # fmt: skip
        return text

    def trail(self, rs: str, record: str) -> dict[str, Any]:
        return self.store.trail(rs, record)


def _brief(d: dict[str, Any]) -> dict[str, Any]:
    return {"id": int(d["id"]), "record": d["record"], "visit": d["visit"], "item": d["item"]}
