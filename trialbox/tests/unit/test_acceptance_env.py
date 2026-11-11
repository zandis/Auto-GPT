"""T-213a (D-410; CR-071, OPS-051): the acceptance environment. Its overlay composes with the identity overlay (the
rendered config, by ``docker compose config``; skipped without the compose plugin), ``prepare`` writes what the
overlay mounts (certificates that verify, an Authelia configuration with no SITE value left, the seed, 0600 secrets
never printed), and the plan and the dry runs run nothing. The start itself is on the acceptance box."""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12

from tools import acceptance_env as ae
from tools import images_lock as il

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> ae.Prepared:
    return ae.prepare(tmp_path_factory.mktemp("acc") / "acceptance")


def _env(d: Path) -> dict[str, str]:
    out = {}
    for ln in (d / ae.MARKER).read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1)
            out[k] = v
    return out


# --------------------------------------------------------------------------------------------------- plan, dry run
def test_the_stack_adds_the_overlay_after_the_identity_overlay() -> None:
    assert ae.Stack().files() == ["docker-compose.yml", "docker-compose.secrets.yml", "docker-compose.identity.yml",
                                  "docker-compose.acceptance.yml"]  # fmt: skip
    gpu = ae.Stack(gpu="rtxpro6000")
    assert gpu.files()[2] == "docker-compose.rtxpro6000.yml" and gpu.files()[-2:] == ae.Stack().files()[-2:]
    assert gpu.profiles() == ["gpu", "oidc"] and ae.Stack().profiles() == ["stub", "oidc"]
    for f in [*gpu.files(), *ae.Stack(gpu="shared-quota").files()]:
        assert (DEPLOY / f).is_file(), f
    argv = ae.Stack(dir=Path("/x/acc")).compose("up", "-d", "--wait")
    assert argv[:4] == ["docker", "compose", "--project-directory", str(DEPLOY)]
    assert argv[argv.index("--env-file", 5) + 1] == "/x/acc/acceptance.env"  # after deploy/.env: it wins
    assert argv[-3:] == ["up", "-d", "--wait"]


def test_plan_lists_every_step_and_runs_nothing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
                                                ) -> None:  # fmt: skip
    monkeypatch.setattr(subprocess, "run", _no_run)
    assert ae.main(["plan", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    commands = " | ".join(s["command"] for s in doc["steps"])
    for want in ("secrets init", "acceptance_env prepare", "/etc/hosts", "up -d --wait", "acceptance_env check",
                 "acceptance_env down", ae.OVERLAY, "docker-compose.identity.yml", "--profile oidc"):  # fmt: skip
        assert want in commands, want
    assert doc["profiles"] == ["stub", "oidc"]


def _no_run(*a: Any, **k: Any) -> Any:
    raise AssertionError(f"a dry run ran {a}")


@pytest.mark.parametrize("cmd", ["up", "check", "down"])
def test_a_dry_run_prints_the_commands_and_runs_nothing(
    cmd: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(subprocess, "run", _no_run)
    assert ae.main([cmd, "--dir", str(tmp_path), "--gpu", "rtxpro6000", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "docker compose" in out and "docker-compose.identity.yml" in out and ae.OVERLAY in out
    assert "docker-compose.rtxpro6000.yml" in out and "--profile gpu" in out


def test_up_refuses_an_unprepared_folder_before_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    monkeypatch.setattr(subprocess, "run", _no_run)
    assert ae.main(["up", "--dir", str(tmp_path / "none")]) == 2
    assert "is not prepared" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------------- prepare
def test_prepare_writes_what_the_overlay_mounts(prepared: ae.Prepared) -> None:
    d = prepared.dir
    for rel in ("ca/ca.crt", "tls/site.crt", "tls/site.key", "authelia/configuration.yml",
                "authelia/secrets/jwt_secret", "authelia/secrets/session_secret", "authelia/secrets/storage_key",
                "authelia/secrets/oidc_hmac", "authelia/secrets/ldap_password", "authelia/secrets/oidc_jwks.pem",
                "console/oidc_client_secret.txt", "directory/lldap_config.toml", "directory/admin_password",
                "directory/tls/directory.crt", "directory/tls/directory.key", "mail/mail.p12", "accounts.txt",
                ae.MARKER):  # fmt: skip
        assert (d / rel).is_file(), rel
    assert sorted(p.name for p in (d / "ca").iterdir()) == ["ca.crt"]  # the CA key is never kept
    env = _env(d)
    assert env["TB_TLS_MODE"] == "hospital" and env["TB_TLS_HOSTNAME"] == ae.CONSOLE_HOST
    assert env["TB_OIDC_ENABLED"] == "1" and env["TB_OIDC_ISSUER"] == f"https://{ae.AUTH_HOST}"
    assert env["TB_TLS_BIND"] == "127.0.0.1"
    for k in ("TB_TLS_CERT_FILE", "TB_TLS_KEY_FILE", "TB_AUTHELIA_CONFIG", "TB_OIDC_CLIENT_SECRET", "TB_OIDC_CA",
              "TB_EXTRA_CA"):  # fmt: skip
        assert Path(env[k]).is_file() and Path(env[k]).is_absolute(), k


def test_every_secret_is_0600_and_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ae.main(["prepare", "--dir", str(tmp_path / "a")]) == 0
    out = capsys.readouterr()
    d = tmp_path / "a"
    private = [d / "tls/site.key", d / "console/oidc_client_secret.txt", d / ae.MARKER, d / "directory/admin_password",
               d / "directory/lldap_config.toml", d / "directory/tls/directory.key", d / "authelia/configuration.yml",
               *(d / "authelia/secrets").iterdir(), *(d / "directory/passwords").iterdir()]  # fmt: skip
    for p in private:
        assert p.stat().st_mode & 0o777 == 0o600, p
    for name, value in _env(d).items():
        if "PASSWORD" in name:
            assert len(value) == 64 and value not in out.out + out.err
    for p in [*(d / "authelia/secrets").iterdir(), *(d / "directory/passwords").iterdir()]:
        assert p.read_text(encoding="utf-8").strip()[:40] not in out.out + out.err


def test_prepare_refuses_a_full_folder_and_removes_only_its_own(tmp_path: Path) -> None:
    d = tmp_path / "acc"
    ae.prepare(d)
    with pytest.raises(ae.AcceptanceError, match="--force"):
        ae.prepare(d)
    before = (d / "console/oidc_client_secret.txt").read_text(encoding="utf-8")
    ae.prepare(d, force=True)
    assert (d / "console/oidc_client_secret.txt").read_text(encoding="utf-8") != before  # every secret is new
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ae.AcceptanceError, match="not made by this tool"):
        ae.prepare(other, force=True)
    assert (other / "keep.txt").is_file()


def _chain_ok(leaf: Path, ca: Path) -> x509.Certificate:
    certs = x509.load_pem_x509_certificates(leaf.read_bytes())
    root = x509.load_pem_x509_certificate(ca.read_bytes())
    certs[0].verify_directly_issued_by(root)
    return certs[0]


def test_the_certificates_name_the_hosts_and_chain_to_the_test_ca(prepared: ae.Prepared) -> None:
    d = prepared.dir
    names = {
        "tls/site.crt": {ae.CONSOLE_HOST, ae.AUTH_HOST},  # Caddy (hospital mode): the console and Authelia
        "directory/tls/directory.crt": {ae.DIRECTORY_HOST},  # Authelia's tls.server_name
    }
    for rel, want in names.items():
        cert = _chain_ok(d / rel, d / "ca/ca.crt")
        alt = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert want <= set(alt.get_values_for_type(x509.DNSName)), rel
    password = _env(d)["TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD"].encode()
    mail_key, mail_cert, _ = pkcs12.load_key_and_certificates((d / "mail/mail.p12").read_bytes(), password)
    assert mail_key is not None and mail_cert is not None
    mail_cert.verify_directly_issued_by(x509.load_pem_x509_certificate((d / "ca/ca.crt").read_bytes()))
    alt = mail_cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ae.MAIL_HOST in alt.get_values_for_type(x509.DNSName)


def test_the_authelia_configuration_is_the_site_template_with_acceptance_values(prepared: ae.Prepared) -> None:
    text = (prepared.dir / "authelia/configuration.yml").read_text(encoding="utf-8")
    assert "hospital.example" not in text and "SITE-REPLACE" not in text
    # the template's one Go-template line (the JWKS key from a file) stays for Authelia; the rest is plain YAML
    doc = yaml.safe_load("\n".join("" if "{{" in ln else ln for ln in text.splitlines()))
    ldap = doc["authentication_backend"]["ldap"]
    assert ldap["implementation"] == "lldap" and ldap["address"] == f"ldaps://{ae.DIRECTORY_HOST}:6360"
    assert ldap["tls"] == {"server_name": ae.DIRECTORY_HOST, "minimum_version": "TLS1.2", "skip_verify": False}
    assert ldap["user"] == "UID=svc-trialbox,OU=people,DC=acceptance,DC=test"
    assert doc["certificates_directory"] == "/config/certificates"
    assert doc["session"]["cookies"][0]["domain"] == ae.AUTH_HOST
    client = doc["identity_providers"]["oidc"]["clients"][0]
    assert client["redirect_uris"] == [f"https://{ae.CONSOLE_HOST}/auth/oidc/callback"]
    secret = (prepared.dir / "console/oidc_client_secret.txt").read_text(encoding="utf-8")
    assert ae.verify_client_secret(secret, client["client_secret"])
    assert not ae.verify_client_secret(secret + "x", client["client_secret"])
    assert doc["access_control"]["default_policy"] == "two_factor"  # unchanged from the template


def test_a_moved_template_line_is_refused() -> None:
    template = ae.AUTHELIA_TEMPLATE.read_text(encoding="utf-8")
    with pytest.raises(ae.AcceptanceError, match="occurs 0 times"):
        ae.render_authelia(template.replace("implementation: activedirectory", "implementation: custom"), "$d")
    with pytest.raises(ae.AcceptanceError, match="SITE value is left"):
        ae.render_authelia(template + "\n# dc02.hospital.example\n", "$d")


def test_the_digest_has_authelias_form() -> None:
    d = ae.client_secret_digest("secret", salt=b"\xfb" * 16, rounds=1000)
    _, scheme, rounds, salt, key = d.split("$")
    assert (scheme, rounds) == ("pbkdf2-sha512", "1000")
    assert "+" not in salt + key and "=" not in salt + key and len(key) == 86  # 64 bytes, adapted base64
    assert ae.verify_client_secret("secret", d) and not ae.verify_client_secret("Secret", d)


def test_the_seed_gives_one_account_per_role_and_two_refusals(prepared: ae.Prepared) -> None:
    d = prepared.dir
    users = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (d / "directory/users").glob("*.json")}
    groups = {json.loads(p.read_text(encoding="utf-8"))["name"] for p in (d / "directory/groups").glob("*.json")}
    roles = dict(x.split(":") for x in _env(d)["TB_OIDC_GROUP_ROLES"].split(","))
    assert set(roles) == groups and set(roles.values()) == {"admin", "coordinator", "investigator", "cro", "viewer"}
    for a in ae.ACCOUNTS:
        mapped = {roles[g] for g in users[a.uid]["groups"]}
        assert (mapped == {a.expect}) if a.expect != "refused" else len(mapped) != 1, a
        assert users[a.uid]["email"].endswith("@acceptance.test")
        assert (d / "directory/passwords" / a.uid).is_file()
    bind = users[ae.BIND_ACCOUNT]
    assert bind["groups"] == ["lldap_strict_readonly"]  # read-only bind account
    assert (d / "directory/passwords" / ae.BIND_ACCOUNT).read_text(encoding="utf-8") == (
        d / "authelia/secrets/ldap_password").read_text(encoding="utf-8")  # fmt: skip
    toml = (d / "directory/lldap_config.toml").read_text(encoding="utf-8")
    assert 'ldap_base_dn = "dc=acceptance,dc=test"' in toml and "enabled = true" in toml
    assert "RanD0m" not in toml  # the image template's fixed key seed is never used
    assert "acc-norole" in (d / "accounts.txt").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------ check
def test_evaluate_ps_wants_healthy_services_and_one_shots_exited_0() -> None:
    config = {"services": {"db": {"restart": "unless-stopped"}, "authelia": {"restart": "unless-stopped"},
                           "acceptance-directory-seed": {"restart": "no"}, "caddy": {}}}  # fmt: skip
    rows: list[dict[str, Any]] = [
        {"Service": "db", "State": "running", "Health": "healthy"},
        {"Service": "authelia", "State": "running", "Health": "healthy"},
        {"Service": "acceptance-directory-seed", "State": "exited", "Health": "", "ExitCode": 0},
        {"Service": "caddy", "State": "running", "Health": ""},
    ]
    assert ae.evaluate_ps(config, rows)[1] == []
    rows[1]["Health"] = "unhealthy"
    rows[2]["ExitCode"] = 1
    problems = ae.evaluate_ps(config, rows[:3])[1]
    assert problems == ["acceptance-directory-seed: one-shot exited, exit code 1", "authelia: running, health unhealthy",
                        "caddy: no container"]  # fmt: skip
    assert ae._rows('[{"Service": "db"}]') == ae._rows('{"Service": "db"}\n') == [{"Service": "db"}]


@pytest.fixture
def edge(prepared: ae.Prepared) -> Iterator[int]:
    """A stand-in for Caddy: TLS with the site certificate, Authelia's discovery document on the auth host."""

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            host = self.headers.get("Host", "").split(":")[0]
            body = json.dumps({"issuer": f"https://{host}"}).encode() if "openid" in self.path else b"<html></html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: Any) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(prepared.dir / "tls/site.crt", prepared.dir / "tls/site.key")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_the_probes_verify_the_site_certificate_against_the_test_ca(prepared: ae.Prepared, edge: int,
                                                                    tmp_path: Path) -> None:  # fmt: skip
    answers, problems = ae.probes("127.0.0.1", edge, prepared.dir / "ca/ca.crt")
    assert problems == [], answers
    assert answers["oidc"] == f"HTTP 200, issuer https://{ae.AUTH_HOST}"
    _, other = ae.make_ca()
    (tmp_path / "other.crt").write_bytes(ae._pem(other))
    _, problems = ae.probes("127.0.0.1", edge, tmp_path / "other.crt")
    assert len(problems) == 2 and all("CERTIFICATE_VERIFY_FAILED" in p for p in problems)


# ---------------------------------------------------------------------------------------------- the rendered overlay
def _compose() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
def test_the_overlay_composes_with_the_identity_overlay(prepared: ae.Prepared, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TB_TZ=Asia/Taipei\nPOSTGRES_PASSWORD=x\n", encoding="utf-8")
    stack = ae.Stack(dir=prepared.dir, deploy=DEPLOY)
    argv = stack.compose("config", "--format", "json")
    argv[argv.index("--env-file") + 1] = str(tmp_path / ".env")  # a box's deploy/.env, here a dummy one
    argv[argv.index("--project-directory") + 1] = str(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "COMPOSE_")) and not k.endswith("_IMAGE")}
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False, env=env)
    assert r.returncode == 0, r.stderr
    svcs = json.loads(r.stdout)["services"]
    d = str(prepared.dir)
    assert {"acceptance-directory", "acceptance-directory-seed", "acceptance-mail", "authelia", "caddy"} <= set(svcs)
    # only Caddy publishes, only 443, on the address prepare chose
    published = {n: [(p["host_ip"], p["published"]) for p in s.get("ports") or []] for n, s in svcs.items()}
    assert {n: p for n, p in published.items() if p} == {"caddy": [("127.0.0.1", "443")]}
    # Authelia reads the acceptance configuration, secrets and CA (the identity overlay's mounts are replaced)
    mounts = {v["target"]: v.get("source") for v in svcs["authelia"]["volumes"]}
    assert mounts["/config/configuration.yml"] == f"{d}/authelia/configuration.yml"
    assert mounts["/run/authelia"] == f"{d}/authelia/secrets"
    assert mounts["/config/certificates"] == f"{d}/ca"
    assert svcs["authelia"]["depends_on"]["acceptance-directory-seed"]["condition"] == "service_completed_successfully"
    caddy = {v["target"]: v.get("source") for v in svcs["caddy"]["volumes"]}
    assert caddy["/etc/caddy/certs/site.crt"] == f"{d}/tls/site.crt"
    assert svcs["caddy"]["environment"]["TB_TLS_MODE"] == "hospital"
    console = svcs["console"]["environment"]
    assert console["TB_OIDC_ENABLED"] == "1" and console["TB_OIDC_ISSUER"] == f"https://{ae.AUTH_HOST}"
    assert console["TB_OIDC_REDIRECT_URL"] == f"https://{ae.CONSOLE_HOST}/auth/oidc/callback"
    assert "console" not in published or not published["console"]
    mail = svcs["mail-gateway"]["environment"]
    assert (mail["IMAP_HOST"], mail["IMAP_SSL"], mail["SMTP_PORT"]) == (ae.MAIL_HOST, "true", "465")
    assert mail["IMAP_PASS"] == _env(prepared.dir)["TB_ACCEPTANCE_MAIL_PASSWORD"]
    assert "auth.disabled" not in svcs["acceptance-mail"]["environment"]["GREENMAIL_OPTS"]  # sign-in required
    # the mirrors sit on the internal network only, under the names the configuration uses
    nets = svcs["acceptance-directory"]["networks"]
    assert set(nets) == {"trialbox-net"} and ae.DIRECTORY_HOST in nets["trialbox-net"]["aliases"]
    assert ae.MAIL_HOST in svcs["acceptance-mail"]["networks"]["trialbox-net"]["aliases"]
    lldap = il.pinned(il.load()["third_party"]["lldap"])
    assert svcs["acceptance-directory"]["image"] == svcs["acceptance-directory-seed"]["image"] == lldap


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
def test_the_overlay_refuses_to_render_without_prepare(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TB_TZ=Asia/Taipei\nPOSTGRES_PASSWORD=x\nTB_TLS_HOSTNAME=h.test\n", encoding="utf-8")
    files = [x for f in ae.Stack().files() for x in ("-f", str(DEPLOY / f))]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "COMPOSE_"))}
    r = subprocess.run(["docker", "compose", "--project-directory", str(tmp_path), *files, "--profile", "oidc",
                        "config", "--quiet"], capture_output=True, text=True, timeout=120, check=False, env=env)  # fmt: skip
    assert r.returncode != 0 and "acceptance_env prepare" in r.stderr
