"""The CDISC ODM 1.3.2 schema check of an ODM file (E-25, STD-062; T-115): ``lxml`` (libxml2, the library behind
``xmllint``) against ``tests/fixtures/odm/ODM1-3-2.xsd``, and ``xmllint --schema`` itself where it is installed.
The schema files are CDISC's, unchanged (``tests/fixtures/odm/SOURCE.txt``); nothing is fetched from the network."""

from __future__ import annotations

import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]

XSD = Path(__file__).resolve().parent / "fixtures" / "odm" / "ODM1-3-2.xsd"


@cache
def _schema() -> Any:
    parser = etree.XMLParser(no_network=True, resolve_entities=False)
    return etree.XMLSchema(etree.parse(str(XSD), parser))


def problems(text: str) -> list[str]:
    """The schema's complaints about ``text`` (empty: valid)."""
    doc = etree.fromstring(text.encode("utf-8"), etree.XMLParser(no_network=True, resolve_entities=False))
    schema = _schema()
    if schema.validate(doc):
        return []
    return [f"{e.line}: {e.message}" for e in schema.error_log]


def xmllint(text: str, folder: Path) -> tuple[int, str] | None:
    """``xmllint --noout --nonet --schema ODM1-3-2.xsd`` on ``text``: (exit code, output), or None without xmllint."""
    exe = shutil.which("xmllint")
    if exe is None:
        return None
    f = folder / "export.odm.xml"
    f.write_text(text, encoding="utf-8")
    r = subprocess.run([exe, "--noout", "--nonet", "--schema", str(XSD), str(f)], capture_output=True, text=True,
                       check=False, timeout=60)  # fmt: skip
    return r.returncode, r.stdout + r.stderr
