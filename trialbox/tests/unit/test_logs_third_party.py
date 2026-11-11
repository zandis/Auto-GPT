"""T-209c (D-406, review OPS-035): third-party service logs are collected apart, marked D3 and kept a short time;
PostgreSQL logs no failed statement. Before this change every service's log went into one ``services`` tree for 365
days."""

from __future__ import annotations

import gzip
import stat
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from tools.trialbox import logs as tl

ROOT = Path(__file__).resolve().parents[2]


def test_third_party_logs_go_apart_marked_d3_and_owner_only(tmp_path: Path) -> None:
    def run(argv: Any) -> bytes:
        if "ps" in argv:
            return b"orchestrator\ndb\nfhir-store\nconsole\nllm-service\n"
        return f"log of {argv[-1]}\n".encode()

    files = tl.collect(tmp_path / "deploy", date(2026, 11, 8), tmp_path / "logs", run, tz="UTC")
    ours = tmp_path / "logs" / "services" / "2026-11-08"
    apart = tmp_path / "logs" / "third-party" / "2026-11-08"
    assert sorted(p.name for p in ours.iterdir()) == ["console.log.gz", "orchestrator.log.gz"]
    assert sorted(p.name for p in apart.iterdir()) == ["CLASS", "db.log.gz", "fhir-store.log.gz", "llm-service.log.gz"]
    assert len(files) == 5 and gzip.decompress((apart / "db.log.gz").read_bytes()) == b"log of db\n"
    assert (apart / "CLASS").read_text().startswith("D3:") and "support bundle" in (apart / "CLASS").read_text()
    assert stat.S_IMODE(apart.stat().st_mode) == 0o700 and stat.S_IMODE((apart / "db.log.gz").stat().st_mode) == 0o600
    assert stat.S_IMODE((ours / "console.log.gz").stat().st_mode) == 0o640


def test_third_party_days_are_pruned_on_their_own_window(tmp_path: Path) -> None:
    for tree in ("services", "third-party"):
        for d in ("2026-09-01", "2026-10-01", "2026-11-08"):
            (tmp_path / "logs" / tree / d).mkdir(parents=True)
    assert tl.prune(tmp_path / "logs", tl.DEFAULT_THIRD_PARTY_DAYS, date(2026, 11, 9), "third-party") == [
        "2026-09-01",
        "2026-10-01",
    ]
    assert tl.prune(tmp_path / "logs", tl.DEFAULT_LOGS_DAYS, date(2026, 11, 9)) == []
    assert tl.retention_days(tmp_path / "none.yaml", "third_party_logs_days", 30) == 30


def test_daily_prints_both_trees(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_TZ=UTC\nTB_LOG_DIR={tmp_path / 'logs'}\n")

    def run(argv: Any) -> bytes:
        return b"db\nconsole\n" if "ps" in argv else b"x\n"

    assert tl.main_action("collect", deploy, "2026-11-08", run) == 0
    out = capsys.readouterr().out
    assert "collected 1 service logs" in out and "1 third-party logs (D3) apart" in out


def test_postgres_logs_no_failed_statement() -> None:
    db = yaml.safe_load((ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))["services"]["db"]
    cmd = db["command"]
    assert "log_min_error_statement=panic" in cmd and "log_parameter_max_length_on_error=0" in cmd
    docs = list(yaml.safe_load_all((ROOT / "deploy/platform/base/db.yaml").read_text(encoding="utf-8")))
    text = repr(docs)
    assert "log_min_error_statement=panic" in text and "log_parameter_max_length_on_error=0" in text
