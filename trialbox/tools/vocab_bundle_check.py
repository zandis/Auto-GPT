"""No must-not-ship vocabulary reaches a bundle (card 22-4, root review 22; the guard of plan 10's 9h-13).

    python -m tools.vocab_bundle_check --tree                       # the shipped data files of this tree
    python -m tools.vocab_bundle_check PATH...                      # bundle inputs: rule-set zips, refdata packs
    python -m tools.vocab_bundle_check --models DIR [PATH...]       # a models folder (make_bundle.sh --models)

**What it reads.** Every file under the paths, opening containers as it goes: ``.zip``, ``.tar``, ``.tar.gz``/``.tgz``
and ``.gz`` (nested ones too). Tables (CSV, TSV, ``.txt``, Parquet) by their vocabulary and system columns; JSON,
NDJSON and JSONL by every key and string value; other text (SQL, CQL, YAML, XML, Markdown, files without an
extension) by a search for the URIs and OIDs of the must-not-ship vocabularies.

**What fails it.** A row, value or mention of a vocabulary the licence register classes ``c`` (must not ship): the ids
of its ``athena_never`` cells with their aliases, URIs and OIDs (``ID|alias|...``), and nothing else: the register is
the one source. Names are compared without case and with spaces collapsed. (The WHO ICD-10 system URI is not among
them: WHO ICD-10 codes ship as identifiers under register row ``icd10-who-cm-bridge``; only the Athena ``ICD10``
vocabulary, codes with WHO's titles, is class c.) Also a problem: a path that does not exist, no artefact at all, JSON
or an NDJSON line that does not parse, and anything it **cannot check**: a database file (SQLite, a dump), a
``.bz2``/``.xz``/``.7z``/``.zst`` archive, a container image tar, a PDF, an unknown binary, or, in a bundle input, a
table with no vocabulary or system column. Model weights, fonts and images in a models folder are listed as not
terminology.

**By label only.** The check reads the vocabulary labels and system URIs the artefacts carry. A row relabelled, or a
concept id with no label, passes; looking concept ids up in the site's own download is card 22-4b, not done here.

**What guards what.** ``--tree`` (the shipped tree, the images' content) runs in ``make vocab-bundle-check``, which
``make release-bundle`` and ``make demo-bundle`` need. ``tools/make_bundle.sh`` checks only what it stages beside the
images (rule-set zips, reference data packs, the models folder): run directly, as ``tools/rehearse_box/rehearse.sh``,
``tools/runbook_install.py``, ``deploy/gcp/box-install-run.sh`` and ``deploy/gcp/demo-vm-update.sh`` do, it does not
check the tree.

**Exceptions.** A register row of kind ``bundle-exception`` (status ``decision-pending``: an owner decision is
pending) names shipped files in ``paths``; a hit in such a file is printed as a warning, not a failure. A row of status
``owner-approved`` (the owner ruled) names in ``excepts`` the vocabularies whose concept ids, and nothing else of them,
its files may carry (``VOCAB``, or ``VOCAB:id|id`` to name the ids). In those files an entry labelled with an excepted
vocabulary passes, as a note, only while it carries no text (no key or column naming a name, display, description,
definition, title, synonym, designation, term or text with a value) and, where the row names ids, its id
(``concept_id``, ``code`` or ``concept_code``) is one of them; a JSON or YAML object passes so, a table row only when
the row names ids. A hit of any other vocabulary, an entry that fails those tests, a hit counted beyond the entries
let through (a URI in prose) and a hit in any other kind of file still fail. The register holds the rows; this tool
holds no list of its own.
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

import yaml  # noqa: E402
from omop.vocab_load import REGISTER, athena_register  # noqa: E402
from tb_common.vocabfold import fold  # noqa: E402

from tools import licence_register as lr  # noqa: E402

BY_LABEL = (
    "checked by label: vocabulary and system columns, JSON and YAML keys and values, delimited fields of other text, "
    "URI and OID mentions; a relabelled row or an unlabelled concept id passes (a lookup in the site's download is "
    "card 22-4b). --tree guards make vocab-bundle-check, release-bundle and demo-bundle; make_bundle.sh, run directly "
    "(rehearse.sh, runbook_install, box-install-run.sh, demo-vm-update.sh), checks only what it stages"
)
TABLE = (".csv", ".tsv", ".txt", ".parquet")
JSON_DOC = (".json",)
JSON_LINES = (".ndjson", ".jsonl")
YAML = (".yaml", ".yml")
# notices and read-me files: searched for URIs and OIDs only, not field by field
PROSE = (".md", ".html", ".htm", ".rst")
# the fields of other text (SQL, CQL, a dump, an unknown extension): the pieces between these delimiters (not spaces,
# so prose is one field and is folded whole)
FIELD = re.compile(r"[\t,;|'\"`()=:\[\]{}<>]")
OID = re.compile(r"\d+(?:\.\d+){3,}")
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
    return (k in ("vocab", "vocabid", "vocabulary", "terminology", "codingscheme", "cs") or k.endswith("vocabularyid")
            or k.endswith("vocabulary"))  # fmt: skip


def is_system_key(name: str) -> bool:
    k = _key(name)
    return k in ("system", "codesystem", "sourceuri", "targeturi", "source", "target") or k.endswith("system")


Hits = dict[tuple[str, str], int]  # (vocabulary, register row) -> rows


@dataclass(frozen=True)
class ExceptionRow:
    """A register row of kind bundle-exception: its id, path patterns, status and (owner-approved) the register
    vocabulary ids whose concept ids its files may carry, each with the ids it lists (None: any id)."""

    row: str
    patterns: tuple[str, ...]
    status: str = lr.PENDING
    excepts: dict[str, frozenset[str] | None] = field(default_factory=dict)
    owners: dict[str, str] = field(default_factory=dict)  # vocabulary -> the row that excepts it


# the keys of a labelled object that carry a concept's text, not its id (folded: lower case, no punctuation)
TEXT_KEY = re.compile(r"name|display|description|definition|title|synonym|designation|term|text")


@dataclass(frozen=True)
class Rules:
    """The must-not-ship names (folded) -> (vocabulary, register row); the URIs and OIDs searched for in text; the
    exception rows (id, path patterns)."""

    names: dict[str, tuple[str, str]]
    needles: dict[str, tuple[str, str]]
    exceptions: tuple[ExceptionRow, ...] = ()


def rules(register: Path = REGISTER) -> Rules:
    names: dict[str, tuple[str, str]] = {}
    for v, c in athena_register(register).items():
        if not c.loadable:
            for n in (v, *c.aliases):
                names.setdefault(fold(n), (v, c.row))
    rows = lr.load(register)
    needles: dict[str, tuple[str, str]] = {}  # URIs and OIDs as written (lower case), searched for whole in text
    for v, c in athena_register(register).items():
        if c.loadable:
            continue
        for n in (v, *c.aliases):
            low = n.strip().lower()
            forms = [low]
            if low.startswith("http://"):
                forms.append("https://" + low[7:])
            if low.startswith("urn:oid:"):
                forms.append(low[8:])
            for f in forms:
                if "://" in f or f.startswith("urn:oid:") or OID.fullmatch(f):
                    needles.setdefault(f, (v, c.row))
                    names.setdefault(fold(f), (v, c.row))
    exceptions = []
    for r in rows:
        if r.kind == lr.EXCEPTION_KIND:
            excepts = {names[fold(v)][0]: ids for v, ids in lr.excepted(r).items() if fold(v) in names}
            exceptions.append(ExceptionRow(r.id, r.paths, r.status, excepts))
    return Rules(names, needles, tuple(exceptions))


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    artefacts: int = 0


def _documents(text: str, *, yaml_: bool) -> list[Any]:
    """The parsed documents of a JSON or YAML text; none when it does not parse (reported by the reader)."""
    try:
        return list(yaml.safe_load_all(text)) if yaml_ else [json.loads(text)]
    except (ValueError, yaml.YAMLError):
        return []


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

    def _exception(self, f: Path) -> ExceptionRow | None:
        try:
            rel = f.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return None
        found = [e for e in self.r.exceptions if any(re.fullmatch(lr._glob_rx(pat), rel) for pat in e.patterns)]
        if len(found) <= 1:
            return found[0] if found else None
        # several rows name the file: their excepted vocabularies together; a pending row keeps the file a warning
        merged = ExceptionRow(" and ".join(e.row for e in found), (),
                              lr.PENDING if any(e.status == lr.PENDING for e in found) else lr.APPROVED)  # fmt: skip
        for e in found:
            merged.excepts.update(e.excepts)
            merged.owners.update(dict.fromkeys(e.excepts, e.row))
        return merged

    def data(self, name: str, blob: bytes, mode: str, depth: int, exception: ExceptionRow | None = None) -> None:
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
        texts: list[str] = []  # in an owner-approved exception: labelled entries it does not let through
        allowed: dict[str, int] = {}  # vocabulary -> labelled entries it lets through (an id only, listed if listed)
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
            elif low.endswith(YAML):
                self._yaml(name, text, hits)
            elif low.endswith((".csv", ".tsv", ".txt")):
                self._table(name, text, mode, hits)
            elif low.endswith(PROSE):
                self._mentions(text, hits)
            else:  # SQL, CQL, a dump, any other text: its delimited fields, and the URIs and OIDs it mentions
                self._fields(text, hits)
                self._mentions(text, hits, skip=hits)
            if exception and exception.excepts:
                if low.endswith((*JSON_DOC, *YAML)):
                    for doc in _documents(text, yaml_=low.endswith(YAML)):
                        self._excepted_objects(doc, exception, allowed, texts)
                elif low.endswith((".csv", ".tsv", ".txt")):
                    self._excepted_rows(text, exception, allowed, texts)
        for (vocab, row), n in sorted(hits.items()):
            line = f"{name}: {n} row(s) of vocabulary {vocab!r}, licence class c, must not ship (register row {row})"
            if exception and exception.status == lr.PENDING:
                self.report.warnings.append(f"WARNING {line}; allowed for now by register row {exception.row} "
                                            "(owner decision pending)")  # fmt: skip
            elif exception and vocab in exception.excepts and allowed.get(vocab, 0) == n:
                owner = exception.owners.get(vocab, exception.row)
                self.report.notes.append(f"{name}: {n} concept id(s) of vocabulary {vocab!r}, ids only, allowed by "
                                         f"register row {owner} (owner-approved)")  # fmt: skip
            else:
                self.report.problems.append(line)
        for t in texts:
            self.report.problems.append(f"{name}: {t}; register row {exception.row if exception else ''} lets "
                                        "through the concept ids it names, never their text")  # fmt: skip
        return None

    def _excepted(self, vocab: str, ident: Any, entry: dict[str, Any], exc: ExceptionRow, what: str,
                  allowed: dict[str, int], out: list[str]) -> None:  # fmt: skip
        """One labelled entry of an excepted vocabulary: let through when it carries no text and, where the row lists
        ids, its id is listed."""
        ok = True
        for k, v in entry.items():
            if isinstance(k, str) and TEXT_KEY.search(_key(k)) and v not in (None, "", [], {}):
                out.append(f"{what} of vocabulary {vocab!r} carries text in {k!r}")
                ok = False
        ids = exc.excepts[vocab]
        if ids is not None and str(ident if ident is not None else "").strip() not in ids:
            out.append(f"{what} of vocabulary {vocab!r} has id {ident!r}, which the register row does not list")
            ok = False
        if ok:
            allowed[vocab] = allowed.get(vocab, 0) + 1

    def _vocab_of(self, k: Any, v: Any, exc: ExceptionRow) -> str | None:
        if isinstance(k, str) and isinstance(v, str) and v and (is_vocab_key(k) or is_system_key(k)):
            got = self.r.names.get(fold(v))
            if got is not None and got[0] in exc.excepts:
                return got[0]
        return None

    def _excepted_objects(self, node: Any, exc: ExceptionRow, allowed: dict[str, int], out: list[str]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                vocab = self._vocab_of(k, v, exc)
                if vocab is not None:
                    ident = node.get("concept_id", node.get("code"))
                    self._excepted(vocab, ident, node, exc, "an object", allowed, out)
            for v in node.values():
                self._excepted_objects(v, exc, allowed, out)
        elif isinstance(node, list):
            for v in node:
                self._excepted_objects(v, exc, allowed, out)

    def _excepted_rows(self, text: str, exc: ExceptionRow, allowed: dict[str, int], out: list[str]) -> None:
        head = text.split("\n", 1)[0]
        delim = "\t" if head.count("\t") >= max(head.count(","), 1) else ","
        for n, r in enumerate(csv.DictReader(io.StringIO(text), delimiter=delim), start=2):
            for k, v in r.items():
                vocab = self._vocab_of(k, v, exc)
                if vocab is not None and exc.excepts[vocab] is None:
                    out.append(f"line {n} of vocabulary {vocab!r} is a table row: the register row lets a table "
                               "through only for the ids it lists")  # fmt: skip
                elif vocab is not None:
                    ident = next((r[c] for c in ("concept_id", "code", "concept_code") if r.get(c)), None)
                    self._excepted(vocab, ident, r, exc, f"line {n}", allowed, out)

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
            if got is None and "://" in value:  # an edition or version URI: http://snomed.info/sct/<id>/version/<d>
                got = self.r.names.get(fold(re.sub(r"/\d[\w./-]*$", "", value.strip())))
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

    def _yaml(self, name: str, text: str, hits: Hits) -> None:
        try:
            docs = list(yaml.safe_load_all(text))
        except yaml.YAMLError:
            self.report.problems.append(f"{name}: YAML does not parse")
            return
        for doc in docs:
            self._json_walk(doc, hits)

    def _fields(self, text: str, hits: Hits) -> None:
        for line in text.splitlines():
            for field_ in FIELD.split(line):
                if field_.strip():
                    self._hit(field_, hits)

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

        try:  # read at once, single-threaded (H-52, H-62: no Python object handed to Arrow's IO pool)
            table = pq.ParquetFile(io.BytesIO(blob)).read(use_threads=False)
        except Exception as exc:  # any reader error: this file cannot be checked
            self.cannot(name, f"Parquet does not open ({type(exc).__name__})")
            return
        keep = self._columns(name, table.schema.names, mode)
        if keep:
            for row in table.select(keep).to_pylist():
                for v in row.values():
                    self._hit(v, hits)

    def _mentions(self, text: str, hits: Hits, skip: Hits | None = None) -> None:
        low = text.casefold()
        ends: dict[tuple[str, str], set[int]] = {}
        for needle, got in self.r.needles.items():
            if skip and got in skip:
                continue
            # a whole URI or OID (http://hl7.org/fhir/sid/icd-10 is no mention inside .../icd-10-cm), with an edition
            # or version path after it (http://snomed.info/sct/<module>/version/<date>); one place counted once
            rx = r"(?<![\w.])" + re.escape(needle) + r"(?:/\d[\w./-]*)?(?![\w\-./#])"
            ends.setdefault(got, set()).update(m.end() for m in re.finditer(rx, low))
        for got, at in ends.items():
            if at:
                hits[got] = hits.get(got, 0) + len(at)


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
    ap = argparse.ArgumentParser(prog="python -m tools.vocab_bundle_check", description=__doc__.split("\n")[0],
                                 epilog=BY_LABEL)  # fmt: skip
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
