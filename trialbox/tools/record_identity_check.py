"""Inventory local constructions of clinical record and owner keys under libs and services.

Inspect expressions, including nested functions and imported aliases. The ratchet is only an
expected result, never the input to discovery. Each function's operation counts also catch a
second use in an already listed function. Source-field/SQL idioms cover the existing non-hash
paths. Extend the idioms when introducing a new representation of source identity.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

GATE = "libs/tb_common/identity.py"
Location = tuple[str, str]
Inventory = dict[Location, Counter[str]]

# Existing ID makers, including the adapter's legacy bulk entry point.
CONSTRUCTORS = {
    "pid_for_mrn",
    "resource_id",
    "bulk_id",
    "pseudonymise_bulk",
    "pseudonymise",
    "order_no",
    "diag_key",
    "join_key",
    "erased_token",
    "add_drafts",
    "add_proposals",
    "patient_id",
    "pseudonym",
    "alias_patient",
    "alias_references",
}
ID_FIELDS = {
    "patient_id",
    "patient_key",
    "record_id",
    "record_key",
    "resource_id",
    "row_id",
    "person_id",
    "source_record_id",
    "pid",
    "oid",
    "eid",
    "cid",
    "fid",
    "did",
    "consid",
    "prid",
    "chunk_key",
    "enc_no",
    "lab_no",
    "rx_no",
    "diag_no",
    "note_no",
}
RAW_FIELDS = {"mrn", "chart_no", "patient_id", "patient_key", "resource_id", "record_id", "source_record_id"}
CLINICAL_TYPES = {
    "Patient",
    "Encounter",
    "Condition",
    "Observation",
    "MedicationRequest",
    "MedicationStatement",
    "Procedure",
    "DocumentReference",
    "DiagnosticReport",
    "Claim",
    "ClaimResponse",
    "Appointment",
    "Coverage",
    "Consent",
    "QuestionnaireResponse",
}
# Short names like cid, oid and pid also identify criteria, XML definitions and operating-system processes.
# Only infer their meaning from the destination in these packages. Named clinical constructors,
# explicit patient/record fields and patient-owned FHIR resources are checked everywhere.
CLINICAL_PACKAGES = {"adapter", "lake", "omop", "datacore", "sitesetup", "rc_bridge", "edc"}
SHORT = {"pid", "cid", "oid", "did", "eid", "fid", "consid", "prid"}
ID_FUNCTION = re.compile(
    r"^_*(?:(?:make_|build_|new_|stable_|canonical_)?(?:pid|rid|hid|(?:patient|owner|resource|record|row|person)_(?:key|id))|pid_for_mrn|key_part|diag_key)$"
)
BUILD_CALLS = {
    "new",
    "digest",
    "hexdigest",
    "sha256",
    "sha1",
    "sha256_text",
    "blake2b",
    "uuid4",
    "uuid5",
    "join",
    "format",
    "lower",
    "upper",
    "casefold",
    "normalise",
    "normalize",
}
# These writes/checks choose the first owner or mint the integer that will identify their record.
SQL_BINDINGS = (
    "SELECT pid FROM draft WHERE study = ? AND record = ? AND pid <> ?",
    "INSERT INTO subject (study, record, pid,",
    "UPDATE subject SET pid = ? WHERE study = ? AND record = ?",
    "INSERT INTO screening_no (",
    "INSERT INTO rc_record (",
    "SELECT nextval('tb_row_seq')",
    "INSERT INTO src_record (",
    "SELECT s.source_record_id, i.record_id FROM tb_load_stage",
    "UPDATE candidate_views SET pid = 'erased:'",
    "UPDATE tuned_patients SET pid = 'erased:'",
)
SQL_PREFIXES = tuple(s.upper() for s in SQL_BINDINGS)

# Small expressions with application-specific meanings that a generic ID sink cannot infer.
# Match the AST wherever it occurs, independent of file, function, whitespace and line number.
IDIOMS = {
    "source file identity": (
        "key_part(value).upper()",
        "key_part(placer)",
        "key_part(order)",
        "pid.reps(n)",
        "key_part(sf.order)",
        "f'{sf.order}@{sf.day}'",
        "key[0] != patient",
        "sf.patient[0:3]",
        "_KEY_OF[_TABLE_OF[typ]]",
        "_KEY_OF.get(table, '')",
        "StoredFile(path, pid, day, typ, order, stamp, dept, flag == '0', flag)",
        "self._key(sf.patient, sf.type, sf.order, sf.day)",
    ),
    "source correction key": (
        "corrected.get(r.pop('_same'))",
        "self._dx_dead.append(old)",
        "self._rx_dead.append(row)",
        "self._plain_keys",
        "self._deleted_docs.append",
        "key_part(base)",
        "row['_line']",
        "keys.add(row['rx_no'])",
    ),
    "source number": ("pv1.comp(19, 1)", "prb.comp(4, 1)", "obx.comp(21, 1)"),
    "chart alias": (
        "chartno.same_number(None, kept[1], mrn)",
        "self.aliases().get(pid, pid)",
        "_follow(raw, a)",
        "aliases[m.group(1)]",
        "aliases.get(str(r.get('id')))",
        "self.aliases.get(str(r.get('id')))",
        "self.surviving(pseudonym(site_key, new_chart)[0])",
        "str(ident.get('value')) in aliases",
    ),
    "EDC subject binding": (
        "sd.attrs.get('SubjectKey', '').strip()",
        "str(sd.get('SubjectKey') or '')",
        "max(used, default=0) + 1",
        "(str(rec.get(rid)), rec.get('redcap_event_name') if longitudinal else None, "
        "str(rec.get('redcap_repeat_instrument') or ''), _instance(rec))",
        "str(x).split(',', 1)[0]",
        "(v.record, visit, name)",
        "screening.get(value)",
        "self._pid_of(rs, rec)",
        "self.record_of.items()",
        "known.get(j.link_value)",
        "Lifecycle(self.dc).subject(rs, record)",
        "zip(new, ids, strict=False)",
        "r.source_id or r.record",
        "r[self.pid_field]",
        "r[self.key_field]",
        "r.get(self.key_column, '').strip().upper()",
        "str(r.get(link.link_field) or '').strip().upper()",
        "e.no.strip().upper()",
        "str(qr.get('id') or key)",
        "next((p for p, n in store.screening_nos(rid).items() if str(n).upper() == rec), None)",
        "(record, slot.event, slot.instrument, slot.instance)",
        "str(slot.instance)",
        "ids.get(str(d['record']).upper())",
        "str(r.get(key) or '').strip().upper() == record.upper()",
        "(doc.get('subjects') or {}).items()",
    ),
    "CDM source key": (
        "rec.key in pending",
        "(self.rtype, self.srcid, self.part)",
        "(r.rtype, r.srcid, r.part)",
        "(str(t), str(s_), int(p_))",
        "(str(t), str(s), int(p))",
        "srcid or str(r['id'])",
        "rec('measurement', o['pid'], part)",
        "_map_ids(tx, 'person', pids, 'tb_person_seq')",
        "['id_kind', 'source_id', 'omop_id']",
        "persons.get(str(pid))",
        "person.get(r['person_id'])",
    ),
    "source owner": (
        "str(ref['reference']).split('/')[-1]",
        "_ref(r.get('subject'), 'Patient')",
        "_ref_id(r.get('subject'))",
        "_ref_id(r.get('patient'))",
        "_ref_id(c.get('patient'))",
    ),
    "mapping deletion key": ("(rs.type, self.row_id(rs, row))",),
    "FHIR deletion key": ("rid.split('/', 1)[0]",),
    "bulk resource identity": ("new_id(r['resourceType'], r['id'])", "new_id(m.group(1), m.group(2))"),
}


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript):
        return _name(node.slice)
    return ""


def _constructed(expr: ast.expr) -> bool:
    return any(
        isinstance(n, ast.JoinedStr)
        or (isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Mod)))
        or (isinstance(n, ast.Call) and _name(n.func) in BUILD_CALLS)
        for n in ast.walk(expr)
    )


def _sql_binding(sql: str) -> bool:
    query = " ".join(sql.upper().split())
    insert = re.match(r"INSERT INTO [\w.]+\s*\(([^)]+)\)", query)
    columns = {v.strip() for v in insert[1].split(",")} if insert else set()
    binds_owner = bool(columns & {"RECORD", "RECORD_ID", "RECORD_KEY"} and columns & {"PID", "PATIENT_ID", "PERSON_ID"})
    return binds_owner or query.startswith(SQL_PREFIXES)


class Scan(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.Module, found: Inventory, detailed: bool) -> None:
        self.path = path
        self.detailed = detailed
        self.clinical = path.split("/")[1] in CLINICAL_PACKAGES
        self.stack: list[str] = []
        self.constructed_names: set[str] = set()
        self.aliases = {
            a.asname: a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names if a.asname
        }
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Name, ast.Attribute)):
                origin = self.aliases.get(_name(n.value), _name(n.value))
                if origin in CONSTRUCTORS or origin == "dict":
                    for target in n.targets:
                        if isinstance(target, ast.Name):
                            self.aliases[target.id] = origin
        self.found = found
        self.seen: set[tuple[int, int, str]] = set()

    def hit(self, node: ast.AST, operation: str) -> None:
        if not isinstance(node, (ast.expr, ast.stmt)):
            return
        at = node.lineno, node.col_offset, operation
        if at not in self.seen:
            key = operation + "\n" + ast.unparse(node) if self.detailed else operation
            self.found[self.path, ".".join(self.stack) or "<module>"][key] += 1
            self.seen.add(at)

    def scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.stack.append(node.name)
        enclosing = self.constructed_names
        self.constructed_names = set()
        self.generic_visit(node)
        self.constructed_names = enclosing
        self.stack.pop()

    visit_FunctionDef = scope
    visit_AsyncFunctionDef = scope
    visit_ClassDef = scope

    def visit_Call(self, node: ast.Call) -> None:
        name = _name(node.func)
        name = self.aliases.get(name, name)
        if name in {"digest", "hexdigest", "sha256", "sha256_text", "blake2b", "new"}:
            inputs = {_name(arg) for arg in ast.walk(node)}
            if (
                inputs & RAW_FIELDS
                or ("pid" in inputs and inputs & {"kind", "rtype", "rid", "srcid"})
                or (inputs & {"rtype", "resource_type"} and inputs & {"value", "rid", "srcid", "raw_id", "source_id"})
            ):
                self.hit(node, "hash source identifier")
        if (
            name == "build"
            and any(_name(n) == "pid" for n in ast.walk(node))
            and any(_name(n) == "record" for n in ast.walk(node))
        ):
            self.hit(node, "EDC subject binding")
        if name == "dict":
            self.mapping_fields(list(self.literal_fields(node)))
        if name in CONSTRUCTORS:
            self.hit(node, "call " + name)
        self.generic_visit(node)

    def sink(self, name: str, value: ast.expr) -> None:
        if name == "oid" and any(_name(n) == "OID" for n in ast.walk(value)):
            return  # an ODM metadata definition
        parsed_ref = name in {"pid", "patient_id"} and any(
            isinstance(n, ast.Call) and _name(n.func) in {"split", "rsplit", "removeprefix"} for n in ast.walk(value)
        )
        raw_owner = name in {"patient_id", "pid", "owner", "patient_key"} and _name(value) in {
            "mrn",
            "chart_no",
            "raw_id",
        }
        if name == "pid" and isinstance(value, ast.Subscript) and _name(value.value) == "raw" and _name(value) == "pid":
            self.hit(value, "chart alias")
        if name in SHORT and not self.clinical and not raw_owner:
            return
        if raw_owner or (name in ID_FIELDS and (_constructed(value) or parsed_ref)):
            self.hit(value, "build " + name)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and (
                _constructed(node.value) or _name(node.value) in self.constructed_names
            ):
                self.constructed_names.add(target.id)
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "id"
                and _name(target.value) != "mark"
                and _constructed(node.value)
            ):
                self.hit(node.value, "assign constructed id")
            if (
                _name(target) == "key"
                and _constructed(node.value)
                and any(_name(n) in {"rx_no", "lab_no", "diag_no"} for n in ast.walk(node.value))
            ):
                self.hit(node.value, "source occurrence key")
            self.sink(_name(target), node.value)
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg:
            self.sink(node.arg, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value:
            self.sink(_name(node.target), node.value)
        self.generic_visit(node)

    def literal_fields(self, node: ast.expr) -> Iterator[tuple[str, ast.expr]]:
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if key is None:
                    yield from self.literal_fields(value)
                elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield key.value, value
        elif isinstance(node, ast.Call) and self.aliases.get(_name(node.func), _name(node.func)) == "dict":
            for arg in node.args:
                yield from self.literal_fields(arg)
            for kw in node.keywords:
                if kw.arg is None:
                    yield from self.literal_fields(kw.value)
                else:
                    yield kw.arg, kw.value
        elif isinstance(node, (ast.Tuple, ast.List)):
            for pair in node.elts:
                if isinstance(pair, (ast.Tuple, ast.List)) and len(pair.elts) == 2:
                    key, value = pair.elts
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        yield key.value, value

    def visit_Dict(self, node: ast.Dict) -> None:
        self.mapping_fields(list(self.literal_fields(node)))
        self.generic_visit(node)

    def mapping_fields(self, fields: list[tuple[str, ast.expr]]) -> None:
        fhir = any(
            name == "resourceType" and (_name(value) in CLINICAL_TYPES or not isinstance(value, ast.Constant))
            for name, value in fields
        )
        for name, value in fields:
            if name == "record" and any(key == "pid" for key, _ in fields) and _constructed(value):
                self.hit(value, "EDC subject binding")
            if name == "mrn" and isinstance(value, ast.Attribute) and value.attr == "patient":
                self.hit(value, "source owner")
            if (
                name == "id"
                and fhir
                and (
                    _constructed(value)
                    or isinstance(value, ast.Constant)
                    or (isinstance(value, ast.Name) and value.id in self.constructed_names)
                    or _name(value) in RAW_FIELDS | {"raw_id", "srcid", "_rid"}
                    or (isinstance(value, ast.Call) and _name(value.func) == "_rid")
                )
            ):
                self.hit(value, "build FHIR id")
            self.sink(name, value)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value and isinstance(node.value, (ast.JoinedStr, ast.BinOp, ast.Tuple, ast.Call)):
            fields = {_name(n) for n in ast.walk(node.value)}
            if (
                fields & RAW_FIELDS
                and _constructed(node.value)
                and (
                    fields & {"sha256", "blake2b", "hexdigest", "digest"}
                    or (fields & {"number", "occurrence", "record_id", "record_key"} and fields & {"patient_id", "mrn"})
                )
            ):
                self.hit(node.value, "compose source identity")
        if (
            self.stack
            and self.stack[-1] in {"_rec", "join_key", "erased_token"}
            and node.value
            and _constructed(node.value)
        ):
            self.hit(node.value, "return constructed identity")
        if self.stack and ID_FUNCTION.fullmatch(self.stack[-1]) and node.value and _constructed(node.value):
            self.hit(node.value, "return constructed identity")
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        if isinstance(node.ctx, ast.Load) and 1 < len(node.elts) <= 4:
            parts = {_name(e) for e in node.elts}
            if parts & {"patient", "patient_id", "mrn"} and parts & {
                "typ",
                "order",
                "diag_no",
                "rx_no",
                "enc_no",
                "kind",
                "source_record_id",
                "record_id",
                "occurrence",
            }:
                self.hit(node, "source owner and occurrence")
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        fields = {_name(n) for n in ast.walk(node)}
        if fields & {"patient_id", "chart_no", "mrn", "pid"} and fields & {
            "record_id",
            "source_record_id",
            "occurrence",
        }:
            self.hit(node, "compose source identity")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if (
            isinstance(node.value, str)
            and node.value.lstrip().upper().startswith(("SELECT ", "UPDATE ", "INSERT "))
            and _sql_binding(node.value)
        ):
            self.hit(node, "SQL record binding")

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, IDIOM_TYPES):
            # Filter on the head first: full dumps of every expression of every module are expensive.
            for expected, label in PATTERNS.get(_head(node), ()):
                if ast.dump(node) == expected:
                    self.hit(node, label)
                    break
        super().generic_visit(node)


def _head(node: ast.AST) -> tuple[type[ast.AST], str]:
    if isinstance(node, ast.Call):
        return type(node), _name(node.func)
    return type(node), _name(node)


PATTERNS: dict[tuple[type[ast.AST], str], list[tuple[str, str]]] = defaultdict(list)
for label, examples in IDIOMS.items():
    for example in examples:
        expression = ast.parse(example, mode="eval").body
        PATTERNS[_head(expression)].append((ast.dump(expression), label))
IDIOM_TYPES = tuple({kind for kind, _ in PATTERNS})


def scan(root: Path, *, detailed: bool = False) -> Inventory:
    found: Inventory = defaultdict(Counter)
    for directory in ("libs", "services"):
        for path in sorted((root / directory).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel != GATE:
                tree = ast.parse(path.read_bytes(), filename=rel)
                Scan(rel, tree, found, detailed).visit(tree)
        for path in sorted((root / directory).rglob("*.sql")):
            rel = path.relative_to(root).as_posix()
            sql = re.sub(r"--[^\n]*|/\*.*?\*/", "", path.read_text(), flags=re.DOTALL)
            for statement in sql.split(";"):
                if _sql_binding(statement):
                    key = "SQL record binding"
                    if detailed:
                        key += "\n" + " ".join(statement.split())
                    found[rel, "<sql>"][key] += 1
    return dict(found)


def expected_inventory(path: Path, *, detailed: bool = False) -> Inventory:
    """Each reviewed expression occurs once per entry, including repeated identical writes."""
    return _inventory(path.read_text(), detailed)


def _inventory(document: str, detailed: bool) -> Inventory:
    result: Inventory = defaultdict(Counter)
    for entry in json.loads(document):
        location = (entry["file"], entry["function"])
        if not all(entry.get(k) for k in ("why", "area", "operation", "expression")):
            raise ValueError(f"Invalid entry / 清單項目無效 / 無効な項目 {location}")
        operation = entry["operation"]
        if detailed:
            operation += "\n" + entry["expression"]
        result[location][operation] += 1
    return dict(result)


def ratchet_growth(proposed: str, previous: str) -> Inventory:
    """Count new expressions, including extra copies at an already reviewed location."""
    before = _inventory(previous, detailed=True)
    return {
        location: added
        for location, entries in _inventory(proposed, detailed=True).items()
        if (added := entries - before.get(location, Counter()))
    }


def historical_growth(root: Path) -> Inventory:
    """Follow the first-parent ratchet, including the working copy. Squash merges are ordinary transitions."""
    path = "tools/record_identity_ratchet.json"

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout

    revisions = git("log", "--first-parent", "--format=%H", "--", path).splitlines()
    current = (root / path).read_text()
    for revision in revisions:
        previous = git("show", f"{revision}:./{path}")
        if added := ratchet_growth(current, previous):
            return added
        current = previous
    # Authenticate the starting list too: a shallow checkout or a squashed first introduction
    # cannot silently establish a larger baseline.
    if (
        hashlib.sha256(current.encode()).hexdigest()
        != "a864d589201c6f26dc4a7b37baeb5e0f799b2da70586550b92f899850a022377"
    ):
        raise ValueError(
            "Unverified initial ratchet. Use full history. / 無法驗證初始清單，請使用完整歷程。 / "
            "初期リストを検証できません。完全な履歴を使用してください。"
        )
    return {}
