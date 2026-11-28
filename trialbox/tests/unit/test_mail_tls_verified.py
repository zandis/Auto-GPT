"""H-137, the owner's decision on #639 (7156806411 item 6): the mail servers' certificates are verified by default.

A per-server switch turns the check off, and each start with it off (or with no TLS at all) is audited. The install
check tests the relay's certificate. A stand-in relay on 127.0.0.1 speaks STARTTLS with a certificate from a made-up
CA made here; nothing leaves the machine.
"""

from __future__ import annotations

import datetime as dt
import imaplib
import ipaddress
import socket
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from tb_common.config import Env, load_env

from tools.trialbox import doctor
from tools.trialbox import preflight as pf

HOST = "127.0.0.1"


def _pki(tmp: Path) -> tuple[Path, Path, Path]:
    """A made-up CA and a server certificate for 127.0.0.1 signed by it: (ca.pem, server.pem, server.key)."""
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Hospital Mail CA")])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )  # fmt: skip
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "relay.hospital.test")]))
        .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(HOST))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )  # fmt: skip
    ca_pem, leaf_pem, key_pem = tmp / "ca.pem", tmp / "server.pem", tmp / "server.key"
    ca_pem.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    leaf_pem.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return ca_pem, leaf_pem, key_pem


def _relay(server: ssl.SSLContext, got: list[bytes]) -> tuple[int, socket.socket]:
    """An SMTP stand-in: greeting, EHLO with STARTTLS, the handshake, then 250 to all, 354 to DATA."""
    lsock = socket.socket()
    lsock.bind((HOST, 0))
    lsock.listen(4)

    def one(conn: socket.socket) -> None:
        f: Any = conn.makefile("rwb")
        try:
            f.write(b"220 relay.hospital.test ESMTP\r\n")
            f.flush()
            while line := f.readline():
                cmd = line.strip().upper()
                if cmd.startswith(b"EHLO"):
                    f.write(b"250-relay.hospital.test\r\n250 STARTTLS\r\n")
                elif cmd == b"STARTTLS":
                    f.write(b"220 go ahead\r\n")
                    f.flush()
                    conn = server.wrap_socket(conn, server_side=True)
                    f = conn.makefile("rwb")
                    continue
                elif cmd == b"DATA":
                    f.write(b"354 end with .\r\n")
                    f.flush()
                    while (body := f.readline()) and body != b".\r\n":
                        got.append(body)
                    f.write(b"250 queued\r\n")
                elif cmd == b"QUIT":
                    f.write(b"221 bye\r\n")
                    f.flush()
                    return
                else:
                    f.write(b"250 ok\r\n")
                f.flush()
        except (OSError, ssl.SSLError):
            return
        finally:
            conn.close()

    def serve() -> None:
        while True:
            try:
                conn, _ = lsock.accept()
            except OSError:
                return
            threading.Thread(target=one, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return lsock.getsockname()[1], lsock


@pytest.fixture()
def relay(tmp_path: Path) -> Iterator[tuple[int, Path, list[bytes]]]:
    ca, cert, key = _pki(tmp_path)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, key)
    got: list[bytes] = []
    port, lsock = _relay(server, got)
    yield port, ca, got
    lsock.close()


def test_the_mail_context_checks_the_certificate_unless_switched_off() -> None:
    from mail_gateway import tls

    on, off = tls.context(True), tls.context(False)
    assert on.verify_mode == ssl.CERT_REQUIRED and on.check_hostname
    assert off.verify_mode == ssl.CERT_NONE and not off.check_hostname


def test_the_switches_are_read_per_server_and_default_on() -> None:
    env = load_env(Path("/nonexistent"), {})
    assert env.smtp_tls_verify is True and env.imap_tls_verify is True
    env = load_env(Path("/nonexistent"), {"SMTP_TLS_VERIFY": "false"})
    assert env.smtp_tls_verify is False and env.imap_tls_verify is True
    env = load_env(Path("/nonexistent"), {"IMAP_TLS_VERIFY": "0"})
    assert env.smtp_tls_verify is True and env.imap_tls_verify is False


def test_a_relay_with_an_untrusted_certificate_gets_no_mail(relay: tuple[int, Path, list[bytes]]) -> None:
    from mail_gateway.outbound import NotSent, smtp_transport

    port, _ca, got = relay
    send = smtp_transport(HOST, port, starttls=True)
    with pytest.raises(NotSent) as caught:
        send("box@hospital.test", ["crc@hospital.test"], b"Subject: synthetic\r\n\r\nsynthetic body\r\n")
    assert isinstance(caught.value.cause, ssl.SSLCertVerificationError), caught.value.cause
    assert got == []  # nothing reached the server that could not show who it is


def test_the_hospitals_ca_makes_the_relay_trusted(
    relay: tuple[int, Path, list[bytes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mail_gateway.outbound import smtp_transport

    port, ca, got = relay
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))  # what tb_common.extra_ca sets for a mounted TB_EXTRA_CA
    smtp_transport(HOST, port, starttls=True)("box@hospital.test", ["crc@hospital.test"], b"Subject: s\r\n\r\nok\r\n")
    assert b"ok\r\n" in got


def test_the_switch_off_sends_without_the_check(relay: tuple[int, Path, list[bytes]]) -> None:
    from mail_gateway.outbound import smtp_transport

    port, _ca, got = relay
    smtp_transport(HOST, port, starttls=True, verify=False)("box@hospital.test", ["crc@hospital.test"], b"\r\nok\r\n")
    assert b"ok\r\n" in got


def test_port_465_checks_the_certificate_from_the_first_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    import smtplib

    from mail_gateway.outbound import NotSent, smtp_transport

    seen: list[Any] = []

    def smtp_ssl(host: str, port: int, *a: Any, context: ssl.SSLContext | None = None, **k: Any) -> Any:
        seen.append(context)
        raise ConnectionRefusedError("no relay in this test")

    monkeypatch.setattr(smtplib, "SMTP_SSL", smtp_ssl)
    for verify, mode in ((True, ssl.CERT_REQUIRED), (False, ssl.CERT_NONE)):
        with pytest.raises(NotSent):
            smtp_transport("relay.hospital.test", 465, verify=verify)("box@hospital.test", ["crc@hospital.test"], b"x")
        assert seen[-1] is not None and seen[-1].verify_mode == mode


def test_the_imap_poll_checks_the_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    from mail_gateway.gateway import Gateway

    seen: list[Any] = []

    class Stop(Exception):
        pass

    def imap_ssl(host: str, port: int, *a: Any, ssl_context: ssl.SSLContext | None = None, **k: Any) -> Any:
        seen.append(ssl_context)
        raise Stop

    monkeypatch.setattr(imaplib, "IMAP4_SSL", imap_ssl)
    for verify, mode in ((True, ssl.CERT_REQUIRED), (False, ssl.CERT_NONE)):
        gw = SimpleNamespace(cfg=SimpleNamespace(env=Env(imap_host="imap.hospital.test", imap_tls_verify=verify)))
        with pytest.raises(Stop):
            Gateway.poll_once(cast(Gateway, gw))  # the poll reads only cfg.env before it connects
        assert seen[-1] is not None and seen[-1].verify_mode == mode


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields.get("detail") or {}))


@pytest.mark.parametrize(
    ("fields", "imap", "want"),
    [
        ({}, True, []),
        ({"smtp_tls_verify": False}, False, [("mail.tls_unverified", "smtp", "SMTP_TLS_VERIFY=false")]),
        ({"smtp_starttls": False}, False, [("mail.plaintext", "smtp", "SMTP_STARTTLS=false")]),
        ({"smtp_port": 465, "smtp_starttls": False}, False, []),  # 465 is TLS from the first byte
        ({"imap_ssl": False, "imap_tls_verify": False}, True, [("mail.plaintext", "imap", "IMAP_SSL=false")]),
        ({"imap_tls_verify": False}, True, [("mail.tls_unverified", "imap", "IMAP_TLS_VERIFY=false")]),
        ({"imap_tls_verify": False}, False, []),  # no mailbox polled: nothing spoken to
    ],
)
def test_each_start_without_a_verified_certificate_is_audited(
    fields: dict[str, Any], imap: bool, want: list[tuple[str, str, str]]
) -> None:
    from mail_gateway import tls

    audit = _Audit()
    tls.audit_modes(audit, Env(**fields), imap_used=imap)
    assert [(e, d["server"], d["setting"]) for e, d in audit.events] == want  # the line names the setting
    assert all(d["host"] for _e, d in audit.events)


def _mail_tls(env: dict[str, str]) -> doctor.Check:
    return next(c for c in doctor.CHECKS if c.__name__ == "check_mail_tls")(doctor.DoctorInputs(env=env))


def test_the_doctor_warns_while_a_mail_check_is_switched_off() -> None:
    assert _mail_tls({"TB_ENV": "PRODUCTION"}).status == "PASS"
    off = _mail_tls({"TB_ENV": "DEV", "SMTP_HOST": "relay.hospital.test", "SMTP_TLS_VERIFY": "false"})
    assert off.status == "WARN" and "smtp relay.hospital.test: SMTP_TLS_VERIFY=false" in off.detail
    plain = _mail_tls({"TB_ENV": "PRODUCTION", "SMTP_STARTTLS": "false", "SMTP_PORT": "25"})
    assert plain.status == "WARN" and "SMTP_STARTTLS=false" in plain.detail
    imap = {"TB_ENV": "PRODUCTION", "IMAP_HOST": "imap.hospital.test", "IMAP_TLS_VERIFY": "false"}
    assert _mail_tls(imap).status == "PASS"  # no mailbox polled
    polled = _mail_tls({**imap, "IMAP_USER": "intake"})
    assert polled.status == "WARN" and "imap imap.hospital.test: IMAP_TLS_VERIFY=false" in polled.detail
    both = _mail_tls({**imap, "IMAP_USER": "intake", "IMAP_SSL": "false", "SMTP_TLS_VERIFY": "0"})
    assert "IMAP_SSL=false" in both.detail and "SMTP_TLS_VERIFY=false" in both.detail


def test_the_gateway_start_writes_the_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    from mail_gateway import app

    audit = _Audit()
    env = Env(
        smtp_tls_verify=False,
        imap_user="intake",
        imap_host="imap.hospital.test",
        imap_ssl=False,
        audit_dir="/nonexistent",
    )
    monkeypatch.setenv("IMAP_HOST", "imap.hospital.test")  # review M-2: a mailbox is audited when it is polled
    monkeypatch.setenv("TB_MAIL_POLL_SECONDS", "60")
    monkeypatch.setattr(app, "_gw", None)
    monkeypatch.setattr(app, "get_config", lambda: SimpleNamespace(env=env))
    monkeypatch.setattr(app, "open_audit", lambda *a: audit)
    monkeypatch.setattr(app, "from_config", lambda: None)
    monkeypatch.setattr(app, "MailDB", lambda: None)
    monkeypatch.setattr(app, "Gateway", SimpleNamespace)
    monkeypatch.setenv("TB_MAIL_AUTHSERV_ID", "mx.hospital.test")
    app.gateway()
    assert [e for e, _ in audit.events] == ["mail.tls_unverified", "mail.plaintext"]


# ------------------------------------------------------------------------------------------- the install check
def _check(env: dict[str, str], cert: Any) -> doctor.Check:
    inp = doctor.DoctorInputs(env={"SMTP_HOST": "relay.hospital.test", "SMTP_PORT": "587", **env})
    probes = pf.Probes(banner=lambda h, p, t: "220 relay ESMTP", mail_cert=cert)
    return pf.check_mail_relay(inp, probes)


def test_the_install_check_tests_the_relay_certificate() -> None:
    def untrusted(host: str, port: int, cafile: str, t: float) -> str:
        raise ssl.SSLCertVerificationError("certificate verify failed: unable to get local issuer certificate")

    asked: list[str] = []

    def trusted(host: str, port: int, cafile: str, t: float) -> str:
        asked.append(cafile)
        return "verified"

    bad = _check({}, untrusted)
    assert bad.status == "FAIL" and "not trusted" in bad.detail and "TB_EXTRA_CA" in bad.detail
    good = _check({"TB_EXTRA_CA": "/etc/hospital-ca.pem"}, trusted)
    assert good.status == "PASS" and "certificate verified" in good.detail and asked == ["/etc/hospital-ca.pem"]
    off = _check({"SMTP_TLS_VERIFY": "false"}, untrusted)
    assert off.status == "WARN" and "mail.tls_unverified" in off.detail
    plain = _check({"SMTP_STARTTLS": "false"}, untrusted)
    assert plain.status == "WARN" and "mail.plaintext" in plain.detail


def test_the_install_checks_probe_speaks_starttls(relay: tuple[int, Path, list[bytes]]) -> None:
    port, ca, _got = relay
    with pytest.raises(ssl.SSLCertVerificationError):
        pf._mail_cert(HOST, port, "", 5.0)
    assert pf._mail_cert(HOST, port, str(ca), 5.0) == "verified"
