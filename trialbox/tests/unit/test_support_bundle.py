"""T-209b (D-405; WS-17.4, R-61, D-23): the PHI-free support bundle. Acceptance (TB-ASSESS-01 T-209 item 4): a
bundle scanned for chart numbers and names finds none; a planted log line is removed by the scanner and the run says
so. Negative: a bundle that would include /data is refused and nothing is written. The planted values are read from
the data-scan's own planted positives (tests/fixtures/data_scan/positives), never written here."""

from __future__ import annotations

import gzip
import json
import os
import stat
import tarfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import data_scan as ds
from tools import support_bundle as sb
from tools.trialbox.__main__ import main as trialbox_main

POS = Path(__file__).resolve().parents[1] / "fixtures" / "data_scan" / "positives"
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
FAKE_PASSWORD = "not-a-real-pw-" + "x" * 8  # a synthetic secret value: it must not reach the bundle
DAYS = ["2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10"]


def _planted(pid: str) -> str:
    """The first planted line of one pattern's positives file (fictional, allowlisted only by that file's path)."""
    return next(x for x in (POS / f"{pid}.txt").read_text(encoding="utf-8").splitlines() if x and x[0] != "#")


def _gz(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(text.encode("utf-8"))


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR"):
        monkeypatch.delenv(k, raising=False)
    deploy = tmp_path / "deploy"
    logs = tmp_path / "logs"
    (deploy / "secrets").mkdir(parents=True)
    (deploy / "secrets" / "backup.pub").write_text("public\n", encoding="utf-8")
    (deploy / ".env").write_text(
        "TB_TZ=Asia/Taipei\n"
        f"TB_LOG_DIR={logs}\n"
        f"TB_AUDIT_HOST_DIR={tmp_path / 'audit'}\n"
        f"POSTGRES_PASSWORD={FAKE_PASSWORD}\n"
        "TB_METRICS_TOKEN_FILE=/run/secrets/metrics.token\n"
        f"SMTP_PASS={FAKE_PASSWORD}\n"
        f"IMAP_PASS={FAKE_PASSWORD}\n"
        f"TB_DB_PW_LAKE={FAKE_PASSWORD}\n"
        f"TB_KEK_PASSPHRASE={FAKE_PASSWORD}\n"
        f"TB_DB_URL=postgresql://tb:{FAKE_PASSWORD}@db:5432/tb\n",
        encoding="utf-8",
    )
    (deploy / "settings.yaml").write_text('mrn_regex: "^\\\\d{8}$"\n', encoding="utf-8")
    (deploy / "updates").mkdir()
    (deploy / "updates" / "history.jsonl").write_text('{"at": "2026-11-01", "step": "verified", "ok": true}\n')
    for day in DAYS:
        _gz(logs / "services" / day / "console.log.gz", f"{day}T01:00:00Z console | GET /healthz 200\n")
        _gz(logs / "services" / day / "db.log.gz", f"{day} ERROR: duplicate key value\n")
        _gz(logs / "services" / day / "fhir-store.log.gz", f"{day} HAPI resource\n")
    # the newest day of the console log carries the planted lines
    _gz(
        logs / "services" / DAYS[-1] / "console.log.gz",
        "2026-11-10T01:00:00Z console | job started\n"
        f"2026-11-10T01:00:01Z console | {_planted('tw_id')}\n"
        f"2026-11-10T01:00:02Z console | {_planted('cjk_name_dob')}\n"
        "2026-11-10T01:00:03Z console | lookup 31415926 done\n"
        "2026-11-10T01:00:04Z console | job finished\n",
    )
    return deploy


def fake_runner(argv: Sequence[str], timeout: int) -> tuple[int, str]:
    cmd = " ".join(argv)
    if cmd.endswith(" config"):
        return 0, f"services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: {FAKE_PASSWORD}\n      PGTZ: UTC\n"
    if cmd.endswith("ps --all -q"):
        return 0, "abc123\n"
    if argv[0] == "docker" and argv[1] == "inspect":
        return 0, "/trialbox-console-1 restarts=2 status=running health=healthy started=2026-11-10T00:00:00Z\n"
    if argv[0] == "nvidia-smi":
        return 127, "not run: FileNotFoundError"
    return 0, f"ran {argv[-1]}\n"


def _members(path: Path) -> dict[str, str]:
    with tarfile.open(path, "r:gz") as tar:
        return {
            m.name.removeprefix("support/"): tar.extractfile(m).read().decode("utf-8")  # type: ignore[union-attr]
            for m in tar.getmembers()
        }


def test_bundle_holds_the_box_state_and_no_patient_data(box: Path, tmp_path: Path) -> None:
    said: list[str] = []
    out = sb.build(box, tmp_path / "usb", runner=fake_runner, now=NOW, say=said.append)
    assert out.name == "trialbox-support-20261111T030000Z.tar.gz"
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    m = _members(out)
    for name in ("MANIFEST.json", "ops-snapshot.json", "health.json", "release.json", "history.jsonl",
                 "env.redacted", "audit-verify.json", "cmd/doctor.json", "cmd/compose-config.yaml",
                 "cmd/restarts.txt", "cmd/df.txt", "cmd/nvidia-smi.txt"):  # fmt: skip
        assert name in m, name
    # the last three collected days of TrialBox's own services; never the database's or HAPI's
    assert sorted(n for n in m if n.startswith("logs/")) == [f"logs/{d}/console.log" for d in DAYS[1:]]
    manifest = json.loads(m["MANIFEST.json"])
    left = " ".join(r["what"] for r in manifest["left_out"])
    assert "logs of db" in left and "logs of fhir-store" in left
    # the planted lines: the scrubber replaced the ID and the chart number, the scan removed the name line, and said so
    newest = m[f"logs/{DAYS[-1]}/console.log"]
    assert "job started" in newest and "job finished" in newest
    assert "[TWID]" in newest and "[MRN]" in newest and "31415926" not in newest
    assert "[line removed by the data-handling scan]" in newest
    for pid in ("tw_id", "cjk_name_dob"):
        planted = _planted(pid)
        assert not any(planted in text for text in m.values()), pid
    changed = manifest["changed"][f"logs/{DAYS[-1]}/console.log"]
    assert changed["lines_removed"] >= 1 and "cjk_name_dob" in changed["patterns"] and changed["redacted"] >= 2
    assert any("removed" in s and "cjk_name_dob" in s for s in said) and "scans clean" in said[-1]
    # secrets: names kept, values redacted, file paths kept
    assert not any(FAKE_PASSWORD in text for text in m.values())
    assert "POSTGRES_PASSWORD=[redacted]" in m["env.redacted"]
    for name in ("SMTP_PASS", "IMAP_PASS", "TB_DB_PW_LAKE", "TB_KEK_PASSPHRASE"):  # OPS-002 (review of 2026-11-12)
        assert f"{name}=[redacted]" in m["env.redacted"], name
    assert "TB_METRICS_TOKEN_FILE=/run/secrets/metrics.token" in m["env.redacted"]
    assert "postgresql://[redacted]@db" in m["env.redacted"]
    assert (
        "POSTGRES_PASSWORD: [redacted]" in m["cmd/compose-config.yaml"] and "PGTZ: UTC" in m["cmd/compose-config.yaml"]
    )
    assert "restarts=2" in m["cmd/restarts.txt"] and m["cmd/nvidia-smi.txt"].startswith("# exit 127")
    # every file is listed with its hash; the whole archive scans clean
    assert {f["name"] for f in manifest["files"]} == set(m) - {"MANIFEST.json"}
    assert ds.run([out], in_repo=False) == []


def test_a_bundle_that_would_include_data_is_refused(box: Path, tmp_path: Path) -> None:
    usb = tmp_path / "usb"
    with pytest.raises(sb.BundleRefused, match="/data"):
        sb.build(box, usb, add=[Path("/data/ingest_report.json")], runner=fake_runner, now=NOW, say=lambda _: None)
    assert not usb.exists() or not any(usb.iterdir())


def test_a_link_into_data_or_secrets_is_refused(box: Path, tmp_path: Path) -> None:
    link = tmp_path / "innocent.json"
    link.symlink_to("/data/lake/patients.json")
    assert "under /data" in str(sb.refusal(link, box, {}))
    assert "secrets" in str(sb.refusal(box / "secrets" / "backup.pub", box, {}))
    target = tmp_path / "nas"
    assert sb.refusal(target / "x.json", box, {"TB_BACKUP_TARGETS": str(target)})
    for name in ("trialbox-a-20261110T000000Z.tbbak", "backup.key", ".env", "pidmap.json", "metrics.token"):
        assert sb.refusal(tmp_path / name, box, {}), name
    ok = tmp_path / "ingest_report.json"
    assert sb.refusal(ok, box, {}) is None


def test_an_added_file_is_scrubbed_and_scanned(box: Path, tmp_path: Path) -> None:
    rep = tmp_path / "ingest_report.json"
    rep.write_text(f'{{"rows": 120}}\n{_planted("cjk_name_dob")}\n', encoding="utf-8")
    out = sb.build(box, tmp_path / "usb", add=[rep], commands=False, now=NOW, say=lambda _: None)
    m = _members(out)
    assert '"rows": 120' in m["added/ingest_report.json"]
    assert _planted("cjk_name_dob") not in m["added/ingest_report.json"]
    assert not any(n.startswith("cmd/") for n in m)


def test_a_file_the_scan_cannot_read_is_refused(box: Path, tmp_path: Path) -> None:
    blob = tmp_path / "blob.bin"
    blob.write_bytes(bytes(range(256)) * 4)
    usb = tmp_path / "usb"
    with pytest.raises(sb.BundleRefused, match="not a UTF-8 text file"):
        sb.build(box, usb, add=[blob], commands=False, now=NOW, say=lambda _: None)
    assert not usb.exists() or not any(usb.iterdir())


def test_redact_secrets() -> None:
    text, n = sb.redact_secrets(
        "TB_LLM_API_KEY=abc\nTB_SECRETS_DIR=/run/secrets\nSMTP_URL=smtp://u:p@mail:25\n  api_token: ''\nTB_TZ=Asia/Taipei\n"
    )
    assert text.splitlines() == ["TB_LLM_API_KEY=[redacted]", "TB_SECRETS_DIR=/run/secrets",
                                 "SMTP_URL=smtp://[redacted]@mail:25", "  api_token: ''", "TB_TZ=Asia/Taipei"]  # fmt: skip
    assert n == 2


def test_trialbox_command(box: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    usb = tmp_path / "usb"
    assert trialbox_main(["support-bundle", "--deploy", str(box), "--out", str(usb), "--no-commands"]) == 0
    assert "scans clean" in capsys.readouterr().out
    assert len(list(usb.glob("trialbox-support-*.tar.gz"))) == 1
    assert trialbox_main(["support-bundle", "--deploy", str(box), "--out", str(usb), "--no-commands",
                          "--add", "/data/x.json"]) == 2  # fmt: skip
    assert "refused, nothing written" in capsys.readouterr().err
    assert os.listdir(usb) == [next(usb.glob("*.tar.gz")).name]
