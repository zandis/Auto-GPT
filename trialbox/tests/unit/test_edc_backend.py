"""The selectable EDC backend (D-915): REDCap or an internal service with the same API.

Fixtures under tests/fixtures/redcap_api mimic the documented JSON. The simulator stands in for a server.
Nothing here is imported by the demo: connect() with no TB_EDC_BACKEND returns None.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from edc_backend.config import EdcConfigError, load_config
from edc_backend.connection import EdcConnection, connect, copy_records
from edc_backend.mapping import map_project
from fastapi.testclient import TestClient
from rc_bridge.client import RcError, RedcapClient, _attachment_name, error_marker, major_of, register_local
from rc_sim.app import create_app

from tests.rc_kit import TOKEN_A, TOKEN_B

pytestmark = pytest.mark.nodb

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "redcap_api"
METADATA = json.loads((FIXTURES / "metadata.json").read_text(encoding="utf-8"))
RECORDS = json.loads((FIXTURES / "records.json").read_text(encoding="utf-8"))


def _open(env: dict[str, str], http: httpx.Client, *, at_root: bool = False) -> EdcConnection:
    """``at_root`` points the client at the TestClient's ``/api/`` instead of an absolute URL."""
    conn = connect(env, http=http)
    assert conn is not None
    if at_root:
        conn.client.url = "/api/"
    return conn


def _env(**extra: str) -> dict[str, str]:
    base = {
        "TB_EDC_BACKEND": "redcap",
        "TB_REDCAP_API_URL": "https://rc.example/api/",
        "TB_REDCAP_API_TOKEN": TOKEN_A,
    }
    base.update(extra)
    return base


def test_unset_backend_connects_nothing() -> None:
    assert connect({}) is None
    assert "TOKEN" not in repr(load_config({}))


def test_a_redcap_url_must_be_https_and_loopback_http_is_only_for_internal() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    with httpx.Client(transport=transport) as http:
        with pytest.raises(RcError):
            connect(_env(TB_REDCAP_API_URL="http://redcap.example/"), http=http)
        with pytest.raises(RcError):
            connect(_env(TB_REDCAP_API_URL="http://10.1.1.5/"), http=http)
        internal = {
            "TB_EDC_BACKEND": "internal",
            "TB_EDC_INTERNAL_URL": "http://10.1.1.5/",
            "TB_EDC_INTERNAL_TOKEN": TOKEN_A,
        }
        with pytest.raises(RcError):
            connect(internal, http=http)
        with pytest.raises(RcError):
            connect({**internal, "TB_EDC_INTERNAL_URL": "http://user:pw@127.0.0.1:8792/"}, http=http)
        conn = connect({**internal, "TB_EDC_INTERNAL_URL": "http://127.0.0.1:8792"}, http=http)
        assert conn is not None and conn.kind == "internal"
        assert conn.client.url == "http://127.0.0.1:8792/api"
        assert "TOKEN" not in repr(conn) and TOKEN_A not in repr(conn)


def test_project_tokens_and_the_short_names() -> None:
    cfg = load_config(
        {
            "EDC_BACKEND": "external",
            "REDCAP_API_URL": "https://redcap.example/",
            "REDCAP_API_TOKEN": TOKEN_A,
            "TB_REDCAP_PROJECT_TOKENS": f"other:{TOKEN_A}",
            "TB_REDCAP_TOKEN_gzqo": TOKEN_B,
            "REDCAP_TOKEN_rabio": TOKEN_A,
        }
    )
    assert cfg.kind == "redcap" and cfg.url == "https://redcap.example/"
    assert cfg.token_for(None) == TOKEN_A
    assert cfg.token_for("gzqo") == TOKEN_B  # the prefixed name wins over the list
    assert cfg.token_for("RABIO") == TOKEN_A
    assert TOKEN_A not in repr(cfg) and TOKEN_B not in repr(cfg)
    with pytest.raises(EdcConfigError):
        cfg.token_for("missing")
    with pytest.raises(EdcConfigError):
        connect({"TB_EDC_BACKEND": "redcap", "TB_REDCAP_API_URL": "https://redcap.example/"})


def test_version_13_is_accepted_by_the_backend_and_still_refused_by_the_study_link() -> None:
    app = create_app(version="13.7.23")
    http = TestClient(app, base_url="http://rc")
    conn = _open(_env(), http, at_root=True)
    assert conn.ensure_version() == "13.7.23"
    link = RedcapClient("https://rc.example/", TOKEN_A, http=TestClient(app, base_url="http://rc"))
    link.url = "/api/"
    with pytest.raises(RcError) as err:
        link.check_version()
    assert err.value.code == "RC-VERSION"


def test_dictionary_maps_to_questionnaires_and_identifier_fields_are_blanked_on_export() -> None:
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        seen.append(form)
        assert TOKEN_A not in (request.url.query.decode() if request.url.query else "")
        content = form["content"][0]
        if content == "record":
            assert form["events[0]"] == ["screening_arm_1"]
            assert form["fields[0]"] == ["eligible"]
            return httpx.Response(200, json=RECORDS)
        if content == "metadata":
            return httpx.Response(200, json=METADATA)
        raise AssertionError(content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        rows = _open(_env(), http).export_records(fields=["eligible"], events=["screening_arm_1"])
    assert rows[0]["mrn"] == "" and rows[0]["eligible"] == "1"
    assert rows[1]["redcap_repeat_instrument"] == "adverse_event"
    assert rows[1]["redcap_repeat_instance"] == "1"
    assert seen[0]["token"] == [TOKEN_A]
    mapped = map_project(
        "GZQO",
        METADATA,
        project={"project_id": 7, "project_title": "synthetic", "is_longitudinal": 1},
        events=[{"unique_event_name": "screening_arm_1", "arm_num": 1}],
        repeating=[{"event_name": "screening_arm_1", "form_name": "adverse_event"}],
    )
    assert mapped["identifiers_not_stored"] == ["mrn"]
    assert [item["name"] for item in mapped["instruments"]] == ["screening", "adverse_event"]
    link_ids = [item["linkId"] for q in mapped["questionnaires"] for item in q["item"]]
    assert "mrn" not in link_ids and "icf_dt" in link_ids
    assert mapped["visits"][0]["unique_event_name"] == "screening_arm_1"
    assert mapped["crosswalk"]["omop"] and mapped["crosswalk"]["cdisc"] and mapped["crosswalk"]["fhir"]


def test_a_refused_token_is_not_repeated_and_the_client_cap_stops_the_second_call() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, json={"error": f"refused {TOKEN_A}"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        conn = _open(_env(TB_REDCAP_MAX_PER_MINUTE="1"), http)
        with pytest.raises(RcError) as err:
            conn.project()
        assert err.value.code == "RC-TOKEN" and TOKEN_A not in str(err.value)
        with pytest.raises(RcError) as limited:
            conn.project()
        assert limited.value.code == "RC-RATE" and calls["n"] == 1


def test_dictionary_import_sends_the_csv_and_copy_blanks_identifiers() -> None:
    csv_text = "field_name,form_name\nrecord_id,screening\n"
    captured: dict[str, Any] = {}

    def source(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        content = form["content"][0]
        if content == "record":
            return httpx.Response(200, json=RECORDS)
        if content == "metadata":
            return httpx.Response(200, json=METADATA)
        raise AssertionError(content)

    def dest(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        captured["content"] = form["content"][0]
        captured["format"] = form.get("format", [""])[0]
        captured["data"] = form.get("data", [""])[0]
        if form["content"][0] == "metadata":
            return httpx.Response(200, json=2)
        body = json.loads(form["data"][0])
        captured["rows"] = body
        return httpx.Response(200, json=["1"])

    with (
        httpx.Client(transport=httpx.MockTransport(source)) as src_http,
        httpx.Client(transport=httpx.MockTransport(dest)) as dst_http,
    ):
        src = _open(_env(), src_http)
        dst = _open(_env(TB_REDCAP_API_TOKEN=TOKEN_B), dst_http)
        assert dst.import_dictionary(csv_text) == 2
        copied = copy_records(src, dst)
    assert captured["format"] == "json"  # the record import is the last call
    assert captured["rows"][0]["mrn"] == ""
    assert copied == {"rows": 2, "records": 1}
    # the dictionary call was the first destination request; check it by importing again on a fresh capture
    seen: dict[str, str] = {}

    def only_dict(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        seen["format"] = form["format"][0]
        seen["data"] = form["data"][0]
        assert form["token"][0] == TOKEN_B
        return httpx.Response(200, json=1)

    with httpx.Client(transport=httpx.MockTransport(only_dict)) as http:
        _open(_env(TB_REDCAP_API_TOKEN=TOKEN_B), http).import_dictionary(csv_text)
    assert seen == {"format": "csv", "data": csv_text}


def test_simulator_file_round_trip_survey_link_and_instruments() -> None:
    app = create_app()
    http = TestClient(app, base_url="http://rc")
    made = http.post(
        "/sim/projects",
        json={
            "title": "uploads",
            "metadata": [
                {"field_name": "record_id", "form_name": "upload", "field_type": "text", "field_label": "Record"},
                {"field_name": "scan", "form_name": "upload", "field_type": "file", "field_label": "Scan"},
            ],
        },
    ).json()
    conn = _open(_env(TB_REDCAP_API_TOKEN=made["token"]), http, at_root=True)
    conn.import_file("1", "scan", "note.txt", b"synthetic")
    body, name = conn.export_file("1", "scan")
    assert (body, name) == (b"synthetic", "note.txt")
    conn.delete_file("1", "scan")
    with pytest.raises(RcError) as err:
        conn.export_file("1", "scan")
    assert err.value.code == "RC-UPSTREAM" and "synthetic" not in str(err.value)
    conn.import_file("1", "scan", "../secret.txt", b"x")  # the path is dropped; the base name is sent
    assert conn.export_file("1", "scan") == (b"x", "secret.txt")
    with pytest.raises(RcError):
        conn.import_file("1", "scan", "a\nb.txt", b"x")
    names = [row["instrument_name"] for row in conn.instruments()]
    assert names == ["upload"]
    link = conn.survey_link("1", "upload")
    assert link == "http://127.0.0.1/surveys/?s=sim" and made["token"] not in link
    conn.file_max_bytes = 4
    with pytest.raises(RcError) as too_big:
        conn.import_file("1", "scan", "note.txt", b"abcdef")
    assert "larger" in too_big.value.message


def test_repeat_instance_new_needs_17_4() -> None:
    old = create_app(version="13.7.23")
    http = TestClient(old, base_url="http://rc")
    made = http.post(
        "/sim/projects",
        json={
            "title": "files",
            "metadata": [
                {"field_name": "record_id", "form_name": "upload", "field_type": "text"},
                {"field_name": "scan", "form_name": "upload", "field_type": "file"},
            ],
        },
    ).json()
    conn = _open(_env(TB_REDCAP_API_TOKEN=made["token"]), http, at_root=True)
    with pytest.raises(RcError) as err:
        conn.import_file("1", "scan", "note.txt", b"a", repeat_instance="new")
    assert "not recognized" in err.value.message or err.value.code == "RC-UPSTREAM"
    new = create_app(version="17.4.0")
    http2 = TestClient(new, base_url="http://rc")
    made2 = http2.post(
        "/sim/projects",
        json={
            "title": "files",
            "metadata": [
                {"field_name": "record_id", "form_name": "upload", "field_type": "text"},
                {"field_name": "scan", "form_name": "upload", "field_type": "file"},
            ],
        },
    ).json()
    conn2 = _open(_env(TB_REDCAP_API_TOKEN=made2["token"]), http2, at_root=True)
    conn2.import_file("1", "scan", "note.txt", b"a", repeat_instance="new")
    body, _name = conn2.export_file("1", "scan", repeat_instance="1")
    assert body == b"a"


def test_a_classic_project_has_no_events_and_a_bare_file_call_is_still_refused() -> None:
    app = create_app()
    http = TestClient(app, base_url="http://rc")
    conn = _open(_env(), http, at_root=True)
    assert conn.events() == [] and conn.arms() == [] and conn.repeating() == []
    assert {row["instrument_name"] for row in conn.instruments()} >= {"screening"}
    client = conn.client
    with pytest.raises(RcError) as err:
        client._post("file")
    assert (err.value.code, err.value.status) == ("RC-UPSTREAM", 502)


def test_the_client_refuses_a_bad_answer_and_reads_the_extra_calls() -> None:
    """The lists, the survey link and the schedule import, and the answers that are not what the client asked for."""
    assert error_marker("classic projects") == "classic"
    assert error_marker("no repeating instruments") == "repeat"
    assert error_marker("a form is locked") == ""
    with pytest.raises(ValueError):
        register_local("https://rc.example", lambda: None)
    with pytest.raises(RcError):
        major_of("nope")
    assert _attachment_name('attachment; filename="note.txt"') == "note.txt"
    assert _attachment_name('inline; filename="a*b"') == "upload.bin"
    assert _attachment_name("") == "upload.bin"
    with pytest.raises(RcError, match="no in-process"):
        RedcapClient("inproc://not-a-simulator", TOKEN_A)
    owned = RedcapClient("https://rc.example/", TOKEN_A, declare_host=True)
    owned.close()

    app = create_app()
    http = TestClient(app, base_url="http://rc")
    client = RedcapClient("https://rc.example/", TOKEN_A, http=http)
    client.url = "/api/"
    assert client.users() == []
    assert client.import_records([]) == []
    assert client.import_arms([]) == {"count": 0}
    with pytest.raises(RcError):
        client.report("")
    with pytest.raises(RcError) as err:
        client.report("9")
    assert err.value.refused
    assert client.project_log("record", "2026-01-01 00:00", "2026-12-31 00:00") == []
    with pytest.raises(RcError):
        client.survey_link("", "")
    assert client.survey_link("1", "screening", event="screening_arm_1", repeat_instance="1").startswith("http")
    with pytest.raises(RcError):
        client.import_metadata("  ")
    with pytest.raises(RcError):
        client.export_file("1", "Not A Field")
    with pytest.raises(RcError, match="not usable"):
        client.export_file("a\nb", "record_id")
    with pytest.raises(RcError):
        client.export_file("1", "record_id", event="screening_arm_1")
    assert client.import_repeating([{"event_name": "", "form_name": "screening"}])["count"] == 1
    raw = http.post("/api/", data={"token": TOKEN_A, "content": "arm", "format": "json", "data": "not-json"})
    assert raw.status_code == 400
    raw = http.post("/api/", data={"token": TOKEN_A, "content": "event", "format": "json", "data": "{}"})
    assert raw.status_code == 400
    raw = http.post("/api/", data={"token": TOKEN_A, "content": "file", "format": "json"})
    assert raw.status_code == 400

    def answer(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode())
        content = body.get("content", [""])[0]
        if content == "project":
            return httpx.Response(200, text="not-json")
        if content == "metadata":
            return httpx.Response(200, json={"not": "a list"})
        if content == "record":
            return httpx.Response(400, text="plain refusal")
        return httpx.Response(200, json="no")

    mocked = RedcapClient("https://rc.example/api/", TOKEN_A, http=httpx.Client(transport=httpx.MockTransport(answer)))
    with pytest.raises(RcError, match="not JSON"):
        mocked.project()
    with pytest.raises(RcError, match="not a list"):
        mocked.metadata()
    with pytest.raises(RcError) as err:
        mocked.records()
    assert err.value.kind == "" and not err.value.refused
    with pytest.raises(RcError, match="not a list"):
        mocked.repeating_forms_events()
    mocked.close()

    def odd(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode())
        content = body.get("content", [""])[0]
        if content == "record" and "data" in body:
            return httpx.Response(200, json={"ids": 1})
        if content == "record":
            return httpx.Response(200, json={"rows": 1})
        return httpx.Response(200, json={"users": 1})

    odd_client = RedcapClient("https://rc.example/api/", TOKEN_A, http=httpx.Client(transport=httpx.MockTransport(odd)))
    with pytest.raises(RcError, match="not a list"):
        odd_client.records()
    with pytest.raises(RcError, match="record ids"):
        odd_client.import_records([{"record_id": "1"}])
    with pytest.raises(RcError, match="not a list"):
        odd_client.users()
    odd_client.close()
