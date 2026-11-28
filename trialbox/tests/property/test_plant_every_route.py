"""M3, acceptance 1: every named identifier form, planted in every container, at every route of the egress edge.

The forms are named ones (a label, a check digit, a number's shape). A person's name standing free in running text is
not one of them and no test here claims it (ruling c). All values are invented.
"""

from __future__ import annotations

import csv
import html
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tb_common import egress_edge as ee

pytestmark = pytest.mark.nodb

#: form -> (label, value, the line of a note that holds it)
FORMS: dict[str, tuple[str, str, str]] = {
    "name_en": ("Patient name", "Robin Example", "Patient name: Robin Example."),
    "name_en_pt": ("Pt", "Robin Example", "Pt: Robin Example. Gout."),
    "name_ja": ("患者氏名", "山田太郎", "患者氏名:山田太郎"),
    "name_zh": ("病患姓名", "王小明", "病患姓名:王小明"),
    "chart_label": ("MRN", "70000054", "MRN: 70000054"),
    "chart_bare": ("x", "70000054", "seen as 70000054 today"),
    "dob_en": ("DOB", "1961-04-03", "DOB: 1961-04-03"),
    "dob_ja": ("生年月日", "昭和36年4月3日", "生年月日:昭和36年4月3日"),
    "dob_zh": ("生日", "民國50年4月3日", "生日:民國50年4月3日"),
    "phone_tw": ("手機", "0912-345-678", "手機 0912-345-678"),
    "phone_ja": ("電話", "090-1234-5678", "電話 090-1234-5678"),
    "id_tw": ("身分證", "A123456789", "身分證 A123456789"),
}
BOUND = sorted(k for k, r in ee.ROUTES.items() if r.mode != "exception")
OPEN = sorted(k for k, r in ee.ROUTES.items() if r.mode == "exception")


class Audit:
    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def append(self, event: str, **fields: Any) -> None:
        self.lines.append({"event": event, **fields})


@pytest.fixture(autouse=True)
def the_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ee, "site", lambda: ee.Site(r"^\d{8}$", ("hosp.example",)))


@pytest.fixture(autouse=True)
def the_box_made_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """1523 ruling (round 3): these tests read the second layer, the reading of a file the box made, so every file in
    them is taken as the box's own; ``tests/unit/test_egress_made.py`` tests the record and the refusal of any other."""
    monkeypatch.setattr(ee, "_box_made", lambda _digest, _vouched: True)


def _xlsx(label: str, value: str, line: str) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws: Any = wb.active
    ws.append(["count", label])
    ws.append([3, value])
    wb.create_sheet("b").append([label, value])
    wb.create_sheet("c").append([line])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv(label: str, value: str, line: str) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows([["n", label, "detail"], ["1", value, line]])
    return buf.getvalue().encode()


def _zip(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, data)
    return buf.getvalue()


def _docx(label: str, value: str, line: str) -> bytes:
    from docx import Document

    d = Document()
    d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _members(*members: tuple[str, bytes], comment: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members:
            z.writestr(name, data)
        z.comment = comment.encode()
    return buf.getvalue()


def _pdf(attached: bytes = b"", field: str = "") -> bytes:
    """A page of clean text, with a file attached or a form's field filled in."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 700, "12 of 85 patients")
    c.save()
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    if attached:
        w.add_attachment("list.csv", attached)
    if field:
        f = DictionaryObject({NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject("a"),
                              NameObject("/V"): TextStringObject(field)})  # fmt: skip
        form = DictionaryObject({NameObject("/Fields"): ArrayObject([w._add_object(f)])})
        w._root_object[NameObject("/AcroForm")] = w._add_object(form)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


_TYPES = ("[Content_Types].xml", b"<Types/>")
CONTAINERS: dict[str, Callable[[str, str, str], Any]] = {
    "text": lambda _l, _v, line: line,
    "txt": lambda _l, _v, line: ee.File("a.txt", line.encode()),
    "json": lambda lb, v, line: ee.File("a.json", json.dumps({lb: v, "rows": [line]}, ensure_ascii=False).encode()),
    "jsonl": lambda lb, v, line: ee.File("a.jsonl", json.dumps({lb: v, "d": line}, ensure_ascii=False).encode()),
    "csv": lambda lb, v, line: ee.File("a.csv", _csv(lb, v, line)),
    "html": lambda _l, _v, line: ee.File("a.html", f"<p>{line}</p>".encode()),
    "xlsx": lambda lb, v, line: ee.File("a.xlsx", _xlsx(lb, v, line)),
    "docx": lambda lb, v, line: ee.File("a.docx", _docx(lb, v, line)),
    "zip": lambda lb, v, line: ee.File("a.zip", _zip("in.csv", _csv(lb, v, line))),
    "zip_xlsx": lambda lb, v, line: ee.File("a.zip", _zip("in.xlsx", _xlsx(lb, v, line))),
    # OCR 1523-3: what a container holds beside its text
    "zip_content_types": lambda _l, _v, line: ee.File("a.zip", _members(_TYPES, ("notes.txt", line.encode()))),
    "docx_embedded": lambda lb, v, line: ee.File(
        "a.docx", _members(_TYPES, ("word/document.xml", b"<p>hi</p>"), ("word/embedded/a.csv", _csv(lb, v, line)))
    ),
    "zip_comment": lambda _l, _v, line: ee.File("a.zip", _members(("a.txt", b"hello"), comment=line)),
    "pdf_attached": lambda lb, v, line: ee.File("a.pdf", _pdf(attached=_csv(lb, v, line))),
    "pdf_field": lambda _l, _v, line: ee.File("a.pdf", _pdf(field=line)),
    "mail": lambda lb, v, line: ee.Message(line, line, (("a.csv", _csv(lb, v, line)),)),
    "record": lambda lb, v, line: {"rows": [{lb: v, "detail": line}]},
}


def _all_text(p: Any) -> str:
    """Everything a reader of the payload could read, archives opened."""
    if isinstance(p, ee.File):
        return p.name + "\n" + _all_text(p.data)
    if isinstance(p, ee.Message):
        return "\n".join([p.subject, p.body, *(n + "\n" + _all_text(d) for n, d in p.files)])
    if isinstance(p, bytes):
        if p[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(p)) as z:
                parts = [i.filename + "\n" + _all_text(z.read(i)) for i in z.infolist()]
                return "\n".join([*parts, z.comment.decode()])
        if p[:5] == b"%PDF-":
            from pypdf import PdfReader

            r = PdfReader(io.BytesIO(p))
            fields = [str(f.get("/V")) for f in (r.get_fields() or {}).values()]
            return "\n".join([*fields, *(_all_text(d) for files in r.attachments.values() for d in files)])
        return html.unescape(p.decode("utf-8", errors="replace"))  # a workbook writes a character as its number
    return p if isinstance(p, str) else json.dumps(p, ensure_ascii=False)


@pytest.mark.parametrize("route", BOUND)
@pytest.mark.parametrize("container", sorted(CONTAINERS))
@pytest.mark.parametrize("form", sorted(FORMS))
def test_no_named_form_is_readable(route: str, container: str, form: str) -> None:
    label, value, line = FORMS[form]
    payload = CONTAINERS[container](label, value, line)
    assert value in _all_text(payload)
    audit = Audit()
    try:
        out = ee.leave(route, "somewhere", payload, audit=audit, actor="t", named=["somewhere"])
    except ee.Refused as exc:
        assert exc.reason in ("identifiers", "free_text"), exc.reason
        out = ""
    else:
        assert ee.ROUTES[route].mode == "mask"
    assert value not in _all_text(out)
    assert len(audit.lines) == 1 and value not in json.dumps(audit.lines, ensure_ascii=False)


@pytest.mark.parametrize("route", OPEN)
@pytest.mark.parametrize("form", sorted(FORMS))
def test_an_exception_passes_to_its_named_destination_only(route: str, form: str) -> None:
    label, value, line = FORMS[form]
    payload = ee.File("a.csv", _csv(label, value, line))
    audit = Audit()
    assert ee.leave(route, "here", payload, audit=audit, actor="t", named=["here"]) == payload
    bad: list[dict[str, Any]] = [{"named": ["there"]}, {"named": []}, {"named": ["here"], "actor": ""}]
    for kw in bad:
        with pytest.raises(ee.Refused):
            ee.leave(route, "here", payload, **{"audit": audit, "actor": "t", **kw})
    assert [x["detail"]["result"] for x in audit.lines] == ["exception", "refused", "refused", "refused"]
    assert value not in json.dumps(audit.lines, ensure_ascii=False)


def test_a_clean_payload_leaves_as_it_is() -> None:
    """The edge changes nothing where there is nothing to mask, so two identical nights send the same bytes."""
    clean = {"Arm": "A", "count": 12, "made": "2026-11-25T08:00:00+09:00", "pid": "0f3a0912345678ab", "n": "<5"}
    for route in sorted(k for k in BOUND if k != "download.audit"):
        for p in (ee.File("a.json", json.dumps(clean).encode()), ee.File("a.csv", _csv("Arm", "A", "no one"))):
            assert ee.leave(route, "x", p, audit=Audit(), actor="t", named=["x"]) == p


def test_the_same_payload_leaves_as_the_same_bytes() -> None:
    p = ee.File("a.xlsx", _xlsx("Patient name", "Robin Example", "Pt: Robin Example"))
    a, b = (ee.leave("download.study", "x", p, audit=Audit(), actor="t") for _ in range(2))
    assert a == b


@pytest.mark.parametrize("ask", [{}, {"Range": "bytes=0-"}, {"Range": "bytes=3-"}, {"Range": "bytes=0-1,2-"}])
@pytest.mark.parametrize("form", sorted(FORMS))
def test_no_range_request_takes_a_form_past_the_console_s_layer(form: str, ask: dict[str, str], tmp_path: Path) -> None:
    """OCR 1523-5: a file answer to a request for a part of it."""
    from console.egress_page import EgressLayer
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, Response
    from starlette.testclient import TestClient

    _label, value, line = FORMS[form]
    sheet = tmp_path / "a.md"
    sheet.write_text("x\n" + line, encoding="utf-8")

    class Door:
        def leave(self, _request: Any, _path: str, name: str, data: bytes) -> ee.File:
            got: ee.File = ee.leave("download.site", "x", ee.File(name, data), audit=Audit(), actor="t")
            return got

        def refusal(self, *_a: Any) -> Response:
            return Response(status_code=409)

    app = FastAPI()
    app.get("/admin/ops/network/{name}")(lambda name: FileResponse(sheet, filename=name))
    door: Any = Door()
    app.add_middleware(EgressLayer, door=door)
    r = TestClient(app).get("/admin/ops/network/a.md", headers=ask)
    assert r.status_code in (200, 409) and value not in r.content.decode("utf-8", errors="replace")
