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


def _read(raw: bytes) -> intake.Inbound:
    """As the gateway reads a mail behind the hospital MTA ``mx`` (the authserv-id of :func:`_msg`'s header)."""
    return intake.read(raw, "mx")


def test_authentication_results() -> None:
    def auth(h: str, server: str = "mx.hospa.test", sender: str = "crc1@hospa.test") -> bool:
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
        "mx.hospa.test",
        "pi@hospa.test",
    )
    assert not ok and "no pass aligned with hospa.test" in detail
    assert not intake.authentication(message_from_bytes(_msg(auth=None), policy=policy.default), "")[0]


def test_intake_decisions(tmp_path: Path) -> None:
    db = MailDB()
    m = _read(_msg("Re: FEAS gzqo lookback=24 -- for sponsor"))
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
    unknown = intake.decide(_read(_msg(sender="x@evil.example")), SETTINGS, db, NOW)
    assert unknown.action == "reject" and not unknown.detailed_reply
    st = intake.decide(_read(_msg("STATUS 01JB0000000000000000000000")), SETTINGS, db, NOW)
    assert st.job is not None and st.job.ruleset is None and st.job.options == {"target": "01JB0000000000000000000000"}
    for _ in range(20):
        db.record_intake(f"<{_}@x>", "crc1@hospa.test", NOW.isoformat(), "job", "J")
    huge = intake.decide(_read(_msg("FEAS GZQO -- " + "A" * 200_000)), SETTINGS, db, NOW)
    assert huge.action == "reject" and "longer than 998" in huge.reason  # stress test #4
    limited = intake.decide(_read(_msg("FEAS GZQO")), SETTINGS, db, NOW)
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
        _read(_msg("ok!", sender="pi@hospa.test", In_Reply_To="<review-1@hospa.test>")), SETTINGS, db, NOW
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
    p = prepare(_req(["PI@hospa.test"]), store=store, sender="trialbox@hospa.test", internal_domains=["hospa.test"],
                mode="zip", allow_phi_zip=True)  # fmt: skip
    assert p.encrypted and p.recipients == ["pi@hospa.test"] and len(p.password_mails) == 1
    msg = message_from_bytes(p.data, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    html = msg.get_body(("html",))
    assert html is not None and "<table>" in html.get_content()
    (att,) = list(msg.iter_attachments())
    assert att.get_filename() == "01JB0000000000000000000000.7z" and b"PK candidate list" not in p.data
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


def test_reply_to_subject_with_encoded_crlf(tmp_path: Path) -> None:
    """An encoded-word subject that decodes to CR/LF is rejected with a one-line reply subject (it used to raise in
    the auto-reply and abort the IMAP poll)."""
    from mail_gateway.gateway import Gateway
    from tb_common.audit import AuditLog
    from tb_common.config import Config, load_env

    env = load_env(dotenv=tmp_path / "none.env", environ={"MAIL_FROM_ADDR": "trialbox@hospa.test"})
    sent: list[bytes] = []
    gw = Gateway(
        Config(env=env, settings=SETTINGS),
        FsStore(tmp_path / "obj"),
        MailDB(),
        AuditLog(tmp_path / "audit", "Asia/Taipei"),
        lambda _frm, _to, data: sent.append(data),
        jobs=lambda req: pytest.fail("no job for a malformed subject"),
        secrets_dir=tmp_path,
        authserv_id="mx.hospa.test",
    )
    raw = (
        b"From: crc1@hospa.test\r\nTo: trialbox@hospa.test\r\nMessage-ID: <crlf@hospa.test>\r\n"
        b"Authentication-Results: mx.hospa.test; spf=pass smtp.mailfrom=hospa.test\r\n"
        b"Subject: =?utf-8?q?hello=0D=0ABcc:_evil@evil.example?=\r\n\r\nx"
    )
    assert gw.handle(raw) == "Rejected"
    assert len(sent) == 1
    reply = message_from_bytes(sent[0], policy=policy.default)
    assert reply["Subject"] == "Re: hello Bcc: evil@evil.example" and reply["Bcc"] is None


def test_text_part_of_a_body_with_html_blocks_has_no_raw_tags() -> None:
    from mail_gateway.outbound import render_body

    text, html = render_body(
        "Ruleset **X** compiled.\n\n<h2>Ruleset X &mdash; round 1</h2>\n<ul><li>PHI guard: clean</li></ul>\n"
        "<table><tr><th>id</th><th>kind</th></tr><tr><td>X-INC-01</td><td>inclusion</td></tr></table>\n"
    )
    assert "<" not in text and "Ruleset X — round 1" in text
    assert "- PHI guard: clean" in text and "X-INC-01 | inclusion" in text
    assert "<table>" in html
    # D-119: the text part is rendered from the Markdown; T-116: the intended-use statement closes it
    assert render_body("plain **md**")[0].split("\n\n-- \n")[0] == "plain md"


def test_outbound_subject_with_a_middle_dot_has_no_empty_encoded_word(tmp_path: Path) -> None:
    """The box's subjects carry one non-ASCII character ("·"); Python's header folder used to emit an empty encoded
    word (``=?utf-8?q??=``) when it folded them, which some mail clients render as garbage."""
    store = _store(tmp_path)
    req = _req(["pi@hospa.test"], tag="aggregate", enc=False)
    req = req.model_copy(
        update={"subject": "[GZQO] CONSENT draft ready for review: EN, JA, zh-TW · job 01M6P5YTYTF5EZ35KRT7E7F75X"}
    )
    p = prepare(req, store=store, sender="trialbox@hospa.test", internal_domains=["hospa.test"])
    head = p.data.split(b"\r\n\r\n")[0]
    assert b"=?utf-8?q??=" not in head and all(len(line) <= 998 for line in head.split(b"\r\n"))
    msg = message_from_bytes(p.data, policy=policy.default)
    assert msg["Subject"] == req.subject
    enc = prepare(_req(["pi@hospa.test"]), store=store, sender="trialbox@hospa.test", internal_domains=["hospa.test"],
                  mode="zip", allow_phi_zip=True)  # fmt: skip
    pw = message_from_bytes(enc.password_mails[0][1], policy=policy.default)
    assert str(pw["Subject"]).startswith("Password: ")


def _send_gateway(tmp_path: Path, transport, allow_phi_zip: bool = True):  # type: ignore[no-untyped-def]
    from mail_gateway.gateway import Gateway
    from tb_common.audit import AuditLog
    from tb_common.config import Config, load_env

    env = load_env(dotenv=tmp_path / "none.env", environ={"MAIL_FROM_ADDR": "trialbox@hospa.test"})
    return Gateway(
        Config(env=env, settings=SETTINGS),
        _store(tmp_path),
        MailDB(),
        AuditLog(tmp_path / "audit", "Asia/Taipei"),
        transport,
        jobs=lambda req: pytest.fail("no job"),
        secrets_dir=tmp_path,
        allow_phi_zip=allow_phi_zip,  # the example settings' zip mode: a synthetic box unless a test says otherwise
        outputs_current=lambda _job: True,  # D-863: the orchestrator says the job's outputs are current
    )


def test_the_same_send_key_never_mails_twice(tmp_path: Path) -> None:
    """D-127 (review F-02): a step re-run after a restart sends the same key; the PI gets one mail and one password."""
    sent: list[list[str]] = []
    gw = _send_gateway(tmp_path, lambda _f, to, _d: sent.append(list(to)))
    req = _req(["pi@hospa.test"], tag="phi", enc=True).model_copy(update={"idempotency_key": "tbmail-k1"})
    first = gw.send(req)
    n = len(sent)
    again = gw.send(req)
    assert again.message_id == first.message_id and len(sent) == n  # nothing sent the second time
    assert gw.send(req.model_copy(update={"idempotency_key": "tbmail-k2"})).message_id != first.message_id


def test_a_refusal_before_sending_is_held_and_a_lost_answer_never_resends(tmp_path: Path) -> None:
    """D-127 with T-108c (D-401): a 5xx refusal is held as ``failed`` and a lost answer as ``uncertain``; neither is
    an error for the caller, neither key stays in ``sending``, and the same key never sends again by itself."""
    import smtplib

    state = {"fail": "refused"}
    sent: list[bytes] = []

    def transport(_f: str, to: list[str], data: bytes) -> None:
        if state["fail"] == "refused":
            raise smtplib.SMTPRecipientsRefused({to[0]: (550, b"no")})
        if state["fail"] == "lost":
            sent.append(data)  # the server took it, then the connection dropped before the answer
            raise TimeoutError("answer lost")
        sent.append(data)

    gw = _send_gateway(tmp_path, transport)
    req = _req(["pi@hospa.test"], tag="aggregate", enc=False).model_copy(update={"idempotency_key": "tbmail-a"})
    out = gw.deliver(req)
    assert out.state == "failed" and out.result.sent_to == [] and gw.db.get("tbmail-a").state == "failed"
    state["fail"] = ""
    assert gw.deliver(req).state == "failed" and sent == []  # held for a person: not sent again by itself
    req2 = req.model_copy(update={"idempotency_key": "tbmail-b"})
    state["fail"] = "lost"
    assert gw.deliver(req2).state == "uncertain"
    state["fail"] = ""
    assert gw.deliver(req2).state == "uncertain"  # may have arrived: never resent automatically
    assert gw.drain(force=True) == {} and len(sent) == 1
    assert {r.state for r in gw.db.open_keys()} == {"failed", "uncertain"}


def test_orchestrator_send_keys_are_stable() -> None:
    from orchestrator.core import send_key

    a = send_key("J1", "done", ["b@x", "a@x"], "S", ["list.xlsx", "r.pdf"])
    assert a == send_key("J1", "done", ["a@x", "b@x"], "S", ["r.pdf", "list.xlsx"])
    assert a != send_key("J1", "failed", ["a@x", "b@x"], "S", ["r.pdf", "list.xlsx"])


def test_link_mode_sends_no_patient_file_and_no_password(tmp_path: Path) -> None:
    """D-127: a site that chose 'link' gets a mail with a sign-in link instead of a zip and a password mail."""
    from mail_gateway.outbound import EncryptionError

    store = _store(tmp_path)
    req = _req(["pi@hospa.test"], tag="phi", enc=True)
    p = prepare(req, store=store, sender="trialbox@hospa.test", internal_domains=["hospa.test"], mode="link",
                link_base="https://trialbox.hospa.test/")  # fmt: skip
    msg = message_from_bytes(p.data, policy=policy.default)
    assert not p.password_mails and not p.encrypted
    assert not [part for part in msg.iter_attachments()]
    text = msg.get_body(preferencelist=("plain",)).get_content()  # type: ignore[union-attr]
    assert f"https://trialbox.hospa.test/pilot/jobs/{req.job_id}" in text and "サインイン" in text and "登入" in text
    with pytest.raises(EncryptionError, match="TB_CONSOLE_URL"):
        prepare(req, store=store, sender="trialbox@hospa.test", internal_domains=["hospa.test"], mode="link")
