"""Gate 2's cross-path test, the machinery (review 2026-11-22 §3.5): drive :mod:`tests.gate2_people`'s people through
every road into the box, read back what the box published, and judge it.

A **road** is one way records enter the box. The roads are enumerated from the product: :func:`product_source_kinds`
reads the source kinds the adapter accepts out of ``adapter.pipeline`` (``make_source``'s branches and
``run_ingest``'s own ``fhir_bulk`` branch), and :data:`ROADS` must give every kind at least one road, so a new
connector with no road fails the test that checks it.

What is read back is what the box **published**, never a function's return value:

* ``ndjson``: the served snapshot's NDJSON (``CURRENT``), the lake's input and the source of every rebuild;
* ``lake``: the screening lake's tables (DuckDB, ``lake.store.Lake``), what every screening query reads;
* ``omop``: the OMOP store of record (``tb_record`` and the CDM rows, PostgreSQL), filled by the dual write;
* ``pidmap``: the patient index (the reverse map and the identity rows), for the held chart only.

The judges (:func:`judge`) return findings as text lines ``<invariant> <store> <person>: <what>``; an empty list is a
pass. They never stop at the first finding, so a red run says everything that is wrong at once.
"""

from __future__ import annotations

import ast
import inspect
import json
import shutil
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
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
#: the published stores every road is judged over
STORES = ("ndjson", "lake", "omop", "omop_export")
NIGHTS = ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04")


# ---------------------------------------------------------------------------------------------- the registry
def product_source_kinds() -> set[str]:
    """Every source kind the adapter's night accepts, read from the product's code: the string compared with
    ``kind`` in ``adapter.pipeline.make_source`` and with ``source_kind`` in ``adapter.pipeline._run_ingest``."""
    from adapter import pipeline

    kinds: set[str] = set()
    for fn, name in ((pipeline.make_source, "kind"), (pipeline._run_ingest, "source_kind")):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == name:
                for op, right in zip(node.ops, node.comparators, strict=True):
                    if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) and isinstance(right.value, str):
                        kinds.add(right.value)
                    if isinstance(op, ast.In) and isinstance(right, ast.Tuple):
                        kinds |= {
                            e.value for e in right.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        }
    return kinds


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
    return None


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
    ):
        for r in lake.query(sql).to_pylist():
            ref = str(r.get("eid") or "")
            out.append(Row("lake", rtype, str(r["k"]), str(r["pid"]), norm_marker(rtype, r["m"]), ref))
    return out


def read_omop(lake_dir: Path, db_url: str) -> list[Row]:
    from omop import schema

    db = schema.connect(db_url, schema.schema_for(lake_dir), lake_dir=lake_dir)
    try:
        q = {
            "Patient": ("person", "person_id", "p.birth_datetime"),
            "Encounter": ("visit_occurrence", "visit_occurrence_id", "c.visit_start_datetime"),
            "Condition": ("condition_occurrence", "condition_occurrence_id", "c.condition_source_value"),
            "Observation": ("measurement", "measurement_id", "c.value_as_number"),
        }
        out = []
        # a condition's visit, by the visit's own source key (the key the box published for it)
        visit = (
            "(SELECT v.source_record_id FROM tb_record v WHERE v.cdm_table = 'visit_occurrence' "
            "AND v.record_id = c.visit_occurrence_id AND v.tombstoned_at IS NULL LIMIT 1)"
        )
        for rtype, (table, idcol, mark) in q.items():
            src = "person c" if table == "person" else f"{table} c"
            ref = visit if table == "condition_occurrence" else "''"
            rows = db.fetchall(
                f"SELECT r.source_record_id, p.person_source_value, {mark}, {ref} FROM tb_record r "
                f"JOIN {src} ON c.{idcol} = r.record_id JOIN person p ON p.person_id = c.person_id "
                f"WHERE r.resource_type = ? AND r.cdm_table = ? AND r.tombstoned_at IS NULL",
                (rtype, table),
            )
            out += [Row("omop", rtype, str(k), str(pid), norm_marker(rtype, m), str(v or "")) for k, pid, m, v in rows]
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
    ):
        for r in got.get(table, []):
            ref = str(r.get("eid") or "") if rtype == "Condition" else ""
            out.append(Row("omop_export", rtype, str(r[k]), str(r["pid"]), norm_marker(rtype, r[m]), ref))
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
        night.patients,
        [
            gp.Rec(
                r.person,
                r.table,
                r.number,
                chartno.normalise(gp.CHART_RULE, r.chart),
                r.when,
                r.marker,
                r.source,
                r.deleted,
            )
            for r in night.records
        ],
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
    (storage / "extended").mkdir(parents=True, exist_ok=True)
    for letter in letters[:1]:
        for f in (tmp / letter / "storage" / "extended").glob("*.csv"):
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
            rtype = {"encounter": "Encounter", "diagnosis": "Condition", "lab": "Observation"}
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
        cannot={"conflict_birth": ONE_PATIENT_FILE, "conflict_national": NO_NATIONAL},
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
    return gp.Story(story.people, story.nights, story.merges, story.optouts, story.held & keep, exp, story.gone)


# ---------------------------------------------------------------------------------------------- a story on a road
@dataclass
class Drive:
    story: gp.Story
    box: Box
    nights: list[NightOutcome]
    after: list[list[Row]]  # the published rows after each night
    replay: list[Row]  # after the last night was sent again, as the next night
    rebuilt: list[Row] | None = None  # a box rebuilt from empty with the hospital as it stands at the end
    effective_optouts: set[str] = field(default_factory=set)
    held_pids: set[str] = field(default_factory=set)
    pidmap_held: dict[str, Any] = field(default_factory=dict)


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


def full_state(story: gp.Story) -> gp.Night:
    """The hospital as it stands after the story's last night, as a full export: every live record in its latest
    version, filed under its person's surviving chart."""
    surviving: dict[str, str] = {}
    for merges in story.merges.values():
        for old, new, _ in merges:
            surviving[old] = new

    def chart(c: str) -> str:
        from tb_common import chartno

        c = chartno.normalise(gp.CHART_RULE, c)
        while c in surviving:
            c = surviving[c]
        return c

    latest: dict[tuple[str, str, str], gp.Rec] = {}
    for n in story.nights:
        for r in n.records:
            latest[(r.person, r.table, r.number)] = r
    pats: dict[str, tuple[gp.Person, str]] = {}
    for p, c in story.nights[0].patients:
        pats.setdefault(chart(c), (p, chart(c)))
    recs = [
        gp.Rec(r.person, r.table, r.number, chart(r.chart), r.when, r.marker, r.source)
        for r in latest.values()
        if not r.deleted
    ]
    return gp.Night(list(pats.values()), recs)


def drive(road: Road, story: gp.Story, order: str, root: Path, db_url: str, *, rebuild: bool = False) -> Drive:
    """Run ``story`` on ``road`` with every night's rows in ``order``; then the last night again as the next night
    (replay); with ``rebuild``, also the hospital as it stands at the end into a second box from empty."""
    story = road_people(road, story)
    box = Box(root / "box", db_url, MAPPINGS[road.mapping])
    work = root / "work"
    markers = set(story.owner_of())
    nights: list[NightOutcome] = []
    after: list[list[Row]] = []
    last_good: str | None = None
    for i, night in enumerate(story.nights):
        _record_between(box, story, i)
        snap = NIGHTS[i]
        n = gp.ordered(night, order)
        if i == 0 or story.held:  # the first night, or a conflict night: the whole hospital as a full night
            out = _night(box, partial(road.first, box, story, n, snap, work), snap)
        else:
            assert last_good is not None
            out = _night(box, partial(road.later, box, story, n, snap, last_good, work), snap)
        if out.passed:
            last_good = snap
        nights.append(out)
        after.append(box.published(markers))
    eff = _withhold(box) if story.optouts else set()
    final = after[-1] if not story.optouts else box.published(markers)
    after[-1] = final
    # replay: the last night sent again as the next night (a full night as a full night, a delta as a delta)
    snap = NIGHTS[len(story.nights)]
    last = gp.ordered(story.nights[-1], order)
    if len(story.nights) == 1 or story.held:
        nights.append(_night(box, lambda: road.first(box, story, last, snap, work), snap))
    else:
        assert last_good is not None
        nights.append(_night(box, lambda: road.later(box, story, last, snap, last_good, work), snap))
    if story.optouts:
        _withhold(box)
    replay = box.published(markers)
    d = Drive(story, box, nights, after, replay, effective_optouts=eff)
    if story.held:
        from tb_common.crypto import pid_for_mrn

        held_charts = {story.people[x].chart for x in story.held}
        d.held_pids = {pid_for_mrn(KEY, c) for c in held_charts}
        pm = box.pidmap()
        try:
            d.pidmap_held = {p: (pm.resolve(p), pm.identity(p)) for p in d.held_pids}
        finally:
            pm.close()
    if rebuild and len(story.nights) > 1 and not story.held:
        # the same box with its lake emptied: the patient index, its merges and the opt-out register are kept
        other = Box(root / "rebuilt", db_url, MAPPINGS[road.mapping])
        shutil.copytree(box.root / "secrets", other.root / "secrets", dirs_exist_ok=True)
        if road.name in ("ssmix2",):
            shutil.rmtree(_ssmix2_storage(other), ignore_errors=True)
        road.first(other, story, gp.ordered(full_state(story), order), NIGHTS[0], root / "work-rebuilt")
        if story.optouts:
            _withhold(other)
        d.rebuilt = other.published(markers)
    return d


# ---------------------------------------------------------------------------------------------- the judges
def judge(d: Drive) -> list[str]:
    """Every finding of the six invariants over the published stores; [] when all hold."""
    story = d.story
    owner = story.owner_of()
    out: list[str] = []
    final = d.after[-1]
    stores = sorted({r.store for r in final} | set(STORES))
    held = [n for n in d.nights if n.held]
    if story.held:
        out += _hold(d, held)
    elif held:
        out += [f"published store=night person=-: night {n.snapshot} was not published: {n.held}" for n in held]
    for store in stores:
        rows = [r for r in final if r.store == store and r.rtype in gp.TYPES]
        out += _sharing(store, rows, owner, merged_people(story))
        out += _references(store, rows, owner, merged_people(story))
        out += _splitting(store, rows, owner, story)
        if story.optouts:
            out += _optout(store, rows, owner, story, d.effective_optouts)
    out += _stability(d, owner)
    if d.rebuilt is not None:
        out += _path(final, d.rebuilt, owner)
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


def _sharing(store: str, rows: list[Row], owner: dict[str, str], same: dict[str, str]) -> list[str]:
    out = []
    by_pid: dict[str, set[str]] = defaultdict(set)
    by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        who = same.get(_who(r, owner), _who(r, owner))
        by_pid[r.pid].add(who)
        by_key[(r.rtype, r.key)].add(who)
    for pid, people in by_pid.items():
        if len(people) > 1:
            out.append(
                f"no-sharing store={store} person={'+'.join(sorted(people))}: one pseudonym {pid[:8]} holds "
                f"records of {len(people)} people"
            )
    for (rtype, key), people in by_key.items():
        if len(people) > 1:
            out.append(
                f"no-sharing store={store} person={'+'.join(sorted(people))}: one {rtype} key {key[:8]} "
                f"reached from {len(people)} people"
            )
    for r in rows:
        if r.marker not in owner:
            out.append(f"no-sharing store={store} person=?: a {r.rtype} row with no person's marker ({r.marker!r})")
    return out


def _references(store: str, rows: list[Row], owner: dict[str, str], same: dict[str, str]) -> list[str]:
    """No sharing through a reference: a published Condition's visit is a published visit of the same person."""
    out = []
    visits = {r.key: same.get(_who(r, owner), _who(r, owner)) for r in rows if r.rtype == "Encounter"}
    for r in rows:
        if r.rtype != "Condition" or not r.ref:
            continue
        who = same.get(_who(r, owner), _who(r, owner))
        if r.ref not in visits:
            out.append(
                f"no-sharing store={store} person={who}: a Condition points at a visit {r.ref[:8]} not published"
            )
        elif visits[r.ref] != who:
            out.append(
                f"no-sharing store={store} person={who}+{visits[r.ref]}: a Condition reaches another person's visit"
            )
    return out


def _splitting(store: str, rows: list[Row], owner: dict[str, str], story: gp.Story) -> list[str]:
    out = []
    pids: dict[str, set[str]] = defaultdict(set)
    got: Counter[tuple[str, str]] = Counter()
    per_marker: Counter[str] = Counter()
    for r in rows:
        who = _who(r, owner)
        pids[who].add(r.pid)
        got[(who, r.rtype)] += 1
        per_marker[r.marker] += 1
    merged_into = merged_people(story)
    withheld = {x for x, p in story.people.items() if p.chart in story.optouts} if store.startswith("omop") else set()
    groups: dict[str, set[str]] = defaultdict(set)
    for who, ps in pids.items():
        groups[merged_into.get(who, who)] |= ps
    for who, ps in sorted(groups.items()):
        if len(ps) > 1:
            out.append(f"no-splitting store={store} person={who}: one person under {len(ps)} pseudonyms")
    for (who, rtype), n in sorted(story.expected.items()):
        if who in withheld:  # opted out: the OMOP store must hold none (the opt-out judge says so if it does)
            continue
        if got[(who, rtype)] != n:
            out.append(f"no-splitting store={store} person={who}: {got[(who, rtype)]} {rtype} rows, expected {n}")
    for (who, rtype), n in sorted(got.items()):
        if (who, rtype) not in story.expected and who in story.people:
            out.append(f"no-splitting store={store} person={who}: {n} {rtype} rows, expected 0")
    for m, n in sorted(per_marker.items()):
        if n > 1:
            out.append(
                f"no-splitting store={store} person={owner.get(m, '?')}: one source record ({m}) published {n} times"
            )
    for m in sorted(story.gone):
        if per_marker[m]:
            out.append(
                f"no-splitting store={store} person={owner.get(m, '?')}: a replaced or deleted version ({m}) "
                f"is still published"
            )
    return out


def _optout(store: str, rows: list[Row], owner: dict[str, str], story: gp.Story, eff: set[str]) -> list[str]:
    from tb_common.crypto import pid_for_mrn

    out = []
    opted = {letter for letter, p in story.people.items() if p.chart in story.optouts}
    if not {pid_for_mrn(KEY, c) for c in story.optouts} <= eff:
        out.append(
            f"opt-out store={store} person={'+'.join(sorted(opted))}: the register's effective set lacks the "
            f"opt-out as typed"
        )
    for r in rows:
        who = _who(r, owner)
        if who not in opted:
            continue
        if store.startswith("omop"):
            out.append(f"opt-out store={store} person={who}: a {r.rtype} row is live after the withhold")
        elif r.pid not in eff:
            out.append(
                f"opt-out store={store} person={who}: a {r.rtype} row under {r.pid[:8]}, a pseudonym the "
                f"opt-out does not cover"
            )
    return out


def _hold(d: Drive, held: list[NightOutcome]) -> list[str]:
    out = []
    letters = "+".join(sorted(d.story.held))
    if not any(n.held or not n.passed for n in d.nights[1:]):
        out.append(f"hold store=night person={letters}: the conflicting night was published, not held")
    for rows, when in ((d.after[-1], "after the conflict night"), (d.replay, "after the replay")):
        for r in rows:
            if r.pid in d.held_pids:
                out.append(
                    f"hold store={r.store} person={letters}: a {r.rtype} row under the conflicting chart is "
                    f"published {when}"
                )
    for pid, (chart, identity) in d.pidmap_held.items():
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


def _stability(d: Drive, owner: dict[str, str]) -> list[str]:
    """Key stability and idempotence: the replay publishes exactly what the last night did (keys, pseudonyms and
    values as sets), and a key a recorded correction or merge changed is gone from every store."""
    out = []
    before = {(r.store, r.rtype, r.key, r.pid, r.marker) for r in d.after[-1]}
    again = {(r.store, r.rtype, r.key, r.pid, r.marker) for r in d.replay}
    for t in sorted(before ^ again)[:20]:
        where = "after the replay only" if t in again else "before the replay only"
        out.append(f"stability store={t[0]} person={owner.get(t[4], '?')}: {t[1]} {t[2][:8]} {where}")
    if len(d.after) > 1:
        first = {(r.store, r.rtype, r.marker): r.key for r in d.after[0]}
        last = {(r.store, r.rtype, r.marker): r.key for r in d.after[-1]}
        live = defaultdict(set)
        for r in d.after[-1]:
            live[r.store].add(r.key)
        for (store, rtype, m), k in sorted(first.items()):
            if (store, rtype, m) in last and last[(store, rtype, m)] != k:
                if k in live[store]:
                    out.append(
                        f"stability store={store} person={owner.get(m, '?')}: {rtype}'s key changed and the "
                        f"old key is still live"
                    )
                elif not d.story.merges:
                    out.append(
                        f"stability store={store} person={owner.get(m, '?')}: {rtype}'s key changed between "
                        f"nights with no correction recorded"
                    )
    return out


def _path(incremental: list[Row], rebuilt: list[Row], owner: dict[str, str]) -> list[str]:
    out = []
    for store in STORES:
        a = {(r.rtype, r.key, r.pid, r.marker) for r in incremental if r.store == store}
        b = {(r.rtype, r.key, r.pid, r.marker) for r in rebuilt if r.store == store}
        for t in sorted(a - b):
            out.append(
                f"path-independence store={store} person={owner.get(t[3], '?')}: {t[0]} {t[1][:8]} only in "
                f"the incremental store"
            )
        for t in sorted(b - a):
            out.append(
                f"path-independence store={store} person={owner.get(t[3], '?')}: {t[0]} {t[1][:8]} only in "
                f"the rebuild from empty"
            )
    return out


def summary(findings: Iterable[str]) -> str:
    return "\n".join(findings)


def today() -> date:
    return date.today()
