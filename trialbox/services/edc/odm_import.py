"""Reading a CDISC ODM 1.3 file into proposals for a person to confirm (T-302d, D-435).

The file is outside data. It is read the same way whoever sent it:

* at most :data:`MAX_BYTES` (``TB_EDC_ODM_MAX_BYTES``), decoded strictly by ``tb_common.encoding.decode`` (D-215);
* parsed with expat directly, never with ElementTree's parser (bandit B314): a document type declaration, an entity
  declaration or an external entity reference stops the parse; the depth, the number of elements and the length of
  a value are bounded;
* checked whole before anything is kept: one problem refuses the file with a named reason (:class:`OdmRefused`),
  so a file is never half-imported. An OID is a name the sender chose: two definitions or two values with the same
  key refuse the file.

:func:`read` answers the values as they sit in the file (:class:`OdmValue`); :func:`proposals` turns them into one
proposal per record, visit and item of the study's map, with D-414's visit names (``<event>``,
``<event>__<form>__<n>``, ``<event>__<n>``) and a REDCap checkbox's ``field___code`` items folded back into the
several-choices value, each value checked against its field. TrialBox's own export (:mod:`edc.odm`) re-imports
equal. Storing a proposal is :meth:`edc.service.EdcService.import_odm`: an open draft, never a signed value.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from xml.parsers import expat

from datacore import forms
from datacore.export import BASE_EVENT, ODM_NS
from datacore.forms import Field, problem, reason
from tb_common.encoding import EncodingRefused, decode

from edc.layout import visit_of

MAX_BYTES_ENV = "TB_EDC_ODM_MAX_BYTES"
MAX_BYTES = 5_000_000
MAX_DEPTH = 16  # ODM/ClinicalData/SubjectData/StudyEventData/FormData/ItemGroupData/ItemData/... is 7 deep
MAX_ELEMENTS = 500_000
MAX_VALUE = 4000  # characters of one attribute or text
VERSIONS = ("1.3", "1.3.1", "1.3.2")
FILE_TYPES = ("Snapshot", "Transactional")
TRANSACTIONS = ("", "Insert", "Update", "Upsert")  # never Remove or Context: an import does not delete
_RECORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_KEY = re.compile(r"^[1-9]\d{0,3}$")
_NS = ODM_NS + " "


class OdmRefused(ValueError):
    """The file is refused whole. ``code`` names the reason (``odm.*``); ``where`` the place in the file."""

    def __init__(self, code: str, message: str, where: str = "") -> None:
        super().__init__(f"{code}: {message}" + (f" ({where})" if where else ""))
        self.code = code
        self.message = message
        self.where = where


def max_bytes(env: Mapping[str, str] | None = None) -> int:
    raw = str((os.environ if env is None else env).get(MAX_BYTES_ENV) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else MAX_BYTES


@dataclass
class _Node:
    tag: str  # the local name of an ODM element; "" for an element of another namespace (kept out)
    attrs: dict[str, str]
    children: list[_Node] = field(default_factory=list)

    def kids(self, tag: str) -> list[_Node]:
        return [c for c in self.children if c.tag == tag]


def _parse(data: bytes) -> _Node:
    """The document as a tree of ODM elements, with expat: no DTD, no entity, bounded."""
    try:
        text, _codec = decode(data)
    except EncodingRefused as exc:
        raise OdmRefused("odm.encoding", exc.message, f"line {exc.line}" if exc.line else "") from exc
    p = expat.ParserCreate(encoding="UTF-8", namespace_separator=" ")
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    root: list[_Node] = []
    stack: list[_Node] = []
    count = [0]

    def no_dtd(*_: Any) -> None:
        raise OdmRefused("odm.dtd", "the file declares a DTD or an entity; ODM needs neither")

    def start(name: str, attrs: dict[str, str]) -> None:
        count[0] += 1
        if count[0] > MAX_ELEMENTS:
            raise OdmRefused("odm.size", f"more than {MAX_ELEMENTS} elements")
        if len(stack) >= MAX_DEPTH:
            raise OdmRefused("odm.depth", f"elements nested deeper than {MAX_DEPTH}")
        local = name[len(_NS) :] if name.startswith(_NS) else ""
        if stack and not stack[-1].tag:
            local = ""  # everything under another namespace's element stays out
        kept = {}
        for k, v in attrs.items():
            if len(v) > MAX_VALUE:
                raise OdmRefused("odm.size", f"an attribute longer than {MAX_VALUE} characters", k)
            if " " not in k:  # ODM's own attributes have no namespace; a vendor's (redcap:...) are left out
                kept[k] = v
        node = _Node(local, kept)
        if stack:
            stack[-1].children.append(node)
        else:
            root.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        stack.pop()

    p.StartDoctypeDeclHandler = no_dtd
    p.EntityDeclHandler = no_dtd
    p.UnparsedEntityDeclHandler = no_dtd
    p.ExternalEntityRefHandler = no_dtd  # type: ignore[assignment]
    p.StartElementHandler = start
    p.EndElementHandler = end
    try:
        p.Parse(text.encode("utf-8"), True)
    except expat.ExpatError as exc:
        raise OdmRefused("odm.xml", f"not well-formed XML ({expat.errors.messages.get(exc.code, 'error')})",
                         f"line {exc.lineno}") from None  # fmt: skip
    if not root:
        raise OdmRefused("odm.not_odm", "the file has no root element")
    return root[0]


@dataclass(frozen=True)
class OdmValue:
    """One ``ItemData`` as it sits in the file. A repeat key of 0: the element had none."""

    record: str
    event: str
    event_key: int
    form: str
    form_key: int
    item: str
    value: str

    @property
    def path(self) -> str:
        ev = f"Event.{self.event}" + (f"[{self.event_key}]" if self.event_key else "")
        fm = f"Form.{self.form}" + (f"[{self.form_key}]" if self.form_key else "")
        return f"{self.record}/{ev}/{fm}/{self.item}"


@dataclass
class OdmFile:
    sha256: str
    file_oid: str
    file_type: str
    study_oid: str
    values: list[OdmValue]
    repeating_forms: set[str]
    repeating_events: set[str]


def _key(raw: str | None, where: str) -> int:
    raw = (raw or "").strip()
    if not raw:
        return 0
    if not _KEY.match(raw):
        raise OdmRefused("odm.repeat_key", f"repeat key {raw[:20]!r} is not a whole number from 1", where)
    return int(raw)


def _transaction(n: _Node, where: str) -> None:
    t = n.attrs.get("TransactionType", "")
    if t not in TRANSACTIONS:
        raise OdmRefused("odm.transaction", f"TransactionType {t[:20]!r}: an import only inserts or updates", where)


def _prefixed(oid: str, prefix: str, code: str, where: str) -> str:
    name = oid[len(prefix) :] if oid.startswith(prefix) else ""
    if not _NAME.match(name):
        raise OdmRefused(code, f"{oid[:60]!r} is not {prefix}<name>", where)
    return name


def _definitions(study: _Node, mdv_oid: str) -> tuple[set[str], set[str]]:
    """The repeating forms and events of the MetaDataVersion the data names; duplicate definitions refuse the
    file. No MetaDataVersion: nothing repeats."""
    mdvs = [m for m in study.kids("MetaDataVersion") if m.attrs.get("OID") == mdv_oid]
    if len(mdvs) > 1:
        raise OdmRefused("odm.duplicate_oid", "two MetaDataVersion elements with one OID", mdv_oid[:60])
    if not mdvs:
        return set(), set()
    forms: set[str] = set()
    events: set[str] = set()
    for tag, out in (("FormDef", forms), ("StudyEventDef", events)):
        seen: set[str] = set()
        for d in mdvs[0].kids(tag):
            oid = d.attrs.get("OID", "")
            if oid in seen:
                raise OdmRefused("odm.duplicate_oid", f"two {tag} elements with one OID", oid[:60])
            seen.add(oid)
            if d.attrs.get("Repeating") == "Yes":
                out.add(oid)
    seen_items: set[str] = set()
    for tag in ("ItemDef", "ItemGroupDef", "CodeList"):
        for d in mdvs[0].kids(tag):
            oid = f"{tag}:{d.attrs.get('OID', '')}"
            if oid in seen_items:
                raise OdmRefused("odm.duplicate_oid", f"two {tag} elements with one OID", oid[:60])
            seen_items.add(oid)
    return forms, events


def read(data: bytes, study_oid: str, env: Mapping[str, str] | None = None) -> OdmFile:
    """Read and check the whole file; ``study_oid``: the study it must be for (``Project.<study>``)."""
    limit = max_bytes(env)
    if len(data) > limit:
        raise OdmRefused("odm.size", f"the file is larger than {limit} bytes")
    if not data.strip():
        raise OdmRefused("odm.not_odm", "the file is empty")
    sha = hashlib.sha256(data).hexdigest()
    root = _parse(data)
    if root.tag != "ODM":
        raise OdmRefused("odm.not_odm", f"the root element is not ODM in the namespace {ODM_NS}")
    if root.attrs.get("ODMVersion", "") not in VERSIONS:
        raise OdmRefused("odm.version", f"ODMVersion {root.attrs.get('ODMVersion', '')[:10]!r}: ODM 1.3 is read")
    ftype = root.attrs.get("FileType", "")
    if ftype not in FILE_TYPES:
        raise OdmRefused("odm.file_type", f"FileType {ftype[:20]!r}: Snapshot or Transactional")
    for other in ("ReferenceData", "AnnotatedData"):
        if root.kids(other):
            raise OdmRefused("odm.element", f"{other} is not read", other)
    cds = root.kids("ClinicalData")
    if not cds:
        raise OdmRefused("odm.no_data", "the file has no ClinicalData")
    studies = [s for s in root.kids("Study") if s.attrs.get("OID") == study_oid]
    if len(studies) > 1:
        raise OdmRefused("odm.duplicate_oid", "two Study elements with one OID", study_oid)
    values: list[OdmValue] = []
    keys: dict[tuple[str, str, int, str, int, str], str] = {}
    rep_forms: set[str] = set()
    rep_events: set[str] = set()
    mdv_seen: set[str] = set()
    for cd in cds:
        if cd.attrs.get("StudyOID") != study_oid:
            raise OdmRefused("odm.study", f"ClinicalData is for {cd.attrs.get('StudyOID', '')[:60]!r}, not this "
                             f"study ({study_oid})")  # fmt: skip
        mdv = cd.attrs.get("MetaDataVersionOID", "")
        if mdv not in mdv_seen and studies:
            f, e = _definitions(studies[0], mdv)
            rep_forms |= {x.removeprefix("Form.") for x in f}
            rep_events |= {x.removeprefix("Event.") for x in e}
            mdv_seen.add(mdv)
        for sd in cd.kids("SubjectData"):
            rec = sd.attrs.get("SubjectKey", "").strip()
            if not _RECORD.match(rec):
                raise OdmRefused("odm.subject", f"SubjectKey {rec[:40]!r} is not a record key", "SubjectData")
            _transaction(sd, rec)
            for se in sd.kids("StudyEventData"):
                ev = _prefixed(se.attrs.get("StudyEventOID", ""), "Event.", "odm.event", rec)
                ek = _key(se.attrs.get("StudyEventRepeatKey"), f"{rec}/Event.{ev}")
                _transaction(se, f"{rec}/Event.{ev}")
                for fd in se.kids("FormData"):
                    fm = _prefixed(fd.attrs.get("FormOID", ""), "Form.", "odm.form", f"{rec}/Event.{ev}")
                    fk = _key(fd.attrs.get("FormRepeatKey"), f"{rec}/Event.{ev}/Form.{fm}")
                    _transaction(fd, f"{rec}/Event.{ev}/Form.{fm}")
                    for ig in fd.kids("ItemGroupData"):
                        where = f"{rec}/Event.{ev}/Form.{fm}"
                        if _key(ig.attrs.get("ItemGroupRepeatKey"), where) > 1:
                            raise OdmRefused("odm.repeat_key", "item groups do not repeat (repeat the form)", where)
                        _transaction(ig, where)
                        for it in ig.children:
                            if it.tag != "ItemData":
                                if it.tag:
                                    raise OdmRefused("odm.element", f"{it.tag} is not read (ItemData only)", where)
                                continue
                            _transaction(it, where)
                            oid = it.attrs.get("ItemOID", "")
                            v = OdmValue(rec, ev, ek, fm, fk, oid, it.attrs.get("Value", ""))
                            if it.attrs.get("IsNull") == "Yes":
                                v = OdmValue(rec, ev, ek, fm, fk, oid, "")
                            k = (rec, ev, ek, fm, fk, oid)
                            if k in keys:
                                raise OdmRefused("odm.duplicate_value", "one item twice on one row", v.path)
                            keys[k] = v.value
                            values.append(v)
    return OdmFile(sha, root.attrs.get("FileOID", "")[:200], ftype, study_oid, values, rep_forms, rep_events)


@dataclass(frozen=True)
class Proposal:
    record: str
    visit: str
    item: str
    form: str
    value: str
    path: str


def _visit(v: OdmValue, f: OdmFile) -> str:
    """D-414's name of the row: a repeat key counts only on a form or event the file defines as repeating; on any
    other it must be 1 (REDCap and TrialBox's Snapshot write 1) or absent."""
    form_rep = v.form in f.repeating_forms
    ev_rep = v.event in f.repeating_events
    if v.form_key > 1 and not form_rep:
        raise OdmRefused("odm.repeat_key", f"Form.{v.form} does not repeat but has repeat key {v.form_key}", v.path)
    if v.event_key > 1 and not ev_rep:
        raise OdmRefused("odm.repeat_key", f"Event.{v.event} does not repeat but has repeat key {v.event_key}",
                         v.path)  # fmt: skip
    if form_rep and ev_rep:
        raise OdmRefused("odm.repeat_key", "a repeating form on a repeating event is not read", v.path)
    if form_rep:
        return visit_of(v.event, v.form, v.form_key or 1)
    if ev_rep:
        return visit_of(v.event, "", v.event_key or 1)
    return visit_of(v.event or BASE_EVENT)


def proposals(f: OdmFile, fields: Mapping[str, Field], mapped: Iterable[str], record_field: str = "record_id",
              protected: Iterable[str] = ()) -> list[Proposal]:  # fmt: skip
    """One proposal per record, visit and mapped item with a value; the whole file refused on the first problem.
    ``record_field`` and ``protected`` (the target's key fields) are skipped: they say whose row it is, they are
    not values to confirm."""
    skip = {record_field, *protected}
    allowed = set(mapped)
    rows: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    ticks: dict[tuple[str, str, str], dict[str, str]] = {}
    for v in f.values:
        if v.item in skip:
            continue
        base, sep, _code = v.item.partition("___")
        name = base if sep else v.item
        fld = fields.get(name)
        if fld is None or name not in allowed:
            raise OdmRefused("odm.unknown_item", f"{v.item[:60]!r} is not an item of the study's map", v.path)
        if fld.kind in ("calc", "file", "display"):
            raise OdmRefused("odm.unknown_item", f"{name} is computed or not entered; it is never imported", v.path)
        if fld.form != v.form:
            raise OdmRefused("odm.wrong_form", f"{name} is on the form {fld.form}, not {v.form}", v.path)
        if bool(sep) != (fld.kind == "multi"):
            raise OdmRefused("odm.unknown_item", f"{v.item[:60]!r} does not match the field's kind", v.path)
        visit = _visit(v, f)
        key = (v.record, visit, name)
        if sep:
            choice = forms.checkbox_code(fld, v.item)  # the column as REDCap names it (NEW-EDC-3b)
            if choice is None or v.value not in ("", "0", "1"):
                raise OdmRefused("odm.invalid", f"{v.item[:60]!r}: a choice of {name} is 0 or 1", v.path)
            ticks.setdefault(key, {})[choice] = v.value
            rows.setdefault(key, (fld.form, "", v.path.rsplit("/", 1)[0] + f"/{name}"))
            continue
        if key in rows:
            raise OdmRefused("odm.duplicate_value", "one item twice for one visit", v.path)
        rows[key] = (fld.form, v.value, v.path)
    out: list[Proposal] = []
    for key, (form, value, path) in sorted(rows.items()):
        rec, visit, name = key
        fld = fields[name]
        if key in ticks:
            value = ",".join(c for c in fld.options if ticks[key].get(c) == "1")
        if value == "":
            continue
        p = problem(fld, value)
        if p is not None:
            raise OdmRefused("odm.invalid", reason(p, value), path)
        out.append(Proposal(rec, visit, name, form, value, path))
    return out


def citation(f: OdmFile, p: Proposal, name: str) -> dict[str, Any]:
    """The source of an imported value: the file (sha256, name, FileOID) and the place of the value in it."""
    return {"kind": "odm", "file": f.sha256, "name": name[:120], "file_oid": f.file_oid, "path": p.path[:300]}
