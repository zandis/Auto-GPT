"""No must-not-ship vocabulary reaches a bundle (card 22-4, root review 22; the guard of plan 10's 9h-13).

    python -m tools.vocab_bundle_check                     # the shipped data files of this tree (CI job `checks`)
    python -m tools.vocab_bundle_check --tree DIR FILE...  # also these folders or files (make_bundle.sh: --rulesets)

It reads the terminology artefacts a bundle carries: tables (CSV, TSV, text, gzipped CSV, Parquet), mapping files and
value sets (FHIR JSON, any JSON), and attributes each row to a vocabulary by

* a column named ``vocabulary_id`` or ending in ``vocabulary_id`` / ``_vocabulary`` (the OMOP shape a table derived
  from an Athena download carries: ``concept``, ``source_to_concept_map``, a candidate table), whose value is an
  Athena vocabulary id;
* a column named ``system`` or ending in ``_system``, or a JSON key ``system``, ``source``, ``target``,
  ``sourceUri``, ``targetUri``, ``sourceSystem`` or ``targetSystem``, whose value is a code system URI: the URI's
  register row is read from ``tools.codemap_release.SYSTEM_REGISTER`` (the systems the box knows).

The build fails, naming the file, the vocabulary and the register row, when any row is attributed to a vocabulary the
licence register classes ``c`` (must not ship): one named in a row's ``athena_never`` column
(``omop.vocab_load.athena_register``), or a URI whose register row is of class ``c``. The register is the one source:
this tool holds no list of its own. A mapping whose source or target is such a vocabulary fails the same way.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omop.vocab_load import REGISTER, athena_register  # noqa: E402

from tools import licence_register as lr  # noqa: E402
from tools.codemap_release import SYSTEM_REGISTER  # noqa: E402

TABULAR = (".csv", ".tsv", ".txt", ".csv.gz", ".tsv.gz", ".parquet")
JSON = (".json", ".ndjson")
JSON_SYSTEM_KEYS = frozenset({"system", "source", "target", "sourceUri", "targetUri", "sourceSystem", "targetSystem"})


@dataclass(frozen=True)
class Forbidden:
    """The must-not-ship vocabularies, by Athena id and by code-system URI, each with its register row."""

    ids: dict[str, str]  # Athena vocabulary_id -> register row
    uris: dict[str, str]  # code system URI -> register row


def forbidden(register: Path = REGISTER) -> Forbidden:
    ids = {v: c.row for v, c in athena_register(register).items() if not c.loadable}
    c_rows = {r.id for r in lr.load(register) if r.klass == lr.MUST_NOT_SHIP}
    return Forbidden(ids, {u: row for u, row in SYSTEM_REGISTER.items() if row in c_rows})


def _vocab_column(name: str) -> bool:
    n = name.strip().lower()
    return n == "vocabulary_id" or n.endswith("vocabulary_id") or n.endswith("_vocabulary") or n == "vocabulary"


def _system_column(name: str) -> bool:
    n = name.strip().lower()
    return n == "system" or n.endswith("_system") or n in ("sourceuri", "targeturi")


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    name = path.name.lower()
    if name.endswith(".parquet"):
        import pyarrow.parquet as pq

        cols = [c for c in pq.read_schema(path).names if _vocab_column(c) or _system_column(c)]
        if cols:
            yield from pq.read_table(path, columns=cols).to_pylist()
        return
    opener: Any = gzip.open if name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        text = fh.read()
    head = text.split("\n", 1)[0]
    delim = "\t" if "\t" in head and head.count("\t") >= head.count(",") else ","
    yield from csv.DictReader(io.StringIO(text), delimiter=delim)


def _json_values(node: Any) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and (k in JSON_SYSTEM_KEYS or _vocab_column(k)):
                yield k, v
            else:
                yield from _json_values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _json_values(v)


def _json_docs(path: Path) -> Iterator[Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.name.lower().endswith(".ndjson"):
        for line in text.splitlines():
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
        return
    try:
        yield json.loads(text)
    except ValueError:
        return


def inspect(path: Path, bad: Forbidden) -> dict[tuple[str, str], int]:
    """``(vocabulary or URI, register row) -> rows`` of one artefact attributed to a must-not-ship vocabulary."""
    hits: dict[tuple[str, str], int] = {}

    def hit(value: Any, by_id: bool) -> None:
        v = str(value or "").strip()
        row = (bad.ids if by_id else bad.uris).get(v)
        if row is None and not by_id:
            row = bad.ids.get(v)  # a system column holding an Athena id
        if row is not None:
            hits[(v, row)] = hits.get((v, row), 0) + 1

    name = path.name.lower()
    if name.endswith(JSON):
        for doc in _json_docs(path):
            for k, v in _json_values(doc):
                hit(v, _vocab_column(k))
        return hits
    if name.endswith(TABULAR):
        for r in _rows(path):
            for k, v in r.items():
                if k is None:
                    continue
                if _vocab_column(k):
                    hit(v, True)
                elif _system_column(k):
                    hit(v, False)
    return hits


def artefacts(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.is_file() and f.name.lower().endswith((*TABULAR, *JSON)))
        elif p.is_file():
            out.append(p)
    return out


def check(paths: Iterable[Path], register: Path = REGISTER) -> list[str]:
    bad = forbidden(register)
    out = []
    for f in artefacts(paths):
        for (vocab, row), n in sorted(inspect(f, bad).items()):
            out.append(f"{f}: {n} row(s) of vocabulary {vocab!r}, licence class c, must not ship (register row {row})")
    return out


def tree_artefacts(root: Path = ROOT) -> list[Path]:
    """The shipped data files of the tree (``tools.licence_register.shipped_data_files``)."""
    return [root / f for f in lr.shipped_data_files(root)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.vocab_bundle_check", description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", type=Path, help="further folders or files going into the bundle")
    ap.add_argument("--tree", action="store_true", help="also the shipped data files of this tree (the default "
                                                        "when no path is given)")  # fmt: skip
    a = ap.parse_args(argv)
    paths = list(a.paths)
    if a.tree or not paths:
        paths += tree_artefacts()
    problems = check(paths)
    for p in problems:
        print(p, file=sys.stderr)
    n = len(artefacts(paths))
    print(f"vocabulary bundle check: {n} artefacts, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
