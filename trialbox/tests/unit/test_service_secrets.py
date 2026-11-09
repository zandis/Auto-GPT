"""TB-PLAN-04 step 8 (D-128, D-138): one token per service, accepted only from its own callers; generated 0600,
never printed; rotated with one command; the old shared token works until the rotation, with a warning."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from tb_common import service_auth as sa
from tb_common.http import make_app

from tools.trialbox import svc_secrets as sx

ROOT = Path(__file__).resolve().parents[2]


def _app(name: str, protect_reads: bool = True) -> TestClient:
    app = make_app(name, protect_reads=protect_reads)

    @app.post("/x")
    def x() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/r")
    def r() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


@pytest.fixture()
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_SITE_ID=T\nTB_SERVICE_TOKEN=old-shared-token-0123456789\n", encoding="utf-8")
    sx.init(deploy, uid=None)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv(sa.REGISTRY_ENV, str(sx.registry_path(deploy)))
    return deploy


def _tok(deploy: Path, name: str) -> str:
    return sx.token_path(deploy, name).read_text(encoding="utf-8").strip()


def _as(monkeypatch: pytest.MonkeyPatch, deploy: Path, name: str) -> dict[str, str]:
    """This process plays service ``name``: its own token file, as the compose overlay mounts it."""
    monkeypatch.setenv("TB_SERVICE_TOKEN_FILE", str(sx.token_path(deploy, name)))
    return sa.auth_headers()


def test_init_makes_one_private_token_per_service_and_a_registry_of_hashes(box: Path) -> None:
    names = {p.stem for p in sx.secrets_dir(box).glob("*.token")}
    assert names == set(sx.IDENTITIES)
    tokens = {n: _tok(box, n) for n in names}
    assert len(set(tokens.values())) == len(tokens) and all(len(t) >= 40 for t in tokens.values())
    for n in names:
        assert stat.S_IMODE(sx.token_path(box, n).stat().st_mode) == 0o600
    assert stat.S_IMODE(sx.secrets_dir(box).stat().st_mode) == 0o700
    reg = sx.registry_path(box).read_text(encoding="utf-8")
    assert not any(t in reg for t in tokens.values())  # hashes only
    assert json.loads(reg)["legacy"] == sa.token_hash("old-shared-token-0123456789")
    before = {n: _tok(box, n) for n in names}
    assert sx.init(box, uid=None).created == [] and {n: _tok(box, n) for n in names} == before  # idempotent


def test_each_service_accepts_only_its_own_callers(box: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orch = _app("orchestrator")
    assert orch.post("/x", headers=_as(monkeypatch, box, "console")).status_code == 200
    assert orch.get("/r", headers=_as(monkeypatch, box, "mail-gateway")).status_code == 200
    # review F-02: a doc-parser token (the least trusted container) cannot reveal a chart number
    r = orch.post("/x", headers=_as(monkeypatch, box, "doc-parser"))
    assert r.status_code == 403 and "doc-parser may not call orchestrator" in r.text
    assert orch.post("/x", headers=_as(monkeypatch, box, "operator")).status_code == 200
    assert orch.post("/x", headers={sa.TOKEN_HEADER: "not-a-token"}).status_code == 403
    assert orch.post("/x").status_code == 401
    assert orch.get("/healthz").status_code == 200
    lake = _app("lake")
    assert lake.get("/r", headers=_as(monkeypatch, box, "criteria-compiler")).status_code == 200
    assert lake.get("/r", headers=_as(monkeypatch, box, "console")).status_code == 403
    assert _app("embed-service").post("/x", headers=_as(monkeypatch, box, "lake")).status_code == 200
    assert _app("embed-service").post("/x", headers=_as(monkeypatch, box, "gateway")).status_code == 403


def test_the_old_shared_token_works_until_rotation_with_a_warning(
    box: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sa._warned.clear()
    orch = _app("orchestrator")  # the service's JSON log goes to stdout (tb_common.logging)
    r = orch.post("/x", headers={sa.TOKEN_HEADER: "old-shared-token-0123456789"})
    assert r.status_code == 200
    out = capsys.readouterr().out
    assert '"level": "WARNING"' in out and "old shared service token" in out
    assert "old-shared-token-0123456789" not in out  # the warning never carries the token
    res = sx.rotate(box, list(sx.IDENTITIES), do_restart=False, uid=None)  # every token: the migration ends
    assert not res.legacy_kept and "legacy" not in json.loads(sx.registry_path(box).read_text(encoding="utf-8"))
    assert "TB_SERVICE_TOKEN" not in (box / ".env").read_text(encoding="utf-8")
    assert orch.post("/x", headers={sa.TOKEN_HEADER: "old-shared-token-0123456789"}).status_code == 403
    assert orch.post("/x", headers=_as(monkeypatch, box, "console")).status_code == 200  # the new token


def test_without_a_registry_the_shared_token_rule_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(sa.REGISTRY_ENV, raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_SERVICE_TOKEN", "shared-0123456789")
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    c = _app("orchestrator")
    assert c.post("/x", headers={sa.TOKEN_HEADER: "shared-0123456789"}).status_code == 200
    assert c.post("/x", headers={sa.TOKEN_HEADER: "wrong"}).status_code == 403
    monkeypatch.delenv("TB_SERVICE_TOKEN")
    assert c.post("/x").status_code == 503  # unset token: PRODUCTION fails closed
    monkeypatch.delenv("TB_ENV")
    assert c.post("/x").status_code == 503  # unset TB_ENV is PRODUCTION
    monkeypatch.setenv("TB_ENV", "DEV")
    assert c.post("/x").status_code == 200


def test_an_unreadable_registry_refuses_every_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sa.REGISTRY_ENV, str(tmp_path / "missing.json"))
    monkeypatch.setenv("TB_ENV", "DEV")
    assert _app("orchestrator").post("/x", headers={sa.TOKEN_HEADER: "x"}).status_code == 503


def _runner(calls: list[tuple[list[str], str | None]]) -> Any:
    def run(argv: Sequence[str], stdin: str | None) -> None:
        calls.append((list(argv), stdin))

    return run


def test_rotate_one_service_restarts_only_it_and_never_prints_a_token(
    box: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old = {n: _tok(box, n) for n in sx.IDENTITIES}
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setenv("TB_COMPOSE", "docker compose --project-directory /opt/trialbox/deploy")
    res = sx.rotate(box, ["orchestrator"], runner=_runner(calls), uid=None)
    new = {n: _tok(box, n) for n in sx.IDENTITIES}
    assert new["orchestrator"] != old["orchestrator"] and all(new[n] == old[n] for n in old if n != "orchestrator")
    assert res.restarted == ["orchestrator"] and res.legacy_kept  # one service rotated: the old token still works
    assert calls == [(["docker", "compose", "--project-directory", "/opt/trialbox/deploy", "up", "-d", "--no-deps",
                       "--force-recreate", "--wait", "orchestrator"], None)]  # fmt: skip
    reg = json.loads(sx.registry_path(box).read_text(encoding="utf-8"))
    assert reg["services"]["orchestrator"] == sa.token_hash(new["orchestrator"])  # the old hash dropped after restart
    from tools.trialbox.__main__ import main

    main(["secrets", "status", "--deploy", str(box)])
    out = capsys.readouterr().out
    assert "orchestrator" in out and "mode=0o600" in out
    assert not any(t in out for t in new.values())
    with pytest.raises(sx.SecretsError, match="unknown service"):
        sx.rotate(box, ["nobody"], runner=_runner(calls), uid=None)


def test_a_failed_restart_keeps_both_hashes_so_nothing_is_cut_off(box: Path) -> None:
    old = _tok(box, "console")

    def boom(argv: Sequence[str], stdin: str | None) -> None:
        raise sx.SecretsError("compose failed")

    with pytest.raises(sx.SecretsError):
        sx.rotate(box, ["console"], runner=boom, uid=None)
    reg = json.loads(sx.registry_path(box).read_text(encoding="utf-8"))
    assert sa.token_hash(old) in reg["services"]["console"] and len(reg["services"]["console"]) == 2


def test_only_the_console_can_name_a_signed_in_user(box: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review 2026-11-09 S-09 (D-143): ``X-TB-Actor`` was whatever a token holder wrote. The console signs it with a
    key derived from its own token; the orchestrator verifies it with the key file ``init`` writes for it alone."""
    keys = sx.actor_keys_path(box)
    assert stat.S_IMODE(keys.stat().st_mode) == 0o600 and stat.S_IMODE(keys.parent.stat().st_mode) == 0o700
    assert _tok(box, "console") not in keys.read_text(encoding="utf-8")  # a derived key, never the token
    _as(monkeypatch, box, "console")
    signed = sa.actor_header("dr_tanaka", "sess-1")
    _as(monkeypatch, box, "mail-gateway")
    forged = sa.actor_header("dr_tanaka", "sess-1")  # the mail gateway signs with its own token
    monkeypatch.setenv(sa.ACTOR_KEYS_ENV, str(keys))
    who = sa.verify_actor(signed[sa.ACTOR_HEADER], signed[sa.ASSERTION_HEADER])
    assert who.name == "dr_tanaka" and who.session == "sess-1" and who.verified
    for bad in (forged[sa.ASSERTION_HEADER], "", "v1.1.x.y", signed[sa.ASSERTION_HEADER].replace("sess-1", "sess-2")):
        with pytest.raises(sa.ActorError):
            sa.verify_actor(signed[sa.ACTOR_HEADER], bad)
    with pytest.raises(sa.ActorError, match="expired"):  # short-lived
        sa.verify_actor(signed[sa.ACTOR_HEADER], signed[sa.ASSERTION_HEADER], now=__import__("time").time() + 600)
    with pytest.raises(sa.ActorError):  # another name under the console's assertion
        sa.verify_actor(sa.actor_header("dr_sato")[sa.ACTOR_HEADER], signed[sa.ASSERTION_HEADER])
    monkeypatch.delenv(sa.ACTOR_KEYS_ENV)  # a registry and no key file: nothing verifies (fail closed)
    with pytest.raises(sa.ActorError):
        sa.verify_actor(signed[sa.ACTOR_HEADER], signed[sa.ASSERTION_HEADER])
    # a console rotation keeps the old key valid until the console restarted, then drops it
    old = _tok(box, "console")
    calls: list[tuple[list[str], str | None]] = []
    sx.rotate(box, ["console"], runner=_runner(calls), uid=None)
    assert keys.read_text(encoding="utf-8").split() == [sx.actor_key_hex(_tok(box, "console"))]
    assert sx.actor_key_hex(old) not in keys.read_text(encoding="utf-8")
    over = yaml.safe_load((ROOT / "deploy/docker-compose.secrets.yml").read_text(encoding="utf-8"))["services"]
    mounts = {n: [v for v in svc.get("volumes", []) if "actor" in v] for n, svc in over.items()}
    assert {n for n, m in mounts.items() if m} == {"orchestrator"}  # nobody else holds the verification key
    assert over["orchestrator"]["environment"][sa.ACTOR_KEYS_ENV] == "/etc/trialbox/actor/keys"


def test_rotate_db_sends_the_passwords_on_stdin_only(box: Path) -> None:
    (box / ".env").write_text(
        "POSTGRES_PASSWORD=a\nPOSTGRES_WF_PASSWORD=b\nTB_DB_URL=postgresql://trialbox:b@db:5432/trialbox_wf\n",
        encoding="utf-8",
    )
    calls: list[tuple[list[str], str | None]] = []
    res = sx.rotate(box, ["db"], runner=_runner(calls), uid=None)
    env = dict(line.split("=", 1) for line in (box / ".env").read_text(encoding="utf-8").splitlines())
    wf, hapi = env["POSTGRES_WF_PASSWORD"], env["POSTGRES_PASSWORD"]
    assert wf not in ("b",) and hapi != "a" and env["TB_DB_URL"] == f"postgresql://trialbox:{wf}@db:5432/trialbox_wf"
    psql, restart = calls
    assert "psql" in psql[0] and psql[0][-4:] == ["-U", "hapi", "-d", "hapi"]
    assert wf in (psql[1] or "") and hapi in (psql[1] or "")
    assert not any(wf in a or hapi in a for argv, _ in calls for a in argv)  # never on a command line
    assert set(res.restarted) == set(sx.DB_USERS) and "fhir-store" in restart[0]
    assert stat.S_IMODE((box / ".env").stat().st_mode) == 0o600


def test_the_compose_overlay_gives_each_service_only_its_own_token() -> None:
    over = yaml.safe_load((ROOT / "deploy/docker-compose.secrets.yml").read_text(encoding="utf-8"))
    base = yaml.safe_load((ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))["services"]
    py = {n for n, s in base.items() if "uvicorn" in json.dumps(s.get("command", "")) and n != "llm-stub"}
    assert py == set(sx.SERVICES) == set(over["services"])
    for name, svc in over["services"].items():
        assert svc["secrets"] == [{"source": f"token_{name}", "target": "tb_service_token"}]
        assert over["secrets"][f"token_{name}"] == {"file": f"./secrets/services/{name}.token"}
        env = svc["environment"]
        assert env["TB_SERVICE_TOKEN"] == "" and env["TB_SERVICE_TOKEN_FILE"] == "/run/secrets/tb_service_token"
        assert env["POSTGRES_PASSWORD"] == "" and env["POSTGRES_WF_PASSWORD"] == ""
        assert (env.get("IMAP_PASS") == "") == (name != "mail-gateway")  # mail passwords: the mail gateway only
        assert (env.get("CLOUD_LLM_API_KEY") == "") == (name != "gateway")  # the cloud key: the gateway only
    assert over["services"]["doc-parser"]["environment"]["TB_DB_URL"] == ""


def test_the_caller_table_covers_every_call_between_services_in_the_code() -> None:
    """Scan each service for the clients it builds; every callee it reaches must accept it (else the box breaks
    the day per-service tokens are on). A new call between services fails here until CALLERS is updated."""
    uses = {
        "lake_url": "lake", "LakeHttp(": "lake", "orchestrator_url": "orchestrator", "http_job_sink": "orchestrator",
        "mail_gateway_url": "mail-gateway", "MailHttp(": "mail-gateway", "doc_parser_url": "doc-parser",
        "ParserHttp(": "doc-parser", "compiler_url": "criteria-compiler", "CompilerHttp(": "criteria-compiler",
        "adapter_url": "adapter", "AdapterHttp(": "adapter", "HttpEmbedder(": "embed-service",
        "TB_GATEWAY_URL": "gateway", "GatewayClient(": "gateway",
    }  # fmt: skip
    dirs = {"orchestrator": "orchestrator", "console": "console", "mail-gateway": "mail_gateway", "lake": "lake",
            "criteria-compiler": "criteria_compiler", "adapter": "adapter", "doc-parser": "doc_parser",
            "embed-service": "embed_service", "gateway": "gateway"}  # fmt: skip
    probes_only = {("console", "lake"), ("console", "doc-parser"), ("console", "criteria-compiler")}  # /healthz
    compose = yaml.safe_load((ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))["services"]
    missing = []
    for caller, d in dirs.items():
        text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "services" / d).rglob("*.py"))
        callees = {callee for needle, callee in uses.items() if needle in text}
        if "TB_GATEWAY_URL" in json.dumps(compose[caller].get("environment", {})):
            callees.add("gateway")  # model calls through tb_llm / tb_common.llm
        if caller == "lake":
            callees.discard("lake")  # LakeHttp is defined there
        if caller == "embed-service":
            callees.discard("embed-service")
        for callee in callees - {caller}:
            if (caller, callee) not in probes_only and not sa.allowed(callee, caller):
                missing.append(f"{caller} -> {callee}")
    assert not missing, f"add to tb_common.service_auth.CALLERS: {missing}"
    assert set(sa.CALLERS) <= set(sx.SERVICES)
    assert all(c in sx.SERVICES for callers in sa.CALLERS.values() for c in callers)


def test_install_wires_the_secrets() -> None:
    sh = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    assert "python3 -m tools.trialbox secrets init" in sh
    assert "-f deploy/docker-compose.secrets.yml" in sh and "COMPOSE_FILE=" in sh
    assert not re.search(r"for k in [^;]*TB_SERVICE_TOKEN", sh)  # no new shared token on a new box
