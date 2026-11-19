"""A site profile: one hospital's habits as data (10B-6, C-6, D-1233; design: docs/data/15-the-site-profile.md).

A profile is one folder::

    profile.yaml        the manifest (site_profile.schema.json beside this module): id, site, country, version,
                        the door and the standard versions it targets, the data types the site stores, its tables
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
#: the columns a table the SS-MIX2 reader alone reads may have (its key and target, the code's name, and the shipped
#: lab table's columns), besides its state column: an allowlist, so no other column (a patient's) can ride along. A
#: table a mapping reads (``mapping.<look-up>``) is held to the mapping's own look-up columns at the night and by
#: ``adapter.site_profile check --mapping``
READER_ALLOWED = {
    "ssmix2.diagnosis": frozenset({"code", "name", "icd10"}),
    "ssmix2.drug": frozenset({"yj_code", "name", "atc"}),
    "ssmix2.lab": frozenset({"local_code", "system", "code", "display", "ucum", "factor", "category", "value_type",
                             "answers", "profile", "source_unit", "plausible_low", "plausible_high"}),
}  # fmt: skip
_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
#: what free text in a manifest (a table's ``source``, a standard's version) must not hold: an address with a scheme
#: (a database URL with its password), an ``@`` (a sign-in or mail address), or a long run of token characters (a key)
_SECRET_SHAPES = (re.compile(r"://"), re.compile(r"@"), re.compile(r"[A-Za-z0-9+/=_-]{32,}"))
MAX_ROWS = 200_000  # a code table larger than any hospital master: a wrong file, refused before it fills memory
#: the code systems a table's standard code may be in, each with the shape of its codes (ASCII only). The shapes are
#: the product's own: LOINC (with its Mod-10 check digit), the WHO ICD-10 shape site set-up accepts
#: (``sitesetup.mapping._ICD``), the full ATC level of every medication value set, and TrialBox's own score codes. A
#: system outside these is refused: the product reads no other, and the licence register says which must never ship
SYSTEM_SHAPES = {
    "loinc": re.compile(r"[0-9]{1,7}-[0-9]"),
    "icd10": re.compile(r"[A-TV-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?"),
    "atc": re.compile(r"[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}"),
    "score": re.compile(r"[A-Z0-9][A-Z0-9-]{0,31}"),
}
#: the system of a table's standard code when the table has no ``system`` column, by where it is read
SYSTEM_OF_USE = {"ssmix2.diagnosis": "icd10", "ssmix2.drug": "atc"}
REGISTER = Path(__file__).resolve().parents[2] / "docs" / "licences" / "register.csv"


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
    columns: tuple[str, ...] = ()  # the header, trimmed

    def csv_text(self) -> str:
        """The table as the night reads it: the header and every row as loaded (every cell trimmed), so a cell the
        loader read as ``2160-0`` is never read at night as `` 2160-0 ``."""
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(self.columns), lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for code in sorted(self.rows, key=lambda c: self.rows[c].line):
            w.writerow(self.rows[code].row)
        return buf.getvalue()

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

    def to_json(self) -> dict[str, Any]:
        """The profile as loaded and checked: what ``load --by`` keeps in the lake folder and the night reads."""
        return {
            "format": FORMAT, "id": self.id, "site_id": self.site_id, "country": self.country,
            "version": self.version, "door": self.door, "synthetic": self.synthetic, "standards": self.standards,
            "data_types": list(self.data_types), "digest": self.digest,
            "tables": {n: {"file": t.file, "key": t.key, "target": t.target, "state_column": t.state_column,
                           "source": t.source, "used_by": list(t.used_by), "columns": list(t.columns),
                           "rows": [{"line": r.line, "state": r.state, "row": r.row}
                                    for r in sorted(t.rows.values(), key=lambda r: r.line)]}
                       for n, t in sorted(self.tables.items())},
        }  # fmt: skip

    @classmethod
    def from_json(cls, doc: dict[str, Any], folder: Path) -> Profile:
        """A profile kept by :meth:`to_json` (already checked when it was loaded)."""
        tables = {}
        for n, t in doc["tables"].items():
            rows = {}
            for r in t["rows"]:
                cells = {str(k): str(v) for k, v in r["row"].items()}
                rows[cells[t["key"]]] = CodeRow(cells[t["key"]], cells[t["target"]], str(r["state"]), int(r["line"]),
                                                cells)  # fmt: skip
            path = folder / t["file"].replace(SHIPPED, "shipped/")
            tables[n] = Table(n, t["file"], path, t["key"], t["target"], t["state_column"], t["source"],
                              tuple(t["used_by"]), rows, tuple(t["columns"]))  # fmt: skip
        return cls(folder, doc["id"], doc["site_id"], doc["country"], doc["version"], doc["door"],
                   bool(doc["synthetic"]), dict(doc["standards"]), tuple(doc["data_types"]), tables,
                   doc["digest"])  # fmt: skip


def _schema() -> dict[str, Any]:
    """The manifest's JSON Schema, beside this module (a site file, not a service contract of ``schemas/``)."""
    data: dict[str, Any] = json.loads(Path(__file__).with_name("site_profile.schema.json").read_text(encoding="utf-8"))
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


def loinc_check_digit_ok(code: str) -> bool:
    """LOINC's Mod-10 check: the digit after the hyphen is the Luhn check digit of the digits before it."""
    number, _, check = code.partition("-")
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return (10 - total % 10) % 10 == int(check)


def _register_says(system: str) -> str:
    """What the licence register says of a code system the product does not read (its row and status), if the
    register is beside the code (a repository; an image carries none)."""
    try:
        with REGISTER.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("kind") == "code-system" and system.replace("-", "") in r.get("id", "").replace("-", ""):
                    return f"; the licence register's row {r['id']} is {r.get('status') or 'not cleared'}"
    except OSError:
        pass
    return ""


def check_code(system: str, code: str) -> str | None:
    """Why ``code`` is not a code of ``system`` (``SYSTEM_SHAPES``), or None when it is."""
    if system not in SYSTEM_SHAPES:
        return f"code system {system!r} is not one this product reads ({', '.join(sorted(SYSTEM_SHAPES))})" + (
            _register_says(system.lower().rsplit("/", 1)[-1].split(".")[0] or system)
        )
    if not code.isascii() or not SYSTEM_SHAPES[system].fullmatch(code):
        return f"{code!r} is not a {system} code"
    if system == "loinc" and not loinc_check_digit_ok(code):
        return f"{code!r} fails LOINC's check digit"
    return None


def read_table(name: str, spec: dict[str, Any], folder: Path, where: str) -> tuple[Table, bytes]:
    """One code table, every row checked; the bytes are returned for the digest."""
    from tb_common.codekey import fold_key

    path = _table_path(folder, str(spec["file"]), where)
    data = path.read_bytes()
    shown = spec["file"]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        line = data[: exc.start].count(b"\n") + 1
        raise ProfileError(f"{shown}:{line}", "not UTF-8 text (save the table as UTF-8)") from None
    rows_in = csv.reader(io.StringIO(text, newline=""))
    cols = [c.strip() for c in next(rows_in, [])]
    key, target = str(spec["key"]), str(spec["target"])
    state_col = str(spec.get("state") or DEFAULT_STATE_COLUMN)
    for col in (key, target, state_col):
        if col not in cols:
            raise ProfileError(f"{shown}:1", f"no column {col!r} (the header has {', '.join(cols) or 'nothing'})")
    patient = sorted(c for c in cols if c.lower() in PATIENT_COLUMNS)
    if patient:
        raise ProfileError(f"{shown}:1", f"column {patient[0]!r} would hold patient data: a profile holds codes only")
    uses = tuple(spec["used_by"])
    if all(u in READER_ALLOWED for u in uses):
        allowed = frozenset().union(*(READER_ALLOWED[u] for u in uses)) | {state_col}
        extra = sorted(c for c in cols if c not in allowed)
        if extra:
            raise ProfileError(f"{shown}:1", f"column {extra[0]!r} is not one {', '.join(uses)} reads")
    fixed = next((SYSTEM_OF_USE[u] for u in uses if u in SYSTEM_OF_USE), None)
    if "system" not in cols and fixed is None:
        raise ProfileError(f"{shown}:1", "no column 'system': say the code system of each row's standard code")
    rows: dict[str, CodeRow] = {}
    folded: dict[str, CodeRow] = {}
    for n, cells in enumerate(rows_in, start=2):
        if n > MAX_ROWS + 1:
            raise ProfileError(shown, f"more than {MAX_ROWS} rows: not a code table")
        if not any(c.strip() for c in cells):
            continue  # a blank line
        if len(cells) > len(cols):
            raise ProfileError(f"{shown}:{n}", "more cells than the header has columns")
        r = {c: (cells[i].strip() if i < len(cells) else "") for i, c in enumerate(cols)}
        code, tgt, word = r[key], r[target], r[state_col].lower()
        if not code:
            raise ProfileError(f"{shown}:{n}", f"the {key} cell is empty")
        same = folded.get(fold_key(code))
        if same is not None:
            raise ProfileError(f"{shown}:{n}", f"{key} {code!r} is {same.code!r} of line {same.line} (one code)")
        if not tgt:
            raise ProfileError(f"{shown}:{n}", f"the {target} cell is empty: a code nobody mapped is not a row")
        if word not in STATE_WORDS:
            raise ProfileError(
                f"{shown}:{n}", f"state {word!r} is not one of {', '.join(sorted(STATE_WORDS))} (verified or verify)"
            )
        system = (r.get("system") or "").lower() if "system" in cols else str(fixed)
        why = check_code(system, tgt)
        if why:
            raise ProfileError(f"{shown}:{n}", f"column {target}: {why}")
        row = CodeRow(code, tgt, STATE_WORDS[word], n, r)
        rows[code] = folded[fold_key(code)] = row
    if not rows:
        raise ProfileError(shown, "the table has no rows: a table nobody filled is left out of the profile")
    table = Table(name, str(spec["file"]), path, key, target, state_col, str(spec.get("source") or ""),
                  tuple(spec["used_by"]), rows, tuple(cols))  # fmt: skip
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
    texts = [(["tables", n, "source"], str(t.get("source") or "")) for n, t in doc["tables"].items()]
    texts += [(["standards", k], str(v)) for k, v in doc["standards"].items()]
    for node, value in texts:
        if any(rx.search(value) for rx in _SECRET_SHAPES):
            raise ProfileError(f"{where}:{_line_of(text, node)}", f"{'.'.join(node)} looks like an address or a key: "
                               "a profile holds nothing secret (no URL, no @, no token)")  # fmt: skip
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
