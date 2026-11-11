"""The admin Models tile lists each model build pinned on the box with its qualification record (T-012b, LLM-029): a
champion without a record is flagged, because a PRODUCTION gateway refuses it (``champion_unqualified``)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from console.models_view import build_rows

from tests.console.test_console_app import box, login  # noqa: F401 - fixture by name
from tests.model_pins import qualified

SHA = "ab" * 32
BUILDS: list[dict[str, Any]] = [
    {"build_id": "trialbox-stub-1", "alias": "trialbox-stub", "status": "champion", "pinned": False},
    {"build_id": "qwen3.5-35b-a3b-candidate", "alias": "j-workhorse", "status": "candidate", "pinned": False},
    {
        "build_id": "gemma-4-26b-a4b-it-rtxpro6000",
        "alias": "j-workhorse",
        "status": "champion",
        "pinned": True,
        "expected": {"manifest_sha256": SHA},
        "weights_expected": True,
        "qualification": qualified(SHA, "rtxpro6000-pair-20261111"),
        "qualified_for_production": True,
    },
    {
        "build_id": "qwen3.5-9b-rtxpro6000",
        "alias": "v-verifier",
        "status": "champion",
        "pinned": True,
        "expected": {"manifest_sha256": SHA},
        "weights_expected": True,
        "qualification": None,
        "qualified_for_production": False,
    },
    {
        "build_id": "gemma-4-26b-a4b-it-spark",
        "alias": "j-workhorse",
        "status": "candidate",
        "pinned": True,
        "expected": {"manifest_sha256": SHA},
        "weights_expected": False,
        "qualification": None,
        "qualified_for_production": False,
    },
]


def test_build_rows_lists_pinned_builds_and_champions_but_not_the_stub() -> None:
    rows = build_rows(BUILDS)
    assert rows is not None
    assert [r["build_id"] for r in rows] == [
        "gemma-4-26b-a4b-it-rtxpro6000",
        "qwen3.5-9b-rtxpro6000",
        "gemma-4-26b-a4b-it-spark",
    ]
    assert (
        rows[0]["qualified"] and rows[0]["record"] == "rtxpro6000-pair-20261111" and rows[0]["at"] == "2026-11-11 00:00"
    )
    assert not rows[1]["qualified"] and not rows[1]["unexpected"]
    assert rows[2]["unexpected"]
    assert build_rows(None) is None and build_rows([]) == []


def test_the_models_tile_shows_the_record_and_flags_an_unqualified_champion(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_console_app import ADMIN_PW

    box["backend"].model_builds = lambda: BUILDS
    c, csrf = login(box["app"], "admin", ADMIN_PW)
    page = c.get("/admin").text
    tile = page[page.index('data-testid="tile-models"') :]
    tile = tile[: tile.index("</section>")]
    assert 'data-testid="models-records"' in tile
    judge = tile[tile.index('data-testid="model-build-gemma-4-26b-a4b-it-rtxpro6000"') :]
    assert "qualified: record rtxpro6000-pair-20261111, promoted 2026-11-11 00:00" in judge.split("</li>")[0]
    verifier = tile[tile.index('data-testid="model-build-qwen3.5-9b-rtxpro6000"') :].split("</li>")[0]
    assert "no qualification record: a PRODUCTION box refuses this model" in verifier
    spark = tile[tile.index('data-testid="model-build-gemma-4-26b-a4b-it-spark"') :].split("</li>")[0]
    assert "these weights are not the expected release" in spark
    assert "trialbox-stub-1" not in tile
    for lang, word in (("ja", "適格性確認の記録がありません"), ("zh-TW", "沒有資格確認紀錄")):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/admin"})
        assert word in c.get("/admin").text
    box["backend"].model_builds = lambda: []
    c.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/admin"})
    assert "No model build is pinned on this box." in c.get("/admin").text


def test_no_build_list_when_the_gateway_is_not_read(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_console_app import ADMIN_PW

    c, _ = login(box["app"], "admin", ADMIN_PW)
    assert 'data-testid="models-records"' not in c.get("/admin").text  # the fake backend has no gateway


def test_the_http_backend_reads_the_gateways_registry_view(monkeypatch: pytest.MonkeyPatch) -> None:
    from console import backend as be

    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json={"version": "v", "builds": BUILDS})

    real = httpx.Client

    def client(*a: Any, **kw: Any) -> httpx.Client:
        return real(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", client)
    obj = object.__new__(be.HttpBackend)
    obj.services = {"gateway": "http://gateway:8020"}
    assert obj.model_builds() == BUILDS and seen == ["http://gateway:8020/registry/v1/builds"]
    obj.services = {}
    assert obj.model_builds() is None
