"""Exports of a study's data core (TB-PLAN-04 step 4, D-129): CDISC ODM 1.3.2, REDCap CSV and XLSX.

All three are built from the study's forms (the metadata) and its values, the way REDCap exports a project, so a
REDCap project with the same data dictionary takes them back unchanged:

* the record id column is ``record_id`` (the screening number or pseudonym; never a chart number);
* a study with any value on an event is *longitudinal*: the CSV has ``redcap_event_name`` and a value with no event
  sits on ``event_1_arm_1``, REDCap's name for a classic project's one event; a classic study has no event column;
* a several-choices field is one column per choice (``field___code``, 1 or 0), as REDCap exports checkboxes;
* ODM uses REDCap's OIDs: ``Project.<study>``, ``Metadata.<study>_<stamp>``, ``Event.<event>``, ``Form.<form>``,
  item groups ``<form>.<first field>`` and the field name as ``ItemOID``; labels carry every language as
  ``TranslatedText`` with ``xml:lang``.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any
from xml.etree import ElementTree as ET  # building only; nothing is parsed here

from datacore.forms import LANGS, Field, fields_of, titles_of
from datacore.store import DataCore

RECORD_ID = "record_id"
BASE_EVENT = "event_1_arm_1"  # REDCap's one event of a classic (not longitudinal) project
ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_DTYPE = {"integer": "integer", "decimal": "float", "date": "date", "dateTime": "datetime", "multi": "boolean"}


def export_fields(dc: DataCore, study: str) -> list[Field]:
    """The study's fields in form order, with the record id first (as REDCap's dictionary starts)."""
    out: list[Field] = []
    for q in dc.forms(study):
        out.extend(f for f in fields_of(q) if f.kind != "display")
    if not any(f.name == RECORD_ID for f in out):
        form = out[0].form if out else "record"
        out.insert(0, Field(RECORD_ID, form, "text", "Record ID", labels={"ja": "レコードID", "zh-TW": "紀錄編號"}))
    return out


def _events(dc: DataCore, study: str) -> list[str]:
    return sorted({str(r["event"]) for r in dc.values(study) if r["event"]})


def event_name(event: str) -> str:
    return event or BASE_EVENT


def columns(fields: list[Field], longitudinal: bool) -> list[str]:
    """The REDCap CSV header for these fields."""
    cols = [RECORD_ID] + (["redcap_event_name"] if longitudinal else [])
    for f in fields:
        if f.name == RECORD_ID:
            continue
        cols.extend(_item_oids(f))
    return cols


def flat(dc: DataCore, study: str) -> tuple[list[str], list[dict[str, str]]]:
    """REDCap's flat export: one row per record and event, values as raw codes."""
    fields = export_fields(dc, study)
    by_name = {f.name: f for f in fields}
    longitudinal = bool(_events(dc, study))
    cols = columns(fields, longitudinal)
    rows: dict[tuple[str, str], dict[str, str]] = {}
    for r in dc.values(study):
        f = by_name.get(str(r["field"]))
        if f is None or f.name == RECORD_ID:
            continue
        row = rows.setdefault((r["record"], r["event"]), {})
        if f.kind == "multi":
            picked = set(str(r["value"]).split(",")) if r["value"] else set()
            row.update({f"{f.name}___{c}": "1" if c in picked else "0" for c in f.options})
        else:
            row[f.name] = str(r["value"])
    out = []
    for (rec, ev), vals in sorted(rows.items()):
        if not any(vals.values()):
            continue
        row = {c: "" for c in cols}
        row[RECORD_ID] = rec
        if longitudinal:
            row["redcap_event_name"] = event_name(ev)
        row.update(vals)
        out.append(row)
    return cols, out


def redcap_csv(dc: DataCore, study: str) -> str:
    cols, rows = flat(dc, study)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def xlsx(dc: DataCore, study: str) -> bytes:
    """The REDCap CSV as a workbook, with the data dictionary (every language) on a second sheet."""
    from openpyxl import Workbook

    from datacore.forms import metadata

    cols, rows = flat(dc, study)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "data"
    ws.append(cols)
    for r in rows:
        ws.append([r[c] for c in cols])
    meta = metadata(export_fields(dc, study), translations=True)
    md = wb.create_sheet("dictionary")
    md.append(list(meta[0]) if meta else [])
    for m in meta:
        md.append(list(m.values()))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sub(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, tag, {k: v for k, v in attrs.items() if v != ""})


def _texts(parent: ET.Element, tag: str, en: str, tr: dict[str, str]) -> None:
    el = _sub(parent, tag)
    t = _sub(el, "TranslatedText")
    t.set(XML_LANG, "en")
    t.text = en
    for g in LANGS:
        if tr.get(g):
            x = _sub(el, "TranslatedText")
            x.set(XML_LANG, g)
            x.text = tr[g]


def _oid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)


def odm(dc: DataCore, study: str, at: str) -> str:
    """CDISC ODM 1.3.2 (``FileType="Snapshot"``): ``Study``/``MetaDataVersion`` from the forms, ``ClinicalData``
    from the values. ``at`` is the creation time (ISO 8601 with offset)."""
    fields = export_fields(dc, study)
    by_name = {f.name: f for f in fields}
    qs = dc.forms(study)
    stamp = re.sub(r"[^0-9]", "", at)[:12]
    study_oid, mdv_oid = f"Project.{_oid(study)}", f"Metadata.{_oid(study)}_{stamp}"
    root = ET.Element("ODM", {"xmlns": ODM_NS, "FileType": "Snapshot",
                              "FileOID": f"TrialBox.{_oid(study)}.{stamp}", "CreationDateTime": at,
                              "ODMVersion": "1.3.2", "SourceSystem": "TrialBox", "Granularity": "All"})  # fmt: skip
    st = _sub(root, "Study", OID=study_oid)
    gv = _sub(st, "GlobalVariables")
    for tag in ("StudyName", "StudyDescription", "ProtocolName"):
        _sub(gv, tag).text = study
    mdv = _sub(st, "MetaDataVersion", OID=mdv_oid, Name=study)
    events = _events(dc, study)
    with_base = any(not r["event"] for r in dc.values(study)) or not events
    event_names = ([BASE_EVENT] if with_base else []) + [e for e in events if e != BASE_EVENT]
    proto = _sub(mdv, "Protocol")
    for i, ev in enumerate(event_names, 1):
        _sub(proto, "StudyEventRef", StudyEventOID=f"Event.{ev}", OrderNumber=str(i), Mandatory="No")
    forms = [str(q["name"]) for q in qs]
    for ev in event_names:
        sed = _sub(mdv, "StudyEventDef", OID=f"Event.{ev}", Name=ev, Repeating="No", Type="Common")
        for i, fm in enumerate(forms, 1):
            _sub(sed, "FormRef", FormOID=f"Form.{fm}", OrderNumber=str(i), Mandatory="No")
    groups: dict[str, list[Field]] = {}
    for f in fields:
        groups.setdefault(f.form, []).append(f)
    group_oid = {fm: f"{fm}.{fs[0].name}" for fm, fs in groups.items()}
    for q in qs:
        fm = str(q["name"])
        tt = titles_of(q)
        fd = _sub(mdv, "FormDef", OID=f"Form.{fm}", Name=tt.get("en") or fm, Repeating="No")
        if fm in groups:
            _sub(fd, "ItemGroupRef", ItemGroupOID=group_oid[fm], Mandatory="No")
    for fm, fs in groups.items():
        ig = _sub(mdv, "ItemGroupDef", OID=group_oid[fm], Name=fm, Repeating="No")
        for f in fs:
            for oid in _item_oids(f):
                _sub(ig, "ItemRef", ItemOID=oid, Mandatory="Yes" if f.required else "No")
    codelists: list[Field] = []
    for f in fields:
        if f.kind == "multi":
            for c, d in f.options.items():
                idf = _sub(mdv, "ItemDef", OID=f"{f.name}___{c}", Name=f"{f.name}___{c}", DataType="boolean")
                tr = {g: f"{f.label_in(g)} ({f.options_in(g).get(c, d)})" for g in f.labels}
                _texts(idf, "Question", f"{f.label} ({d})", tr)
            continue
        dtype = _DTYPE.get(f.kind, "text")
        idf = _sub(mdv, "ItemDef", OID=f.name, Name=f.name, DataType=dtype,
                   Length="" if dtype != "text" else "999")  # fmt: skip
        _texts(idf, "Question", f.label or f.name, f.labels)
        for comp, v in (("GE", f.vmin), ("LE", f.vmax)):
            if v:
                rc = _sub(idf, "RangeCheck", Comparator=comp, SoftHard="Hard")
                _sub(rc, "CheckValue").text = v
        if f.kind == "choice":
            _sub(idf, "CodeListRef", CodeListOID=f"{f.name}.choices")
            codelists.append(f)
    for f in codelists:
        cl = _sub(mdv, "CodeList", OID=f"{f.name}.choices", Name=f.name, DataType="text")
        for c, d in f.options.items():
            item = _sub(cl, "CodeListItem", CodedValue=c)
            _texts(item, "Decode", d, {g: f.options_in(g).get(c, "") for g in f.option_labels})
    cd = _sub(root, "ClinicalData", StudyOID=study_oid, MetaDataVersionOID=mdv_oid)
    data: dict[str, dict[str, dict[str, str]]] = {}
    for r in dc.values(study):
        fld = by_name.get(str(r["field"]))
        if fld is None or fld.name == RECORD_ID or r["value"] == "":
            continue
        data.setdefault(str(r["record"]), {}).setdefault(event_name(str(r["event"])), {})[fld.name] = str(r["value"])
    for rec in sorted(data):
        sd = _sub(cd, "SubjectData", SubjectKey=rec, TransactionType="Snapshot")
        for ev in sorted(data[rec], key=lambda e: event_names.index(e) if e in event_names else 99):
            se = _sub(sd, "StudyEventData", StudyEventOID=f"Event.{ev}", StudyEventRepeatKey="1")
            vals = data[rec][ev]
            for fm, fs in groups.items():
                here = [f for f in fs if f.name in vals]
                if not here:
                    continue
                fdata = _sub(se, "FormData", FormOID=f"Form.{fm}", FormRepeatKey="1")
                igd = _sub(fdata, "ItemGroupData", ItemGroupOID=group_oid[fm], ItemGroupRepeatKey="1")
                for f in here:
                    if f.kind == "multi":
                        picked = set(vals[f.name].split(","))
                        for c in f.options:
                            _sub(igd, "ItemData", ItemOID=f"{f.name}___{c}", Value="1" if c in picked else "0")
                    else:
                        _sub(igd, "ItemData", ItemOID=f.name, Value=vals[f.name])
    ET.indent(root, space=" ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _item_oids(f: Field) -> list[str]:
    return [f"{f.name}___{c}" for c in f.options] if f.kind == "multi" else [f.name]


def values_of(dc: DataCore, study: str) -> dict[tuple[str, str, str], str]:
    """Every non-blank value of a form field as ``(record, event, field) -> raw value`` (the round-trip check)."""
    names = {f.name for f in export_fields(dc, study)} - {RECORD_ID}
    return {(str(r["record"]), str(r["event"]), str(r["field"])): str(r["value"]) for r in dc.values(study)
            if r["field"] in names and r["value"] != ""}  # fmt: skip


def media(fmt: str) -> tuple[str, str]:
    """(file suffix, media type) of an export format."""
    return {"odm": (".odm.xml", "application/xml"), "csv": (".csv", "text/csv"),
            "xlsx": (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}[fmt]  # fmt: skip


def export(dc: DataCore, study: str, fmt: str, at: str) -> Any:
    """``odm`` and ``csv`` as text, ``xlsx`` as bytes."""
    if fmt == "odm":
        return odm(dc, study, at)
    if fmt == "csv":
        return redcap_csv(dc, study)
    if fmt == "xlsx":
        return xlsx(dc, study)
    raise ValueError(fmt)
