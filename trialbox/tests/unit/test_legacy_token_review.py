"""Card 9g-13b (D-1349): the independent review of 9g-13 (PR #1267, head 5a421d64), one test per finding. Each was
written to fail on that head before its fix. Synthetic, made-up tokens only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from tb_common import service_auth as sa
from tb_common.http import make_app

from tools.trialbox import doctor, prestart
from tools.trialbox import svc_secrets as sx
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
SHARED = "h9g13b-made-up-shared-token-0123456789"  # synthetic, made up for this test
SECRETS_OVERLAY = "docker-compose.secrets.yml"

pytestmark = pytest.mark.nodb


def _deploy(tmp: Path, env_lines: str, *, registry: bool = True, overlay: bool = True) -> Path:
    """A box's deploy folder: ``deploy/.env`` as given, ``COMPOSE_FILE`` with or without the secrets overlay, and
    (``registry``) the per-service tokens of ``secrets init`` (which keeps a ``TB_SERVICE_TOKEN`` as ``legacy``)."""
    deploy = tmp / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    files = f"{deploy}/docker-compose.yml" + (f":{deploy}/{SECRETS_OVERLAY}" if overlay else "")
    (deploy / ".env").write_text(f"COMPOSE_FILE={files}\n{env_lines}", encoding="utf-8")
    if registry:
        sx.init(deploy, uid=None)
    return deploy


def _registry_env(tmp: Path, monkeypatch: pytest.MonkeyPatch, doc: dict[str, Any]) -> None:
    (tmp / "tokens.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv(sa.REGISTRY_ENV, str(tmp / "tokens.json"))
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)


# ------------------------------------------------------------------- High: the first upgrade, an old updater


def test_the_new_trees_pre_start_refuses_a_box_that_holds_the_old_token_before_anything_else(tmp_path: Path) -> None:
    """Review High (update.py:677): the installed, older updater runs its own preflight, which has no such check.
    What every updater runs from the NEW tree is ``pre-start`` (``ComposeBox.pre_start``: ``python -m
    tools.trialbox pre-start`` in the install folder, before the stack starts). Its first step refuses."""
    assert prestart.STEPS[0][1] is prestart._legacy_token
    deploy = _deploy(tmp_path, f"TB_ENV=PRODUCTION\nTB_SERVICE_TOKEN={SHARED}\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    env["PYTHONPATH"] = os.pathsep.join(["libs", "services", "."])
    # the stand-in for an old updater: the command ComposeBox.pre_start of every release since UPDATE-PRESTART runs
    r = subprocess.run([sys.executable, "-m", "tools.trialbox", "pre-start", "--deploy", str(deploy)],
                       cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 1
    assert "pre-start: failed: old shared service token:" in r.stderr and "secrets rotate" in r.stderr
    assert SHARED not in r.stdout + r.stderr and sa.token_hash(SHARED) not in r.stdout + r.stderr


def test_the_pre_start_step_stops_before_any_other_step_and_passes_a_clean_box(tmp_path: Path) -> None:
    calls: list[str] = []

    class Box:
        def __init__(self, deploy: Path) -> None:
            self.deploy, self.env = deploy, up._env_file(deploy / ".env")

        def environment(self) -> str:
            return up.ComposeBox.environment(self)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> Any:
            calls.append(name)
            return lambda *a, **k: True

    held = _deploy(tmp_path / "held", f"TB_ENV=PRODUCTION\nTB_SERVICE_TOKEN={SHARED}\n")
    with pytest.raises(up.UpdateFailed, match="old shared service token"):
        prestart.run(held, Box(held))  # type: ignore[arg-type]
    assert calls == []  # nothing was made, pinned or started before the refusal
    clean = _deploy(tmp_path / "clean", "TB_ENV=PRODUCTION\n")
    assert prestart._legacy_token(Box(clean)).startswith("none")  # type: ignore[arg-type]
    dev = _deploy(tmp_path / "dev", f"TB_ENV=DEV\nTB_SERVICE_TOKEN={SHARED}\n")
    assert "DEV accepts" in prestart._legacy_token(Box(dev))  # type: ignore[arg-type]


# ------------------------------------------------------------- High: a named match beats the legacy hash


def test_a_hash_marked_legacy_is_legacy_even_when_a_service_has_the_same_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review High (service_auth.py:490): the same digest under ``legacy`` and ``services.operator`` identified the
    old token as ``operator``. The legacy mark is decided first; then it is refused like any legacy token."""
    h = sa.token_hash(SHARED)
    _registry_env(tmp_path, monkeypatch, {"schema": sa.REGISTRY_SCHEMA, "services": {"operator": h, "lake": "a" * 64},
                                          "legacy": h})  # fmt: skip
    reg = sa.registry()
    assert reg is not None and reg.identify(SHARED) == sa.LEGACY
    for callee in ("orchestrator", "lake", "adapter", None):
        refusal, caller = sa.authorize("POST", SHARED, "PRODUCTION", protect_reads=True, callee=callee)
        assert caller == sa.LEGACY and refusal is not None and refusal[0] == 403, callee
    # the gateway's changing calls: passed on as legacy, never as operator, to its own refusal (D-437)
    assert sa.authorize("POST", SHARED, "PRODUCTION", protect_reads=True, callee="gateway") == (None, sa.LEGACY)


# --------------------------------------------------------------- High: the shell can set the gateway's TB_ENV


INSTALLED = ("docker-compose.yml", SECRETS_OVERLAY, "docker-compose.gb10.yml", "docker-compose.rtx5090.yml",
             "docker-compose.rtxpro6000.yml")  # fmt: skip


@pytest.mark.parametrize("name", INSTALLED)
def test_no_service_of_an_installed_box_takes_tb_env_from_the_shell(name: str) -> None:
    """Review High (service_auth.py:492): ``TB_ENV: "${TB_ENV:-PRODUCTION}"`` in the gateway's environment is
    interpolated by compose from the shell that runs it, before ``deploy/.env``. Every service of the files
    ``install.sh`` composes takes ``TB_ENV`` from ``deploy/.env`` (``env_file``) only, the value it was started
    with; ``authorize`` reads it from the process (``environment_name(os.environ)``), which no caller changes."""
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert f"deploy/{name}" in install
    doc = yaml.safe_load((ROOT / "deploy" / name).read_text(encoding="utf-8"))
    for svc, body in (doc.get("services") or {}).items():
        env = (body or {}).get("environment") or {}
        if isinstance(env, list):
            env = dict(e.split("=", 1) if "=" in e else (e, None) for e in env)
        assert "TB_ENV" not in env, f"{name}: {svc} sets TB_ENV in its environment: {env.get('TB_ENV')!r}"


# ------------------------------------------------- Medium: rotation on a box without the secrets overlay


def test_rotation_is_refused_where_the_services_would_get_no_token_of_their_own(tmp_path: Path) -> None:
    """Review Medium (update.py:664): on a box composed without the secrets overlay ``secrets rotate`` dropped the
    shared token while no service mounts its own: the next recreation answered 503. Rotation is refused there,
    and doctor, the preflight and pre-start name the missing overlay."""
    deploy = _deploy(tmp_path, f"TB_ENV=PRODUCTION\nTB_SERVICE_TOKEN={SHARED}\n", overlay=False)
    with pytest.raises(sx.SecretsError, match="deploy/install.sh"):
        sx.rotate(deploy, list(sx.IDENTITIES), do_restart=False, uid=None)
    assert SHARED in (deploy / ".env").read_text(encoding="utf-8")  # nothing was changed
    assert any(SECRETS_OVERLAY in h for h in sx.legacy_held(deploy))
    check = doctor.check_legacy_token(doctor.DoctorInputs(env=dict(up._env_file(deploy / ".env")), deploy=deploy))
    assert check.status == "FAIL" and SECRETS_OVERLAY in check.detail and "deploy/install.sh" in check.detail


# ------------------------------------------------------- Medium: the first run's answers add a token back


def test_the_first_runs_answers_add_no_shared_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Medium (install.sh:408): ``box-install.sh --firstrun`` applies the owner's answers through the
    settings wizard (``tools.box apply``), whose environment carries a random ``TB_SERVICE_TOKEN``; it was merged
    into ``deploy/.env`` after ``install.sh`` had dropped the wizard's first one."""
    import shutil

    from tools.box import __main__ as bm

    from tests.unit.test_wizard_chartno_rule import REHEARSAL, _answers

    deploy = _deploy(tmp_path, "TB_ENV=PRODUCTION\nTB_SITE_ID=T\n")
    shutil.copytree(REHEARSAL / "mapping", deploy / "site" / "mapping")
    monkeypatch.setattr(bm.firstrun, "read", lambda _p: {})
    monkeypatch.setattr(bm, "parse", lambda raw, disks: (object(), []))
    monkeypatch.setattr(bm, "plan", lambda a, hw, d: SimpleNamespace(wizard_answers=_answers(), warnings=[]))
    monkeypatch.setattr(bm, "write", lambda *a: None)
    monkeypatch.setattr(bm, "chartno_change", lambda *a: None)
    bm.apply(tmp_path, SimpleNamespace(disks=()), deploy)  # type: ignore[arg-type]
    text = (deploy / ".env").read_text(encoding="utf-8")
    assert "TB_SITE_ID=" in text and "TB_SERVICE_TOKEN" not in text
    assert sx.legacy_held(deploy) == []


# ------------------------------------------------------------- Medium: a file-backed shared token


def test_a_file_backed_shared_token_is_held_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Medium (svc_secrets.py:329): ``TB_SERVICE_TOKEN_FILE`` in ``deploy/.env`` with no registry is the
    box's one token (``service_token`` reads it first; ``authorize`` calls it legacy), so it is held."""
    deploy = _deploy(tmp_path, "TB_SERVICE_TOKEN_FILE=/run/secrets/shared.token\n", registry=False, overlay=False)
    assert any("TB_SERVICE_TOKEN_FILE" in h for h in sx.legacy_held(deploy))
    check = doctor.check_legacy_token(doctor.DoctorInputs(env=dict(up._env_file(deploy / ".env")), deploy=deploy))
    assert check.status == "FAIL" and check.detail.startswith("PRODUCTION:")  # TB_ENV unset is PRODUCTION
    with pytest.raises(up.UpdateRefused, match="old shared service token"):
        up.Updater(up.ComposeBox(deploy), deploy / "updates")._legacy_token()
    # the runtime agrees: one file-backed token, no registry, TB_ENV unset
    token_file = tmp_path / "shared.token"
    token_file.write_text(SHARED + "\n", encoding="utf-8")
    monkeypatch.delenv(sa.REGISTRY_ENV, raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("TB_SERVICE_TOKEN_FILE", str(token_file))
    assert sa.authorize("POST", SHARED, "PRODUCTION", callee="adapter")[1] == sa.LEGACY


# --------------------------------------------------------------- Medium: doctor --env-file reads that file


def test_doctor_reads_the_env_file_it_was_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Medium (doctor.py:472): with ``--env-file /site/validation.env`` doctor read ``/site/.env``."""
    for k in ("TB_SERVICE_TOKEN", "TB_SERVICE_TOKEN_FILE", "TB_SERVICE_TOKENS", "TB_ENV"):
        monkeypatch.delenv(k, raising=False)
    site = tmp_path / "site"
    site.mkdir()
    chosen = site / "validation.env"
    chosen.write_text(f"TB_ENV=VALIDATION\nTB_SERVICE_TOKEN={SHARED}\n", encoding="utf-8")
    inp = doctor.inputs_from(env_file=chosen, settings=None, routing=None, lake=None)
    check = doctor.check_legacy_token(inp)
    assert check.status == "FAIL" and check.detail.startswith("VALIDATION:") and str(chosen) in check.detail
    assert SHARED not in check.detail


# ------------------------------------------------------------- Medium: a quoted TB_ENV in deploy/.env


@pytest.mark.parametrize("quoted", ['"TEST"', "'TEST'", ' "test" '])
def test_a_quoted_tb_env_is_read_as_compose_reads_it(tmp_path: Path, quoted: str) -> None:
    """Review Medium (update.py:656): compose reads ``TB_ENV="TEST"`` as TEST; the updater kept the quotes, took the
    name for unknown and so for PRODUCTION, and refused a TEST box's update."""
    deploy = _deploy(tmp_path, f"TB_ENV={quoted}\nTB_SERVICE_TOKEN={SHARED}\n")
    box = up.ComposeBox(deploy)
    assert box.environment() == "TEST"
    assert up.Updater(box, deploy / "updates")._legacy_token() == []
    assert "TEST accepts" in prestart._legacy_token(box)


# ------------------------------------------------------------ Low: the callee can read the registry


def test_every_service_of_an_installed_box_can_read_the_registry_it_needs() -> None:
    """Review Low (test_legacy_token_refused.py:151): each callee needs the registry (``TB_SERVICE_TOKENS`` and its
    mount) to know who called; without it the nightly call is answered 503."""
    overlay = yaml.safe_load((ROOT / "deploy" / SECRETS_OVERLAY).read_text(encoding="utf-8"))
    path = overlay["x-tokens"]["TB_SERVICE_TOKENS"]
    assert path == "/etc/trialbox/service-tokens/tokens.json"
    for name in sx.SERVICES:
        svc = overlay["services"][name]
        assert svc["environment"]["TB_SERVICE_TOKENS"] == path, name
        mounts = [str(v).split(":") for v in svc.get("volumes") or []]
        assert ["./secrets/services/public", "/etc/trialbox/service-tokens", "ro"] in mounts, name
    assert sx.registry_path(Path("deploy")) == Path("deploy/secrets/services/public/tokens.json")


# --------------------------------------------------------- the orchestrator keeps its audited refusal


def test_a_route_gate_can_only_replace_a_legacy_refusal_with_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the name exemptions gone, ``make_app`` hands a legacy refusal to the service's route gate (the
    orchestrator's audits it, D-464). A gate that answers None leaves the token layer's refusal: never a pass."""
    _registry_env(tmp_path, monkeypatch, {"schema": sa.REGISTRY_SCHEMA, "services": {"console": "c" * 64},
                                          "legacy": sa.token_hash(SHARED)})  # fmt: skip
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    seen: list[Any] = []

    def admits(request: Any, caller: str | None) -> None:
        seen.append((caller, getattr(request.state, "tb_caller", None)))
        return None

    app = make_app("adapter", protect_reads=True, route_gate=admits)

    @app.post("/x")
    def x() -> dict[str, str]:
        return {"ok": "yes"}

    r = TestClient(app).post("/x", headers={sa.TOKEN_HEADER: SHARED})
    assert r.status_code == 403 and "(D-1349)" in r.json()["detail"]
    assert seen == [(sa.LEGACY, sa.LEGACY)]
