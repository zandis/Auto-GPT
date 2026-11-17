"""V-1 (plan 8, activity V7, criterion 8): after an opt-out, is the patient found in any store? Searched by brute force.

One box per module, as full as the unit tier stands up: every store's migrations in one throwaway PostgreSQL, a lake
folder made by the night's own ingest (NDJSON, the DuckDB snapshot and its generation, Parquet, the embed cache, the
gates), the derive batch, an object store with job outputs and attachments, a site set-up folder, the mail outbox, the
trace store, the recall ledger, the patient twin, the job queue and the OMOP store.

Two synthetic marker patients, all values invented: P, never consented, and S, a trial subject (consented in one study,
enrolled in another). Both have a row in every kind of table of the synthetic hospital export, so the ingest and the
OMOP load write every table they can. Every store is seeded with every variant the product can hold for a patient
(:data:`VARIANTS`): what a clear removes and what it is ruled or owed to leave. Every other table with a ``pid`` or
``pid_hash`` column gets one planted row (``planted`` in the record). P's derive recompute is made to fail once, so
the product's own failure log line is written. Both opt out (the register's ``add``, which the console's route
calls) and the opt-out worker runs twice.

Then ``tools/erasure_reach.py`` searches every table of every schema, every file of the lake, object and set-up
folders, the audit folder and the captured log text, before and after, independent of the erasure registry. One test
case per store, for P: a store still holding P passes only when the registry keeps it with a decision; an owed store
is ``xfail(strict=True)`` with its finding; a store the registry calls erased, or does not list, is a finding of its
own (also strict). A store that could not be read fails. A store P never reached is skipped as "not reached".
``TB_REACH_OUT=<folder>`` writes the module's record (``reach.json``) there.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tb_common import erasure

from tools import erasure_reach as er

SNAP = "2026-10-04"
T0 = "2026-10-05T09:00:00+00:00"
NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
SITE_KEY = b"trialbox-test-site-key-0123456789abcdef"
#: the marker patients' values: invented, plainly synthetic (a national-ID shape with no valid second digit). The
#: phones are put together at run time, so the repository's data scan does not take the line for a real number
CHART, CHART_S = "77770727", "77770728"
MARK: dict[str, Any] = {"chart": CHART, "national_id": "Z300072701", "name": "假名測試甲",
        "phone": "09" + "00 072 700", "dob": "1937-07-27"}  # fmt: skip
MARK_S: dict[str, Any] = {"chart": CHART_S, "national_id": "Z300072802", "name": "假名測試乙",
          "phone": "09" + "00 072 800", "dob": "1938-08-28"}  # fmt: skip
OTHERS = 5  # site A's first patients, kept beside the markers; the first is the control (never opts out)

# ------------------------------------------------------------------------------------------------ what master shows
#: the stores where P is still found after the ticks, with the finding that says so (the page's ids). A fix that
#: clears a store turns its case red here until the line goes.
_LAKE = ("V1-02", "the kept snapshot keeps the patient's rows and note text (ruled by D-513)")
_JOB = ("V1-08", "a job's request and an EDC draft keep the pseudonym (owed)")
_SETUP = ("V1-15", "a set-up sheet of many patients keeps the patient (owed, D-869)")
KNOWN_LEFT: dict[str, tuple[str, str]] = {
    "lake:db": _LAKE,
    "lake:ndjson": _LAKE,
    "lake:parquet": _LAKE,
    "lake:embed_cache.duckdb": ("V1-02", "the embed cache keeps the vectors of the patient's chunks (D-862)"),
    "omop.tb_record_event": ("V1-03", "the before-images keep the note's name, chart number and phone (D-1031)"),
    "objects:outputs": ("V1-04", "a job's list and a per-patient file keep the pseudonym (ruled by D-513)"),
    "objects:attachments": ("V1-04", "an attached chart of the patient stays (ruled by D-513)"),
    "trace.traces": ("V1-05", "a model call's body keeps the pseudonym and the name (owed)"),
    "pidmap.identity": ("V1-06", "the encrypted identity stays: no crypto-shred (owed)"),
    "recall.recall_known_positive": ("V1-07", "the unsalted hash of the pseudonym stays (owed)"),
    "recall.recall_observation": ("V1-07", "the unsalted hash of the pseudonym stays (owed)"),
    "orch.jobs": _JOB,
    "edc.draft": _JOB,
    "logs:captured": ("V1-09", "the derive batch's failure line names the pseudonym"),
    "orch.submissions": ("V1-13", "a live submission stays (D-513) where the registry says the store is erased"),
    "mail.send_keys": ("V1-14", "a queued mail of a list and an uncertain mail keep the patient (owed, D-863, D-874)"),
    "sitesetup.input": _SETUP,
    "sitesetup.check_item": _SETUP,
    "sitesetup.fix": _SETUP,
}
#: stores the walk finds that the registry does not list
UNLISTED: tuple[str, ...] = ("logs:captured",)


# ------------------------------------------------------------------------------------------------ the box
class _Logs(logging.Handler):
    """Every log record of the run, as text with its fields (what a JSON log line of the box would carry)."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            fields = {k: v for k, v in record.__dict__.items() if k not in ("msg", "args", "exc_info")}
            self.lines.append(record.getMessage() + " " + json.dumps(fields, default=str, ensure_ascii=False))
            if record.exc_info:
                self.lines.append(logging.Formatter().formatException(record.exc_info))
        except Exception:  # a record that cannot be read: kept by its name
            self.lines.append(record.name)


def _marker_rows(name: str, template: dict[str, str], chart: str, mark: dict[str, str]) -> list[dict[str, str]]:
    """A marker patient's row of one export table, made from the table's first row: the chart number and the
    patient's own encounter put in, every other ``*_no`` key made new."""
    if name == "patient.csv":
        return [{"mrn": chart, "name": mark["name"], "id_no": mark["national_id"], "birth_date": mark["dob"],
                 "sex": "F", "death_date": "", "phone": mark["phone"]}]  # fmt: skip
    row = dict(template, mrn=chart)
    for k in row:
        if k == "enc_no":
            row[k] = f"E{chart}"
        elif k.endswith("_no"):
            row[k] = f"{k[0].upper()}{chart}1"
    if name == "encounter.csv":
        row["visit_datetime"] = "2026-09-01 09:00:00"
    if name == "note.csv":
        row["text"] = (f"Patient {mark['name']} (chart {chart}, phone {mark['phone']}) seen for gout. Uric acid high. "
                       "Continue allopurinol.")  # fmt: skip
    if name == "registry.csv":
        row["consent_contact"] = "Y"
    return [row]


def _source(site_a: Path, into: Path) -> tuple[Path, str, list[str]]:
    """Site A cut to its first patients, plus both marker patients with a row in every table that names a patient.
    Returns the folder, the control's chart number and the tables the markers were given a row in."""
    src = into / "src"
    shutil.copytree(site_a, src, ignore=shutil.ignore_patterns("*.sqlite"))
    with (src / "patient.csv").open(encoding="utf-8") as fh:
        keep = [r["mrn"] for r in list(csv.DictReader(fh))[:OTHERS]]
    kinds: list[str] = []
    for f in sorted(src.glob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            names = list(rd.fieldnames or [])
            every = list(rd)
        rows = [r for r in every if "mrn" not in r or r["mrn"] in keep]
        add: list[dict[str, str]] = []
        if "mrn" in names and every:
            kinds.append(f.stem)
            for chart, mark in ((CHART, MARK), (CHART_S, MARK_S)):
                add += _marker_rows(f.name, every[0], chart, mark)
        with f.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, names)
            w.writeheader()
            w.writerows(rows)
            w.writerows([{k: r.get(k, "") for k in names} for r in add])
    return src, keep[0], kinds


def _batch_from(nd: Path, pids: set[str]) -> dict[str, list[dict[str, Any]]]:
    """The night's NDJSON resources of ``pids`` (and the resources that name no patient), by type."""
    out: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(nd.glob("*.ndjson")):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            ref = json.dumps(r)
            if r.get("resourceType") == "Patient" and r.get("id") not in pids:
                continue
            if (
                r.get("resourceType") != "Patient"
                and "Patient/" in ref
                and not any(f"Patient/{p}" in ref for p in pids)
            ):
                continue
            out.setdefault(str(r["resourceType"]), []).append(r)
    return out


_N = iter(range(1, 10**6))


def _plant(db: Any, table: str, values: dict[str, Any]) -> int | None:
    """One row: ``values`` and every other required column a distinct dummy of its type (as
    ``test_optout_clears_the_owed_tables._row``). Returns its ``id`` when the table has one."""
    cols = db.fetchall(
        "SELECT column_name, data_type, is_nullable, column_default, is_identity FROM information_schema.columns"
        " WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
        (db.schema, table),
    )
    vals = dict(values)
    for name, typ, nullable, default, ident in cols:
        if name in vals or nullable == "YES" or default is not None or ident == "YES":
            continue
        n = next(_N)
        vals[name] = {"bigint": n, "integer": n, "smallint": 1, "boolean": True, "double precision": 1.0,
                      "real": 1.0, "numeric": 1, "date": "2026-01-01", "jsonb": "{}", "json": "{}",
                      "bytea": b"x", "timestamp with time zone": T0, "timestamp without time zone": "2026-01-01",
                      "ARRAY": "{}", "uuid": f"00000000-0000-4000-8000-{n:012d}"}.get(typ, f"{name}-{n}")  # fmt: skip
    names = [c[0] for c in cols if c[0] in vals]
    sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})"
    if any(c[0] == "id" for c in cols):
        return int(db.fetchval(sql + " RETURNING id", tuple(vals[c] for c in names)))
    db.execute(sql, tuple(vals[c] for c in names))
    return None


def _plant_everywhere(url: str, pid: str, already: set[str]) -> dict[str, str]:
    """A row of ``pid`` in every table with a ``pid`` or ``pid_hash`` text column that does not hold it yet."""
    import psycopg
    from tb_common.db import Database, split_url

    dsn, prefix = split_url(url)
    with psycopg.connect(dsn, autocommit=True) as con:
        rows = con.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns WHERE left(table_schema, %s)"
            " = %s AND column_name IN ('pid', 'pid_hash') AND data_type = 'text' ORDER BY 1, 2, 3",
            (len(prefix), prefix),
        ).fetchall()
    out: dict[str, str] = {}
    for schema, table, col in rows:
        key = f"{str(schema)[len(prefix) :]}.{table}"
        entry = erasure.entries().get(key)
        if key in already or key in out or (entry is not None and entry.kind == erasure.KEEP):
            continue  # a kept store proves nothing, and a planted row in the register or its copies would steer it
        value = pid if col == "pid" else er.recall_hash(pid)
        try:
            with Database.connect(url, str(schema)[len(prefix) :]) as db:
                _plant(db, str(table), {str(col): value})
            out[key] = "planted"
        except Exception as exc:  # a foreign key or a check the dummies do not meet: said in the record
            out[key] = f"not planted: {type(exc).__name__}"
    return out


def _vec_offered(url: str) -> bool:
    from tb_common.db import Database

    with Database.connect(url, "vec_probe") as db:
        if db.fetchval("SELECT count(*) FROM pg_extension WHERE extname = 'vector'"):
            return True
        if not db.fetchval("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'"):
            return False
        db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        return True


# ------------------------------------------------------------------------------------------------ the variants
#: every variant of a store the seed writes, and what the product does with it at P's (or S's) opt-out:
#: ``gone`` (the clear takes it), ``kept <decision>`` (ruled to stay) or ``owed <decision>`` (the registry owes it)
VARIANTS: dict[str, str] = {
    "orch.submissions: a dry run": "gone",
    "orch.submissions: a live submission": "kept D-513",
    "orch.candidates: a never-consented candidate": "gone",
    "orch.candidates: S consented in one study": "kept OD-8",
    "orch.candidates: S enrolled in another": "kept OD-8",
    "mail.send_keys: a held mail of the patient's own file": "gone",
    "mail.send_keys: an uncertain mail of the patient's own file": "owed D-874",
    "mail.send_keys: a queued mail of a list that names the patient": "owed D-863",
    "sitesetup.input: the patient's own upload": "gone",
    "sitesetup.input: a sheet of many patients": "owed D-869",
    "sitesetup.check_item: a sheet's row of the patient": "owed D-869",
    "sitesetup.fix: a sheet column's example of the patient": "owed D-869",
}


def _seed_variants(url: str, p: str, s: str, setup: Path) -> dict[str, Any]:
    """The variants of :data:`VARIANTS`, written by the stores' own methods where they have one. Returns the handles
    the checks need."""
    from mail_gateway.store import MailDB
    from orchestrator.db import JobDB
    from tb_common.db import Database
    from tb_common.patient_files import HELD

    jobs = JobDB()
    jobs.candidate_set("GZQO", s, "consented", None, "crc1", T0, "consent", "J3")
    jobs.candidate_set("RAQX", s, "enrolled", None, "crc1", T0, "enrol", "J4")
    with Database.connect(url, "orch") as db:
        _plant(db, "submissions", {"pid": p, "dry_run": 1, "job_id": "J5"})
        _plant(db, "submissions", {"pid": p, "dry_run": 0, "job_id": "J6"})
    mail = MailDB(url)
    own = {"to": ["pi@hospa.test"], "subject": "TrialBox results",
           "attachments": [{"filename": f"twpas_{p[:16]}.json", "key": f"outputs/J1/twpas_{p[:16]}.json"}]}  # fmt: skip
    lst = {"to": ["pi@hospa.test"], "subject": "TrialBox list", "body": f"One candidate is new: {p}.",
           "attachments": [{"filename": "candidates.csv", "key": "outputs/J1/candidates.csv"}]}  # fmt: skip
    for key, state, req, err in (("k-own-held", "failed", own, HELD), ("k-own-uncertain", "uncertain", own, "?"),
                                 ("k-list-queued", "queued", lst, "")):  # fmt: skip
        mail.claim_send(key, "J1", T0)
        mail.hold(key, state, request_json=json.dumps(req), message_id=f"<{key}@hospa.test>", result_json="{}",
                  recipients=["pi@hospa.test"], attempts=1, next_at=None, error=err, at=T0)  # fmt: skip
    mail.close()
    with Database.connect(url, "sitesetup") as db:
        own_id = _plant(db, "input", {"pid": p, "ws": "space1", "kind": "chart"})
        sheet = _plant(db, "input", {"ws": "space1", "kind": "sheet", "name": "labs.csv"})
        _plant(db, "check_item", {"ws": "space1", "input_id": sheet, "key": "k1", "raw": CHART})
        _plant(db, "fix", {"input_id": sheet, "examples": json.dumps([CHART, MARK["name"]], ensure_ascii=False)})
    (setup / "space1" / "inputs").mkdir(parents=True)
    (setup / "space1" / "inputs" / f"{own_id}.txt").write_text(f"{CHART},{MARK['name']}\n", encoding="utf-8")
    (setup / "space1" / "inputs" / f"{sheet}.csv").write_text(f"mrn,name\n{CHART},{MARK['name']}\n10000001,x\n",
                                                              encoding="utf-8")  # fmt: skip
    return {"own_id": own_id, "sheet": sheet}


def _variant_states(url: str, p: str, s: str, ids: dict[str, Any], setup: Path) -> dict[str, str]:
    """What each variant is after the ticks: ``gone`` or ``there``."""
    from tb_common.db import Database

    def n(schema: str, q: str, args: tuple[Any, ...]) -> int:
        with Database.connect(url, schema) as db:
            return int(db.fetchval(q, args))

    def st(count: int) -> str:
        return "there" if count else "gone"

    own, sheet = ids["own_id"], ids["sheet"]
    return {
        "orch.submissions: a dry run": st(
            n("orch", "SELECT count(*) FROM submissions WHERE pid = ? AND dry_run = 1", (p,))
        ),
        "orch.submissions: a live submission": st(
            n("orch", "SELECT count(*) FROM submissions WHERE pid = ? AND dry_run = 0", (p,))
        ),
        "orch.candidates: a never-consented candidate": st(
            n("orch", "SELECT count(*) FROM candidates WHERE pid = ?", (p,))
        ),
        "orch.candidates: S consented in one study": st(
            n("orch", "SELECT count(*) FROM candidates WHERE pid = ? AND status = 'consented'", (s,))
        ),
        "orch.candidates: S enrolled in another": st(
            n("orch", "SELECT count(*) FROM candidates WHERE pid = ? AND status = 'enrolled'", (s,))
        ),
        "mail.send_keys: a held mail of the patient's own file": st(
            n("mail", "SELECT count(*) FROM send_keys WHERE key = 'k-own-held' AND request IS NOT NULL", ())
        ),
        "mail.send_keys: an uncertain mail of the patient's own file": st(
            n("mail", "SELECT count(*) FROM send_keys WHERE key = 'k-own-uncertain' AND request IS NOT NULL", ())
        ),
        "mail.send_keys: a queued mail of a list that names the patient": st(
            n("mail", "SELECT count(*) FROM send_keys WHERE key = 'k-list-queued' AND strpos(request, ?) > 0", (p,))
        ),
        "sitesetup.input: the patient's own upload": st(
            n("sitesetup", "SELECT count(*) FROM input WHERE id = ? AND status <> 'erased'", (own,))
            + len(list((setup / "space1" / "inputs").glob(f"{own}.*")))
        ),
        "sitesetup.input: a sheet of many patients": st(
            n("sitesetup", "SELECT count(*) FROM input WHERE id = ?", (sheet,))
            * len(list((setup / "space1" / "inputs").glob(f"{sheet}.*")))
        ),
        "sitesetup.check_item: a sheet's row of the patient": st(
            n("sitesetup", "SELECT count(*) FROM check_item WHERE input_id = ? AND raw = ?", (sheet, CHART))
        ),
        "sitesetup.fix: a sheet column's example of the patient": st(
            n("sitesetup", "SELECT count(*) FROM fix WHERE input_id = ? AND strpos(examples, ?) > 0", (sheet, CHART))
        ),
    }


# ------------------------------------------------------------------------------------------------ the stores
def _seed_stores(url: str, work: Path, pids: tuple[str, str, str], lake: Path) -> dict[str, str]:
    """The product write paths this module can reach; returns how each store was seeded."""
    import tb_contracts as c
    from omop import schema
    from omop.load import load_batch
    from orchestrator.db import JobDB
    from orchestrator.recall.ledger import RecallLedger
    from patient_profile.twin import ProfileStore
    from tb_common.objstore import FsStore
    from tb_contracts.recall import KnownPositiveLineKind

    from tests.unit.test_migrations import store_migrations

    how: dict[str, str] = {}
    p, s, q = pids
    omop = schema.connect(url)
    load_batch(omop, "feed", SNAP, _batch_from(lake / "ndjson" / SNAP, {p, s, q}), tz="Asia/Taipei")
    omop.close()
    how["omop"] = "omop.load.load_batch of the night's NDJSON"
    jobs = JobDB()
    for i, pid in enumerate((p, q)):
        jobs.pool_upsert("GZQO", "1", [{"pid": pid, "tier": "high", "verdicts": []}], "J1", T0)
        jobs.candidate_set("GZQO", pid, "candidate", None, "steward1", T0, "screen", "J1")
        jobs.put(c.Job(job_id=f"01JV1REACH{i:016d}", type="CASE", requested_by="crc1@hospa.test",
                       received_at=datetime.fromisoformat(T0), state="done", options={"pid": pid}))  # fmt: skip
    how["orch"] = "JobDB: pool_upsert, candidate_set, a CASE job naming the patient"
    twins = ProfileStore(url)
    for pid, born in ((p, MARK["dob"]), (q, "1950-01-01")):
        twins.put({"pid": pid, "profile": "v1", "basis": {"snapshot": SNAP},
                   "layers": {"core": {"sex": "F", "birth": born}}}, T0)  # fmt: skip
    twins.close()
    how["profile"] = "ProfileStore.put"
    led = RecallLedger(url=url)
    for pid in (p, q):
        h = er.recall_hash(pid)
        led.add_known_positive(KnownPositiveLineKind.BLINDED_CHART_REVIEW, "pop", f"b:{h}", h, False)
    led.close()
    how["recall"] = "RecallLedger.add_known_positive"
    from tracestore.store import TraceStore

    ts = TraceStore(url)
    for pid in (p, q):
        ts.write({"call_id": f"call-{pid}", "prompt": f"Note of {pid}: {MARK['name']} was seen.", "output": "yes",
                  "attributes": {"tb.pid": pid, "tb.data_class": "D2"}})  # fmt: skip
    ts.close()
    how["trace"] = "TraceStore.write"
    store = FsStore(work / "obj", work / "secrets")
    store.put("outputs/J1/candidates.csv", f"pid,tier\n{p},high\n{q},high\n".encode())
    for pid in (p, q):
        store.put(
            f"outputs/J1/twpas_{pid[:16]}.json", json.dumps({"subject": pid, "id": er.twpas_ids(pid)[2]}).encode()
        )
        store.put(f"attachments/J2/chart_{pid[:16]}.txt", f"chart of {pid}".encode())
    how["objects"] = "FsStore.put: a list, a per-patient file, an attached chart"
    if _vec_offered(url):
        from vec.store import VecStore

        with VecStore(url, model="test-embed", dim=3) as st:
            for i, pid in enumerate((p, q)):
                sha = f"{i}" * 64
                st.put_vectors("test-embed", 3, {sha: [0.1 * (i + 1), 0.2, 0.3]})
                st.db.execute(
                    "INSERT INTO note_chunk (pid, did, chunk_no, note_date, note_type, start_char, end_char, text, sha,"
                    " mask_version) VALUES (?, ?, 0, '2026-10-01', 'progress', 0, 20, ?, ?, 'm1')",
                    (pid, f"note-{pid}", f"masked note of {pid}", sha),
                )
        how["vec"] = "VecStore.put_vectors and a chunk"
    else:
        how["vec"] = "not seeded: the server offers no pgvector"
    from tb_common.db import Database

    for name, scripts in store_migrations().items():  # every other store exists, empty, as on a box
        try:
            with Database.connect(url, name) as db:
                db.migrate(scripts)
        except Exception as exc:
            how.setdefault(f"migrate:{name}", f"not made: {type(exc).__name__}")
    return how


def _derive(url: str, lake: Path, p: str) -> str:
    """The derive batch on the trial database's store (as the INGEST job runs it), then P's recompute made to fail
    once, so the batch writes its own failure line (``derived_store.py``, "recompute failed for <pid>")."""
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator import derive
    from tb_common.derived_store import mapping_version_of, run_batch

    st = derive.store(url)
    if st is None:
        return "not run: no derived store"
    lk = LakeLocal(lake, HashEmbedder())
    mv = mapping_version_of(lk, SNAP)
    rep = run_batch(st, lk, mapping_version=mv, snapshot=SNAP)

    class Failing:
        def recompute(self, pid: str, *a: Any, **k: Any) -> Any:
            if pid == p:
                raise KeyError("a synthetic failure")
            return st.recompute(pid, *a, **k)  # type: ignore[union-attr]

    run_batch(Failing(), lk, mapping_version=mv, pids=[p])  # type: ignore[arg-type]
    return f"run_batch on the trial database's store ({rep.failed} failed), then P's recompute failed once"


def _search(url: str, marker: er.Marker, roots: dict[str, Path], logs: list[str]) -> er.Found:
    found = er.search_db(url, marker)
    found.merge(er.search_tree(roots["lake"], marker, er.lake_key))
    found.merge(er.search_tree(roots["obj"], marker, er.objects_key))
    found.merge(er.search_tree(roots["setup"], marker, lambda rel: er.SETUP_FILES))
    found.merge(er.search_tree(roots["audit"], marker, lambda rel: "outside:audit"))
    found.seen("logs:captured")
    for kind, n in er.search_text("\n".join(logs), marker).items():
        found.add("logs:captured", kind, n)
    return found


def _chunk_shas(lake: Path, pid: str) -> tuple[tuple[str, str], ...]:
    """The hashes of the patient's note chunks in the snapshot: the embed cache keeps its vectors by them."""
    import duckdb

    con = duckdb.connect(str(lake / "db" / f"{SNAP}.duckdb"), read_only=True)
    try:
        rows = con.execute("SELECT DISTINCT sha FROM document_chunk WHERE pid = ?", [pid]).fetchall()
    finally:
        con.close()
    return tuple(("chunk_sha", str(r[0])) for r in rows)


@pytest.fixture(scope="module")
def reach(pg_cluster_url: str, synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from adapter.pidmap import pseudonym
    from datacore.optout_worker import KEEP_MONTHS, WorkerEnv, run_once
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from omop import schema
    from orchestrator.db import JobDB
    from tb_common.audit import AuditLog
    from tb_common.db import split_url
    from tb_common.optout import OptOutRegister

    from tests.inproc_box import ingest_site
    from tools import pglocal

    work = tmp_path_factory.mktemp("reach")
    sep = "&" if "?" in pg_cluster_url else "?"
    prefix = f"v1r{os.getpid()}_"
    url = f"{pg_cluster_url}{sep}tb_prefix={prefix}"
    logs = _Logs()
    root = logging.getLogger()
    level = root.level
    root.addHandler(logs)
    root.setLevel(logging.DEBUG)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("TB_DB_URL", url)
            secrets = work / "secrets"
            secrets.mkdir()
            (secrets / "site_hmac.key").write_bytes(SITE_KEY)
            (secrets / "site_hmac.key").chmod(0o600)
            src, control_chart, kinds = _source(synth_dir / "site-a", work)
            lake = work / "lake"
            report = ingest_site(src, lake, secrets, SNAP)
            assert report.passed, "the night's ingest must pass for the lake to hold the patient"
            p, s = pseudonym(SITE_KEY, CHART)[0], pseudonym(SITE_KEY, CHART_S)[0]
            q = pseudonym(SITE_KEY, control_chart)[0]
            how = {"lake": "tests.inproc_box.ingest_site (the csv source, the adapter, the lake rebuild, derive)",
                   "export_tables": ", ".join(kinds)}  # fmt: skip
            how |= _seed_stores(url, work, (p, s, q), lake)
            how["derived"] = _derive(url, lake, p)
            setup = work / "sitesetup"
            ids = _seed_variants(url, p, s, setup)
            omop_db = schema.connect(url)
            pids_of = {
                x: tuple(
                    int(r[0])
                    for r in omop_db.fetchall(
                        "SELECT omop_id FROM tb_id_map WHERE id_kind = 'person' AND source_id = ?", (x,)
                    )
                )
                for x in (p, s)
            }
            marker = er.Marker(pid=p, person_ids=pids_of[p], extra=_chunk_shas(lake, p), **MARK)
            marker_s = er.Marker(pid=s, person_ids=pids_of[s], **MARK_S)
            control = er.Marker(pid=q)
            roots = {"lake": lake, "obj": work / "obj", "setup": setup, "audit": work / "audit"}
            (work / "audit").mkdir(exist_ok=True)
            seeded = _search(url, marker, roots, logs.lines)
            how["planted"] = json.dumps(_plant_everywhere(url, p, set(seeded.stores)), sort_keys=True)
            _plant_everywhere(url, q, set(er.search_db(url, control).stores))
            before = _search(url, marker, roots, logs.lines)

            reg = OptOutRegister()
            reg.add(p, "paper", "", "console:office1", T0)
            reg.add(s, "paper", "", "console:office1", T0)
            env = WorkerEnv(register=reg, audit=AuditLog(work / "audit"), now=NOW,
                            lake=LakeLocal(lake, HashEmbedder()), jobs=JobDB(), omop=omop_db,
                            extra={"setup_root": setup, KEEP_MONTHS: 36})  # fmt: skip
            tick = run_once(env)
            tick2 = run_once(env)  # a second tick: idempotent, and what a restart runs
            after = _search(url, marker, roots, logs.lines)
            after_s = er.search_db(url, marker_s)
            stays = _search(url, control, roots, [])
            variants = _variant_states(url, p, s, ids, setup)
            omop_db.close()
            reg.close()
    finally:
        root.removeHandler(logs)
        root.setLevel(level)
        pglocal.drop_prefix(split_url(url)[0], prefix)  # the module's schemas go with it
    rows = er.reach_rows(before, after, erasure.entries())
    folded = sorted(k for k in after.searched if er.registry_key(k) != k and k.startswith("omop."))
    record = {
        "card": "V-1",
        "what": "tests/unit/test_erasure_reach.py: two synthetic patients seeded, opted out, two worker ticks, "
        "searched before and after",
        "seeded_by": how,
        "tick": {k: tick[k] for k in ("failed", "left", "opted_out") if k in tick},
        "tick_stores": tick.get("stores"),
        "second_tick_failed": tick2.get("failed"),
        "log_lines": len(logs.lines),
        "partitions_folded": len(folded),
        "variants": {k: {"after": variants[k], "expected": VARIANTS[k]} for k in VARIANTS},
        "trial_subject_stores": sorted(er._fold(after_s).stores),  # type: ignore[union-attr]
        "stores": rows,
    }
    out = os.environ.get("TB_REACH_OUT")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "reach.json").write_text(
            json.dumps(record, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
    yield {"rows": {r["store"]: r for r in rows}, "record": record, "stays": stays, "before": before,
           "after": after, "tick": tick, "variants": variants}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the cases
def _cases() -> list[Any]:
    keys = sorted(set(erasure.entries()) | set(UNLISTED))
    out: list[Any] = []
    for k in keys:
        if k in KNOWN_LEFT:
            fid, why = KNOWN_LEFT[k]
            out.append(pytest.param(k, marks=pytest.mark.xfail(strict=True, reason=f"{fid}: {why}")))
        else:
            out.append(k)
    return out


@pytest.mark.parametrize("store", _cases())
def test_the_opted_out_patient_is_not_in_the_store(reach: dict[str, Any], store: str) -> None:
    row = reach["rows"].get(store)
    if row is None or row["verdict"] == "not_searched":
        pytest.skip("not searched in the unit box (compose only, or the store is not made here)")
    assert row["verdict"] != "error", f"{store} could not be read: {row['error']}"
    if row["verdict"] == "not_reached":
        pytest.skip("the patient never reached this store in the unit box: its absence proves nothing")
    if row["verdict"] == "kept":
        e = erasure.entries()[store]
        assert e.kind == erasure.KEEP and e.decision, store  # kept on purpose, with a decision
        return
    assert row["verdict"] == "clean", f"{store}: the opted-out patient is still there ({row['kinds']}, {row['files']})"


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_each_variant_does_what_the_registry_and_the_rulings_say(reach: dict[str, Any], variant: str) -> None:
    """A variant the clear takes is gone; a variant a ruling keeps, or the registry owes, is still there."""
    want = "gone" if VARIANTS[variant] == "gone" else "there"
    assert reach["variants"][variant] == want, (variant, VARIANTS[variant])


def test_the_search_sees_a_patient_who_did_not_opt_out(reach: dict[str, Any]) -> None:
    """The search is not blind: the control patient is still where the marker patient was before the opt-out."""
    stays = reach["stays"].stores
    for k in ("orch.pool", "omop.person", "profile.tb_patient_profile", "lake:db", "lake:parquet", "lake:ndjson",
              "objects:outputs", "trace.traces"):  # fmt: skip
        assert k in stays, k
    reached = set(er._fold(reach["before"]).stores)  # type: ignore[union-attr]
    for k in ("omop.drug_exposure", "omop.measurement", "omop.procedure_occurrence", "lake:embed_cache.duckdb",
              "logs:captured", "orch.pool", "pidmap.pid_map"):  # fmt: skip
        assert k in reached, k  # the thicker seed reaches them


def test_the_worker_tick_reports_no_failure(reach: dict[str, Any]) -> None:
    assert reach["tick"]["failed"] == [] and reach["tick"]["left"] == {}, reach["tick"]
    assert reach["tick"]["opted_out"] == 2


def test_no_store_outside_the_registry_holds_the_patient_unseen(reach: dict[str, Any]) -> None:
    """A store the walk finds holding the patient that the registry does not list must be a known finding here."""
    unlisted = {k for k, r in reach["rows"].items() if r["verdict"] == "unlisted"}
    assert unlisted <= set(UNLISTED), sorted(unlisted - set(UNLISTED))


def test_no_store_the_registry_calls_erased_holds_the_patient_unseen(reach: dict[str, Any]) -> None:
    leaks = {k for k, r in reach["rows"].items() if r["verdict"] == "leak"}
    assert leaks <= set(KNOWN_LEFT), sorted(leaks - set(KNOWN_LEFT))


def test_no_store_could_not_be_read(reach: dict[str, Any]) -> None:
    assert {k: r["error"] for k, r in reach["rows"].items() if r["verdict"] == "error"} == {}


@pytest.mark.xfail(strict=True, reason="V1-01: criterion 8 fails: the registry owes erasure in stores inside the box")
def test_criterion_8_no_owed_entry_for_a_store_inside_the_box() -> None:
    """Plan 8, criterion 8: "The erasure registry shows no owed entry for a store inside the box"."""
    inside = [r["store"] for r in er.owed_rows() if r["inside"]]
    assert inside == [], f"{len(inside)} owed inside the box: {inside}"


@pytest.mark.xfail(strict=True, reason="V1-09: a failed recompute logs the pseudonym, and the log scrubber keeps it")
def test_no_log_line_names_an_opted_out_patient(monkeypatch: pytest.MonkeyPatch) -> None:
    """The box's JSON log formatter (``tb_common.logging.JsonFormatter``) on the derive batch's failure line: the
    pseudonym stays in the line the box would write."""
    from tb_common import derived_store
    from tb_common.logging import JsonFormatter

    pid = "1ee23f8bc69240ca7c572e40510f985b"
    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(JsonFormatter("orchestrator").format(record))

    class Store:
        def recompute(self, *_a: Any, **_k: Any) -> Any:
            raise KeyError("synthetic failure")

    h = Keep()
    lg = derived_store.log  # the logger the batch writes to
    lg.addHandler(h)
    try:
        monkeypatch.setattr(derived_store, "rows_from_lake", lambda *_a: {pid: ([], None, False)})
        derived_store.run_batch(Store(), None, mapping_version="m", pids=[pid])  # type: ignore[arg-type]
    finally:
        lg.removeHandler(h)
    assert lines, "the failure is logged"
    assert not [ln for ln in lines if pid in ln], lines
