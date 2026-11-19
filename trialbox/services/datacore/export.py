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

``cdisc`` (D-396, T-619b, STD-063) is the same ODM with the CDISC content TrialBox holds: the built-in items carry
their CDASH tag as an ``Alias`` (and ``SDSVarName`` where it is an SDTM name), and one more form, ``Form.cdash``, on
the first event holds the CDASH IE rows (the criterion a screen failure did not meet) and DS rows (consent, screen
failure, completion, withdrawal) fed from the screening log's steps. A REDCap project does not have these items, so
the REDCap round trip uses ``odm``; ``cdisc`` is for a sponsor or an EDC that reads CDASH.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any
from xml.etree import ElementTree as ET  # building only; nothing is parsed here

from edc import cdash
from tb_common import sheets

from datacore import proxy_consent
from datacore.forms import LANGS, XML_ILLEGAL, Field, checkbox_column, fields_of, titles_of, xml_text
from datacore.lifecycle import Lifecycle, live_steps
from datacore.store import DataCore, DataError

RECORD_ID = "record_id"
BASE_EVENT = "event_1_arm_1"  # REDCap's one event of a classic (not longitudinal) project
ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
FORMATS = ("odm", "cdisc", "csv", "xlsx")
CDASH_FORM = "cdash"  # the CDISC export's own form (IE and DS rows)
BUILTIN_FORMS = ("tb_screening_log", "tb_consent", "tb_enrolment", "tb_visit", "tb_adverse_event", "tb_deviation",
                 "tb_withdrawal")  # fmt: skip
_DTYPE = {"integer": "integer", "decimal": "float", "date": "date", "dateTime": "datetime", "multi": "boolean"}


def export_fields(dc: DataCore, study: str) -> list[Field]:
    """The study's fields in form order, with the record id first (as REDCap's dictionary starts)."""
    out: list[Field] = []
    for q in dc.forms(study):
        out.extend(f for f in fields_of(q) if f.kind != "display")
    # 10C-19 (D-1232): the consent form's representative and assent items come last, after every other column, so a
    # reader of the columns before them finds them where they were (absent while the setting is off)
    late = [f for f in out if f.form == "tb_consent" and f.name in proxy_consent.FIELDS]
    out = [f for f in out if f not in late] + late
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
            row.update({checkbox_column(f.name, c): "1" if c in picked else "0" for c in f.options})
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
    bad = sorted({c for r in rows for c in cols if XML_ILLEGAL.search(str(r[c]))})
    if bad:  # EDC-010 (D-581): a row from before the rule; the workbook library would raise its own error
        raise DataError(
            "DATA-CHARS",
            "a stored value holds a character a file cannot carry; correct it, then export: " + ", ".join(bad),
            [{"field": name, "code": "chars"} for name in bad],
        )
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
    sheets.no_formulas(wb)  # NEW-CSV-1 (D-549): a typed value that begins with = stays text
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def item_def_attrs(f: Field) -> dict[str, str]:
    """``DataType`` with the ``Length`` ODM 1.3.2 asks of text, integer and float items, and ``SignificantDigits``
    (decimal places) of a float: the field's own when its REDCap validation names them (``number_1dp``), else 4
    (E-23 a, STD-062, T-115)."""
    dtype = _DTYPE.get(f.kind, "text")
    if dtype == "text":
        return {"DataType": "text", "Length": "999"}
    if dtype == "integer":
        return {"DataType": "integer", "Length": "11"}
    if dtype == "float":
        m = re.match(r"^number_(\d)dp", f.validation)
        return {"DataType": "float", "Length": "16", "SignificantDigits": m.group(1) if m else "4"}
    return {"DataType": dtype}


def _sub(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, tag, {k: v for k, v in attrs.items() if v != ""})


def write_xml(root: ET.Element) -> str:
    """The ODM file of ``root`` (EDC-010, D-581). Text that is not a value (a label, a name, a reason) has a
    character XML 1.0 does not allow written as U+FFFD; the values were checked by the caller before this."""
    for el in root.iter():
        if el.text:
            el.text = xml_text(el.text)
        for name, text in el.attrib.items():
            el.set(name, xml_text(text))
    ET.indent(root, space=" ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


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


def cdash_rows(dc: DataCore, study: str) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Per record, its CDASH IE and DS rows (``("IE", row)``, ``("DS", row)``) from the screening log's standing
    steps (D-396)."""
    by_rec: dict[str, list[dict[str, Any]]] = {}
    for st in Lifecycle(dc).steps(study):
        by_rec.setdefault(str(st["record"]), []).append(st)
    out: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for rec, steps in by_rec.items():
        live = live_steps(steps)
        rows = [("IE", r) for r in cdash.ie_rows(live)] + [("DS", r) for r in cdash.ds_rows(live)]
        if rows:
            out[rec] = rows
    return out


def _cdash_alias(idf: ET.Element, f: Field) -> None:
    """A built-in item's CDASH tag (D-396), and the CTCAE version item's SDTM trial summary parameter."""
    if f.form not in BUILTIN_FORMS:
        return
    tag = cdash.BUILTIN.get(f.name, "")
    if tag:
        _sub(idf, "Alias", Context="CDASH", Name=tag)
    elif f.name == "ae_ctcae_version":
        _sub(idf, "Alias", Context="SDTM", Name=cdash.TOXGRV)


def odm(dc: DataCore, study: str, at: str, cdisc: bool = False) -> str:
    """CDISC ODM 1.3.2 (``FileType="Snapshot"``): ``Study``/``MetaDataVersion`` from the forms, ``ClinicalData``
    from the values. ``at`` is the creation time (ISO 8601 with offset). ``cdisc`` adds the CDASH tags and the IE
    and DS rows (D-396)."""
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
    extra = cdash_rows(dc, study) if cdisc else {}
    with_base = any(not r["event"] for r in dc.values(study)) or not events or bool(extra)
    event_names = ([BASE_EVENT] if with_base else []) + [e for e in events if e != BASE_EVENT]
    proto = _sub(mdv, "Protocol")
    for i, ev in enumerate(event_names, 1):
        _sub(proto, "StudyEventRef", StudyEventOID=f"Event.{ev}", OrderNumber=str(i), Mandatory="No")
    forms = [str(q["name"]) for q in qs]
    for ev in event_names:
        sed = _sub(mdv, "StudyEventDef", OID=f"Event.{ev}", Name=ev, Repeating="No", Type="Common")
        for i, fm in enumerate(forms, 1):
            _sub(sed, "FormRef", FormOID=f"Form.{fm}", OrderNumber=str(i), Mandatory="No")
        if cdisc and ev == event_names[0]:
            _sub(sed, "FormRef", FormOID=f"Form.{CDASH_FORM}", OrderNumber=str(len(forms) + 1), Mandatory="No")
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
    domains = (("IE", cdash.IE_ITEMS), ("DS", cdash.DS_ITEMS)) if cdisc else ()
    if cdisc:
        fd = _sub(mdv, "FormDef", OID=f"Form.{CDASH_FORM}", Name="CDASH IE and DS", Repeating="No")
        for dom, _ in domains:
            _sub(fd, "ItemGroupRef", ItemGroupOID=f"IG.{dom}", Mandatory="No")
    for fm, fs in groups.items():
        ig = _sub(mdv, "ItemGroupDef", OID=group_oid[fm], Name=fm, Repeating="No")
        for f in fs:
            for oid in _item_oids(f):
                _sub(ig, "ItemRef", ItemOID=oid, Mandatory="Yes" if f.required else "No")
    for dom, items in domains:  # repeating: one group per IE criterion or DS event
        ig = _sub(mdv, "ItemGroupDef", OID=f"IG.{dom}", Name=dom, Repeating="Yes", SASDatasetName=dom, Domain=dom)
        for var, _ in items:
            _sub(ig, "ItemRef", ItemOID=f"{dom}.{var}", Mandatory="No")
    codelists: list[Field] = []
    for f in fields:
        if f.kind == "multi":
            for c, d in f.options.items():
                col = checkbox_column(f.name, c)
                idf = _sub(mdv, "ItemDef", OID=col, Name=col, DataType="boolean")
                tr = {g: f"{f.label_in(g)} ({f.options_in(g).get(c, d)})" for g in f.labels}
                _texts(idf, "Question", f"{f.label} ({d})", tr)
            continue
        idf = _sub(mdv, "ItemDef", OID=f.name, Name=f.name, **item_def_attrs(f))
        _texts(idf, "Question", f.label or f.name, f.labels)
        for comp, v in (("GE", f.vmin), ("LE", f.vmax)):
            if v:
                rc = _sub(idf, "RangeCheck", Comparator=comp, SoftHard="Hard")
                _sub(rc, "CheckValue").text = v
        if f.kind == "choice":
            _sub(idf, "CodeListRef", CodeListOID=f"{f.name}.choices")
            codelists.append(f)
        if cdisc:
            _cdash_alias(idf, f)
    for dom, items in domains:
        for var, dtype in items:
            attrs = {"DataType": "text", "Length": "200"} if dtype == "text" else {"DataType": dtype}
            idf = _sub(mdv, "ItemDef", OID=f"{dom}.{var}", Name=var, **attrs, SDSVarName=cdash.sds_name(var))
            _texts(idf, "Question", cdash.VARIABLES.get(f"{dom}.{var}", var), {})
            _sub(idf, "Alias", Context="CDASH", Name=f"{dom}.{var}")
    for f in codelists:
        cl = _sub(mdv, "CodeList", OID=f"{f.name}.choices", Name=f.name, DataType="text")
        for c, d in f.options.items():
            item = _sub(cl, "CodeListItem", CodedValue=c)
            _texts(item, "Decode", d, {g: f.options_in(g).get(c, "") for g in f.option_labels})
    cd = _sub(root, "ClinicalData", StudyOID=study_oid, MetaDataVersionOID=mdv_oid)
    data: dict[str, dict[str, dict[str, str]]] = {}
    bad: set[str] = set()
    for r in dc.values(study):
        fld = by_name.get(str(r["field"]))
        if fld is None or fld.name == RECORD_ID or r["value"] == "":
            continue
        if XML_ILLEGAL.search(str(r["value"])):  # a row from before the rule (D-581): never written, never altered
            bad.add(fld.name)
        if XML_ILLEGAL.search(str(r["record"])) or XML_ILLEGAL.search(str(r["event"])):
            bad.add("record or event key")  # two keys must never become one SubjectKey by replacement
        data.setdefault(str(r["record"]), {}).setdefault(event_name(str(r["event"])), {})[fld.name] = str(r["value"])
    if bad:
        raise DataError(
            "DATA-CHARS",
            "a stored value holds a character an XML file cannot carry; correct it, then export: "
            + ", ".join(sorted(bad)),
            [{"field": name, "code": "chars"} for name in sorted(bad)],
        )
    for rec in extra:
        data.setdefault(rec, {}).setdefault(event_names[0], {})
    for rec in sorted(data):
        sd = _sub(cd, "SubjectData", SubjectKey=rec)  # a Snapshot file has no TransactionType (the XSD, T-115)
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
                            _sub(
                                igd,
                                "ItemData",
                                ItemOID=checkbox_column(f.name, c),
                                Value="1" if c in picked else "0",
                            )
                    else:
                        _sub(igd, "ItemData", ItemOID=f.name, Value=vals[f.name])
            if ev == event_names[0] and extra.get(rec):
                fdata = _sub(se, "FormData", FormOID=f"Form.{CDASH_FORM}", FormRepeatKey="1")
                n = {"IE": 0, "DS": 0}
                for dom, row in extra[rec]:
                    n[dom] += 1
                    igd = _sub(fdata, "ItemGroupData", ItemGroupOID=f"IG.{dom}", ItemGroupRepeatKey=str(n[dom]))
                    for var, _ in dict(domains)[dom]:
                        if row.get(var):
                            _sub(igd, "ItemData", ItemOID=f"{dom}.{var}", Value=row[var])
    return write_xml(root)


def _item_oids(f: Field) -> list[str]:
    return [checkbox_column(f.name, c) for c in f.options] if f.kind == "multi" else [f.name]


def values_of(dc: DataCore, study: str) -> dict[tuple[str, str, str], str]:
    """Every non-blank value of a form field as ``(record, event, field) -> raw value`` (the round-trip check)."""
    names = {f.name for f in export_fields(dc, study)} - {RECORD_ID}
    return {(str(r["record"]), str(r["event"]), str(r["field"])): str(r["value"]) for r in dc.values(study)
            if r["field"] in names and r["value"] != ""}  # fmt: skip


def media(fmt: str) -> tuple[str, str]:
    """(file suffix, media type) of an export format."""
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return {"odm": (".odm.xml", "application/xml"), "cdisc": (".cdisc.odm.xml", "application/xml"),
            "csv": (".csv", "text/csv"), "xlsx": (".xlsx", xlsx)}[fmt]  # fmt: skip


def export(dc: DataCore, study: str, fmt: str, at: str) -> Any:
    """``odm``, ``cdisc`` and ``csv`` as text, ``xlsx`` as bytes."""
    if fmt in ("odm", "cdisc"):
        return odm(dc, study, at, cdisc=fmt == "cdisc")
    if fmt == "csv":
        return redcap_csv(dc, study)
    if fmt == "xlsx":
        return xlsx(dc, study)
    raise ValueError(fmt)
