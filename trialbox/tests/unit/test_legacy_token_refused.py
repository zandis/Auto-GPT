"""Card 9g-13 (D-1349): outside DEV and TEST the old shared service token is refused, as D-447 refuses the v1 actor
form. The token layer refuses it with 403 and one warning in the log, never the token; the orchestrator and the
gateway refuse it themselves with an audit event (D-464, D-437). A box installed by this release holds no such token;
one that still does is told by ``doctor`` (``legacy_token``) and refused by the update's preflight."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from tb_common import service_auth as sa
from tb_common.http import make_app

from tools.trialbox import doctor
from tools.trialbox import svc_secrets as sx
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
SHARED = "h9g13-made-up-shared-token-0123456789"  # synthetic, made up for this test
REFUSED = "refused outside DEV and TEST (D-1349)"
STRICT = ("VALIDATION", "PRODUCTION", "")  # "" is an unset TB_ENV: PRODUCTION by the one rule (D-127)

pytestmark = pytest.mark.nodb


def _app(name: str) -> TestClient:
    app = make_app(name, protect_reads=True)

    @app.post("/x")
    def x() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/r")
    def r() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def _env(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)


def _registry_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A box installed before step 8 and then given its per-service tokens by ``secrets init``: the shared token is
    kept in ``tokens.json`` as ``legacy``."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_SITE_ID=T\nTB_SERVICE_TOKEN={SHARED}\n", encoding="utf-8")
    sx.init(deploy, uid=None)
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv(sa.REGISTRY_ENV, str(sx.registry_path(deploy)))
    return deploy


def _no_registry_box(monkeypatch: pytest.MonkeyPatch) -> None:
    """A box before step 8: one shared token, no registry."""
    monkeypatch.delenv(sa.REGISTRY_ENV, raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_SERVICE_TOKEN", SHARED)


@pytest.mark.parametrize("mode", ["registry", "shared"])
@pytest.mark.parametrize("env", STRICT)
def test_the_old_token_is_refused_outside_dev_and_test_with_one_warning_and_no_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: str, mode: str
) -> None:
    deploy = _registry_box(tmp_path, monkeypatch) if mode == "registry" else None
    if mode == "shared":
        _no_registry_box(monkeypatch)
    _env(monkeypatch, env)
    sa._warned.clear()
    capsys.readouterr()
    lake = _app("lake")
    for _ in range(2):
        r = lake.post("/x", headers={sa.TOKEN_HEADER: SHARED})
        assert r.status_code == 403 and REFUSED in r.json()["detail"], (env, mode)
        assert lake.get("/r", headers={sa.TOKEN_HEADER: SHARED}).status_code == 403  # reads too (protect_reads)
    out = capsys.readouterr().out
    assert out.count("old shared service token and was refused (D-1349)") == 1  # once per process
    assert "secrets rotate" in out
    assert SHARED not in out and SHARED not in r.text  # never the token, in the log or in the answer
    if deploy is not None:  # the per-service tokens are untouched: the console's own token reaches the adapter
        monkeypatch.setenv("TB_SERVICE_TOKEN_FILE", str(sx.token_path(deploy, "console")))
        assert _app("adapter").post("/x", headers=sa.auth_headers()).status_code == 200


@pytest.mark.parametrize("mode", ["registry", "shared"])
@pytest.mark.parametrize("env", ["DEV", "TEST"])
def test_dev_and_test_keep_todays_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str, mode: str) -> None:
    if mode == "registry":
        _registry_box(tmp_path, monkeypatch)
    else:
        _no_registry_box(monkeypatch)
    monkeypatch.setenv("TB_ENV", env)
    assert _app("lake").post("/x", headers={sa.TOKEN_HEADER: SHARED}).status_code == 200
    assert sa.authorize("POST", SHARED, env, callee="lake") == (None, sa.LEGACY)


@pytest.mark.parametrize("env", STRICT)
def test_every_callee_refuses_it_but_the_two_that_refuse_and_audit_it_themselves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """The orchestrator's route gate refuses it on every route (D-464) and the gateway on every call that reaches a
    model or swaps one (D-437), each with an audit event: there the token layer passes it on to that refusal. The
    gateway's reads (models, serving status, registry) are refused here."""
    _registry_box(tmp_path, monkeypatch)
    want = env or "PRODUCTION"
    for callee in (*sorted(sa.CALLERS), None):
        refusal, caller = sa.authorize("POST", SHARED, want, protect_reads=True, callee=callee)
        assert caller == sa.LEGACY
        if callee in ("orchestrator", "gateway"):
            assert refusal is None, callee
        else:
            assert refusal == (403, f"the old shared {sa.TOKEN_HEADER} is {REFUSED}"), callee
    assert sa.authorize("GET", SHARED, want, protect_reads=True, callee="orchestrator")[0] is None
    assert sa.authorize("GET", SHARED, want, protect_reads=True, callee="gateway")[0] is not None


def test_the_orchestrator_still_refuses_and_audits_it_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import app as oapp

    _registry_box(tmp_path, monkeypatch)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    r = TestClient(oapp.app).get("/jobs", headers={sa.TOKEN_HEADER: SHARED})
    assert r.status_code == 403 and r.headers["X-TB-Refusal"] == "caller_unverified"


# ------------------------------------------------------------------------------- what a box presents and holds


def test_every_service_of_an_installed_box_presents_its_own_token() -> None:
    """install.sh starts every box with the secrets overlay; there every TrialBox service has its own token file
    and the shared ``TB_SERVICE_TOKEN`` cleared, and ``service_token`` reads the file first."""
    assert "-f deploy/docker-compose.yml -f deploy/docker-compose.secrets.yml)" in INSTALL
    assert 'FILES="$ROOT/deploy/docker-compose.yml:$ROOT/deploy/docker-compose.secrets.yml"' in INSTALL
    overlay = yaml.safe_load((ROOT / "deploy" / "docker-compose.secrets.yml").read_text(encoding="utf-8"))
    for name in sx.SERVICES:
        svc = overlay["services"][name]
        assert svc["environment"]["TB_SERVICE_TOKEN"] == "", name
        assert svc["environment"]["TB_SERVICE_TOKEN_FILE"] == "/run/secrets/tb_service_token", name
        assert {"source": f"token_{name}", "target": "tb_service_token"} in svc["secrets"], name
        assert overlay["secrets"][f"token_{name}"] == {"file": f"./secrets/services/{name}.token"}, name


def test_the_service_file_wins_over_a_shared_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    own = tmp_path / "own.token"
    own.write_text("h9g13-made-up-own-token\n", encoding="utf-8")
    monkeypatch.setenv("TB_SERVICE_TOKEN", SHARED)
    monkeypatch.setenv("TB_SERVICE_TOKEN_FILE", str(own))
    assert sa.auth_headers() == {sa.TOKEN_HEADER: "h9g13-made-up-own-token"}


def _service_tokens_block() -> str:
    start = INSTALL.index("# SERVICE TOKENS (D-128, D-138, D-1349)")
    return INSTALL[start : INSTALL.index("# ---- end of SERVICE TOKENS", start)]


def _old_token_line() -> str:
    (line,) = [ln for ln in INSTALL.splitlines() if ln.startswith("if [ -f deploy/.env ] && grep -q '^TB_SERVICE_TOK")]
    return line


def _install(tmp: Path, before: str | None, wizard: str) -> subprocess.CompletedProcess[str]:
    """The installer's lines as they stand: deploy/.env as it was ``before`` the install (None: none), then as the
    settings wizard wrote it (``wizard``), then the SERVICE TOKENS block with the real ``secrets init``."""
    deploy = tmp / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    if before is not None:
        (deploy / ".env").write_text(before, encoding="utf-8")
    pypath = os.pathsep.join([str(ROOT), str(ROOT / "libs")])
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\n'
        f'python3() {{ PYTHONPATH="{pypath}" command "{sys.executable}" "$@"; }}\n'
        "HAD_SHARED=unset\n"
        f"{_old_token_line()}\n"
        f"cat > deploy/.env <<'EOF'\n{wizard}EOF\n"
        f"{_service_tokens_block()}\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, env=env)


WIZARD = f"TB_SITE_ID=T\nTB_SERVICE_TOKEN={'w' * 32}\n"  # the settings wizard writes a random token of its own


@pytest.mark.parametrize(
    "before",
    [None, "TB_ENV=PRODUCTION\n", "TB_ENV=VALIDATION\n", "TB_SERVICE_TOKEN=change-me-service-token\n"],
    ids=["fresh", "env-written-first-production", "env-written-first-validation", "placeholder"],
)
def test_a_box_installed_by_this_release_holds_no_old_token(tmp_path: Path, before: str | None) -> None:
    """D-837 lets an operator write TB_ENV into deploy/.env before the install; the wizard then rewrites the file
    with a token of its own, which was kept as ``legacy`` before D-1349 (a box that existed only as that file)."""
    r = _install(tmp_path, before, WIZARD)
    assert r.returncode == 0, r.stderr
    deploy = tmp_path / "deploy"
    assert "TB_SERVICE_TOKEN" not in (deploy / ".env").read_text(encoding="utf-8")
    assert sx.legacy_held(deploy) == []
    assert "legacy" not in sx.registry_path(deploy).read_text(encoding="utf-8")
    assert {p.stem for p in sx.secrets_dir(deploy).glob("*.token")} == set(sx.IDENTITIES)
    inp = doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=deploy)
    assert doctor.check_legacy_token(inp).status == "PASS"
    assert _updater(deploy, "PRODUCTION")._legacy_token() == []


def test_a_box_installed_before_step_8_keeps_its_token_until_rotation_and_is_told(tmp_path: Path) -> None:
    old = f"TB_SITE_ID=T\nTB_SERVICE_TOKEN={SHARED}\n"
    r = _install(tmp_path, old, old)
    assert r.returncode == 0, r.stderr
    assert SHARED not in r.stdout + r.stderr  # init never prints the token
    deploy = tmp_path / "deploy"
    held = sx.legacy_held(deploy)
    assert held == [f"TB_SERVICE_TOKEN in {deploy / '.env'}", f"the legacy hash in {sx.registry_path(deploy)}"]
    assert not any(SHARED in h for h in held)
    check = doctor.check_legacy_token(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=deploy))
    assert check.status == "FAIL"
    sx.rotate(deploy, list(sx.IDENTITIES), do_restart=False, uid=None)  # the fix doctor names
    assert sx.legacy_held(deploy) == []
    assert doctor.check_legacy_token(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=deploy)).status == "PASS"


# ------------------------------------------------------------------------------------------------------- doctor


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION", ""])
def test_doctor_fails_outside_dev_and_test_with_a_plain_line_and_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    deploy = _registry_box(tmp_path, monkeypatch)
    check = doctor.check_legacy_token(doctor.DoctorInputs(env={"TB_ENV": env} if env else {}, deploy=deploy))
    assert check.name == "legacy_token" and check.status == "FAIL"
    assert check.detail.startswith(f"{env or 'PRODUCTION'}: the box still holds the old shared service token (")
    assert "Fix: sudo python3 -m tools.trialbox secrets rotate" in check.detail
    assert SHARED not in check.detail and sa.token_hash(SHARED) not in check.detail
    assert doctor.check_legacy_token in doctor.CHECKS
    (line,) = [
        c for c in doctor.run(doctor.DoctorInputs(env={"TB_ENV": env}, deploy=deploy)) if c.name == "legacy_token"
    ]
    assert line.status == "FAIL"


@pytest.mark.parametrize("env", ["DEV", "TEST"])
def test_doctor_passes_dev_and_test_with_a_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    deploy = _registry_box(tmp_path, monkeypatch)
    check = doctor.check_legacy_token(doctor.DoctorInputs(env={"TB_ENV": env}, deploy=deploy))
    assert check.status == "PASS" and f"{env} accepts the old shared service token" in check.detail


def test_doctor_without_a_deploy_folder_reads_the_settings_it_was_given() -> None:
    tok = {"TB_ENV": "PRODUCTION", "TB_SERVICE_TOKEN": SHARED}
    check = doctor.check_legacy_token(doctor.DoctorInputs(env=tok))
    assert check.status == "FAIL" and SHARED not in check.detail
    for clean in ({"TB_ENV": "PRODUCTION"}, {"TB_ENV": "PRODUCTION", "TB_SERVICE_TOKEN": "change-me-service-token"}):
        assert doctor.check_legacy_token(doctor.DoctorInputs(env=clean)).status == "PASS"


# ----------------------------------------------------------------------------------------------- the update


class _Box:
    name = "compose"

    def __init__(self, deploy: Path, env: str) -> None:
        self.deploy, self._env = deploy, env
        self.env: dict[str, str] = {}

    def environment(self) -> str:
        return self._env


def _updater(deploy: Path, env: str) -> up.Updater:
    return up.Updater(_Box(deploy, env), deploy / "updates", say=lambda _m: None)  # type: ignore[arg-type]


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION", "nonsense"])
def test_the_update_preflight_refuses_a_box_that_still_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    from tests.unit.test_update_safety import _plan

    deploy = _registry_box(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in deploy.rglob("*") if p.is_file()}
    with pytest.raises(up.UpdateRefused, match=r"secrets rotate.*nothing was changed") as exc:
        _updater(deploy, env).preflight(_plan(tmp_path, seq=None), backup=False)
    assert SHARED not in str(exc.value) and sa.token_hash(SHARED) not in str(exc.value)
    assert {p: p.read_bytes() for p in deploy.rglob("*") if p.is_file()} == before
    sx.rotate(deploy, list(sx.IDENTITIES), do_restart=False, uid=None)
    assert _updater(deploy, env)._legacy_token() == []


@pytest.mark.parametrize("env", ["DEV", "TEST"])
def test_the_update_preflight_leaves_dev_and_test_as_they_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    deploy = _registry_box(tmp_path, monkeypatch)
    assert _updater(deploy, env)._legacy_token() == []
    other: Any = type("Other", (), {"name": "k8s", "deploy": deploy, "environment": lambda self: "PRODUCTION"})()
    assert up.Updater(other, deploy / "updates")._legacy_token() == []  # a compose box's files only
