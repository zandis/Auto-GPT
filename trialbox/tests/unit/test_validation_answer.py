"""NEW-TRUST-2 (D-551): a service's answer to a request of the wrong shape carries no value of that request.

The framework's own 422 answer repeats what was sent (``"input": ...``): a body with a chart number and a missing
field came back with the chart number in it, and a client that logs a refusal then logs the chart number. Every
service made by ``tb_common.http.make_app`` answers with where and why only."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, field_validator
from tb_common.http import make_app

CHART = "A1234567"  # synthetic
pytestmark = pytest.mark.nodb


class _Row(BaseModel):
    mrn: str | None = None
    status: Literal["candidate", "contacted"]
    note: str = Field("", max_length=5)
    inner: dict[str, int] = {}

    @field_validator("mrn")
    @classmethod
    def _shape(cls, v: str | None) -> str | None:
        if v is not None and not v.isdigit():
            raise ValueError("a chart number is digits")  # the message names no value
        return v


def _client() -> TestClient:
    app = make_app("toy", service_token=False)

    @app.post("/rows")
    def add(row: _Row) -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/rows")
    def rows(limit: int = 10) -> dict[str, int]:
        return {"limit": limit}

    return TestClient(app)


@pytest.mark.parametrize(
    "body",
    [
        {"mrn": CHART},  # the review's case: a chart number and a missing field
        {"mrn": CHART, "status": "nope"},
        {"mrn": "12345678", "status": "candidate", "note": CHART},  # too long
        {"mrn": "12345678", "status": "candidate", "inner": {"k": CHART}},  # a nested value of the wrong type
        {"mrn": CHART, "status": "candidate"},  # refused by the model's own rule
        [CHART],  # not an object at all
    ],
)
def test_a_body_of_the_wrong_shape_is_answered_without_its_values(body: Any) -> None:
    r = _client().post("/rows", json=body)
    assert r.status_code == 422
    assert CHART not in r.text
    detail = r.json()["detail"]
    assert detail and all(set(d) == {"type", "loc", "msg"} for d in detail)
    assert all(d["loc"][0] == "body" for d in detail)  # where it is wrong is still said


class _Cat(BaseModel):
    kind: Literal["cat"]


class _Dog(BaseModel):
    kind: Literal["dog"]


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}
    status: str = ""
    counts: dict[str, int] = {}
    by_no: dict[int, int] = {}
    pet: _Cat | _Dog | None = Field(None, discriminator="kind")
    code: str = ""

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if v == "raise":
            raise ValueError(f"v={CHART!r} does not look right")  # a rule whose author put the value in its text
        assert v != "assert", f"bad {CHART}"
        return v


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({CHART: 1}, ["body", "*"]),  # the review's case on the real orchestrator: an extra key
        ({"counts": {CHART: "x"}}, ["body", "counts", "*"]),  # a key of a mapping
        ({"by_no": {CHART: 1}}, ["body", "by_no", "*", "[key]"]),
        ({"pet": {"kind": CHART}}, ["body", "pet"]),  # the framework's own text names the tag that was sent
        ({"code": "raise"}, ["body", "code"]),
        ({"code": "assert"}, ["body", "code"]),
    ],
)
def test_a_key_the_caller_chose_and_a_rules_own_text_are_not_repeated(body: Any, loc: list[Any]) -> None:
    app = make_app("toy", service_token=False)

    @app.post("/strict")
    def add(row: _Strict) -> dict[str, str]:
        return {"ok": "yes"}

    r = TestClient(app).post("/strict", json=body)
    assert r.status_code == 422 and CHART not in r.text, r.text
    assert [d["loc"] for d in r.json()["detail"]] == [loc]  # the declared names are still said


def test_a_path_value_is_not_repeated() -> None:
    app = make_app("toy", service_token=False)

    @app.get("/p/{n}")
    def one(n: int) -> dict[str, int]:
        return {"n": n}

    r = TestClient(app).get(f"/p/{CHART}")
    assert r.status_code == 422 and CHART not in r.text and r.json()["detail"][0]["loc"] == ["path", "n"]


def test_a_query_value_and_a_body_that_is_not_json_are_not_repeated_either() -> None:
    c = _client()
    r = c.get(f"/rows?limit={CHART}")
    assert r.status_code == 422 and CHART not in r.text and r.json()["detail"][0]["loc"] == ["query", "limit"]
    r = c.post("/rows", content=f'{{"mrn": "{CHART}"'.encode(), headers={"content-type": "application/json"})
    assert r.status_code == 422 and CHART not in r.text


def test_the_orchestrators_own_route_answers_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import app as oapp

    monkeypatch.setenv("TB_ENV", "TEST")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    c = TestClient(oapp.app, raise_server_exceptions=False)
    r = c.post("/registry/GZQO", json={"mrn": CHART})
    assert r.status_code == 422 and CHART not in r.text, r.text[:200]
    r = c.post("/registry/GZQO", json={"mrn": "12345678", CHART: 1})  # an extra key, on a contract that forbids one
    assert r.status_code == 422 and CHART not in r.text, r.text[:200]
    r = c.post("/jobs", json={CHART: 1})
    assert r.status_code == 422 and CHART not in r.text, r.text[:200]


def test_every_service_app_is_made_where_the_answer_is_set() -> None:
    """A service that builds its own app would bring the framework's answer back. The apps of ``services/`` are
    made by ``make_app``, except the console (which sets the same answer, ``console.api_first``) and the REDCap
    simulator, a test stand-in that is no service of the box."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    makes = re.compile(r"\b(FastAPI|Starlette)\s*\(")  # a call, however it is spaced; an alias would still slip by
    own = sorted(str(f.relative_to(root)) for f in (root / "services").rglob("*.py")
                 if any(makes.search(ln.split("#")[0]) and "``" not in ln
                        for ln in f.read_text(encoding="utf-8").splitlines()))  # fmt: skip
    assert own == ["services/console/app.py", "services/rc_sim/app.py"], own
    from fastapi.exceptions import RequestValidationError
    from orchestrator import app as oapp
    from tb_common.http import validation_answer

    assert oapp.app.exception_handlers[RequestValidationError] is validation_answer  # installed, not only named
    console = (root / "services/console/api_first.py").read_text(encoding="utf-8")
    assert "validation_answer(request, exc)" in console and "request_validation_exception_handler" not in console
