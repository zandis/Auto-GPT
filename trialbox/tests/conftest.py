from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith(("TB_", "IMAP_", "SMTP_", "MINIO_", "LLM_", "CLOUD_LLM", "MAIL_")):
            monkeypatch.delenv(key, raising=False)
    yield


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TB_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="needs compose services (set TB_INTEGRATION=1, run `make up-test`)")
    for item in items:
        if item.get_closest_marker("integration") or item.get_closest_marker("e2e"):
            item.add_marker(skip)


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
def ingested(synth_dir: Path, site_key_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Site A ingested in-process (csv source) into a lake with the hash embedder."""
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
    )
    report = run_ingest(cfg, "csv", str(synth_dir / "site-a"), snapshot=SNAPSHOT, load_fhir=False)
    return {
        "lake_dir": lake_dir,
        "report": report,
        "cfg": cfg,
        "key": (site_key_dir / "site_hmac.key").read_bytes(),
    }
