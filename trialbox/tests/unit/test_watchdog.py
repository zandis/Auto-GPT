"""T-108a (D-360; OPS-029): the host watchdog restarts a service whose health check fails and audits it.

The acceptance case: a vLLM whose /health stops answering is restarted and an ``ops.watchdog.restart`` line is in the
hash-chained audit log. Docker is replaced by a fake that keeps a container's health the way Docker does (a real HTTP
probe of a real local server, ``retries`` failures in a row make it unhealthy, ``docker restart`` starts the server
again); the watchdog under test is the real one, with its real command lines.
"""

from __future__ import annotations

import http.server
import json
import threading
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from tb_common.audit import AuditLog, verify

from tools.trialbox import __main__ as tb_main
from tools.trialbox import watchdog as wd


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        ok = self.path == "/health"
        self.send_response(200 if ok else 404)
        self.end_headers()

    def log_message(self, *a: object) -> None:
        pass


class FakeVllm:
    """A stand-in for the vLLM server: a real /health endpoint that can be stopped and started."""

    def __init__(self) -> None:
        self.srv: http.server.HTTPServer | None = None
        self.port = 0
        self.start()

    def start(self) -> None:
        self.srv = http.server.HTTPServer(("127.0.0.1", self.port), _Health)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None

    def probe(self) -> int:
        """The compose health check of llm-service, against this server: exit 0 when /health answers."""
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2)
            return 0
        except OSError:
            return 1


class FakeDocker:
    """`docker ps`, `docker inspect` and `docker restart` of a compose project, with Docker's health rule."""

    def __init__(self, project: str = "trialbox", retries: int = 3) -> None:
        self.project = project
        self.retries = retries
        self.containers: dict[str, dict[str, Any]] = {}
        self.calls: list[list[str]] = []
        self.fail_restart = False

    def add(self, service: str, mode: str, probe: Any = None, restart: Any = None, health: str = "healthy") -> None:
        cid = f"{service}-id"
        self.containers[cid] = {"service": service, "mode": mode, "probe": probe, "on_restart": restart,
                                "status": health, "streak": 0, "exit": 0}  # fmt: skip

    def check(self) -> None:
        """One health-check interval: run each probe; `retries` failures in a row make the container unhealthy."""
        for c in self.containers.values():
            if c["probe"] is None:
                continue
            c["exit"] = c["probe"]()
            c["streak"] = 0 if c["exit"] == 0 else c["streak"] + 1
            c["status"] = "healthy" if c["exit"] == 0 else ("unhealthy" if c["streak"] >= self.retries else c["status"])

    def __call__(self, argv: Sequence[str], timeout: float) -> str:
        argv = list(argv)
        self.calls.append(argv)
        if argv[:2] == ["docker", "ps"]:
            assert f"label=com.docker.compose.project={self.project}" in argv and "label=tb.watchdog" in argv
            return "\n".join(self.containers) + "\n"
        if argv[:2] == ["docker", "inspect"]:
            return json.dumps([self._inspect(cid) for cid in argv[2:]])
        if argv[:2] == ["docker", "restart"]:
            if self.fail_restart:
                raise wd.WatchdogError("docker restart ... exit 1: no such container")
            c = self.containers[argv[-1]]
            if c["on_restart"]:
                c["on_restart"]()
            c.update(status="starting", streak=0)
            return argv[-1] + "\n"
        raise AssertionError(argv)

    def _inspect(self, cid: str) -> dict[str, Any]:
        c = self.containers[cid]
        labels = {
            "com.docker.compose.service": c["service"],
            "com.docker.compose.project": self.project,
            "tb.watchdog": c["mode"],
        }
        log = [{"ExitCode": c["exit"], "Output": "not for the audit"}]
        health = {"Status": c["status"], "FailingStreak": c["streak"], "Log": log}
        state = {"Status": "running", "Health": health}
        return {"Id": cid, "Name": f"/trialbox-{c['service']}-1", "Config": {"Labels": labels}, "State": state}


class Clock:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t

    def tick(self, minutes: float) -> None:
        self.t += minutes * 60


def _local_audit(directory: Path) -> wd.AuditWriter:
    def write(e: dict[str, Any]) -> None:
        AuditLog(directory).append(e["event"], actor=e["actor"], detail=e["detail"])

    return write


def _events(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for f in sorted(directory.glob("*.jsonl")) for ln in f.read_text().splitlines()]


@pytest.fixture
def vllm() -> Any:
    v = FakeVllm()
    yield v
    v.stop()


def _watchdog(tmp_path: Path, docker: FakeDocker, clock: Clock, **kw: Any) -> wd.Watchdog:
    return wd.Watchdog(tmp_path / "deploy", run=docker, audit=_local_audit(tmp_path / "audit"), clock=clock,
                       out=lambda _m: None, **kw)  # fmt: skip


def test_a_stopped_vllm_health_endpoint_leads_to_a_restart_and_an_audit_line(tmp_path: Path, vllm: FakeVllm) -> None:
    docker, clock = FakeDocker(), Clock()
    docker.add("llm-service", "restart", probe=vllm.probe, restart=vllm.start)
    w = _watchdog(tmp_path, docker, clock, after_minutes=2)
    docker.check()
    assert w.tick() == [] and not (tmp_path / "audit").exists()  # healthy: nothing to do

    vllm.stop()  # the server hangs: /health no longer answers
    for _ in range(docker.retries):
        docker.check()
        clock.tick(0.5)
    assert docker.containers["llm-service-id"]["status"] == "unhealthy"
    assert [a["action"] for a in w.tick()] == ["waiting"]  # unhealthy, not yet for --after-minutes
    clock.tick(2)
    docker.check()
    acts = w.tick()
    assert [a["action"] for a in acts] == ["restarted"]
    assert ["docker", "restart", "--time", "60", "llm-service-id"] in docker.calls

    ev = [e for e in _events(tmp_path / "audit") if e["event"].startswith("ops.watchdog")]
    assert len(ev) == 1 and ev[0]["event"] == "ops.watchdog.restart" and ev[0]["actor"] == "trialbox-watchdog"
    d = ev[0]["detail"]
    assert d["service"] == "llm-service" and d["container"] == "trialbox-llm-service-1"
    assert d["unhealthy_minutes"] >= 2 and d["failing_streak"] >= 3 and d["last_exit"] == 1
    assert "not for the audit" not in json.dumps(ev)  # never the health check's output
    assert verify(tmp_path / "audit").ok  # the chain holds

    docker.check()  # the restarted server answers again
    assert docker.containers["llm-service-id"]["status"] == "healthy"
    assert w.tick() == [] and len(_events(tmp_path / "audit")) == 1


def test_a_restart_loop_stops_after_the_cap_and_is_audited_once(tmp_path: Path) -> None:
    docker, clock = FakeDocker(), Clock()
    docker.add("orchestrator", "restart", health="unhealthy")  # stays unhealthy whatever is done
    w = _watchdog(tmp_path, docker, clock, after_minutes=0, max_restarts=2, window_hours=6)
    acts = []
    for _ in range(5):
        docker.containers["orchestrator-id"]["status"] = "unhealthy"
        acts += [a["action"] for a in w.tick()]
        clock.tick(5)
    assert acts == ["restarted", "restarted", "gave_up"]
    names = [e["event"] for e in _events(tmp_path / "audit")]
    assert names == ["ops.watchdog.restart", "ops.watchdog.restart", "ops.watchdog.gave_up"]
    clock.tick(6 * 60)  # the window has passed: restarts allowed again, but only after a healthy spell
    docker.containers["orchestrator-id"]["status"] = "healthy"
    w.tick()
    docker.containers["orchestrator-id"]["status"] = "unhealthy"
    assert [a["action"] for a in w.tick()] == ["restarted"]


def test_the_database_is_reported_once_and_never_restarted(tmp_path: Path) -> None:
    docker, clock = FakeDocker(), Clock()
    docker.add("db", "report", health="unhealthy")
    w = _watchdog(tmp_path, docker, clock, after_minutes=1)
    w.tick()
    clock.tick(2)
    assert [a["action"] for a in w.tick()] == ["reported"]
    clock.tick(2)
    assert w.tick() == []
    assert not any(c[:2] == ["docker", "restart"] for c in docker.calls)
    assert [e["event"] for e in _events(tmp_path / "audit")] == ["ops.watchdog.unhealthy"]


def test_a_failed_restart_is_audited_and_counts_toward_the_cap(tmp_path: Path) -> None:
    docker, clock = FakeDocker(), Clock()
    docker.add("gateway", "restart", health="unhealthy")
    docker.fail_restart = True
    w = _watchdog(tmp_path, docker, clock, after_minutes=0, max_restarts=1)
    assert [a["action"] for a in w.tick()] == ["restart_failed"]
    clock.tick(1)
    assert [a["action"] for a in w.tick()] == ["gave_up"]
    ev = _events(tmp_path / "audit")
    assert [e["event"] for e in ev] == ["ops.watchdog.restart_failed", "ops.watchdog.gave_up"]
    assert "no such container" in ev[0]["detail"]["error"]


def test_an_audit_that_cannot_be_written_waits_and_is_written_first_next_time(tmp_path: Path) -> None:
    docker, clock = FakeDocker(), Clock()
    docker.add("console", "restart", health="unhealthy")
    good = _local_audit(tmp_path / "audit")
    down = {"yes": True}

    def flaky(e: dict[str, Any]) -> None:
        if down["yes"]:
            raise wd.WatchdogError("orchestrator is not running")
        good(e)

    w = wd.Watchdog(tmp_path / "deploy", run=docker, audit=flaky, clock=clock, after_minutes=0, out=lambda _m: None)
    assert [a["action"] for a in w.tick()] == ["restarted"]
    pending = (tmp_path / "deploy/watchdog/pending_audit.jsonl").read_text().splitlines()
    assert [json.loads(p)["event"] for p in pending] == ["ops.watchdog.restart"]
    down["yes"] = False
    docker.containers["console-id"]["status"] = "healthy"
    w.tick()
    assert [e["event"] for e in _events(tmp_path / "audit")] == ["ops.watchdog.restart"]
    assert not (tmp_path / "deploy/watchdog/pending_audit.jsonl").exists()


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    docker, clock = FakeDocker(), Clock()
    docker.add("lake", "restart", health="unhealthy")
    w = _watchdog(tmp_path, docker, clock, after_minutes=0, dry_run=True)
    assert [a["action"] for a in w.tick()] == ["would_restart"]
    assert not any(c[:2] == ["docker", "restart"] for c in docker.calls)
    assert not (tmp_path / "audit").exists() and not (tmp_path / "deploy/watchdog").exists()


def test_the_site_audit_is_written_inside_the_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_COMPOSE", raising=False)
    seen: list[list[str]] = []

    def run(argv: Sequence[str], timeout: float) -> str:
        seen.append(list(argv))
        return ""

    wd.compose_audit(tmp_path, run)({"event": "ops.watchdog.restart", "actor": wd.ACTOR, "detail": {"service": "x"}})
    argv = seen[0]
    assert argv[:4] == ["docker", "compose", "--project-directory", str(tmp_path)]
    assert argv[4:9] == ["exec", "-T", "orchestrator", "python", "-c"]
    assert "open_audit().append" in argv[9] and json.loads(argv[10])["detail"] == {"service": "x"}


def test_no_container_without_the_label_is_touched(tmp_path: Path) -> None:
    """Only labelled containers of this project: an unknown mode is ignored."""
    docker, clock = FakeDocker(), Clock()
    docker.add("other", "sometimes", health="unhealthy")
    assert _watchdog(tmp_path, docker, clock, after_minutes=0).tick() == []


def test_the_cli_runs_one_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    got: dict[str, Any] = {}

    def fake_main(deploy: Path, **kw: Any) -> int:
        got.update(deploy=deploy, **kw)
        return 0

    monkeypatch.setattr(wd, "main", fake_main)
    assert tb_main.main(["watchdog", "--deploy", str(tmp_path), "--after-minutes", "3", "--dry-run"]) == 0
    assert got == {"deploy": tmp_path, "interval": 0, "after_minutes": 3.0, "max_restarts": 3, "window_hours": 6.0,
                   "dry_run": True, "as_json": False}  # fmt: skip


def test_no_docker_is_an_error_not_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setenv("TB_DOCKER", str(tmp_path / "no-docker"))
    assert wd.main(tmp_path, as_json=True) == 1
    out = capsys.readouterr()
    assert out.out.strip() == "[]" and "watchdog:" in out.err
