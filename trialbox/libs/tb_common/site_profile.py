"""A site profile: one hospital's habits as data (10B-6, commitment C-6, D-1233; design: docs/data/site-profile.md).

A profile is one folder::

    profile.yaml        the manifest (schemas/site_profile.schema.json): id, site, country, version, the door and the
                        standard versions it targets, the data types the site stores, its code tables
    codes/<name>.csv    a code table: the site's own code, the standard code, and a state on every row

:func:`load` is the one way the product gets a profile. It refuses, naming the file, the line and the reason:

* a manifest that does not match the schema, an unknown key included (``additionalProperties: false``);
* a table whose file is missing, outside the profile folder, or lacks its key, target or state column;
* a row with an empty or repeated key, an empty target, or a state that is not one of :data:`STATE_WORDS`;
* a column that would hold patient data (:data:`PATIENT_COLUMNS`): a profile holds codes, never a patient.

**The state of a row.** Every row is ``verified`` (a person checked the standard code against its release) or
``verify`` (not yet: a sample, a suggestion, a row nobody checked). The legacy words of the shipped tables read as
:data:`STATE_WORDS` says: ``yes`` and ``confirmed`` are ``verified``; ``local`` (a TrialBox-local score code with no
standard behind it) reads as ``verify``, the safe side. :meth:`Table.find` returns the row with its state, so a value
taken from a profile carries it to wherever it is shown; the work list lists every ``verify`` row.

**Shipped tables.** A synthetic profile in the repository may name a table already shipped in the image's mapping
folder (``file: shipped:jp_core/byomei_to_icd10.csv``) instead of a copy, so a code is written in one place only.
A site's own profile keeps its tables in ``codes/``.

**The digest** is the SHA-256 of the manifest and of every table's bytes, in table-name order: two profiles with
the same digest read every code alike. The version is the steward's; the digest is what the night records.

Standard library, PyYAML and jsonschema only (both in ``uv.lock``); imports under Python 3.10.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FORMAT = "tb-site-profile/1"
MANIFEST = "profile.yaml"
VERIFIED = "verified"
VERIFY = "verify"
STATES = (VERIFIED, VERIFY)
#: the words a table's state column may hold, and the state each reads as (the shipped tables' legacy words included)
STATE_WORDS = {"verified": VERIFIED, "yes": VERIFIED, "confirmed": VERIFIED, "verify": VERIFY, "local": VERIFY}
DEFAULT_STATE_COLUMN = "state"
SHIPPED = "shipped:"
#: the image's mapping folder: what ``shipped:<path>`` is relative to (beside libs/ in the tree and in every image)
SHIPPED_ROOT = Path(__file__).resolve().parents[2] / "services" / "adapter" / "mapping"
#: column names a code table must never have: a profile is codes, never a patient (lower case, after trimming;
#: ``name`` is allowed: in a code table it is the code's own name)
PATIENT_COLUMNS = frozenset(
    {"mrn", "chart_no", "chart_number", "patient", "patient_id", "pid", "patient_name", "kana_name", "birth_date",
     "birthdate", "dob", "address", "phone", "id_no", "national_id", "insurance_no"}
)  # fmt: skip
#: the SS-MIX2 reader reads its tables by these columns (key, target): a profile table it reads must use them
READER_COLUMNS = {"ssmix2.diagnosis": ("code", "icd10"), "ssmix2.drug": ("yj_code", "atc"),
                  "ssmix2.lab": ("local_code", "code")}  # fmt: skip
_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
MAX_ROWS = 200_000  # a code table larger than any hospital master: a wrong file, refused before it fills memory


class ProfileError(ValueError):
    """A profile that cannot be used: ``where`` is ``<file>`` or ``<file>:<line>``, ``why`` the reason in words."""

    def __init__(self, where: str, why: str) -> None:
        super().__init__(f"{where}: {why}")
        self.where = where
        self.why = why


@dataclass(frozen=True)
class CodeRow:
    """One row of a code table: the site's code, the standard code it maps to, its state, and the row as written."""

    code: str
    target: str
    state: str
    line: int
    row: dict[str, str] = field(compare=False, repr=False)

    @property
    def verified(self) -> bool:
        return self.state == VERIFIED


@dataclass(frozen=True)
class Table:
    name: str
    file: str  # as the manifest writes it
    path: Path
    key: str
    target: str
    state_column: str
    source: str
    used_by: tuple[str, ...]
    rows: dict[str, CodeRow]

    def find(self, code: object) -> CodeRow | None:
        """The row of a site code, with its state; None when the table has no such code."""
        return self.rows.get("" if code is None else str(code).strip())

    def states(self) -> dict[str, int]:
        out = dict.fromkeys(STATES, 0)
        for r in self.rows.values():
            out[r.state] += 1
        return out


@dataclass(frozen=True)
class Profile:
    folder: Path
    id: str
    site_id: str
    country: str
    version: str
    door: str
    synthetic: bool
    standards: dict[str, str]
    data_types: tuple[str, ...]
    tables: dict[str, Table]
    digest: str

    def used_by(self, use: str) -> Table | None:
        """The table the product reads at ``use`` (``mapping.lab``, ``ssmix2.diagnosis``), or None."""
        return next((t for t in self.tables.values() if use in t.used_by), None)

    def stamp(self) -> dict[str, str]:
        """What a night records of the profile it read with (``site_profile.json`` beside the snapshot)."""
        return {"id": self.id, "site_id": self.site_id, "version": self.version, "digest": self.digest}

    def verify_rows(self) -> Iterator[tuple[Table, CodeRow]]:
        for name in sorted(self.tables):
            t = self.tables[name]
            for code in sorted(t.rows):
                if t.rows[code].state == VERIFY:
                    yield t, t.rows[code]


def _schema() -> dict[str, Any]:
    base = Path(os.environ.get("TB_SCHEMAS_DIR") or Path(__file__).resolve().parents[2] / "schemas")
    data: dict[str, Any] = json.loads((base / "site_profile.schema.json").read_text(encoding="utf-8"))
    return data


def _line_of(text: str, path: list[Any]) -> int | None:
    """The 1-based line of the manifest node at ``path`` (keys and list indices), or of its nearest parent."""
    try:
        node: Any = yaml.compose(text)
    except yaml.YAMLError:
        return None
    line = node.start_mark.line + 1 if node is not None else None
    for step in path:
        if isinstance(node, yaml.MappingNode):
            hit = next(((k, v) for k, v in node.value if k.value == step), None)
            if hit is None:
                break
            line, node = hit[0].start_mark.line + 1, hit[1]
        elif isinstance(node, yaml.SequenceNode) and isinstance(step, int) and step < len(node.value):
            node = node.value[step]
            line = node.start_mark.line + 1
        else:
            break
    return line


def _unknown_key_line(text: str, path: list[Any], message: str) -> int | None:
    """For an ``additionalProperties`` error: the line of the first key the message names."""
    names = re.findall(r"'([^']+)'", message)
    for n in names:
        line = _line_of(text, [*path, n])
        if line is not None and line != _line_of(text, path):
            return line
    return _line_of(text, path)


def check_manifest(doc: Any, text: str, where: str) -> None:
    """Refuse a manifest that does not match the schema; the first error by line, with its reason."""
    from jsonschema import Draft202012Validator

    errors = sorted(Draft202012Validator(_schema()).iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))
    if not errors:
        return
    e = errors[0]
    path = list(e.absolute_path)
    if e.validator == "additionalProperties":
        line = _unknown_key_line(text, path, e.message)
        why = f"unknown key ({e.message})"
    else:
        line = _line_of(text, path)
        at = ".".join(str(p) for p in path) or "the manifest"
        why = f"{at}: {e.message}"
    raise ProfileError(f"{where}:{line}" if line else where, why)


def _table_path(folder: Path, file: str, where: str) -> Path:
    if file.startswith(SHIPPED):
        rel = Path(file[len(SHIPPED) :])
        root = SHIPPED_ROOT.resolve()
    else:
        rel, root = Path(file), folder.resolve()
    if rel.is_absolute() or ".." in rel.parts:
        raise ProfileError(where, f"{file}: a table stays inside its folder (no absolute path, no ..)")
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ProfileError(where, f"{file}: a table stays inside its folder") from None
    if not path.is_file():
        raise ProfileError(where, f"{file}: no such table file")
    return path


def read_table(name: str, spec: dict[str, Any], folder: Path, where: str) -> tuple[Table, bytes]:
    """One code table, every row checked; the bytes are returned for the digest."""
    path = _table_path(folder, str(spec["file"]), where)
    data = path.read_bytes()
    shown = spec["file"]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProfileError(shown, "a code table is UTF-8 text") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = [c.strip() for c in reader.fieldnames or []]
    key, target = str(spec["key"]), str(spec["target"])
    state_col = str(spec.get("state") or DEFAULT_STATE_COLUMN)
    for col in (key, target, state_col):
        if col not in cols:
            raise ProfileError(f"{shown}:1", f"no column {col!r} (the header has {', '.join(cols) or 'nothing'})")
    patient = sorted(c for c in cols if c.lower() in PATIENT_COLUMNS)
    if patient:
        raise ProfileError(f"{shown}:1", f"column {patient[0]!r} would hold patient data: a profile holds codes only")
    rows: dict[str, CodeRow] = {}
    for n, r in enumerate(reader, start=2):
        if n > MAX_ROWS + 1:
            raise ProfileError(shown, f"more than {MAX_ROWS} rows: not a code table")
        if None in r:
            raise ProfileError(f"{shown}:{n}", "more cells than the header has columns")
        code = (r.get(key) or "").strip()
        tgt = (r.get(target) or "").strip()
        word = (r.get(state_col) or "").strip().lower()
        if not code:
            raise ProfileError(f"{shown}:{n}", f"the {key} cell is empty")
        if code in rows:
            raise ProfileError(f"{shown}:{n}", f"{key} {code!r} is already on line {rows[code].line}")
        if not tgt:
            raise ProfileError(f"{shown}:{n}", f"the {target} cell is empty: a code nobody mapped is not a row")
        if word not in STATE_WORDS:
            raise ProfileError(
                f"{shown}:{n}", f"state {word!r} is not one of {', '.join(sorted(STATE_WORDS))} (verified or verify)"
            )
        rows[code] = CodeRow(code, tgt, STATE_WORDS[word], n, {k: (v or "") for k, v in r.items() if k is not None})
    table = Table(name, str(spec["file"]), path, key, target, state_col, str(spec.get("source") or ""),
                  tuple(spec["used_by"]), rows)  # fmt: skip
    return table, data


def load(folder: Path | str) -> Profile:
    """The profile in ``folder`` (its ``profile.yaml``), every table read and checked. :class:`ProfileError` names
    the file, the line and the reason of the first problem found."""
    folder = Path(folder)
    manifest = folder / MANIFEST
    where = str(MANIFEST)
    try:
        raw = manifest.read_bytes()
    except FileNotFoundError:
        raise ProfileError(str(manifest), "no profile manifest here") from None
    try:
        text = raw.decode("utf-8")
        doc = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        mark = getattr(exc, "problem_mark", None)
        at = f"{where}:{mark.line + 1}" if mark else where
        raise ProfileError(at, f"not readable YAML ({type(exc).__name__})") from None
    if not isinstance(doc, dict):
        raise ProfileError(where, "the manifest is a mapping of keys (format, id, site_id, ...)")
    check_manifest(doc, text, where)
    for part in ("standards", "tables"):
        bad = sorted(k for k in doc[part] if not (isinstance(k, str) and _NAME.fullmatch(k)))
        if bad:
            line = _line_of(text, [part, bad[0]])
            raise ProfileError(f"{where}:{line}", f"{part}: {bad[0]!r} is not a name (a-z, 0-9 and _)")
    if not doc.get("synthetic") and any(str(t["file"]).startswith(SHIPPED) for t in doc["tables"].values()):
        raise ProfileError(where, "only a synthetic profile may name a shipped table: a site's tables are in codes/")
    if str(doc["id"]).startswith("synthetic-") != bool(doc.get("synthetic")):
        raise ProfileError(where, "a profile is synthetic exactly when its id starts with synthetic-")
    seen: dict[str, str] = {}
    for name, spec in doc["tables"].items():
        for use in spec["used_by"]:
            if use in seen:
                raise ProfileError(f"{where}:{_line_of(text, ['tables', name])}", f"{use} is read from {seen[use]} too")
            seen[use] = name
            cols = READER_COLUMNS.get(use)
            if cols and (spec["key"], spec["target"]) != cols:
                raise ProfileError(
                    f"{where}:{_line_of(text, ['tables', name])}",
                    f"{use} reads key {cols[0]} and target {cols[1]}, not {spec['key']} and {spec['target']}",
                )
    digest = hashlib.sha256()
    digest.update(b"manifest\0" + raw)
    tables: dict[str, Table] = {}
    for name in sorted(doc["tables"]):
        t, data = read_table(name, doc["tables"][name], folder, f"{where}:{_line_of(text, ['tables', name])}")
        tables[name] = t
        digest.update(f"\0table\0{name}\0".encode() + data)
    return Profile(
        folder=folder,
        id=str(doc["id"]),
        site_id=str(doc["site_id"]),
        country=str(doc["country"]),
        version=str(doc["version"]),
        door=str(doc["door"]),
        synthetic=bool(doc.get("synthetic")),
        standards={str(k): str(v) for k, v in doc["standards"].items()},
        data_types=tuple(doc["data_types"]),
        tables=tables,
        digest=digest.hexdigest(),
    )


def state_of(word: object) -> str:
    """The state a table's state cell reads as; an empty or unknown word is ``verify`` (never shown as verified)."""
    return STATE_WORDS.get(str(word or "").strip().lower(), VERIFY)
