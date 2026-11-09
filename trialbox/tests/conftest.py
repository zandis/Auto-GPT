from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return ROOT


# ------------------------------------------------------------------ the trial database (D-126)
# One throwaway PostgreSQL per test session (tools/pglocal.py), or the one in TB_TEST_DB_URL; every test gets its own
# schemas through a unique tb_prefix, so tests never see each other's rows.
_DB_COUNTER = iter(range(1, 10**9))


@pytest.fixture(scope="session")
def pg_cluster_url() -> Iterator[str]:
    given = os.environ.get("TB_TEST_DB_URL")
    if given:
        yield given
        return
    import shutil
    import tempfile

    from tools import pglocal

    # not under pytest's private tmp: as root the server runs as the `postgres` user and must reach its directory
    root = Path(os.environ.get("TB_TEST_PG_DIR") or tempfile.mkdtemp(prefix="tb-pgtest-"))
    root.chmod(0o755)
    url = pglocal.ensure(root)
    yield url
    if not os.environ.get("TB_TEST_PG_DIR"):
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def db_url(pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """A TB_DB_URL private to this test (also set in the environment for code that reads TB_DB_URL)."""
    sep = "&" if "?" in pg_cluster_url else "?"
    url = f"{pg_cluster_url}{sep}tb_prefix=t{os.getpid()}x{next(_DB_COUNTER)}_"
    monkeypatch.setenv("TB_DB_URL", url)
    return url


@pytest.fixture(autouse=True)
def _private_trial_db(db_url: str) -> str:
    """Every test runs with its own TB_DB_URL, so nothing it stores leaks into another test."""
    return db_url


@pytest.fixture(autouse=True)
def _keep_service_token() -> Iterator[None]:
    """``tools.role_demo.orch_client`` sets ``TB_SERVICE_TOKEN`` for its process (a demo box authenticates like a real
    console). A test that builds such a box must not leave it set: every later test of a service's HTTP surface would
    then expect a token (the 401s seen after tests/integration/test_list_demo.py in one run, D-144)."""
    before = os.environ.get("TB_SERVICE_TOKEN")
    yield
    if before is None:
        os.environ.pop("TB_SERVICE_TOKEN", None)
    else:
        os.environ["TB_SERVICE_TOKEN"] = before


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith(("TB_", "IMAP_", "SMTP_", "LLM_", "CLOUD_LLM", "MAIL_")) and key != "TB_DB_URL":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TB_CANARY_GATE", "off")  # see pytest_configure
    yield


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "req(*ids): spec v4 requirement ids this test verifies (§17.4)")
    # D-117: on a box the pair canary gates note exclusions (on unless TB_ENV is DEV or TEST). The suite's stub and
    # fake models are not the pair and never pass a canary, so the gate is off for the suite; the gate's own tests
    # (tests/unit/test_canary_gate.py) switch it on with monkeypatch.
    os.environ.setdefault("TB_CANARY_GATE", "off")
    # D-127 (F-06): an unset TB_ENV now means PRODUCTION (token required, timers on). The suite is a TEST box; the
    # tests of the PRODUCTION default set or clear TB_ENV themselves.
    os.environ.setdefault("TB_ENV", "TEST")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    from tb_testkit.req import unknown_ids

    bad = sorted({i for item in items for m in item.iter_markers("req") for i in unknown_ids(list(m.args))})
    if bad:
        raise pytest.UsageError(f"@pytest.mark.req names unknown spec v4 requirement ids: {', '.join(bad)}")
    egress = pytest.mark.skip(reason="host egress test: run `make test-egress` as root with the stack up")
    for item in items:
        if item.get_closest_marker("egress") and os.environ.get("TB_EGRESS_TEST") != "1":
            item.add_marker(egress)
    if os.environ.get("TB_INTEGRATION") == "1":
        _skip_compose_tests_without_a_stack(items)
        return
    skip = pytest.mark.skip(reason="needs compose services (set TB_INTEGRATION=1, run `make up-test`)")
    for item in items:
        if item.get_closest_marker("integration") or item.get_closest_marker("e2e"):
            item.add_marker(skip)


def _stack_up() -> bool:
    """The compose test stack answers on the lake's host port (tests/stack.py)."""
    import socket

    from tests.stack import host_port

    try:
        with socket.create_connection(("127.0.0.1", host_port("LAKE")), timeout=1):
            return True
    except OSError:
        return False


def _skip_compose_tests_without_a_stack(items: list[pytest.Item]) -> None:
    """``TB_INTEGRATION=1`` runs the in-process integration tests anywhere; the ``*compose*`` ones need `make
    up-test`, so without a running stack they are skipped by name instead of erroring on a refused connection."""
    compose = [i for i in items if "compose" in Path(str(i.fspath)).name and i.get_closest_marker("integration")]
    if compose and not _stack_up():
        mark = pytest.mark.skip(reason="compose test stack not running (`make up-test`)")
        for item in compose:
            item.add_marker(mark)


# ----------------------------------------------------------------------------- synthetic data fixtures
REF_DATE = "2026-10-05"
SNAPSHOT = "2026-10-04"


@pytest.fixture(scope="session")
def synth_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tools.make_fixtures import main as make_fixtures

    out = tmp_path_factory.mktemp("synth")
    assert make_fixtures(["--out", str(out), "--sites", "ab"]) == 0
    return out


@pytest.fixture(scope="session")
def site_key_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("secrets")
    (d / "site_hmac.key").write_bytes(b"trialbox-test-site-key-0123456789abcdef")
    (d / "site_hmac.key").chmod(0o600)
    return d


@pytest.fixture(scope="session")
def ingested(
    synth_dir: Path, site_key_dir: Path, tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str
) -> dict[str, object]:
    """Site A ingested in-process (csv source) into a lake with the hash embedder. The pid map goes to the session's
    own schemas (``cfg.db_url``): a session fixture runs before any test's private ``TB_DB_URL``."""
    from adapter.pipeline import AdapterConfig, run_ingest
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from tb_contracts import RebuildResult

    lake_dir = tmp_path_factory.mktemp("lake")

    def rebuild(snap: str, nd: Path) -> RebuildResult:
        st = Lake(lake_dir).rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(
            snapshot=st.snapshot,
            tables=st.tables,
            chunks=st.chunks,
            embedded_new=st.embedded_new,
            seconds=st.seconds,
        )

    cfg = AdapterConfig(
        lake_dir=lake_dir,
        secrets_dir=site_key_dir,
        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
        site_id="DEMO-A",
        audit_dir=lake_dir / "audit",
        rebuild=rebuild,
        db_url=f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=s{os.getpid()}ingested_",
    )
    report = run_ingest(cfg, "csv", str(synth_dir / "site-a"), snapshot=SNAPSHOT, load_fhir=False)
    return {
        "lake_dir": lake_dir,
        "report": report,
        "cfg": cfg,
        "key": (site_key_dir / "site_hmac.key").read_bytes(),
    }
