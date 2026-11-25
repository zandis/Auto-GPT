"""M3: the egress edge's rules, its record, its doors, and the code scan that keeps every sender behind it."""

from __future__ import annotations

import ast
import io
import json
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common import egress_edge as ee
from tb_common import egress_record

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
NAMED = {
    "Robin Example": ("Patient name: Robin Example.", "Pt: Robin Example. Gout."),
    "70000054": ("MRN: 70000054",),
    "1961-04-03": ("DOB: 1961-04-03",),
    "昭和36年4月3日": ("生年月日:昭和36年4月3日",),
    "民國50年4月3日": ("生日:民國50年4月3日",),
    "0912-345-678": ("手機 0912-345-678",),
    "090-1234-5678": ("電話 090-1234-5678",),
    "山田太郎": ("患者氏名:山田太郎",),
    "王小明": ("病患姓名:王小明",),
    "A123456789": ("身分證 A123456789",),
}
LINES = [(v, t) for v, ts in NAMED.items() for t in ts]


class Audit:
    def __init__(self, broken: bool = False) -> None:
        self.lines: list[dict[str, Any]] = []
        self.broken = broken

    def append(self, event: str, **fields: Any) -> None:
        if self.broken:
            raise OSError("disk full")
        self.lines.append({"event": event, **fields})


@pytest.fixture(autouse=True)
def the_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ee, "site", lambda: ee.Site(r"^\d{8}$", ("hosp.example",)))


def reason(route: str, payload: Any, **kw: Any) -> str:
    with pytest.raises(ee.Refused) as got:
        ee.leave(route, "x", payload, **{"audit": Audit(), "actor": "t", **kw})
    return got.value.reason


# ------------------------------------------------------------------------------------------------ one rule set
@pytest.mark.parametrize(("value", "line"), LINES)
def test_the_bundle_the_log_and_the_tripwire_read_the_one_rule_set(value: str, line: str) -> None:
    """On master the bundle left 9 of these readable and the log one."""
    from guard.guard import Guard
    from tb_common.logging import redact

    from tools.bundle_scrub import scrub_text

    assert value not in scrub_text(line)
    assert value not in redact(line)
    assert Guard(None).tripwire(line).hit


@pytest.mark.parametrize("image", [True, False])
def test_a_host_without_the_library_asks_the_box_image(
    image: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-88's way: one container of the box's own image answers; no image, refused by name."""
    import sys

    from tools import bundle_scrub as bs
    from tools.trialbox import launch

    docker = tmp_path / "docker"
    run = f"cd {ROOT} && PYTHONPATH=libs:services:. exec {sys.executable} -m tools.bundle_scrub"
    docker.write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/argv\n{run if image else "exit 125"}\n')
    docker.chmod(0o755)
    monkeypatch.setattr(launch, "box_file", lambda: {"TB_DOCKER": str(docker), "TB_IMAGE": "box-img:1"})
    monkeypatch.setitem(sys.modules, "tb_common.egress_edge", None)  # it cannot be imported here
    bs.egress_rules.cache_clear()
    try:
        if not image:
            with pytest.raises(bs.ScrubError, match="box-img:1"):
                bs.scrub_text("Patient name: Robin Example.")
            return
        assert bs.scrub_text("Patient name: Robin Example.") == "Patient name: [NAME]."
        got = bs.egress_rules()(op="leave", route="support.bundle", destination="support", actor="t",
                                files=[["a.txt", "Pt: Robin Example"]])  # fmt: skip
        assert "Robin" not in str(got) and got["line"]["detail"]["result"] == "masked"
        argv = (tmp_path / "argv").read_text()
        assert "--pull never --network none --cap-drop ALL" in argv and "box-img:1 python -m tools.bundle_scrub" in argv
        assert "-v" not in argv.split() and "Robin" not in argv
        rules: Any = bs.egress_rules()
        rules.p.stdin.close()
        rules.p.wait(10)
    finally:
        bs.egress_rules.cache_clear()


@pytest.mark.parametrize("extra", [Path("/x/090-1234-5678"), b"090-1234-5678", ValueError("090-1234-5678"), 70000054])
def test_a_log_extra_that_is_not_text_is_scrubbed(extra: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """R22-21: an object, a path, bytes, an exception, a number went out as written."""
    import logging

    from tb_common import logging as tb_logging

    monkeypatch.setattr(tb_logging, "_EXTRA_MRN", [re.compile(r"(?<![0-9A-Za-z])\d{8}(?![0-9A-Za-z])")])
    rec = logging.LogRecord("x", 20, "x", 1, "m", None, None)
    rec.row = extra
    rec.n, rec.ok, rec.none, rec.sec = 3, True, None, 1.5
    out = json.loads(tb_logging.JsonFormatter("svc").format(rec))
    assert "090-1234-5678" not in str(out) and "70000054" not in str(out)
    assert (out["n"], out["ok"], out["none"], out["sec"]) == (3, True, None, 1.5)


# ------------------------------------------------------------------------------------------------ refused, never passed
def test_a_route_with_no_rule_refuses() -> None:
    assert reason("download.unlisted", "hello") == "no_rule"


def test_a_field_the_rule_does_not_name_is_masked() -> None:
    got = ee.leave("download.audit", "x", ee.File("a.csv", b"time,colour\n2026-11-25,blue\n"), audit=Audit(), actor="t")
    assert got.data == ("time,colour\n2026-11-25," + ee.MASK_CHAR * 4 + "\n").encode()


def test_a_masker_that_fails_sends_nothing_and_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("Robin Example")

    monkeypatch.setattr(ee, "spans", boom)
    audit = Audit()
    assert reason("mail.staff", "Patient name: Robin Example", audit=audit) == "mask_failed"
    assert audit.lines[0]["detail"]["result"] == "refused" and "Robin" not in json.dumps(audit.lines)


def test_a_departure_that_cannot_be_recorded_does_not_leave() -> None:
    assert reason("mail.staff", "hello", audit=Audit(broken=True)) == "not_recorded"
    assert reason("edc.write", "row", audit=Audit(broken=True), named=["x"]) == "not_recorded"


def _pdf_of_a_scan() -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("name", "data"),
    [("a.png", b"\x89PNG\r\n\x1a\n\x00\x00"), ("a.pdf", b"%PDF-1.7 broken"), ("a.pdf", _pdf_of_a_scan()),
     ("a.zip", b"PK\x03\x04 broken"), ("a.csv", "病歷".encode("big5")), ("a.7z", b"7z\xbc\xaf\x27\x1c")],
)  # fmt: skip
def test_what_cannot_be_read_is_refused(name: str, data: bytes) -> None:
    assert reason("download.aggregate", ee.File(name, data)) == "unreadable"


def test_a_payload_too_large_to_read_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ee, "MAX_BYTES", 10)
    assert reason("download.study", ee.File("a.csv", b"a,b\n1,2222222\n")) == "too_large"


def test_note_text_is_refused_on_an_aggregate_route_only() -> None:
    f = ee.File("a.json", b'{"note_text": "stable, no change"}')
    assert reason("download.aggregate", f) == "free_text"
    assert ee.leave("download.study", "x", f, audit=Audit(), actor="t") == f


def test_a_pdf_with_an_identifier_is_refused() -> None:
    from reportlab.pdfgen import canvas

    def made(line: str) -> bytes:
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 700, line)
        c.save()
        return buf.getvalue()

    assert reason("download.aggregate", ee.File("a.pdf", made("MRN: 70000054"))) == "identifiers"
    ok = ee.File("a.pdf", made("12 of 85 patients"))
    assert ee.leave("download.aggregate", "x", ok, audit=Audit(), actor="t") == ok


def test_the_registry_export_is_the_fourth_exception_and_counts_its_chart_numbers() -> None:
    from openpyxl import Workbook

    wb = Workbook()
    for row in (["no", "chart"], ["RA01-0001", "70000054"], ["RA01-0002", "70000062"], ["RA01-0003", "70000054"]):
        wb.active.append(row)  # type: ignore[union-attr]
    buf = io.BytesIO()
    wb.save(buf)
    path = "/pilot/registry/RA01/export.xlsx"
    c, audit = _console({path: ("screening_log_RA01.xlsx", buf.getvalue())})
    assert c.get(path).content == buf.getvalue()
    d = audit.lines[-1]["detail"]
    assert (d["route"], d["result"], d["items"]) == ("download.registry", "exception", 2)
    assert reason("download.registry", ee.File("a.xlsx", buf.getvalue())) == "not_named"
    assert {r for v in ee.EXCEPTIONS.values() for r in v} == {k for k, r in ee.ROUTES.items() if r.mode == "exception"}
    assert len(ee.EXCEPTIONS) == 4 and ee.chart_numbers(b"not a workbook") is None


# ------------------------------------------------------------------------------------------------ names of files
def test_a_file_name_is_masked_and_a_day_in_it_stays() -> None:
    got = ee.leave("download.study", "x", ee.File("log_70000054_20261125.csv", b"a\n1\n"), audit=Audit(), actor="t")
    assert got.name == "log_________" + "_20261125.csv"


def test_a_member_name_inside_a_zip_is_masked() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("70000054.csv", "a\n1\n")
    got = ee.leave("download.aggregate", "x", ee.File("p.zip", buf.getvalue()), audit=Audit(), actor="t")
    assert zipfile.ZipFile(io.BytesIO(got.data)).namelist() == ["________.csv"]


def test_a_staff_address_stays_and_any_other_is_masked() -> None:
    got = ee.leave("mail.staff", "mail:hosp.example", "pi@hosp.example robin@home.example", audit=Audit(), actor="t")
    assert got.startswith("pi@hosp.example ") and "home" not in got


@pytest.mark.parametrize(
    ("line", "stays"),
    [("示範醫師甲 (P12345)", True), ("佐藤 健一 (P12345)", True), ("氏名:佐藤 健一 (P12345)", False),
     ("病患 王小明 (70000054)", False), ("主治醫師 王大明", True), ("山田太郎医師", True), ("Dr. Smith", True),
     ("病患姓名:王小明醫師", False), ("氏名:山田太郎 医師より", False), ("Patient name: Dr. Smith", False)],
)  # fmt: skip
def test_a_report_names_its_doctors_and_never_a_patient(line: str, stays: bool) -> None:
    assert (ee.leave("download.aggregate", "x", line, audit=Audit(), actor="t") == line) is stays


def test_a_study_s_own_number_stays_and_a_chart_number_under_its_head_does_not() -> None:
    f = ee.File("a.csv", b"Subject ID,record_id\nGZQO-0001,17\n")
    assert ee.leave("download.study", "x", f, audit=Audit(), actor="t") == f
    got = ee.leave("download.study", "x", ee.File("a.csv", b"Subject ID\n70000054\n"), audit=Audit(), actor="t")
    assert b"70000054" not in got.data


def test_a_consent_form_keeps_the_hospital_s_own_telephone_and_nothing_of_a_patient() -> None:
    page = b"<p>Emergency line 02-2312-3456. MRN: 70000054</p>"
    audit = Audit()
    form = ee.leave(
        "mail.staff", "x", ee.Message("s", "b", (("consent_RA01_zh-TW.html", page),)), audit=audit, actor="t"
    )
    assert b"02-2312-3456" in form.files[0][1] and b"70000054" not in form.files[0][1]
    other = ee.leave("mail.staff", "x", ee.Message("s", "b", (("report.html", page),)), audit=audit, actor="t")
    assert b"02-2312-3456" not in other.files[0][1]


# ------------------------------------------------------------------------------------------------ the record
def test_the_record_holds_one_line_per_try_and_no_identifier() -> None:
    audit = Audit()
    for _ in range(2):  # a retried send: one line each
        ee.leave("mail.staff", "mail:hosp.example", ee.Message("s", "MRN: 70000054"), audit=audit, actor="job:J")
    assert len(audit.lines) == 2
    d = audit.lines[0]["detail"]
    assert len(audit.lines[0]["output_sha"]) == 64  # where every audited file's hash stands
    assert set(d) | {"sha256"} == egress_record.FIELDS and (d["items"], d["result"], d["rule"]) == (1, "masked", "mask")
    assert "70000054" not in json.dumps(audit.lines)
    ee.leave("edc.write", "x", "row", audit=audit, actor="t", named=["x"])
    assert audit.lines[-1]["detail"]["items"] == "unknown"  # not known is said, never 0


def test_a_destination_that_names_a_person_is_not_recorded() -> None:
    with pytest.raises(ee.Refused, match="not_recorded"):
        ee.leave("mail.staff", "robin@home.example", "hello", audit=Audit(), actor="t")


def test_the_page_counts_by_day_and_route() -> None:
    e = {"event": egress_record.EVENT, "ts": "2026-11-25T01:00:00", "detail": {"route": "log", "result": "sent"}}
    rows = egress_record.by_day([e, e, {"event": "other"}, {**e, "ts": "2026-11-26T01:00:00"}])
    assert [(r["day"], r["count"]) for r in rows] == [("2026-11-26", 1), ("2026-11-25", 2)]


# ------------------------------------------------------------------------------------------------ the tripwire's switch
def test_the_tripwire_cannot_be_off_on_a_production_box(tmp_path: Path) -> None:
    from gateway.core import Gateway, GatewayConfig
    from gateway.policy import RoutingPolicy
    from registry.registry import Registry
    from tb_common.audit import AuditLog
    from tb_common.policy.classes import Environment

    def start(env: Environment) -> Any:
        return Gateway(RoutingPolicy.load(), Registry.load(), AuditLog(tmp_path / env.value),
                       GatewayConfig(environment=env, phi_tripwire=False), env={})  # fmt: skip

    with pytest.raises(ValueError, match="TB_GATEWAY_PHI_TRIPWIRE"):
        start(Environment.PRODUCTION)
    assert start(Environment.TEST)
    off = {"TB_GATEWAY_PHI_TRIPWIRE": "off"}
    state = {env: ee.doctor_checks({**off, "TB_ENV": env})[-1][1] for env in ("PRODUCTION", "VALIDATION", "DEV")}
    assert state == {"PRODUCTION": "FAIL", "VALIDATION": "WARN", "DEV": "WARN"}
    assert ee.doctor_checks(off)[-1][1] == "FAIL"  # an environment that is not named is PRODUCTION
    assert ee.doctor_checks({})[-1][1] == "PASS"


# ------------------------------------------------------------------------------------------------ the mail's exception
def _mail(tag: str = "phi", body: str = "list") -> Any:
    from tb_contracts import SendRequest

    return SendRequest.model_validate({
        "job_id": "01HZZZZZZZZZZZZZZZZZZZZZZZ", "to": ["crc@hosp.example"], "subject": "S", "body_md": body, "tag": tag,
        "attachments": [{"filename": "a.csv", "minio_key": "k", "tag": tag}]})  # fmt: skip


STORE = SimpleNamespace(get=lambda _k: b"MRN\n70000054\n")


@pytest.mark.parametrize("production", [True, False])
def test_the_list_goes_to_a_person_on_the_log_today_only(production: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """PR1239-H2: the current delegation is asked at each send; unknown stops a PRODUCTION box and is shown on others."""
    monkeypatch.setenv("TB_ENV", "PRODUCTION" if production else "VALIDATION")

    def send(delegated: bool | None) -> str:
        audit = Audit()
        ee.gate_mail(_mail(), STORE, audit=audit, internal=lambda _r: True, rights=lambda _j, _t: (delegated, True))
        return str(audit.lines[0]["detail"]["reason"])

    assert send(True) == ""
    with pytest.raises(ee.Refused, match="not_delegated"):
        send(False)
    if production:
        with pytest.raises(ee.Refused, match="not_delegated"):
            send(None)
    else:
        assert send(None) == "rights unknown"


def test_the_list_asked_for_by_a_person_without_the_right_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR1239-H3: the asker's own rights, never a site-wide sender list."""
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    with pytest.raises(ee.Refused, match="sender_right"):
        ee.gate_mail(_mail(), STORE, audit=Audit(), internal=lambda _r: True, rights=lambda _j, _t: (True, False))
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    with pytest.raises(ee.Refused, match="sender_right"):
        ee.gate_mail(_mail(), STORE, audit=Audit(), internal=lambda _r: True, rights=lambda _j, _t: (True, None))
    with pytest.raises(ee.Refused, match="not_delegated"):  # nobody to ask
        ee.gate_mail(_mail(), STORE, audit=Audit(), internal=lambda _r: True)


def test_an_aggregate_mail_is_read_whatever_its_tag_says() -> None:
    req, store = ee.gate_mail(_mail("aggregate", "Pt: Robin Example"), STORE, audit=Audit(), internal=lambda _r: True)
    assert "Robin" not in req.body_md and b"70000054" not in store.get("k")
    with pytest.raises(ee.Refused, match="not_named"):  # a patient file to another domain
        ee.gate_mail(_mail(), STORE, audit=Audit(), internal=lambda _r: False, rights=lambda _j, _t: (True, True))


def test_the_rights_are_read_from_the_log_and_unknown_is_not_a_yes() -> None:
    from orchestrator.grants import all_of

    assert all_of([True, True]) is True and all_of([True, False, None]) is False
    assert all_of([True, None]) is None and all_of([]) is None


def test_a_mailbox_is_on_the_log_by_the_staff_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    from console import teamstore
    from orchestrator.grants import mailbox_right

    class Store:
        def __init__(self, _url: Any = None) -> None: ...
        def close(self) -> None: ...

        def staff(self) -> list[Any]:
            return [SimpleNamespace(username=u, contact=f"{u.upper()}@hosp.example") for u in ("crc", "left")]

        def entries(self, _study: str) -> list[Any]:
            return [SimpleNamespace(username="crc", active_on=lambda _d: True),
                    SimpleNamespace(username="left", active_on=lambda _d: False)]  # fmt: skip

    monkeypatch.setattr(teamstore, "TeamStore", Store)
    day = date(2026, 11, 25)
    ask = {m: mailbox_right(f"{m}@hosp.example", "RA01", day) for m in ("crc", "left", "clinic-list")}
    assert ask == {"crc": True, "left": False, "clinic-list": None}

    def down(_url: Any = None) -> Any:
        raise OSError("no database")

    monkeypatch.setattr(teamstore, "TeamStore", down)
    assert mailbox_right("crc@hosp.example", "RA01", day) is None


def test_an_edc_write_is_recorded_before_it_is_sent_and_a_read_is_not() -> None:
    import httpx
    from orchestrator.study_api import StudyService
    from rc_bridge.client import RedcapClient

    sent: list[bytes] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(200, json=["1"])

    audit = Audit()
    svc = SimpleNamespace(audit=audit)
    http = httpx.Client(transport=httpx.MockTransport(answer))
    rc = StudyService._edge(svc, RedcapClient("https://edc.example/", "0" * 32, http=http))  # type: ignore[arg-type]
    rc.version()
    assert audit.lines == []
    rc.import_records([{"record_id": "1", "a": "2"}])
    assert [x["detail"]["destination"] for x in audit.lines] == ["edc.example"] and len(sent) == 2
    audit.broken = True
    with pytest.raises(ee.Refused, match="not_recorded"):
        rc.import_records([{"record_id": "1"}])
    assert len(sent) == 2


# ------------------------------------------------------------------------------------------------ the console's door
def _console(files: dict[str, tuple[str, bytes]], tag: str = "aggregate", mailbox: str = "crc@hosp.example",
             delegated: bool = True) -> Any:  # fmt: skip
    from console import egress_page
    from console.auth import Session  # noqa: F401  (the console package loads)
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, Response
    from starlette.testclient import TestClient

    audit = Audit()
    user = SimpleNamespace(
        username="crc", mailbox=mailbox, can_view_phi=True, sees_study=lambda _s: True, is_admin=True
    )
    sess = SimpleNamespace(user=user, lang="en")
    job = SimpleNamespace(ruleset="RA01", outputs=[SimpleNamespace(filename="f.csv", tag=tag,
                                                                  recipients=["crc@hosp.example"])])  # fmt: skip
    h: Any = SimpleNamespace(
        au=audit,
        users=SimpleNamespace(session=lambda *_a, **_k: sess),
        actor=lambda s: f"console:{s.user.username}",
        bk=SimpleNamespace(get_job=lambda _j: job),
        delegated_ok=lambda _u, _s: delegated,
        page=lambda _r, _t, _s, status=200, **kw: HTMLResponse(json.dumps(kw["values"]), status_code=status),
    )
    app = FastAPI()
    for path, (name, data) in files.items():

        def give(name: str = name, data: bytes = data) -> Response:
            return Response(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})

        app.get(path)(give)
    egress_page.register(app, h)
    return TestClient(app), audit


CHART = b"MRN,n\n70000054,1\n"


def test_a_download_is_masked_at_the_console_s_edge() -> None:
    c, audit = _console({"/studies/RA01/export.csv": ("70000054.csv", CHART)})
    r = c.get("/studies/RA01/export.csv")
    assert r.status_code == 200 and "70000054" not in r.text and "70000054" not in str(r.headers)
    assert int(r.headers["content-length"]) == len(r.content)
    assert audit.lines[-1]["detail"]["route"] == "download.study" and audit.lines[-1]["actor"] == "console:crc"


def test_an_attachment_no_rule_lists_is_refused() -> None:
    c, audit = _console({"/new/export": ("a.csv", b"a\n1\n")})
    r = c.get("/new/export")
    assert r.status_code == 409 and "a\n1" not in r.text
    assert audit.lines[-1]["detail"]["reason"] == "no_rule"


@pytest.mark.parametrize(
    ("tag", "mailbox", "delegated", "status"),
    [("phi", "crc@hosp.example", True, 200), ("phi", "other@hosp.example", True, 409),
     ("phi", "crc@hosp.example", False, 409), ("phi", "", True, 409), ("secret", "x@hosp.example", True, 409)],
)  # fmt: skip
def test_a_patient_file_goes_to_its_named_recipient_on_the_log(
    tag: str, mailbox: str, delegated: bool, status: int
) -> None:
    path = "/pilot/jobs/01HZ/files/f.csv"
    c, _ = _console({path: ("f.csv", CHART)}, tag, mailbox, delegated)
    r = c.get(path)
    assert r.status_code == status and ("70000054" in r.text) == (status == 200)


def test_an_aggregate_job_file_is_masked() -> None:
    path = "/pilot/jobs/01HZ/files/f.csv"
    c, _ = _console({path: ("f.csv", CHART)})
    assert c.get(path).status_code == 200 and "70000054" not in c.get(path).text


# ------------------------------------------------------------------------------------------------ the doctor
def test_the_doctor_names_every_route_and_what_is_not_wired(tmp_path: Path) -> None:
    rows = {k: s for k, s, _t in ee.doctor_checks({}, tmp_path)}
    assert set(rows) == {f"egress.{k}" for k in ee.ROUTES} | {"egress.tripwire"}
    assert {s for k, s in rows.items() if k != "egress.tripwire"} == {"WARN"}  # nothing here to read: not a FAIL
    (tmp_path / "services/console").mkdir(parents=True)
    (tmp_path / "services/console/app.py").write_text("nothing")
    rows = {k: s for k, s, _t in ee.doctor_checks({}, tmp_path)}
    assert rows["egress.download.study"] == "FAIL"


def test_every_door_outside_the_console_is_wired_in_this_tree() -> None:
    """The console's line is in ``console/app.py`` (F0's): until it is there the doctor says FAIL for its routes."""
    assert {k for k in ee.ROUTES if ee.wired(k) is not True} <= {
        k for k, r in ee.ROUTES.items() if r.door == ee._CONSOLE
    }


# ------------------------------------------------------------------------------------------------ the code scan
#: a call that sends, by its shape in the source
SEND = re.compile(
    r"smtplib\.SMTP(?:_SSL)?\(|send_message\(|guarded_client\(|httpx\.(?:post|put|request|stream)\(|urlopen\(|"
    r"requests\.(?:post|put)\(|self\.transport\("
)
ATTACHMENT = re.compile(r"(?i)content.disposition")
#: files that send: how each is behind the edge, or why nothing of a patient can be in it
SENDERS = {
    "services/mail_gateway/gateway.py": "gate_mail, mail.reply",
    "services/mail_gateway/outbound.py": "the transport gateway.py hands the gated mail to",
    "services/console/backend.py": "mail.test",
    "services/rc_bridge/client.py": "on_leave: edc.write",
    "services/orchestrator/scenarios/submit.py": "nhi.submit",
    "services/criteria_compiler/ctgov.py": "a public registry is read by its own id; nothing is sent",
    "services/console/oidc.py": "the sign-in provider: a code and a token",
    "libs/tb_common/http.py": "the guarded client itself and the box's own services",
}


def _code() -> list[Path]:
    return sorted(p for d in ("services", "libs") for p in (ROOT / d).rglob("*.py") if "rc_sim" not in p.parts)


def _strip(text: str) -> str:
    """The source without its docstrings and comments."""
    tree = ast.parse(text)
    return ast.unparse(tree) if tree.body else ""


def test_every_outward_send_is_listed_and_goes_through_the_edge() -> None:
    found = {p.relative_to(ROOT).as_posix() for p in _code() if SEND.search(_strip(p.read_text(encoding="utf-8")))}
    assert found - set(SENDERS) == set(), "a new direct send: route it through egress_edge.leave"


def test_every_file_the_console_gives_is_in_the_download_rules() -> None:
    """Draft #1295's 28 download sites: each console route that sets an attachment has a rule (else it is refused)."""
    paths = set()
    for p in (ROOT / "services/console").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            body = ast.get_source_segment(text, fn) or ""
            if not (ATTACHMENT.search(body) or "content_disposition_type" in body):
                continue
            for dec in fn.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "get" and dec.args:
                    arg = dec.args[0]
                    if isinstance(arg, ast.Constant):
                        paths.add(str(arg.value))
    assert len(paths) >= 15
    unlisted = {x for x in paths if not ee.download_route(re.sub(r"\{[^}]+\}", "x", x))[0]}
    assert unlisted == set()


# ------------------------------------------------------------------------------------------------ OCR 1523-3: containers
LIST = b"mrn,name\n70000054,Robin Example\n"


def _zip_of(members: dict[str, bytes], comment: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
        z.comment = comment
    return buf.getvalue()


def _office(more: dict[str, bytes]) -> bytes:
    return _zip_of({"[Content_Types].xml": b"<Types/>", **more})


def _book(more: dict[str, bytes] | None = None) -> bytes:
    """A real workbook with members added to it."""
    from openpyxl import Workbook

    buf = io.BytesIO()
    Workbook().save(buf)
    with zipfile.ZipFile(buf, "a") as z:
        for n, d in (more or {}).items():
            z.writestr(n, d)
    return buf.getvalue()


def _pdf(attached: bytes = b"", field: str = "", note: str = "") -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import FreeText
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 700, "12 of 85 patients")
    c.save()
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    if attached:
        w.add_attachment("list.csv", attached)
    if field:
        f = DictionaryObject({NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject("a"),
                              NameObject("/V"): TextStringObject(field)})  # fmt: skip
        form = DictionaryObject({NameObject("/Fields"): ArrayObject([w._add_object(f)])})
        w._root_object[NameObject("/AcroForm")] = w._add_object(form)
    if note:
        w.add_annotation(0, FreeText(text=note, rect=(10, 10, 90, 90)))
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _twice() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", b"MRN: 70000054")
        with pytest.warns(UserWarning):
            z.writestr("a.txt", b"hello")
    return buf.getvalue()


UNREAD: dict[str, tuple[str, bytes]] = {
    "content_types_beside_a_list": ("a.zip", _office({"notes.txt": b"MRN: 70000054\n"})),
    "office_embedded_list": ("a.docx", _office({"word/embedded/list.csv": LIST})),
    "office_embedded_zip": ("a.docx", _office({"word/embedded/a.bin": _zip_of({"list.csv": LIST})})),
    "a_list_called_a_picture": ("a.docx", _office({"word/media/image1.png": LIST})),
    "a_list_called_xml": ("a.docx", _office({"word/a.xml": b"MRN: 70000054"})),
    "office_link": ("a.docx", _office({"word/_rels/a.rels": b'<R Target="mailto:robin@mail.example"/>'})),
    "office_member_name": ("a.docx", _office({"word/MRN 70000054.xml": b"<a/>"})),
    "zip_comment": ("a.zip", _zip_of({"a.txt": b"hello"}, comment=b"MRN: 70000054")),
    "workbook_theme_list": ("a.xlsx", _book({"xl/theme/list.csv": LIST})),
    "workbook_sheet_list": ("a.xlsx", _book({"xl/worksheets/sheet2.txt": b"MRN: 70000054"})),
    "pdf_attachment": ("a.pdf", _pdf(attached=LIST)),
    "pdf_form_value": ("a.pdf", _pdf(field="MRN: 70000054")),
    "pdf_note": ("a.pdf", _pdf(note="MRN: 70000054")),
}


@pytest.mark.parametrize("case", sorted(UNREAD))
def test_what_a_container_holds_beside_its_text_is_read_too(case: str) -> None:
    name, data = UNREAD[case]
    assert reason("download.study", ee.File(name, data)) == "identifiers"


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.docx", _office({"word/a.xml": "<a>MRN: 70000054</a>".encode("utf-16")})),
        ("a.docx", _office({"word/a.xml": "<a>MRN: 70000054</a>".encode("utf-16-le")})),
        ("a.xlsm", _book({"xl/vbaProject.bin": b"\xd0\xcf\x11\xe0\x00MRN: 70000054"})),
        ("a.xlsx", _book({"xl/worksheets/sheet9.xml": b"<s><c><v>70000054</v></c></s>"})),
        ("a.zip", _twice()),
    ],
    ids=["utf16", "utf16_no_mark", "macro", "a_sheet_no_book_lists", "two_members_of_one_name"],
)
def test_what_cannot_be_read_in_a_container_does_not_leave(name: str, data: bytes) -> None:
    assert reason("download.study", ee.File(name, data)) == "unreadable"


_CLEAN = {"word/document.xml": b"<w:p>hi</w:p>", "word/_rels/a.rels": b'<R Target="a.xml"/>'}


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.docx", _office({**_CLEAN, "word/media/image1.png": b"\x89PNG\r\n\x1a\n\x00\x00", "word/a/": b""})),
        ("a.docx", _office({"word/document.xml": b"\xef\xbb\xbf<w:p>hi</w:p>", "word/e/list.csv": b"n\n3\n"})),
        ("a.xlsx", _book()),
        ("a.pdf", _pdf(attached=b"n\n3\n", field="yes", note="a clean note")),
        ("a.pdf", _pdf()),
    ],
    ids=["office_picture", "office_clean_list", "workbook", "pdf_clean_parts", "pdf"],
)
def test_a_clean_container_still_leaves_as_it_is(name: str, data: bytes) -> None:
    f = ee.File(name, data)
    assert ee.leave("download.study", "x", f, audit=Audit(), actor="t") == f


# ------------------------------------------------------------------------------------------------ OCR 1523-5: a range
@pytest.mark.parametrize("path", ["/admin/ops/network/{name}", "/new/{name}"])
def test_a_range_request_does_not_take_a_download_past_the_edge(tmp_path: Path, path: str) -> None:
    """A file answer to a request with a Range header answered 206 with the file's own bytes, and the layer held only
    a 200."""
    from fastapi.responses import FileResponse

    sheet = tmp_path / "sheet.md"
    sheet.write_bytes(b"MRN: 70000054\n")
    c, _ = _console({})
    c.app.get(path)(lambda name: FileResponse(sheet, filename=name, content_disposition_type="attachment"))
    asks: list[dict[str, str]] = [{}, {"Range": "bytes=0-"}, {"Range": "bytes=5-"}, {"Range": "bytes=0-4,5-"}]
    for ask in asks:
        r = c.get(path.replace("{name}", "sheet.md"), headers=ask)
        assert r.status_code in (200, 409) and b"70000054" not in r.content, (ask, r.status_code)


def test_a_door_named_in_a_comment_only_is_not_wired(tmp_path: Path) -> None:
    """OCR 1523-14: the doctor looks for the call, not for its name in a comment or a docstring."""
    (tmp_path / "services/gateway").mkdir(parents=True)
    door = tmp_path / "services/gateway/core.py"
    door.write_text('"""leaves by "model.offbox" ."""\n# leave("model.offbox")\n')
    assert ee.wired("model.offbox", tmp_path) is False
    door.write_text('leave("model.offbox")\n')
    assert ee.wired("model.offbox", tmp_path) is True
