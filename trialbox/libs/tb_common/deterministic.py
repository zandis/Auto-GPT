"""Byte-reproducible office documents (SPEC §11.2: same inputs + versions -> identical output hashes).

openpyxl / python-docx write zip entries with the current time and core properties with "now"; these helpers fix
both so a rerun produces identical bytes.
"""

from __future__ import annotations

import io
import re
import zipfile

FIXED = (2026, 1, 1, 0, 0, 0)
_TS = re.compile(rb"(<dcterms:(created|modified)[^>]*>)[^<]*(</dcterms:\2>)")


def normalize_ooxml(data: bytes, stamp: str = "2026-01-01T00:00:00Z") -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(src.namelist(), key=lambda n: (n != "[Content_Types].xml", n)):
            body = src.read(name)
            if name == "docProps/core.xml":
                body = _TS.sub(lambda m: m.group(1) + stamp.encode() + m.group(3), body)
            info = zipfile.ZipInfo(name, date_time=FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            dst.writestr(info, body)
    return out.getvalue()
