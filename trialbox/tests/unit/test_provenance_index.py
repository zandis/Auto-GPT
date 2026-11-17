"""D-989 step 2c: the provenance index, derived from the audit chain, rebuilt and checked against it, and searched.

* ``llm.call`` gives a call row (model, build, prompt id, version, sha); ``ai.used`` and ``ai.confirmed`` give a use
  row per call; every other event, and a call from before step 1 (no call id), gives none;
* "which records did build X influence" is one join: the search returns the records and how they were touched;
* the index is rebuilt from the chain and checked against it line by line; a row missing or extra is named, and a
  line written twice is one row;
* at an opt-out the patient's use rows go; a rebuild leaves them out and the check does not report them missing;
* the drain writes the index after the chain line, only when it is installed, and a failed index write never stops
  it; the CLI and the doctor say the same as the module.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tb_common import provenance
from tb_common import provenance_index as idx
from tb_common.audit import AuditLog
from tb_common.audit_writer import Drain, _dsn

PID_A = "0ca5381cfa6bdf1c22961d65579f93b3"
PID_B = "1afe78d42518132b113c5858cedcbb54"
_N = itertools.count()


@pytest.fixture
def con(pg_cluster_url: str) -> Iterator[Any]:
    """A database of this test's own, with the index's schema and tables."""
    import psycopg

    name = f"tb_prov_{os.getpid()}_{next(_N)}"
    admin = psycopg.connect(_dsn(pg_cluster_url), autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(_dsn(pg_cluster_url), dbname=name)
    c = psycopg.connect(dsn, autocommit=True)
    c.execute(idx.INDEX_SQL)
    c.info_dsn = dsn  # type: ignore[attr-defined]
    try:
        yield c
    finally:
        c.close()
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.close()


def _call(log: AuditLog, call_id: str, build: str = "b1", prompt: str = "judge_v4") -> dict[str, Any]:
    return log.append("llm.call", model="m-judge", prompt_version=prompt, input_sha="i", output_sha="o",
                      detail={"call_id": call_id, "build_sha": build, "prompt_sha": "p" * 64})  # fmt: skip


def provenance_rec(log: AuditLog, crit: dict[str, str]) -> dict[str, Any]:
    """A confirmation taken back (D-1152): its own line, the same record and calls; the search shows it as such."""
    provenance.confirmed(log, "criterion", crit, ["c1"], "crc1@hospa.test", "withdrawn")
    (rec,) = [r for r in idx.chain_records(log.directory) if (r.get("detail") or {}).get("decision") == "withdrawn"]
    return rec


def _chain(tmp_path: Path) -> AuditLog:
    log = AuditLog(tmp_path / "audit")
    _call(log, "c1")
    _call(log, "c2", build="b2")
    _call(log, "")  # a call from before D-989 step 1: no call id, no row
    log.append("job.done", job_id="J1")  # any other event: no row
    v = provenance.ref(ruleset="GZQO", version="1.0.0", job="J1", pid=PID_A, crit="N-INC-01")
    provenance.used(log, "verdict", v, ["c1", "c2"])
    provenance.used(log, "verdict", provenance.ref(ruleset="GZQO", version="1.0.0", job="J1", pid=PID_B,
                                                   crit="N-INC-01"), ["c2"])  # fmt: skip
    crit = provenance.ref(ruleset="GZQO", version="1.0.0", crit="INC-01")
    provenance.used(log, "criterion", crit, ["c1"])
    provenance.confirmed(log, "criterion", crit, ["c1"], "crc1@hospa.test", "changed")
    return log


def test_each_event_gives_its_rows_and_others_give_none(tmp_path: Path) -> None:
    log = _chain(tmp_path)
    recs = list(idx.chain_records(log.directory))
    calls = [c for r in recs for c in idx.rows_of(r)[0]]
    uses = [u for r in recs for u in idx.rows_of(r)[1]]
    assert [(c.call_id, c.build_sha, c.prompt_id, c.prompt_version) for c in calls] == [
        ("c1", "b1", "judge", "4"), ("c2", "b2", "judge", "4")]  # fmt: skip
    assert [(u.call_id, u.event, u.record_kind, u.pid) for u in uses] == [
        ("c1", "used", "verdict", PID_A), ("c2", "used", "verdict", PID_A), ("c2", "used", "verdict", PID_B),
        ("c1", "used", "criterion", None), ("c1", "confirmed", "criterion", None)]  # fmt: skip
    assert uses[-1].decision == "changed" and uses[-1].by_whom == "crc1@hospa.test"


def test_which_records_a_build_touched_is_one_search(con: Any, tmp_path: Path) -> None:
    log = _chain(tmp_path)
    assert idx.rebuild(con, log.directory) == (2, 5)
    got = idx.search(con, build_sha="b2")
    assert sorted(r["record_ref"]["pid"] for r in got) == sorted([PID_A, PID_B])
    by_prompt = idx.search(con, prompt_id="judge", prompt_version="4", model="m-judge")
    assert {(r["record_kind"], r["event"]) for r in by_prompt} == {
        ("verdict", "used"), ("criterion", "used"), ("criterion", "confirmed")}  # fmt: skip
    assert idx.search(con, build_sha="nobody") == []
    crit = provenance.ref(ruleset="GZQO", version="1.0.0", crit="INC-01")
    idx.add(con, provenance_rec(log, crit))
    took_back = [r for r in idx.search(con, build_sha="b1") if r["decision"] == "withdrawn"]
    assert [(r["record_kind"], r["event"], r["by"]) for r in took_back] == [
        ("criterion", "confirmed", "crc1@hospa.test")
    ]
    with pytest.raises(ValueError, match="name a model"):
        idx.search(con)


def test_the_index_is_checked_against_the_chain_line_by_line(con: Any, tmp_path: Path) -> None:
    log = _chain(tmp_path)
    idx.rebuild(con, log.directory)
    assert idx.check(con, log.directory).ok
    rec = _call(log, "c3", build="b3")  # a line the index has not seen
    diff = idx.check(con, log.directory)
    assert diff.missing == [("provenance.model_calls", rec["hash"], "c3")] and not diff.extra
    idx.add(con, rec)
    idx.add(con, rec)  # written twice: one row
    assert idx.check(con, log.directory).ok
    con.execute("INSERT INTO provenance.model_calls (rec_hash, call_id, at) VALUES ('forged', 'cX', now())")
    assert idx.check(con, log.directory).extra == [("provenance.model_calls", "forged", "cX")]


def test_an_opt_out_takes_the_patients_use_rows_and_a_rebuild_keeps_them_out(con: Any, tmp_path: Path) -> None:
    log = _chain(tmp_path)
    idx.rebuild(con, log.directory)
    assert idx.erase(con, [PID_A]) == 2
    assert not idx.check(con, log.directory).ok  # the chain still names her: the check is told who is out
    assert idx.check(con, log.directory, erased=[PID_A]).ok
    idx.rebuild(con, log.directory, erased=[PID_A])
    assert all(r["record_ref"].get("pid") != PID_A for r in idx.search(con, model="m-judge"))
    assert idx.erase(con, []) == 0


def test_the_drain_writes_the_index_only_when_installed_and_never_stops_on_it(con: Any, tmp_path: Path) -> None:
    drain = Drain("postgresql://x@h/db", tmp_path / "chain", "Asia/Taipei", connect=lambda: con)
    drain.con = con
    assert drain._index_installed()
    rec = _call(drain.chain, "c9")
    drain._index(rec)
    assert [r[0] for r in con.execute("SELECT call_id FROM provenance.model_calls").fetchall()] == ["c9"]
    con.execute("DROP TABLE provenance.model_uses")
    assert not drain._index_installed()

    class Broken:
        def execute(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("the index refused")

    drain.con = Broken()
    drain._index(rec)  # logged, never raised


def test_the_cli_and_the_doctor_say_what_the_module_says(
    con: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.trialbox import doctor
    from tools.trialbox import provenance as cli

    log = _chain(tmp_path)
    url = "postgresql:///x"
    monkeypatch.setattr(cli, "_connect", lambda _u: con)
    monkeypatch.setattr(cli, "_erased", lambda _u: frozenset())
    monkeypatch.setattr(con, "close", lambda: None)
    args = ["--db-url", url, "--audit-dir", str(log.directory)]
    assert cli.main(["--rebuild", *args]) == 0
    assert cli.main(["--check", *args]) == 0
    assert cli.main(["--search", "--build", "b2", *args]) == 0
    assert "2 record(s)" in capsys.readouterr().out
    _call(log, "c4")
    assert cli.main(["--check", *args]) == 1
    assert "1 row(s) missing" in capsys.readouterr().out

    assert doctor.check_provenance_index(doctor.DoctorInputs(env={})).detail.startswith("NOT CHECKED")
    import psycopg
    from tb_common import optout

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: con)
    monkeypatch.setattr(optout, "opted_out", lambda *a, **k: frozenset())
    env = {"TB_DB_URL": url, "TB_AUDIT_DIR": str(log.directory)}
    assert doctor.check_provenance_index(doctor.DoctorInputs(env=env)).status == "FAIL"
    idx.rebuild(con, log.directory)
    assert doctor.check_provenance_index(doctor.DoctorInputs(env=env)).status == "PASS"
