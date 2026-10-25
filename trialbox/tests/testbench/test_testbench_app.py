"""Test Bench app (docs/HANDOFF.md §5) through FastAPI's TestClient: pages, refusals, and each driver."""

from __future__ import annotations

import hashlib
import re
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common.policy.classes import Environment, PolicyError

from tools.testbench import BANNER, HTMX_SHA256, HTMX_VERSION, e2e_adapter
from tools.testbench.app import PAGES, create_app
from tools.testbench.datasets import load_registry, require
from tools.testbench.safety import check_bind_host, startup_checks

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "tools" / "testbench" / "static"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    app = create_app(env={"TB_ENV": "TEST"}, workdir=tmp_path_factory.mktemp("bench"))
    return TestClient(app)


def _wait(client: TestClient, location: str, timeout: float = 600.0) -> str:
    """Follow a job redirect until the job is finished; return the job page."""
    jid = location.rstrip("/").split("/")[-2]
    t0 = time.time()
    while time.time() - t0 < timeout:
        if client.get(f"/jobs/{jid}").json()["status"] != "running":
            break
        time.sleep(0.5)
    page = client.get(f"/jobs/{jid}/view")
    assert page.status_code == 200
    return str(page.text)


# ------------------------------------------------------------------------------------------------ pages
@pytest.mark.parametrize("path", [p for p, _ in PAGES])
def test_every_page_loads_with_the_banner(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200
    assert BANNER in r.text
    assert '<script src="/static/htmx.min.js"' in r.text and "unpkg" not in r.text and "cdnjs" not in r.text
    assert r.headers["x-tb-test-bench"] == "synthetic-and-open-data-only"


def test_fragments_opened_directly_carry_the_banner(client: TestClient) -> None:
    r = client.get("/llm/routes", params={"topology": "B"})
    assert r.status_code == 200 and BANNER in r.text
    partial = client.get("/llm/routes", params={"topology": "B"}, headers={"HX-Request": "true"})
    assert BANNER not in partial.text and "route-table" in partial.text
    missing = client.get("/jobs/nope/view")
    assert missing.status_code == 404 and BANNER in missing.text


def test_htmx_is_vendored_and_pinned(client: TestClient) -> None:
    data = (STATIC / "htmx.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == HTMX_SHA256
    assert f'version:"{HTMX_VERSION}"' in data.decode()
    assert client.get("/static/htmx.min.js").content == data


# ------------------------------------------------------------------------------------------------ refusals
@pytest.mark.parametrize("env", [{}, {"TB_ENV": "PRODUCTION"}, {"TB_ENV": "VALIDATION"}, {"TB_ENV": "dev"}])
def test_refuses_to_start_outside_dev_and_test(env: dict[str, str], tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="TB_ENV"):
        create_app(env=env, workdir=tmp_path)


@pytest.mark.parametrize("var", ["TB_LAKE_DIR", "TB_ORCH_DIR", "FHIR_BASE_URL", "TB_PG_DSN"])
def test_refuses_to_start_with_a_patient_store(var: str, tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match=var):
        create_app(env={"TB_ENV": "DEV", var: "/data/lake"}, workdir=tmp_path)


@pytest.mark.req("ENG-16")
@pytest.mark.parametrize("cls", ["D1", "D2", "D3", "D4", "", "D5"])
def test_refuses_anything_above_d0(cls: str) -> None:
    reg = load_registry()
    reg["synthetic_hospitals"] = {**reg["synthetic_hospitals"], "data_class": cls}
    with pytest.raises(PolicyError):
        require("synthea_site_a", Environment.DEV, reg)
    if cls:
        with pytest.raises(PolicyError):
            startup_checks({"TB_ENV": "TEST", "TB_DATA_CLASS": cls})


@pytest.mark.req("ENG-16")
def test_every_bench_dataset_is_d0_open_or_synthetic() -> None:
    reg = load_registry()
    for key in ("synthetic_hospitals", "mimic_iv_fhir_demo", "ctgov_records", "recall_cert", "deid_synthetic"):
        assert reg[key]["data_class"] == "D0" and reg[key]["kind"] in ("open", "synthetic")
    reg["ctgov_records"] = {**reg["ctgov_records"], "kind": "hospital"}
    with pytest.raises(PolicyError, match="open or synthetic"):
        require("ctgov_records", Environment.TEST, reg)


def test_unknown_dataset_is_refused_with_403(client: TestClient) -> None:
    r = client.post("/run", data={"dataset": "real_hospital_emr"}, follow_redirects=False)
    assert r.status_code == 403 and BANNER in r.text and "unknown Test Bench dataset" in r.text


def test_binds_loopback_only() -> None:
    for ok in ("127.0.0.1", "::1", "localhost"):
        check_bind_host(ok, {})
    for bad in ("0.0.0.0", "10.1.2.3", "bench.example"):
        with pytest.raises(PolicyError):
            check_bind_host(bad, {})
    check_bind_host("0.0.0.0", {"TB_TESTBENCH_IN_CONTAINER": "1"})


def test_file_route_stays_inside_the_job(client: TestClient) -> None:
    loc = client.post("/recall", data={"reps": 2, "months": 2, "per_month": 5}, follow_redirects=False)
    jid = loc.headers["location"].split("/")[-2]
    _wait(client, loc.headers["location"])
    assert client.get(f"/files/{jid}/../../../../etc/passwd").status_code == 404
    assert client.get(f"/files/{jid}/%2e%2e/%2e%2e/etc/hostname").status_code == 404


# ------------------------------------------------------------------------------------------------ drivers
def test_route_table_never_routes_d3_d4_outside(client: TestClient) -> None:
    for topo in ("A", "B", "C"):
        r = client.get(
            "/llm/routes", params={"topology": topo, "env": "PRODUCTION", "opt_in": "1"}, headers={"HX-Request": "true"}
        )
        assert r.status_code == 200
        rows = r.text.split("<tr>")[2:]
        assert len(rows) > 20
        for row in rows:
            cells = row.split("<td")[2:]
            for cell in cells[4:6]:  # D3, D4
                assert "@external_x" not in cell and "@openrouter" not in cell
    dev = client.get("/llm/routes", params={"env": "DEV"}, headers={"HX-Request": "true"}).text
    assert "class_not_allowed_in_env" in dev and "dev-public" in dev


def test_prompt_through_the_gateway_is_allowed_or_refused_and_audited(client: TestClient) -> None:
    ok = client.post("/llm/prompt", data={"text": "Acute gout flare, ongoing.", "data_class": "D0"})
    assert "HTTP 200: allowed" in ok.text and "llm.gateway.call" in ok.text and "chain verify: ok" in ok.text
    d3 = client.post("/llm/prompt", data={"text": "x", "data_class": "D3"})
    assert "HTTP 403: refused (step_unconfirmed)" in d3.text
    d1 = client.post("/llm/prompt", data={"text": "x", "data_class": "D1"})
    assert "class_not_allowed_in_env" in d1.text
    phi = client.post("/llm/prompt", data={"text": "Patient A123456789 has gout", "data_class": "D0"})
    assert "phi_tripwire" in phi.text and "A123456789" not in phi.text.split("Audit records")[1]


def test_registry_and_model_cards_are_shown(client: TestClient) -> None:
    r = client.get("/llm").text
    assert "trialbox-stub-1" in r and "registry-" in r and "<details>" in r


def test_guard_redacts(client: TestClient) -> None:
    r = client.post("/guard", data={"text": "Patient A123456789 phoned 0912-345-678."}, headers={"HX-Request": "true"})
    assert "[TW_NATIONAL_ID]" in r.text and "[PHONE]" in r.text and "tripwire: HIT" in r.text
    clean = client.post("/guard", data={"text": "Gout flare."}, headers={"HX-Request": "true"})
    assert "tripwire: clear" in clean.text


def test_registry_match_on_fixtures(client: TestClient) -> None:
    r = client.post(
        "/match",
        data={"note": "A 60-year-old man with gout and high serum urate.", "open_data": "1", "synthetic": "1"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "NCT02568722" in r.text and "NCT00000011" in r.text and "match-table" in r.text


def test_recall_simulation_shows_cs_and_cp(client: TestClient) -> None:
    loc = client.post("/recall", data={"reps": 3, "months": 4, "per_month": 10, "rate": 0.02}, follow_redirects=False)
    assert loc.status_code == 303
    page = _wait(client, loc.headers["location"])
    assert "recall-table" in page and "repeated CP miss" in page and "<svg" in page and BANNER in page


def test_dataplat_planted_defect_blocks_publish(client: TestClient) -> None:
    loc = client.post("/dataplat", data={"defect": "null_identifier"}, follow_redirects=False)
    page = _wait(client, loc.headers["location"])
    assert 'data-testid="gate-outcome">PUBLISH' in page and 'data-testid="gate-outcome">HOLD' in page
    assert "NULL_IDENTIFIER" in page and "Steward notice" in page and "tb.l1.validate" in page


def test_run_end_to_end_on_the_synthetic_fixture_passes(client: TestClient) -> None:
    loc = client.post("/run", data={"dataset": "synthea_site_a", "trial_id": "GZQO"}, follow_redirects=False)
    page = _wait(client, loc.headers["location"])
    assert 'data-testid="result-status">PASS' in page, page[page.find("result-status") - 200 :][:2000]
    assert "monotone funnel" in page and "lineage complete" in page and "reproducible second run" in page
    links = re.findall(r'href="(/files/[^"]+)"', page)
    pdfs = [x for x in links if x.endswith(".pdf")]
    assert pdfs, links
    pdf = client.get(pdfs[0])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


# ------------------------------------------------------------------------------------------------ e2e adapter
def test_adapter_prefers_the_v4_entry_point(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, str, Path]] = []

    def run_end_to_end(source_dir: Path, trial_id: str, out_dir: Path) -> Any:
        calls.append((source_dir, trial_id, out_dir))
        (out_dir / "pack.pdf").write_bytes(b"%PDF-1.4")
        return types.SimpleNamespace(
            passed=True,
            stage_counts={"S0": 600, "S5": 12},
            invariants={"monotone funnel": True, "small cells": []},
            files=["pack.pdf"],
            out_dir=out_dir,
        )

    mod = types.ModuleType("fake_tb_e2e")
    mod.run_end_to_end = run_end_to_end  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_tb_e2e", mod)
    ds = require("synthea_site_a", Environment.TEST)
    res = e2e_adapter.run(ds, "GZQO", tmp_path, lambda _m: None, {e2e_adapter.ENV_VAR: "fake_tb_e2e:run_end_to_end"})
    assert calls == [(ds.path, "GZQO", tmp_path / "v4")]
    assert res.passed and res.status == "PASS" and res.engine == "fake_tb_e2e:run_end_to_end"
    assert ("S0", "600") in res.stages and all(i.ok for i in res.invariants)
    assert res.files == [tmp_path / "v4" / "pack.pdf"]


def test_adapter_falls_back_when_the_v4_entry_point_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def broken(source_dir: Path, trial_id: str, out_dir: Path) -> Any:
        raise RuntimeError("not finished yet")

    mod = types.ModuleType("broken_tb_e2e")
    mod.run_end_to_end = broken  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "broken_tb_e2e", mod)
    v1 = e2e_adapter.BenchE2E("fallback: v1", "synthea_site_a", "GZQO", True, tmp_path / "v1")
    monkeypatch.setattr(e2e_adapter, "synthetic_v1", lambda *a: v1)
    ds = require("synthea_site_a", Environment.TEST)
    env = {e2e_adapter.ENV_VAR: "broken_tb_e2e:run_end_to_end"}
    res = e2e_adapter.run(ds, "GZQO", tmp_path, lambda _m: None, env)
    assert res.passed and "after the v4 entry point failed" in res.engine and "not finished yet" in res.note
    with pytest.raises(RuntimeError, match="not finished yet"):
        e2e_adapter.run(ds, "GZQO", tmp_path, lambda _m: None, {**env, e2e_adapter.STRICT_VAR: "1"})


def test_adapter_reads_a_failed_result() -> None:
    res = e2e_adapter.from_e2e_result(
        {"status": "FAIL", "checks": [{"name": "recall certificate", "ok": False}]}, "x", "d", "t", Path("/nonexistent")
    )
    assert not res.passed and res.invariants[0].name == "recall certificate" and not res.invariants[0].ok


def test_adapter_without_entry_point_falls_back() -> None:
    assert e2e_adapter.find_entry({e2e_adapter.ENV_VAR: "no_such_module_xyz:run_end_to_end"}) is None
