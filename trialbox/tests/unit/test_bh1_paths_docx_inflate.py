"""BH1-08 probe: a protocol DOCX is a zip, and the parser inflates its members with no cap.

Entry point a real user reaches: ``POST /pilot/protocol`` (also ``/pilot/consent`` and ``/pilot/case``) in the
console, and a mailed attachment through the mail gateway; both hand the stored file to the doc-parser service's
``POST /parse``, which calls :func:`doc_parser.parser.parse`. The upload is capped at 50 MB compressed; the rule-set
zip has caps on what it inflates (D-1102, ``tb_common.zipcap``: member, total and ratio), the protocol DOCX has none.

The probe stays small: a document whose ``word/document.xml`` inflates at far more than the ratio cap the box
already applies (``RULESET_ZIP_MAX_RATIO``), above the floor under which the ratio is not judged. The safe behaviour:
the parser refuses it as unreadable before reading it. Today it reads it, so the same missing cap lets a 50 MB upload
inflate to many GB in the doc-parser.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from doc_parser import parser
from tb_common.zipcap import RATIO_FLOOR_BYTES, RULESET_ZIP_MAX_RATIO

BODY_BYTES = 8 * RATIO_FLOOR_BYTES  # 8 MB of one repeated character: deflates at roughly 1000 to 1


def _inflating_docx() -> bytes:
    """A valid package whose word/document.xml holds one paragraph of BODY_BYTES characters (synthetic text)."""
    import docx

    d = docx.Document()
    d.add_paragraph("Inclusion criteria")
    buf = io.BytesIO()
    d.save(buf)
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    out = io.BytesIO()
    head = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:body><w:p><w:r><w:t>")  # fmt: skip
    tail = b"</w:t></w:r></w:p></w:body></w:document>"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for info in src.infolist():
            if info.filename != "word/document.xml":
                z.writestr(info.filename, src.read(info.filename))
        z.writestr("word/document.xml", head + b"a" * BODY_BYTES + tail)
    return out.getvalue()


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-08: a protocol DOCX is inflated with no size or ratio cap (doc_parser._lite_docx)",
)
def test_a_docx_far_over_the_ratio_cap_is_refused_before_it_is_read() -> None:
    data = _inflating_docx()
    info = zipfile.ZipFile(io.BytesIO(data)).getinfo("word/document.xml")
    assert info.file_size > RATIO_FLOOR_BYTES
    assert info.file_size > RULESET_ZIP_MAX_RATIO * info.compress_size  # the crafted member is over the box's ratio cap
    with pytest.raises(parser.UnreadableDocument):
        parser.parse(data, "protocol.docx", None, backend="lite")
