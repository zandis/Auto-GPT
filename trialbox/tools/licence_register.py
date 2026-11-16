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
  ``deploy/docker/python.Dockerfile``: ``ARG <ID>_VERSION`` must be the row's version and every
  ``ARG <ID>_SHA256_<ARCH>`` must be written in the row's evidence. A software row ships no path of its own.

The rows are rendered by hand into ``NOTICE`` (T-617a); the register is the data behind it.
"""

from __future__ import annotations

import argparse
import csv
import gzip
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
IMAGE = ROOT / "deploy/docker/python.Dockerfile"  # where a software row's tool is pinned (D-968)
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


def check(root: Path = ROOT, register: Path | None = None, models: Path | None = None) -> list[str]:
    rows = load(register or root / "docs/licences/register.csv")
    files = shipped_data_files(root)
    out = row_problems(rows) + file_problems(rows, files) + snomed_problems(root, files)
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
