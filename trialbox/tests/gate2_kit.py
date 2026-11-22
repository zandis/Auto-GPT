"""Gate 2's cross-path test, the machinery (review 2026-11-22 §3.5): drive :mod:`tests.gate2_people`'s people through
every road into the box, read back what the box published, and judge it.

A **road** is one way records enter the box. The source kinds are collected from the product's own code
(:func:`product_kind_sites`: every literal a kind-like name is compared with, matched, contained-tested against or
dict-keyed by, in every ``services/adapter`` module, and the command line's ``choices``); every kind must have a
road, and every drive records the kinds the product actually opened (:class:`Observed`), never a road's say-so.

What is read back is what the box **published**, never a function's return value (:data:`STORE_TYPES`): the served
NDJSON; the screening lake's tables; its note chunks; its retrieval answers per patient (``Lake.search``, BM25 and
the vectors of ``embed_cache.duckdb``); the OMOP CDM tables as stored (every row, whatever ``tb_record`` says); the
lake as OMOP exports it; the EDC drafts built from the lake; and, for a held chart, the patient index and the audit.
Deletion and erasure, the OMOP load (the dual write), the patient registry's alias path (``PidMap.merge``) and the
opt-out worker's OMOP withhold are driven inside the stories.

The judges (:func:`judge`) return findings as text lines ``<invariant> <store> <person>: <what>``; an empty list is a
pass. They never stop at the first finding, so a red run says everything that is wrong at once.
"""

from __future__ import annotations

import ast
import base64
import json
import re
import shutil
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Any

from tests import gate2_people as gp

KEY = bytes(range(101, 133))  # the synthetic site's key: 32 bytes no box uses
SITE = "G2"
TZ = "Asia/Taipei"
ROOT = Path(__file__).resolve().parents[1]
MAPPINGS = {
    "tw": ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
    "jp": ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml",
}
#: the published stores every road is judged over, and the record types each one holds
STORE_TYPES: dict[str, tuple[str, ...]] = {
    "ndjson": gp.TYPES,  # the served snapshot's NDJSON (CURRENT)
    "lake": gp.TYPES,  # the screening lake's tables
    "chunks": ("Chunk",),  # the lake's note chunks (document_chunk: the text BM25 and the vectors are made from)
    "answers": ("Answer",),  # what the lake's retrieval answers for each patient (Lake.search: BM25 + vectors)
    "omop": gp.TYPES,  # the OMOP CDM tables as stored, every row whatever its bookkeeping says
    "omop_export": gp.TYPES,  # the lake as OMOP exports it
    "edc": ("Patient", "Observation"),  # the EDC drafts built from the lake (birth date, uric acid)
}
STORES = tuple(STORE_TYPES)
#: the stores a rebuild from empty is compared on (the EDC drafts and the answers are made on request)
PATH_STORES = ("ndjson", "lake", "chunks", "omop", "omop_export")
_TOKEN = re.compile(r"G2N[A-Z]+")
NIGHTS = ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04")


# ---------------------------------------------------------------------------------------------- the registry
#: the names a source kind travels under in the adapter's code
KIND_NAMES = re.compile(r"^(source_kind|kind|source|door|src_kind|data_source)$")
#: literals the collector finds under those names that are not source kinds, each with where and why. The test
#: fails on a literal in neither this table nor a road, and on an entry here the collector no longer finds
NOT_SOURCE_KINDS: dict[str, str] = {
    "none": "adapter.pipeline and adapter.backfill: settings.registry_source 'none' (no consent registry)",
    "PPR^ZD1": "adapter.sources.ssmix2.source: an HL7 message kind (MSH-9), not a source",
    "coded": "adapter.site_questionnaire: an answer kind of the site questionnaire",
    "jlac10": "adapter.licensed: a licensed code list's kind",
    "medis": "adapter.licensed: a licensed code list's kind",
    "medis_modifier": "adapter.licensed: a licensed code list's kind",
    "yj": "adapter.licensed: a licensed code list's kind",
}
_CASE_FOLDS = ("lower", "upper", "strip", "casefold")


def _kind_name(n: ast.AST) -> str | None:
    while isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _CASE_FOLDS:
        n = n.func.value
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return n.attr
    return None


def _literals(n: ast.AST | None, consts: dict[str, set[str]]) -> set[str]:
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return {n.value}
    if isinstance(n, ast.Tuple | ast.List | ast.Set):
        return {e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    if isinstance(n, ast.Dict):
        return {k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("frozenset", "set", "tuple", "list"):
        return _literals(n.args[0], consts) if n.args else set()
    if isinstance(n, ast.Name):
        return consts.get(n.id, set())
    return set()


def _is_kind(n: ast.AST) -> bool:
    name = _kind_name(n)
    return bool(name and KIND_NAMES.match(name))


def kinds_in_text(text: str, where: str = "<text>") -> set[tuple[str, int, str]]:
    """``(where, line, literal)`` for every string literal a source-kind name (:data:`KIND_NAMES`, also behind
    ``.lower()`` and the like) is compared with (either side; ``==``, ``!=``, ``in``, ``not in``), contained-tested
    against (a literal tuple, list, set or dict, a ``frozenset(...)``, or a module constant holding one), matched by a
    ``match`` statement, or used to key a dict (``{...}[kind]``, ``D[kind]``, ``D.get(kind)``); and the ``choices``
    of an argparse option whose name says kind or source."""
    tree = ast.parse(text)
    consts: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and (v := _literals(node.value, {})):
                    consts[t.id] = v
    out: set[tuple[str, int, str]] = set()

    def add(line: int, values: set[str]) -> None:
        out.update((where, line, v) for v in values)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            for i in range(len(node.ops)):
                for x, y in ((sides[i], sides[i + 1]), (sides[i + 1], sides[i])):
                    if _is_kind(x):
                        add(node.lineno, _literals(y, consts))
        elif isinstance(node, ast.Match) and _is_kind(node.subject):
            for case in node.cases:
                for pat in ast.walk(case.pattern):
                    if isinstance(pat, ast.MatchValue):
                        add(node.lineno, _literals(pat.value, consts))
        elif isinstance(node, ast.Subscript) and _is_kind(node.slice):
            add(node.lineno, _literals(node.value, consts))
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "get" and node.args and _is_kind(node.args[0]):
                add(node.lineno, _literals(f.value, consts))
            for kw in node.keywords:
                if (
                    kw.arg == "choices"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and re.search(r"kind|source", str(node.args[0].value))
                ):
                    add(node.lineno, _literals(kw.value, consts))
    return out


def product_kind_sites() -> set[tuple[str, int, str]]:
    """:func:`kinds_in_text` over every module of ``services/adapter`` (the night, the back-fill, the command line,
    the sources, the site profile and the rest)."""
    base = ROOT / "services" / "adapter"
    out: set[tuple[str, int, str]] = set()
    for f in sorted(base.rglob("*.py")):
        out |= kinds_in_text(f.read_text(encoding="utf-8"), str(f.relative_to(base)))
    return out


def product_source_kinds() -> set[str]:
    """The source kinds the adapter accepts: every literal :func:`product_kind_sites` finds, less the reviewed
    non-kinds of :data:`NOT_SOURCE_KINDS`."""
    return {v for _, _, v in product_kind_sites()} - set(NOT_SOURCE_KINDS)


class Observed:
    """The source kinds the product itself opened while a drive ran: ``adapter.pipeline.make_source`` (also as the
    back-fill imported it) and the bulk reader's constructor are wrapped for the drive, never declared by a road."""

    def __init__(self) -> None:
        self.kinds: set[str] = set()
        self._undo: list[Callable[[], None]] = []

    def __enter__(self) -> Observed:
        from adapter import backfill, pipeline
        from adapter.sources.fhir_bulk import source as bulk

        real = pipeline.make_source

        def make_source(kind: str, *a: Any, **kw: Any) -> Any:
            self.kinds.add(kind)
            return real(kind, *a, **kw)

        init = bulk.FhirBulkSource.__init__

        def bulk_init(obj: Any, *a: Any, **kw: Any) -> None:
            self.kinds.add(bulk.FhirBulkSource.name)
            init(obj, *a, **kw)

        patches: tuple[tuple[Any, str, Any], ...] = (
            (pipeline, "make_source", make_source),
            (backfill, "make_source", make_source),
            (bulk.FhirBulkSource, "__init__", bulk_init),
        )
        for target, attr, new in patches:
            self._undo.append(partial(setattr, target, attr, getattr(target, attr)))
            setattr(target, attr, new)
        return self

    def __exit__(self, *exc: object) -> None:
        for undo in reversed(self._undo):
            undo()


# ---------------------------------------------------------------------------------------------- published rows
@dataclass(frozen=True)
class Row:
    store: str
    rtype: str
    key: str
    pid: str
    marker: str
    ref: str = ""  # a Condition: the key of the visit it points at


def norm_marker(rtype: str, value: Any) -> str:
    if value is None:
        return ""
    if rtype == "Patient":
        return str(value)[:10]
    if rtype == "Encounter":  # minute and second of the visit's start: the same whatever zone the store writes in
        text = value.isoformat() if isinstance(value, datetime) else str(value)
        return text[14:19]
    if rtype == "Observation":
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _subject(r: dict[str, Any]) -> str:
    ref = str((r.get("subject") or r.get("patient") or {}).get("reference") or "")
    return ref.removeprefix("Patient/")


def _fhir_row(store: str, r: dict[str, Any], markers: set[str]) -> Row | None:
    rtype = str(r.get("resourceType"))
    if rtype == "Patient":
        return Row(store, rtype, str(r["id"]), str(r["id"]), norm_marker(rtype, r.get("birthDate")))
    if rtype == "Encounter":
        return Row(store, rtype, str(r["id"]), _subject(r), norm_marker(rtype, (r.get("period") or {}).get("start")))
    if rtype == "Condition":
        codes = [str(c.get("code")) for c in (r.get("code") or {}).get("coding") or []]
        mark = next((c for c in codes if c in markers), codes[0] if codes else "")
        ref = str((r.get("encounter") or {}).get("reference") or "").removeprefix("Encounter/")
        return Row(store, rtype, str(r["id"]), _subject(r), mark, ref)
    if rtype == "Observation":
        return Row(
            store, rtype, str(r["id"]), _subject(r), norm_marker(rtype, (r.get("valueQuantity") or {}).get("value"))
        )
    if rtype == "DocumentReference":
        text = ""
        for c in r.get("content") or []:
            data = (c.get("attachment") or {}).get("data")
            if data:
                text += base64.b64decode(data).decode("utf-8", "replace")
        return Row(store, rtype, str(r["id"]), _subject(r), token(text))
    return None


def token(text: Any) -> str:
    """The note marker in a text ("" when none)."""
    m = _TOKEN.search(str(text or ""))
    return m.group(0) if m else ""


def read_ndjson(lake_dir: Path, markers: set[str]) -> list[Row]:
    from adapter.ndjson import read_type, snapshot_dir
    from adapter.pipeline import _current

    served = _current(lake_dir)
    if served is None:
        return []
    out = []
    for rtype in gp.TYPES:
        for r in read_type(snapshot_dir(lake_dir, served), rtype):
            if (row := _fhir_row("ndjson", r, markers)) is not None:
                out.append(row)
    return out


def read_lake(lake_dir: Path) -> list[Row]:
    from adapter.pipeline import _current
    from lake.store import Lake

    if _current(lake_dir) is None:
        return []
    lake = Lake(lake_dir)
    out = []
    for rtype, sql in (
        ("Patient", "SELECT pid AS k, pid, birth_date AS m FROM patient"),
        ("Encounter", "SELECT eid AS k, pid, start AS m FROM encounter"),
        ("Condition", "SELECT cid AS k, pid, code AS m, eid FROM condition"),
        ("Observation", "SELECT oid AS k, pid, value_num AS m FROM observation"),
        ("DocumentReference", "SELECT did AS k, pid, text AS m FROM document"),
    ):
        for r in lake.query(sql).to_pylist():
            ref = str(r.get("eid") or "")
            mark = token(r["m"]) if rtype == "DocumentReference" else norm_marker(rtype, r["m"])
            out.append(Row("lake", rtype, str(r["k"]), str(r["pid"]), mark, ref))
    for r in lake.query("SELECT chunk_key, pid, text FROM document_chunk").to_pylist():
        out.append(Row("chunks", "Chunk", str(r["chunk_key"]), str(r["pid"]), token(r["text"])))
    return out


def read_answers(lake_dir: Path) -> list[Row]:
    """The lake's retrieval (``Lake.search``: BM25 and the vectors of ``embed_cache.duckdb``, fused) asked, for every
    patient the lake holds a note for, what their notes say: each answer is a chunk the box hands out as that
    patient's."""
    from adapter.pipeline import _current
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    if _current(lake_dir) is None:
        return []
    lake = Lake(lake_dir)
    pids = sorted({str(r["pid"]) for r in lake.query("SELECT DISTINCT pid FROM document").to_pylist()})
    out = []
    for pid in pids:
        try:
            got = lake.search(pid, "follow-up visit marker stable plan", HashEmbedder(), k=5)
        except Exception as exc:  # the box could not answer: said as a row of no one's, never a crash of the judge
            out.append(Row("answers", "Answer", f"error:{pid}", pid, f"unanswered:{type(exc).__name__}"))
            continue
        for a in got:
            out.append(Row("answers", "Answer", f"{a['did']}#{a['chunk_no']}", pid, token(a["text"])))
    return out


def read_omop(lake_dir: Path, db_url: str) -> list[Row]:
    from omop import schema

    db = schema.connect(db_url, schema.schema_for(lake_dir), lake_dir=lake_dir)
    try:
        # every row of the CDM tables as stored. The source key comes from tb_record when it names the row (live or
        # not); a row it does not name is still a row ("cdm:<table>:<id>"). The person's pseudonym comes from the
        # person row, else from the id map: a row whose person row is gone still belongs to someone
        q = {
            "Patient": ("person", "person_id", "c.birth_datetime"),
            "Encounter": ("visit_occurrence", "visit_occurrence_id", "c.visit_start_datetime"),
            "Condition": ("condition_occurrence", "condition_occurrence_id", "c.condition_source_value"),
            "Observation": ("measurement", "measurement_id", "c.value_as_number"),
            "DocumentReference": ("note", "note_id", "c.note_text"),
        }
        out = []
        visit = (
            "(SELECT v.source_record_id FROM tb_record v WHERE v.cdm_table = 'visit_occurrence' "
            "AND v.record_id = c.visit_occurrence_id ORDER BY v.tombstoned_at NULLS FIRST LIMIT 1)"
        )
        for rtype, (table, idcol, mark) in q.items():
            ref = visit if table == "condition_occurrence" else "''"
            rows = db.fetchall(
                f"SELECT c.{idcol}, (SELECT r.source_record_id FROM tb_record r WHERE r.cdm_table = ? "
                f"AND r.record_id = c.{idcol} ORDER BY r.tombstoned_at NULLS FIRST LIMIT 1), "
                f"coalesce((SELECT p.person_source_value FROM person p WHERE p.person_id = c.person_id), "
                f"(SELECT m.source_id FROM tb_id_map m WHERE m.id_kind = 'person' AND m.omop_id = c.person_id)), "
                f"{mark}, {ref} FROM {table} c",
                (table,),
            )
            for rid, k, pid, m, v in rows:
                mark_ = token(m) if rtype == "DocumentReference" else norm_marker(rtype, m)
                key = str(k) if k is not None else f"cdm:{table}:{rid}"
                out.append(Row("omop", rtype, key, str(pid or ""), mark_, str(v or "")))
        return out
    finally:
        db.close()


def read_omop_export(lake_dir: Path, db_url: str) -> list[Row]:
    """The lake as OMOP exports it (``omop.export.export_rows``): the rows a lake rebuilt from the store would hold."""
    from omop import schema
    from omop.export import export_rows

    db = schema.connect(db_url, schema.schema_for(lake_dir), lake_dir=lake_dir)
    try:
        got = export_rows(db)
    finally:
        db.close()
    out = []
    for rtype, table, k, m in (
        ("Patient", "patient", "pid", "birth_date"),
        ("Encounter", "encounter", "eid", "start"),
        ("Condition", "condition", "cid", "code"),
        ("Observation", "observation", "oid", "value_num"),
        ("DocumentReference", "document", "did", "text"),
    ):
        for r in got.get(table, []):
            ref = str(r.get("eid") or "") if rtype == "Condition" else ""
            mark = token(r[m]) if rtype == "DocumentReference" else norm_marker(rtype, r[m])
            out.append(Row("omop_export", rtype, str(r[k]), str(r["pid"]), mark, ref))
    return out


def read_edc(lake_dir: Path, work: Path, subjects: dict[str, tuple[str, str]], draft: int) -> list[Row]:
    """The EDC drafts (``edc.service.EdcService.build``, the synthetic study of ``tests.edc_kit``) for every
    subject: ``subjects`` is record -> (pid, visit date), the pseudonym a coordinator's screening list names. The
    drafts read the box's lake (``edc.prefill.LakeFacts``). Rows: the drafted birth date (Patient) and uric acid
    (Observation), each with its cited row as its key. A subject the box refuses to draft (opted out) has none."""
    from adapter.pipeline import _current
    from edc.prefill import LakeFacts
    from edc.store import EdcError
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from tb_common.optout import opted_out

    from tests import edc_kit

    if not subjects or _current(lake_dir) is None:  # nothing served: nothing to draft from (judged as missing rows)
        return []
    records = [{"record_id": str(i + 1), "tb_screening_no": rec} for i, rec in enumerate(sorted(subjects))]
    facts = LakeFacts(LakeLocal(lake_dir, HashEmbedder(), TZ))
    svc, _, _ = edc_kit.service(work / f"edc-{draft}", records=records)
    svc.facts = lambda: facts
    svc.optouts = opted_out  # as the orchestrator wires it (orchestrator.app.edc_of)
    edc_kit.ready(svc)
    out = []
    for rec, (pid, visit) in sorted(subjects.items()):
        try:
            drafts = svc.build(edc_kit.STUDY, rec, pid, "", visit, "crc")
        except EdcError as exc:
            if exc.code != "edc.opted_out":  # any other refusal is the road failing, said as it is
                raise
            continue
        for d in drafts:
            if d.get("item") not in ("brthdat", "urate"):
                continue
            if d.get("state") != "drafted":  # said as a row of no one's: an undrafted item is a finding with its why
                rtype = "Patient" if d["item"] == "brthdat" else "Observation"
                out.append(Row("edc", rtype, f"{rec}:{d['item']}", pid, f"undrafted:{d.get('why')}"))
                continue
            rtype = "Patient" if d["item"] == "brthdat" else "Observation"
            cite = d.get("citation") or {}
            if isinstance(cite, str):
                cite = json.loads(cite)
            key = f"{rec}:{d['item']}:{cite.get('row', '')}"
            out.append(Row("edc", rtype, key, pid, norm_marker(rtype, d.get("value"))))
    return out


# ---------------------------------------------------------------------------------------------- one box
@dataclass
class NightOutcome:
    snapshot: str
    held: str = ""  # the refusal's type when the night was held (HeldOwner, ...), else ""
    passed: bool = True
    audit: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Box:
    """One TrialBox's stores in a temporary folder and a private database."""

    root: Path
    db_url: str
    mapping: Path

    def __post_init__(self) -> None:
        (self.root / "secrets").mkdir(parents=True, exist_ok=True)
        (self.root / "secrets" / "site_hmac.key").write_bytes(KEY)

    @property
    def lake_dir(self) -> Path:
        return self.root / "lake"

    def cfg(self) -> Any:
        from adapter.pipeline import AdapterConfig
        from embed_service.embedder import HashEmbedder
        from lake.store import Lake
        from tb_contracts import RebuildResult

        lake_dir = self.lake_dir

        def rebuild(snap: str, nd: Path) -> RebuildResult:
            st = Lake(lake_dir).rebuild(snap, HashEmbedder(), nd)
            return RebuildResult(
                snapshot=st.snapshot,
                tables=st.tables,
                chunks=st.chunks,
                embedded_new=st.embedded_new,
                seconds=st.seconds,
            )

        return AdapterConfig(
            lake_dir=lake_dir,
            secrets_dir=self.root / "secrets",
            mapping_path=self.mapping,
            site_id=SITE,
            tz=TZ,
            audit_dir=self.root / "audit",
            rebuild=rebuild,
            db_url=self.db_url,
        )

    def pidmap(self) -> Any:
        from adapter.pidmap import PidMap

        return PidMap(self.root / "secrets" / "pid_map.key", self.db_url)

    def audit_events(self) -> list[dict[str, Any]]:
        out = []
        for f in sorted((self.root / "audit").rglob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def published(self, markers: set[str]) -> list[Row]:
        return (
            read_ndjson(self.lake_dir, markers)
            + read_lake(self.lake_dir)
            + read_answers(self.lake_dir)
            + read_omop(self.lake_dir, self.db_url)
            + read_omop_export(self.lake_dir, self.db_url)
        )


# ---------------------------------------------------------------------------------------------- roads
@dataclass(frozen=True)
class Road:
    """One way into the box. ``first`` and ``later`` run a night (the first load and every later night);
    ``kinds`` names the product's source kinds it drives."""

    name: str
    kinds: tuple[str, ...]
    mapping: str  # tw | jp
    first: Callable[[Box, gp.Story, gp.Night, str, Path], None]
    later: Callable[[Box, gp.Story, gp.Night, str, str, Path], None]
    #: stories this road cannot carry, with why (the input itself cannot say it: never a narrowing of a judge)
    cannot: dict[str, str] = field(default_factory=dict)


class NotPublished(RuntimeError):
    """The night ended without publishing (held by a check, or a failed back-fill): its reasons are the message."""


def _run(box: Box, kind: str, where: str, snap: str, since: str | None) -> None:
    from adapter.pipeline import run_ingest

    rep = run_ingest(box.cfg(), kind, where, since=since, snapshot=snap, load_fhir=False, validate=False)
    if not rep.passed or rep.held:
        raise NotPublished("; ".join(rep.errors or []) or "held")


def _tables(story: gp.Story, night: gp.Night, delta: bool) -> dict[str, list[dict[str, str]]]:
    return gp.table_rows(night, story.people, delta_at="2026-10-01 12:00:00" if delta else "")


def _csv_first(box: Box, story: gp.Story, night: gp.Night, snap: str, work: Path) -> None:
    _run(box, "csv", str(gp.write_csv(work / f"csv-{snap}", _tables(story, night, False))), snap, None)


def _csv_later(box: Box, story: gp.Story, night: gp.Night, snap: str, since: str, work: Path) -> None:
    _run(box, "csv", str(gp.write_csv(work / f"csv-{snap}", _tables(story, night, True))), snap, since)


def _sql_first(box: Box, story: gp.Story, night: gp.Night, snap: str, work: Path) -> None:
    _run(box, "cgrd_sql", gp.write_sqlite(work / f"sql-{snap}.sqlite", _tables(story, night, False)), snap, None)


def _sql_later(box: Box, story: gp.Story, night: gp.Night, snap: str, since: str, work: Path) -> None:
    _run(box, "cgrd_sql", gp.write_sqlite(work / f"sql-{snap}.sqlite", _tables(story, night, True)), snap, since)


def _ssmix2_storage(box: Box) -> Path:
    return box.root / "ssmix2"


def _ssmix2_write(story: gp.Story, night: gp.Night, storage: Path, work: Path, stamp: str) -> None:
    """The night's messages written into the storage the way a hospital's gateway adds them: every file of this
    night carries tonight's 発生日時 (a resend or a correction is a newer file beside the old one), and a record
    deleted at the source is the same file with flag 0."""
    from tb_common import chartno

    from tools.ssmix2_export import STAMP, export

    tmp = work / f"ssmix2-{stamp}"
    # The storage names every folder and file by the patient's ID as the gateway writes it: a chart spelled another
    # way on one record (E's) is not something the storage can hold, so each record is filed under its chart written
    # the site's way (a file whose PID disagrees with its folder is quarantined by the reader and holds the night)
    night = gp.Night(
        night.patients, [replace(r, chart=chartno.normalise(gp.CHART_RULE, r.chart)) for r in night.records]
    )
    deleted = {(r.chart, r.number) for r in night.records if r.deleted}
    # one export per person: the exporter keys visits by their number alone (``enc_by_no``), a test tool's shortcut
    # that would drop A's visit "V1" behind B's before the box ever saw it
    letters = sorted({p.letter for p, _ in night.patients} | {r.person for r in night.records})
    for letter in letters:
        one = gp.Night(
            [pc for pc in night.patients if pc[0].letter == letter], [r for r in night.records if r.person == letter]
        )
        csv_dir = gp.write_csv(tmp / letter / "csv", gp.table_rows(one, story.people))
        export(csv_dir, tmp / letter / "storage")
        _ssmix2_copy(tmp / letter / "storage", storage, stamp, deleted, STAMP)
    # the tables SS-MIX2 does not standardise (the notes among them) sit in the extended folder as tonight's CSV
    from adapter.sources.ssmix2.source import TYPES as STANDARD

    ext = gp.write_csv(tmp / "extended", gp.table_rows(night, story.people))
    (storage / "extended").mkdir(parents=True, exist_ok=True)
    for f in ext.glob("*.csv"):
        if f.stem not in STANDARD:
            shutil.copyfile(f, storage / "extended" / f.name)


def _ssmix2_copy(src: Path, storage: Path, stamp: str, deleted: set[tuple[str, str]], exported: str) -> None:
    for f in src.rglob("*"):
        if not f.is_file() or "extended" in f.relative_to(src).parts[:1] or "extended_storage" in f.parts:
            continue
        rel = f.relative_to(src)
        parts = f.name.split("_")
        if len(parts) == 7 and parts[4] == exported:
            parts[4] = stamp
            if (parts[0], parts[3]) in deleted:
                parts[6] = "0"
        dest = storage / rel.parent / "_".join(parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dest)


def _ssmix2_first(box: Box, story: gp.Story, night: gp.Night, snap: str, work: Path) -> None:
    _ssmix2_write(story, night, _ssmix2_storage(box), work, snap.replace("-", "") + "000000000")
    _run(box, "ssmix2", str(_ssmix2_storage(box)), snap, None)


def _ssmix2_later(box: Box, story: gp.Story, night: gp.Night, snap: str, since: str, work: Path) -> None:
    _ssmix2_write(story, night, _ssmix2_storage(box), work, snap.replace("-", "") + "000000000")
    _run(box, "ssmix2", str(_ssmix2_storage(box)), snap, since)


def _bulk(sources: tuple[str, ...]) -> tuple[Callable[..., None], Callable[..., None]]:
    def write(story: gp.Story, night: gp.Night, out: Path) -> Path:
        gp.write_bulk(out, gp.bulk_resources(night, sources, story))
        dead = [r for r in night.records if r.deleted and r.source in sources]
        if dead:
            rtype = {
                "encounter": "Encounter",
                "diagnosis": "Condition",
                "lab": "Observation",
                "note": "DocumentReference",
            }
            bundle = {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {"request": {"method": "DELETE", "url": f"{rtype[r.table]}/{gp.bulk_id(r, story)}"}} for r in dead
                ],
            }
            (out / "deleted").mkdir(exist_ok=True)
            (out / "deleted" / "deleted.ndjson").write_text(json.dumps(bundle) + "\n", encoding="utf-8")
        return out

    def first(box: Box, story: gp.Story, night: gp.Night, snap: str, work: Path) -> None:
        _run(box, "fhir_bulk", str(write(story, night, work / f"bulk-{snap}")), snap, None)

    def later(box: Box, story: gp.Story, night: gp.Night, snap: str, since: str, work: Path) -> None:
        _run(box, "fhir_bulk", str(write(story, night, work / f"bulk-{snap}")), snap, since)

    return first, later


#: the back-fill's commit boundary for the pid map (``adapter.backfill.PID_BATCH``, 5,000 on a box): two rows here,
#: so a hospital of a dozen people crosses it several times
BACKFILL_BATCH = 2


def _backfill_first(box: Box, story: gp.Story, night: gp.Night, snap: str, work: Path) -> None:
    from adapter import backfill

    old = backfill.PID_BATCH
    backfill.PID_BATCH = BACKFILL_BATCH
    try:
        src = gp.write_csv(work / f"backfill-{snap}", _tables(story, night, False))
        rep = backfill.backfill(box.cfg(), "csv", str(src), snapshot=snap, validate=False)
        if rep.state != "published":
            raise NotPublished(f"back-fill {rep.state}: " + "; ".join(rep.errors + rep.incomplete))
    finally:
        backfill.PID_BATCH = old


_bulk_one = _bulk(("sysA",))
_bulk_two = _bulk(("sysA", "sysB"))
NO_NATIONAL = "the source carries no national identifier (SS-MIX2 PID has none in this storage)"
ONE_PATIENT_FILE = (
    "the storage holds one demographic message per chart (ADT-00 at '-' / '-'); a newer one is a "
    "correction by the specification, not a second patient"
)
ROADS: tuple[Road, ...] = (
    Road("csv", ("csv",), "tw", _csv_first, _csv_later),
    Road("cgrd_sql", ("cgrd_sql",), "tw", _sql_first, _sql_later),
    Road(
        "ssmix2",
        ("ssmix2",),
        "jp",
        _ssmix2_first,
        _ssmix2_later,
        cannot={
            "conflict_birth": ONE_PATIENT_FILE,
            "conflict_national": NO_NATIONAL,
            "conflict_birth_later": ONE_PATIENT_FILE,
            "conflict_national_later": NO_NATIONAL,
        },
    ),
    Road("fhir_bulk_one", ("fhir_bulk",), "tw", _bulk_one[0], _bulk_one[1]),
    Road("fhir_bulk_two", ("fhir_bulk",), "tw", _bulk_two[0], _bulk_two[1]),
    Road("backfill", ("csv",), "tw", _backfill_first, _csv_later),
)
ROAD = {r.name: r for r in ROADS}


def road_people(road: Road, story: gp.Story) -> gp.Story:
    """The story as the road carries it: a single-source bulk export holds only system A's people."""
    if road.name != "fhir_bulk_one":
        return story
    keep = {p.letter for p in story.people.values() if p.source == "sysA"}
    exp = Counter({k: v for k, v in story.expected.items() if k[0] in keep})
    return replace(story, held=story.held & keep, expected=exp)


# ---------------------------------------------------------------------------------------------- a story on a road
@dataclass
class Drive:
    story: gp.Story
    box: Box
    nights: list[NightOutcome]
    after: list[list[Row]]  # the published rows after each night (the last: with the first EDC draft)
    replay: list[Row]  # after the last night was sent again, as the next night (with the second EDC draft)
    rebuilt: list[Row] | None = None  # the same box's lake rebuilt from empty with the hospital as published
    effective_optouts: set[str] = field(default_factory=set)
    held_pids: set[str] = field(default_factory=set)
    pidmap_held: dict[str, Any] = field(default_factory=dict)
    kinds: set[str] = field(default_factory=set)  # the source kinds the product opened (observed)
    edc: bool = True  # the EDC drafts were made (and so are judged)


def _record_between(box: Box, story: gp.Story, i: int) -> None:
    from tb_common.crypto import pid_for_mrn
    from tb_common.optout import OptOutRegister

    merges = story.merges.get(i, [])
    if merges:
        pm = box.pidmap()
        try:
            for old, new, why in merges:
                pm.merge(KEY, old, new, why, f"G2-{why}")
        finally:
            pm.close()
    if i == 1 and story.optouts:
        reg = OptOutRegister(box.db_url)
        try:
            for chart in story.optouts:
                reg.add(pid_for_mrn(KEY, chart), "office", "", "g2-steward", "2026-10-01T13:00:00+08:00")
        finally:
            reg.close()


def _withhold(box: Box) -> set[str]:
    """The opt-out worker's OMOP step (``omop.load.withhold`` of the register's effective set, aliases followed)."""
    from omop import schema
    from omop.load import withhold
    from tb_common.optout import OptOutRegister

    reg = OptOutRegister(box.db_url)
    try:
        eff = reg.effective()
    finally:
        reg.close()
    if eff:
        db = schema.connect(box.db_url, schema.schema_for(box.lake_dir), lake_dir=box.lake_dir)
        try:
            withhold(db, eff)
        finally:
            db.close()
    return eff


def _night(box: Box, run: Callable[[], None], snap: str) -> NightOutcome:
    from tb_common.identity import HeldOwner

    out = NightOutcome(snap)
    try:
        run()
    except HeldOwner as exc:
        out.held, out.passed = type(exc).__name__, False
    except NotPublished as exc:
        out.held, out.passed = f"not published ({str(exc)[:300]})", False
    return out


def surviving_chart(story: gp.Story, chart: str) -> str:
    from tb_common import chartno

    surviving = {old: new for merges in story.merges.values() for old, new, _ in merges}
    c = chartno.normalise(gp.CHART_RULE, chart)
    while c in surviving:
        c = surviving[c]
    return c


def full_state(story: gp.Story, published: Iterable[int]) -> gp.Night:
    """The hospital as the published nights leave it, as one full export: every live record in its latest version,
    filed under its person's surviving chart (a held night is no part of it)."""
    nights = [story.nights[i] for i in published]
    latest: dict[tuple[str, str, str], gp.Rec] = {}
    pats: dict[str, tuple[gp.Person, str]] = {}
    for n in nights:
        for p, c in n.patients:
            pats.setdefault(surviving_chart(story, c), (p, surviving_chart(story, c)))
        for r in n.records:
            latest[(r.person, r.table, r.number)] = r
    recs = [replace(r, chart=surviving_chart(story, r.chart)) for r in latest.values() if not r.deleted]
    return gp.Night(list(pats.values()), recs)


def edc_subjects(story: gp.Story) -> dict[str, tuple[str, str]]:
    """record -> (pid, visit date) for every person the story expects to be published with a visit: the pid a
    coordinator's list names (the person's surviving chart), the day of their first visit."""
    from tb_common.crypto import pid_for_mrn

    out = {}
    for letter, p in story.people.items():
        if not story.expected[(letter, "Patient")] and letter not in story.optout_letters():
            continue
        visits = [r for n in story.nights for r in n.records if r.person == letter and r.table == "encounter"]
        if visits:
            out[f"S-{letter}"] = (pid_for_mrn(KEY, surviving_chart(story, p.chart)), visits[0].when[:10])
    return out


def drive(road: Road, story: gp.Story, order: str, root: Path, db_url: str, *, edc: bool = True) -> Drive:
    """Run ``story`` on ``road`` with every night's rows in ``order``; draft the EDC record of every subject; send
    the last night again as the next night (replay) and draft again; then rebuild the same box's lake from empty
    with the hospital as the published nights leave it."""
    story = road_people(road, story)
    with Observed() as seen:
        d = _drive(road, story, order, root, db_url, edc)
    d.kinds = seen.kinds
    return d


def _drive(road: Road, story: gp.Story, order: str, root: Path, db_url: str, edc: bool) -> Drive:
    box = Box(root / "box", db_url, MAPPINGS[road.mapping])
    work = root / "work"
    markers = set(story.owner_of())
    subjects = edc_subjects(story) if edc else {}
    nights: list[NightOutcome] = []
    after: list[list[Row]] = []
    last_good: str | None = None
    for i, night in enumerate(story.nights):
        _record_between(box, story, i)
        snap = NIGHTS[i]
        n = gp.ordered(night, order)
        if i == 0 or (story.held and not story.later):  # a first night, or the whole hospital again with a conflict
            out = _night(box, partial(road.first, box, story, n, snap, work), snap)
        else:  # a later night: a delta over the last published night (or, when none was, the night before: the
            # product then says itself that it has nothing to merge over)
            since = last_good or NIGHTS[i - 1]
            out = _night(box, partial(road.later, box, story, n, snap, since, work), snap)
        if out.passed:
            last_good = snap
        nights.append(out)
        after.append(box.published(markers))
    eff = _withhold(box) if story.optouts else set()
    after[-1] = box.published(markers) + (read_edc(box.lake_dir, work, subjects, 1) if edc else [])
    # replay: the last night sent again as the next night (a full night as a full night, a delta as a delta)
    snap = NIGHTS[len(story.nights)]
    last = gp.ordered(story.nights[-1], order)
    if len(story.nights) == 1 or (story.held and not story.later) or last_good is None:
        nights.append(_night(box, partial(road.first, box, story, last, snap, work), snap))
    else:
        nights.append(_night(box, partial(road.later, box, story, last, snap, last_good, work), snap))
    if story.optouts:
        _withhold(box)
    replay = box.published(markers) + (read_edc(box.lake_dir, work, subjects, 2) if edc else [])
    d = Drive(story, box, nights, after, replay, effective_optouts=eff, edc=edc)
    if story.held:
        from tb_common.crypto import pid_for_mrn

        d.held_pids = {pid_for_mrn(KEY, story.people[x].chart) for x in story.held}
        pm = box.pidmap()
        try:
            d.pidmap_held = {p: (pm.resolve(p), pm.identity(p)) for p in d.held_pids}
        finally:
            pm.close()
    # rebuild from empty: the same box (its patient index, merges and opt-out register) with an empty lake, fed the
    # hospital as the published nights left it, as one full night
    published = [i for i, n in enumerate(nights[: len(story.nights)]) if n.passed]
    other = Box(root / "rebuilt", db_url, MAPPINGS[road.mapping])
    shutil.copytree(box.root / "secrets", other.root / "secrets", dirs_exist_ok=True)
    if published:
        _night(
            other,
            partial(
                road.first,
                other,
                story,
                gp.ordered(full_state(story, published), order),
                NIGHTS[0],
                root / "work-rebuilt",
            ),
            NIGHTS[0],
        )
        if story.optouts:
            _withhold(other)
    d.rebuilt = other.published(markers)
    return d


# ---------------------------------------------------------------------------------------------- the case matrix
STORIES: dict[str, Callable[[], gp.Story]] = {
    "one_night": gp.one_night_story,
    "corrections": gp.corrections_story,
    "conflict_birth": partial(gp.conflict_story, ("J", "K")),
    "conflict_national": partial(gp.conflict_story, ("M", "N")),
    "conflict_birth_later": partial(gp.conflict_story, ("J", "K"), later=True),
    "conflict_national_later": partial(gp.conflict_story, ("M", "N"), later=True),
}
#: the stories whose outcome can turn on the order of rows (corrections and merges, the opt-out under an alias, the
#: conflicts within a night and across nights): every order runs in the unit tier
ORDER_SENSITIVE = frozenset(
    {"corrections", "conflict_birth", "conflict_national", "conflict_birth_later", "conflict_national_later"}
)
#: every road with every story its input can say (a road's ``cannot`` names the stories its source format has no
#: way to write, and why), in every order
ALL_CASES = [(r.name, s, o) for r in ROADS for s in STORIES if s not in r.cannot for o in gp.ORDERS]
UNIT_CASES = [c for c in ALL_CASES if c[1] in ORDER_SENSITIVE or c[2] == "as_written"]
NIGHTLY_CASES = [c for c in ALL_CASES if c not in UNIT_CASES]


def run_case(road: str, story: str, order: str, root: Path, db_url: str) -> list[str]:
    """One case of the matrix: the story on the road in the order, replayed and rebuilt, judged. The EDC drafts
    read the lake, which every order's case judges; they are drafted (twice) in the as-written order."""
    r = ROAD[road]
    d = drive(r, STORIES[story](), order, root, db_url, edc=order == "as_written")
    observed = (
        []
        if d.kinds == set(r.kinds)
        else [f"registry store=- person=-: {road} declares {sorted(r.kinds)}; the product opened {sorted(d.kinds)}"]
    )
    return observed + judge(d)


# ---------------------------------------------------------------------------------------------- the judges
def expected_for(story: gp.Story, store: str) -> Counter[tuple[str, str]]:
    """(person, type) -> how many rows ``store`` must hold after the last night. The opted-out people are left
    out: they must hold none anywhere, and :func:`opt_out` says so for every row of theirs."""
    out: Counter[tuple[str, str]] = Counter()
    gone = story.optout_letters()
    for (who, rtype), n in story.expected.items():
        if who in gone or n <= 0:
            continue
        if store in ("chunks", "answers"):
            if rtype == "DocumentReference":
                out[(who, "Chunk" if store == "chunks" else "Answer")] += n
        elif store == "edc":  # a subject is drafted for each person still published as a patient
            if rtype in ("Patient", "Observation") and story.expected[(who, "Patient")] > 0:
                out[(who, rtype)] = 1
        elif rtype in STORE_TYPES[store]:
            out[(who, rtype)] += n
    return out


def judge(d: Drive) -> list[str]:
    """Every finding of the six invariants over the published stores; [] when all hold."""
    story = d.story
    owner = story.owner_of()
    same = merged_people(story)
    out: list[str] = []
    final = d.after[-1]
    held = [n for n in d.nights if n.held]
    if story.held:
        out += hold(d, held)
        if not d.nights[0].passed:  # the night before the conflict has none in it: its refusal is said as one
            out.append(
                f"published store=night person=-: night {d.nights[0].snapshot} was not published: {d.nights[0].held}"
            )
    elif held:
        out += [f"published store=night person=-: night {n.snapshot} was not published: {n.held}" for n in held]
    any_published = any(n.passed for n in d.nights)
    for store in STORES:
        if store == "edc" and not d.edc:
            continue
        rows = [r for r in final if r.store == store]
        want = expected_for(story, store)
        if any_published and want.total() and not rows:
            out.append(f"read store={store} person=-: nothing read where {want.total()} rows are expected")
        out += sharing(store, rows, owner, same)
        out += references(store, rows, owner, same)
        out += splitting(store, rows, owner, story, want)
    if story.optouts:
        out += opt_out(final, owner, story, d.effective_optouts, "after the last night")
        out += opt_out(d.replay, owner, story, d.effective_optouts, "after the replay")
        out += opt_out(d.rebuilt or [], owner, story, d.effective_optouts, "after the rebuild from empty")
    out += stability(d.after, d.replay, owner, story)
    if d.rebuilt is not None:
        out += path(final, d.rebuilt, owner)
    return out


def _who(r: Row, owner: dict[str, str]) -> str:
    return owner.get(r.marker, f"?{r.marker}")


def merged_people(story: gp.Story) -> dict[str, str]:
    """person -> the person they are after the recorded merges (I is H once I's chart is merged into H's)."""
    by_chart = {p.chart: p.letter for p in story.people.values()}
    out = {}
    for merges in story.merges.values():
        for old, new, _ in merges:
            if old in by_chart and new in by_chart:
                out[by_chart[old]] = by_chart[new]
    return out


def merge_named(story: gp.Story) -> set[str]:
    """The people a recorded merge or correction names (its old or its new chart is theirs)."""
    out = set()
    for merges in story.merges.values():
        for old, new, _ in merges:
            out |= {x for x, p in story.people.items() if p.chart in (old, new)}
    return out


def sharing(store: str, rows: list[Row], owner: dict[str, str], same: dict[str, str]) -> list[str]:
    """No published row (and no pseudonym) is reachable from two people."""
    out = []
    by_pid: dict[str, set[str]] = defaultdict(set)
    by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        who = same.get(_who(r, owner), _who(r, owner))
        by_pid[r.pid].add(who)
        by_key[(r.rtype, r.key)].add(who)
    for pid, people in sorted(by_pid.items()):
        if len(people) > 1:
            out.append(
                f"no-sharing store={store} person={'+'.join(sorted(people))}: one pseudonym {pid[:8]} holds "
                f"records of {len(people)} people"
            )
    for (rtype, key), people in sorted(by_key.items()):
        if len(people) > 1:
            out.append(
                f"no-sharing store={store} person={'+'.join(sorted(people))}: one {rtype} key {key[:12]} "
                f"reached from {len(people)} people"
            )
    for r in rows:
        if r.marker not in owner:
            out.append(f"no-sharing store={store} person=?: a {r.rtype} row with no person's marker ({r.marker!r})")
    return out


def references(store: str, rows: list[Row], owner: dict[str, str], same: dict[str, str]) -> list[str]:
    """No sharing through a reference: a published Condition's visit is a published visit of the same person."""
    out = []
    visits = {r.key: same.get(_who(r, owner), _who(r, owner)) for r in rows if r.rtype == "Encounter"}
    for r in rows:
        if r.rtype != "Condition" or not r.ref:
            continue
        who = same.get(_who(r, owner), _who(r, owner))
        if r.ref not in visits:
            out.append(
                f"no-sharing store={store} person={who}: a Condition points at a visit {r.ref[:12]} not published"
            )
        elif visits[r.ref] != who:
            out.append(
                f"no-sharing store={store} person={who}+{visits[r.ref]}: a Condition reaches another person's visit"
            )
    return out


def splitting(
    store: str, rows: list[Row], owner: dict[str, str], story: gp.Story, want: Counter[tuple[str, str]]
) -> list[str]:
    """Each source record of each person exactly once, under one pseudonym, the counts the table expects."""
    out = []
    gone = story.optout_letters()
    pids: dict[str, set[str]] = defaultdict(set)
    got: Counter[tuple[str, str]] = Counter()
    per_marker: Counter[tuple[str, str]] = Counter()
    for r in rows:
        who = _who(r, owner)
        if who in gone:
            continue
        pids[who].add(r.pid)
        got[(who, r.rtype)] += 1
        per_marker[(r.rtype, r.marker)] += 1
    merged_into = merged_people(story)
    groups: dict[str, set[str]] = defaultdict(set)
    for who, ps in pids.items():
        groups[merged_into.get(who, who)] |= ps
    for who, ps in sorted(groups.items()):
        if len(ps) > 1:
            out.append(f"no-splitting store={store} person={who}: one person under {len(ps)} pseudonyms")
    for (who, rtype), n in sorted(want.items()):
        if got[(who, rtype)] != n:
            out.append(f"no-splitting store={store} person={who}: {got[(who, rtype)]} {rtype} rows, expected {n}")
    for (who, rtype), n in sorted(got.items()):
        if (who, rtype) not in want and who in story.people:
            out.append(f"no-splitting store={store} person={who}: {n} {rtype} rows, expected 0")
    for (rtype, m), n in sorted(per_marker.items()):
        if n > 1:
            out.append(
                f"no-splitting store={store} person={owner.get(m, '?')}: one source record ({rtype} {m}) "
                f"published {n} times"
            )
    for m in sorted(story.gone):
        if any(mk == m for _, mk in per_marker):
            out.append(
                f"no-splitting store={store} person={owner.get(m, '?')}: a replaced or deleted version ({m}) "
                f"is still published"
            )
    return out


def opt_out(rows: list[Row], owner: dict[str, str], story: gp.Story, eff: set[str], when: str) -> list[str]:
    """Opt-out survives: the opted-out person's records are absent from every store, under every alias."""
    from tb_common.crypto import pid_for_mrn

    out = []
    opted = story.optout_letters()
    if when == "after the last night" and not {pid_for_mrn(KEY, c) for c in story.optouts} <= eff:
        out.append(f"opt-out store=register person={'+'.join(sorted(opted))}: the opt-out as typed is not in force")
    held: Counter[tuple[str, str, str]] = Counter()
    for r in rows:
        if _who(r, owner) in opted:
            held[(r.store, _who(r, owner), r.rtype)] += 1
    for (store, who, rtype), n in sorted(held.items()):
        out.append(f"opt-out store={store} person={who}: {n} {rtype} rows present {when}")
    return out


def hold(d: Drive, held: list[NightOutcome]) -> list[str]:
    """Hold, do not guess: the conflicting night publishes nothing for the chart, and the hold is visible."""
    out = []
    story = d.story
    letters = "+".join(sorted(story.held))
    conflict = d.nights[1:2] if story.later else d.nights[1:-1] or d.nights[1:2]
    if not any(not n.passed for n in conflict):
        out.append(f"hold store=night person={letters}: the conflicting night was published, not held")
    owner = story.owner_of()
    absent = {x for x in story.held if not story.expected[(x, "Patient")]}
    for rows, when in ((d.after[-1], "after the conflict night"), (d.replay, "after the replay")):
        n_rows: Counter[tuple[str, str]] = Counter()
        for r in rows:
            if (not story.later and r.pid in d.held_pids) or _who(r, owner) in absent:
                n_rows[(r.store, r.rtype)] += 1
        for (store, rtype), n in sorted(n_rows.items()):
            out.append(f"hold store={store} person={letters}: {n} {rtype} rows of the held chart published {when}")
    if not story.later:
        for pid, (chart, identity) in sorted(d.pidmap_held.items()):
            if chart is not None or identity is not None:
                out.append(
                    f"hold store=pidmap person={letters}: the conflicting chart {pid[:8]} entered the patient index "
                    f"({'reverse map' if chart is not None else ''}{' identity' if identity is not None else ''})"
                )
    events = [e for e in d.box.audit_events() if str(e.get("event", "")).startswith("ingest.")]
    if (
        held
        and not any(
            e.get("event") == "ingest.failed" and (e.get("detail") or {}).get("error") in ("HeldOwner",) for e in events
        )
        and not any(e.get("event") in ("ingest.held", "backfill.held") for e in events)
    ):
        out.append(f"hold store=audit person={letters}: the hold is not visible in the audit")
    return out


def stability(after: list[list[Row]], replay: list[Row], owner: dict[str, str], story: gp.Story) -> list[str]:
    """Key stability and idempotence: the replay publishes exactly what the last night did (keys, pseudonyms and
    values as sets); between nights a record keeps its key unless a recorded merge or correction names its person,
    and an old key is never left live beside the new one."""
    out = []
    before = {(r.store, r.rtype, r.key, r.pid, r.marker) for r in after[-1]}
    again = {(r.store, r.rtype, r.key, r.pid, r.marker) for r in replay}
    for t in sorted(before ^ again):
        where = "after the replay only" if t in again else "before the replay only"
        out.append(f"stability store={t[0]} person={owner.get(t[4], '?')}: {t[1]} {t[2][:12]} {where}")
    if len(after) > 1:
        named = merge_named(story)
        first = {(r.store, r.rtype, r.marker): r.key for r in after[0]}
        last = {(r.store, r.rtype, r.marker): r.key for r in after[-1]}
        live: dict[str, set[str]] = defaultdict(set)
        for r in after[-1]:
            live[r.store].add(r.key)
        for (store, rtype, m), k in sorted(first.items()):
            if (store, rtype, m) in last and last[(store, rtype, m)] != k:
                who = owner.get(m, "?")
                if k in live[store]:
                    out.append(
                        f"stability store={store} person={who}: {rtype}'s key changed and the old key is still live"
                    )
                elif who not in named:
                    out.append(
                        f"stability store={store} person={who}: {rtype}'s key changed between nights with no "
                        f"correction recorded for them"
                    )
    return out


def path(incremental: list[Row], rebuilt: list[Row], owner: dict[str, str]) -> list[str]:
    """Path independence: the incremental stores equal a rebuild from empty, keys compared as sets."""
    out = []
    for store in PATH_STORES:
        a = {(r.rtype, r.key, r.pid, r.marker) for r in incremental if r.store == store}
        b = {(r.rtype, r.key, r.pid, r.marker) for r in rebuilt if r.store == store}
        for t in sorted(a - b):
            out.append(
                f"path-independence store={store} person={owner.get(t[3], '?')}: {t[0]} {t[1][:12]} only in "
                f"the incremental store"
            )
        for t in sorted(b - a):
            out.append(
                f"path-independence store={store} person={owner.get(t[3], '?')}: {t[0]} {t[1][:12]} only in "
                f"the rebuild from empty"
            )
    return out


def summary(findings: Iterable[str]) -> str:
    return "\n".join(findings)


def today() -> date:
    return date.today()
