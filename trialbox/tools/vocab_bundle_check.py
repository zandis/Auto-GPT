"""No must-not-ship vocabulary reaches a bundle (card 22-4, root review 22; the guard of plan 10's 9h-13).

    python -m tools.vocab_bundle_check --tree                       # the shipped data files of this tree
    python -m tools.vocab_bundle_check PATH...                      # bundle inputs: rule-set zips, refdata packs
    python -m tools.vocab_bundle_check --models DIR [PATH...]       # a models folder (make_bundle.sh --models)

**What it reads.** Every file under the paths, opening containers as it goes: ``.zip``, ``.tar``, ``.tar.gz``/``.tgz``
and ``.gz`` (nested ones too). Tables (CSV, TSV, ``.txt``, Parquet) by their vocabulary and system columns; JSON,
NDJSON and JSONL by every key and string value; other text (SQL, CQL, YAML, XML, Markdown, files without an
extension) by a search for the URIs and OIDs of the must-not-ship vocabularies.

**What fails it.** A row, value or mention of a vocabulary the licence register classes ``c`` (must not ship): the
ids of its ``athena_never`` cells with their aliases, URIs and OIDs (``ID|alias|...``), and the code-system URIs of
``tools.codemap_release.SYSTEM_REGISTER`` whose register row is class c. Names are compared without case and with
spaces collapsed. Also a problem: a path that does not exist, no artefact at all, JSON or an NDJSON line that does
not parse, and anything it **cannot check**: a database file (SQLite, a dump), a ``.bz2``/``.xz``/``.7z``/``.zst``
archive, a container image tar, a PDF, an unknown binary, or, in a bundle input, a table with no vocabulary or
system column. Model weights, fonts and images in a models folder are listed as not terminology.

**By label only.** The check reads the vocabulary labels and system URIs the artefacts carry. A row relabelled, or a
concept id with no label, passes; looking concept ids up in the site's own download is card 22-4b, not done here.

**Exceptions.** A register row of kind ``bundle-exception`` (status ``decision-pending``: an owner decision is
pending) names shipped files in ``paths``; a hit in such a file is printed as a warning, not a failure. The register
holds the rows; this tool holds no list of its own.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omop.vocab_load import REGISTER, athena_register, fold  # noqa: E402

from tools import licence_register as lr  # noqa: E402
from tools.codemap_release import SYSTEM_REGISTER  # noqa: E402

BY_LABEL = (
    "checked by label: vocabulary columns, system columns, JSON keys and values, URI and OID mentions; a relabelled "
    "row or an unlabelled concept id passes (a lookup in the site's download is card 22-4b)"
)
TABLE = (".csv", ".tsv", ".txt", ".parquet")
JSON_DOC = (".json",)
JSON_LINES = (".ndjson", ".jsonl")
CANNOT = (
    ".sqlite", ".sqlite3", ".db", ".dump", ".bak", ".bz2", ".xz", ".7z", ".zst", ".rar", ".lz4", ".pdf", ".xlsx",
    ".xls", ".docx", ".mdb", ".accdb", ".feather", ".arrow", ".avro", ".orc", ".pkl", ".pickle",
)  # fmt: skip
NOT_TERMINOLOGY = (
    ".safetensors", ".gguf", ".bin", ".pt", ".pth", ".onnx", ".msgpack", ".h5", ".ttf", ".otf", ".woff", ".woff2",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
)  # fmt: skip
ENCODINGS = ("utf-8", "cp932")  # the JP masters' sample files are Shift-JIS (cp932)
NESTED_LIMIT = 6


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def is_vocab_key(name: str) -> bool:
    k = _key(name)
    return k in ("vocab", "vocabid", "vocabulary") or k.endswith("vocabularyid") or k.endswith("vocabulary")


def is_system_key(name: str) -> bool:
    k = _key(name)
    return k in ("system", "codesystem", "sourceuri", "targeturi", "source", "target") or k.endswith("system")


Hits = dict[tuple[str, str], int]  # (vocabulary, register row) -> rows


@dataclass(frozen=True)
class Rules:
    """The must-not-ship names (folded) -> (vocabulary, register row); the URIs and OIDs searched for in text; the
    exception rows (id, path patterns)."""

    names: dict[str, tuple[str, str]]
    needles: dict[str, tuple[str, str]]
    exceptions: tuple[tuple[str, tuple[str, ...]], ...] = ()


def rules(register: Path = REGISTER) -> Rules:
    names: dict[str, tuple[str, str]] = {}
    for v, c in athena_register(register).items():
        if not c.loadable:
            for n in (v, *c.aliases):
                names.setdefault(fold(n), (v, c.row))
    rows = lr.load(register)
    c_rows = {r.id for r in rows if r.klass == lr.MUST_NOT_SHIP}
    for uri, row in SYSTEM_REGISTER.items():
        if row in c_rows:
            names.setdefault(fold(uri), (uri, row))
    needles = {n: hit for n, hit in names.items() if "://" in n or n.startswith("urn:oid:")}
    exceptions = tuple((r.id, r.paths) for r in rows if r.kind == lr.EXCEPTION_KIND)
    return Rules(names, needles, exceptions)


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    artefacts: int = 0


def _decode(blob: bytes) -> str | None:
    if b"\x00" in blob[:4096]:
        return None
    for enc in ENCODINGS:
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


class Checker:
    """Reads one input (a file or a folder) in a mode: ``tree`` (shipped data files, tables need no vocabulary
    column), ``bundle`` (a bundle input: every table must have one) or ``models`` (a models folder)."""

    def __init__(self, r: Rules, report: Report, root: Path = ROOT) -> None:
        self.r, self.report, self.root = r, report, root

    # ---------------------------------------------------------------------------------------------- walking
    def path(self, p: Path, mode: str) -> None:
        if not p.exists():
            self.report.problems.append(f"{p}: no such path")
            return
        files = sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
        if not files:
            self.report.problems.append(f"{p}: no artefact to check")
        for f in files:
            self.data(str(f), f.read_bytes(), mode, 0, self._exception(f))

    def _exception(self, f: Path) -> str | None:
        try:
            rel = f.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return None
        for rid, patterns in self.r.exceptions:
            if any(re.fullmatch(lr._glob_rx(pat), rel) for pat in patterns):
                return rid
        return None

    def data(self, name: str, blob: bytes, mode: str, depth: int, exception: str | None = None) -> None:
        low = name.lower()
        if depth > NESTED_LIMIT:
            return self.cannot(name, "containers nested too deep")
        if low.endswith(".zip"):
            return self._zip(name, blob, mode, depth)
        if low.endswith((".tar", ".tar.gz", ".tgz")):
            return self._tar(name, blob, mode, depth)
        if low.endswith(".gz"):
            try:
                return self.data(name[:-3], gzip.decompress(blob), mode, depth + 1, exception)
            except (OSError, EOFError) as exc:
                return self.cannot(name, f"gzip does not open ({exc})")
        if low.endswith(CANNOT):
            return self.cannot(name, "a database, archive or document kind this check does not read")
        if low.endswith(NOT_TERMINOLOGY):
            self.report.notes.append(f"{name}: not terminology (model weights, font or image), not read")
            return None
        self.report.artefacts += 1
        hits: dict[tuple[str, str], int] = {}
        if low.endswith(".parquet"):
            self._parquet(name, blob, mode, hits)
        else:
            text = _decode(blob)
            if text is None:
                return self.cannot(name, "binary content of an unknown kind")
            if low.endswith(JSON_DOC):
                self._json(name, text, hits)
            elif low.endswith(JSON_LINES):
                self._jsonl(name, text, hits)
            elif low.endswith((".csv", ".tsv", ".txt")):
                self._table(name, text, mode, hits)
            else:  # SQL, CQL, YAML and any other text: the URIs and OIDs it mentions
                self._mentions(text, hits)
        for (vocab, row), n in sorted(hits.items()):
            line = f"{name}: {n} row(s) of vocabulary {vocab!r}, licence class c, must not ship (register row {row})"
            if exception:
                self.report.warnings.append(f"WARNING {line}; allowed for now by register row {exception} "
                                            "(owner decision pending)")  # fmt: skip
            else:
                self.report.problems.append(line)
        return None

    def cannot(self, name: str, why: str) -> None:
        self.report.problems.append(f"{name}: cannot be checked: {why}")

    def _zip(self, name: str, blob: bytes, mode: str, depth: int) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                members = [i for i in z.infolist() if not i.is_dir()]
                if not members:
                    self.report.problems.append(f"{name}: an empty zip")
                for i in members:
                    self.data(f"{name}!{i.filename}", z.read(i), mode, depth + 1)
        except zipfile.BadZipFile as exc:
            self.cannot(name, f"zip does not open ({exc})")

    def _tar(self, name: str, blob: bytes, mode: str, depth: int) -> None:
        try:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
                members = [m for m in tf.getmembers() if m.isfile()]
                base = {m.name.split("/")[-1] for m in members}
                if "manifest.json" in base and ({"repositories", "oci-layout"} & base or
                                                any(m.name.endswith("/layer.tar") for m in members)):  # fmt: skip
                    return self.cannot(name, "a container image tar")
                for m in members:
                    f = tf.extractfile(m)
                    if f is not None:
                        self.data(f"{name}!{m.name}", f.read(), mode, depth + 1)
        except tarfile.TarError as exc:
            self.cannot(name, f"tar does not open ({exc})")
        return None

    # ---------------------------------------------------------------------------------------------- reading
    def _hit(self, value: Any, hits: dict[tuple[str, str], int]) -> None:
        if isinstance(value, str) and value:
            got = self.r.names.get(fold(value))
            if got is not None:
                hits[got] = hits.get(got, 0) + 1

    def _json_walk(self, node: Any, hits: dict[tuple[str, str], int]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str):
                    if is_vocab_key(k) or is_system_key(k) or "://" in v or v.startswith("urn:"):
                        self._hit(v, hits)
                else:
                    self._json_walk(v, hits)
        elif isinstance(node, list):
            for v in node:
                self._json_walk(v, hits)

    def _json(self, name: str, text: str, hits: dict[tuple[str, str], int]) -> None:
        try:
            doc = json.loads(text)
        except ValueError as exc:
            self.report.problems.append(f"{name}: JSON does not parse ({exc})")
            return
        self._json_walk(doc, hits)

    def _jsonl(self, name: str, text: str, hits: dict[tuple[str, str], int]) -> None:
        for n, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                try:
                    self._json_walk(json.loads(line), hits)
                except ValueError as exc:
                    self.report.problems.append(f"{name}: line {n} does not parse ({exc})")

    def _columns(self, name: str, cols: Iterable[str], mode: str) -> list[str]:
        keep = [c for c in cols if c and (is_vocab_key(c) or is_system_key(c))]
        if not keep and mode == "bundle":
            self.cannot(name, "a table with no vocabulary or system column")
        return keep

    def _table(self, name: str, text: str, mode: str, hits: dict[tuple[str, str], int]) -> None:
        head = text.split("\n", 1)[0]
        delim = "\t" if head.count("\t") >= max(head.count(","), 1) else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        keep = self._columns(name, reader.fieldnames or [], mode)
        if keep:
            for r in reader:
                for c in keep:
                    self._hit(r.get(c), hits)
        self._mentions(text, hits, skip=hits)

    def _parquet(self, name: str, blob: bytes, mode: str, hits: dict[tuple[str, str], int]) -> None:
        import pyarrow.parquet as pq

        try:
            f = pq.ParquetFile(io.BytesIO(blob))
        except Exception as exc:  # any reader error: this file cannot be checked
            self.cannot(name, f"Parquet does not open ({type(exc).__name__})")
            return
        keep = self._columns(name, f.schema_arrow.names, mode)
        if keep:
            for row in f.read(columns=keep).to_pylist():
                for v in row.values():
                    self._hit(v, hits)

    def _mentions(self, text: str, hits: Hits, skip: Hits | None = None) -> None:
        low = text.casefold()
        for needle, got in self.r.needles.items():
            if skip and got in skip:
                continue
            # a whole URI or OID: http://hl7.org/fhir/sid/icd-10 is not a mention inside .../icd-10-cm
            n = len(re.findall(re.escape(needle) + r"(?![\w\-./#])", low))
            if n:
                hits[got] = hits.get(got, 0) + n


def check(paths: Iterable[Path] = (), *, tree: bool = False, models: Iterable[Path] = (),
          register: Path = REGISTER, root: Path = ROOT) -> Report:  # fmt: skip
    report = Report()
    c = Checker(rules(register), report, root)
    if tree:
        for f in lr.shipped_data_files(root):
            c.path(root / f, "tree")
    for p in paths:
        c.path(p, "bundle")
    for p in models:
        c.path(p, "models")
    if not tree and report.artefacts == 0 and not report.problems:
        report.problems.append("no artefact to check")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.vocab_bundle_check", description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", type=Path, help="bundle inputs: folders or files (zip, tar, refdata packs)")
    ap.add_argument("--tree", action="store_true", help="the shipped data files of this tree")
    ap.add_argument("--models", action="append", type=Path, default=[], help="a models folder")
    a = ap.parse_args(argv)
    if not (a.tree or a.paths or a.models):
        ap.error("give --tree, --models DIR or a path")
    rep = check(a.paths, tree=a.tree, models=a.models)
    print(BY_LABEL)
    for n in rep.notes:
        print(n)
    for w in rep.warnings:
        print(w)
    for p in rep.problems:
        print(p, file=sys.stderr)
    print(f"vocabulary bundle check: {rep.artefacts} artefacts, {len(rep.problems)} problems, "
          f"{len(rep.warnings)} warnings")  # fmt: skip
    return 1 if rep.problems else 0


if __name__ == "__main__":
    sys.exit(main())
