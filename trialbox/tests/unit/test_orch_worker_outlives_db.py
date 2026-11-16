"""D-895: a job worker outlives the database. Train 39's validation rehearsal restarted the stack without the
installer; the orchestrator came up before host ``db`` resolved, every worker's claim raised ``DatabaseError`` and
the worker threads ended. The API stayed up, so a SCREEN job was accepted and never taken ("after a reboot, jobs
queue for ever and doctor is green"). Now a worker that cannot reach the database waits and tries again, never
ending, and the health line is red when fewer workers are alive than were started.

The database is taken away for real: the orchestrator's job store talks to the test cluster through a small TCP
relay that the test closes (every connection cut, new ones refused) and opens again on the same port."""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
from psycopg.conninfo import conninfo_to_dict
from tb_common.db import split_url

ROOT = Path(__file__).resolve().parents[2]


class Relay:
    """A TCP relay to the PostgreSQL server: ``down()`` cuts every connection and refuses new ones, ``up()`` listens
    again on the same port."""

    def __init__(self, target: tuple[str, Any]) -> None:
        self.target = target  # ("unix", path) or ("tcp", (host, port))
        self.port = 0
        self._conns: list[socket.socket] = []
        self._lock = threading.Lock()
        self._srv: socket.socket | None = None
        self.up()

    def _dial(self) -> socket.socket:
        kind, where = self.target
        s = socket.socket(socket.AF_UNIX if kind == "unix" else socket.AF_INET, socket.SOCK_STREAM)
        s.connect(where)
        return s

    def up(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.port))
        srv.listen(16)
        self.port = srv.getsockname()[1]
        self._srv = srv
        threading.Thread(target=self._accept, args=(srv,), daemon=True).start()

    def _accept(self, srv: socket.socket) -> None:
        while True:
            try:
                client, _ = srv.accept()
            except OSError:
                return
            try:
                server = self._dial()
            except OSError:
                client.close()
                continue
            with self._lock:
                self._conns += [client, server]
            for a, b in ((client, server), (server, client)):
                threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket) -> None:
        try:
            while data := a.recv(65536):
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                with contextlib.suppress(OSError):
                    s.shutdown(socket.SHUT_RDWR)

    def down(self) -> None:
        if self._srv is not None:
            with contextlib.suppress(OSError):  # wakes the accepting thread: a closed socket alone keeps listening
                self._srv.shutdown(socket.SHUT_RDWR)
            self._srv.close()
            self._srv = None
        with self._lock:
            for s in self._conns:
                with contextlib.suppress(OSError):
                    s.shutdown(socket.SHUT_RDWR)
                s.close()
            self._conns.clear()


def _relayed(url: str) -> tuple[str, Relay]:
    """``url`` with its server replaced by a relay to that server (the tb_prefix and the rest kept)."""
    info = conninfo_to_dict(split_url(url)[0])
    host, port = str(info.get("host") or "/tmp"), int(info.get("port") or 5432)
    target: tuple[str, Any] = ("unix", f"{host}/.s.PGSQL.{port}") if host.startswith("/") else ("tcp", (host, port))
    relay = Relay(target)
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("host", "port")]
    query.append(("connect_timeout", "2"))
    user = parts.netloc.rsplit("@", 1)[0] + "@" if "@" in parts.netloc else ""
    netloc = f"{user}127.0.0.1:{relay.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), "")), relay


def _orch(tmp_path: Path, url: str, ran: list[str], workers: int) -> Any:
    from orchestrator.core import Orchestrator, Services
    from orchestrator.db import JobDB
    from tb_common.audit import AuditLog
    from tb_common.config import Config, load_env, load_settings
    from tb_common.objstore import FsStore

    def scenario(ctx: Any) -> Any:
        ran.append(ctx.job.job_id)

    cfg = Config(env=load_env(dotenv=tmp_path / "x.env", environ={}),
                 settings=load_settings(ROOT / "deploy/settings.example.yaml"))  # fmt: skip
    return Orchestrator(
        cfg, JobDB(url), FsStore(tmp_path / "obj"), AuditLog(tmp_path / "audit"),
        Services(lake=None, parser=None, compiler=None, mail=None, adapter=None),  # type: ignore[arg-type]
        {"INGEST": scenario}, tmp_path / "rulesets", tmp_path, workers=workers, async_notify=False,
    )  # fmt: skip


def _wait(cond: Any, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_a_worker_whose_database_goes_away_keeps_trying_and_takes_a_job_when_it_is_back(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from orchestrator import core
    from tb_contracts import JobCreate

    monkeypatch.setattr(core, "WORKER_RETRY_FIRST", 0.05)
    monkeypatch.setattr(core, "WORKER_RETRY_MAX", 0.2)
    relayed, relay = _relayed(db_url)
    ran: list[str] = []
    o = _orch(tmp_path, relayed, ran, workers=2)
    claims = {"failed": 0}
    real_claim = o.db.claim

    def counted(only: tuple[str, ...] = ()) -> str | None:
        try:
            got: str | None = real_claim(only)
            return got
        except Exception:
            claims["failed"] += 1
            raise

    monkeypatch.setattr(o.db, "claim", counted)
    o.start()
    try:
        assert o.workers_alive() == (2, 2)
        relay.down()  # the database goes away under the running workers
        assert _wait(lambda: claims["failed"] >= 6, 20), claims  # each worker failed, waited and tried again
        assert o.workers_alive() == (2, 2)  # before D-895: (0, 2), the threads had ended
        assert "cannot claim a job" in caplog.text
        relay.up()
        job = o.create(JobCreate(type="INGEST", requested_by="scheduler"), notify=False)
        assert _wait(lambda: job.job_id in ran, 20), "the job was accepted and never taken"
        assert o.workers_alive() == (2, 2)
    finally:
        o.stop()
        relay.down()


def test_the_health_line_is_red_when_a_started_worker_is_dead(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator import app as orch_app

    o = _orch(tmp_path, db_url, [], workers=2)
    monkeypatch.setattr(orch_app, "_orch", o)
    assert orch_app._workers() == {"workers_alive": "0/0"}  # not started (a test client without its lifespan)
    o.start()
    try:
        assert orch_app._workers() == {"workers_alive": "2/2"}
        dead = threading.Thread(target=lambda: None, name="worker-dead")
        dead.start()
        dead.join()
        o._threads.append(dead)  # a worker thread that ended
        with pytest.raises(orch_app.WorkersNotAlive, match="2 of 3 job workers alive"):
            orch_app._workers()
        from fastapi.testclient import TestClient

        r = TestClient(orch_app.app).get("/healthz")  # no lifespan: the same orchestrator, its health only
        assert r.status_code == 503 and r.json()["checks"]["_workers"] == "error: WorkersNotAlive"
    finally:
        o.stop()


def test_the_orchestrator_waits_for_a_healthy_database_in_every_compose_file() -> None:
    """(d) of the card: the base file's services start after ``db`` is healthy. A daemon restart (a reboot) starts
    the containers without compose's order, which is what the worker's own retry covers."""
    import yaml

    base = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    dep = base["services"]["orchestrator"].get("depends_on", {})
    assert dep.get("db", {}).get("condition") == "service_healthy"
