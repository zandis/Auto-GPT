"""V-18 (D-1182; the integrator's ruling on #639): no licensed file and no table built from one reaches a backup
target. The backup keeps each system's name, version and hash (the terminology volume's manifest.json); a restore
reloads the tables from the hospital's folder, and until then the doctor names each one missing.

Synthetic data only: an invented ATC index (licensed, under a named person) and an invented site list (not licensed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from criteria_compiler.terminology import installed as inst
from tb_common.db import Database

from tests import pg_client
from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bs

PERSON = "Synthetic Person"


@pytest.fixture
def terminology(tmp_path: Path) -> Path:
    where = tmp_path / "terminology"
    atc = tmp_path / "atc.csv"
    atc.write_text("ATC code,ATC level name\nV99SY01,synthetic substance\n", encoding="utf-8")
    inst.install_atc(atc, where, accepted_by=PERSON, accepted_on="2026-11-23", version="2099")
    site = tmp_path / "site_dx.csv"
    site.write_text("local_code,code,display\nL1,M10.0,synthetic local\n", encoding="utf-8")
    inst.install_site_list(site, where, "dx", "icd10cm")
    return where


def test_the_volume_backup_leaves_out_the_licensed_tables_and_keeps_their_record(terminology: Path) -> None:
    keep, left = bk.select_files("terminology", terminology)
    assert "atc_index.parquet" not in keep and {"site_dx.parquet", "manifest.json"} <= set(keep)
    assert left == {"terminology tables built from a licensed copy (reloaded from the hospital's folder)": 1}
    line = json.loads((terminology / "manifest.json").read_text("utf-8"))["tables"]["atc_index"]
    assert line["version"] == "ATC 2099" and len(line["sha256"]) == 64  # name, version and hash: kept


def test_an_unreadable_manifest_keeps_no_table(terminology: Path) -> None:
    (terminology / "manifest.json").write_text("{not json", encoding="utf-8")
    keep, _ = bk.select_files("terminology", terminology)
    assert "manifest.json" in keep and not [k for k in keep if k.endswith(".parquet")]


def test_a_restored_box_has_no_licensed_table_and_the_doctor_names_it(
    terminology: Path, tmp_path: Path, db_url: str
) -> None:
    Database.connect(db_url, "site").migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY)"])
    priv, pub = tmp_path / "usb" / "backup.key", tmp_path / "box" / "backup.pub"
    bk.keygen(priv, pub)
    env = {**pg_client.env(), "TB_DB_URL": db_url, "TB_SITE_ID": "SYN"}
    (made,) = bk.backup([tmp_path / "nas"], pub, env=env, dirs={"terminology": terminology})
    assert b"V99SY01" not in made.read_bytes() and b"synthetic substance" not in made.read_bytes()
    restored = tmp_path / "restored"
    out = bk.restore(made, priv, env=env, dirs={"terminology": restored}, public_key=pub, keep_to=tmp_path / "kept")
    assert out["ok"] and not (restored / "atc_index.parquet").exists() and (restored / "site_dx.parquet").exists()
    problems = {t.name: t.problem for t in inst.status(restored) if t.problem}
    assert problems == {"atc_index": "in the manifest but its file is missing"}


def test_the_host_files_leave_out_the_hospitals_folder(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    licensed = deploy / "site" / "terminology"
    (licensed / "snomed").mkdir(parents=True)
    (licensed / "snomed" / "sct2_Concept_Snapshot_INT_20990131.txt").write_text("id\n1000001\n", encoding="utf-8")
    (licensed / "acceptance.json").write_text(json.dumps({"accepted_by": PERSON}), encoding="utf-8")
    (deploy / "site" / "registry.site.yaml").write_text("pins: {}\n", encoding="utf-8")
    (deploy / "site" / "needed.jsonl").write_text("{}\n", encoding="utf-8")
    (deploy / ".env").write_text("TB_SITE_ID=SYN\n", encoding="utf-8")
    ops = bs.ComposeOps(deploy, lambda *a, **k: "")
    taken = ops.host_files(tmp_path / "host")
    copied = sorted(str(p.relative_to(tmp_path / "host")) for p in (tmp_path / "host").rglob("*") if p.is_file())
    assert "site" in taken and copied == ["deploy.env", "site/needed.jsonl", "site/registry.site.yaml"]
