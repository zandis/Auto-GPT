"""T-212a (D-369, CR-025, SEC-11): the mail boundary. Patient files are not mailed as a password zip on a real box,
the default delivery is a sign-in link, and a failed sender authentication sends nothing."""

from __future__ import annotations

import inspect
from email import policy
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import pytest
import yaml
from mail_gateway import intake
from mail_gateway.gateway import Gateway
from mail_gateway.outbound import EncryptionError, prepare
from mail_gateway.store import MailDB
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, SendRequest, Settings

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(ROOT / "deploy" / "settings.example.yaml")  # attachment_encryption: zip (test stacks)
MX = "mx.hospa.test"


def _gateway(
    tmp_path: Path,
    sent: list[tuple[list[str], bytes]],
    *,
    authserv_id: str = MX,
    allow_phi_zip: bool = False,
    settings: Settings = SETTINGS,
    console_url: str = "",
) -> Gateway:
    environ = {"MAIL_FROM_ADDR": "trialbox@hospa.test", "MAIL_INTAKE_ADDR": "trialbox@hospa.test"}
    if console_url:
        environ["TB_CONSOLE_URL"] = console_url
    env = load_env(dotenv=tmp_path / "none.env", environ=environ)
    store = FsStore(tmp_path / "obj")
    store.put("outputs/J/list.xlsx", b"PK candidate list")

    def no_job(req: JobCreate) -> Any:
        pytest.fail("no job may start from this mail")

    return Gateway(
        Config(env=env, settings=settings),
        store,
        MailDB(),
        AuditLog(tmp_path / "audit", "Asia/Taipei"),
        lambda _frm, to, data: sent.append((list(to), data)),
        jobs=no_job,
        secrets_dir=tmp_path,
        authserv_id=authserv_id,
        allow_phi_zip=allow_phi_zip,
        outputs_current=lambda _job: True,  # D-863: the orchestrator says the job's outputs are current
    )


def _phi(key: str = "") -> SendRequest:
    return SendRequest.model_validate(
        {
            "job_id": "01JB0000000000000000000000",
            "to": ["pi@hospa.test"],
            "subject": "Done 01JB · SCREEN GZQO",
            "body_md": "The candidate list is ready.",
            "tag": "phi",
            "encrypt": True,
            "attachments": [{"minio_key": "outputs/J/list.xlsx", "filename": "list.xlsx", "tag": "phi"}],
            **({"idempotency_key": key} if key else {}),
        }
    )


def _mail(auth: str | None, sender: str = "crc1@hospa.test") -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "trialbox@hospa.test"
    m["Subject"] = "FEAS GZQO"
    m["Message-ID"] = make_msgid(domain="hospa.test")  # a new one each time: a repeated id is answered from the store
    if auth:
        m["Authentication-Results"] = auth
    m.set_content("count please")
    return m.as_bytes(policy=policy.SMTP)


# ------------------------------------------------------------------------------------------- the default is not zip
def test_the_default_is_not_zip(tmp_path: Path) -> None:
    from tools.settings_wizard import QUESTIONS, build

    assert Settings.model_fields["attachment_encryption"].default == "link"
    assert load_env(dotenv=tmp_path / "none.env", environ={}).attach_password_mode == "link"
    assert inspect.signature(prepare).parameters["mode"].default == "link"
    assert next(q for q in QUESTIONS if q[0] == "attachment_encryption")[2] == "link"
    answers = yaml.safe_load((ROOT / "tests/fixtures/onboarding/site_c_answers.yaml").read_text(encoding="utf-8"))
    answers.pop("attachment_encryption")
    answers["mapping"] = "mapping/tw_core/demo_his.yaml"  # an installed mapping (the site C one is the test's own)
    settings, env, warnings = build(answers)
    assert settings["attachment_encryption"] == "link" and env["ATTACH_PASSWORD_MODE"] == "link"
    assert env["TB_CONSOLE_URL"] == "https://trialbox.hospc.test" and warnings == []
    answers["attachment_encryption"] = "zip"
    assert any("D-369" in w for w in build(answers)[2])


def test_a_patient_file_is_never_mailed_as_a_password_zip_on_a_real_box(tmp_path: Path) -> None:
    sent: list[tuple[list[str], bytes]] = []
    gw = _gateway(tmp_path, sent)  # the settings say zip; the box is not a synthetic one
    with pytest.raises(EncryptionError, match="D-369"):
        gw.send(_phi("tbmail-ppap"))
    assert sent == []  # nothing left: no archive, no password mail
    with pytest.raises(EncryptionError):  # the key was freed, so a corrected setting can send it later
        gw.send(_phi("tbmail-ppap"))
    # an aggregate attachment that asks to be encrypted may still go as a zip (no chart numbers in it)
    agg = _phi().model_copy(
        update={
            "tag": "aggregate",
            "attachments": [a.model_copy(update={"tag": "aggregate"}) for a in _phi().attachments or []],
        }
    )
    assert gw.send(agg).password_sent
    # a synthetic box (TB_ENV DEV or TEST) keeps the zip its tests open
    sent2: list[tuple[list[str], bytes]] = []
    assert _gateway(tmp_path / "synthetic", sent2, allow_phi_zip=True).send(_phi()).password_sent


def test_link_mode_delivers_a_link_to_the_named_recipients(tmp_path: Path) -> None:
    sent: list[tuple[list[str], bytes]] = []
    link = Settings.model_validate(
        {**SETTINGS.model_dump(mode="json", exclude_none=True), "attachment_encryption": "link"}
    )
    gw = _gateway(tmp_path, sent, settings=link, console_url="https://trialbox.hospa.test")
    res = gw.send(_phi())
    assert res.sent_to == ["pi@hospa.test"] and not res.password_sent and not res.encrypted
    ((to, data),) = sent
    assert to == ["pi@hospa.test"] and b"PK candidate list" not in data and b"x-7z" not in data
    assert b"/pilot/jobs/01JB0000000000000000000000" in data


# ------------------------------------------------------------------------------ sender authentication fails closed
def test_no_authserv_id_trusts_no_header() -> None:
    from email import message_from_bytes

    msg = message_from_bytes(_mail(f"{MX}; spf=pass smtp.mailfrom=hospa.test; dmarc=pass"), policy=policy.default)
    assert isinstance(msg, EmailMessage)
    ok, detail = intake.authentication(msg, "", "crc1@hospa.test")
    assert not ok and "TB_MAIL_AUTHSERV_ID" in detail
    assert intake.authentication(msg, MX, "crc1@hospa.test")[0]


@pytest.mark.parametrize(
    ("authserv_id", "auth"),
    [
        (MX, f"{MX}; spf=fail smtp.mailfrom=hospa.test; dkim=fail header.d=hospa.test"),  # failed at our MTA
        (MX, "evil.example; spf=pass smtp.mailfrom=hospa.test; dmarc=pass"),  # forged by another server
        (MX, None),  # no result at all
        ("", f"{MX}; spf=pass smtp.mailfrom=hospa.test; dmarc=pass"),  # the box does not know its MTA
    ],
)
def test_a_failed_mail_auth_sends_nothing(tmp_path: Path, authserv_id: str, auth: str | None) -> None:
    sent: list[tuple[list[str], bytes]] = []
    gw = _gateway(tmp_path, sent, authserv_id=authserv_id)
    assert gw.handle(_mail(auth)) == "Rejected"
    assert sent == []  # no refusal mail to an address nobody proved
    rows = [r for r in (tmp_path / "audit").rglob("*") if r.is_file()]
    assert rows, "the refusal is still audited"


def test_an_authenticated_mail_still_gets_its_answer(tmp_path: Path) -> None:
    sent: list[tuple[list[str], bytes]] = []
    gw = _gateway(tmp_path, sent)
    raw = _mail(f"{MX}; spf=pass smtp.mailfrom=hospa.test").replace(b"FEAS GZQO", b"PLEASE COUNT GZQO")
    assert gw.handle(raw) == "Rejected"
    assert len(sent) == 1 and b"unknown command" in sent[0][1].lower()
