"""U-5 (D-1280, the integrator's go on #639): the first real-data run, at any time, is the step that needs the data
source, the chart-number rule, the backup target, key and alarm, the audit share and the hospital's name.

SAFE-1 A3: an ingest or a back-fill with any of them missing, not usable or a stand-in is never refused for them. On
a PRODUCTION box the run goes on and the items are audited once (``ingest.site_needs``, the keys only) for the page
"Information still needed"; on a PoC box the run goes on with the stand-ins and nothing is audited. The backup is
asked where records nobody can make again begin, a study opening (``tests/unit/test_study_records_gate.py``).

The backup key is on the host only. The service reads ``host-given.json`` through its read-only mount, and
``backup-keygen`` writes that list when it makes the box's key. Synthetic values only."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from adapter import pipeline
from adapter.pipeline import AdapterConfig
from tb_common import site_needs
from tb_common.crypto import create_key

GIVEN_ENV = {
    "TB_SOURCE_DIR": "/data/source/site-a",
    "TB_CHARTNO_RULE": "kept_as_written",
    "TB_BACKUP_TARGETS": "/mnt/backup",
    "TB_BACKUP_MAILTO": "it@hospa.test",
    "TB_AUDIT_ANCHOR_TARGETS": "/mnt/audit",
}
SETTINGS = {"site": {"name": "Synthetic Hospital A"}, "data_source": {"type": "csv"}}


def _cfg(tmp_path: Path, settings: dict[str, Any] | None = None) -> AdapterConfig:
    return AdapterConfig(
        lake_dir=tmp_path / "lake",
        secrets_dir=tmp_path / "secrets",
        mapping_path=tmp_path / "mapping.yaml",
        site_id="DEMO-A",
        tz="Asia/Taipei",
        audit_dir=tmp_path / "audit",
        site_settings=SETTINGS if settings is None else settings,
    )


def _box(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env: str,
    *,
    given: dict[str, str] | None = None,
    key_on_host: bool = True,
    stand_ins: tuple[str, ...] = (),
) -> Path:
    """A box's environment, and its ``deploy/site/needs`` as the services' read-only mount."""
    monkeypatch.setenv("TB_ENV", env)
    for k in (*GIVEN_ENV, "TB_SOURCE_DSN", "TB_BACKUP_ALERT_WATCHER", "TB_BACKUP_ALERT_CMD"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (GIVEN_ENV if given is None else given).items():
        monkeypatch.setenv(k, v)
    deploy = tmp_path / "deploy"
    if key_on_host:
        (deploy / "secrets").mkdir(parents=True)
        (deploy / "secrets" / "backup.pub").write_text("synthetic public key\n", encoding="utf-8")
    site_needs.write_host_given(deploy)
    site_needs.write_stand_ins(deploy, stand_ins)
    monkeypatch.setattr(site_needs, "MOUNTED", (deploy / site_needs.HOST_GIVEN).parent)
    return deploy


def _events(tmp_path: Path) -> list[dict[str, Any]]:
    lines = [ln for f in sorted((tmp_path / "audit").glob("*.jsonl")) for ln in f.read_text().splitlines()]
    return [json.loads(ln) for ln in lines]


def _refusals(tmp_path: Path) -> list[dict[str, Any]]:
    events = _events(tmp_path)
    return [e for e in events if e["event"] == "ingest.failed" and e["detail"].get("refused") == "site_needs"]


def _warnings(tmp_path: Path) -> list[dict[str, Any]]:
    return [e for e in _events(tmp_path) if e["event"] == "ingest.site_needs"]


def test_production_runs_with_everything_still_needed_and_audits_each_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SAFE-1 A3: was refused; the run goes on and the audit names every item (keys only, never a setting)."""
    _box(tmp_path, monkeypatch, "PRODUCTION", given={}, key_on_host=False)
    pipeline.refuse_site_needs(_cfg(tmp_path, {}), "2026-11-20", "csv")
    wanted = ["data_source", "chart_number", "backup_target", "backup_key", "backup_alarm", "audit_share", "site_name"]
    (event,) = _warnings(tmp_path)
    assert sorted(event["detail"]["needs"]) == sorted(wanted) and set(event["detail"]["needs"].values()) == {"missing"}
    assert "TB_" not in json.dumps(event) and _refusals(tmp_path) == []


def test_production_runs_when_every_item_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _box(tmp_path, monkeypatch, "PRODUCTION")
    pipeline.refuse_site_needs(_cfg(tmp_path), "2026-11-20", "csv")
    assert _refusals(tmp_path) == [] and _warnings(tmp_path) == []


def test_a_backup_key_the_host_does_not_have_is_audited_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _box(tmp_path, monkeypatch, "PRODUCTION", key_on_host=False)
    pipeline.refuse_site_needs(_cfg(tmp_path), "2026-11-20", "csv")  # SAFE-1 A3: was refused
    assert _warnings(tmp_path)[0]["detail"]["needs"] == {"backup_key": "missing"}


def test_a_stand_in_is_audited_not_refused_on_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _box(tmp_path, monkeypatch, "PRODUCTION", stand_ins=("chart_number", "site_name"))
    pipeline.refuse_site_needs(_cfg(tmp_path), "2026-11-20", "csv")  # SAFE-1 A3: was refused
    assert _warnings(tmp_path)[0]["detail"]["needs"] == {"chart_number": "stand_in", "site_name": "stand_in"}


@pytest.mark.parametrize("env", ["DEV", "TEST", "VALIDATION"])
def test_a_poc_box_runs_with_the_stand_ins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    _box(tmp_path, monkeypatch, env, given={}, key_on_host=False, stand_ins=("site_name",))
    pipeline.refuse_site_needs(_cfg(tmp_path, {}), "2026-11-20", "csv")
    assert _refusals(tmp_path) == [] and _warnings(tmp_path) == []


def test_a_night_with_the_backup_key_still_needed_is_published_and_audits_it_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_cluster_url: str
) -> None:
    """SAFE-1 A3: was refused before anything was read; a synthetic bulk export is now read and published on a
    PRODUCTION box whose backup key is still needed, and the item is audited once."""
    _box(tmp_path, monkeypatch, "PRODUCTION", key_on_host=False)
    monkeypatch.delenv("TB_DB_URL", raising=False)  # its own pid map below, not the shared one
    monkeypatch.setenv("TB_CHARTNO_RULE", "asis")  # a rule the night itself can read
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    create_key(sec / "pid_map.key")  # as the install ceremony makes it on a PRODUCTION box
    exp = tmp_path / "bulk"
    exp.mkdir()
    patients = [{"resourceType": "Patient", "id": f"p{i}", "gender": "female", "birthDate": "1970-01-01"}
                for i in range(3)]  # fmt: skip
    (exp / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in patients) + "\n", encoding="utf-8")
    sep = "&" if "?" in pg_cluster_url else "?"
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, site_id=f"A3-{tmp_path.name}", tz="Asia/Taipei",
                        audit_dir=tmp_path / "audit", site_settings=SETTINGS,
                        db_url=f"{pg_cluster_url}{sep}tb_prefix=a3night{os.getpid()}_",
                        mapping_path=Path(__file__).resolve().parents[2] / "services/adapter/mapping/tw_core/demo_his.yaml")  # fmt: skip
    rep = pipeline.run_ingest(cfg, "fhir_bulk", str(exp), snapshot="2026-11-20", load_fhir=False, rebuild_lake=False,
                              validate=False)  # fmt: skip
    assert rep.passed and not rep.held, rep.errors
    assert rep.counts.get("Patient") == 3
    (event,) = _warnings(tmp_path)
    assert event["detail"]["needs"] == {"backup_key": "missing"} and _refusals(tmp_path) == []


def test_the_host_names_the_backup_key_only_when_its_file_is_there(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    assert site_needs.write_host_given(deploy) == frozenset()
    (deploy / "secrets").mkdir()
    (deploy / "secrets" / "backup.pub").symlink_to(tmp_path / "elsewhere.pub")
    assert site_needs.host_given(deploy) == frozenset()  # a link is not the box's key
    (deploy / "secrets" / "backup.pub").unlink()
    (deploy / "secrets" / "backup.pub").write_text("synthetic public key\n", encoding="utf-8")
    assert site_needs.write_host_given(deploy) == {"backup_key"}
    path = deploy / site_needs.HOST_GIVEN
    assert json.loads(path.read_text(encoding="utf-8")) == {"format": "tb-host-given/1", "keys": ["backup_key"]}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert site_needs.read_host_given(deploy) == (frozenset({"backup_key"}), [])
    assert site_needs.mounted_files(path.parent) == {"secrets/backup.pub"}


def test_no_mount_names_no_file(tmp_path: Path) -> None:
    assert site_needs.mounted_files(tmp_path / "absent") == frozenset()


def test_backup_keygen_writes_the_hosts_list_for_the_boxs_own_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import __main__ as cli

    calls: list[Path] = []

    def written(deploy: Path) -> frozenset[str]:
        calls.append(deploy)
        return frozenset()

    monkeypatch.setattr(site_needs, "write_host_given", written)
    monkeypatch.setattr("tools.trialbox.backup.keygen", lambda private, public: "fp")
    monkeypatch.setattr("tb_common.rc1_refusals.check", lambda *a, **k: None)
    deploy = Path(cli.__file__).resolve().parents[2] / "deploy"
    assert cli.main(["backup-keygen", "--private", str(tmp_path / "k"), "--public", str(tmp_path / "b.pub")]) == 0
    assert calls == []  # a key made elsewhere is not the box's
    assert (
        cli.main(
            ["backup-keygen", "--private", str(tmp_path / "k"), "--public", str(deploy / "secrets" / "backup.pub")]
        )
        == 0
    )
    assert calls == [deploy]
