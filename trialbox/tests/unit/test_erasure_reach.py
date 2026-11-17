"""V-1 (plan 8, activity V7, criterion 8): after an opt-out, is the patient found in any store? Searched by brute force.

One box per module, as full as the unit tier stands up: every store's migrations in one throwaway PostgreSQL, a lake
folder made by the night's own ingest (NDJSON, the DuckDB snapshot and its generation, Parquet, the embed cache, the
gates), an object store with job outputs and attachments, a site set-up folder, the mail outbox, the trace store, the
recall ledger, the patient twin, the job queue and the OMOP store. One synthetic patient carries marker values: the
pseudonym, a chart number, a national-ID-shaped number, a name, a phone and a date of birth (all invented). They go in
through the product's own write paths where the module can reach one (the ingest, the OMOP load, the stores' own
methods); every other table with a ``pid`` or ``pid_hash`` column gets one planted row (``planted`` in the record).
The patient opts out (the register's ``add``, as the console's opt-out does) and one tick of the opt-out worker runs.

Then ``tools/erasure_reach.py`` searches every table of every schema, every file of the lake, object and set-up
folders, the audit folder and the captured log text, independent of the erasure registry. One test case per store.
A store where the marker is still there passes only when the registry keeps it with a decision; an owed store is
``xfail(strict=True)`` with its finding; a store the registry calls erased or without patient data, or does not list,
is a finding of its own (also strict xfail). A store the marker never reached is skipped as "not seeded": absence
there proves nothing. ``TB_REACH_OUT=<folder>`` writes the module's record (``reach.json``) there.
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
#: the marker patient's values: invented, plainly synthetic (a national-ID shape with no valid second digit). The
#: phone is put together at run time, so the repository's data scan does not take the line for a real number
PHONE = "09" + "00 072 700"
CHART = "77770727"
MARK = {"chart": CHART, "national_id": "Z300072701", "name": "假名測試甲",
        "phone": PHONE, "dob": "1937-07-27"}  # fmt: skip
OTHERS = 5  # site A's first patients, kept beside the marker patient; the first is the control (never opts out)

# ------------------------------------------------------------------------------------------------ what master shows
#: the stores where the opted-out patient is still found after one tick, with the finding that says so. The ids are
#: the page's (docs/plan/measurements/erasure-reach-2026-11-17.md). A fix that clears a store turns its case red here
#: until the line goes.
_LAKE = ("V1-02", "the kept snapshot keeps the patient's rows and note text (owed, D-513)")
_JOB = ("V1-08", "a job's request and an EDC draft keep the pseudonym (owed)")
KNOWN_LEFT: dict[str, tuple[str, str]] = {
    "lake:db": _LAKE,
    "lake:ndjson": _LAKE,
    "lake:parquet": _LAKE,
    "omop.tb_record_event": ("V1-03", "the before-images keep the note's name, chart number and phone (owed, D-1031)"),
    "objects:outputs": ("V1-04", "a job's list and a per-patient file keep the pseudonym (owed, D-513)"),
    "objects:attachments": ("V1-04", "an attached chart of the patient stays (owed, D-513)"),
    "trace.traces": ("V1-05", "a model call's body keeps the pseudonym and the name (owed)"),
    "pidmap.identity": ("V1-06", "the encrypted identity stays: no crypto-shred (owed)"),
    "recall.recall_known_positive": ("V1-07", "the unsalted hash of the pseudonym stays (owed)"),
    "recall.recall_observation": ("V1-07", "the unsalted hash of the pseudonym stays (owed)"),
    "orch.jobs": _JOB,
    "edc.draft": _JOB,
}
#: stores the walk finds that the registry does not list (none held the patient on 2026-11-17)
UNLISTED: tuple[str, ...] = ()


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


def _source(site_a: Path, into: Path) -> tuple[Path, str]:
    """Site A cut to its first patients, plus the marker patient with an encounter, a diagnosis and a note that names
    them. Returns the folder and the control patient's chart number."""
    src = into / "src"
    shutil.copytree(site_a, src, ignore=shutil.ignore_patterns("*.sqlite"))
    with (src / "patient.csv").open(encoding="utf-8") as fh:
        keep = [r["mrn"] for r in list(csv.DictReader(fh))[:OTHERS]]
    for f in src.glob("*.csv"):
        with f.open(encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            names = list(rd.fieldnames or [])
            rows = [r for r in rd if "mrn" not in r or r["mrn"] in keep]
        add: list[dict[str, str]] = []
        if f.name == "patient.csv":
            add = [{"mrn": CHART, "name": MARK["name"], "id_no": MARK["national_id"], "birth_date": MARK["dob"],
                    "sex": "F", "death_date": "", "phone": MARK["phone"]}]  # fmt: skip
        elif f.name == "encounter.csv":
            add = [{"enc_no": "E77770001", "mrn": CHART, "visit_datetime": "2026-09-01 09:00:00", "dept_code": "RHEU",
                    "staff_id": "P12345", "enc_type": "OPD"}]  # fmt: skip
        elif f.name == "diagnosis.csv":
            add = [{"diag_no": "D77770001", "enc_no": "E77770001", "mrn": CHART, "icd10": "M10.9",
                    "diag_date": "2026-09-01", "recorded_date": "2026-09-01", "status": "A"}]  # fmt: skip
        elif f.name == "note.csv":
            add = [{"note_no": "N77770001", "mrn": CHART, "enc_no": "E77770001", "note_datetime": "2026-09-01 10:00:00",
                    "note_type": "progress",
                    "text": f"Patient {MARK['name']} (chart {CHART}, phone {MARK['phone']}) seen for gout. "
                            "Uric acid high. Continue allopurinol."}]  # fmt: skip
        with f.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, names)
            w.writeheader()
            w.writerows(rows)
            w.writerows([{k: r.get(k, "") for k in names} for r in add])
    return src, keep[0]


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


def _plant(db: Any, table: str, values: dict[str, Any]) -> None:
    """One row: ``values`` and every other required column a distinct dummy of its type (as
    ``test_optout_clears_the_owed_tables._row``)."""
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
    db.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
               tuple(vals[c] for c in names))  # fmt: skip


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
                given: dict[str, Any] = {str(col): value}
                if key == "orch.submissions":
                    given["dry_run"] = 1  # a dry run goes; a live submission stays by D-513 and is not planted
                _plant(db, str(table), given)
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


def _seed_stores(url: str, work: Path, pids: tuple[str, str], lake: Path) -> dict[str, str]:
    """The product write paths this module can reach; returns how each store was seeded."""
    import tb_contracts as c
    from omop import schema
    from omop.load import load_batch
    from orchestrator.db import JobDB
    from orchestrator.recall.ledger import RecallLedger
    from patient_profile.twin import ProfileStore
    from tb_common.objstore import FsStore
    from tb_common.patient_files import HELD
    from tb_contracts.recall import KnownPositiveLineKind

    from tests.unit.test_migrations import store_migrations

    how: dict[str, str] = {}
    p, q = pids
    omop = schema.connect(url)
    load_batch(omop, "feed", SNAP, _batch_from(lake / "ndjson" / SNAP, {p, q}), tz="Asia/Taipei")
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
    try:
        from tracestore.store import TraceStore

        ts = TraceStore(url)
        for pid in (p, q):
            ts.write({"call_id": f"call-{pid}", "prompt": f"Note of {pid}: {MARK['name']} was seen.", "output": "yes",
                      "attributes": {"tb.pid": pid, "tb.data_class": "D2"}})  # fmt: skip
        ts.close()
        how["trace"] = "TraceStore.write"
    except Exception as exc:
        how["trace"] = f"not seeded: {type(exc).__name__}"
    from mail_gateway.store import MailDB

    mail = MailDB(url)
    for i, pid in enumerate((p, q)):
        for kind, fname in (("own", f"twpas_{pid[:16]}.json"), ("list", "candidates.csv")):
            key = f"k-{kind}-{i}"
            mail.claim_send(key, "J1", T0)
            req = {"to": ["pi@hospa.test"], "subject": "TrialBox results",
                   "attachments": [{"filename": fname, "key": f"outputs/J1/{fname}"}]}  # fmt: skip
            mail.hold(key, "failed", request_json=json.dumps(req), message_id=f"<m{i}{kind}@hospa.test>",
                      result_json="{}", recipients=["pi@hospa.test"], attempts=1, next_at=None, error=HELD,
                      at=T0)  # fmt: skip
    mail.close()
    how["mail"] = "MailDB.claim_send and hold: a held mail of the patient's own file, and one of a list"
    store = FsStore(work / "obj", work / "secrets")
    store.put("outputs/J1/candidates.csv", f"pid,tier\n{p},high\n{q},high\n".encode())
    for pid in (p, q):
        store.put(f"outputs/J1/twpas_{pid[:16]}.json", json.dumps({"subject": pid}).encode())
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


def _search(url: str, marker: er.Marker, roots: dict[str, Path], logs: list[str]) -> er.Found:
    found = er.search_db(url, marker)
    found.merge(er.search_tree(roots["lake"], marker, er.lake_key))
    found.merge(er.search_tree(roots["obj"], marker, er.objects_key))
    found.merge(er.search_tree(roots["setup"], marker, lambda rel: "sitesetup.input"))
    found.merge(er.search_tree(roots["audit"], marker, lambda rel: "outside:audit"))
    found.seen("logs:captured")
    for kind, n in er.search_text("\n".join(logs), marker).items():
        found.add("logs:captured", kind, n)
    return found


@pytest.fixture(scope="module")
def reach(pg_cluster_url: str, synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from adapter.pidmap import pseudonym
    from datacore.optout_worker import KEEP_MONTHS, WorkerEnv, run_once
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from omop import schema
    from orchestrator.db import JobDB
    from tb_common.audit import AuditLog
    from tb_common.db import Database
    from tb_common.optout import OptOutRegister

    from tests.inproc_box import ingest_site

    work = tmp_path_factory.mktemp("reach")
    sep = "&" if "?" in pg_cluster_url else "?"
    url = f"{pg_cluster_url}{sep}tb_prefix=v1r{os.getpid()}_"
    logs = _Logs()
    root = logging.getLogger()
    level = root.level
    root.addHandler(logs)
    root.setLevel(logging.DEBUG)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TB_DB_URL", url)
        secrets = work / "secrets"
        secrets.mkdir()
        (secrets / "site_hmac.key").write_bytes(SITE_KEY)
        (secrets / "site_hmac.key").chmod(0o600)
        src, control_chart = _source(synth_dir / "site-a", work)
        lake = work / "lake"
        report = ingest_site(src, lake, secrets, SNAP)
        assert report.passed, "the night's ingest must pass for the lake to hold the patient"
        p = pseudonym(SITE_KEY, CHART)[0]
        q = pseudonym(SITE_KEY, control_chart)[0]
        how = {"lake": "tests.inproc_box.ingest_site (the csv source, the adapter, the lake rebuild, derive)"}
        how |= _seed_stores(url, work, (p, q), lake)
        setup = work / "sitesetup"
        with Database.connect(url, "sitesetup") as db:
            _plant(db, "input", {"pid": p, "ws": "space1"})
            (setup / "space1" / "inputs").mkdir(parents=True)
            for iid in [r[0] for r in db.fetchall("SELECT id FROM input WHERE pid = ?", (p,))]:
                (setup / "space1" / "inputs" / f"{iid}.txt").write_text(f"{CHART},{MARK['name']}\n", encoding="utf-8")
        omop_db = schema.connect(url)
        person_ids = tuple(
            int(x)
            for (x,) in omop_db.fetchall(
                "SELECT omop_id FROM tb_id_map WHERE id_kind = 'person' AND source_id = ?", (p,)
            )
        )
        marker = er.Marker(pid=p, person_ids=person_ids, **MARK)
        control = er.Marker(pid=q)
        roots = {"lake": lake, "obj": work / "obj", "setup": setup, "audit": work / "audit"}
        (work / "audit").mkdir(exist_ok=True)
        seeded = _search(url, marker, roots, logs.lines)
        how["planted"] = json.dumps(_plant_everywhere(url, p, set(seeded.stores)), sort_keys=True)
        _plant_everywhere(url, q, set(er.search_db(url, control).stores))
        before = _search(url, marker, roots, logs.lines)

        reg = OptOutRegister()
        reg.add(p, "paper", "", "console:office1", T0)
        env = WorkerEnv(register=reg, audit=AuditLog(work / "audit"), now=NOW, lake=LakeLocal(lake, HashEmbedder()),
                        jobs=JobDB(), omop=omop_db, extra={"setup_root": setup, KEEP_MONTHS: 36})  # fmt: skip
        tick = run_once(env)
        tick2 = run_once(env)  # a second tick: idempotent, and what a restart runs
        after = _search(url, marker, roots, logs.lines)
        stays = _search(url, control, roots, [])
        omop_db.close()
        reg.close()
    root.removeHandler(logs)
    root.setLevel(level)
    rows = er.reach_rows(before, after, erasure.entries())
    for r in rows:
        r["verdict"] = er.verdict_of(r)
    record = {
        "card": "V-1",
        "what": "tests/unit/test_erasure_reach.py: one synthetic patient seeded, opted out, one worker tick, searched",
        "seeded_by": how,
        "tick": {k: tick[k] for k in ("failed", "left", "opted_out") if k in tick},
        "tick_stores": tick.get("stores"),
        "second_tick_failed": tick2.get("failed"),
        "log_lines": len(logs.lines),
        "stores": rows,
    }
    out = os.environ.get("TB_REACH_OUT")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "reach.json").write_text(
            json.dumps(record, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
    yield {"rows": {r["store"]: r for r in rows}, "record": record, "stays": stays, "before": before,
           "after": after, "tick": tick}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the cases
def _cases() -> list[Any]:
    keys = sorted(set(erasure.entries()) | set(UNLISTED) | {"logs:captured"})
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
    if row["verdict"] == "not_seeded":
        pytest.skip("the marker never reached this store in the unit box: its absence proves nothing")
    if row["verdict"] == "kept":
        e = erasure.entries()[store]
        assert e.kind == erasure.KEEP and e.decision, store  # kept on purpose, with a decision
        return
    assert row["verdict"] == "clean", f"{store}: the opted-out patient is still there ({row['kinds']}, {row['files']})"


def test_the_search_sees_a_patient_who_did_not_opt_out(reach: dict[str, Any]) -> None:
    """The search is not blind: the control patient is still where the marker patient was before the opt-out."""
    stays = reach["stays"].stores
    for k in ("orch.pool", "omop.person", "profile.tb_patient_profile", "lake:db", "lake:parquet", "lake:ndjson",
              "objects:outputs", "trace.traces"):  # fmt: skip
        assert k in stays, k
    assert {"orch.pool", "omop.person", "lake:ndjson", "pidmap.pid_map"} <= set(reach["before"].stores)


def test_the_worker_tick_reports_no_failure(reach: dict[str, Any]) -> None:
    assert reach["tick"]["failed"] == [] and reach["tick"]["left"] == {}, reach["tick"]
    assert reach["tick"]["opted_out"] == 1


def test_no_store_outside_the_registry_holds_the_patient_unseen(reach: dict[str, Any]) -> None:
    """A store the walk finds holding the patient that the registry does not list must be a known finding here."""
    unlisted = {k for k, r in reach["rows"].items() if r["verdict"] == "unlisted"}
    assert unlisted <= set(UNLISTED) | {"logs:captured"}, sorted(unlisted - set(UNLISTED))


def test_no_store_the_registry_calls_erased_holds_the_patient_unseen(reach: dict[str, Any]) -> None:
    leaks = {k for k, r in reach["rows"].items() if r["verdict"] == "leak"}
    assert leaks <= set(KNOWN_LEFT), sorted(leaks - set(KNOWN_LEFT))


@pytest.mark.xfail(strict=True, reason="V1-01: criterion 8 fails: the registry owes erasure in stores inside the box")
def test_criterion_8_no_owed_entry_for_a_store_inside_the_box() -> None:
    """Plan 8, criterion 8: "The erasure registry shows no owed entry for a store inside the box"."""
    inside = [r["store"] for r in er.owed_rows() if r["inside"]]
    assert inside == [], f"{len(inside)} owed inside the box: {inside}"


@pytest.mark.xfail(strict=True, reason="V1-09: a failed recompute logs the pseudonym, and the log scrubber keeps it")
def test_no_log_line_names_an_opted_out_patient(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run above logged no marker value (``logs:captured``). The logging code has two lines that name a
    pseudonym on a failure (``tb_common/derived_store.py`` and ``patient_profile/twin.py``); the box's JSON log
    formatter scrubs chart numbers and phones but not a pseudonym, and the box keeps its logs (json-file, 10 files of
    100 MB per service), which no opt-out reaches. Shown here for the derive batch's line."""
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
