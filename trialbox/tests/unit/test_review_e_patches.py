"""H-137: the fixes an outside review ("model E") suggested, each checked on master and written anew.

One test per fix, each failing on master before its fix. Synthetic data only: made-up tokens, keys, pseudonyms and
chart numbers; no database (the data core is the in-memory one), no network beyond 127.0.0.1.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import stat
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import model_guard as mg
import pytest
from console.auth import Session, csrf_ok
from datacore.forms import Field
from edc import prefill
from edc_backend import events, linkmap, oidc
from edc_backend.config import load_config

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user

TOKEN_A = "A" * 32
TOKEN_B = "B" * 32
PID = "c" * 32  # a made-up pseudonym


# ------------------------------------------------------------------------------------- 1. edc_backend/oidc.py
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token_under(key: bytes, sub: str, aud: str) -> str:
    head = _b64(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64(json.dumps({"sub": sub, "aud": aud, "exp": 9_999_999_999}).encode())
    return f"{head}.{body}.{_b64(hmac.new(key, f'{head}.{body}'.encode(), hashlib.sha256).digest())}"


def test_an_empty_oidc_client_secret_neither_signs_nor_verifies_a_token() -> None:
    env = {"TB_EDC_OIDC": "1", "TB_EDC_OIDC_CLIENT_ID": "edc", "TB_EDC_OIDC_CLIENT_SECRET": ""}
    assert oidc.subject_of(_token_under(b"", "admin", "edc"), env) is None  # anyone can compute an empty-key HMAC
    with pytest.raises(ValueError):
        oidc.sign_id_token("crc", env)
    env["TB_EDC_OIDC_CLIENT_SECRET"] = "synthetic-oidc-secret"
    assert oidc.subject_of(oidc.sign_id_token("crc", env), env) == "crc"
    assert oidc.subject_of(_token_under(b"", "admin", "edc"), env) is None


# --------------------------------------------------------------------------------------------- 2. edc/prefill.py
def test_a_drafted_number_is_not_shown_by_a_quote_of_fewer_digits() -> None:
    hr = Field(name="hr", form="vs", kind="integer", label="HR")
    assert prefill._value_in_quote(hr, "70", "HR 70 bpm")
    assert not prefill._value_in_quote(hr, "70", "HR 7 bpm")  # 70 is not 7
    assert not prefill._value_in_quote(hr, "100", "HR 1 bpm")
    assert not prefill._value_in_quote(hr, "0", "HR 72 bpm")  # zero is not every quote
    assert not prefill._value_in_quote(hr, "", "HR 72 bpm")  # nor is an empty value
    t = Field(name="t", form="vs", kind="decimal", label="T")
    assert prefill._value_in_quote(t, "7.0", "pH 7 today")  # a decimal's trailing zeros may go
    assert prefill._value_in_quote(t, "7.50", "pH 7.5 today")
    assert prefill._value_in_quote(t, "0.0", "drain 0 ml")
    assert not prefill._value_in_quote(t, "10", "pH 1 today")
    assert not prefill._value_in_quote(t, "0.0", "pH 7.4 today")


# --------------------------------------------------------------------------------------- 3. edc_backend/events.py
def test_a_non_ascii_event_signature_is_refused_not_raised() -> None:
    assert events.signature_ok("s3cret", b"{}", "sha256=" + "é" * 64) is False
    assert events.signature_ok("s3cret", b"{}", "sha256=zz") is False
    good = hmac.new(b"s3cret", b"{}", hashlib.sha256).hexdigest()
    assert events.signature_ok("s3cret", b"{}", "sha256=" + good) is True
    assert events.signature_ok("other,s3cret", b"{}", "sha256=" + good.upper()) is True


# --------------------------------------------------------------------------------------- 4. edc_backend/config.py
def test_the_short_token_alias_never_overrides_the_tb_setting() -> None:
    base = {"TB_EDC_BACKEND": "redcap", "TB_REDCAP_API_URL": "https://redcap.example/"}
    cfg = load_config(
        {**base, "TB_REDCAP_TOKEN_gzqo": TOKEN_B, "REDCAP_TOKEN_gzqo": TOKEN_A, "REDCAP_TOKEN_rabio": TOKEN_A}
    )
    assert cfg.token_for("gzqo") == TOKEN_B  # docs/data/13: the shorter name works when the TB_ one is empty
    assert cfg.token_for("rabio") == TOKEN_A
    cfg = load_config({**base, "TB_REDCAP_PROJECT_TOKENS": f"gzqo:{TOKEN_B}", "REDCAP_TOKEN_gzqo": TOKEN_A})
    assert cfg.token_for("gzqo") == TOKEN_B


# -------------------------------------------------------------------------------------- 5. edc_backend/linkmap.py
def test_a_failed_link_map_save_keeps_the_saved_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = str(tmp_path / "edc")
    linkmap.save(folder, {"studies": {"GZQO": "17"}, "subjects": {"GZQO": {"1": "SYN-001"}}})
    first = os.stat(linkmap.map_path(folder)).st_ino
    linkmap.save(folder, {"studies": {"GZQO": "17", "RABIO": "18"}})
    assert os.stat(linkmap.map_path(folder)).st_ino != first  # a new file renamed over, never rewritten in place
    with pytest.raises(UnicodeEncodeError):  # a lone surrogate, as a JSON body's "\ud800" escape gives
        linkmap.save(folder, {"studies": {"GZQO": "17"}, "subjects": {"GZQO": {"1": "SYN-\ud800"}}})
    assert linkmap.load(folder)["studies"] == {"GZQO": "17", "RABIO": "18"}
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", synced.append)
    linkmap.save(folder, {"studies": {"GZQO": "17", "RABIO": "18", "TBX": "19"}})
    assert len(synced) == 2  # the file, then the folder that holds the rename

    def full(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", full)  # the disk fills while the new map is written
    with pytest.raises(OSError):
        linkmap.save(folder, {"studies": {"GZQO": "99"}})
    assert linkmap.load(folder)["studies"] == {"GZQO": "17", "RABIO": "18", "TBX": "19"}
    assert sorted(p.name for p in linkmap.map_path(folder).parent.iterdir()) == [linkmap.map_path(folder).name]


def test_the_link_map_is_never_readable_by_group_or_others(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = str(tmp_path / "edc")
    path = linkmap.map_path(folder)
    seen: list[int] = []
    real_chmod = os.chmod

    def chmod(target: Any, mode: int, *a: Any, **k: Any) -> None:
        if path.exists():  # the map as any other reader could open it at this moment
            seen.append(stat.S_IMODE(os.stat(path).st_mode))
        real_chmod(target, mode, *a, **k)

    monkeypatch.setattr(os, "chmod", chmod)
    old = os.umask(0o022)
    try:
        linkmap.save(folder, {"studies": {"GZQO": "17"}})
    finally:
        os.umask(old)
    assert all(m & 0o077 == 0 for m in seen), [oct(m) for m in seen]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


# -------------------------------------------------------------------------------- 6. orchestrator/datacore_api.py
def test_a_pseudonym_entered_by_put_is_the_record_every_other_route_reads(tmp_path: Path) -> None:
    from tests.unit.test_datacore_api import _api

    c, _ = _api(tmp_path)
    r = c.put(f"/studies/GZQO/data/{PID.upper()}", json={"values": {"tb_status": "2"}, "by": "crc"})
    assert r.status_code == 200, r.text
    assert r.json()["record"] == {"tb_status": "2"}
    got = c.get(f"/studies/GZQO/records/{PID}")
    assert got.status_code == 200, got.text
    assert got.json()["record"] == PID and got.json()["values"], got.json()  # the one record, in lower case
    assert c.put("/studies/GZQO/data/gzqo-0043", json={"values": {"tb_status": "1"}, "by": "crc"}).status_code == 200
    assert c.get("/studies/GZQO/records/gzqo-0043").json()["record"] == "GZQO-0043"  # a screening number: upper


# --------------------------------------------------------------------------------------- 7. console/audit_page.py
def test_the_audit_report_file_hides_a_disclosure_lookups_pseudonym(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from console.backend import Unavailable

    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        if path == "/setup/pseudonym":
            return {"pid": PID, "known": True}
        raise Unavailable("no study store in this test")

    monkeypatch.setattr(box["backend"], "study_api", study_api, raising=False)
    box["app"].state.helpers.au.append("console.reveal", actor="console:crc", detail={"pid": PID, "purpose": "contact"})
    dpo = _user(box, "dpo1", "privacy")
    r = dpo.post("/audit/patients/by-chart", data={"csrf": _csrf(dpo.get("/audit").text), "chart_no": "SYN-0001"})
    assert r.status_code == 200, r.text[-300:]
    page = dpo.get(f"/audit/patients/{PID}").text
    csv = dpo.get(f"/audit/patients/{PID}/report.csv")
    assert csv.status_code == 200
    lookups = [line for line in csv.text.splitlines() if "console.chart_lookup" in line]
    assert lookups, csv.text[:600]
    assert all(PID not in line for line in lookups), lookups  # as the page shows it (shown_to)
    assert "console.chart_lookup" in page or "chart" in page
    reveal = [line for line in csv.text.splitlines() if "console.reveal" in line]
    assert reveal and PID in reveal[0]  # a reader with audit.ids still sees the other events' pseudonym


# ---------------------------------------------------------------------------------------------- 8. console/auth.py
def test_a_non_ascii_csrf_value_is_refused_not_raised() -> None:
    sess = cast(Session, SimpleNamespace(csrf="synthetic-csrf-value"))
    assert csrf_ok(sess, "synthetic-csrf-value") is True
    assert csrf_ok(sess, "synthetic-csrf-valué") is False
    assert csrf_ok(sess, "") is False and csrf_ok(sess, None) is False


# ---------------------------------------------------------------------------------------------- 9. adapter/app.py
@pytest.mark.parametrize("snap", ["..", "../outside", "a/b", "..\\outside", "x\x00y"])
def test_a_snapshot_name_never_leaves_the_lake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snap: str) -> None:
    from adapter.app import app
    from fastapi.testclient import TestClient

    lake = tmp_path / "lake"
    (lake / "ndjson" / "2026-11-24").mkdir(parents=True)
    (lake / "outside").mkdir()
    (lake / "ndjson" / "a" / "b").mkdir(parents=True)
    monkeypatch.setenv("TB_LAKE_DIR", str(lake))
    c = TestClient(app)
    assert c.post("/$validate", json={"snapshot": snap}).status_code == 400
    assert c.post("/publish", json={"snapshot": snap}).status_code == 400
    assert c.post("/$validate", json={"snapshot": "2026-11-24"}).status_code == 200


# --------------------------------------------------------------------------------------- 10. model_guard/__init__.py
KEY = "guard-key-0123456789"


class _Upstream(BaseHTTPRequestHandler):
    """A keep-alive model server (HTTP/1.1, as the real one): records every request it parses."""

    protocol_version = "HTTP/1.1"
    seen: ClassVar[list[str]] = []

    def _any(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _Upstream.seen.append(f"{self.command} {self.path}")
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST = _any

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture()
def guard_port() -> Iterator[int]:
    _Upstream.seen = []
    up = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    g = mg.Guard(KEY, {"llm-service": ("127.0.0.1", up.server_address[1])})
    gs = ThreadingHTTPServer(("127.0.0.1", 0), mg.make_handler(g))
    threading.Thread(target=gs.serve_forever, daemon=True).start()
    yield gs.server_address[1]
    gs.shutdown()
    up.shutdown()


def _raw(port: int, head: str, body: bytes) -> tuple[bytes, bool]:
    """The status line of the guard's answer, and whether the guard closed the connection after it."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(head.encode() + body)
        got = b""
        s.settimeout(3)
        try:
            while chunk := s.recv(4096):
                got += chunk
            closed = True
        except TimeoutError:
            closed = False
    return got.split(b"\r\n", 1)[0], closed


def _head(*fields: str) -> str:
    lines = ["GET /v1/models HTTP/1.1", "Host: llm-service:8000", f"Authorization: Bearer {KEY}", *fields]
    return "\r\n".join(lines) + "\r\n\r\n"


def test_a_request_with_two_content_lengths_is_refused(guard_port: int, capsys: pytest.CaptureFixture[str]) -> None:
    hidden = b"GET /smuggled HTTP/1.1\r\nHost: x\r\n\r\n"
    body = b"{}" + hidden
    status, closed = _raw(guard_port, _head(f"Content-Length: {len(body)}", "Content-Length: 2"), body)
    assert b" 400 " in status, status
    assert closed  # RFC 9112 6.3: an unrecoverable framing error; the connection is not used again
    assert _Upstream.seen == []
    err = capsys.readouterr().err
    assert "refused GET: more than one Content-Length" in err, err
    assert "smuggled" not in err  # the refusal is logged without the body


def test_one_content_length_is_forwarded(guard_port: int) -> None:
    status, _ = _raw(guard_port, _head("Content-Length: 2"), b"{}")
    assert b" 200 " in status, status
    assert _Upstream.seen == ["GET /v1/models"]


def test_transfer_encoding_beside_content_length_is_refused_and_the_connection_closed(guard_port: int) -> None:
    """RFC 9112 6.1: a server may refuse a request with both, and must close the connection after answering it.
    The guard refuses it (it refuses any Transfer-Encoding: it reads bodies by length only)."""
    status, closed = _raw(guard_port, _head("Transfer-Encoding: chunked", "Content-Length: 2"), b"2\r\n{}\r\n0\r\n\r\n")
    assert b" 400 " in status, status
    assert closed
    assert _Upstream.seen == []
