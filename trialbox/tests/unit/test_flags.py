"""Feature flags (T-008, D-207, MR-090): one audited ``app.flag`` table; ``lake.source`` behind it.

The seed happens once; the environment is not read after it; a change is one ``flag_event`` row and one audit event
with the actor and the reason; ``get`` never raises and caches for five seconds; an undeclared name is refused; a
second process sees a change without a restart; the lake rebuild follows the flag."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from tb_common import flags as fl
from tb_common.audit import AuditLog, verify
from tb_common.db import Database

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    yield
    fl.clear_cache()


def _audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit")


def _events(tmp_path: Path, name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == name]


def test_seed_happens_once_and_the_environment_is_ignored_after(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TB_LAKE_SOURCE", "omop")
    f = fl.Flags(audit=_audit(tmp_path))
    assert f.get("lake.source") is None  # nothing seeded yet: the caller's default
    assert f.seed() == [{"name": "lake.source", "value": "omop", "origin": "TB_LAKE_SOURCE"}]
    assert f.get("lake.source") == "omop"
    monkeypatch.setenv("TB_LAKE_SOURCE", "legacy")  # a later start with another value: ignored
    assert f.seed() == []
    fl.clear_cache()
    assert f.get("lake.source") == "omop"
    ev = f.events("lake.source")
    assert [(e["kind"], e["new_value"], e["actor"]) for e in ev] == [("seed", "omop", fl.SEED_ACTOR)]
    seeds = _events(tmp_path, "flag.seed")
    assert len(seeds) == 1 and seeds[0]["detail"]["value"] == "omop" and seeds[0]["actor"] == fl.SEED_ACTOR


def test_seed_without_the_variable_pins_the_declared_default(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.delenv("TB_LAKE_SOURCE", raising=False)
    f = fl.Flags(audit=_audit(tmp_path))
    assert f.seed()[0]["value"] == "legacy" and f.row("lake.source") == "legacy"
    monkeypatch.setenv("TB_LAKE_SOURCE", "omop")
    assert fl.env_drift({"TB_LAKE_SOURCE": "omop"}) == [
        "TB_LAKE_SOURCE=omop is ignored: the flag lake.source is legacy (change it on /ops/flags)"
    ]
    assert fl.env_drift({"TB_LAKE_SOURCE": "legacy"}) == [] and fl.env_drift({}) == []


def test_a_bad_seed_variable_is_refused_never_guessed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TB_LAKE_SOURCE", "fhir")
    with pytest.raises(ValueError, match="TB_LAKE_SOURCE='fhir'"):
        fl.Flags(audit=_audit(tmp_path)).seed()
    assert fl.Flags().row("lake.source") is None


def test_set_is_one_event_and_one_audit_event_with_actor_and_reason(tmp_path: Path) -> None:
    f = fl.Flags(audit=_audit(tmp_path))
    f.seed({})
    out = f.set("lake.source", "omop", actor="console:admin", reason="  WS-03.5:   goldens held  ")
    assert out["old"] == "legacy" and out["new"] == "omop" and out["reason"] == "WS-03.5: goldens held"
    assert f.get("lake.source") == "omop"  # the writer's own cache is cleared
    ev = f.events("lake.source")
    assert [(e["kind"], e["old_value"], e["new_value"], e["actor"], e["reason"]) for e in ev] == [
        ("set", "legacy", "omop", "console:admin", "WS-03.5: goldens held"),
        ("seed", None, "legacy", fl.SEED_ACTOR, "seeded at the first start from the default"),
    ]
    (audit,) = _events(tmp_path, "flag.set")
    assert audit["actor"] == "console:admin"
    assert audit["detail"] == {"flag": "lake.source", "old": "legacy", "new": "omop",
                               "reason": "WS-03.5: goldens held", "event": ev[0]["id"]}  # fmt: skip
    assert verify(tmp_path / "audit").ok
    row = Database.connect(fl.Flags()._url, fl.SCHEMA).fetchdicts("SELECT * FROM flag")
    assert [(r["name"], r["value"], r["changed_by"]) for r in row] == [("lake.source", "omop", "console:admin")]


@pytest.mark.parametrize(
    ("kw", "why"),
    [({"value": "fhir"}, "use one of"), ({"reason": "  "}, "reason"), ({"actor": ""}, "actor"),
     ({"value": "legacy"}, "already legacy")],
)  # fmt: skip
def test_set_refuses(tmp_path: Path, kw: dict[str, str], why: str) -> None:
    f = fl.Flags(audit=_audit(tmp_path))
    f.seed({})
    args = {"value": "omop", "actor": "console:admin", "reason": "x", **kw}
    with pytest.raises(ValueError, match=why):
        f.set("lake.source", args["value"], actor=args["actor"], reason=args["reason"])
    assert [e["kind"] for e in f.events()] == ["seed"] and not _events(tmp_path, "flag.set")


def test_a_change_needs_an_audit_log_and_a_failed_audit_rolls_it_back(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="audited"):
        fl.Flags().set("lake.source", "omop", actor="a", reason="b")

    class Full:
        def append(self, *a: Any, **k: Any) -> None:
            raise OSError("audit volume full")

    f = fl.Flags(audit=Full())
    with pytest.raises(OSError, match="full"):
        f.set("lake.source", "omop", actor="console:admin", reason="flip")
    assert f.row("lake.source") is None and f.events() == []


def test_undeclared_names_are_refused(tmp_path: Path) -> None:
    f = fl.Flags(audit=_audit(tmp_path))
    for call in (lambda: f.get("lake.sauce"), lambda: f.set("lake.sauce", "omop", "a", "b"), lambda: fl.read("x")):
        with pytest.raises(ValueError, match="undeclared flag"):
            call()


def test_get_never_raises_the_default_on_any_error(monkeypatch: Any, caplog: Any) -> None:
    assert fl.Flags(url="postgresql://nobody@/nowhere?host=/nonexistent").get("lake.source", "legacy") == "legacy"
    assert "unreadable" in caplog.text
    monkeypatch.delenv("TB_DB_URL")
    assert fl.Flags().get("lake.source", "omop") == "omop"  # no store configured at all
    assert fl.read("lake.source") is None


def test_the_cache_holds_five_seconds_then_reads_again(tmp_path: Path) -> None:
    now = [1000.0]
    reader = fl.Flags(clock=lambda: now[0])
    writer = fl.Flags(audit=_audit(tmp_path))
    writer.seed({})
    assert reader.get("lake.source") == "legacy"
    fl._CACHE[reader._key("lake.source")] = ("legacy", now[0])  # as another process's cache would be
    Database.connect(writer._url, fl.SCHEMA).execute("UPDATE flag SET value = 'omop'")  # changed elsewhere
    now[0] += fl.CACHE_SECONDS - 0.1
    assert reader.get("lake.source") == "legacy"  # still cached
    now[0] += 0.2
    assert reader.get("lake.source") == "omop"  # expired: read again


def test_a_second_process_sees_the_change_without_a_restart(tmp_path: Path, db_url: str) -> None:
    """Acceptance (1): one long-running process reads the lake source as a rebuild would; this process changes the
    flag; the other sees it at its next read, without a restart."""
    script = textwrap.dedent(
        """
        import sys
        from tb_common import flags
        from lake.source import rebuild_source
        flags.CACHE_SECONDS = 0.0  # the test does not wait out the five seconds
        for line in sys.stdin:
            print(rebuild_source()[0], flush=True)
        """
    )
    env = {"PATH": "/usr/bin:/bin", "TB_DB_URL": db_url, "TB_LAKE_SOURCE": "omop",
           "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT / 'services'}:{ROOT}"}  # fmt: skip
    p = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                         env=env)  # fmt: skip
    assert p.stdin is not None and p.stdout is not None

    def ask() -> str:
        assert p.stdin is not None and p.stdout is not None
        p.stdin.write("?\n")
        p.stdin.flush()
        return p.stdout.readline().strip()

    try:
        assert ask() == "omop"  # not seeded yet: TB_LAKE_SOURCE decides
        f = fl.Flags(audit=_audit(tmp_path))
        f.seed({"TB_LAKE_SOURCE": "omop"})  # the console starts: the flag is seeded from the variable
        assert ask() == "omop"
        f.set("lake.source", "legacy", actor="console:admin", reason="back to legacy for the test")
        assert ask() == "legacy"  # the same process, no restart; its TB_LAKE_SOURCE=omop is ignored now
    finally:
        p.stdin.close()
        p.wait(timeout=30)


def test_the_rebuild_follows_the_flag(tmp_path: Path, monkeypatch: Any) -> None:
    """``lake_rows`` reads the source once per rebuild: legacy rows by default; after the flip to omop, the rows come
    from the OMOP store (its persons are there); the env variable no longer matters."""
    from lake.source import lake_rows

    monkeypatch.delenv("TB_LAKE_SOURCE", raising=False)
    feed: dict[str, list[dict[str, Any]]] = {
        "Patient": [{"resourceType": "Patient", "id": "p1", "birthDate": "1970-01-02", "gender": "female"}],
        "Condition": [{"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"},
                       "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "M10.9"}]},
                       "recordedDate": "2026-01-02"}],
    }  # fmt: skip
    f = fl.Flags(audit=_audit(tmp_path))
    f.seed({})
    lake = tmp_path / "lake"
    legacy = lake_rows(feed, {}, tz="Asia/Taipei", snapshot="2026-10-31", lake_dir=lake)
    from omop.schema import schema_for
    from tb_common.db import split_url

    def persons() -> int | None:
        full = split_url(f._url)[1] + schema_for(lake)
        db = Database.connect(f._url, fl.SCHEMA)
        try:
            if db.fetchval("SELECT to_regclass(?)", (f'"{full}".person',)) is None:
                return None
            return int(db.fetchval(f'SELECT count(*) FROM "{full}".person'))
        finally:
            db.close()

    assert persons() is None  # legacy: no OMOP store was loaded
    f.set("lake.source", "omop", actor="console:admin", reason="flip for the test")
    monkeypatch.setenv("TB_LAKE_SOURCE", "legacy")  # ignored: the flag decides
    omop = lake_rows(feed, {}, tz="Asia/Taipei", snapshot="2026-10-31", lake_dir=lake)
    assert persons() == 1
    assert omop == legacy  # the same rows from either source (D-151)


def test_a_seed_must_be_audited_and_doctor_sees_an_unseeded_flag(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="audited"):
        fl.Flags().seed({})
    assert fl.Flags().row("lake.source") is None
    assert fl.env_drift({"TB_LAKE_SOURCE": "omop"}) == [
        "TB_LAKE_SOURCE=omop still decides: the flag lake.source was never seeded (no console start yet)"
    ]


def test_an_unreadable_flag_store_stops_the_rebuild(monkeypatch: Any) -> None:
    """Review H1: a configured store that cannot be read never falls back to the variable."""
    from lake.source import lake_rows, rebuild_source

    monkeypatch.setenv("TB_DB_URL", "postgresql://nobody@/nowhere?host=/nonexistent")
    monkeypatch.setenv("TB_LAKE_SOURCE", "legacy")
    with pytest.raises(RuntimeError, match="does not guess"):
        rebuild_source()
    with pytest.raises(RuntimeError, match="does not guess"):
        lake_rows({}, {}, tz="Asia/Taipei", snapshot="2026-10-31")
    monkeypatch.delenv("TB_DB_URL")
    assert rebuild_source() == ("legacy", "TB_LAKE_SOURCE (no trial database configured)")


# ---------------------------------------------------------------- T-655: the review fixes of PR #71, ported
def test_a_read_creates_nothing_in_the_database(db_url: str) -> None:
    """``row``, ``get``, ``read``, ``all``, ``events`` and doctor's ``env_drift`` only read: no schema ``app`` and no
    table appears because somebody looked (a read-only role can read a flag)."""
    import psycopg
    from tb_common.db import split_url

    dsn, prefix = split_url(db_url)

    def count(sql: str) -> int:
        with psycopg.connect(dsn, autocommit=True) as con:
            got = con.execute(sql, (prefix + fl.SCHEMA,)).fetchone()
        return int(got[0]) if got else 0

    assert fl.Flags().row("lake.source") is None and fl.read("lake.source") is None
    assert fl.Flags().get("lake.source", "legacy") == "legacy"
    assert fl.env_drift({"TB_LAKE_SOURCE": "omop", "TB_DB_URL": db_url})  # the unseeded warning, read only
    assert count("SELECT count(*) FROM pg_namespace WHERE nspname = %s") == 0
    f = fl.Flags()
    assert [x["value"] for x in f.all()] == [None] and f.events() == []  # the page's reads: no table made
    assert count("SELECT count(*) FROM pg_tables WHERE schemaname = %s") == 0


def test_a_commit_that_fails_after_the_audit_event_is_named_in_the_audit(tmp_path: Path) -> None:
    """Review M5: the audit event is written inside the transaction; when the commit then fails, the trail must not
    say the flag changed without also saying it did not (``flag.set.failed``)."""
    from contextlib import contextmanager

    real = Database.connect(fl.Flags()._url, fl.SCHEMA)

    class LostCommit:
        url = real.url

        def migrate(self, versions: Any) -> int:
            return real.migrate(versions)

        @contextmanager
        def transaction(self) -> Any:
            with real.transaction() as tx:
                yield tx
                raise ConnectionError("server closed the connection at COMMIT")

    f = fl.Flags(LostCommit(), audit=_audit(tmp_path))  # type: ignore[arg-type]
    with pytest.raises(ConnectionError):
        f.set("lake.source", "omop", actor="console:admin", reason="flip")
    real.close()
    assert fl.Flags().row("lake.source") is None and fl.Flags().events() == []
    (said,) = _events(tmp_path, "flag.set")
    (failed,) = _events(tmp_path, "flag.set.failed")
    assert failed["actor"] == "console:admin"
    assert failed["detail"] == {**said["detail"], "error": "ConnectionError"}
    assert verify(tmp_path / "audit").ok


def test_a_refused_change_writes_no_failed_event(tmp_path: Path) -> None:
    """``flag.set.failed`` names only a change whose audit event was written: a refusal before it writes neither."""
    f = fl.Flags(audit=_audit(tmp_path))
    f.seed({})
    with pytest.raises(ValueError, match="already legacy"):
        f.set("lake.source", "legacy", actor="console:admin", reason="same value")
    assert not _events(tmp_path, "flag.set") and not _events(tmp_path, "flag.set.failed")


def test_a_tool_forces_its_source_whatever_the_flag_says(tmp_path: Path, monkeypatch: Any) -> None:
    """Review H2: ``tools/omop_parity.py`` and ``tools/goldens.py`` build both lakes in a database whose flag may be
    seeded; ``force`` wins over the flag and the variable, and ends with its block."""
    from lake import source as src

    fl.Flags(audit=_audit(tmp_path)).seed({"TB_LAKE_SOURCE": "legacy"})
    monkeypatch.setenv("TB_LAKE_SOURCE", "legacy")
    with src.force("omop"):
        assert src.rebuild_source() == ("omop", "forced by the caller (a tool)")
        with src.force("legacy"):
            assert src.rebuild_source()[0] == "legacy"
        assert src.rebuild_source()[0] == "omop"
    assert src.rebuild_source() == ("legacy", "flag lake.source")
    with pytest.raises(ValueError, match="use one of"), src.force("fhir"):
        pass


def test_the_parity_tool_forces_each_source_and_checks_the_record() -> None:
    from tools import omop_parity as parity

    assert "force(source)" in (ROOT / "tools" / "omop_parity.py").read_text(encoding="utf-8")
    entry = {"omop": {"rows": {"person": 3}}, "tables": {"patient": {"rows": 3}},
             "screening": {"R": {"patients_evaluated": 3}}}  # fmt: skip
    assert parity.failures({**entry, "recorded_source": {"legacy": "legacy", "omop": "omop"}}) == []
    assert parity.failures({**entry, "recorded_source": {"legacy": "legacy", "omop": "legacy"}}) == [
        "the omop lake was meant to come from omop, its rebuild recorded legacy"
    ]


def test_the_rebuild_records_its_source(tmp_path: Path, monkeypatch: Any) -> None:
    """Review M2: what built a snapshot is kept (``source.jsonl`` in the lake, an audit event where the audit log is
    mounted), not only logged."""
    from lake.source import lake_rows

    from tools.omop_parity import recorded_source

    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.delenv("TB_LAKE_SOURCE", raising=False)
    fl.Flags(audit=_audit(tmp_path)).seed({})
    lake = tmp_path / "lake"
    lake_rows({}, {}, tz="Asia/Taipei", snapshot="2026-10-31", lake_dir=lake)
    (line,) = [json.loads(x) for x in (lake / "source.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {k: line[k] for k in ("snapshot", "source", "origin")} == {
        "snapshot": "2026-10-31", "source": "legacy", "origin": "flag lake.source"}  # fmt: skip
    (ev,) = _events(tmp_path, "lake.rebuild.source")
    assert ev["actor"] == "lake" and ev["detail"]["source"] == "legacy" and ev["detail"]["snapshot"] == "2026-10-31"
    assert verify(tmp_path / "audit").ok
    assert recorded_source(lake, "2026-10-31") == "legacy" and recorded_source(lake, "2026-11-01") is None
