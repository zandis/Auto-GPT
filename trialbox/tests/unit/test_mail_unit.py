"""mail-gateway: authentication results, outbound routing + encryption (7z AES-256 and S/MIME), intake decisions."""

from __future__ import annotations

import datetime as dt
import io
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path

import pytest
from mail_gateway import intake
from mail_gateway.outbound import RoutingRefused, prepare, smime_wrap
from mail_gateway.store import MailDB
from tb_common.config import load_settings
from tb_common.objstore import FsStore
from tb_contracts import SendRequest

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(ROOT / "deploy" / "settings.example.yaml")
NOW = dt.datetime(2026, 10, 5, 9, 0, tzinfo=dt.UTC)


def _msg(
    subject: str = "FEAS GZQO",
    sender: str = "crc1@hospa.test",
    auth: str | None = "aligned",
    **headers: str,
) -> bytes:
    if auth == "aligned":  # what the hospital MTA records for an authenticated sender
        dom = sender.rsplit("@", 1)[-1].strip(">")
        auth = f"mx; spf=pass smtp.mailfrom={dom}; dkim=pass header.d={dom}"
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "trialbox@hospa.test"
    m["Subject"] = subject
    m["Message-ID"] = f"<{abs(hash(subject + sender))}@hospa.test>"
    if auth:
        m["Authentication-Results"] = auth
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content("hi")
    m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="../../etc/協議書 v3.pdf")
    return m.as_bytes(policy=policy.SMTP)


def test_authentication_results() -> None:
    def auth(h: str, server: str = "", sender: str = "crc1@hospa.test") -> bool:
        return intake.authentication(message_from_bytes(_msg(auth=h), policy=policy.default), server, sender)[0]

    assert auth("mx.hospa.test; spf=pass smtp.mailfrom=hospa.test")
    assert auth("mx.hospa.test; spf=pass smtp.mailfrom=bounce@mail.hospa.test")  # subdomain: relaxed alignment
    assert auth("mx.hospa.test; spf=softfail; dkim=pass header.d=hospa.test")
    assert auth("mx.hospa.test; dkim=fail header.d=hospa.test; dkim=pass header.d=hospa.test")
    assert auth("mx.hospa.test; spf=none; dmarc=pass header.from=hospa.test")
    assert not auth("mx.hospa.test; spf=fail; dkim=none")
    assert not auth("mx.hospa.test; spf=pass; dmarc=fail")
    assert not auth("evil.example; spf=pass; dkim=pass", server="mx.hospa.test")  # forged by another server
    # a pass for the attacker's own domain says nothing about From: pi@hospa.test (no enforcing DMARC)
    assert not auth("mx.hospa.test; spf=pass smtp.mailfrom=evil.example; dmarc=none", sender="pi@hospa.test")
    assert not auth("mx.hospa.test; dkim=pass header.d=hospa.test.evil.example", sender="pi@hospa.test")
    assert not auth("mx.hospa.test; spf=pass", sender="pi@hospa.test")  # pass without a domain cannot be aligned
    ok, detail = intake.authentication(
        message_from_bytes(_msg(auth="mx.hospa.test; spf=pass smtp.mailfrom=evil.example"), policy=policy.default),
        "",
        "pi@hospa.test",
    )
    assert not ok and "no pass aligned with hospa.test" in detail
    assert not intake.authentication(message_from_bytes(_msg(auth=None), policy=policy.default), "")[0]


def test_intake_decisions(tmp_path: Path) -> None:
    db = MailDB(tmp_path / "m.sqlite")
    m = intake.read(_msg("Re: FEAS gzqo lookback=24 -- for sponsor"))
    d = intake.decide(m, SETTINGS, db, NOW)
    assert d.action == "job" and d.job is not None
    assert (d.job.type, d.job.ruleset, d.job.options, d.job.comment) == (
        "FEAS",
        "GZQO",
        {"lookback": "24"},
        "for sponsor",
    )
    assert m.attachments[0][0] == "etc_協議書_v3.pdf"  # path components and spaces neutralised
    store = FsStore(tmp_path / "obj")
    files = intake.store_inputs(store, "01JB0000000000000000000000", m)
    assert store.get(files[0].minio_key) == b"%PDF-1.4 fake" and len(files[0].sha256) == 64
    assert store.get("attachments/01JB0000000000000000000000/message.eml") == m.raw
    unknown = intake.decide(intake.read(_msg(sender="x@evil.example")), SETTINGS, db, NOW)
    assert unknown.action == "reject" and not unknown.detailed_reply
    st = intake.decide(intake.read(_msg("STATUS 01JB0000000000000000000000")), SETTINGS, db, NOW)
    assert st.job is not None and st.job.ruleset is None and st.job.options == {"target": "01JB0000000000000000000000"}
    for _ in range(20):
        db.record_intake(f"<{_}@x>", "crc1@hospa.test", NOW.isoformat(), "job", "J")
    limited = intake.decide(intake.read(_msg("FEAS GZQO")), SETTINGS, db, NOW)
    assert limited.action == "reject" and "daily limit" in limited.reason
    db.record_sent(
        "<review-1@hospa.test>",
        "J1",
        "APPROVE GZQO version=1.0.0 -- review round 1, job J1",
        ["pi@hospa.test"],
        "aggregate",
        NOW.isoformat(),
    )
    reply = intake.decide(
        intake.read(_msg("ok!", sender="pi@hospa.test", In_Reply_To="<review-1@hospa.test>")), SETTINGS, db, NOW
    )
    assert reply.job is not None and (reply.job.type, reply.job.options) == ("APPROVE", {"version": "1.0.0"})


def _store(tmp_path: Path) -> FsStore:
    store = FsStore(tmp_path / "obj")
    store.put("outputs/J/list.xlsx", b"PK candidate list")
    store.put("outputs/J/report.pdf", b"%PDF summary")
    return store


def _req(to: list[str], tag: str = "phi", enc: bool = True) -> SendRequest:
    return SendRequest.model_validate(
        {
            "job_id": "01JB0000000000000000000000",
            "to": to,
            "subject": "Done 01JB — SCREEN GZQO",
            "body_md": "**Done.**\n\n| a | b |\n|---|---|\n| 1 | 2 |",
            "tag": tag,
            "encrypt": enc,
            "attachments": [{"minio_key": "outputs/J/list.xlsx", "filename": "list.xlsx", "tag": tag}],
        }
    )


def test_outbound_zip_encryption_and_routing(tmp_path: Path) -> None:
    import py7zr

    store = _store(tmp_path)
    with pytest.raises(RoutingRefused):
        prepare(
            _req(["pi@hospa.test", "cra@pharma.example"]),
            store=store,
            sender="trialbox@hospa.test",
            internal_domains=["hospa.test"],
        )
    p = prepare(_req(["PI@hospa.test"]), store=store, sender="trialbox@hospa.test", internal_domains=["hospa.test"])
    assert p.encrypted and p.recipients == ["pi@hospa.test"] and len(p.password_mails) == 1
    msg = message_from_bytes(p.data, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    html = msg.get_body(("html",))
    assert html is not None and "<table>" in html.get_content()
    (att,) = list(msg.iter_attachments())
    assert att.get_filename() == "01JB0000000000000000000000.7z" and b"candidate" not in p.data
    pw_msg = message_from_bytes(p.password_mails[0][1], policy=policy.default)
    body = str(pw_msg.get_body(("plain",)).get_content())  # type: ignore[union-attr]
    password = next(ln.strip() for ln in body.splitlines() if ln.startswith("    "))
    with py7zr.SevenZipFile(io.BytesIO(att.get_payload(decode=True)), password=password) as z:  # type: ignore[arg-type]
        z.extractall(tmp_path / "x")
    assert (tmp_path / "x" / "list.xlsx").read_bytes() == b"PK candidate list"
    agg = prepare(
        _req(["cra@pharma.example"], tag="aggregate", enc=False),
        store=store,
        sender="trialbox@hospa.test",
        internal_domains=["hospa.test"],
    )
    assert not agg.encrypted and b"PK candidate list" in message_from_bytes(
        agg.data, policy=policy.default
    ).get_payload()[1].get_payload(decode=True)  # type: ignore[index, union-attr]


def _cert(tmp_path: Path, name: str) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - dt.timedelta(days=1))
        .not_valid_after(NOW + dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    crt, kp = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kp.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return crt, kp


def test_outbound_smime(tmp_path: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs7

    sdir = tmp_path / "smime"
    sdir.mkdir()
    site_crt, site_key = _cert(tmp_path, "site")
    (sdir / "site.crt").write_bytes(site_crt.read_bytes())
    (sdir / "site.key").write_bytes(site_key.read_bytes())
    pi_crt, pi_key = _cert(tmp_path, "pi")
    p = prepare(
        _req(["pi@hospa.test"]),
        store=_store(tmp_path),
        sender="trialbox@hospa.test",
        internal_domains=["hospa.test"],
        mode="smime",
        smime_certs={"pi@hospa.test": str(pi_crt)},
        smime_dir=sdir,
    )
    assert p.encrypted and not p.password_mails and b"application/pkcs7-mime" in p.data
    plain = pkcs7.pkcs7_decrypt_smime(
        p.data,
        x509.load_pem_x509_certificate(pi_crt.read_bytes()),
        serialization.load_pem_private_key(pi_key.read_bytes(), None),  # type: ignore[arg-type]
        [],
    )
    assert b"multipart/signed" in plain and b"pkcs7-signature" in plain and b"list.xlsx" in plain
    with pytest.raises(Exception, match="no S/MIME certificate"):
        smime_wrap(EmailMessage(), ["nurse@hospa.test"], {}, sdir)
