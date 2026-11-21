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


def test_poc_bootstrap_screens_synthetic_night(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_url: str) -> None:
    """Exercise poc.sh with the compose transport in-process, including the actual key command it requests."""
    import os
    import shutil
    import subprocess
    import sys

    import yaml
    from adapter import app as adapter_app
    from console.backend import HttpBackend
    from console.sitestore import SiteStore
    from criteria_compiler.app import ruleset_repo
    from fastapi.testclient import TestClient
    from tb_common.audit import AuditLog
    from tb_common.flags import Flags

    from tests.inproc_box import ROOT, make_box
    from tests.unit.test_t723_publish_night import Fhir

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(ROOT / "deploy/poc.sh", deploy)
    shutil.copy(ROOT / ".env.example", tmp_path)
    sec = tmp_path / ".cache/test-secrets"
    transport = tmp_path / "docker"
    transport.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        ' *" python -m adapter.cli keys-init "*) exec "$POC_PYTHON" -m adapter.cli keys-init ;;\n'
        ' *" console.cli poc-settings "*) exec "$POC_PYTHON" -m console.cli poc-settings --in "$POC_TEMPLATE" '
        '--out deploy/poc/settings.yaml --admin-email "$TB_POC_ADMIN_EMAIL" ;;\n'
        ' *" console.cli ingest "*) touch deploy/poc/ingest-requested ;;\n'
        "esac\n"
    )
    transport.chmod(0o755)
    monkeypatch.setenv("TB_SECRETS_DIR", str(sec))
    subprocess.run(
        ["bash", str(deploy / "poc.sh")],
        check=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "POC_PYTHON": sys.executable,
            "POC_TEMPLATE": str(ROOT / "deploy/settings.example.yaml"),
            "PYTHONPATH": os.pathsep.join(str(ROOT / d) for d in ("libs", "services", ".")),
        },
    )
    feed = ROOT / "tests/fixtures/synthetic_patients/site-a"
    settings = deploy / "poc/settings.yaml"
    assert (deploy / "poc/ingest-requested").is_file()
    doc = yaml.safe_load(settings.read_bytes())
    doc["data_source"]["path"] = str(feed)
    doc["registry_source"]["path"] = str(feed / "registry.csv")
    settings.write_text(yaml.safe_dump(doc))
    env = {
        "TB_SETTINGS": str(settings),
        "TB_DATA_DIR": str(tmp_path),
        "TB_SECRETS_DIR": str(sec),
        "TB_LAKE_DIR": str(tmp_path / "lake"),
        "TB_RULESETS_DIR": str(tmp_path / "poc-rules"),
        "TB_ADAPTER_LAKE": "local",
        "TB_ENV": "TEST",
        "TB_ADAPTER_RUN": "thread",
        "TB_CONSOLE_SNAPSHOT": "2026-10-04",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, settings_update=doc, extra_env=env)
    box.orch.rulesets_dir = ruleset_repo(tmp_path / "poc-rules").path
    Flags(url=db_url, audit=box.orch.audit).seed()
    SiteStore(db_url).close()
    backend = HttpBackend(box.orch.cfg, box.store, AuditLog(box.audit_dir))
    Fhir(monkeypatch)
    monkeypatch.setattr(adapter_app, "_spawn", lambda work: work())
    with TestClient(adapter_app.app) as transport_client:
        backend.adapter.close()
        backend.adapter.client = transport_client
        started = backend.ingest()
        result = backend.adapter.get_json("/run/" + started["run"])
        assert result["state"] == "done" and result["report"]["passed"], result
    box.mail("SCREEN GZQO", sender="admin@hospa.test")
    box.orch.drain()
    job = box.orch.db.find(type_="SCREEN")[0]
    assert job.state == "done", job.error
    candidate = next(o for o in job.outputs or [] if o.filename.startswith("candidate_list_"))
    assert json.loads(box.store.get(candidate.minio_key))["rows"]
