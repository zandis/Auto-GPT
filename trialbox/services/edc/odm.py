"""CDISC ODM 1.3.2 of a study's signed prefill values (D-160): the generic path to any EDC that imports ODM.

TrialBox never types into another EDC's screens (no screen-scraping, no RPA). A site whose EDC is not REDCap imports
this file, or keys it in by hand from it. Only values a person confirmed **and** signed are written, and only while
they still match their signature (``EdcStore.signed``).

The file is ``FileType="Transactional"``: each ``ItemData`` is an ``Upsert`` and carries

* ``AuditRecord``: who decided the value, where, when, the reason when it was changed, and the citation as
  ``SourceID`` (the hospital record or note it came from, never its content);
* ``Signature``: who signed, where, when, and the ``SignatureDef`` that states the meaning.

``AdminData`` lists the users, the site and one ``SignatureDef`` per meaning text and language a signer actually saw
(E-23 e). Each ``ItemDef`` carries ``Length`` (and ``SignificantDigits`` for a float), its unit as a
``MeasurementUnitRef`` to ``BasicDefinitions`` and its CDASH tag as an ``Alias`` with ``Context="CDASH"``;
``SDSVarName`` only when the CDASH name is also an SDTM variable (a CDASH date such as ``BRTHDAT`` is not). Repeat
keys are not written: no event, form or group here repeats (E-23 a to c, STD-062; T-115). OIDs follow REDCap's
(``Project.<study>``, ``Event.<event>``, ``Form.<form>``, the field name as ``ItemOID``) so a REDCap project takes
the file back as it is. The file holds each value as decided and signed; its earlier values stay in the trail
(D-368). The file is checked against the ODM 1.3.2 schema in the tests (E-25).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from xml.etree import ElementTree as ET  # building only; nothing is parsed here

from datacore.export import BASE_EVENT, ODM_NS, _sub, _texts, item_def_attrs
from datacore.forms import Field

LOCATION_OID = "LOC.site"
#: the signature's legal reason in the file (D-281, REG-021): a plain statement, no claim of conformance with 21 CFR
#: Part 11 or the Japanese ER/ES guideline. It changes only when an assessment of those rules is on file.
LEGAL_REASON = "Electronic signature of the person named; see the site's validation summary"


def _oid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)


def user_oid(name: str) -> str:
    """One OID per user name; a short hash keeps ``a@b`` and ``a_b`` apart (review E-23)."""
    return f"USR.{_oid(name)}.{hashlib.sha256(name.encode('utf-8')).hexdigest()[:6]}"


def unit_oid(unit: str) -> str:
    """One OID per unit text; a short hash keeps ``mg/dL`` and ``mg_dL`` apart."""
    return f"MU.{_oid(unit)}.{hashlib.sha256(unit.encode('utf-8')).hexdigest()[:6]}"


def signature_def_oid(meaning: str, lang: str, text: str) -> str:
    """One SignatureDef per meaning, language and the words the signer saw (E-23 e)."""
    return f"SD.{_oid(meaning)}.{_oid(lang)}.{hashlib.sha256(text.encode('utf-8')).hexdigest()[:6]}"


def sds_name(var: str) -> str:
    """The SDTM variable of a CDASH name, or "" when the CDASH name is not one: CDASH dates and times (``BRTHDAT``,
    ``VSDAT``, ``VISDAT``, ``--TIM``) become ``--DTC`` in SDTM, so they carry only the CDASH alias (STD-062)."""
    return "" if re.search(r"(DAT|TIM)$", var) else var


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
    by_item = {str(m["item"]): m for m in items}
    used = [fields[n] for n in by_item if n in fields]
    units = sorted({str(by_item[f.name]["unit"]) for f in used if by_item[f.name].get("unit")})
    if units:  # E-23 c: the unit is a MeasurementUnit, not a free text
        bd = _sub(st, "BasicDefinitions")
        for unit in units:
            _texts(_sub(bd, "MeasurementUnit", OID=unit_oid(unit), Name=unit), "Symbol", unit, {})
    mdv = _sub(st, "MetaDataVersion", OID=mdv_oid, Name=f"{study} prefill items")
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
    for f in used:
        m = by_item[f.name]
        tag = str(m.get("cdash") or "")
        attrs = item_def_attrs(f) if f.kind != "multi" else {"DataType": "text", "Length": "999"}
        idf = _sub(mdv, "ItemDef", OID=f.name, Name=f.name, **attrs,
                   SDSVarName=sds_name(tag.split(".", 1)[1]) if "." in tag else "")  # fmt: skip
        _texts(idf, "Question", f.label or f.name, f.labels)
        if m.get("unit"):
            _sub(idf, "MeasurementUnitRef", MeasurementUnitOID=unit_oid(str(m["unit"])))
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

    # E-23 e: one SignatureDef per meaning, language and words a signer saw; a row from before the words were kept
    # takes the service's text
    def words(s: dict[str, Any]) -> tuple[str, str, str]:
        return str(s.get("meaning") or "transcribed"), str(s.get("lang") or "en"), str(s.get("meaning_text") or
                                                                                         meaning_text)  # fmt: skip

    defs = sorted({words(s) for s in signatures.values()}) or [("transcribed", "en", meaning_text)]
    for mn, lg, tx in defs:
        sd = _sub(ad, "SignatureDef", OID=signature_def_oid(mn, lg, tx), Methodology="Electronic")
        _sub(sd, "Meaning").text = tx
        _sub(sd, "LegalReason").text = LEGAL_REASON
    # ClinicalData: signed values only
    cd = _sub(root, "ClinicalData", StudyOID=study_oid, MetaDataVersionOID=mdv_oid)
    data: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for v in values:
        if str(v["item"]) in by_item and str(v["item"]) in fields:
            data.setdefault(str(v["record"]), {}).setdefault(str(v["visit"]) or BASE_EVENT, []).append(v)
    for rec in sorted(data):
        sdat = _sub(cd, "SubjectData", SubjectKey=rec, TransactionType="Upsert")
        for ev in sorted(data[rec]):
            se = _sub(sdat, "StudyEventData", StudyEventOID=f"Event.{ev}")
            for fm, fs in groups.items():
                here = {str(v["item"]): v for v in data[rec][ev] if fields[str(v["item"])].form == fm}
                if not here:
                    continue
                fdata = _sub(se, "FormData", FormOID=f"Form.{fm}")
                igd = _sub(fdata, "ItemGroupData", ItemGroupOID=group_oid[fm])
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
                        _sub(sg, "SignatureRef", SignatureOID=signature_def_oid(*words(sig)))
                        _sub(sg, "DateTimeStamp").text = str(sig["at"])
    ET.indent(root, space=" ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
