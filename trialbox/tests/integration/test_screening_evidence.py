"""The installed adapter owns only the clinical content it actually reviewed."""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter import cli
from adapter.mapping.engine import MAPPING_VERSION, Mapper, Mapping
from adapter.pipeline import AdapterConfig, run_ingest
from lake.source import lake_rows
from tb_common.crypto import load_key
from tb_common.flags import Flags
from tb_common.screening_inputs import ScreeningRefused, clearance_path
from tb_contracts import JobCreate

from tests.inproc_box import ROOT, Box, make_box
from tests.unit.test_dataflow_lake_p0 import _row
from tests.unit.test_t723_publish_night import N1, N2, Fhir, _night
from tools.ingest_local import run_local

FEED = ROOT / "tests/fixtures/synthetic_patients/site-a"


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Box, AdapterConfig, Path]:
    feed = tmp_path / "feed"
    shutil.copytree(FEED, feed)
    settings = yaml.safe_load((ROOT / "deploy/settings.example.yaml").read_bytes())
    settings["data_source"]["path"] = str(feed)
    settings["registry_source"]["path"] = str(feed / "registry.csv")
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(yaml.safe_dump(settings))
    sec = tmp_path / "sec"
    env = {
        "TB_SETTINGS": str(settings_path),
        "TB_SETTINGS_FILE": str(settings_path),
        "TB_DATA_DIR": str(tmp_path),
        "TB_LAKE_DIR": str(tmp_path / "lake"),
        "TB_RULESETS_DIR": str(tmp_path / "box/repo"),
        "TB_SECRETS_DIR": str(sec),
        "TB_ADAPTER_LAKE": "local",
        "TB_LAKE_EMBEDDER": "hash",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.main(["keys-init"]) == 0
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, settings_update=settings, extra_env=env)
    Flags(url=box.orch.db.url, audit=box.orch.audit).seed()
    cfg, _, _ = cli.build_config()
    return box, cfg, feed


def test_lake_inventory_distinguishes_clinical_values() -> None:
    hashes = []
    for value in [4, 9]:
        row = {"resourceType": "Observation", "id": "7", "valueQuantity": {"value": value}}
        meta: dict[str, str] = {}
        lake_rows({"Observation": [row]}, {}, tz="Asia/Taipei", snapshot=N1, source="legacy", inventory=meta)
        hashes.append(meta["lake"])
    assert hashes[0] != hashes[1]


@pytest.mark.parametrize("fault", ["other_work_directory", "missing_registry"])
def test_local_ingest_cannot_clear_installed_inputs(installed: tuple[Box, AdapterConfig, Path], fault: str) -> None:
    box, cfg, feed = installed
    root = cfg.lake_dir.parent
    if fault == "missing_registry":
        (feed / "registry.csv").unlink()
    work = root / "other" if fault == "other_work_directory" else root
    with contextlib.suppress(ScreeningRefused):
        run_local(
            feed,
            work,
            site_key=load_key(cfg.secrets_dir / "site_hmac.key"),
            snapshot=N1,
            screening_site=box.orch.cfg,
            contracts=False,
        )
    assert not clearance_path(root).exists()


@pytest.mark.parametrize("fault", ["held_duplicate", "verify", "carried_bulk", "retry"])
def test_mapped_evidence_tracks_issued_rows(
    installed: tuple[Box, AdapterConfig, Path], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    _, cfg, site_feed = installed
    root = cfg.lake_dir.parent
    # Small mapped feed. The producer sees the same mapper, merge and two-step publish as a full site.
    cfg.first_night_all_tables = False
    cfg.registry = None
    feed = _night(root, "small", [_row("D1", N2)], ["10000001"])
    snapshot = N2
    since = None
    if fault == "carried_bulk":
        bulk = root / "bulk"
        bulk.mkdir()
        tag = {"system": MAPPING_VERSION, "code": Mapping.load(cfg.mapping_path).version}
        resources: list[tuple[str, dict[str, Any]]] = [
            ("Patient", {"id": "10000001"}),
            ("Observation", {"id": "7", "subject": {"reference": "Patient/10000001"}}),
        ]
        for kind, resource in resources:
            (bulk / f"{kind}.ndjson").write_text(json.dumps({"resourceType": kind, "meta": {"tag": [tag]}, **resource}))
        first = run_ingest(cfg, "fhir_bulk", str(bulk), snapshot=N1, validate=False, load_fhir=False)
        assert first.passed, first.errors
        since = N1
    elif fault == "retry":
        fhir = Fhir(monkeypatch)
        fhir.down = True
        first = run_ingest(cfg, "csv", feed, snapshot=snapshot, validate=False)
        assert not first.passed and first.lake and first.lake.generation
        fhir.down = False
    elif fault == "verify":
        from adapter import site_profile
        from tb_common.site_profile import load

        from tests.unit.test_site_profile import _manifest, _profile

        cfg.site_profile = _profile(root / "profile", _manifest(site_id=cfg.site_id))
        site_profile.activate(
            load(cfg.site_profile),
            cfg.lake_dir,
            site_id=cfg.site_id,
            by="steward",
            audit_dir=cfg.audit_dir,
            tz=cfg.tz,
            door="csv",
        )
        feed = str(site_feed)
    else:
        original = Mapper.map_table

        def mapped(mapper: Mapper, table: str, rows: Any) -> Iterator[dict[str, Any]]:
            for row in original(mapper, table, rows):
                if row["resourceType"] == "Condition":
                    yield {**row, "review_tag": "held"}
                yield row

        monkeypatch.setattr(Mapper, "map_table", mapped)
    rep = run_ingest(cfg, "csv", feed, since=since, snapshot=snapshot, validate=False, load_fhir=fault == "retry")
    assert rep.passed, rep.errors
    records = list((root / "screening-inputs").glob(f"{snapshot}.g*/GZQO/*.json"))
    assert bool(records) == (fault == "retry")


def test_shipped_cohort_uses_pi_recipient(installed: tuple[Box, AdapterConfig, Path]) -> None:
    from console.sitestore import SiteStore

    box, cfg, feed = installed
    SiteStore(box.orch.db.url).close()
    assert run_ingest(cfg, "csv", str(feed), snapshot="2026-10-04", validate=False, load_fhir=False).passed
    job = box.orch.create(
        JobCreate(type="SCREEN", ruleset="RA-COH", requested_by="pi@hospa.test", options={"scope": "hospital"})
    )
    box.orch.drain()
    saved = box.orch.db.get(job.job_id)
    assert saved and saved.state == "done", saved.error if saved else None
    candidate = next(o for o in saved.outputs or [] if o.filename.startswith("candidate_list_"))
    assert candidate.recipients == ["pi@hospa.test"]


def test_mapped_delta_retains_cleared_owner_stamps(installed: tuple[Box, AdapterConfig, Path]) -> None:
    _, cfg, _ = installed
    root = cfg.lake_dir.parent
    cfg.first_night_all_tables = False
    cfg.registry = None
    full = _night(root, "full", [_row("D1", N1)], ["10000001"])
    delta = _night(root, "delta", [_row("D2", N2)], ["10000001"])

    def stamps(day: str) -> dict[str, str]:
        (record,) = (root / "screening-inputs").glob(f"{day}.g*/GZQO/*.json")
        return {
            row["key"]: row["owner_rule_stamp"]
            for row in json.loads(record.read_bytes())["rows"]
            if row["key"].startswith("Condition/")
        }

    assert run_ingest(cfg, "csv", full, snapshot=N1, validate=False, load_fhir=False).passed
    first = stamps(N1)
    assert len(first) == 1
    assert run_ingest(cfg, "csv", delta, since=N1, snapshot=N2, validate=False, load_fhir=False).passed
    second = stamps(N2)
    assert len(second) == 2 and first.items() <= second.items()
