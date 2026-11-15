"""REDCap API simulator (TB-DS-08 §4.4, ICD-04S), written from the public REDCap API documentation only.

``POST /api/`` takes the same form fields as REDCap (``token``, ``content``, ``format=json``) and answers R1 version,
R2 project, R3 metadata, R7 record (flat export with ``records[]``/``fields[]``/``events[]``/``dateRangeBegin`` and
``exportDataAccessGroups``), R8 dag, and the record import (``content=record`` with ``data``: flat JSON rows,
``overwriteBehavior=normal``, ``forceAutoNumber``, ``returnContent=count|ids|auto_ids``; D-123), also with
``format=odm`` and ``type=flat``: ``data`` is a CDISC ODM document whose ``ClinicalData`` becomes the same rows
(``SubjectKey`` is the record id, ``StudyEventOID`` ``Event.<unique event name>`` the event, ``ItemOID`` the field;
a checkbox comes as ``field___code`` items; TB-PLAN-04 step 4). Every other ``content`` answers 501. Each fixture
project has its own 32-hex token; a wrong token answers 403 with REDCap's error text. ``POST /sim/records`` adds or
edits a record (the test and demo lever) and stamps its change time, which ``dateRangeBegin`` filters on;
``POST /sim/projects`` adds an empty project from a data dictionary (and events, for a longitudinal one).

T-302b (D-414): arms (events carry ``arm_num``), instrument designations per event, and repeating instruments and
events (the project's ``repeating`` list, ``content=repeatingFormsEvents``). A project with a repeating set exports
``redcap_repeat_instrument`` and ``redcap_repeat_instance`` on every row (blank on the base row) and keys its rows by
record, event, instrument and instance; an import puts a repeating instrument's field only on its own instance rows
and the other fields only on the base row, as REDCap does. ODM ``FormRepeatKey`` and ``StudyEventRepeatKey`` become
the instance. ``overwriteBehavior=overwrite`` lets a blank erase a value. Calculated fields are computed on import,
as REDCap does since its auto-calculation on import, with TrialBox's own small evaluator (``edc.logic``); a
``/sim/records`` edit leaves them as given (the lever for a REDCap-side calculation that differs).
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# ``record`` is the export, or the import when ``data`` is sent
SUPPORTED = {
    "version",
    "project",
    "metadata",
    "record",
    "dag",
    "event",
    "arm",
    "formEventMapping",
    "repeatingFormsEvents",
}
NO_PERMISSION = "You do not have permissions to use the API"


def load_projects(fixtures_dir: Path = FIXTURES) -> dict[str, dict[str, Any]]:
    """Read every ``*.json`` fixture project, keyed by its API token."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(fixtures_dir).glob("*.json")):
        proj = json.loads(path.read_text(encoding="utf-8"))
        out[str(proj["token"]).upper()] = proj
    return out


def _form_list(form: Any, name: str) -> list[str]:
    """REDCap accepts ``name[0]=a&name[1]=b``, ``name[]=a`` or a comma list in ``name``."""
    vals: list[str] = []
    for key, val in form.multi_items():
        if key in (name, f"{name}[]") or (key.startswith(f"{name}[") and key.endswith("]")):
            vals.extend(v.strip() for v in str(val).split(",") if v.strip())
    return vals


def _local_now() -> str:
    """REDCap stamps changes in its server's local time; the simulator uses the site zone (``TB_TZ``, D-315)."""
    from tb_common.config import site_zone

    return datetime.now(site_zone()).replace(microsecond=0, tzinfo=None).isoformat()


def _err(status: int, msg: str) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


class SimState:
    def __init__(self, projects: dict[str, dict[str, Any]], version: str, rate_limit: int | None) -> None:
        self.projects = projects
        self.version = version
        self.rate_limit = rate_limit
        self.calls: list[float] = []
        self.lock = threading.Lock()

    def by_pid(self, project_id: int) -> dict[str, Any] | None:
        return next((p for p in self.projects.values() if int(p["project"]["project_id"]) == project_id), None)

    def limited(self) -> bool:
        if not self.rate_limit:
            return False
        now = time.monotonic()
        with self.lock:
            self.calls = [t for t in self.calls if now - t < 60.0]
            if len(self.calls) >= self.rate_limit:
                return True
            self.calls.append(now)
        return False


def _record_id_field(proj: dict[str, Any]) -> str:
    return str(proj["metadata"][0]["field_name"])


REPEAT_COLS = ("redcap_repeat_instrument", "redcap_repeat_instance")
EXTRA_COLS = {"redcap_event_name", "redcap_data_access_group", *REPEAT_COLS}


def _repeating(proj: dict[str, Any]) -> list[dict[str, str]]:
    return list(proj.get("repeating") or [])


def _repeat_set(proj: dict[str, Any]) -> set[tuple[str, str]]:
    """(unique event name, or "" in a classic project; instrument, or "" for a whole repeating event)."""
    return {(str(r.get("event_name") or ""), str(r.get("form_name") or "")) for r in _repeating(proj)}


def _instance(rec: dict[str, Any]) -> str:
    return str(rec.get("redcap_repeat_instance") or "").strip()


def _export_records(proj: dict[str, Any], form: Any) -> list[dict[str, Any]]:
    want_records = set(_form_list(form, "records"))
    want_fields = _form_list(form, "fields")
    want_events = set(_form_list(form, "events"))
    since = str(form.get("dateRangeBegin") or "").strip()
    with_dag = str(form.get("exportDataAccessGroups") or "").lower() == "true"
    longitudinal = bool(int(proj["project"].get("is_longitudinal", 0)))
    rid = _record_id_field(proj)
    known = [m["field_name"] for m in proj["metadata"]]
    if want_fields:
        cols = [rid] + [f for f in want_fields if f in known and f != rid]
    else:
        cols = list(known)
    rows: list[dict[str, Any]] = []
    for rec in proj["records"]:
        if want_records and str(rec.get(rid)) not in want_records:
            continue
        if want_events and rec.get("redcap_event_name") not in want_events:
            continue
        if since and str(rec.get("_changed", "")).replace("T", " ") < since.replace("T", " "):
            continue
        row: dict[str, Any] = {rid: str(rec.get(rid, ""))}
        if longitudinal:
            row["redcap_event_name"] = rec.get("redcap_event_name", "")
        if _repeating(proj):  # every row carries the repeat keys; blank on the base row
            row["redcap_repeat_instrument"] = str(rec.get("redcap_repeat_instrument") or "")
            row["redcap_repeat_instance"] = _instance(rec)
        if with_dag:
            row["redcap_data_access_group"] = rec.get("redcap_data_access_group", "")
        for col in cols:
            if col == rid:
                continue
            m: dict[str, Any] = next((x for x in proj["metadata"] if x["field_name"] == col), {})
            if m.get("field_type") == "checkbox":  # NEW-EDC-3b: REDCap exports one column per choice
                have = str(rec.get(col, "")).split(",")
                for code in _codes(m):
                    row[_column(col, code)] = "1" if code in have else "0"
                continue
            row[col] = str(rec.get(col, ""))
        rows.append(row)
    return rows


def _key(rec: dict[str, Any], rid: str, longitudinal: bool) -> tuple[str, Any, str, str]:
    return (str(rec.get(rid)), rec.get("redcap_event_name") if longitudinal else None,
            str(rec.get("redcap_repeat_instrument") or ""), _instance(rec))  # fmt: skip


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def odm_rows(proj: dict[str, Any], text: str) -> list[dict[str, str]] | None:
    """An ODM document's ``ClinicalData`` as REDCap's flat rows (``None`` if it is not ODM)."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:  # no DTD, no entity: nothing for the parser to expand or fetch
        return None
    try:
        root = ET.fromstring(text)  # noqa: S314 - refused above when the document declares a DTD or an entity
    except ET.ParseError:
        return None
    if _local(root.tag) != "ODM":
        return None
    rid = _record_id_field(proj)
    checkbox = {m["field_name"] for m in proj["metadata"] if m["field_type"] == "checkbox"}
    longitudinal = bool(int(proj["project"].get("is_longitudinal", 0)))
    repeat = _repeat_set(proj)
    rows: list[dict[str, str]] = []

    def items(parent: ET.Element, row: dict[str, str]) -> None:
        for item in (el for el in parent.iter() if _local(el.tag) == "ItemData"):
            oid, val = str(item.get("ItemOID") or ""), str(item.get("Value") or "")
            base, sep, _code = oid.partition("___")
            if (sep and base in checkbox) or oid != rid:  # a checkbox's choice stays its own column (NEW-EDC-3b)
                row[oid] = val

    for sd in (el for el in root.iter() if _local(el.tag) == "SubjectData"):
        for se in (el for el in sd if _local(el.tag) == "StudyEventData"):
            ev = str(se.get("StudyEventOID") or "").removeprefix("Event.")
            head: dict[str, str] = {rid: str(sd.get("SubjectKey") or "")}
            if longitudinal:
                head["redcap_event_name"] = ev
            key_ev = ev if longitudinal else ""
            ev_rep = str(se.get("StudyEventRepeatKey") or "").strip()
            if ev_rep and (key_ev, "") in repeat:  # a repeating event: the whole event is one instance row
                row = {**head, "redcap_repeat_instrument": "", "redcap_repeat_instance": ev_rep}
                items(se, row)
                rows.append(row)
                continue
            base = dict(head)
            reps: list[dict[str, str]] = []
            for fd in (el for el in se if _local(el.tag) == "FormData"):
                form = str(fd.get("FormOID") or "").removeprefix("Form.")
                key = str(fd.get("FormRepeatKey") or "").strip()
                if key and (key_ev, form) in repeat:
                    row = {**head, "redcap_repeat_instrument": form, "redcap_repeat_instance": key}
                    items(fd, row)
                    reps.append(row)
                else:
                    items(fd, base)
            if len(base) > len(head) or not reps:
                rows.append(base)
            rows.extend(reps)
    return rows


TICKS = "\x00ticks:"  # NEW-EDC-3b: a checkbox's ``___`` columns of one import row, carried through the checks as one


def _codes(meta: dict[str, Any]) -> list[str]:
    """A checkbox's choice codes (``1, Toe | 2, Ankle``)."""
    raw = str(meta.get("select_choices_or_calculations") or "")
    return [p.split(",", 1)[0].strip() for p in raw.split("|") if p.strip()]


def _column(field: str, code: str) -> str:
    """REDCap's column of a checkbox choice: the code lowercased, ``-`` and ``.`` written ``_`` (``x____99``)."""
    return f"{field}___{code.lower().replace('-', '_').replace('.', '_')}"


def _checkbox_columns(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str | None:
    """REDCap's flat form of a checkbox (NEW-EDC-3b, EDC-001 on this point): one ``field___code`` column per choice,
    ``1`` ticked, ``0`` not, blank left as it is. A bare checkbox column, or a code the field has no choice for, is
    refused as REDCap refuses it. Each row's columns of a checkbox are carried as one value until the write."""
    boxes = {f: _codes(m) for f, m in meta.items() if m.get("field_type") == "checkbox"}
    for r in rows:
        bare = sorted(f for f in r if f in boxes)
        if bare:
            return f"The following fields were not found in the project as real data fields: {', '.join(bare)}"
        ticks: dict[str, dict[str, str]] = {}
        for col in list(r):
            base, sep, _ = str(col).partition("___")
            if not sep or base not in boxes:
                continue
            v = str(r.pop(col))
            code = next((c for c in boxes[base] if _column(base, c) == col), None)
            if code is None or v not in ("0", "1", ""):
                return f"The following fields were not found in the project: {col}"
            ticks.setdefault(base, {})[code] = v
        for base, t in ticks.items():
            r[base] = TICKS + ",".join(f"{c}={v}" for c, v in t.items())
    return None


def _real_day(y: str, m: str, d: str) -> bool:
    try:
        date(int(y), int(m), int(d))
    except ValueError:
        return False
    return True


def _day(value: str) -> bool:
    """CGRD-B5a (D-843): a date as REDCap's import reads it, whatever the field shows: Y-M-D or M/D/Y, a real day."""
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value):
        return _real_day(m.group(1), m.group(2), m.group(3))
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value):
        return _real_day(m.group(3), m.group(1), m.group(2))
    return False


def _fits(meta: dict[str, Any], value: str) -> bool:
    """REDCap's check of a value against its field (STD-061, T-115; CGRD-B5a, D-843): a choice field takes one of
    its codes (yes/no and true/false: 0 or 1); ``integer`` and ``number`` take a number; a date or date-time takes
    Y-M-D or M/D/Y (a time after it for a date-time); ``number_1dp`` takes exactly one decimal place, a
    ``_comma_decimal`` type takes the comma. A range is not checked: REDCap's import does not refuse it."""
    ftype = str(meta.get("field_type") or "")
    if ftype in ("yesno", "truefalse"):
        return value in ("0", "1")
    if ftype in ("radio", "dropdown"):
        return value in _codes(meta)
    vt = str(meta.get("text_validation_type_or_show_slider_number") or "")
    if vt == "integer":
        return re.fullmatch(r"-?\d+", value) is not None
    if vt == "number":
        return re.fullmatch(r"-?\d+(\.\d+)?", value) is not None
    if vt.startswith("date_"):
        return _day(value)
    if vt.startswith("datetime_"):
        day, _, clock = value.partition(" ")
        return _day(day) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?", clock) is not None
    m = re.fullmatch(r"number_(\d)dp(_comma_decimal)?", vt)
    if m:
        sep = "," if m.group(2) else r"\."
        return re.fullmatch(rf"-?\d+{sep}\d{{{m.group(1)}}}", value) is not None
    if vt == "number_comma_decimal":
        return re.fullmatch(r"-?\d+(,\d+)?", value) is not None
    return True


def _import_records(proj: dict[str, Any], form: Any) -> Any:
    """REDCap's record import: unknown fields, (longitudinal) missing or unknown events, a field on the wrong row
    (an instrument not designated for the event; a repeating instrument's field on the base row or on another
    instrument's instance row; a repeat row with no instance) and a value that fails its field's decimal validation
    are refused whole. ``overwriteBehavior=overwrite``: a blank erases. Calculated fields are computed afterwards."""
    rows: Any
    if str(form.get("format") or "json") == "odm":
        rows = odm_rows(proj, str(form.get("data")))
        if rows is None:
            return _err(400, "The data being imported is not in a valid format")
    else:
        try:
            rows = json.loads(str(form.get("data")))
        except ValueError:
            return _err(400, "The data being imported is not in a valid format")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return _err(400, "The data being imported is not in a valid format")
    rid = _record_id_field(proj)
    meta = {m["field_name"]: m for m in proj["metadata"]}
    refused = _checkbox_columns(rows, meta)
    if refused:
        return _err(400, refused)
    extra = EXTRA_COLS
    longitudinal = bool(int(proj["project"].get("is_longitudinal", 0)))
    repeat = _repeat_set(proj)
    events = {e["unique_event_name"] for e in proj.get("events", [])}
    dags = {d["unique_group_name"] for d in proj.get("dags", [])}
    mapping = proj.get("form_event_mapping") or []
    for r in rows:
        bad = sorted(set(r) - set(meta) - extra)
        if bad:
            return _err(400, f"The following fields were not found in the project: {', '.join(bad)}")
        if rid not in r or not str(r[rid]).strip():
            return _err(400, f"The record identifier field ({rid}) is missing")
        if longitudinal:
            ev = str(r.get("redcap_event_name") or "")
            if ev not in events:
                return _err(400, f"The event name '{ev}' is not valid")
            forms = {m["form"] for m in mapping if m["unique_event_name"] == ev}
            off = [f for f in r if f in meta and f != rid and forms and meta[f]["form_name"] not in forms]
            if off:
                return _err(400, f"Fields not designated for event {ev}: {', '.join(off)}")
        rep_form = str(r.get("redcap_repeat_instrument") or "")
        rep_inst = str(r.get("redcap_repeat_instance") or "").strip()
        ev_key = str(r.get("redcap_event_name") or "") if longitudinal else ""
        if (rep_form or rep_inst) and not repeat:
            return _err(400, "This project has no repeating instruments or events")
        if rep_form or rep_inst:
            if not rep_inst.isdigit() or int(rep_inst) < 1:
                return _err(400, "The repeat instance (redcap_repeat_instance) is missing or not a whole number")
            if (ev_key, rep_form) not in repeat:
                what = f"instrument '{rep_form}'" if rep_form else "event"
                return _err(400, f"The {what} is not set to repeat on event '{ev_key or 'event_1_arm_1'}'")
            if rep_form:
                off = [f for f in r if f in meta and f != rid and meta[f]["form_name"] != rep_form]
                if off:
                    return _err(400, f"Fields not on the repeating instrument {rep_form}: {', '.join(off)}")
        else:
            off = [f for f in r if f in meta and f != rid and (ev_key, meta[f]["form_name"]) in repeat]
            if off or (repeat and (ev_key, "") in repeat and any(f in meta and f != rid for f in r)):
                return _err(400, "Fields of a repeating instrument or event need redcap_repeat_instrument and "
                            f"redcap_repeat_instance: {', '.join(off) or 'the event repeats'}")  # fmt: skip
        off_format = sorted(f for f, v in r.items() if f in meta and str(v) != "" and not _fits(meta[f], str(v)))
        if off_format:
            # as REDCap answers: one line per refused value, quoting the record, the field and the VALUE. So the
            # box's client must not pass this text on (tests/unit/test_rc_error_text.py)
            lines = [
                f'"{r.get(rid, "")}","{f}","{r[f]}","The value you provided could not be validated because it '
                'does not follow the expected format. Please try again."'
                for f in off_format
            ]
            return _err(400, "\n".join(lines))
        dag = str(r.get("redcap_data_access_group") or "")
        if dag and dag not in dags:
            return _err(400, f"The data access group '{dag}' is not valid")
    auto = str(form.get("forceAutoNumber") or "").lower() == "true"
    erase = str(form.get("overwriteBehavior") or "normal") == "overwrite"
    stamp = _local_now()
    used = [int(x[rid]) for x in proj["records"] if str(x.get(rid, "")).isdigit()]
    next_id = max(used, default=0) + 1
    renamed: dict[str, str] = {}
    written: list[str] = []
    for r in rows:
        name = str(r[rid])
        if auto:
            if name not in renamed:
                renamed[name] = str(next_id)
                next_id += 1
            name = renamed[name]
        key = _key({**r, rid: name}, rid, longitudinal)
        hit = next((x for x in proj["records"] if _key(x, rid, longitudinal) == key), None)
        if hit is None:
            hit = {f: "" for f in meta}
            hit[rid] = name
            proj["records"].append(hit)
        for k, v in r.items():
            if k == rid:
                continue
            if str(v) == "" and not erase:  # overwriteBehavior=normal: a blank never erases
                continue
            if str(v).startswith(TICKS):  # NEW-EDC-3b: each choice ticked (1) or not (0); a blank one left
                have = [c for c in str(hit.get(k) or "").split(",") if c]
                for pair in str(v)[len(TICKS) :].split(","):
                    code, _, tick = pair.partition("=")
                    if tick == "1" and code not in have:
                        have.append(code)
                    elif (tick == "0" or (tick == "" and erase)) and code in have:
                        have.remove(code)
                order = _codes(meta[k])
                hit[k] = ",".join(sorted(have, key=lambda c: order.index(c) if c in order else len(order)))
                continue
            hit[k] = str(v)
        _calculate(proj, hit)
        hit["_changed"] = stamp
        if name not in written:
            written.append(name)
    how = str(form.get("returnContent") or "count")
    if how == "ids":
        return written
    if how == "auto_ids":
        back = {v: k for k, v in renamed.items()}
        return [f"{w},{back.get(w, w)}" for w in written]
    return {"count": len(written)}


def _calculate(proj: dict[str, Any], row: dict[str, Any]) -> None:
    """REDCap computes the calculated fields of the row's instruments after an import (TrialBox's ``edc.logic``)."""
    from edc import logic
    from tb_common.config import site_zone

    rid = _record_id_field(proj)
    longitudinal = bool(int(proj["project"].get("is_longitudinal", 0)))
    meta = {m["field_name"]: m for m in proj["metadata"]}
    repeat = _repeat_set(proj)
    ev = str(row.get("redcap_event_name") or "") if longitudinal else ""
    here = str(row.get("redcap_repeat_instrument") or "")
    mapping = proj.get("form_event_mapping") or []
    designated = {m["form"] for m in mapping if m["unique_event_name"] == ev} if longitudinal and mapping else None

    def lookup(event: str | None, name: str, code: str | None, instance: int | None) -> str:
        if name not in meta:
            raise logic.LogicError(f"no field {name}")
        src = row
        if (event and event != ev) or instance:
            src = next((x for x in proj["records"] if str(x.get(rid)) == str(row.get(rid))
                        and (not longitudinal or x.get("redcap_event_name") == (event or ev))
                        and _instance(x) == (str(instance) if instance else "")), {})  # fmt: skip
        val = str(src.get(name) or "")
        return ("1" if code in val.split(",") else "0") if code else val

    for m in proj["metadata"]:
        if m.get("field_type") != "calc":
            continue
        form = m["form_name"]
        if designated is not None and form not in designated:
            continue
        if here and form != here:
            continue
        if not here and (ev, form) in repeat:
            continue
        try:
            row[m["field_name"]] = logic.calculate(str(m.get("select_choices_or_calculations") or ""), lookup,
                                                   datetime.now(site_zone()).date())  # fmt: skip
        except logic.LogicError:
            continue


def _event(e: dict[str, Any]) -> dict[str, Any]:
    name = str(e["unique_event_name"])
    return {"event_name": str(e.get("event_name") or name), "arm_num": int(e.get("arm_num") or 1),
            "unique_event_name": name}  # fmt: skip


def _designation(m: dict[str, Any]) -> dict[str, Any]:
    return {"arm_num": int(m.get("arm_num") or 1), "unique_event_name": str(m["unique_event_name"]),
            "form": str(m["form"])}  # fmt: skip


def _repeat(r: dict[str, Any]) -> dict[str, str]:
    return {"event_name": str(r.get("event_name") or ""), "form_name": str(r.get("form_name") or ""),
            "custom_form_label": ""}  # fmt: skip


def _dictionary_refused(meta: list[dict[str, Any]], not_offered: frozenset[str]) -> str | None:
    """CGRD-B5b (D-844): what a real REDCap refuses in a data dictionary: ``^`` in a calculation, and a validation
    the instance does not offer (its administrator's choice). None when it takes the dictionary."""
    for m in meta:
        name = str(m.get("field_name") or "")
        if str(m.get("field_type") or "") == "calc" and "^" in str(m.get("select_choices_or_calculations") or ""):
            return f"The calculation of {name} is not valid: ^ is not an operator REDCap takes"
        vt = str(m.get("text_validation_type_or_show_slider_number") or "")
        if vt and vt in not_offered:
            return f"The validation type of {name} ({vt}) is not offered on this instance"
    return None


def create_app(fixtures_dir: Path | None = None, version: str | None = None, rate_limit: int | None = None,
               not_offered: Iterable[str] = ()) -> FastAPI:  # fmt: skip
    """Build a simulator app (each app holds its own copy of the fixtures, so tests stay independent).
    ``not_offered`` (CGRD-B5b, D-844): the validation types the instance does not offer; a dictionary using one is
    refused, as on a REDCap whose administrator turned it off."""
    refused_validations = frozenset(not_offered)
    state = SimState(
        copy.deepcopy(load_projects(fixtures_dir or FIXTURES)),
        version or os.environ.get("TB_RC_SIM_VERSION", "16.0.10"),
        rate_limit,
    )
    app = FastAPI(title="trialbox-rc-sim")
    app.state.sim = state

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": "rc_sim", "projects": len(state.projects), "version": state.version}

    @app.post("/api/")
    async def api(request: Request) -> Any:
        form = await request.form()
        if state.limited():
            return _err(429, "Too many API requests")
        token = str(form.get("token") or "").strip().upper()
        proj = state.projects.get(token)
        if proj is None:
            return _err(403, NO_PERMISSION)
        content = str(form.get("content") or "")
        fmt = str(form.get("format") or "json")
        if fmt != "json" and not (fmt == "odm" and content == "record" and form.get("data") is not None):
            return _err(400, "This simulator answers format=json only (and takes ODM for a record import)")
        if content not in SUPPORTED:
            return _err(501, f"The content '{content}' is not supported by the TrialBox REDCap simulator")
        if content == "version":  # REDCap answers this one call with plain text, not JSON (STD-060)
            return PlainTextResponse(state.version)
        if content == "project":
            return {**proj["project"], "has_repeating_instruments_or_events": 1 if _repeating(proj) else
                    int(proj["project"].get("has_repeating_instruments_or_events") or 0)}  # fmt: skip
        if content == "metadata":
            fields = set(_form_list(form, "fields"))
            return [m for m in proj["metadata"] if not fields or m["field_name"] in fields]
        if content == "dag":
            return proj["dags"]
        if content == "repeatingFormsEvents":  # REDCap answers it only for a project that repeats something
            if not _repeating(proj):
                return _err(400, "There are no repeating instruments or events in this project")
            return [{"event_name": r.get("event_name", ""), "form_name": r.get("form_name", ""),
                     "custom_form_label": r.get("custom_form_label", "")} for r in _repeating(proj)]  # fmt: skip
        if content == "formEventMapping":  # REDCap answers it for a longitudinal project only
            if not int(proj["project"].get("is_longitudinal", 0)):
                return _err(400, "You cannot export form/event mappings for classic projects")
            return list(proj.get("form_event_mapping") or [])
        if content in ("event", "arm"):  # REDCap answers these for a longitudinal project only
            if not int(proj["project"].get("is_longitudinal", 0)):
                return _err(400, "You cannot export arms or events for classic projects")
            events = [{"day_offset": 0, "offset_min": 0, "offset_max": 0, **e} for e in proj.get("events", [])]
            if content == "event":
                return events
            arms = sorted({int(e.get("arm_num") or 1) for e in events})
            return [{"arm_num": a, "name": f"Arm {a}"} for a in arms]
        if str(form.get("type") or "flat") != "flat":
            return _err(400, "Only type=flat is supported")
        if form.get("data") is not None:
            return _import_records(proj, form)
        return _export_records(proj, form)

    @app.post("/sim/records")
    async def sim_records(request: Request) -> Any:
        """Add or edit records: ``{"project_id": 101, "records": [{...}]}``; unknown fields are refused."""
        body = await request.json()
        proj = state.by_pid(int(body.get("project_id", 0)))
        if proj is None:
            return _err(404, "No such project")
        rid = _record_id_field(proj)
        known = {m["field_name"] for m in proj["metadata"]} | EXTRA_COLS
        stamp = str(body.get("at") or _local_now())
        n = 0
        for new in body.get("records", []):
            bad = set(new) - known
            if bad:
                return _err(400, f"Unknown fields: {', '.join(sorted(bad))}")
            key = _key(new, rid, True)
            hit = next((r for r in proj["records"] if _key(r, rid, True) == key), None)
            if hit is None:
                hit = {f: "" for f in known if f in {m["field_name"] for m in proj["metadata"]}}
                proj["records"].append(hit)
            hit.update({k: str(v) for k, v in new.items()})
            hit["_changed"] = stamp
            n += 1
        return {"count": n}

    @app.post("/sim/projects")
    async def sim_projects(request: Request) -> Any:
        """Add an empty project: ``{"title", "metadata": [dictionary rows], "events": [unique event names, or
        {unique_event_name, arm_num}], "mapping": [{unique_event_name, form}], "repeating": [{event_name,
        form_name}]}``. With events it is longitudinal (with no mapping, every form on every event). Answers its
        project id and API token."""
        body = await request.json()
        meta = list(body.get("metadata") or [])
        if not meta or any("field_name" not in m or "form_name" not in m for m in meta):
            return _err(400, "A data dictionary with field_name and form_name is needed")
        why = _dictionary_refused(meta, refused_validations)
        if why:  # CGRD-B5b (D-844): as a real REDCap refuses the dictionary
            return _err(400, why)
        events = [e if isinstance(e, dict) else {"unique_event_name": str(e)} for e in body.get("events") or []]
        pid = max((int(p["project"]["project_id"]) for p in state.projects.values()), default=100) + 1
        token = secrets.token_hex(16).upper()
        project = {
            "project_id": pid,
            "project_title": str(body.get("title") or f"Project {pid}"),
            "is_longitudinal": 1 if events else 0,
            "has_repeating_instruments_or_events": 1 if body.get("repeating") else 0,
            "record_autonumbering_enabled": 0,
            "in_production": 0,
        }
        state.projects[token] = {
            "token": token,
            "project": project,
            "metadata": [{k: str(v) for k, v in m.items()} for m in meta],
            "events": [_event(e) for e in events],
            "form_event_mapping": [_designation(m) for m in body.get("mapping") or []],
            "repeating": [_repeat(r) for r in body.get("repeating") or []],
            "dags": [],
            "records": [],
        }
        return {"project_id": pid, "token": token}

    @app.post("/sim/metadata/rename")
    async def sim_rename(request: Request) -> Any:
        """Rename a field in the data dictionary (lets a test break a link: RC-LINK-FIELD)."""
        body = await request.json()
        proj = state.by_pid(int(body.get("project_id", 0)))
        if proj is None:
            return _err(404, "No such project")
        old, new = str(body["old"]), str(body["new"])
        for m in proj["metadata"]:
            if m["field_name"] == old:
                m["field_name"] = new
        for r in proj["records"]:
            if old in r:
                r[new] = r.pop(old)
        return {"renamed": old, "to": new}

    return app


app = create_app()
INPROC_URL = "inproc://rc-sim"


def register_inproc(sim: FastAPI | None = None, replace: bool = True) -> None:
    """Route ``inproc://rc-sim`` in rc-bridge to this simulator (the module-level app unless one is given).
    ``replace=False`` (the orchestrator's DEV/TEST default) never overrides a simulator a demo registered first."""
    from fastapi.testclient import TestClient
    from rc_bridge.client import register_local

    target = sim or app
    register_local(INPROC_URL, lambda: TestClient(target, base_url="http://rc-sim"), replace=replace)


def main() -> None:  # pragma: no cover - entry point
    import uvicorn

    uvicorn.run(
        app, host=os.environ.get("TB_RC_SIM_HOST", "127.0.0.1"), port=int(os.environ.get("TB_RC_SIM_PORT", "8790"))
    )


if __name__ == "__main__":  # pragma: no cover
    main()
