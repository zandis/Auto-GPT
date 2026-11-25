"""M3: the one way out of the box, and the one rule set behind it (D-1093, 10G-49).

Inside the box notes are read as written. What leaves passes :func:`leave`: the route's rule is looked up, the payload
is masked, refused or (on an exception route) let through to its named destination, and one line is written to the
audit log (``tb_common.egress_record``) BEFORE the payload is handed back. No rule, no named destination, a payload the
rules cannot read, a masker that fails, a record that cannot be written: nothing leaves (:class:`Refused`).

The identifier rules are :func:`spans`: the note masker's (``phi_guard.note_spans``), the log scrubber's and the
guard's. The log scrubber, the support bundle's scrub, the tripwire and every export read them here. They find the
named forms (a labelled name, chart number, date of birth, national id, phone, address, e-mail); a person's name
standing free in running text is not one of them, and no test claims it. Pixels are not read: a picture on its own is
refused, a picture inside a document is not looked at.

Standard library and ``phi_guard`` only at import: the support bundle runs this on the host's python3.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import unicodedata
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tb_common import egress_record, phi_guard

MASK_CHAR = phi_guard.MASK_CHAR
MAX_BYTES = 64 * 1024 * 1024  # a larger payload is refused: it cannot be read whole


class Refused(RuntimeError):
    """Nothing left. ``reason`` is a code, never a value."""

    def __init__(self, route: str, reason: str) -> None:
        super().__init__(f"{route}: {reason}")
        self.route, self.reason = route, reason


# ------------------------------------------------------------------------------------------------ the routes
@dataclass(frozen=True)
class Route:
    """``mode``: ``mask`` (text is masked; what cannot be masked is refused), ``refuse`` (any identifier refuses) or
    ``exception`` (as it is, to a named destination, under ``role``). ``free_text``: whether note text may be in it.
    ``fields``: the columns of a table the rule names; any other is masked whole. ``door``: the file and the call that
    send this route through :func:`leave` (the doctor reads it)."""

    mode: str
    door: tuple[str, str]
    role: str = ""
    keep: frozenset[str] = frozenset()  # kinds that stay readable
    free_text: bool = True
    fields: frozenset[str] | None = None


_CONSOLE = ("services/console/app.py", "egress_page.register(")
_MAIL = ("services/mail_gateway/gateway.py", "gate_mail(")
_AUDIT_COLUMNS = frozenset(
    [
        "time",
        "event",
        "label",
        "kind",
        "actor",
        "study",
        "job",
        "pid",
        "purpose",
        "reason",
        "basis",
        "via",
        "cap",
        "refused",
        "grant",
        "detail",
        "hash",
    ]
)
_NAMED = "the patient file's named recipients (D-369)"
ROUTES: dict[str, Route] = {
    "log": Route("mask", ("libs/tb_common/logging.py", "egress_edge import spans")),
    "support.bundle": Route("mask", ("tools/support*.py", '"support.bundle"')),
    "mail.staff": Route("mask", _MAIL),
    # a reply goes to its sender and quotes the sender's own subject: an address in it stays
    "mail.reply": Route("mask", ("services/mail_gateway/gateway.py", '"mail.reply"'), keep=frozenset({"email"})),
    "mail.test": Route("mask", ("services/console/backend.py", '"mail.test"')),
    "download.audit": Route("mask", _CONSOLE, fields=_AUDIT_COLUMNS),
    "download.aggregate": Route("mask", _CONSOLE, free_text=False),
    "download.study": Route("mask", _CONSOLE),
    "download.site": Route("mask", _CONSOLE),
    "download.registry": Route("refuse", _CONSOLE),  # the log with every chart number: ruling (b) names no exception
    "model.offbox": Route("refuse", ("services/gateway/core.py", '"model.offbox"')),
    "patient.mail": Route("exception", _MAIL, role=_NAMED),
    "patient.download": Route("exception", _CONSOLE, role=_NAMED),
    "edc.write": Route("exception", ("services/orchestrator/study_api.py", '"edc.write"'), role="the signed EDC send"),
    "nhi.submit": Route(
        "exception", ("services/orchestrator/scenarios/submit.py", '"nhi.submit"'), role="the confirmed SUBMIT"
    ),
}
#: the three exceptions of ruling (b); the patient file leaves by mail or by its sign-in link
EXCEPTIONS = {"patient": ("patient.mail", "patient.download"), "edc": ("edc.write",), "nhi": ("nhi.submit",)}

#: a console address that gives a file, and its route (None: the job's output says, ``console.egress_page``)
DOWNLOADS: tuple[tuple[re.Pattern[str], str | None], ...] = tuple(
    (re.compile(p), r)
    for p, r in (
        (r"^/pilot/jobs/[^/]+/files/[^/]+$", None),
        (r"^/pilot/jobs/[^/]+/sponsor-pack\.zip$", "download.aggregate"),
        (r"^/pilot/cascade/[^/]+/files/[^/]+$", "download.aggregate"),
        (r"^/reports/research-office\.xlsx$", "download.aggregate"),
        (r"^/pilot/registry/[^/]+/export\.xlsx$", "download.registry"),
        (r"^/audit/patients/[^/]+/report\.csv$", "download.audit"),
        (r"^/studies/[^/]+/screening-log\.xlsx$", "download.study"),
        (r"^/studies/[^/]+/enrolment\.[a-z]+$", "download.study"),
        (r"^/studies/[^/]+/export\.[a-z.]+$", "download.study"),
        (r"^/studies/[^/]+/edc/(?:copy\.csv|export\.odm\.xml)$", "download.study"),
        (r"^/api/v1/studies/[^/]+/(?:enrolment|export)/[^/]+$", "download.study"),
        (r"^/api/v1/studies/[^/]+/edc/export/odm$", "download.study"),
        (r"^/feedback/export\.csv$", "download.site"),
        (r"^/admin/ops/network/[^/]+$", "download.site"),
        (r"^/site/templates/[^/]+\.xlsx$", "download.site"),
    )
)


def download_route(path: str) -> tuple[bool, str | None]:
    """Whether ``path`` is a listed download, and its route (None: the job's output says)."""
    for rx, route in DOWNLOADS:
        if rx.match(path):
            return True, route
    return False, None


# ------------------------------------------------------------------------------------------------ the rule set
#: the guard's forms the note masker does not hold (``guard.recognisers`` reads them from here)
NAME_EN_CTX = re.compile(
    r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+|\b(?:Patient(?: name)?|Name|Pt)\s*[:：]\s*)"
    r"(?P<v>[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)?)"
)
PASSPORT_CTX = re.compile(
    r"(?:護照(?:號碼|号码|號)?|旅券(?:番号)?|パスポート(?:番号)?|(?i:passport)(?:\s*(?:no\.?|number|#))?)"
    r"[\s:：#]*(?P<v>[A-Z0-9]{6,9})(?![A-Za-z0-9])"
)
#: the box's own ids (a digest, a pseudonym, a UUID, a job id): digits inside one are no identifier
_OWN = re.compile(
    r"(?<![0-9A-Za-z])(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|(?=[0-9]*[a-f])[0-9a-f]{16,}"
    r"|(?=[0-9]*[A-Z])[0-7][0-9A-HJKMNP-TV-Z]{25})(?![0-9A-Za-z])"
)
#: a US social security number (V5-09)
_SSN = re.compile(r"(?<![0-9A-Za-z\-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![0-9A-Za-z\-])")
#: a compact ROC birth date (year, month, day) before 出生 (V5-08)
_BORN_ROC = re.compile(r"(?<!\d)\d{2,3}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?=\s*出生)")
_FRACTION = re.compile(r"\d\.$")  # the digits after a decimal point are no phone number
Span = tuple[str, int, int]


def _folded(text: str) -> str:
    """``text`` with every full-width character written half-width, place by place (V5-05, V5-06)."""
    if text.isascii():
        return text
    return "".join(n if len(n := unicodedata.normalize("NFKC", c)) == 1 else c for c in text)


def spans(text: str, mrn_regex: str | None = None, *, own_ids: bool = False) -> list[Span]:
    """Where the named forms stand in ``text``: ``(kind, start, end)``, merged, in order. ``own_ids``: the box's own
    ids stay readable (an export, the bundle); the log scrubber and the tripwire hide them too."""
    from tb_common.logging import _PHI_PATTERNS  # the log scrubber's forms; logging reads this module when it scrubs

    found: list[Span] = []
    for view in {text: None, _folded(text): None}:  # as written, and in half width: the same places
        found += phi_guard.note_spans(view, mrn_regex) if mrn_regex else phi_guard.note_spans(view)
        for kind, rx in (("name", NAME_EN_CTX), ("id", PASSPORT_CTX)):
            found += [(kind, m.start("v"), m.end("v")) for m in rx.finditer(view)]
        for kind, rx in (("id", _SSN), ("dob", _BORN_ROC)):
            found += [(kind, m.start(), m.end()) for m in rx.finditer(view)]
        for pat, r in _PHI_PATTERNS:
            found += [(r.strip("[]").lower(), m.start(), m.end()) for m in pat.finditer(view)
                      if not _FRACTION.search(view, max(m.start() - 2, 0), m.start())]  # fmt: skip
    if own_ids and found:
        own = [m.span() for m in _OWN.finditer(text)]
        found = [f for f in found if not any(a <= f[1] and f[2] <= b for a, b in own)]
    merged: list[Span] = []
    for kind, s, e in sorted(found, key=lambda f: (f[1], -f[2])):
        if e <= s:
            continue
        if merged and s < merged[-1][2]:
            k, s0, e0 = merged[-1]
            merged[-1] = (k, s0, max(e, e0))
        else:
            merged.append((kind, s, e))
    return merged


def _cover(text: str, found: Iterable[tuple[int, int]]) -> str:
    out = list(text)
    for s, e in found:
        for i in range(s, e):
            if not out[i].isspace():
                out[i] = MASK_CHAR
    return "".join(out)


def mask_text(text: str, mrn_regex: str | None = None) -> str:
    """``text`` with every named form masked, the length and the white space kept."""
    return _cover(text, ((s, e) for _k, s, e in spans(text, mrn_regex, own_ids=True)))


# ------------------------------------------------------------------------------------------------ reading a payload
@dataclass(frozen=True)
class Site:
    mrn: str | None
    domains: tuple[str, ...] = ()


def site() -> Site:
    """The site's chart-number form and mail domains. Without a readable site, the contract's own form: a chart
    number is never let through because the settings could not be read."""
    try:
        from tb_common.config import get_config

        s = get_config().settings
        return Site(s.mrn_regex, tuple(d.lower() for d in s.internal_domains))
    except Exception:
        try:
            from tb_contracts.generated.models import Settings

            return Site(str(Settings.model_fields["mrn_regex"].default))
        except Exception:  # the host's python3
            return Site(r"^\d{8}$")


#: a field whose name alone says whose value it is
_DIRECT = frozenset(
    [
        "mrn",
        "chart",
        "chartno",
        "chartnumber",
        "patientname",
        "dob",
        "birthdate",
        "dateofbirth",
        "nationalid",
        "phone",
        "mobile",
        "telephone",
    ]
)
#: a field that holds note text (ruling (c): refused on an aggregate route)
_FREE = frozenset(
    [
        "notetext",
        "notestext",
        "charttext",
        "freetext",
        "narrative",
        "clinicalnote",
        "progressnote",
        "nursingnote",
        "evidencetext",
    ]
)


#: a field that holds a study's own number of a person, which is no identifier outside the site
_STUDY_NO = re.compile(
    r"(?i)^(?:subject|screening|record|participant|randomi[sz]ation)[ _-]?(?:id|no|number|nr)?\b|^record_?id$|"
    r"受試者編號|篩選編號|被験者番号|被験者識別|スクリーニング番号|症例番号|登録番号"
)


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9\u3040-\u9fff]", "", label.lower())


_TITLE = r"(?:醫師|医師|醫生|護理師|看護師|藥師|薬剤師|技師)"
#: a title, or the staff code the box prints after a doctor's name (a letter first: no chart number)
_TITLE_AFTER = re.compile(rf"{_TITLE}|[ \u3000]?\([A-Z]{{1,3}}\d{{3,6}}\)")
_TITLE_BEFORE = re.compile(rf"(?:{_TITLE}|主治医|担当医|\bDrs?\.?)[ :：(（/]*$")
_PATIENT_BEFORE = re.compile(r"(?i)(?:姓名|氏名|名前|患者|病患|病人|個案|受試者|patient(?: name)?|name|\bpt)[\s:：]*$")


def _staff(text: str, s: int, e: int) -> bool:
    before = text[max(s - 16, 0) : s]
    if _PATIENT_BEFORE.search(before):
        return False
    return bool(_TITLE_AFTER.match(text, e) or _TITLE_BEFORE.search(before))


#: a consent form is read by patients: the hospital's own telephone, mail and address in it must stay readable
_SITE_DOCUMENT = re.compile(r"^consent_[\w-]+\.(?:html|json)$")


def _kept_in(name: str) -> frozenset[str]:
    return frozenset({"phone", "email", "address"}) if _SITE_DOCUMENT.match(name) else frozenset()


class _Reader:
    """One payload on its way out: the count of identifiers found, and the masked copy."""

    def __init__(self, rule: Route, where: Site) -> None:
        self.rule, self.site, self.keep = rule, where, rule.keep
        self.hits = 0

    # -------------------------------------------------------------------------------- text
    def find(self, text: str) -> list[tuple[int, int]]:
        """The identifiers in ``text``. An address of the site's own mail domain, and a name written with a member of
        staff's title and no patient's label, is no patient's: a report names its doctors."""
        out = []
        for k, s, e in spans(text, self.site.mrn, own_ids=True):
            at = text[s:e].rpartition("@")
            if not (at[1] and at[2].lower().rstrip(".") in self.site.domains) and not (
                k in self.keep or (k == "name" and _staff(text, s, e))
            ):
                out.append((s, e))
        return out

    def text(self, text: str) -> str:
        got = self.find(text)
        self.hits += len(got)
        return _cover(text, got) if got else text

    def value(self, label: str, value: str) -> str:
        """A value with its field's name: read alone, and as ``label: value``."""
        if not value.strip():
            return value
        key = _norm(label)
        if key in _FREE and not self.rule.free_text:
            raise Refused("", "free_text")
        if key in _DIRECT or (label and self.rule.fields is not None and key not in self.rule.fields):
            self.hits += key in _DIRECT
            return _cover(value, [(0, len(value))])
        got = self.find(value)
        if label and len(label) <= 60 and not _STUDY_NO.search(label):
            pre = f"{label}: "
            got += [(max(s - len(pre), 0), e - len(pre)) for s, e in self.find(pre + value) if e > len(pre)]
        self.hits += len(got)
        return _cover(value, got) if got else value

    def scalar(self, label: str, v: Any) -> Any:
        if v is None or isinstance(v, bool):
            return v
        s = v if isinstance(v, str) else v.isoformat() if hasattr(v, "isoformat") else str(v)
        t = self.value(label, s)
        return v if t == s else t

    def tree(self, v: Any, label: str = "") -> Any:
        if isinstance(v, Mapping):
            return {self.text(str(k)): self.tree(x, str(k)) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [self.tree(x, label) for x in v]
        return self.scalar(label, v)

    # -------------------------------------------------------------------------------- files
    def file(self, name: str, data: bytes, depth: int = 0) -> bytes:
        before, self.keep = self.keep, self.keep | _kept_in(name)
        try:
            return self._file(name, data, depth)
        finally:
            self.keep = before

    def _file(self, name: str, data: bytes, depth: int) -> bytes:
        if len(data) > MAX_BYTES:
            raise Refused("", "too_large")
        kind = Path(name.lower()).suffix
        if data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):  # what it is, not what it is called
            return self.archive(data, depth)
        if data[:5] == b"%PDF-":
            return self.pdf(data)
        try:
            raw = data.decode("utf-8")
        except UnicodeDecodeError:
            raise Refused("", "unreadable") from None
        if re.search(r"[\x00-\x08\x0e-\x1f]", raw):
            raise Refused("", "unreadable")
        out = self.document(kind, raw)
        return data if out == raw else out.encode("utf-8")

    def document(self, kind: str, raw: str) -> str:
        if kind == ".json":
            return self.json(raw, 1)
        if kind == ".jsonl":
            return "\n".join(self.json(x, None) if x.strip() else x for x in raw.split("\n"))
        if kind == ".csv":
            return self.table(raw)
        out = self.text(raw)
        if kind in (".html", ".htm", ".xml") and self.find(html.unescape(re.sub(r"<[^>]+>", " ", out))):
            raise Refused("", "identifiers")  # a label in one element, its value in the next
        return out

    def json(self, raw: str, indent: int | None) -> str:
        try:
            obj = json.loads(raw)
        except ValueError:
            return self.text(raw)
        new = self.tree(obj)
        return raw if new == obj else json.dumps(new, ensure_ascii=False, indent=indent)

    def table(self, raw: str) -> str:
        bom, body = ("\ufeff", raw[1:]) if raw.startswith("\ufeff") else ("", raw)
        rows = list(csv.reader(io.StringIO(body)))
        if not rows:
            return raw
        head = rows[0]
        new = [[self.text(c) for c in head]]
        new += [[self.value(head[i] if i < len(head) else "", c) for i, c in enumerate(r)] for r in rows[1:]]
        if new == rows:
            return raw
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\r\n" if "\r\n" in body else "\n").writerows(new)
        return bom + buf.getvalue()

    def pdf(self, data: bytes) -> bytes:
        from pypdf import PdfReader

        try:
            r = PdfReader(io.BytesIO(data))
            body = "\n".join(p.extract_text() or "" for p in r.pages)
            meta = "\n".join(str(v) for v in (r.metadata or {}).values())
        except Exception:
            raise Refused("", "unreadable") from None
        if not body.strip():  # a scan: nothing in it can be read
            raise Refused("", "unreadable")
        self.none_in(body + "\n" + meta)
        return data

    def none_in(self, text: str) -> None:
        got = self.find(text)
        if got:
            self.hits += len(got)
            raise Refused("", "identifiers")

    def archive(self, data: bytes, depth: int) -> bytes:
        from tb_common.zipcap import ZipRefused, check_infos

        if depth > 2:
            raise Refused("", "unreadable")
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            infos = z.infolist()
            check_infos(infos)
        except (zipfile.BadZipFile, ZipRefused):
            raise Refused("", "unreadable") from None
        if any(i.flag_bits & 1 for i in infos):  # encrypted
            raise Refused("", "unreadable")
        names = {i.filename for i in infos}
        if "[Content_Types].xml" in names:
            return self.workbook(data, z) if "xl/workbook.xml" in names else self.parts(data, z)
        old = {i.filename: z.read(i) for i in infos if not i.is_dir()}
        new = {n: self.file(n, d, depth + 1) for n, d in old.items()}
        safe = {n: self.name(n) for n in old}
        if new == old and all(a == b for a, b in safe.items()):
            return data
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as out:
            for i in infos:
                if not i.is_dir():
                    info = zipfile.ZipInfo(safe[i.filename], date_time=i.date_time)
                    info.compress_type = i.compress_type
                    out.writestr(info, new[i.filename])
        return buf.getvalue()

    def parts(self, data: bytes, z: zipfile.ZipFile, skip: str = "") -> bytes:
        """An office document's text, part by part. It is not rewritten: an identifier refuses it."""
        for i in z.infolist():
            if i.filename.endswith(".xml") and not (skip and re.match(skip, i.filename)):
                raw = z.read(i).decode("utf-8", errors="replace")
                raw = re.sub(r"</(?:\w+:)?(?:p|tr)>", "\n", raw)  # a paragraph's runs read together
                self.none_in(html.unescape(re.sub(r"<[^>]+>", "", raw)))
        return data

    def workbook(self, data: bytes, z: zipfile.ZipFile) -> bytes:
        """A workbook's cells, each read with its column's head and with the cell to its left; every other part
        (properties, comments, drawings) as text."""
        from openpyxl import load_workbook

        self.parts(data, z, skip=r"xl/(?:worksheets/sheet|sharedStrings|styles|theme/|workbook\.xml)|docProps/app")
        try:
            wb = load_workbook(io.BytesIO(data))
        except Exception:
            raise Refused("", "unreadable") from None
        changed = False
        for ws in wb.worksheets:
            self.none_in(ws.title)
            head: list[str] = []
            for row in ws.iter_rows():
                left = ""
                for k, c in enumerate(row):
                    v = c.value
                    new: Any = v
                    for label in (head[k] if k < len(head) else "", left):
                        new = self.scalar(label, new)
                    if new != v:
                        c.value, changed = new, True
                    left = v if isinstance(v, str) else ""
                if not head and sum(isinstance(c.value, str) for c in row) >= 2:
                    head = [c.value if isinstance(c.value, str) else "" for c in row]
        if not changed:
            return data
        from tb_common.deterministic import normalize_ooxml

        buf = io.BytesIO()
        wb.save(buf)
        return normalize_ooxml(buf.getvalue())

    def name(self, name: str) -> str:
        """A file's name: an identifier in it becomes ``_``. Eight digits that are a day stay: the box dates its
        files so."""
        out = name
        view = re.sub(r"[._/-]", " ", name)  # a dot or a hyphen joins a number to the rest of a name
        for s, e in {*self.find(name), *self.find(view)}:
            if not _a_day(name[s:e]):
                self.hits += 1
                out = out[:s] + "_" * (e - s) + out[e:]
        return out


def _a_day(text: str) -> bool:
    try:
        return len(text) == 8 and 1990 <= date.fromisoformat(text).year < 2100
    except ValueError:
        return False


@dataclass(frozen=True)
class Message:
    """A mail on its way out."""

    subject: str
    body: str
    files: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True)
class File:
    """A file on its way out."""

    name: str
    data: bytes


def _bytes_of(p: Any) -> bytes:
    if isinstance(p, File):
        return p.data
    if isinstance(p, Message):
        return "\n".join([p.subject, p.body]).encode() + b"".join(d for _n, d in p.files)
    if isinstance(p, bytes):
        return p
    return p.encode() if isinstance(p, str) else json.dumps(p, ensure_ascii=False, sort_keys=True, default=str).encode()


def _clean(r: _Reader, p: Any) -> Any:
    if isinstance(p, File):
        return File(r.name(p.name), r.file(p.name, p.data))
    if isinstance(p, Message):
        return Message(r.text(p.subject), r.text(p.body), tuple((r.name(n), r.file(n, d)) for n, d in p.files))
    if isinstance(p, bytes):
        return r.file("", p)
    return r.text(p) if isinstance(p, str) else r.tree(p)


# ------------------------------------------------------------------------------------------------ the way out
def leave(
    route: str,
    destination: str,
    payload: Any,
    *,
    audit: Any,
    actor: str,
    named: Iterable[str] = (),
    items: int | None = None,
    unchecked: bool = False,
    refused: str = "",
    note: str = "",
) -> Any:
    """The payload as it may leave by ``route`` to ``destination``, or :class:`Refused`. ``payload``: a text, a
    mapping or list, a :class:`File` or a :class:`Message`. ``audit``: the service's audit log; a record that cannot be
    written refuses. ``named``: an exception route's named destinations. ``items``: how many patients it is about, when
    the caller knows. ``unchecked``: the tripwire's development switch, for a model off the box only. ``refused``: an
    exception's own check already said no, and why; ``note``: what it did not know."""
    rule = ROUTES.get(route)
    out, why, result = payload, "", "sent"
    reader: _Reader | None = None
    try:
        if rule is None:
            why = "no_rule"
        elif rule.mode == "exception":
            result = "exception"
            if not actor or not destination or destination not in set(named):
                why = "not_named"
            why = why or refused
        elif unchecked and route == "model.offbox":
            result = "unchecked"
        else:
            reader = _Reader(rule, site())
            out = _clean(reader, payload)
            if rule.mode == "refuse" and reader.hits:
                why = "identifiers"
            result = "masked" if reader.hits else "sent"
    except Refused as exc:
        why = exc.reason
    except Exception:  # the masker failed: nothing is sent (the error's text may quote the payload)
        why = "mask_failed"
    body = _bytes_of(payload if why else out)
    try:
        egress_record.write(
            audit,
            actor=actor,
            route=route,
            destination=destination,
            kind=type(payload).__name__,
            items=items if items is not None or reader is None else reader.hits,
            rule=rule.mode if rule else "none",
            size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            result="refused" if why else result,
            reason=why or note,
        )
    except Exception:
        raise Refused(route, why or "not_recorded") from None
    if why:
        raise Refused(route, why)
    return out


class _Held:
    """An object store that answers the attachments of one mail as the edge left them."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self.files = files

    def get(self, key: str) -> bytes:
        return self.files[key]


#: (job, recipients) -> whether every recipient is on the study's delegation log today, and whether the person who
#: asked for the job is: yes, no, or unknown (None)
Rights = Callable[[str, list[str]], tuple[bool | None, bool | None]]


def may_have(delegated: bool | None, sender: bool | None) -> str:
    """Why a patient file may not go to its named recipients now ("" when it may): the current delegation and the
    asker's own rights, never a site-wide list (PR1239-H2, H3). A no refuses everywhere; unknown refuses on a
    PRODUCTION box and is recorded on any other."""
    for answer, why in ((delegated, "not_delegated"), (sender, "sender_right")):
        if answer is False or (answer is None and production()):
            return why
    return ""


def gate_mail(
    req: Any, store: Any, *, audit: Any, internal: Callable[[str], bool], rights: Rights | None = None
) -> tuple[Any, Any]:
    """A send request and its store as they may leave. A patient file goes as it is, to the site's own domains only
    (D-369 names its recipients), by :func:`may_have`; any other mail is read whole, attachments too."""
    atts = list(req.attachments or [])
    files = tuple((a.filename, store.get(a.minio_key)) for a in atts)
    to = sorted({str(r).strip().lower() for r in req.to if r})
    where = "mail:" + ",".join(sorted({r.rsplit("@", 1)[-1] for r in to}))
    patient = req.tag == "phi" or any(a.tag == "phi" for a in atts)
    why, note = "", ""
    if patient and atts:
        known = rights(str(req.job_id), to) if rights is not None and req.job_id else (None, None)
        why, note = may_have(*known), "rights unknown" if None in known else ""
    msg: Message = leave(
        "patient.mail" if patient else "mail.staff",
        where,
        Message(req.subject, req.body_md, files),
        audit=audit,
        actor=f"job:{req.job_id or '-'}",
        named=[where] if patient and to and all(internal(r) for r in to) else (),
        refused=why,
        note=note,
    )
    if not patient:
        new = [a.model_copy(update={"filename": n}) for a, (n, _d) in zip(atts, msg.files, strict=True)]
        req = req.model_copy(update={"subject": msg.subject, "body_md": msg.body, "attachments": new or None})
    return req, _Held({a.minio_key: d for a, (_n, d) in zip(atts, msg.files, strict=True)})


# ------------------------------------------------------------------------------------------------ the tripwire's switch
def production(env: Mapping[str, str] | None = None) -> bool:
    return ((os.environ if env is None else env).get("TB_ENV") or "PRODUCTION").strip().upper() == "PRODUCTION"


def tripwire_on(env: Mapping[str, str] | None = None) -> bool:
    raw = (os.environ if env is None else env).get("TB_GATEWAY_PHI_TRIPWIRE") or "on"
    return raw.strip().lower() not in ("off", "0", "false", "no")


# ------------------------------------------------------------------------------------------------ the doctor
ROOT = Path(__file__).resolve().parents[2]


def wired(route: str, root: Path = ROOT) -> bool | None:
    """Whether the route's door calls the edge in this tree; None when the file is not here to read."""
    file, call = ROUTES[route].door
    try:
        texts = [p.read_text(encoding="utf-8") for p in root.glob(file)]
    except OSError:
        return None
    return any(call in t for t in texts) if texts else None


def doctor_checks(env: Mapping[str, str] | None = None, root: Path = ROOT) -> list[tuple[str, str, str]]:
    """One row per route, then the tripwire: what its rule is and whether its door goes through the edge."""
    rows: list[tuple[str, str, str]] = []
    for key, r in ROUTES.items():
        says = {
            "mask": "identifiers masked; what cannot be masked is refused",
            "refuse": "identifiers refused",
            "exception": f"exception: {r.role}, audited",
        }[r.mode]
        on = wired(key, root)
        if on is None:
            rows.append((f"egress.{key}", "WARN", f"not looked at: {r.door[0]} is not here to read (rule: {says})"))
        elif on:
            rows.append((f"egress.{key}", "PASS", says))
        else:
            rows.append((f"egress.{key}", "FAIL", f"no masking: {r.door[0]} does not go through the egress edge"))
    if tripwire_on(env):
        rows.append(("egress.tripwire", "PASS", "the tripwire is on"))
    else:
        why = "the tripwire is off (TB_GATEWAY_PHI_TRIPWIRE): calls to a model off the box are not checked; turn it on"
        rows.append(("egress.tripwire", "FAIL" if production(env) else "WARN", f"{why} and restart the gateway"))
    return rows
