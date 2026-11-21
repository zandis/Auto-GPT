"""One study's jRCT record from a file the person downloaded themself (plan 10 card 10D-16, file half "10D-16a",
D-1373; Decision 52: one record at a time, started by a person; D-317: TrialBox never fetches jRCT data).

:func:`read_record` turns the bytes of an uploaded file into a :class:`Record`, or raises :class:`Refused` with the
first rule the file breaks. It opens no file, no socket and no other process: it reads the bytes it is given and
returns values. The file is hostile input:

* **size first:** more than :data:`MAX_BYTES` is refused before anything else is looked at (the console stops reading
  the request there, ``console.registry_record_page``);
* **type by content, never by name:** a ZIP or XLSX, a PDF, an old Office file, a gzip, UTF-16 text, a NUL byte,
  markup (a file whose first character is ``<``: XML, HTML, an SVG, a DTD with entities) and JSON (``{`` or ``[``)
  are refused; the text must decode as UTF-8 (a BOM is allowed) or Shift_JIS (CP932) and hold no control character
  but tab and line ends. No XML or JSON parser is ever run on it, so an entity or a nesting depth never expands;
* **a strict CSV:** Python's ``csv`` reader with ``strict=True`` (a stray quote is an error), at most
  :data:`MAX_COLUMNS` columns and :data:`CELL_MAX` characters in any cell, the header in the first row (two header
  cells that are the same column name for a kept field are refused: which one is meant is not known), a data row with
  more cells than the header refused, and **exactly one record**: a second data row is refused (Decision 52); a
  kept field's column present under more than one of its names (``Title`` and ``Public Title``, ``jRCT番号`` and
  ``Trial ID``) is refused, as which one is meant is not known;
* **kept fields:** no format character (direction marks and overrides, zero-width characters), private-use or control
  character, and no value starting with ``=``, ``+``, ``-`` or ``@`` (refused, not rewritten: a later export can never
  turn it into a formula; a dash alone is kept);
* **the record's number** must be one jRCT number standing alone in its cell, as ``tb_common.ctgov_record.registry_of``
  recognises it (``jRCT`` + 10 digits, or ``jRCTs`` + 9 digits).

**Kept:** the jRCT number, the title, the health conditions, the recruitment status, the phase and the date of the
last update (:data:`KEPT`), each within its length (:data:`FIELD_MAX`). **Never kept:** every other column, whatever
it holds: the responsible and contact persons' names, e-mail addresses and telephone numbers, the review board, the
eligibility text and the summaries. jRCT's terms put names and contacts outside the open-data licence (review 14 §5.2,
S4); the card asks that none is stored. The columns are matched by alias, as the hospital's jRCT download loader
(``tb_common.refdata_jp.JRCT_COLS``, D-317) matches them; that they are the columns of jRCT's real download is not
verified (review 14, "not examined").
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import asdict, dataclass

from tb_common.ctgov_record import registry_of
from tb_common.refdata_jp import JRCT_COLS, _key

#: the largest file read (bytes); a larger one is refused before it is looked at
MAX_BYTES = 256 * 1024
#: the most columns a row may have
MAX_COLUMNS = 300
#: the longest cell of any column, kept or not (characters)
CELL_MAX = 32_000
#: the kept fields, in the order the page shows them, and the longest each may be (characters)
FIELD_MAX: dict[str, int] = {
    "id": 20,
    "title": 1000,
    "condition": 1000,
    "status": 200,
    "phase": 200,
    "updated": 40,
}
KEPT: tuple[str, ...] = tuple(FIELD_MAX)
#: what an upload's name may say about its type is never read; these first bytes say the file is not CSV text
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "archive"),  # ZIP, XLSX, DOCX, ODS
    (b"PK\x05\x06", "archive"),
    (b"%PDF", "binary"),
    (b"\xd0\xcf\x11\xe0", "binary"),  # an old Office file (XLS)
    (b"\x1f\x8b", "binary"),  # gzip
    (b"\xff\xfe", "binary"),  # UTF-16 text
    (b"\xfe\xff", "binary"),
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
#: the codes of :class:`Refused`, each with its message key ``rrec.err.<code>`` in the console's catalogue
CODES: tuple[str, ...] = (
    "empty", "too_large", "archive", "binary", "markup", "json", "not_text", "bad_csv", "too_wide", "cell_long",
    "no_header", "header_twice", "row_wide", "no_record", "many_records", "bad_id", "field_long", "invisible",
    "formula",
)  # fmt: skip
#: the first characters a spreadsheet reads as a formula: a kept field starting with one is refused (a later export
#: can then never turn it into one); a field that is a dash alone ("none") is kept
FORMULA_START = ("=", "+", "-", "@")
#: Unicode categories refused in a kept field: format characters (direction marks and overrides, zero-width
#: characters), private use, and control characters (refused in the whole file already)
INVISIBLE = ("Cf", "Co", "Cc")


class Refused(ValueError):
    """The file breaks a rule: ``code`` (one of :data:`CODES`) and, for ``field_long``, the field."""

    def __init__(self, code: str, field: str = "") -> None:
        assert code in CODES, code
        super().__init__(code if not field else f"{code}: {field}")
        self.code = code
        self.field = field


@dataclass(frozen=True)
class Record:
    """The kept fields of one jRCT record, as text (an empty string where the file has no such column)."""

    id: str
    title: str
    condition: str
    status: str
    phase: str
    updated: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(data: bytes) -> str:
    if not data:
        raise Refused("empty")
    if len(data) > MAX_BYTES:
        raise Refused("too_large")
    for magic, code in _MAGIC:
        if data.startswith(magic):
            raise Refused(code)
    if b"\x00" in data:
        raise Refused("binary")
    text = None
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise Refused("not_text")
    head = text.lstrip(" \t\r\n﻿")[:1]
    if head == "<":
        raise Refused("markup")
    if head in ("{", "["):
        raise Refused("json")
    if _CONTROL.search(text):
        raise Refused("not_text")
    return text


def _rows(text: str) -> list[list[str]]:
    """The header and the data rows (blank rows left out), refusing a second record as soon as it is read."""
    out: list[list[str]] = []
    try:
        for row in csv.reader(io.StringIO(text, newline=""), strict=True):
            if len(row) > MAX_COLUMNS:
                raise Refused("too_wide")
            if any(len(c) > CELL_MAX for c in row):
                raise Refused("cell_long")
            if not any(c.strip() for c in row):
                continue
            out.append(row)
            if len(out) > 2:
                raise Refused("many_records")
    except csv.Error as exc:
        if "field larger than field limit" in str(exc):  # Python csv's own cell limit, above CELL_MAX
            raise Refused("cell_long") from exc
        raise Refused("bad_csv") from exc
    return out


def _columns(header: list[str]) -> dict[str, int]:
    keys = [_key(c) for c in header]
    idx: dict[str, int] = {}
    for name in ("id", *KEPT[1:]):
        names = {_key(a) for a in JRCT_COLS[name]}
        at = [i for i, k in enumerate(keys) if k in names]
        if len(at) > 1:  # two columns for one kept field (one name twice, or two of its names): which is meant?
            raise Refused("header_twice")
        if at:
            idx[name] = at[0]
    if "id" not in idx or "title" not in idx:
        raise Refused("no_header")
    return idx


def _one_line(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).split())


def read_record(data: bytes) -> Record:
    """The kept fields of the one jRCT record in ``data``, or :class:`Refused` at the first rule it breaks."""
    rows = _rows(_text(data))
    if not rows:
        raise Refused("no_header")
    header, body = rows[0], rows[1:]
    idx = _columns(header)
    if not body:
        raise Refused("no_record")
    row = body[0]
    if len(row) > len(header) and any(c.strip() for c in row[len(header) :]):
        raise Refused("row_wide")
    got = {k: (_one_line(row[i]) if i < len(row) else "") for k, i in idx.items()}
    found = registry_of(got["id"])
    if found is None or found[0] != "jRCT" or got["id"].replace(" ", "").replace("-", "").lower() != found[1].lower():
        raise Refused("bad_id")
    got["id"] = found[1]
    at = idx.get("condition", len(row))
    conditions = [c.strip() for c in re.split(r"[、;；\n]", row[at] if at < len(row) else "")]
    got["condition"] = "; ".join(_one_line(c) for c in conditions if c.strip())
    for k in KEPT:
        v = got.get(k, "")
        if any(unicodedata.category(ch) in INVISIBLE for ch in v):
            raise Refused("invisible", k)
        if v.startswith(FORMULA_START) and v not in ("-",):
            raise Refused("formula", k)
        if len(v) > FIELD_MAX[k]:
            raise Refused("field_long", k)
    return Record(**{k: got.get(k, "") for k in KEPT})
