"""Copy-assist (T-302c, D-434): the signed values of a subject, to type into the sponsor's EDC by hand.

A study whose sponsor has not acknowledged the REDCap send in writing runs its switch in ``copy``: drafts, review
and signatures as for prefill, never a write to the sponsor's EDC. This module gives the sheet a person copies from
and keeps their "copied" ticks.

* :func:`sheet`: per visit, then per form in the data dictionary's order, then per item in the dictionary's order,
  every value that is decided, signed under a version-2 signature row that still verifies, and unchanged since it
  was signed. Nothing else is a value on the sheet: an open, rejected or unsigned value, and a value under a
  version-1 signature row (D-281), are only counted per visit (``waiting``). Each value carries its citation, who
  signed it and when, and its "copied" tick when one holds for the value as signed. An opted-out patient is never
  on a sheet (a named one is refused; the study's sheet leaves them out). Every read is audited (``edc.copy_view``,
  never a value).
* :func:`tick`: a ``copied`` or ``undone`` tick (with a reason) on values of the sheet, per value or per form. A
  value not on the sheet refuses the whole request. Audited (``edc.copy_tick``) inside the tick's transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from edc.service import EdcService
from edc.store import SIG_VERSION, EdcError

FORMATS = ("page", "csv", "api")


def _values(svc: EdcService, rs: str, record: str | None) -> list[dict[str, Any]]:
    """The values a person may copy: decided, signed (version 2, intact), unchanged since; never an opted-out
    patient's."""
    sigs = {int(s["id"]): s for s in svc.store.signatures(rs, record)}
    gone = set(svc.optouts())
    direct = svc.store.direct_source(rs)
    out = []
    for d in svc.store.signed(rs, record):
        if str(d["item"]) in direct:
            continue  # EDC-023 (D-859): recorded directly in the tool (TFDA §4.7 ¶2); never copied in from a record
        s = sigs.get(int(d["signature_id"]))
        if s is None or int(s.get("sig_version") or 1) != SIG_VERSION:
            continue  # a version-1 row is never a source here (D-434)
        if str(d["pid"]) in gone:
            continue
        if d.get("source_changed"):
            continue  # NEW-EDC-4 (D-694): its source changed since; a person keeps or changes it first
        out.append({**d, "_sig": s})
    return out


def _held(ticks: Iterable[dict[str, Any]], d: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The tick that holds for the value as signed (the newest of its own hash, when it says ``copied``), and the
    earlier ticks of the value under another hash (the value changed and was signed again since)."""
    mine = [t for t in ticks if int(t["draft_id"]) == int(d["id"])]
    same = [t for t in mine if t["signed_sha"] == d["signed_sha"]]
    last = same[-1] if same else None
    held = {"by": last["by_user"], "at": last["at"]} if last is not None and last["action"] == "copied" else None
    stale = [{"by": t["by_user"], "at": t["at"], "action": t["action"]} for t in mine if t["signed_sha"] !=
             d["signed_sha"]]  # fmt: skip
    return held, stale


def sheet(svc: EdcService, rs: str, record: str | None, by: str, fmt: str = "page") -> dict[str, Any]:
    """The copy-assist sheet of one subject (``record``) or of the whole study (``None``), audited."""
    if fmt not in FORMATS:
        raise EdcError("edc.copy_format", "page, csv or api", 400)
    detail: dict[str, Any] = {"record": record or "*", "format": fmt}
    try:
        svc.store.require_drafting(rs)
        if record is not None:
            pids = {str(d["pid"]) for d in svc.store.drafts(rs, record, current=False)}
            if pids & set(svc.optouts()):
                raise EdcError("edc.opted_out", "the patient opted out; nothing is shown")
    except EdcError as exc:
        svc._audit("edc.copy_view", rs, by, {**detail, "refused": exc.code})
        raise
    fields = svc.dc.fields(rs)
    pos = {name: i for i, name in enumerate(fields)}
    form_pos: dict[str, int] = {}
    for f in fields.values():
        form_pos.setdefault(f.form, len(form_pos))
    values = _values(svc, rs, record)
    changed = svc.store.redcap_changes(rs, record)  # NEW-EDC-5c (D-801): what REDCap holds since, while open
    ok = {int(d["id"]) for d in values}
    ticks = svc.store.ticks(rs, record)
    gone = set(svc.optouts())
    direct = svc.store.direct_source(rs)
    records: dict[str, dict[str, dict[str, Any]]] = {}
    for d in svc.store.drafts(rs, record):  # every current draft names its visit; only the sheet's carry a value
        if str(d["pid"]) in gone or str(d["item"]) in direct:
            continue
        v = records.setdefault(str(d["record"]), {}).setdefault(
            str(d["visit"]), {"visit": d["visit"], "visit_date": d["visit_date"], "waiting": 0, "forms": {}}
        )
        if int(d["id"]) not in ok and d["fate"] not in ("rejected", "retired"):
            v["waiting"] += 1  # open, or decided and not (validly) signed: counted, never shown
    for d in values:
        v = records[str(d["record"])][str(d["visit"])]
        held, stale = _held(ticks, d)
        s = d["_sig"]
        form = str(fields[d["item"]].form if d["item"] in fields else d.get("form") or "")
        v["forms"].setdefault(form, []).append({
            "id": int(d["id"]), "item": d["item"], "form": form, "cdash": d.get("cdash") or "",
            "test": d.get("test") or "", "value": d["final"], "citation": d.get("final_citation") or d.get("citation"),
            "signed_by": s["printed_name"], "signed_at": s["at"], "signature_id": int(s["id"]),
            "copied": held, "earlier": stale,
            "redcap_now": changed.get((str(d["record"]), str(d["visit"]), str(d["item"])))})  # fmt: skip
    out = []
    for rec in sorted(records):
        visits = []
        for v in sorted(records[rec].values(), key=lambda x: (str(x["visit_date"]), str(x["visit"]))):
            forms_ = []
            for form in sorted(v["forms"], key=lambda f: (form_pos.get(f, len(form_pos)), f)):
                vals = sorted(v["forms"][form], key=lambda x: (pos.get(x["item"], len(pos)), x["item"]))
                forms_.append({"form": form, "values": vals, "copied": all(x["copied"] for x in vals)})
            visits.append({"visit": v["visit"], "visit_date": v["visit_date"], "waiting": v["waiting"],
                           "forms": forms_})  # fmt: skip
        out.append({"record": rec, "visits": visits})
    n = len(values)
    svc._audit("edc.copy_view", rs, by, {**detail, "values": n, "records": len(out)})
    return {"study": rs, "state": svc.store.switch(rs).state, "records": out, "values": n,
            "direct_source": sorted(direct)}  # fmt: skip


def tick(svc: EdcService, rs: str, record: str, ids: list[int], action: str, by: str,
         reason: str = "") -> dict[str, Any]:  # fmt: skip
    """Tick values of one subject's sheet ``copied`` (or undo a tick, with a reason). All or nothing."""
    detail: dict[str, Any] = {"record": record, "action": action, "drafts": sorted(set(ids))[:200]}
    try:
        svc.store.require_drafting(rs)
        svc.store.require_not_frozen(rs)  # D-1253 review G2: no tick on a study of another id rule
        if not ids:
            raise EdcError("edc.tick_none", "no value to tick", 400)
        pids = {str(d["pid"]) for d in svc.store.drafts(rs, record, current=False)}
        if pids & set(svc.optouts()):
            raise EdcError("edc.opted_out", "the patient opted out; nothing is ticked")
        by_id = {int(d["id"]): d for d in _values(svc, rs, record)}
        missing = sorted(set(ids) - set(by_id))
        if missing:
            err = EdcError("edc.tick_not_signed", "only a signed value of this subject's sheet is ticked", 409)
            err.problems = [{"draft": i, "code": "not_on_sheet"} for i in missing]  # type: ignore[attr-defined]
            raise err
        rows = [by_id[i] for i in sorted(set(ids))]

        def audited(new: list[int]) -> None:
            svc._audit("edc.copy_tick", rs, by, {**detail, "ticks": len(new), "reason": bool(reason.strip())})

        made = svc.store.add_ticks(rs, rows, action, reason=reason, by=by, at=svc.stamp(), before_commit=audited)
    except EdcError as exc:
        svc._audit("edc.copy_tick", rs, by, {**detail, "refused": exc.code})
        raise
    return {"study": rs, "record": record, "action": action, "ticks": made}
