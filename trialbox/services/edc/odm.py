"""CDISC ODM 1.3.2 of a study's signed prefill values (D-160): the generic path to any EDC that imports ODM.

TrialBox never types into another EDC's screens (no screen-scraping, no RPA). A site whose EDC is not REDCap imports
this file, or keys it in by hand from it. Only values a person confirmed **and** signed are written, and only while
they still match their signature (``EdcStore.signed``).

The file is ``FileType="Transactional"``: each ``ItemData`` is an ``Upsert`` and carries

* ``AuditRecord``: who decided the value, where, when, the reason when it was changed, and the citation as
  ``SourceID`` (the hospital record or note it came from, never its content);
* ``Signature``: who signed, where, when, and the ``SignatureDef`` that states the meaning.

``AdminData`` lists the users, the site and the signature's meaning. Each ``ItemDef`` carries its CDASH tag
(``SDSVarName`` and an ``Alias`` with ``Context="CDASH"``). OIDs follow REDCap's (``Project.<study>``,
``Event.<event>``, ``Form.<form>``, the field name as ``ItemOID``) so a REDCap project takes the file back as it is.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from xml.etree import ElementTree as ET  # building only; nothing is parsed here

from datacore.export import BASE_EVENT, ODM_NS, _sub, _texts
from datacore.forms import Field

SIGNATURE_OID = "SD.transcribed"
LOCATION_OID = "LOC.site"


def _oid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)


def user_oid(name: str) -> str:
    """One OID per user name; a short hash keeps ``a@b`` and ``a_b`` apart (review E-23)."""
    return f"USR.{_oid(name)}.{hashlib.sha256(name.encode('utf-8')).hexdigest()[:6]}"


def source_id(c: dict[str, Any] | None) -> str:
    """The citation as one short id: ``kind:table:row@snapshot`` (no clinical text)."""
    if not c:
        return ""
    if c.get("kind") == "manual":
        return f"manual:{c.get('day') or ''}"
    return f"{c.get('kind', '')}:{c.get('table', '')}:{c.get('row', '')}@{c.get('snapshot', '')}"


def build(study: str, fields: dict[str, Field], items: list[dict[str, Any]], values: list[dict[str, Any]],
          signatures: dict[int, dict[str, Any]], meaning_text: str, at: str) -> str:  # fmt: skip
    """``items``: the map rows (item, cdash, test, unit); ``values``: signed drafts (``EdcStore.signed``);
    ``signatures``: id -> signature row. ``at``: the creation time, ISO 8601 with offset."""
    stamp = re.sub(r"[^0-9]", "", at)[:14]
    study_oid, mdv_oid = f"Project.{_oid(study)}", f"Metadata.{_oid(study)}_edc"
    digest = hashlib.sha256(json.dumps([[v.get("id"), v.get("final")] for v in values], default=str).encode())
    file_oid = f"TrialBox.edc.{_oid(study)}.{stamp}.{digest.hexdigest()[:8]}"  # unique within a second (E-28)
    root = ET.Element("ODM", {"xmlns": ODM_NS, "FileType": "Transactional", "FileOID": file_oid,
                              "CreationDateTime": at, "ODMVersion": "1.3.2", "SourceSystem": "TrialBox",
                              "Granularity": "All"})  # fmt: skip
    st = _sub(root, "Study", OID=study_oid)
    gv = _sub(st, "GlobalVariables")
    for tag in ("StudyName", "StudyDescription", "ProtocolName"):
        _sub(gv, tag).text = study
    mdv = _sub(st, "MetaDataVersion", OID=mdv_oid, Name=f"{study} prefill items")
    by_item = {str(m["item"]): m for m in items}
    used = [fields[n] for n in by_item if n in fields]
    events = sorted({str(v["visit"]) or BASE_EVENT for v in values}) or [BASE_EVENT]
    proto = _sub(mdv, "Protocol")
    for i, ev in enumerate(events, 1):
        _sub(proto, "StudyEventRef", StudyEventOID=f"Event.{ev}", OrderNumber=str(i), Mandatory="No")
    groups: dict[str, list[Field]] = {}
    for f in used:
        groups.setdefault(f.form, []).append(f)
    group_oid = {fm: f"{fm}.{fs[0].name}" for fm, fs in groups.items()}
    for ev in events:
        sed = _sub(mdv, "StudyEventDef", OID=f"Event.{ev}", Name=ev, Repeating="No", Type="Common")
        for i, fm in enumerate(groups, 1):
            _sub(sed, "FormRef", FormOID=f"Form.{fm}", OrderNumber=str(i), Mandatory="No")
    for fm in groups:
        fd = _sub(mdv, "FormDef", OID=f"Form.{fm}", Name=fm, Repeating="No")
        _sub(fd, "ItemGroupRef", ItemGroupOID=group_oid[fm], Mandatory="No")
    for fm, fs in groups.items():
        ig = _sub(mdv, "ItemGroupDef", OID=group_oid[fm], Name=fm, Repeating="No")
        for f in fs:
            _sub(ig, "ItemRef", ItemOID=f.name, Mandatory="No")
    codelists: list[Field] = []
    dtypes = {"integer": "integer", "decimal": "float", "date": "date", "dateTime": "datetime"}
    for f in used:
        m = by_item[f.name]
        tag = str(m.get("cdash") or "")
        dtype = dtypes.get(f.kind, "text")
        idf = _sub(mdv, "ItemDef", OID=f.name, Name=f.name, DataType=dtype, Length="999" if dtype == "text" else "",
                   SDSVarName=tag.split(".", 1)[1] if "." in tag else "")  # fmt: skip
        if m.get("unit"):
            _texts(idf, "Description", f"Unit: {m['unit']}", {})
        _texts(idf, "Question", f.label or f.name, f.labels)
        if f.kind == "choice":
            _sub(idf, "CodeListRef", CodeListOID=f"{f.name}.choices")
            codelists.append(f)
        if tag:
            _sub(idf, "Alias", Context="CDASH", Name=tag)
            if m.get("test"):
                _sub(idf, "Alias", Context="CDASH-TESTCD", Name=str(m["test"]))
    for f in codelists:
        cl = _sub(mdv, "CodeList", OID=f"{f.name}.choices", Name=f.name, DataType="text")
        for c, d in f.options.items():
            _texts(_sub(cl, "CodeListItem", CodedValue=c), "Decode", d, {})
    # AdminData: the people who decided or signed, the site, and what a signature means
    ad = _sub(root, "AdminData", StudyOID=study_oid)
    people = sorted({str(v["decided_by"]) for v in values} | {str(s["signer"]) for s in signatures.values()})
    names = {str(s["signer"]): str(s["printed_name"]) for s in signatures.values()}
    for p in people:
        u = _sub(ad, "User", OID=user_oid(p), UserType="Other")
        _sub(u, "LoginName").text = p
        if p in names:
            _sub(u, "FullName").text = names[p]
    loc = _sub(ad, "Location", OID=LOCATION_OID, Name="Study site", LocationType="Site")
    _sub(loc, "MetaDataVersionRef", StudyOID=study_oid, MetaDataVersionOID=mdv_oid, EffectiveDate=at[:10])
    sd = _sub(ad, "SignatureDef", OID=SIGNATURE_OID, Methodology="Electronic")
    _sub(sd, "Meaning").text = meaning_text
    _sub(sd, "LegalReason").text = "21 CFR Part 11 electronic signature; ER/ES guideline (Japan)"
    # ClinicalData: signed values only
    cd = _sub(root, "ClinicalData", StudyOID=study_oid, MetaDataVersionOID=mdv_oid)
    data: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for v in values:
        if str(v["item"]) in by_item and str(v["item"]) in fields:
            data.setdefault(str(v["record"]), {}).setdefault(str(v["visit"]) or BASE_EVENT, []).append(v)
    for rec in sorted(data):
        sdat = _sub(cd, "SubjectData", SubjectKey=rec, TransactionType="Upsert")
        for ev in sorted(data[rec]):
            se = _sub(sdat, "StudyEventData", StudyEventOID=f"Event.{ev}", StudyEventRepeatKey="1")
            for fm, fs in groups.items():
                here = {str(v["item"]): v for v in data[rec][ev] if fields[str(v["item"])].form == fm}
                if not here:
                    continue
                fdata = _sub(se, "FormData", FormOID=f"Form.{fm}", FormRepeatKey="1")
                igd = _sub(fdata, "ItemGroupData", ItemGroupOID=group_oid[fm], ItemGroupRepeatKey="1")
                for f in fs:
                    val = here.get(f.name)
                    if val is None:
                        continue
                    v = val
                    idat = _sub(igd, "ItemData", ItemOID=f.name, Value=str(v["final"]), TransactionType="Upsert")
                    ar = _sub(idat, "AuditRecord")
                    _sub(ar, "UserRef", UserOID=user_oid(str(v["decided_by"])))
                    _sub(ar, "LocationRef", LocationOID=LOCATION_OID)
                    _sub(ar, "DateTimeStamp").text = str(v["decided_at"])
                    if v["fate"] == "edited" and v.get("reason"):
                        _sub(ar, "ReasonForChange").text = str(v["reason"])
                    sid = source_id(v.get("final_citation"))
                    if sid:
                        _sub(ar, "SourceID").text = sid
                    sig = signatures.get(int(v["signature_id"]))
                    if sig is not None:
                        sg = _sub(idat, "Signature")
                        _sub(sg, "UserRef", UserOID=user_oid(str(sig["signer"])))
                        _sub(sg, "LocationRef", LocationOID=LOCATION_OID)
                        _sub(sg, "SignatureRef", SignatureOID=SIGNATURE_OID)
                        _sub(sg, "DateTimeStamp").text = str(sig["at"])
    ET.indent(root, space=" ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
