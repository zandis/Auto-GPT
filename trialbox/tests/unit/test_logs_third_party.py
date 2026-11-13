"""T-209c (D-406, review OPS-035): third-party service logs are collected apart, marked D3 and kept a short time;
PostgreSQL logs no failed statement. Before this change every service's log went into one ``services`` tree for 365
days."""

from __future__ import annotations

import gzip
import json
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
    assert sorted(p.name for p in ours.iterdir()) == ["COVERAGE.json", "console.log.gz", "orchestrator.log.gz"]
    assert sorted(p.name for p in apart.iterdir()) == [
        "CLASS",
        "COVERAGE.json",
        "db.log.gz",
        "fhir-store.log.gz",
        "llm-service.log.gz",
    ]
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


def test_each_tree_has_its_own_coverage_and_gaps_reads_both(tmp_path: Path) -> None:
    def run(argv: Any) -> bytes:
        if "--services" in argv:
            return b"orchestrator\ndb\n"
        if "-q" in argv:
            return b""  # no containers to inspect: no gap
        return b"2026-11-08T00:00:01Z line\n"

    tl.collect(tmp_path / "deploy", date(2026, 11, 8), tmp_path / "logs", run, tz="UTC", cap=1000)
    ours = json.loads((tmp_path / "logs/services/2026-11-08/COVERAGE.json").read_text())
    apart = tmp_path / "logs/third-party/2026-11-08/COVERAGE.json"
    assert set(ours["services"]) == {"orchestrator"} and set(json.loads(apart.read_text())["services"]) == {"db"}
    assert stat.S_IMODE(apart.stat().st_mode) == 0o600
    data = json.loads(apart.read_text())
    data["services"]["db"]["gap"] = True
    apart.write_text(json.dumps(data))
    assert tl.gaps(tmp_path / "logs", date(2026, 11, 8))[0] == ["db"]


def test_the_support_bundle_refuses_the_third_party_folder(tmp_path: Path) -> None:
    from tools import support_bundle as sb

    deploy = tmp_path / "deploy"
    f = deploy / "logs" / "third-party" / "2026-11-08" / "db.log.gz"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    assert sb.refusal(f, deploy, {})
    assert sb.refusal(f, deploy, {"TB_LOG_DIR": str(deploy / "logs")})


def _compose_images() -> dict[str, set[str]]:
    """Every service of every compose file with the images it runs (a custom tag such as ``!reset`` read as none)."""

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    out: dict[str, set[str]] = {}
    for f in sorted((ROOT / "deploy").glob("docker-compose*.yml")):
        body = yaml.load(f.read_text(encoding="utf-8"), Loader=Loader) or {}
        for svc, spec in (body.get("services") or {}).items():
            image = str((spec or {}).get("image") or "")
            if image:
                out.setdefault(svc, set()).add(image)
    return out


def test_every_service_on_an_image_trialbox_does_not_build_is_collected_apart() -> None:
    """Deep review 2026-11-13 (operations): OPS-035 came back in part. The second model server (``llm-verifier``)
    and the three swap helpers of the rtx5090 form run the vLLM image, whose log may carry a prompt, yet
    ``THIRD_PARTY`` named only ``llm-service``: their lines went into the ``services`` tree, which the support
    bundle copies. The rule is the image: a service that does not run a TrialBox-built image is third-party."""
    ours = ("trialbox-", "${TB_IMAGE", "${TB_EMBED_IMAGE", "${TB_DB_IMAGE")
    foreign = {
        svc
        for svc, images in _compose_images().items()
        if any(not any(img.startswith(p) or p.strip("${") in img for p in ours) for img in images)
    }
    assert {"llm-service", "llm-verifier"} <= foreign  # the rule sees the model servers
    assert foreign - tl.THIRD_PARTY == set()
