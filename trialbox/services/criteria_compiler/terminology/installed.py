"""Code systems loaded on the box at install (D-1028, D-1029; TERM-1, D-858).

A code system that may not be committed (LOINC, WHO ICD-10, ATC, a site's own lists: D-1028 as amended by D-1029) is
loaded onto each box at install and at update, by ``python -m tools.terminology_install``, into
``TB_TERMINOLOGY_DIR`` (default ``/data/terminology``). Every table written there has its line in ``manifest.json``:
the source, the version, the licence note, the file's sha256, its rows and when it was loaded. A table with no line,
or whose bytes do not match its line, is refused: it is not read, and ``trialbox doctor`` says so.

Loaders today:

* ``icd10cm_blocks`` and ``icd10cm_index``, from CMS's ICD-10-CM code-tables zip (the tabular list and the
  Alphabetic Index, US public domain): the blocks and chapters (``Ischemic heart diseases``, I20 to I25) and the
  index's main terms and first-level subterms (``Epilepsy``; ``Accident, cerebrovascular``). The FY2026 tables also
  ship in the repository (D-1029); a later release loaded here is read in their place, so a box takes the next
  year's names without a new image. Taiwan's NHI codes diagnoses in ICD-10-CM (its 2023 edition since 2025-01-01,
  D-171); the US release's blocks and index serve its names.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

DIR_ENV = "TB_TERMINOLOGY_DIR"
DEFAULT_DIR = "/data/terminology"
MANIFEST = "manifest.json"
ICD_BLOCKS, ICD_INDEX = "icd10cm_blocks", "icd10cm_index"
ICD_LICENCE = "US public domain (CMS, NCHS): ICD-10-CM; source credited"
_RANGE = re.compile(r"^([A-Z][0-9A-Z]{2})-([A-Z][0-9A-Z]{2})$")


class TerminologyRefused(RuntimeError):
    """A loaded table that cannot be trusted: no manifest line, or bytes that do not match it."""


def installed_dir(env: dict[str, str] | None = None) -> Path:
    return Path(((os.environ if env is None else env).get(DIR_ENV) or "").strip() or DEFAULT_DIR)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(directory: Path) -> dict[str, Any]:
    p = directory / MANIFEST
    if not p.is_file():
        return {"tables": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) and isinstance(data.get("tables"), dict) else {"tables": {}}


def read_table(directory: Path, name: str) -> list[dict[str, Any]] | None:
    """The rows of a loaded table, or None when it is not loaded. Raises :class:`TerminologyRefused` for a table with
    no manifest line or whose sha256 differs from it (a hand-copied or changed file is never read)."""
    path = directory / f"{name}.parquet"
    if not path.is_file():
        return None
    line = manifest(directory)["tables"].get(name)
    if not line:
        raise TerminologyRefused(f"{path}: no line in {MANIFEST}; load it with tools.terminology_install")
    if line.get("sha256") != _sha(path):
        raise TerminologyRefused(f"{path}: its sha256 differs from {MANIFEST}; load it again")
    rows: list[dict[str, Any]] = pq.read_table(path).to_pylist()
    return rows


@dataclass(frozen=True)
class Loaded:
    name: str
    source: str
    version: str
    rows: int
    problem: str = ""


def status(directory: Path) -> list[Loaded]:
    """Each table under the directory and each manifest line: what is loaded, and what is refused and why."""
    lines = manifest(directory)["tables"]
    names = sorted({p.stem for p in directory.glob("*.parquet")} | set(lines)) if directory.is_dir() else []
    out = []
    for n in names:
        line = lines.get(n) or {}
        try:
            rows = read_table(directory, n)
            problem = "" if rows is not None else "in the manifest but its file is missing"
        except TerminologyRefused as exc:
            rows, problem = None, str(exc)
        out.append(Loaded(n, str(line.get("source") or ""), str(line.get("version") or ""), len(rows or []), problem))
    return out


# ------------------------------------------------------------------------------------------------ ICD-10-CM (CMS)
def zip_member(z: zipfile.ZipFile, suffix: str) -> bytes:
    names = [n for n in z.namelist() if n.lower().endswith(suffix)]
    if len(names) != 1:
        raise ValueError(f"the zip holds {len(names)} files ending {suffix!r}: not a CMS ICD-10-CM code-tables zip")
    return z.read(names[0])


def _xml(data: bytes) -> ET.Element:
    """A release's XML, refused when it declares a DTD or an entity: nothing for the parser to expand or fetch."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("the release's XML declares a DTD or an entity: refused, not a CMS ICD-10-CM file")
    return ET.fromstring(data)  # noqa: S314 - refused above when the document declares a DTD or an entity


def icd10cm_blocks(tabular: bytes) -> list[dict[str, str]]:
    """Every block and chapter of the tabular list: ``name, first, last``."""
    root = _xml(tabular)
    out: list[dict[str, str]] = []
    for ch in root.iter("chapter"):
        ranges = []
        for sec in ch.findall("section"):
            m = _RANGE.match(sec.get("id") or "")
            if m:
                name = re.sub(r"\s*\([A-Z0-9-]+\)\s*$", "", (sec.findtext("desc") or "").strip())
                out.append({"name": name, "first": m.group(1), "last": m.group(2)})
                ranges.append((m.group(1), m.group(2)))
        if ranges:
            name = re.sub(r"\s*\([A-Z0-9-]+\)\s*$", "", (ch.findtext("desc") or "").strip())
            out.append({"name": name, "first": ranges[0][0], "last": ranges[-1][1]})
    return out


def icd10cm_index(index: bytes) -> list[dict[str, str]]:
    """Every main term and first-level subterm of the Alphabetic Index that leads to a code or to another term."""
    root = _xml(index)
    out: list[dict[str, str]] = []
    for mt in root.iter("mainTerm"):
        title = " ".join((mt.findtext("title") or "").split())
        code, see = (mt.findtext("code") or "").strip(), " ".join((mt.findtext("see") or "").split())
        if title and (code or see):
            out.append({"term": title, "code": code, "see": "" if code else see})
        for sub in mt.findall("term"):
            st, sc = " ".join((sub.findtext("title") or "").split()), (sub.findtext("code") or "").strip()
            if title and st and sc:
                out.append({"term": f"{title}, {st}", "code": sc, "see": ""})
    return out


def _write(directory: Path, name: str, rows: list[dict[str, str]], cols: tuple[str, ...], line: dict[str, Any]) -> None:
    path = directory / f"{name}.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(pa.table({c: pa.array([r[c] for r in rows], pa.string()) for c in cols}), tmp, compression="zstd")
    tmp.replace(path)
    data = manifest(directory)
    data["tables"][name] = {**line, "sha256": _sha(path), "rows": len(rows)}
    (directory / MANIFEST).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def install_icd10cm(zip_path: Path, directory: Path, year: str, now: datetime | None = None) -> dict[str, int]:
    """Load ICD-10-CM's blocks and Alphabetic Index from CMS's code-tables zip of ``year`` (read, never unpacked)."""
    with zipfile.ZipFile(zip_path) as z:
        tab, idx = zip_member(z, f"icd10cm_tabular_{year}.xml"), zip_member(z, f"icd10cm_index_{year}.xml")
    directory.mkdir(parents=True, exist_ok=True)
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    line = {"source": f"CMS ICD-10-CM {year} code tables ({zip_path.name}, sha256 {_sha(zip_path)[:16]})",
            "version": f"ICD-10-CM {year}", "licence": ICD_LICENCE, "loaded_at": when}  # fmt: skip
    blocks, index = icd10cm_blocks(tab), icd10cm_index(idx)
    _write(directory, ICD_BLOCKS, blocks, ("name", "first", "last"), line)
    _write(directory, ICD_INDEX, index, ("term", "code", "see"), line)
    return {ICD_BLOCKS: len(blocks), ICD_INDEX: len(index)}
