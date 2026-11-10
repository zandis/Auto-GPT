"""T-501: the demo image starts from a clean build. The CI job `demo-image` builds and starts the image itself; these
are the fast checks of the parts it depends on (LIFE-005, ROLE-002, OPS-077, OPS-009)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_cql import translator
from criteria_compiler.service import CompileFailed
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from tests.unit.test_compiler_service import _compile, env  # noqa: F401 - env is a fixture
from tools import demo, pglocal

ROOT = Path(__file__).resolve().parents[2]


def test_compiling_without_translator_jars_is_a_named_error(
    env: dict[str, Any],  # noqa: F811 - the imported fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TB_CQL_TRANSLATOR_LIB", str(tmp_path / "no-jars"))
    with pytest.raises(CompileFailed) as err:
        _compile(env)
    assert err.value.step == "cql_translate"
    assert "CQL translator is not installed" in str(err.value) and "make jvm-deps" in str(err.value)
    assert isinstance(err.value.__cause__, FileNotFoundError)


def _cookie_app() -> FastAPI:
    app = FastAPI()

    @app.get("/set")
    def set_cookie() -> Response:
        resp = Response("set")
        resp.set_cookie("s", "1", httponly=True, samesite="strict", secure=True)
        return resp

    @app.get("/get")
    def get_cookie(request: Request) -> Response:
        return Response(request.cookies.get("s", "none"))

    return app


def test_seeding_sends_secure_cookies_back() -> None:
    app = _cookie_app()
    plain = TestClient(app)
    plain.get("/set")
    assert plain.get("/get").text == "none"  # why the image's Secure cookie broke the in-process seeding
    with demo.https_seeding():
        c = TestClient(app)
        c.get("/set")
        assert c.get("/get").text == "1"
        assert str(TestClient(app, base_url="http://other").base_url) == "http://other"
    assert str(TestClient(app).base_url).startswith("http://testserver")  # restored after seeding


def test_demo_marks_its_temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "tb-tests-demo"
    monkeypatch.setenv("TB_TEST_ROOT", str(root))
    monkeypatch.delenv("TB_DB_URL", raising=False)
    monkeypatch.delenv("TB_PG_DIR", raising=False)
    demo.mark_temp_root()
    (root / "pglocal").mkdir()  # what for_work then starts under it
    assert (root / pglocal.MARKER).exists()
    assert pglocal.check_test_root(root) == root.resolve()  # the next run with the same root is not refused


def test_image_pins_fhirhelpers_and_leaves_out_the_reviews() -> None:
    dockerfile = (ROOT / "demo/Dockerfile").read_text(encoding="utf-8")
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "docs/reviews" in ignore and "!.cache/jvm/cql-translator/lib/quick-*.jar" in ignore
    assert "TB_CONSOLE_SECURE_COOKIE=1" in dockerfile
    pin = re.search(r"ARG FHIRHELPERS_SHA256=([0-9a-f]{64})", dockerfile)
    assert pin
    try:
        source = translator.fhirhelpers_source()
    except FileNotFoundError:
        pytest.skip("no translator jars here (make jvm-deps); CI has them")
    # the jars of the translator's pom.xml carry the FHIRHelpers text the image pins (a version bump must re-pin)
    assert hashlib.sha256(source.encode()).hexdigest() == pin.group(1)
