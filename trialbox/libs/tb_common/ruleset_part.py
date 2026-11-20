"""A rule set carried in a vendor-signed update bundle, for the dry run only (plan 10 row 10D-28, review 19-9; D-1369).

Until the coordinating centre signs a study package (cards 10D-2 to 10D-4), a screen-only site box gets a rule set
compiled and approved on the head box this way: the head box exports the approved version as a **rule-set part**
(``python -m criteria_compiler.export_part``), the vendor signs it into an update bundle with the vendor key
(``python -m tools.ruleset_bundle`` for a part alone; ``tools/make_bundle.sh --rulesets DIR`` beside a release), and
``tools/apply_update.sh`` installs it on the site box through the import that already installs a bundle's rule sets
(``criteria_compiler.import_ruleset``).

A part is a zip of the ``import_ruleset`` form (one folder ``<ID>/``) with one more member at its root,
``ORIGIN.json``: where it came from and the part's sha256.

* **Criteria and codes only** (:func:`neutral_files`), by an allow-list of files and of keys, never a deny-list:

  - **files**: exactly the protocol files of ``tb_common.study_manifest.PROTOCOL_FILES`` (master's list) that are
    criteria and codes, one per name: ``manifest.yaml``, ``labels.yaml``, ``ir/<criterion id>.json``,
    ``valuesets/<value set name>.json``, ``cql/<library>.cql`` and ``cql/elm/<library>.json`` (the study's library and
    ``TB_Common`` only), ``sql/<ID>.sql``. ``tests/`` (synthetic patients and the site's equivalence run) is left
    out; **any other file refuses the export** (and the import refuses any other member);
  - **the manifest**: the protocol's fields of D-1366 (``study_manifest.PROTOCOL_FIELDS``) but ``source_documents``
    and ``docx_template`` (file names) and ``population.notes`` (free notes), ``source_last_update`` a date only;
    with ``status``, ``models.judge_prompt`` and the numbers of ``equivalence``;
    ``routing`` and ``scopes`` stay as the empty placeholders the schema requires; a field nobody placed refuses;
    the result is checked against the manifest schema (an unknown key at any depth refuses) and written again as
    YAML (no comment survives);
  - **each criterion**: the fields of :data:`IR_KEYS` only (the criterion schema's but ``provenance``; ``review``
    keeps its status), checked against the criterion schema; a flag is one word of the compiler's;
  - **value sets**: the keys the compiler writes (:data:`VALUESET_KEYS`) only, else refused; **ELM**
    (:func:`elm_allowed`): the top level ``library`` only, the library's keys of :data:`ELM_LIBRARY_KEYS`, every key
    below of :data:`ELM_NODE_KEYS` (the keys the compiler's translator writes), any other key refused naming its path
    (at the export and at the receiving box); its ``annotation`` entries (the translator's copy of the CQL source, its
    options and messages) and the library's ``localId`` removed by the export, refused at the receiving box; its
    library identifier ``id`` and ``version`` only; **labels**: their keys only, written again as YAML;
  - **CQL and SQL**: carried as their bytes, every comment held against the compiler's own
    (``criteria_compiler.part_text``): another comment refuses the export with the file and the line (a comment is
    never stripped from code). **String literals are not checked**: they are free text the approver may have typed
    and travel as written (in the CQL and SQL), like the criterion text (D-1369, "What travels"). The ELM is not
    checked against the CQL either, and its values are not type-checked: any string value under an allowed key
    travels as written; it is not checked against the CQL.

* **The part's hash** (:func:`part_sha256`) covers every carried file (path and bytes) and every field of
  ``ORIGIN.json`` but the hash itself. No time is in it: the same approved version exported again from the same
  release is the same part, byte for byte (the export's time is the audit event's). Every field is checked against a
  strict form, and the pins against the manifest's (:func:`check_origin`).
* **Not a local approval.** The receiving box takes its own ``routing`` and ``scopes`` for the study, set with
  ``import_ruleset --site-profile`` (audited; the import refuses without them), records the approval tag with
  :data:`ARRIVED_MARK`, and lists it as "arrived in a vendor bundle (interim)".
* **Bounded.** A JSON or YAML file nested deeper than :data:`MAX_DEPTH` is refused before it is parsed.

Standard library, PyYAML and the shared schemas (``tb_contracts``); the CQL and SQL comment check reads the compiler's
templates (``criteria_compiler.part_text``), which the compiler's image and the vendor's checkout both hold.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import PurePosixPath
from typing import Any

import yaml

from tb_common.study_manifest import PROTOCOL_FIELDS as _D1366_PROTOCOL
from tb_common.zipcap import ZipRefused, check_ruleset_zip

PART_FORMAT = "trialbox-ruleset-part/1"
ORIGIN = "ORIGIN.json"
MANIFEST = "manifest.yaml"
LABELS = "labels.yaml"
#: ``(prefix, suffix)`` of each carried file kind besides the two named files: master's ``PROTOCOL_FILES`` less
#: ``tests/`` (left out) and the docx template (no criterion or code), the ELM as JSON only, one name per file
CARRIED = (("ir/", ".json"), ("valuesets/", ".json"), ("cql/elm/", ".json"), ("cql/", ".cql"), ("sql/", ".sql"))
_KIND = {"ir/": "ir", "valuesets/": "valueset", "cql/elm/": "elm", "cql/": "cql", "sql/": "sql"}
LEFT_OUT_DIRS = ("tests/",)
#: written on the approval tag of a rule set a part installed; the console lists such a version as not approved here
ARRIVED_MARK = "arrived in a vendor bundle (interim)"
#: what every installed offline update writes on its tag (D-77): such a version was not approved on this box either
UPDATE_MARK = "(offline update, "

#: D-1366's protocol fields that do not travel: file names someone chose (the uploaded protocol's, the docx template's)
DROPPED_PROTOCOL = ("source_documents", "docx_template")
#: the manifest fields a part carries as they are (D-1366, 10D-2), with ``status``
PROTOCOL_FIELDS = tuple(f for f in _D1366_PROTOCOL if f not in DROPPED_PROTOCOL)
#: D-1366's site part: removed on export (routing and scopes stay as empty placeholders); ``models`` keeps its
#: ``judge_prompt``, ``equivalence`` its numbers
SITE_FIELDS = ("effective_from", "irb_reference", "irb_approved_on", "scopes", "routing", "review",
               "terminology_tables", "terminology_refused", "models", "equivalence")  # fmt: skip
EQUIVALENCE_KEPT = ("overall_pct", "sample_size", "per_criterion", "failing")
#: a criterion's fields a part carries (``CriterionIR``'s but ``provenance``; ``review`` as its status only)
IR_KEYS = ("id", "ruleset", "text", "label", "source_ref", "kind", "class", "time_sensitive", "logic", "fallback",
           "note_question", "note_question_source", "human_question", "action", "suggested_order", "flags",
           "review")  # fmt: skip
#: the keys of a value set as the compiler writes it (``criteria_compiler.terminology.mapper``)
VALUESET_KEYS = {"resourceType", "id", "name", "title", "url", "version", "status", "compose", "extension"}
VALUESET_INCLUDE_KEYS = {"system", "concept"}
VALUESET_CONCEPT_KEYS = {"code", "display"}
VALUESET_EXTENSION_KEYS = {"url", "valueString"}
CODE_FAMILY = "https://trialbox.local/fhir/StructureDefinition/code-family"
LABEL_ENTRY_KEYS = {"source", "todo_source", "en", "ja", "zh-TW"}
LABEL_LANG_KEYS = {"label", "text", "todo"}
#: ELM (D-1369 decision 1, allow-lists): the keys of its ``library``
ELM_LIBRARY_KEYS = frozenset({"identifier", "schemaIdentifier", "usings", "includes", "parameters", "codeSystems",
                              "valueSets", "codes", "concepts", "contexts", "statements"})  # fmt: skip
#: ELM: every key that may stand anywhere below the library's keys. Derived (10D-28, the re-check of #1174) as the
#: union of the dict keys, ``annotation`` left out, of (a) the repository's compiled ELM fixtures
#: ``rulesets/*/cql/elm/*.json`` (8 rule sets, 16 files) and (b) the translator's own output (the pinned
#: ``.cache/jvm/cql-translator`` jars, ``compile_cql.translator.Translator``) for each rule set's CQL, the generator's
#: snapshot ``tests/fixtures/ir/snapshots/ATOMS.cql`` (every atom) and ``render_common()``; (a) and (b) gave the same
#: 81 keys. A key the compiler starts to write after a template change refuses the export, naming it: add it here
#: then, from the translator's output, never by hand from a part.
ELM_NODE_KEYS = frozenset({
    "accessLevel", "alias", "asType", "asTypeSpecifier", "by", "caseItem", "choice", "code", "codeComparator",
    "codeFilter", "codeProperty", "codeSystem", "codeSystems", "codes", "comparand", "condition", "context",
    "contexts", "dataType", "dateFilter", "day", "def", "default", "direction", "element", "elementType", "else",
    "expression", "high", "highClosed", "id", "identifier", "include", "includes", "isTypeSpecifier", "let",
    "libraryName", "localId", "localIdentifier", "locator", "low", "lowClosed", "month", "name", "operand",
    "operandTypeSpecifier", "otherFilter", "parameterTypeSpecifier", "parameters", "path", "pointType", "precision",
    "preserve", "relationship", "resultTypeName", "resultTypeSpecifier", "return", "schemaIdentifier", "scope",
    "separator", "signature", "sort", "source", "statements", "strict", "stringToSplit", "suchThat", "templateId",
    "then", "type", "unit", "uri", "usings", "value", "valueSets", "valueType", "valueset", "version", "when",
    "where", "year",
})  # fmt: skip
#: the translator's bookkeeping the export removes (the receiving box refuses it like any other key): ``annotation``
#: at any depth (the translator's copy of the CQL source, its options and messages) and the library's ``localId``
ELM_STRIPPED_ANYWHERE = frozenset({"annotation"})
ELM_STRIPPED_LIBRARY = frozenset({"localId"})
#: how deep a part's JSON or YAML may nest (the compiler's ELM reaches about 90)
MAX_DEPTH = 256

RULESET_ID = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
CRITERION_ID = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*-(INC|EXC|REN|DOC)-[0-9]{2,3}$")
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
FLAG = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
VERSION = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
BUNDLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
PROMPT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
ORIGIN_KEYS = {"format", "ruleset", "version", "part_sha256", "files", "left_out", "approval_tag", "compiled_on",
               "pins"}  # fmt: skip
_STRING = re.compile(rb'"(?:[^"\\]|\\.)*"', re.S)


class PartRefused(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- bounded parsing
def _json_depth(data: bytes) -> int:
    depth = top = 0
    for b in re.findall(rb"[\[\]{}]", _STRING.sub(b"", data)):
        depth += 1 if b in (b"[", b"{") else -1
        top = max(top, depth)
    return top


def load_json(data: bytes, name: str) -> Any:
    """A part's JSON file: nested at most :data:`MAX_DEPTH` (counted before it is parsed), no key twice."""
    if _json_depth(data) > MAX_DEPTH:
        raise PartRefused(f"{name} nests deeper than {MAX_DEPTH}: refused")
    from tb_common.study_manifest import load_json as strict

    try:
        return strict(data)
    except (ValueError, RecursionError) as exc:
        raise PartRefused(f"{name} is not JSON a part carries: {exc}") from exc


def load_yaml(data: bytes, name: str) -> Any:
    """A part's YAML file: its events counted first (PyYAML's parser keeps no recursion), nested at most
    :data:`MAX_DEPTH`."""
    try:
        text = data.decode("utf-8")
        depth = 0
        for ev in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(ev, yaml.CollectionStartEvent):
                depth += 1
                if depth > MAX_DEPTH:
                    raise PartRefused(f"{name} nests deeper than {MAX_DEPTH}: refused")
            elif isinstance(ev, yaml.CollectionEndEvent):
                depth -= 1
        return yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError, RecursionError) as exc:
        raise PartRefused(f"{name} is not YAML a part carries: {exc}") from exc


def _json(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _yaml(obj: Any) -> bytes:
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False).encode("utf-8")


# ---------------------------------------------------------------------------------------------- the allow-lists
def kind_of(path: str) -> str | None:
    """What a carried file is (``manifest``, ``labels``, ``ir``, ``valueset``, ``elm``, ``cql``, ``sql``); None for a
    file a part does not carry."""
    if path == MANIFEST:
        return "manifest"
    if path == LABELS:
        return "labels"
    for prefix, suffix in CARRIED:
        if path.startswith(prefix) and path.endswith(suffix) and FILE_NAME.match(path[len(prefix) : -len(suffix)]):
            return _KIND[prefix]
    return None


def _stem(path: str) -> str:
    return PurePosixPath(path).stem


def neutral_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest with the site part removed (D-1366): what a part carries. Refuses a field nobody placed."""
    if not isinstance(manifest, dict):
        raise PartRefused("manifest.yaml is not a mapping")
    unplaced = sorted(str(k) for k in manifest if k not in (*_D1366_PROTOCOL, *SITE_FIELDS, "status"))
    if unplaced:
        raise PartRefused(f"manifest fields not placed as protocol or site ({', '.join(unplaced)}): not exported")
    out = {k: v for k, v in manifest.items() if k in PROTOCOL_FIELDS or k == "status"}
    if isinstance(out.get("population"), dict):  # its notes are free words anyone may have typed: they stay here
        out["population"] = {k: v for k, v in out["population"].items() if k != "notes"}
    if "source_last_update" in out and not _is_date(out["source_last_update"]):
        raise PartRefused("manifest.yaml source_last_update is not a date (YYYY-MM-DD)")
    out["scopes"], out["routing"] = {}, {}  # required by the schema; the receiving site's own replace them
    models = manifest.get("models") or {}
    if isinstance(models, dict) and models.get("judge_prompt"):
        out["models"] = {"judge_prompt": models["judge_prompt"]}
    eq = manifest.get("equivalence")
    if isinstance(eq, dict):
        out["equivalence"] = {k: eq[k] for k in EQUIVALENCE_KEPT if k in eq}
        ids = [*(eq.get("failing") or []), *(eq.get("per_criterion") or {})]
        bad = [str(i)[:40] for i in ids if not (isinstance(i, str) and CRITERION_ID.match(i))]
        if bad:
            raise PartRefused(f"manifest.yaml equivalence names something other than a criterion id: {bad[:3]}")
    return out


def _is_date(v: Any) -> bool:
    if isinstance(v, date):
        return True
    try:
        date.fromisoformat(str(v))
    except ValueError:
        return False
    return isinstance(v, str) and len(v) == 10


def _schema_manifest(m: dict[str, Any]) -> None:
    from pydantic import ValidationError
    from tb_contracts import RulesetManifest

    try:
        RulesetManifest.model_validate(m)
    except ValidationError as exc:
        raise PartRefused(f"manifest.yaml is not of the manifest schema: {str(exc)[:300]}") from exc


def neutral_ir(criterion: dict[str, Any]) -> dict[str, Any]:
    """A criterion as a part carries it: the fields of :data:`IR_KEYS` only (any other key is dropped), its review
    status only (no who, when or comment); each flag one word of the compiler's."""
    if not isinstance(criterion, dict):
        raise PartRefused("a criterion is not a mapping")
    out = {k: criterion[k] for k in IR_KEYS if k in criterion and k != "review"}
    review = criterion.get("review")
    if isinstance(review, dict) and review.get("status"):
        out["review"] = {"status": review["status"]}
    flags = out.get("flags")
    if flags is not None and not (isinstance(flags, list) and all(isinstance(f, str) and FLAG.match(f) for f in flags)):
        raise PartRefused(f"{str(out.get('id'))[:40]}: a flag is not one word of the compiler's (a-z, 0-9, _)")
    return out


def _schema_ir(c: dict[str, Any], path: str, rid: str) -> None:
    from pydantic import ValidationError
    from tb_contracts import CriterionIR

    try:
        CriterionIR.model_validate(c)
    except ValidationError as exc:
        raise PartRefused(f"{path} is not of the criterion schema: {str(exc)[:300]}") from exc
    if c.get("id") != _stem(path) or c.get("ruleset") != rid:
        raise PartRefused(f"{path}: its id and rule set are not {_stem(path)} of {rid}")


def _keys(obj: Any, allowed: set[str], where: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise PartRefused(f"{where} is not a mapping")
    extra = sorted(str(k)[:40] for k in obj if k not in allowed)
    if extra:
        raise PartRefused(f"{where} holds keys a part does not carry ({', '.join(extra[:5])}): criteria and codes only")
    return obj


def check_valueset(data: bytes, path: str) -> None:
    """A value set holds the compiler's keys only, at every level; its name is its file's."""
    vs = _keys(load_json(data, path), VALUESET_KEYS, path)
    if vs.get("name") != _stem(path):
        raise PartRefused(f"{path}: its name is not {_stem(path)}")
    compose = _keys(vs.get("compose"), {"include"}, f"{path} compose")
    for i, inc in enumerate(compose.get("include") or []):
        _keys(inc, VALUESET_INCLUDE_KEYS, f"{path} compose.include[{i}]")
        for j, concept in enumerate(inc.get("concept") or []):
            _keys(concept, VALUESET_CONCEPT_KEYS, f"{path} compose.include[{i}].concept[{j}]")
    for i, ext in enumerate(vs.get("extension") or []):
        _keys(ext, VALUESET_EXTENSION_KEYS, f"{path} extension[{i}]")
        if ext.get("url") != CODE_FAMILY or not isinstance(ext.get("valueString"), str):
            raise PartRefused(f"{path} extension[{i}] is not the compiler's code family")


def _elm_key(key: Any) -> str:
    """The offending key as its length only: on the receiving box the key is the part's text, so it is never printed."""
    return f"<a key of length {len(str(key))}>"


def _elm_node(node: Any, path: str, where: str, strip: bool) -> Any:
    """``node`` with every key in :data:`ELM_NODE_KEYS`, at every depth; ``annotation`` removed when ``strip`` (the
    export), refused when not (the receiving box); any other key refused, naming its path (the allowed keys and indices) and the offending key's length, not its text."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if strip and k in ELM_STRIPPED_ANYWHERE:
                continue
            if k not in ELM_NODE_KEYS:
                raise PartRefused(f"{path} {where}.{_elm_key(k)}: a key the compiler's ELM does not hold; a part "
                                  "carries the compiler's ELM keys only")  # fmt: skip
            out[k] = _elm_node(v, path, f"{where}.{k}", strip)
        return out
    if isinstance(node, list):
        return [_elm_node(v, path, f"{where}[{i}]", strip) for i, v in enumerate(node)]
    return node


def elm_allowed(elm: Any, path: str, strip: bool) -> dict[str, Any]:
    """ELM by allow-lists, never a deny-list: the top level ``library`` only, the library's keys of
    :data:`ELM_LIBRARY_KEYS` only, every key below them of :data:`ELM_NODE_KEYS`. With ``strip`` (the export) the
    translator's bookkeeping (:data:`ELM_STRIPPED_ANYWHERE`, :data:`ELM_STRIPPED_LIBRARY`) is removed first; without
    it (the receiving box) that bookkeeping is refused like any other key. Any other key is refused with its path,
    never dropped."""
    if not isinstance(elm, dict):
        raise PartRefused(f"{path} is not ELM (no library)")
    extra = [k for k in elm if k != "library" and not (strip and k in ELM_STRIPPED_ANYWHERE)]
    if extra:
        raise PartRefused(f"{path} {_elm_key(extra[0])}: ELM holds the key library only at its top")
    lib = elm.get("library")
    if not isinstance(lib, dict):
        raise PartRefused(f"{path} is not ELM (no library)")
    out: dict[str, Any] = {}
    for k, v in lib.items():
        if strip and (k in ELM_STRIPPED_ANYWHERE or k in ELM_STRIPPED_LIBRARY):
            continue
        if k not in ELM_LIBRARY_KEYS:
            raise PartRefused(f"{path} library.{_elm_key(k)}: a key the compiler's ELM library does not hold; a part "
                              "carries the compiler's ELM keys only")  # fmt: skip
        out[k] = _elm_node(v, path, f"library.{k}", strip)
    return {"library": out}


def neutral_elm(data: bytes, path: str) -> bytes:
    """ELM by :func:`elm_allowed`: without its ``annotation`` entries (the translator's copy of the CQL source text,
    its options and its messages: nothing of what runs) and the library's ``localId``, every other key on the
    allow-lists or the export is refused; its library identifier ``id`` and ``version`` only, written compact."""
    raw = load_json(data, path)
    lib = raw.get("library") if isinstance(raw, dict) else None
    if isinstance(lib, dict) and "identifier" in lib:  # the translator always writes it (a stand-in may not)
        ident = _keys(lib["identifier"], {"id", "version"}, f"{path} library.identifier")
        if ident.get("id") != _stem(path):
            raise PartRefused(f"{path}: its library is not {_stem(path)}")
    elm = elm_allowed(raw, path, strip=True)
    return json.dumps(elm, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def neutral_labels(data: bytes, rid: str) -> bytes:
    """``labels.yaml`` with its keys only (per criterion: the protocol's text, its to-do and their translations),
    written again (no comment survives)."""
    doc = _keys(load_yaml(data, LABELS), {"ruleset", "criteria"}, LABELS)
    if doc.get("ruleset") != rid:
        raise PartRefused(f"{LABELS}: its rule set is not {rid}")
    for cid, entry in (doc.get("criteria") or {}).items():
        if not (isinstance(cid, str) and CRITERION_ID.match(cid)):
            raise PartRefused(f"{LABELS}: {str(cid)[:40]!r} is not a criterion id")
        for k, v in _keys(entry, LABEL_ENTRY_KEYS, f"{LABELS} {cid}").items():
            words = list(_keys(v, LABEL_LANG_KEYS, f"{LABELS} {cid}.{k}").values()) if isinstance(v, dict) else [v]
            if not all(isinstance(w, str) for w in words):
                raise PartRefused(f"{LABELS} {cid}.{k}: only text")
    return _yaml(doc)


def _code(path: str, data: bytes, manifest: dict[str, Any], criteria: list[dict[str, Any]]) -> bytes:
    """CQL or SQL as its bytes, when its name is the study's and every comment is the compiler's."""
    from criteria_compiler import part_text

    rid, version, stem = str(manifest.get("id")), str(manifest.get("version")), _stem(path)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PartRefused(f"{path} is not UTF-8 text") from exc
    if path.startswith("sql/") and stem != rid:
        raise PartRefused(f"{path}: a part carries sql/{rid}.sql only")
    if path.startswith("cql/"):
        if stem not in (manifest.get("library"), "TB_Common"):
            raise PartRefused(f"{path}: a part carries the library {manifest.get('library')} and TB_Common only")
        m = part_text.LIBRARY.search(text)
        if not m or m.group(1) != stem:
            raise PartRefused(f"{path}: its library line does not name {stem}")
    found = part_text.problems(path, data, rid, version, criteria)
    if found:
        raise PartRefused(f"a comment the compiler does not write, at {', '.join(found[:5])}: a part carries the "
                          "compiler's own comments only; remove it, approve again and export")  # fmt: skip
    return data


def neutral_files(files: dict[str, bytes]) -> dict[str, bytes]:
    """The files of an approved rule set folder as a part carries them: ``tests/`` left out, any other file refused,
    every file in the form above. Given a part's own files it gives them back unchanged (:func:`check_neutral`)."""
    if MANIFEST not in files:
        raise PartRefused("no manifest.yaml")
    for path in sorted(files):
        if not path.startswith(LEFT_OUT_DIRS) and kind_of(path) is None:
            raise PartRefused(f"{path}: not a file a rule-set part carries (criteria and codes only: manifest.yaml, "
                              "labels.yaml, ir/<id>.json, valuesets/<name>.json, cql/<library>.cql, "
                              "cql/elm/<library>.json, sql/<ID>.sql); any other file refuses the export")  # fmt: skip
    manifest = neutral_manifest(load_yaml(files[MANIFEST], MANIFEST) or {})
    _schema_manifest(manifest)
    rid = str(manifest.get("id"))
    if not RULESET_ID.match(rid):
        raise PartRefused(f"manifest.yaml: {rid[:40]!r} is not a rule set id")
    out: dict[str, bytes] = {MANIFEST: _yaml(manifest)}
    criteria: list[dict[str, Any]] = []
    for path in sorted(p for p in files if kind_of(p) == "ir"):
        c = neutral_ir(load_json(files[path], path))
        _schema_ir(c, path, rid)
        criteria.append(c)
        out[path] = _json(c)
    cql = {_stem(p) for p in files if kind_of(p) == "cql"}
    for path in sorted(files):
        kind, data = kind_of(path), files[path]
        if kind == "valueset":
            check_valueset(data, path)
            out[path] = data
        elif kind == "elm":
            if _stem(path) not in cql:
                raise PartRefused(f"{path}: no cql/{_stem(path)}.cql beside it")
            out[path] = neutral_elm(data, path)
        elif kind == "labels":
            out[path] = neutral_labels(data, rid)
        elif kind in ("cql", "sql"):
            out[path] = _code(path, data, manifest, criteria)
    return out


def check_neutral(files: dict[str, bytes]) -> None:
    """Refuse a part whose files are not exactly what the export writes: a site or staff field, a key or file nobody
    placed, an annotation, a comment the compiler does not write (a part not made by the export). Each ELM file is
    first held against the ELM allow-lists as it stands (:func:`elm_allowed` without stripping): a key off them is
    refused naming its path, never dropped."""
    for path in sorted(p for p in files if kind_of(p) == "elm"):
        elm_allowed(load_json(files[path], path), path, strip=False)
    clean = neutral_files(files)
    if clean.keys() != files.keys():
        raise PartRefused(f"the part holds files a part does not carry: {sorted(set(files) - set(clean))[:5]}")
    if clean[MANIFEST] != files[MANIFEST]:
        raise PartRefused("its manifest holds site or staff fields (routing, scopes, the approval record, IRB, the "
                          "site's code tables), or is not as the export writes it: a part carries criteria and codes "
                          "only")  # fmt: skip
    for path in sorted(files):
        if clean[path] != files[path]:
            raise PartRefused(f"{path} holds a reviewer's record, provenance, a key nobody placed or an annotation, or "
                              "is not as the export writes it: a part carries criteria and codes only")  # fmt: skip


def part_sha256(files: dict[str, bytes], origin: dict[str, Any]) -> str:
    """sha256 over the sorted lines ``<sha256 of the bytes>  <path>`` of every file, then the line ``origin
    <sha256 of ORIGIN.json without part_sha256, keys sorted>``. The record holds no time."""
    lines = "".join(f"{hashlib.sha256(files[p]).hexdigest()}  {p}\n" for p in sorted(files))
    rest = {k: v for k, v in origin.items() if k != "part_sha256"}
    canon = json.dumps(rest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    lines += f"origin {hashlib.sha256(canon).hexdigest()}\n"
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def build_part(ruleset_id: str, files: dict[str, bytes], origin: dict[str, Any]) -> bytes:
    """The part's zip: ``<ID>/<file>`` for each carried file (as :func:`neutral_files` gives them) and
    ``ORIGIN.json`` with :func:`part_sha256` filled in; fixed dates, so the same input gives the same bytes."""
    carried = neutral_files(files)
    origin = {**origin, "files": sorted(carried)}
    origin["part_sha256"] = part_sha256(carried, origin)
    check_origin(origin, ruleset_id, str(origin.get("version")), carried, load_yaml(carried[MANIFEST], MANIFEST))
    members = {f"{ruleset_id}/{p}": b for p, b in carried.items()}
    members[ORIGIN] = _json(origin)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, members[name])
    return buf.getvalue()


def origin_of(data: bytes) -> dict[str, Any] | None:
    """The part's ``ORIGIN.json``; None for a rule set zip that is no part (a vendor-shipped rule set). A member named
    ``ORIGIN.json`` anywhere but at the root is refused: a part's record is never moved out of sight."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = check_ruleset_zip(z)
            moved = [n for n in names if PurePosixPath(n).name.lower() == ORIGIN.lower() and n != ORIGIN]
            if moved:
                raise PartRefused(f"{moved[0]}: a part's {ORIGIN} stands at the root of the zip, nowhere else")
            if ORIGIN not in names:
                return None
            raw = z.read(ORIGIN)
    except (ZipRefused, zipfile.BadZipFile) as exc:
        raise PartRefused(f"not a readable rule-set zip: {exc}") from exc
    origin = load_json(raw, ORIGIN)
    if not isinstance(origin, dict) or origin.get("format") != PART_FORMAT:
        raise PartRefused(f"{ORIGIN} is not a {PART_FORMAT} record")
    return origin


def _text(v: Any, cap: int) -> bool:
    return isinstance(v, str) and 0 < len(v) <= cap and not CONTROL.search(v)


def _origin_problems(o: dict[str, Any], ruleset_id: str, version: str, manifest: dict[str, Any]) -> list[str]:
    bad = [f"unexpected field {k!r}" for k in sorted(set(o) - ORIGIN_KEYS)]
    bad += [f"missing field {k!r}" for k in sorted(ORIGIN_KEYS - set(o) - {"left_out"})]
    if not (isinstance(o.get("ruleset"), str) and RULESET_ID.match(o["ruleset"]) and o["ruleset"] == ruleset_id):
        bad.append(f"ruleset is not {ruleset_id}")
    if not (isinstance(o.get("version"), str) and VERSION.match(o["version"]) and o["version"] == str(version)):
        bad.append(f"version is not {version}")
    if o.get("approval_tag") != f"{ruleset_id}/v{version}":
        bad.append(f"approval_tag is not {ruleset_id}/v{version}")
    if not (isinstance(o.get("part_sha256"), str) and SHA256.match(o["part_sha256"])):
        bad.append("part_sha256 is not 64 lowercase hex digits")
    left = o.get("left_out", [])
    if not (isinstance(left, list) and all(x in LEFT_OUT_DIRS for x in left)):
        bad.append("left_out names something other than tests/")
    on = o.get("compiled_on")
    if not isinstance(on, dict) or set(on) - {"bundle_id", "release_seq", "commit"}:
        bad.append("compiled_on is not {bundle_id, release_seq, commit}")
    else:
        if not (isinstance(on.get("bundle_id"), str) and BUNDLE_ID.match(on["bundle_id"])):
            bad.append("compiled_on.bundle_id is not a bundle id")
        seq = on.get("release_seq")
        if seq is not None and not (isinstance(seq, int) and not isinstance(seq, bool) and 0 <= seq < 10**9):
            bad.append("compiled_on.release_seq is not a whole number")
        if on.get("commit") is not None and not (isinstance(on["commit"], str) and COMMIT.match(on["commit"])):
            bad.append("compiled_on.commit is not a 40-hex commit")
    pins = o.get("pins")
    if not isinstance(pins, dict) or set(pins) - {"judge_prompt", "terminology_release"}:
        bad.append("pins is not {judge_prompt, terminology_release}")
    else:
        if pins.get("judge_prompt") is not None and not (isinstance(pins["judge_prompt"], str) and
                                                          PROMPT.match(pins["judge_prompt"])):  # fmt: skip
            bad.append("pins.judge_prompt is not a prompt name")
        if pins.get("terminology_release") is not None and not _text(pins["terminology_release"], 100):
            bad.append("pins.terminology_release is not one line of at most 100 characters")
        models = manifest.get("models")
        if pins.get("judge_prompt") != (models.get("judge_prompt") if isinstance(models, dict) else None):
            bad.append("pins.judge_prompt is not the manifest's")
        if pins.get("terminology_release") != manifest.get("terminology_release"):
            bad.append("pins.terminology_release is not the manifest's")
    return bad


def check_origin(
    origin: dict[str, Any], ruleset_id: str, version: str, files: dict[str, bytes], manifest: dict[str, Any]
) -> None:
    """Refuse a part whose record is not of the strict form, names another rule set or version, pins what its manifest
    does not, whose folder holds a file a part does not carry or a file its record does not list, or whose hash is not
    the one recorded."""
    if not isinstance(origin, dict) or origin.get("format") != PART_FORMAT:
        raise PartRefused(f"{ORIGIN} is not a {PART_FORMAT} record")
    bad = _origin_problems(origin, ruleset_id, version, manifest)
    if bad:
        raise PartRefused(f"{ORIGIN} refused: {'; '.join(bad[:5])}")
    extra = sorted(p for p in files if kind_of(p) is None)
    if extra:
        raise PartRefused(f"the part holds files a part does not carry: {extra[:5]}")
    if origin.get("files") != sorted(files):
        raise PartRefused(f"{ORIGIN} does not list exactly the files of the part")
    got = part_sha256(files, origin)
    if got != origin["part_sha256"]:
        raise PartRefused(f"{ruleset_id} v{version}: part sha256 {got} is not the {origin['part_sha256']} its "
                          f"{ORIGIN} records; refused")  # fmt: skip


def open_part(data: bytes) -> tuple[str, dict[str, bytes], dict[str, Any], dict[str, Any]]:
    """``(id, files, manifest, origin)`` of a part, checked as the receiving box checks it (the vendor's tool reads it
    before signing): every member inside the folder or ``ORIGIN.json``, the record's form, pins and hash, every file
    in the export's form, the rule set approved."""
    origin = origin_of(data)
    if origin is None:
        raise PartRefused(f"no {ORIGIN}: not a rule-set part (python -m criteria_compiler.export_part writes one)")
    rid = origin.get("ruleset")
    if not (isinstance(rid, str) and RULESET_ID.match(rid)):
        raise PartRefused(f"{ORIGIN} names no rule set")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in check_ruleset_zip(z) if not n.endswith("/")]
        stray = [n for n in names if n != ORIGIN and PurePosixPath(n).parts[0] != rid]
        if stray:
            raise PartRefused(f"the part holds members outside its folder {rid}/: {stray[:5]}")
        files = {n[len(rid) + 1 :]: z.read(n) for n in names if n != ORIGIN}
    if MANIFEST not in files:
        raise PartRefused("no manifest.yaml")
    manifest = load_yaml(files[MANIFEST], MANIFEST) or {}
    if not isinstance(manifest, dict) or manifest.get("id") != rid or manifest.get("status") != "approved":
        raise PartRefused(f"{rid}: the part's manifest is not the approved {rid}")
    check_origin(origin, rid, str(manifest.get("version")), files, manifest)
    check_neutral(files)
    return rid, files, manifest, origin


def release_of(origin: dict[str, Any]) -> str:
    """The compiling box's release as one line: ``<bundle id> (release_seq N, commit C)`` (checked fields only)."""
    on = origin.get("compiled_on") or {}
    seq = f"release_seq {on.get('release_seq')}" if on.get("release_seq") is not None else ""
    commit = f"commit {str(on['commit'])[:12]}" if on.get("commit") else ""
    extra = ", ".join(x for x in (seq, commit) if x)
    return f"{on.get('bundle_id') or 'unknown'}" + (f" ({extra})" if extra else "")


def tag_note(origin: dict[str, Any], by: str) -> str:
    """What the receiving box adds to the approval tag: the mark, the bundle, the compiling box's release, the hash.
    Only fields :func:`check_origin` accepted, one line."""
    return (f"{ARRIVED_MARK}: {by}; compiled and approved on another box, release {release_of(origin)}, "
            f"its tag {origin['approval_tag']}; part sha256 {origin['part_sha256']}")  # fmt: skip


def part_sha_on_tag(tag_message: str) -> str | None:
    """The part sha256 an approval tag records, from its last field only (``; part sha256 <hash>``, as
    :func:`tag_note` ends it); None when the tag ends otherwise. Never a match anywhere in the message: the person and
    the bundle named before it are not read as a hash."""
    m = re.search(r"; part sha256 ([0-9a-f]{64})\Z", tag_message.rstrip())
    return m.group(1) if m else None


def arrived(tag_message: str) -> bool:
    """Whether an approval tag records a version that arrived in an update (a part, or any offline update, D-77):
    not approved on this box."""
    return ARRIVED_MARK in tag_message or UPDATE_MARK in tag_message
