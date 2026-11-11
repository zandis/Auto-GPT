"""T-628 (D-413): RUNBOOK §20 names every close-out step in order, the certificate has the NIST SP 800-88 Rev. 1
Appendix G fields in three languages, and ``trialbox decommission-plan`` lists every store from the settings and
changes nothing."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tools.trialbox import __main__ as tb_main
from tools.trialbox import decommission as dc

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "runbook" / "20-close-out-and-decommissioning.md"
CERT = ROOT / "docs" / "plan" / "sites" / "purge-certificate.md"
RECORD = ROOT / "docs" / "plan" / "sites" / "close-out-record.md"


def test_page_names_every_step_in_order() -> None:
    text = PAGE.read_text(encoding="utf-8")
    found = re.findall(r"^\*\*Step (\d), ([a-z-]+)\.\*\*", text, re.M)
    assert found == [(str(i), sid) for i, (sid, _) in enumerate(dc.STEPS, 1)]


@pytest.mark.parametrize(
    "needle",
    [
        # the freeze by the audit chain
        "audit_verify.py /data/audit --json",
        "--sign-head",
        "--heads",
        # the archive with checksums, verified
        "SHA256SUMS",
        "sha256sum -c SHA256SUMS",
        "trialbox backup-verify",
        "trialbox exports",
        # the purge by NIST SP 800-88 Rev. 1, every category, keys first
        "NIST SP 800-88 Rev. 1",
        "| Clear |",
        "| Purge |",
        "| Destroy |",
        "crypto-erase",
        # the certificate and the record
        "docs/plan/sites/purge-certificate.md",
        "docs/plan/sites/close-out-record.md",
        "decommission-plan --json",
    ],
)
def test_page_names_each_part(needle: str) -> None:
    assert needle in PAGE.read_text(encoding="utf-8")


def test_page_names_every_setting_the_plan_reads() -> None:
    text = PAGE.read_text(encoding="utf-8")
    src = (ROOT / "tools" / "trialbox" / "decommission.py").read_text(encoding="utf-8")
    places = {"TB_BACKUP_TARGETS", "TB_BACKUP_OFFBOX", "TB_PGBACKREST_REPO", "TB_AUDIT_ARCHIVE_DIR"}
    places |= {"TB_AUDIT_ANCHOR_TARGETS"}
    assert places <= set(re.findall(r'"(TB_[A-Z_]+)"', src))
    missing = sorted(p for p in places if f"`{p}`" not in text)
    assert not missing


def test_certificate_has_every_field_in_three_languages() -> None:
    text = CERT.read_text(encoding="utf-8")
    parts = re.split(r"^## [ABC]\. ", text, flags=re.M)
    assert len(parts) == 4, "English, 日本語 and 繁體中文"
    for part in parts[1:]:
        numbers = [int(n) for n in re.findall(r"^\| (\d+) \|", part, re.M)]
        assert numbers == list(range(1, 25))
        assert len(re.findall(r"^### [ABC]\.\d ", part, re.M)) == 6
    for word in ("Clear", "Purge", "Destroy", "Appendix G"):
        assert word in text


def test_record_lists_every_step() -> None:
    text = RECORD.read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d) ([a-z-]+) \|", text, re.M)
    assert rows == [(str(i), sid) for i, (sid, _) in enumerate(dc.STEPS, 1)]


def _box(tmp: Path) -> Path:
    deploy = tmp / "deploy"
    deploy.mkdir()
    (deploy / "docker-compose.yml").write_text(
        "services:\n  db:\n    image: x\n    volumes:\n      - db-pg:/var/lib/postgresql\n"
        "volumes:\n  db-pg:\n  audit-data:   # the chain\n  tb-secrets:\nx-other:\n  ignored:\n",
        encoding="utf-8",
    )
    (deploy / ".env").write_text(
        "TB_SITE_ID=site-a\n"
        'TB_BACKUP_TARGETS="/mnt/share/tb,/media/usb1"\n'
        "TB_BACKUP_OFFBOX=/mnt/iscsi\n"
        "TB_PGBACKREST_REPO=/mnt/share/pgbr\n"
        "TB_AUDIT_ARCHIVE_DIR=/mnt/share/audit-archive\n"
        "TB_AUDIT_ANCHOR_TARGETS=/mnt/share/anchors\n"
        "TB_MODELS_DIR=/srv/models\n"
        "# TB_EMBED_MODEL_PATH=/commented\n",
        encoding="utf-8",
    )
    return deploy


def test_plan_lists_every_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in [k for k in os.environ if k.startswith("TB_")]:
        monkeypatch.delenv(k)
    deploy = _box(tmp_path)
    p = dc.plan(deploy, dc.read_env(deploy))
    got = {(s["name"], s["where"]): (s["on_box"], s["action"]) for s in p["stores"]}
    vols = [s["name"] for s in p["stores"] if s["name"].startswith("volume ")]
    assert vols == ["volume db-pg", "volume audit-data", "volume tb-secrets"]
    assert got[("backup target", "/mnt/share/tb")] == (False, "purge")
    assert got[("backup target", "/media/usb1")] == (False, "purge")
    assert got[("declared off-box target", "/mnt/iscsi")] == (False, "purge")
    assert got[("pgBackRest repository", "/mnt/share/pgbr")] == (False, "purge")
    assert got[("audit archive", "/mnt/share/audit-archive")] == (False, "keep")
    assert got[("audit anchor folder", "/mnt/share/anchors")] == (False, "keep")
    assert got[("model weights", "/srv/models")] == (True, "purge")
    assert not any(s["name"] == "embedder weights" for s in p["stores"])
    assert {s["name"] for s in p["stores"] if s["action"] == "ask"} >= {"USB disks", "backup private key"}
    assert p["site"] == "site-a" and p["dry_run"] is True
    # the host disks come after every other on-box store
    on = [s["name"] for s in p["stores"] if s["on_box"]]
    assert on[-1] == "host disks"


def test_cli_prints_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for k in [k for k in os.environ if k.startswith("TB_")]:
        monkeypatch.delenv(k)
    deploy = _box(tmp_path)
    before = sorted((p.relative_to(tmp_path), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    assert tb_main.main(["decommission-plan", "--deploy", str(deploy), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [s["id"] for s in doc["steps"]] == [sid for sid, _ in dc.STEPS]
    assert tb_main.main(["decommission-plan", "--deploy", str(deploy)]) == 0
    out = capsys.readouterr().out
    assert "Step 8, certificate" in out and "Nothing was changed" in out
    assert sorted((p.relative_to(tmp_path), p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before


def test_process_environment_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _box(tmp_path)
    monkeypatch.setenv("TB_PGBACKREST_REPO", "/mnt/other")
    assert dc.read_env(deploy)["TB_PGBACKREST_REPO"] == "/mnt/other"
    assert dc.read_env(deploy, process_env=False)["TB_PGBACKREST_REPO"] == "/mnt/share/pgbr"
