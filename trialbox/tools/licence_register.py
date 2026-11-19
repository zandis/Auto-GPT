"""The licence register as data (T-617b, STD-044, LLM-012): ``docs/licences/register.csv`` and its build check.

    python -m tools.licence_register --check     # exit 1 with one line per problem (CI job `checks`)
    python -m tools.licence_register             # the rows, one line each

One row per third-party (or own) source: standard, version, source, licence and SPDX id, obligation, who holds the
licence, status, the date it was checked, the evidence, the licence text's sha256 (models), the Athena vocabularies
it covers and the shipped files it covers (``paths``: ``;``-separated patterns relative to ``trialbox/``, ``*`` is
one path segment or part of one, ``**`` any number of segments).

The check fails when:

* a **shipped data file** has no row. Shipped means in the demo image's copy of ``trialbox/`` (minus
  ``.dockerignore``). A data file is a code list, code map or value set (the detector of ``tests/unit/test_notice.py``:
  a CSV, TSV, text or Parquet file whose name or header names a code system, or a FHIR ValueSet, CodeSystem or
  ConceptMap), or any other CSV, TSV, text, Parquet or JSON file in a folder that holds one;
* a row's pattern matches no shipped file (a stale row), or a row that ships nothing (``site-loaded``, ``removed``,
  ``model``) has a pattern;
* a shipped data file names the SNOMED CT system or has a ``snomed`` column: v1 ships no SNOMED CT (row
  ``snomed-ct``, D-342);
* a build of ``models/registry.yaml`` disagrees with its row: ``verified: true`` needs ``register: <id>``, a ``model``
  row whose source is the build's repository, whose SPDX id is the build's, and whose status is ``cleared`` or
  ``own-work``; a build past ``candidate`` needs ``verified: true``;
* a vocabulary the OMOP Athena loader allows (``omop.vocab_load.ATHENA_ALLOW``, when it exists) has no row;
* a ``software`` row (a third-party program inside an image, D-968: restic) disagrees with its pin in
  ``deploy/docker/backup.Dockerfile``: ``ARG <ID>_VERSION`` must be the row's version and every
  ``ARG <ID>_SHA256_<PART>`` (the source archive, or one release file per architecture) must be written in the row's
  evidence. A software row ships no path of its own;
* an ``eval/DATASETS.yaml`` entry disagrees with the register (card 10H-1): an open data set names no row in its
  ``register:`` list, a row named does not exist, the entry's licence lacks the words of a row's SPDX id
  (``SPDX_WORDS``), it says "public domain" with no public-domain row, or it names SIGIR without row
  ``pubacc-sigir-2016`` or calls SIGIR material plain public domain;
* a file that holds SIGIR 2016 note text (CC BY-SA 4.0, CSIRO), or a README, NOTICE.md or PROVENANCE.md beside it,
  says "public domain" (NCBI's own "public domain notice" excepted), or such a README names SIGIR without its licence.

The rows are rendered by hand into ``NOTICE`` (T-617a); the register is the data behind it.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs/licences/register.csv"
MODELS = ROOT / "models/registry.yaml"
COLUMNS = ("id", "kind", "standard", "version", "source", "licence", "spdx", "obligation", "holder", "status",
           "checked", "evidence", "text_sha256", "athena", "paths")  # fmt: skip
KINDS = frozenset({"code-system", "map", "data-set", "fhir", "model", "software"})
IMAGE = ROOT / "deploy/docker/backup.Dockerfile"  # where a software row's tool is pinned (D-968)
STATUSES = frozenset({"cleared", "own-work", "synthetic", "site-loaded", "permission-to-ask", "removed"})
SHIPS_NOTHING = frozenset({"site-loaded", "removed"})
MODEL_OK = frozenset({"cleared", "own-work"})
PAST_CANDIDATE = frozenset({"qualified", "champion", "shadow"})

# the data-file detector (the same rule as tests/unit/test_notice.py, which names the folders in NOTICE)
SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__"})
TOKENS = frozenset({
    "atc", "byomei", "cdisc", "ctcae", "hot", "icd", "icd9", "icd10", "icd10cm", "icd10pcs", "icd11", "jlac10",
    "jlac11", "loinc", "meddra", "medis", "nhi", "rxnorm", "snomed", "ucum", "umls", "yakka", "yj",
})  # fmt: skip
TABULAR = (".csv", ".tsv", ".txt", ".csv.gz", ".parquet")
DATA = (*TABULAR, ".json")
FHIR_TERMINOLOGY = re.compile(rb'"resourceType"\s*:\s*"(ValueSet|CodeSystem|ConceptMap)"')
SNOMED_URI = b"snomed.info/sct"


@dataclass(frozen=True)
class Row:
    id: str
    kind: str
    status: str
    source: str
    spdx: str
    athena: tuple[str, ...]
    paths: tuple[str, ...]
    raw: dict[str, str]


def load(path: Path = REGISTER) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path.name}: columns must be {', '.join(COLUMNS)}")
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in reader]
    return [
        Row(r["id"], r["kind"], r["status"], r["source"], r["spdx"], _split(r["athena"]), _split(r["paths"]), r)
        for r in rows
    ]


def _split(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.split(";") if x.strip())


# ------------------------------------------------------------------------------------------------ shipped files
def dockerignore(root: Path) -> list[re.Pattern[str]]:
    """``.dockerignore`` as regular expressions over a path relative to the build context."""
    f = root / ".dockerignore"
    lines = f.read_text(encoding="utf-8").splitlines() if f.is_file() else []
    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        out.append(re.compile(_glob_rx(line.strip("/")) + "(?:/.*)?"))
    return out


def _glob_rx(pattern: str) -> str:
    rx, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            rx, i = rx + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            rx, i = rx + ".*", i + 2
        elif pattern[i] == "*":
            rx, i = rx + "[^/]*", i + 1
        elif pattern[i] == "?":
            rx, i = rx + "[^/]", i + 1
        else:
            rx, i = rx + re.escape(pattern[i]), i + 1
    return rx


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", text.lower()))


def _header(path: Path) -> str:
    opener: Any = gzip.open if path.name.lower().endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            return str(fh.readline())
    except OSError:
        return ""


def is_vocabulary(path: Path) -> bool:
    """A code list, code map or value set: a code system named in a tabular file's name or header, or a FHIR
    terminology resource."""
    name = path.name.lower()
    if name.endswith(TABULAR):
        stem = name.removesuffix(".gz").rsplit(".", 1)[0]
        if _tokens(stem) & TOKENS:
            return True
        return not name.endswith(".parquet") and bool(_tokens(_header(path)) & TOKENS)
    if name.endswith(".json"):
        with path.open("rb") as fh:
            return bool(FHIR_TERMINOLOGY.search(fh.read(4096)))
    return False


def shipped_files(root: Path = ROOT) -> list[str]:
    """Every file of the demo image's copy of ``root`` (minus ``.dockerignore``), relative and posix."""
    ignore = dockerignore(root)
    out: list[str] = []
    stack = [root]
    while stack:
        here = stack.pop()
        for p in here.iterdir():
            rel = p.relative_to(root).as_posix()
            if p.name in SKIP_DIRS or any(rx.fullmatch(rel) for rx in ignore):
                continue
            if p.is_dir() and not p.is_symlink():
                stack.append(p)
            elif p.is_file():
                out.append(rel)
    return sorted(out)


def shipped_data_files(root: Path = ROOT) -> list[str]:
    """The vocabulary files, and every data file in a folder that holds one (top level excluded)."""
    files = [f for f in shipped_files(root) if "/" in f and f.lower().endswith(DATA)]
    vocab = {f for f in files if is_vocabulary(root / f)}
    folders = {f.rsplit("/", 1)[0] for f in vocab}
    return sorted(f for f in files if f in vocab or f.rsplit("/", 1)[0] in folders)


def _matches(pattern: str, path: str) -> bool:
    return re.fullmatch(_glob_rx(pattern), path) is not None


def snomed_problems(root: Path, files: Iterable[str]) -> list[str]:
    out = []
    for f in files:
        p = root / f
        if f.lower().endswith(".parquet"):
            continue
        header = _header(p) if f.lower().endswith(TABULAR) else ""
        if "snomed" in _tokens(Path(f).name) or "snomed" in _tokens(header):
            out.append(f"{f}: SNOMED CT column or name in a shipped file (row snomed-ct: v1 ships none)")
            continue
        opener: Any = gzip.open if f.lower().endswith(".gz") else open
        with opener(p, "rb") as fh:
            if SNOMED_URI in fh.read():
                out.append(f"{f}: names the SNOMED CT system (row snomed-ct: v1 ships none)")
    return out


# ------------------------------------------------------------------------------------------------ the check
def row_problems(rows: list[Row]) -> list[str]:
    out = []
    seen: set[str] = set()
    for r in rows:
        where = f"register row {r.id or '(no id)'}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", r.id):
            out.append(f"{where}: id must be lower case letters, digits, dots and dashes")
        if r.id in seen:
            out.append(f"{where}: id twice")
        seen.add(r.id)
        if r.kind not in KINDS:
            out.append(f"{where}: kind {r.kind!r} not one of {', '.join(sorted(KINDS))}")
        if r.status not in STATUSES:
            out.append(f"{where}: status {r.status!r} not one of {', '.join(sorted(STATUSES))}")
        for col in ("standard", "source", "licence", "obligation", "holder", "checked", "evidence"):
            if not r.raw[col]:
                out.append(f"{where}: {col} is empty")
        if r.raw["checked"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.raw["checked"]):
            out.append(f"{where}: checked must be a date (YYYY-MM-DD)")
        if r.paths and (r.status in SHIPS_NOTHING or r.kind in ("model", "software")):
            out.append(f"{where}: a {r.kind} row with status {r.status} ships no file, yet names paths")
        sha = r.raw["text_sha256"]
        if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
            out.append(f"{where}: text_sha256 is not a sha256")
    return out


def file_problems(rows: list[Row], files: list[str]) -> list[str]:
    patterns = [(r.id, p) for r in rows for p in r.paths]
    out = [f"{f}: shipped data file with no row in docs/licences/register.csv"
           for f in files if not any(_matches(p, f) for _, p in patterns)]  # fmt: skip
    out += [f"register row {rid}: pattern {p!r} matches no shipped data file"
            for rid, p in patterns if not any(_matches(p, f) for f in files)]  # fmt: skip
    return out


def model_problems(rows: list[Row], builds: list[dict[str, Any]]) -> list[str]:
    by_id = {r.id: r for r in rows}
    out = []
    for b in builds:
        bid, lic = b.get("build_id"), dict(b.get("licence") or {})
        if lic.get("verified") is not True:
            if b.get("status") in PAST_CANDIDATE:
                out.append(f"build {bid}: status {b.get('status')} with an unverified licence (stays candidate)")
            continue
        reg = lic.get("register")
        row = by_id.get(str(reg)) if reg else None
        if row is None:
            out.append(f"build {bid}: licence verified without a register row (licence.register)")
            continue
        if row.kind != "model":
            out.append(f"build {bid}: register row {row.id} is not a model row")
        if row.source != str(b.get("repository") or ""):
            out.append(f"build {bid}: repository {b.get('repository')!r} is not row {row.id}'s source {row.source!r}")
        if row.spdx != str(lic.get("spdx") or ""):
            out.append(f"build {bid}: spdx {lic.get('spdx')!r} is not row {row.id}'s {row.spdx!r}")
        if row.status not in MODEL_OK:
            out.append(f"build {bid}: register row {row.id} has status {row.status}, not cleared")
    return out


def software_problems(rows: list[Row], image: str) -> list[str]:
    """A software row against its pin in the image's Dockerfile: the version, and each architecture's sha256."""
    out = []
    for r in rows:
        if r.kind != "software":
            continue
        name = r.id.upper().replace("-", "_").replace(".", "_")
        version = re.search(rf"^ARG {name}_VERSION=(\S+)$", image, re.M)
        if version is None:
            out.append(f"register row {r.id}: the image has no ARG {name}_VERSION")
        elif version.group(1) != r.raw["version"]:
            pinned = f"{name}_VERSION={version.group(1)}"
            out.append(f"register row {r.id}: version {r.raw['version']!r}, the image pins {pinned}")
        sums = re.findall(rf"^ARG ({name}_SHA256_[A-Z0-9]+)=(\S+)$", image, re.M)
        if not sums:
            out.append(f"register row {r.id}: the image has no ARG {name}_SHA256_<ARCH>")
        out += [f"register row {r.id}: {arg}={sha} is not in the row's evidence" for arg, sha in sums
                if sha not in r.raw["evidence"]]  # fmt: skip
    return out


def athena_problems(rows: list[Row]) -> list[str]:
    try:
        from omop.vocab_load import ATHENA_ALLOW
    except (ImportError, AttributeError):  # the Athena loader (PR #145) is not on this tree
        return []
    covered = {v for r in rows for v in r.athena}
    return [f"Athena vocabulary {v!r} is allowed by the loader but has no register row (column athena)"
            for v in sorted(set(ATHENA_ALLOW) - covered)]  # fmt: skip


# ------------------------------------------------------------------------------------------------ evaluation data
# Card 10H-1 (review 20, finding 1): each data set of eval/DATASETS.yaml names its register rows (``register:``), and
# the licence it states must carry each row's licence; a file that holds SIGIR 2016 note text (CC BY-SA 4.0, CSIRO)
# must never be called "public domain". NCBI's own "public domain notice" (the criterion labels) is the one allowed
# use of the words beside SIGIR material.
DATASETS = "eval/DATASETS.yaml"
SIGIR_ROW = "pubacc-sigir-2016"
SIGIR_NOTES = "eval/criterion_ml"  # notes_en.json and its ja, zh-TW and mixed translations
#: the words a data set's stated licence must contain for a row of that SPDX id
SPDX_WORDS = {
    "CC-BY-SA-4.0": "CC BY-SA 4.0",
    "CC-BY-4.0": "CC BY 4.0",
    "ODbL-1.0": "ODbL 1.0",
    "Apache-2.0": "Apache",
    "LicenseRef-US-Public-Domain": "public domain",
    "LicenseRef-ClinicalTrials.gov-Terms": "ClinicalTrials.gov",
    "LicenseRef-NIST-TREC-no-terms": "NIST",
    "LicenseRef-OGDL-Taiwan-1.0": "Open Government Data License",
    "LicenseRef-PDL-1.0-Japan": "Public Data License 1.0",
}
# "public domain", in any spelling ("public-domain", "public_domain", "Public Domain")
PUBLIC_DOMAIN = re.compile(r"public[\s_-]*domain", re.I)
# "public domain notice" names NCBI's notice; "license_name: public-domain" quotes NCBI's dataset card
BARE_PUBLIC_DOMAIN = re.compile(r"(?<!license_name: )public[\s_-]*domain(?![\s_-]*notice)", re.I)
#: words that put a line about the SIGIR notes (or their adaptations) in context
SIGIR_SUBJECT = re.compile(
    r"sigir|criterion_ml|notes_(?:en|ja|zh-TW|mixed)|patient (?:notes|descriptions)|renderings|translations", re.I
)
SUBJECT_WORDS = (
    "sigir",
    "criterion_ml",
    "notes_",
    "patient notes",
    "patient descriptions",
    "renderings",
    "translations",
)
#: words that say the public domain notice is about NCBI's labels, not the notes
NCBI_LABELS = re.compile(r"label|annotation|LICENSE\.NCBI|NCBI code|the code|corpora", re.I)
SPDX_PD = re.compile(r"LicenseRef-US-Public-Domain")
#: the sentence NCBI's benchmark appends to every note: NCBI's text, not CSIRO's (the same index in the translations)
NCBI_ADDED = "The patient will provide informed consent, and will comply with the trial protocol"
#: text files that can hold note text or state a licence; a .gz is read decompressed
TEXT = (".json", ".jsonl", ".jsonl.gz", ".json.gz", ".ndjson", ".md", ".csv", ".tsv", ".txt", ".yaml", ".yml", ".py",
        ".html", ".xml", ".toml", ".sh")  # fmt: skip
LICENCE_FILES = ("README.md", "NOTICE.md", "PROVENANCE.md")
DATA_DOC_ROOTS = ("eval", "tests/fixtures")  # where data sets and their READMEs live
#: records that quote the old labels as history (reviews, hand-overs, decisions); not labels of the data
RECORDS = (
    "docs/reviews/",
    "docs/handover/",
    "docs/decisions/",
    "docs/DECISIONS.md",
    "CHANGELOG.md",
    "docs/plan/measurements/eval-licence-labels-2026-11-18.md",
)  # H-37's before-and-after table
#: the check and its tests, which must spell out the words they look for
CHECK_FILES = (
    "tools/licence_register.py",
    "tests/unit/test_eval_licence_labels.py",
    "tests/unit/test_sigir_notes_licence.py",
)
SKIP_SCAN = frozenset({"build", "dist", "data"})  # local outputs and the box's data folder (.dockerignore'd)


def dataset_problems(root: Path, rows: list[Row]) -> list[str]:
    """Each eval/DATASETS.yaml entry against its register rows: an open data set names at least one row, every row
    named exists and its licence words are in the entry's licence, "public domain" needs a row that says so, and an
    entry naming SIGIR names row pubacc-sigir-2016 and calls nothing about it plain public domain."""
    f = root / DATASETS
    if not f.is_file():
        return []
    by_id = {r.id: r for r in rows}
    out = []
    for key, d in ((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("datasets") or {}).items():
        where = f"{DATASETS} {key}"
        licence, regs = str(d.get("licence") or ""), [str(x) for x in d.get("register") or []]
        if d.get("kind") == "open" and not regs:
            out.append(f"{where}: an open data set names no register row (register:)")
        named = [by_id[r] for r in regs if r in by_id]
        out += [f"{where}: register row {r} does not exist" for r in regs if r not in by_id]
        for r in named:
            words = SPDX_WORDS.get(r.spdx)
            if words is None:
                out.append(f"{where}: register row {r.id} has SPDX id {r.spdx!r}, which has no words in SPDX_WORDS")
            elif words.lower() not in licence.lower():
                out.append(f"{where}: licence does not say {words!r}, as register row {r.id} ({r.spdx}) does")
        if PUBLIC_DOMAIN.search(licence) and not any(PUBLIC_DOMAIN.search(r.raw["licence"]) for r in named):
            out.append(f"{where}: says public domain, but no register row it names does")
        if "sigir" in licence.lower() or SIGIR_ROW in regs:
            if SIGIR_ROW not in regs:
                out.append(f"{where}: names SIGIR material but not register row {SIGIR_ROW}")
            if BARE_PUBLIC_DOMAIN.search(licence):
                out.append(f"{where}: calls SIGIR-derived material public domain (CC BY-SA 4.0, CSIRO)")
    return out


def _read_text(p: Path) -> str:
    try:
        raw = p.read_bytes()
        if p.name.endswith(".gz"):
            raw = gzip.decompress(raw)
    except (OSError, EOFError, gzip.BadGzipFile):
        return ""
    return raw.decode("utf-8", errors="replace")


def sigir_probes(root: Path) -> dict[str, str]:
    """The opening characters of the SIGIR notes' sentences (English 40, the three translations 15), each with its
    whole sentence, without the consent sentence NCBI's benchmark appended to every note (and its translations)."""
    en_file = root / SIGIR_NOTES / "notes_en.json"
    if not en_file.is_file():
        return {}
    en = json.loads(en_file.read_text(encoding="utf-8"))
    added = {(k, i) for k, ss in en.items() for i, s in enumerate(ss) if str(s).startswith(NCBI_ADDED)}
    out: dict[str, str] = {}
    for lang, n in (("en", 40), ("ja", 15), ("zh-TW", 15), ("mixed", 15)):
        p = root / SIGIR_NOTES / f"notes_{lang}.json"
        if p.is_file():
            for k, sentences in json.loads(p.read_text(encoding="utf-8")).items():
                out.update((s[:n], s) for i, s in enumerate(sentences)
                           if (k, i) not in added and isinstance(s, str) and len(s) >= n + 5)  # fmt: skip
    return out


def _text_files(root: Path) -> Iterable[tuple[str, str]]:
    stack = [root]
    while stack:
        here = stack.pop()
        for p in sorted(here.iterdir()):
            if p.name in SKIP_DIRS or (p.is_dir() and (p.name.startswith(".") or p.name in SKIP_SCAN)):
                continue
            if p.is_dir() and not p.is_symlink():
                stack.append(p)
            elif p.is_file() and p.name.lower().endswith(TEXT):
                yield p.relative_to(root).as_posix(), _read_text(p)


_SCANS: dict[str, tuple[list[str], list[str]]] = {}


def _scan(root: Path) -> tuple[list[str], list[str]]:
    """(the files that hold SIGIR note text, the problems of their labels): one read of every text file. The
    repository's own scan is kept for the process (the tests call the check several times)."""
    if root == ROOT and str(root) in _SCANS:
        return _SCANS[str(root)]
    probes = sigir_probes(root)
    texts = dict(_text_files(root)) if probes else {}
    prints = _fingerprints(probes)
    files = sorted(f for f, t in texts.items() if _holds(t, prints))
    out = [f"{f}: {line}" for f, t in sorted(texts.items()) if not f.startswith(RECORDS) and f not in CHECK_FILES
           for line in _public_domain_lines(t)]  # fmt: skip
    for f in files:
        if not _attributed(root, f, texts.get(f, "")):
            out.append(f"{f}: holds SIGIR 2016 note text without its attribution (CC BY-SA 4.0, CSIRO), in the "
                       "file or in a README.md or NOTICE.md of its folder")  # fmt: skip
    result = (files, out)
    if root == ROOT:
        _SCANS[str(root)] = result
    return result


WORD = re.compile(r"[A-Za-z]{4,}")


def _fingerprints(probes: dict[str, str]) -> list[tuple[bool, frozenset[str], str]]:
    """Each probe with the words (English, the first 70 characters) or characters (translations, the first 30) of its
    sentence that a text must hold before the probe is looked for: a quote of the sentence's opening holds them."""
    return [(p.isascii(), frozenset(WORD.findall(s[:70].rsplit(" ", 1)[0])) if p.isascii() else frozenset(s[:30]), p)
            for p, s in sorted(probes.items())]  # fmt: skip


def _holds(text: str, prints: list[tuple[bool, frozenset[str], str]]) -> bool:
    """Does the text hold one of the probes? A probe is looked for only when its words or characters are all in the
    text, which keeps the scan of the whole tree to seconds."""
    words: set[str] | None = None
    chars: set[str] | None = None
    for ascii_, need, p in prints:
        if ascii_:
            words = set(WORD.findall(text)) if words is None else words
            if not need <= words:
                continue
        else:
            chars = set(text) if chars is None else chars
            if not need <= chars:
                continue
        if p in text:
            return True
    return False


def _public_domain_lines(text: str) -> list[str]:
    """Lines that call the SIGIR notes (or their adaptations) public domain: a "public domain" line whose paragraph
    (two lines either side) is about the notes. Plain "public domain" passes only on a line that also says CC BY-SA;
    NCBI's "public domain notice" passes only on a line that names the labels, LICENSE.NCBI or NCBI's code or
    corpora, and whose clause does not put it on the notes. The SPDX id LicenseRef-US-Public-Domain is not a claim
    about the notes."""
    low = text.lower()  # cheap tests first: most files name neither
    if "domain" not in low or not any(k in low for k in SUBJECT_WORDS):
        return []
    lines = [SPDX_PD.sub("", x) for x in text.splitlines()]
    out = []
    for i, line in enumerate(lines):
        if not PUBLIC_DOMAIN.search(line):
            continue
        lo, hi = i, i
        while lo > 0 and i - lo < 2 and lines[lo - 1].strip():
            lo -= 1
        while hi < len(lines) - 1 and hi - i < 2 and lines[hi + 1].strip():
            hi += 1
        window = "\n".join(lines[lo : hi + 1])
        if not PUBLIC_DOMAIN.search(line) or not SIGIR_SUBJECT.search(window):
            continue
        if "cc by-sa" in line.lower() or "license_name: public-domain" in line:
            continue
        if not BARE_PUBLIC_DOMAIN.search(line) and NCBI_LABELS.search(line) and not _notice_on_notes(line):
            continue
        out.append(f"line {i + 1} calls SIGIR 2016 material public domain (CC BY-SA 4.0, CSIRO): {line.strip()[:80]}")
    return out


NOTES_WORDS = re.compile(r"sigir|notes?\b|descriptions|translations|renderings|cohort", re.I)


def _notice_on_notes(line: str) -> bool:
    """Does the clause before a "public domain notice" put the notice on the notes ("the SIGIR notes carry NCBI's
    public domain notice")? The clause runs back to the last ;, ., | or (."""
    m = PUBLIC_DOMAIN.search(line)
    head = line[: m.start()] if m else ""
    clause = re.split(r"[;.|(]", head)[-1]
    return bool(NOTES_WORDS.search(clause))


def _attributed(root: Path, f: str, text: str) -> bool:
    def says(t: str) -> bool:
        return "cc by-sa" in t.lower() and ("csiro" in t.lower() or "koopman" in t.lower())

    if says(text):
        return True
    parts = f.split("/")[:-1]
    return any(says(_read_text(root / Path(*parts[:i], name)))
               for i in range(len(parts), 0, -1) for name in LICENCE_FILES)  # fmt: skip


def sigir_derived_files(root: Path = ROOT) -> list[str]:
    """Every text file outside .cache that holds a sentence of the SIGIR notes (en, ja, zh-TW or mixed)."""
    return _scan(root)[0]


def sigir_problems(root: Path = ROOT) -> list[str]:
    """No text file calls the SIGIR notes or their adaptations public domain (records under RECORDS excepted); every
    file holding their text carries the attribution; every README, NOTICE.md or PROVENANCE.md under eval/ or
    tests/fixtures/ that names SIGIR says CC BY-SA 4.0."""
    out = list(_scan(root)[1])
    for top in DATA_DOC_ROOTS:
        for p in sorted((root / top).rglob("*")) if (root / top).is_dir() else []:
            if p.name in LICENCE_FILES:
                text = _read_text(p).lower()
                if "sigir" in text and "cc by-sa 4.0" not in text:
                    out.append(f"{p.relative_to(root).as_posix()}: names SIGIR 2016 but not its licence, CC BY-SA 4.0")
    return out


def dataset_file_problems(root: Path, files: list[str]) -> list[str]:
    """A file under eval/ or tests/fixtures/ that holds SIGIR note text lies in a data set of eval/DATASETS.yaml
    (the first word of its ``path``) that names register row pubacc-sigir-2016."""
    f = root / DATASETS
    if not f.is_file():
        return []
    entries = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("datasets") or {}
    covered = [str(d.get("path") or "").split(" ")[0].rstrip("/") + "/" for d in entries.values()
               if SIGIR_ROW in (d.get("register") or [])]  # fmt: skip
    return [f"{x}: holds SIGIR 2016 note text but no eval/DATASETS.yaml entry naming {SIGIR_ROW} covers it"
            for x in files if x.startswith(tuple(f"{t}/" for t in DATA_DOC_ROOTS))
            and not any(x.startswith(c) for c in covered)]  # fmt: skip


def check(root: Path = ROOT, register: Path | None = None, models: Path | None = None) -> list[str]:
    rows = load(register or root / "docs/licences/register.csv")
    files = shipped_data_files(root)
    out = row_problems(rows) + file_problems(rows, files) + snomed_problems(root, files)
    out += dataset_problems(root, rows) + sigir_problems(root)
    out += dataset_file_problems(root, sigir_derived_files(root))
    mfile = models or root / "models/registry.yaml"
    if mfile.is_file():
        out += model_problems(rows, list((yaml.safe_load(mfile.read_text(encoding="utf-8")) or {}).get("builds") or []))
    image = root / IMAGE.relative_to(ROOT)
    if image.is_file():
        out += software_problems(rows, image.read_text(encoding="utf-8"))
    return out + athena_problems(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.licence_register", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail on a shipped data file with no row, and the rest")
    args = ap.parse_args(argv)
    if args.check:
        problems = check()
        for p in problems:
            print(p, file=sys.stderr)
        n = len(shipped_data_files())
        print(f"licence register: {len(load())} rows, {n} shipped data files, {len(problems)} problems")
        return 1 if problems else 0
    for r in load():
        print(f"{r.id:32} {r.status:18} {r.raw['licence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
