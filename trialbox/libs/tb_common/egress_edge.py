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

import ast
import csv
import functools
import hashlib
import html
import io
import json
import os
import re
import struct
import threading
import unicodedata
import zipfile
import zlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tb_common import egress_record, phi_guard

MASK_CHAR = phi_guard.MASK_CHAR
MAX_BYTES = 64 * 1024 * 1024  # a larger payload is refused: it cannot be read whole
MADE_MAX = 4096  # the files this process remembers having built (the oldest is forgotten first)


# ------------------------------------------------------------------------------------------------ the box's own files
# 1523 ruling (round 3): a PDF, Office, zip or picture file leaves only when the box built it, by its hash in the box's
# own output record (this process's, below, or one the caller holds, as a job's outputs), or when it is rebuilt: its
# text read, masked, and set in a fresh plain PDF (the original never leaves). Any other is refused (``not_made``).
# The record is in memory and bounded: a restart forgets it, and a file it forgot is refused (built again, it leaves).
_MADE: dict[str, None] = {}
_MADE_LOCK = threading.Lock()


def made(data: bytes) -> bytes:
    """Record that this process built ``data`` itself, and give it back. Only where the code wrote the bytes (a
    workbook, a zip, a report): never on bytes uploaded, imported or handed in by a person
    (``tests/unit/test_egress_made.py`` lists every place that calls it)."""
    digest = hashlib.sha256(data).hexdigest()
    with _MADE_LOCK:
        _MADE.pop(digest, None)
        _MADE[digest] = None
        while len(_MADE) > MADE_MAX:
            del _MADE[next(iter(_MADE))]
    return data


def _box_made(digest: str, vouched: frozenset[str]) -> bool:
    with _MADE_LOCK:
        return digest in vouched or digest in _MADE


#: what makes a payload a container wherever it stands in the first 1024 bytes: a reader looks that far for a PDF's
#: header, and a zip, an SVG or an RTF file is no plain text (1523 review round 3, H1)
_CONTAINER_MARKS = (b"%pdf-", b"pk\x03\x04", b"pk\x05\x06", b"<svg", b"{\\rtf")


def _is_container(data: bytes) -> bool:
    """Whether ``data`` is a PDF, an Office file, a zip, a picture or anything else that is no plain text, decided fail
    closed on its first 1024 bytes: text only when they are UTF-8 (a character cut at the end aside), hold no control
    character, and none of :data:`_CONTAINER_MARKS` (in any case)."""
    head = data[:1024]
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError as exc:
        if len(head) < 1024 or exc.start < len(head) - 3:
            return True
        text = head[: exc.start].decode("utf-8", "replace")
    if re.search(r"[\x00-\x08\x0e-\x1f]", text):
        return True
    low = head.lower()
    return any(m in low for m in _CONTAINER_MARKS)


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
    send this route through :func:`leave` (the doctor reads it). ``only_named``: it goes to the caller's named
    destinations only; to any other, or with none named, it is refused."""

    mode: str
    door: tuple[str, str]
    role: str = ""
    keep: frozenset[str] = frozenset()  # kinds that stay readable
    free_text: bool = True
    fields: frozenset[str] | None = None
    only_named: bool = False


_CONSOLE = ("services/console/app.py", "egress_page(app")
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
    # the study's log with every chart number: the fourth exception (the integrator's default, D-1093 item 4)
    "download.registry": Route("exception", _CONSOLE, role="a person with the reveal right (D-438)"),
    "model.offbox": Route("refuse", ("services/gateway/core.py", '"model.offbox"')),
    "patient.mail": Route("exception", _MAIL, role=_NAMED),
    "patient.download": Route("exception", _CONSOLE, role=_NAMED),
    "edc.write": Route("exception", ("services/orchestrator/study_api.py", '"edc.write"'), role="the signed EDC send"),
    # P-13 ruling: /admin/edc's connection check, to the site's configured EDC host only (a read: never edc.write)
    "edc.tool": Route("refuse", ("services/console/edc_door.py", '"edc.tool"'), only_named=True),
    "nhi.submit": Route(
        "exception", ("services/orchestrator/scenarios/submit.py", '"nhi.submit"'), role="the confirmed SUBMIT"
    ),
}
#: ruling (b)'s three exceptions (the patient file leaves by mail or by its sign-in link) and the registry's log
EXCEPTIONS = {
    "patient": ("patient.mail", "patient.download"),
    "edc": ("edc.write",),
    "nhi": ("nhi.submit",),
    "registry": ("download.registry",),
}

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
#: an office document's parts that hold no text to read: its pictures and the printer's settings (OCR 1523-3)
_OPAQUE = re.compile(r"(?:\.(?:png|jpe?g|gif|bmp|tiff?|emf|wmf)|/printerSettings/[^/]+\.bin)$", re.I)
#: the PNG chunks a picture that is skipped may hold: none holds text (1523 review H4: tEXt, zTXt, iTXt, iCCP and
#: any chunk not named here refuse the part)
_PNG_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"pHYs", b"bKGD", b"sBIT"}
#: the JPEG segments a picture that is skipped may hold: frames, tables, JFIF, Adobe, the scan (no comment, no EXIF)
_JPEG_SEGMENTS = {*range(0xC0, 0xC4), *range(0xC5, 0xC8), *range(0xC9, 0xCC), *range(0xCD, 0xD0), 0xC4, 0xDB, 0xDD,
                  0xDA, 0xE0, 0xEE}  # fmt: skip
#: what a PDF's bytes may hold between its objects: white space and comments (which are read)
_PDF_GAP = re.compile(rb"(?:[\x00\t\n\x0c\r ]+|%[^\r\n]*)*")
#: a PDF's cross-reference table to its trailer's dictionary, and the pointer to the table, as they stand between
#: objects
_PDF_XREF = re.compile(rb"xref\s+(?:\d+\s+\d+\s+(?:\d{10} \d{5} [fn](?: \r| \n|\r\n))*)+trailer")
_PDF_START = re.compile(rb"startxref\s+\d+\s*%%EOF")
#: a sheet's cells, which :meth:`_Reader.workbook` reads with their columns (OCR 1523-19: the rest of the sheet as text)
_CELL_DATA = re.compile(rb"<(?:\w+:)?sheetData\b[^>]*/>|<(?:\w+:)?sheetData\b.*?</(?:\w+:)?sheetData>", re.S)
#: a workbook's parts that :meth:`_Reader.workbook` reads as cells
_CELLS = re.compile(r"xl/(?:worksheets/[^/]+|sharedStrings|styles|theme/[^/]+|workbook)\.xml$|docProps/app\.xml$")
#: an attribute of office markup, and those whose value is no one's words: a revision's, a paragraph's or a drawing's
#: id, a colour, an angle, a place or a size of a drawing, a cell's place and type, a font's signature, a GUID; and the
#: elements whose value is an id (a revision's, a list's, a list template's, the document's)
_ATTR = re.compile(r"""([\w:.-]+)\s*=\s*["']([^"']*)""")
_NOT_READ = re.compile(
    r"(?:\w+:)?(?:rsid\w*|paraId|textId|anchorId|editId|rgb|ang|rot|cx|cy|[xylrtb]|dist[TBLR]|relativeHeight|[uc]sb\d)"
)
_ID_ELEMENT = re.compile(r"<(?:\w+:)?(?:rsid|nsid|tmpl|docId)\b[^>]*>")
_GUID = re.compile(r"\{?[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}?")
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

    def __init__(self, rule: Route, where: Site, vouched: Iterable[str] = (), rebuild: bool = False) -> None:
        self.rule, self.site, self.keep = rule, where, rule.keep
        self.hits = 0
        self.vouched, self.rebuild = frozenset(str(v).lower() for v in vouched), rebuild

    def own(self, name: str, data: bytes) -> tuple[str, bytes]:
        """A file as it may go on to be read (1523 ruling): the box's own as it is; another rebuilt into a plain PDF
        when that was asked, or ``Refused`` (``not_made``). The size and the zip's caps are checked before a rebuild
        reads a byte of it (review round 3, M4)."""
        if not _is_container(data) or _box_made(hashlib.sha256(data).hexdigest(), self.vouched):
            return name, data
        if not self.rebuild:
            raise Refused("", "not_made")
        if len(data) > MAX_BYTES:
            raise Refused("", "too_large")
        if b"%PDF-" not in data[:1024]:
            from tb_common.zipcap import ZipRefused, check_infos

            try:
                check_infos(zipfile.ZipFile(io.BytesIO(data)).infolist())
            except (zipfile.BadZipFile, ZipRefused):
                raise Refused("", "unreadable") from None
        return f"{Path(name).stem or 'file'}.pdf", made(_plain_pdf(self.text(_text_of(data))))

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
        if _is_container(data):  # what it is, not what it is called; wherever its mark stands (review round 3, H1)
            head = data[:1024]
            if b"%PDF-" in head:
                return self.pdf(data, depth)
            if b"PK\x03\x04" in head or b"PK\x05\x06" in data[-65557:]:
                return self.archive(data, depth)
            raise Refused("", "unreadable")
        raw = _plain(data)
        if raw is None:
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

    def pdf(self, data: bytes, depth: int = 0) -> bytes:
        """A PDF's pages, every text its objects hold (a form's filled values, notes, its own description) and the
        files it carries, each read as a file of its own (OCR 1523-3). It is not rewritten: an identifier refuses it."""
        from pypdf import PdfReader

        try:
            r = PdfReader(io.BytesIO(data))
            body = "\n".join(p.extract_text() or "" for p in r.pages)
            seen: set[int] = set()
            texts, files = _pdf_parts(r.trailer, seen)
            hidden = _pdf_earlier(r, data, seen)
            texts += _pdf_bytes(r, data)  # 1523 review M1: its comments; a byte outside its objects refuses it
            for p in r.pages:  # and the comments in what a page draws
                if (shown := p.get_contents()) is not None:
                    texts += _pdf_drawn(shown.get_data())
        except Refused as exc:
            if exc.reason != "form_pdf":
                raise Refused("", "unreadable") from None
            raise
        except Exception:
            raise Refused("", "unreadable") from None
        if hidden:  # OCR 1523-20: an earlier revision's objects stay in the bytes, unread
            raise Refused("", "unreadable")
        if not body.strip():  # a scan: nothing in it can be read
            raise Refused("", "unreadable")
        self.none_in("\n".join([body, *texts]))
        for name, part in files:
            self.whole(name, part, depth)
        return data

    def whole(self, name: str, part: bytes, depth: int) -> None:
        """A file inside one that is not rewritten: refused when reading it would change it."""
        if self.file(name, part, depth + 1) != part:
            raise Refused("", "identifiers")

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
        if any(i.flag_bits & 1 for i in infos) or not _accounted(data, z, infos):  # encrypted; bytes no member holds
            raise Refused("", "unreadable")
        # OCR 1523-3: the archive's comment and its members' comments leave with it
        self.none_in("\n".join(c.decode("utf-8", "replace") for c in (z.comment, *(i.comment for i in infos)) if c))
        safe = {i.filename: self.name(i.filename) for i in infos}
        if "[Content_Types].xml" in safe:
            if any(a != b for a, b in safe.items()):
                raise Refused("", "identifiers")
            return self.workbook(data, z, depth) if "xl/workbook.xml" in safe else self.parts(data, z, depth)
        old = {i.filename: z.read(i) for i in infos if not i.is_dir()}
        new = {n: self.file(n, d, depth + 1) for n, d in old.items()}
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

    def parts(self, data: bytes, z: zipfile.ZipFile, depth: int = 0, cells: frozenset[str] = frozenset()) -> bytes:
        """An office document's text, part by part. It is not rewritten: an identifier refuses it. A part that is not
        XML (an embedded file, a list that a member named ``[Content_Types].xml`` sits beside) is read as a file of its
        own (OCR 1523-3); a picture is not looked at. ``cells``: the sheets whose cells :meth:`workbook` reads."""
        for i in z.infolist():
            if i.is_dir():
                continue
            if cells and _CELLS.match(i.filename):  # OCR 1523-19: what a sheet, the book or a format says beside cells
                if i.filename != "xl/sharedStrings.xml":  # its strings: workbook(), once the cells are known
                    # 1523 review H8: a sheet's cells are left to workbook() only when it read that sheet
                    self.markup(_CELL_DATA.sub(b"", z.read(i)) if i.filename in cells else z.read(i))
                continue
            part = z.read(i)
            markup = i.filename.endswith((".xml", ".rels", ".vml")) and part.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] == b"<"
            said = _opaque(i.filename, part) if _OPAQUE.search(i.filename) and _plain(part) is None else None
            if markup:
                self.markup(part)
            elif said is None:
                self.whole(i.filename, part, depth)
            else:  # a picture whose every byte is one, or the printer's settings: their names only
                self.none_in(said)
        return data

    def markup(self, part: bytes) -> None:
        raw = _plain(part)
        if raw is None:
            raise Refused("", "unreadable")
        # every attribute's value is read (OCR 1523-19; 1523 review H9: a document variable, a tooltip, an author, a
        # picture's alternative text), but the ids, sizes and signatures that hold no one's words (_NOT_READ)
        listed = _ID_ELEMENT.sub("", raw)
        links = [v for k, v in _ATTR.findall(listed) if not _NOT_READ.fullmatch(k) and not _GUID.fullmatch(v)]
        raw = re.sub(r"</(?:\w+:)?(?:p|tr|si)>", "\n", raw)  # a paragraph's runs read together
        # each value read apart: a table's widths one after another are no telephone number
        self.none_in(html.unescape("\n;\n".join([re.sub(r"<[^>]+>", "", raw), *links])))

    def workbook(self, data: bytes, z: zipfile.ZipFile, depth: int = 0) -> bytes:
        """A workbook's cells, each read with its column's head and with the cell to its left; every other part
        (properties, comments, drawings) as text."""
        from openpyxl import load_workbook
        from openpyxl.reader.excel import ExcelReader

        try:
            book = ExcelReader(io.BytesIO(data))  # load_workbook(), and the parts it read
            book.read()
            wb = book.wb
            read = frozenset(rel.target for _s, rel in book.parser.find_sheets()
                             if rel.target in book.valid_files and "chartsheet" not in rel.Type)  # fmt: skip
            cached = load_workbook(io.BytesIO(data), data_only=True).worksheets  # a formula's last value (review H8)
        except Exception:
            raise Refused("", "unreadable") from None
        if sum(bool(re.match(r"xl/worksheets/[^/]+\.xml$", n)) for n in z.namelist()) > len(wb.worksheets):
            raise Refused("", "unreadable")  # a sheet the book does not list: its cells are not read below
        self.parts(data, z, depth, cells=read)
        changed = False
        for ws, last in zip(wb.worksheets, cached, strict=True):
            self.none_in(ws.title)
            head: list[str] = []
            for row in ws.iter_rows():
                left = ""
                for k, c in enumerate(row):
                    v = c.value
                    if c.data_type == "f":  # the value it showed last leaves in the file as it is
                        shown = last[c.coordinate].value
                        for label in (head[k] if k < len(head) else "", left):
                            if self.scalar(label, shown) != shown:
                                raise Refused("", "identifiers")
                    new: Any = v
                    for label in (head[k] if k < len(head) else "", left):
                        new = self.scalar(label, new)
                    if new != v:
                        c.value, changed = new, True
                    left = v if isinstance(v, str) else ""
                if not head and sum(isinstance(c.value, str) for c in row) >= 2:
                    head = [c.value if isinstance(c.value, str) else "" for c in row]
        if not changed:
            for n in z.namelist():  # a text no cell shows leaves with the file as it is
                if n == "xl/sharedStrings.xml":
                    self.markup(z.read(n))
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


def _opaque(name: str, part: bytes) -> str | None:
    """What a part named a picture or the printer's settings says as text ("" for a picture), when every byte of it is
    what its name says (OCR 1523-3; 1523 review H4, H5: a prefix proves nothing); None when it is not."""
    if name.lower().endswith(".bin"):  # DEVMODE: its own size, no driver's bytes; the printer's and the form's names
        if len(part) < 72 or struct.unpack("<HH", part[68:72]) != (len(part), 0):
            return None
        return "\n".join(part[a:b].decode("utf-16-le", "replace").strip("\x00") for a, b in ((0, 64), (102, 166)))
    if (said := _jpeg(part)) is not None:
        return said
    return "" if _png(part) or _bmp(part) else None


def _png(b: bytes) -> bool:
    """A PNG whose chunks are all of :data:`_PNG_CHUNKS`, each with its own check sum, and nothing after its end."""
    if not b.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    pos = 8
    while pos + 12 <= len(b):
        size, kind = struct.unpack(">I4s", b[pos : pos + 8])
        end = pos + 12 + int(size)
        if (
            kind not in _PNG_CHUNKS
            or end > len(b)
            or zlib.crc32(b[pos + 4 : end - 4]) != int.from_bytes(b[end - 4 : end])
        ):
            return False
        pos = end
        if kind == b"IEND":
            return pos == len(b)
    return False


def _jpeg(b: bytes) -> str | None:
    """The text a JPEG holds beside its picture (its comments, EXIF, colour profile and other application segments, as
    single bytes and as UTF-16), when its segments are all of :data:`_JPEG_SEGMENTS` or those, ending at its end marker
    with nothing after it; None when it is not one."""
    if not b.startswith(b"\xff\xd8"):
        return None
    pos, said = 2, list[str]()
    while pos + 2 <= len(b):  # the end marker is two bytes; a segment says its size
        if b[pos] != 0xFF:
            return None
        marker = b[pos + 1]
        if marker == 0xD9:
            return "\n".join(said) if not b[pos + 2 :].strip(b"\x00") else None  # zeros after it (a writer's padding)
        size = int.from_bytes(b[pos + 2 : pos + 4])
        if (
            size < 2
            or pos + 2 + size > len(b)
            or (marker not in _JPEG_SEGMENTS and not (0xE1 <= marker <= 0xEF or marker == 0xFE))
        ):
            return None
        if marker not in _JPEG_SEGMENTS:
            body = b[pos + 4 : pos + 2 + size]
            said += [body.decode(c, "replace") for c in ("latin-1", "utf-16-le", "utf-16-be")]
        pos += 2 + size
        while marker == 0xDA:  # the scan's data, to the next marker that is no stuffed byte and no restart
            pos = b.find(b"\xff", pos)
            if pos < 0 or pos + 1 >= len(b):
                return None
            if b[pos + 1] != 0 and not 0xD0 <= b[pos + 1] <= 0xD7:
                break
            pos += 2
    return None


def _bmp(b: bytes) -> bool:
    """An uncompressed bitmap: its header, its palette and its rows, and not one byte more."""
    if len(b) < 54 or b[:2] != b"BM":
        return False
    size, r1, r2, at, hdr, width, height, _planes, bits, packed = struct.unpack("<IHHIIiiHHI", b[2:34])
    if size != len(b) or r1 or r2 or hdr not in (40, 108, 124) or packed not in (0, 3) or not 0 < bits <= 32:
        return False
    colours = struct.unpack("<I", b[46:50])[0] or (1 << bits if bits <= 8 else 0)
    masks = 12 if packed == 3 and hdr == 40 else 0
    rows = (bits * width + 31) // 32 * 4 * abs(height)
    return bool(width > 0 and at == 14 + hdr + masks + 4 * colours and at + rows == len(b))


def _accounted(data: bytes, z: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> bool:
    """Every byte of the archive is a member's record, the directory or the end record (OCR 1523-18), and a member's
    data is exactly what a reader takes from it (1523 review H1 to H3): no extra field, no data descriptor, no bytes
    after a stored member's end or a compressed member's stream, no method but stored and deflated."""
    pos = 0
    for i in sorted(infos, key=lambda i: i.header_offset):
        head = data[pos : pos + 30]
        if i.header_offset != pos or len(head) < 30 or head[:4] != b"PK\x03\x04" or i.extra or i.flag_bits & 8:
            return False
        n, e = struct.unpack("<HH", head[26:30])
        if e:
            return False
        raw = data[pos + 30 + n : pos + 30 + n + i.compress_size]
        if i.compress_type == zipfile.ZIP_STORED:
            if i.compress_size != i.file_size:
                return False
        elif i.compress_type == zipfile.ZIP_DEFLATED:
            d = zlib.decompressobj(-15)
            if (
                len(d.decompress(raw, i.file_size + 1)) != i.file_size
                or not d.eof
                or d.unused_data
                or d.unconsumed_tail
            ):
                return False
        else:
            return False
        pos += 30 + n + i.compress_size
    end = data.rfind(b"PK\x05\x06")
    if pos != z.start_dir or end < 0:
        return False
    size = struct.unpack("<I", data[end + 12 : end + 16])[0]
    return z.start_dir + size == end and end + 22 + len(z.comment) == len(data)


def _plain(data: bytes) -> str | None:
    """``data`` as text; None when it is not text."""
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if re.search(r"[\x00-\x08\x0e-\x1f]", raw) else raw


def _pdf_parts(trailer: Any, seen: set[int] | None = None) -> tuple[list[str], list[tuple[str, bytes]]]:
    """Every text a PDF's objects hold, and the files it carries with their names. A script, or a note drawn by its own
    picture of text (its appearance), is not read: ``Refused`` (OCR 1523-20)."""
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject, TextStringObject

    texts: list[str] = []
    files: list[tuple[str, bytes]] = []
    seen = set() if seen is None else seen
    todo: list[Any] = [trailer]
    while todo:
        o = todo.pop()
        if isinstance(o, IndirectObject):
            if o.idnum in seen:
                continue
            seen.add(o.idnum)
            o = o.get_object()
        if isinstance(o, TextStringObject):
            texts.append(str(o))
        elif isinstance(o, ArrayObject):
            todo.extend(list.__iter__(o))
        elif isinstance(o, DictionaryObject):
            todo.extend(dict.values(o))
            if "/AP" in o and o.get("/Subtype") == "/Widget":  # a form's field, or a signature, as it is drawn
                raise Refused("", "form_pdf")
            if "/JS" in o or ("/AP" in o and o.get("/Subtype") not in ("/Link", "/Popup")):
                raise Refused("", "unreadable")
            if "/EF" in o:
                name = str(o.get("/UF") or o.get("/F") or "")
                kept: Any = o["/EF"]
                files += [(name, s.get_object().get_data()) for s in kept.values()]
            elif isinstance(o, StreamObject) and o.get("/Subtype") == "/XML":  # its description of itself
                texts.append(html.unescape(re.sub(r"<[^>]+>", "\n", o.get_data().decode("utf-8", "replace"))))
    return texts, files


def _pdf_earlier(r: Any, data: bytes, seen: set[int]) -> bool:
    """Whether the bytes hold an object no reader shows: one written twice (an edit appended to the file), or one
    nothing points at (a page's text replaced by a later revision; 1523 review H6, H7: of any kind, and only the
    linearized file's own dictionary and its hint stream are let be)."""
    from pypdf.generic import DictionaryObject, StreamObject

    defined = re.findall(rb"(?<![0-9])(\d+)\s+\d+\s+obj\b", data)
    if len(defined) != len(set(defined)):
        return True
    at = {o: n for table in r.xref.values() for n, o in table.items()}
    free: set[int] = set()
    first = re.match(rb"%PDF-\d\.\d" + _PDF_GAP.pattern + rb"(\d+)\s+\d+\s+obj\b", data)
    if first and isinstance(lin := r.get_object(int(first[1])), DictionaryObject) and "/Linearized" in lin:
        hint: Any = lin["/H"]  # where the hint stream stands
        free = {int(first[1]), at.get(int(hint[0]), -1)}
    for n in {n for table in r.xref.values() for n in table} | set(r.xref_objStm) - seen:
        if n in seen or n in free:
            continue
        o = r.get_object(n)
        if not (isinstance(o, StreamObject) and o.get("/Type") in ("/ObjStm", "/XRef")):
            return True
    return False


def _pdf_bytes(r: Any, data: bytes) -> list[str]:
    """The comments in a PDF's bytes, to be read as its text is (1523 review M1). Every other byte is its header, an
    object at the place its cross-reference table names, the table and its trailer, or the pointer to the table: a
    byte after the end, or an object the table does not name, is shown by no reader and refuses the file."""
    at: dict[int, int | None] = {o: n for table in r.xref.values() for n, o in table.items()}
    if (start := re.findall(rb"startxref\s+(\d+)", data)) and data[int(start[-1]) : int(start[-1]) + 4] != b"xref":
        at.setdefault(int(start[-1]), None)  # a table that is a stream object of its own
    notes: list[str] = []
    head = re.match(rb"%PDF-\d\.\d", data)
    if head is None:
        raise Refused("", "unreadable")
    pos = _pdf_gap(data, head.end(), notes)
    while pos < len(data):
        if pos in at:
            pos = _pdf_object(r, data, pos, at[pos], notes)
        elif m := _PDF_XREF.match(data, pos):  # the table, and its trailer's dictionary read as an object's is
            pos = _pdf_gap(data, _pdf_value(data, m.end(), notes), notes)
            if (m := _PDF_START.match(data, pos)) is None:
                raise Refused("", "unreadable")
            pos = m.end()
        elif m := _PDF_START.match(data, pos):
            pos = m.end()
        else:
            raise Refused("", "unreadable")
        pos = _pdf_gap(data, pos, notes)
    return notes


def _pdf_object(r: Any, data: bytes, pos: int, n: int | None, notes: list[str]) -> int:
    """Where the object at ``pos`` ends: its number, one value, its stream of the length it says, ``endobj``."""
    m = re.compile(rb"(\d+)\s+\d+\s+obj\b").match(data, pos)
    if m is None or (n is not None and int(m[1]) != n):
        raise Refused("", "unreadable")
    pos = _pdf_gap(data, _pdf_value(data, m.end(), notes), notes)
    if data.startswith(b"stream", pos):
        body = re.compile(rb"stream\r?\n").match(data, pos)
        if body is None:
            raise Refused("", "unreadable")
        size = re.search(rb"/Length\s+(\d+)(?:\s+\d+\s+R\b)?", data[m.end() : body.start()])
        if size is None:
            raise Refused("", "unreadable")
        pos = body.end() + int(r.get_object(int(size[1])) if size[0].endswith(b"R") else size[1])
        if (end := re.compile(rb"\s*endstream").match(data, pos)) is None:
            raise Refused("", "unreadable")
        pos = _pdf_gap(data, end.end(), notes)
    if not data.startswith(b"endobj", pos):
        raise Refused("", "unreadable")
    return pos + 6


def _pdf_gap(data: bytes, pos: int, notes: list[str]) -> int:
    """Past the white space and the comments at ``pos``; the comments to ``notes``."""
    m = _PDF_GAP.match(data, pos)
    assert m is not None  # it matches nothing at worst
    notes += [c.decode("utf-8", "replace") for c in re.findall(rb"%([^\r\n]*)", m[0])]
    return m.end()


_PDF_WORD = re.compile(rb"/?[^\x00\t\n\x0c\r ()<>\[\]{}/%]+|/")


def _pdf_value(data: bytes, pos: int, notes: list[str]) -> int:
    """Where the one value at ``pos`` ends (a dictionary, an array, a string, a name, a number or a word); the
    comments inside it to ``notes``."""
    pos = _pdf_gap(data, pos, notes)
    if data.startswith(b"<<", pos):
        pos += 2
        while not data.startswith(b">>", pos := _pdf_gap(data, pos, notes)):
            pos = _pdf_value(data, pos, notes)
        return pos + 2
    if data.startswith(b"[", pos):
        pos += 1
        while not data.startswith(b"]", pos := _pdf_gap(data, pos, notes)):
            pos = _pdf_value(data, pos, notes)
        return pos + 1
    if data.startswith(b"(", pos):
        depth, pos = 1, pos + 1
        while depth:
            if pos >= len(data):
                raise Refused("", "unreadable")
            c, pos = data[pos], pos + 1
            if c == 0x5C:  # an escaped byte
                pos += 1
            depth += (c == 0x28) - (c == 0x29)
        return pos
    if data.startswith(b"<", pos):
        if (m := re.compile(rb"<[0-9A-Fa-f\x00\t\n\x0c\r ]*>").match(data, pos)) is None:
            raise Refused("", "unreadable")
        return m.end()
    if (m := _PDF_WORD.match(data, pos)) is None:
        raise Refused("", "unreadable")
    return m.end()


def _pdf_drawn(content: bytes) -> list[str]:
    """The comments in what a page draws (its operators and their values; a picture in it is skipped)."""
    notes: list[str] = []
    pos = _pdf_gap(content, 0, notes)
    while pos < len(content):
        if (m := re.compile(rb"ID[\x00\t\n\x0c\r ]").match(content, pos)) is not None:
            if (
                end := re.compile(rb"[\x00\t\n\x0c\r ]EI(?![^\x00\t\n\x0c\r ()<>\[\]{}/%])").search(content, m.end())
            ) is None:
                raise Refused("", "unreadable")
            pos = end.end()
        else:
            pos = _pdf_value(content, pos, notes)
        pos = _pdf_gap(content, pos, notes)
    return notes


#: what a rebuild cannot keep, so refuses (review round 3, M5): a picture, a drawing, deleted or hidden text, and the
#: parts a plain PDF of the body's text would drop (headers, footers, notes, comments)
_LOSSY_MARKS = (b"<w:drawing", b"<w:pict", b"<w:del ", b"<w:del>", b"<w:vanish", b"<p:pic", b"<v:imagedata")
_LOSSY_PARTS = re.compile(
    r"word/(?:header|footer)\d*\.xml|word/(?:footnotes|endnotes|comments\w*)\.xml|ppt/(?:notesSlides|comments)/.*"
)
#: a table's cells read as running text lose their columns: a rebuild refuses tables and workbooks (H2, cut)
_TABLE_MARKS = (b"<w:tbl", b"<a:tbl")


def _text_of(data: bytes) -> str:
    """The text a PDF or a Word or PowerPoint file shows (its pages, its paragraphs), for a rebuild. ``Refused``
    (``rebuild_table``) for a workbook or a table, (``rebuild_lossy``) for what :data:`_LOSSY_MARKS` and
    :data:`_LOSSY_PARTS` name, (``unreadable``) when there is no text to read."""
    from pypdf import PdfReader
    from pypdf.generic import StreamObject

    why, text = "", ""
    try:
        if b"%PDF-" in data[:1024]:
            r = PdfReader(io.BytesIO(data))
            numbers = {n for table in r.xref.values() for n in table} | set(r.xref_objStm)
            for n in numbers:
                o = r.get_object(n)
                if isinstance(o, StreamObject) and o.get("/Subtype") == "/Image":  # a scanned page, a picture
                    why = "rebuild_lossy"
            text = "\n\n".join(p.extract_text() or "" for p in r.pages)
        else:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = z.namelist()
            main = sorted((n for n in names if re.fullmatch(r"word/document\.xml|ppt/slides/slide\d+\.xml", n)),
                          key=lambda n: (len(n), n))  # fmt: skip
            parts = {n: z.read(n) for n in main}
            if "xl/workbook.xml" in names or any(m in b for b in parts.values() for m in _TABLE_MARKS):
                why = "rebuild_table"
            elif any(_LOSSY_PARTS.fullmatch(n) for n in names) or any(
                m in b for b in parts.values() for m in _LOSSY_MARKS
            ):
                why = "rebuild_lossy"
            text = "\n\n".join(
                html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</(?:\w+:)?(?:p|tr)>|<(?:\w+:)?(?:br|tab)\b[^>]*>",
                                                              "\n", b.decode("utf-8"))))
                for b in parts.values()
            )  # fmt: skip
    except Exception:
        raise Refused("", "unreadable") from None
    if why:
        raise Refused("", why)
    if not text.strip():
        raise Refused("", "unreadable")
    return text


def _plain_pdf(text: str) -> bytes:
    """``text`` set line by line in a fresh PDF of the box's own: nothing of the file it came from but its text."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    font = "HeiseiKakuGo-W5" if re.search(r"[\u3040-\u30ff]", text) else "MSung-Light"  # Japanese kana, else Chinese
    pdfmetrics.registerFont(UnicodeCIDFont(font))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=True, pageCompression=0)
    c.setTitle("")
    c.setAuthor("")
    c.setSubject("")
    c.setCreator("")
    height = A4[1]
    y = height - 50
    for line in text.splitlines() or [""]:
        for k in range(0, max(len(line), 1), 90):  # a long line wraps by characters
            if y < 50:
                c.showPage()
                y = height - 50
            c.setFont(font, 10)
            c.drawString(40, y, line[k : k + 90])
            y -= 14
    c.save()
    return buf.getvalue()


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


def chart_numbers(data: bytes) -> int | None:
    """How many different chart numbers a workbook's cells hold; None when it cannot be read."""
    from openpyxl import load_workbook

    rx = re.compile((site().mrn or r"^$").strip("^$"))
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True)
        cells = (str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v is not None)
        return len({c for c in cells if rx.fullmatch(c)})
    except Exception:
        return None


def _bytes_of(p: Any) -> bytes:
    if isinstance(p, File):
        return p.data
    if isinstance(p, Message):
        return "\n".join([p.subject, p.body]).encode() + b"".join(d for _n, d in p.files)
    if isinstance(p, bytes):
        return p
    return p.encode() if isinstance(p, str) else json.dumps(p, ensure_ascii=False, sort_keys=True, default=str).encode()


def _size(body: bytes) -> int:
    """The payload's bytes, unpacked for a workbook or a zip (how well a time in it packs is no size of it)."""
    if body[:4] == b"PK\x03\x04":
        try:
            return sum(i.file_size for i in zipfile.ZipFile(io.BytesIO(body)).infolist())
        except zipfile.BadZipFile:
            pass
    return len(body)


def _clean(r: _Reader, p: Any) -> Any:
    if isinstance(p, File):
        name, data = r.own(p.name, p.data)
        return File(r.name(name), r.file(name, data))
    if isinstance(p, Message):
        files = [r.own(n, d) for n, d in p.files]
        return Message(r.text(p.subject), r.text(p.body), tuple((r.name(n), r.file(n, d)) for n, d in files))
    if isinstance(p, bytes):
        return r.file(*r.own("", p))
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
    where: Site | None = None,
    made: Iterable[str] = (),
    rebuild: bool = False,
    queued: bool = False,
) -> Any:
    """The payload as it may leave by ``route`` to ``destination``, or :class:`Refused`. ``payload``: a text, a
    mapping or list, a :class:`File` or a :class:`Message`. ``audit``: the service's audit log; a record that cannot be
    written refuses. ``named``: an exception route's named destinations. ``items``: how many patients it is about, when
    the caller knows. ``unchecked``: the tripwire's development switch, for a model off the box only. ``refused``: an
    exception's own check (on an ``only_named`` route, the caller's address guard) already said no, and why;
    ``note``: what it did not know.
    ``where``: the site, when the caller holds its settings (else :func:`site`). ``made``: the sha256 of files the
    caller's own output record says the box built (a job's outputs); ``rebuild``: a PDF, Office, zip or picture file
    the box did not build leaves as a plain PDF of its text instead of being refused (1523 ruling). ``queued``: the
    payload goes to an outbox that delivers it later (the mail gateway's): the record says ``queued``, never ``sent``,
    and the delivery is the outbox's own event (``mail.sent``, ``mail.deferred``, ``mail.failed``)."""
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
        elif rule.only_named and (refused or not destination or destination not in set(named)):
            why = refused or "not_named"
        elif unchecked and route == "model.offbox":
            result = "unchecked"
        else:
            reader = _Reader(rule, where or site(), made, rebuild)
            out = _clean(reader, payload)
            if rule.mode == "refuse" and reader.hits:
                why = "identifiers"
            result = "masked" if reader.hits else "sent"
    except Refused as exc:
        why = exc.reason
    except Exception:  # the masker failed: nothing is sent (the error's text may quote the payload)
        why = "mask_failed"
    body = _bytes_of(payload if why else out)
    if queued and not why:  # P-11: an outbox may never deliver it; "sent" is said by the delivery, not here
        result = {"sent": "queued", "masked": "queued_masked", "exception": "queued_exception"}.get(result, result)
    try:
        egress_record.write(
            audit,
            actor=actor,
            route=route,
            destination=destination,
            kind=type(payload).__name__,
            items=items if items is not None or reader is None else reader.hits,
            rule=rule.mode if rule else "none",
            size=_size(body),
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
    req: Any,
    store: Any,
    *,
    audit: Any,
    internal: Callable[[str], bool],
    rights: Rights | None = None,
    site: Site | None = None,
    recorded: Mapping[str, str] | None = None,
) -> tuple[Any, Any]:
    """A send request and its store as they may leave. A patient file goes as it is, to the site's own domains only
    (D-369 names its recipients), by :func:`may_have`; any other mail is read whole, attachments too. An attachment
    that is a PDF, Office, zip or picture file leaves only when the bytes fetched from the store hash to what the job
    recorded when it built that object (``recorded``: object key -> sha256, the orchestrator's own record; 1523
    ruling, review round 3 M1): any sha256 the request carries is ignored, and one with no record is refused
    (``not_made``)."""
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
        where=site,
        made=[str(recorded[a.minio_key]) for a in atts if recorded and a.minio_key in recorded],  # the job's record
        queued=True,  # the outbox delivers it, or not: its mail.* events say which
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


@functools.lru_cache(maxsize=64)
def _code(text: str) -> str:
    """Python source without its comments and docstrings; nothing when it does not parse."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    for n in ast.walk(tree):
        if isinstance(body := getattr(n, "body", None), list):
            kept = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            n.body = kept or [ast.Pass()]  # type: ignore[attr-defined]
    return ast.unparse(tree)


def wired(route: str, root: Path = ROOT) -> bool | None:
    """Whether the route's door calls the edge in this tree (OCR 1523-14: in its code, never in a comment); None when
    the file is not here to read."""
    file, call = ROUTES[route].door
    try:
        texts = [p.read_text(encoding="utf-8") for p in root.glob(file)]
    except OSError:
        return None
    return any(call.replace('"', "'") in _code(t) for t in texts) if texts else None


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
