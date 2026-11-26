"""1523 ruling (round 3): a PDF, Office, zip or picture file leaves the box only when the box built it (its hash in the
box's own output record) or rebuilt into a plain PDF of its text; any other is refused, and the refusal says which of
the two ways to take. The record is in memory and bounded; ``made()`` is called only where the code built the bytes."""

from __future__ import annotations

import ast
import hashlib
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common import egress_edge as ee

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.nodb


class Audit:
    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def append(self, event: str, **fields: Any) -> None:
        self.lines.append({"event": event, **fields})


@pytest.fixture(autouse=True)
def the_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ee, "site", lambda: ee.Site(r"^\d{8}$", ("hosp.example",)))
    monkeypatch.setattr(ee, "_MADE", {})  # each test starts as a box just started: it remembers nothing


def _leave(f: ee.File, **kw: Any) -> Any:
    return ee.leave("download.study", "x", f, audit=Audit(), actor="t", **kw)


def _reason(f: ee.File, **kw: Any) -> str:
    with pytest.raises(ee.Refused) as got:
        _leave(f, **kw)
    return got.value.reason


def _book() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws: Any = wb.active
    ws.append(["site", "n"])
    ws.append(["A", 12])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HIDDEN = b"HIDDEN-7731-PAYLOAD"


def _docx(text: str) -> bytes:
    """A document from outside: its text, and a part no reader shows that holds :data:`HIDDEN`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", b"<Types/>")
        z.writestr(
            "word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
        )
        z.writestr("docProps/custom.xml", b"<Properties><p>" + HIDDEN + b"</p></Properties>")
    return buf.getvalue()


def _pdf(text: str) -> bytes:
    """A PDF from outside: its page, and its description (no page shows it) holding :data:`HIDDEN`."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pageCompression=0)
    c.setKeywords(HIDDEN.decode())
    c.drawString(72, 700, text)
    c.save()
    return buf.getvalue()


def _png() -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + ihdr + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b"")


# ------------------------------------------------------------------------------------------------ rule 1 (a)
def test_a_file_the_box_built_leaves_as_it_is() -> None:
    f = ee.File("counts.xlsx", ee.made(_book()))
    assert _leave(f) == f


def test_a_file_the_jobs_record_names_leaves_as_it_is() -> None:
    data = _book()
    f = ee.File("counts.xlsx", data)
    assert _leave(f, made=[hashlib.sha256(data).hexdigest()]) == f
    assert _reason(f, made=["0" * 64]) == "not_made"  # a record of another file is no record of this one


def test_the_box_s_own_file_is_still_read() -> None:
    """Rule 3: the reading stays as the second layer: a file the box built with an identifier in it is not let by."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["note", "MRN 70000054 Robin Example"])  # type: ignore[union-attr]
    buf = io.BytesIO()
    wb.save(buf)
    got = _leave(ee.File("a.xlsx", ee.made(buf.getvalue())))
    assert b"70000054" not in got.data


# ------------------------------------------------------------------------------------------------ rule 2
@pytest.mark.parametrize(
    ("name", "data"),
    [("a.docx", _docx("12 of 85 patients")), ("a.pdf", _pdf("12 of 85 patients")), ("a.xlsx", _book()),
     ("a.zip", b"PK\x05\x06" + bytes(18)), ("a.png", _png())],
    ids=["docx", "pdf", "xlsx", "zip", "png"],
)  # fmt: skip
def test_a_file_from_outside_is_refused(name: str, data: bytes) -> None:
    assert _reason(ee.File(name, data)) == "not_made"


def test_the_refusal_names_the_two_ways_in_each_language() -> None:
    from console.i18n_egress import EN, JA, ZH

    for words in (EN, JA, ZH):
        said = words["egress.reason.not_made"]
        assert "?rebuild=1" in said and "PDF" in said


def test_a_list_that_begins_as_a_bitmap_is_a_list_not_a_picture() -> None:
    f = ee.File("a.csv", b"BMI,n\n22,3\n")
    assert _leave(f) == f


def test_a_restart_forgets_and_the_record_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition (b): in memory and bounded. A file the record forgot is refused, never let by."""
    data = ee.made(_book())
    ee._MADE.clear()  # a restart
    assert _reason(ee.File("a.xlsx", data)) == "not_made"
    monkeypatch.setattr(ee, "MADE_MAX", 2)
    first = ee.made(_docx("one"))
    ee.made(_docx("two"))
    ee.made(_docx("three"))
    assert len(ee._MADE) == 2
    assert _reason(ee.File("a.docx", first)) == "not_made"


# ------------------------------------------------------------------------------------------------ rule 1 (b)
@pytest.mark.parametrize("kind", ["docx", "pdf"])
def test_a_rebuilt_file_leaves_and_holds_no_byte_of_the_original_but_its_text(kind: str) -> None:
    from pypdf import PdfReader

    data = _docx("12 of 85 patients") if kind == "docx" else _pdf("12 of 85 patients")
    assert HIDDEN in data or HIDDEN.decode() in data.decode("latin-1")
    got = _leave(ee.File(f"report.{kind}", data), rebuild=True)
    assert got.name == "report.pdf" and got.data[:5] == b"%PDF-"
    assert HIDDEN not in got.data
    # its bytes are a function of the text alone: the box's own plain PDF of what the original showed
    assert got.data == ee._plain_pdf(ee._text_of(data))
    assert "12 of 85 patients" in "".join(p.extract_text() for p in PdfReader(io.BytesIO(got.data)).pages)


def test_a_rebuilt_file_is_masked_by_the_rules() -> None:
    from pypdf import PdfReader

    got = _leave(ee.File("a.docx", _docx("MRN 70000054 Robin Example")), rebuild=True)
    shown = "".join(p.extract_text() for p in PdfReader(io.BytesIO(got.data)).pages)
    assert "70000054" not in shown and "MRN" in shown


def test_a_file_with_no_text_cannot_be_rebuilt() -> None:
    assert _reason(ee.File("a.png", _png()), rebuild=True) == "unreadable"


# ------------------------------------------------------------------------------------------------ the mail
def _send(data: bytes, recorded: dict[str, str] | None = None) -> Any:
    """A mail of counts with one job file (object key ``k``); ``recorded``: the job's own record of its files."""
    from tb_contracts import SendRequest

    att = {"filename": "counts.xlsx", "minio_key": "k", "tag": "aggregate"}
    req = SendRequest.model_validate({"job_id": "01HZZZZZZZZZZZZZZZZZZZZZZZ", "to": ["crc@hosp.example"],
                                      "subject": "S", "body_md": "counts", "tag": "aggregate", "attachments": [att]})  # fmt: skip
    store = SimpleNamespace(get=lambda _k: data)
    return ee.gate_mail(req, store, audit=Audit(), internal=lambda _r: True, recorded=recorded)


def test_a_job_attachment_leaves_by_the_sha256_the_job_recorded() -> None:
    data = _book()
    _req, held = _send(data, recorded={"k": hashlib.sha256(data).hexdigest()})
    assert held.get("k") == data


def test_a_mail_attachment_without_its_record_is_refused() -> None:
    with pytest.raises(ee.Refused) as got:
        _send(_book())
    assert got.value.reason == "not_made"


# ------------------------------------------------------------------------------------------------ condition (a)
#: every place that records a file as the box's own, each one where the code built the bytes (or where the box's own
#: service built them for this signed call): a new one is reviewed here before it can let a file out
MADE_AT = {
    ("libs/tb_common/egress_edge.py", "own"),  # the rebuilt plain PDF
    ("services/console/app.py", "sponsor_pack"),
    ("services/console/screening_log.py", "screening_log_xlsx"),
    ("services/console/screening_log.py", "research_office_xlsx"),
    ("services/console/lifecycle_pages.py", "enrolment_file"),
    ("services/console/lifecycle_pages.py", "read_report_file"),
    ("services/console/entry_pages.py", "read_export"),
    ("services/console/site_pages.py", "template_file"),
}
UPLOAD = ("UploadFile", "request.form", ".form()", "request.body", "request.stream", "upload")


def _calls() -> set[tuple[str, str, str]]:
    """(file, innermost function, its source) of every call of ``made``."""
    out: set[tuple[str, str, str]] = set()

    def walk(node: ast.AST, fn: Any, path: str, src: str) -> None:
        for n in ast.iter_child_nodes(node):
            inner = n if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) else fn
            if isinstance(n, ast.Call) and fn is not None and fn.name != "made":
                f = n.func
                name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                if name == "made":
                    out.add((path, fn.name, ast.get_source_segment(src, fn) or ""))
            walk(n, inner, path, src)

    for base in ("libs", "services", "tools"):
        for path in (ROOT / base).rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            if "made(" in src:
                walk(ast.parse(src), None, path.relative_to(ROOT).as_posix(), src)
    return out


def test_made_is_called_only_where_the_code_built_the_bytes() -> None:
    calls = _calls()
    assert {(p, f) for p, f, _s in calls} == MADE_AT
    for path, fn, src in calls:  # none of them reads an upload: a person's file never enters the record
        assert not any(u in src for u in UPLOAD), (path, fn)


# ------------------------------------------------------------------------------------------------ review round 3
@pytest.mark.parametrize(
    ("data", "container"),
    [(b" %PDF-1.4\n" + bytes(10), True), (b"\n\n%PDF-1.7 x", True), (b"hello <SVG xmlns='x'>", True),
     (b"{\\rtf1 x", True), (b"x" * 900 + b"PK\x03\x04", True), (b"\x00\x01binary", True),
     ("病歷".encode("big5"), True), (b"mrn,n\n1,2\n", False), ("﻿name,n\n王,3\n".encode(), False),
     (("é" * 600).encode()[:1024] + b"rest", False)],
)  # fmt: skip
def test_the_container_sniff_reads_the_first_1024_bytes_fail_closed(data: bytes, container: bool) -> None:
    """H1: a mark anywhere in the first 1024 bytes, a byte that is no UTF-8 text, or a control character."""
    assert ee._is_container(data) is container


def test_a_pdf_behind_a_leading_space_is_a_container_and_refused() -> None:
    """H1: viewers find ``%PDF-`` within the first 1024 bytes; the edge did only at byte 0."""
    data = b" " + _pdf("MRN 70000054 Robin Example")
    assert _reason(ee.File("a.txt", data)) == "not_made"


def _sheet(head: list[str], row: list[Any]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws: Any = wb.active
    ws.append(head)
    ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _word(body: str, more: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", b"<Types/>")
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
        for n, d in (more or {}).items():
            z.writestr(n, d)
    return buf.getvalue()


def _pdf_with_picture() -> bytes:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 700, "12 of 85 patients")
    c.drawImage(ImageReader(io.BytesIO(_png())), 72, 600, 10, 10)
    c.save()
    return buf.getvalue()


@pytest.mark.parametrize(
    "data",
    [_sheet(["Patient name", "n"], ["Robin Example", 3]),
     _word("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Robin Example</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"),
     _word("<w:p/>", {"ppt/slides/slide1.xml": b"<a:tbl/>"})],
    ids=["workbook_name_column", "word_table", "slide_table"],
)  # fmt: skip
def test_tables_and_workbooks_are_not_rebuilt(data: bytes) -> None:
    """H2 (cut): a table's cells read as running text lose their columns, so the column rules would not mask them."""
    assert _reason(ee.File("a.bin", data), rebuild=True) == "rebuild_table"


_P = "<w:p><w:r><w:t>12 of 85 patients</w:t></w:r></w:p>"


@pytest.mark.parametrize(
    ("data", "kind"),
    [(_pdf_with_picture(), "pdf_image"),
     (_word(_P + "<w:p><w:r><w:drawing/></w:r></w:p>"), "drawing"),
     (_word(_P + "<w:p><w:r><w:pict/></w:r></w:p>"), "pict"),
     (_word(_P + '<w:p><w:del w:id="1"><w:r><w:delText>MRN 70000054</w:delText></w:r></w:del></w:p>'), "deleted"),
     (_word(_P + "<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>MRN 70000054</w:t></w:r></w:p>"), "hidden"),
     (_word(_P, {"word/header1.xml": b"<w:hdr/>"}), "header"),
     (_word(_P, {"word/footer1.xml": b"<w:ftr/>"}), "footer"),
     (_word(_P, {"word/footnotes.xml": b"<w:footnotes/>"}), "footnotes"),
     (_word(_P, {"word/comments.xml": b"<w:comments/>"}), "comments")],
    ids=lambda v: v if isinstance(v, str) else "",
)  # fmt: skip
def test_what_a_rebuild_cannot_keep_is_refused_not_dropped(data: bytes, kind: str) -> None:
    """M5: a plain PDF of the body's text would drop it, or show what was hidden or deleted."""
    assert _reason(ee.File("a.bin", data), rebuild=True) == "rebuild_lossy", kind


def test_the_size_and_zip_caps_come_before_a_rebuild_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """M4: a rebuild never decompresses what the caps would refuse."""

    def never(_data: bytes) -> str:
        raise AssertionError("_text_of was called")

    monkeypatch.setattr(ee, "_text_of", never)
    monkeypatch.setattr(ee, "MAX_BYTES", 100)
    assert _reason(ee.File("a.docx", _docx("12 of 85 patients")), rebuild=True) == "too_large"
    monkeypatch.setattr(ee, "MAX_BYTES", 64 * 1024 * 1024)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", b"<Types/>")
        z.writestr("word/document.xml", b"0" * (5 * 1024 * 1024))
    assert _reason(ee.File("a.docx", bomb.getvalue()), rebuild=True) == "unreadable"


def test_a_mail_attachment_is_vouched_by_the_job_s_record_of_its_bytes_never_the_request() -> None:
    """M1: the gateway hashes the bytes it fetched against the job's own record (by object key)."""
    data = _book()
    with pytest.raises(ee.Refused) as got:
        _send(data, recorded={"k": hashlib.sha256(b"other bytes").hexdigest()})  # the record names other bytes
    assert got.value.reason == "not_made"
    _req, held = _send(data, recorded={"k": hashlib.sha256(data).hexdigest()})
    assert held.get("k") == data
