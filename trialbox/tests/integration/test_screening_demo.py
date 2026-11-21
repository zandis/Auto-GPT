import json
from pathlib import Path

import pytest

from tools.role_demo import build


def test_fresh_role_demo_screens_published_night(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_TZ", raising=False)
    monkeypatch.delenv("TB_ENV", raising=False)
    box, client, _ = build(tmp_path)
    try:
        job = box.orch.db.find(type_="SCREEN")[0]
        assert job.state == "done", job.error
        candidates = next(o for o in job.outputs if o.filename.startswith("candidate_list_"))
        assert json.loads(box.store.get(candidates.minio_key))["rows"]
    finally:
        client.close()


def test_first_install_cli_night_screens_approved_study(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_url: str
) -> None:
    import yaml
    from adapter import cli
    from console.sitestore import SiteStore
    from tb_common.flags import Flags

    from tests.inproc_box import ROOT, make_box

    feed = ROOT / "tests/fixtures/synthetic_patients/site-a"
    settings = yaml.safe_load((ROOT / "deploy/settings.example.yaml").read_bytes())
    settings["data_source"]["path"] = str(feed)
    settings["registry_source"]["path"] = str(feed / "registry.csv")
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(yaml.safe_dump(settings))
    sec = tmp_path / "secrets"
    env = {
        "TB_SETTINGS_FILE": str(settings_path),
        "TB_SETTINGS": str(settings_path),
        "TB_DATA_DIR": str(tmp_path),
        "TB_LAKE_DIR": str(tmp_path / "lake"),
        "TB_RULESETS_DIR": str(tmp_path / "box" / "repo"),
        "TB_SECRETS_DIR": str(sec),
        "TB_ADAPTER_LAKE": "local",
        "TB_LAKE_EMBEDDER": "hash",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.main(["keys-init"]) == 0
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, extra_env=env)
    Flags(url=db_url, audit=box.orch.audit).seed()
    SiteStore(db_url).close()
    assert (
        cli.main(
            ["run", "--snapshot", "2026-10-04", "--source", "csv", "--path", str(feed), "--no-fhir", "--no-validate"]
        )
        == 0
    )
    box.mail("SCREEN GZQO version=1.0.0")
    box.orch.drain()
    job = box.orch.db.find(type_="SCREEN")[0]
    assert job.state == "done", job.error
    candidate = next(output for output in job.outputs or [] if output.filename.startswith("candidate_list_"))
    assert json.loads(box.store.get(candidate.minio_key))["rows"]
