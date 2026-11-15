"""D-830: ``bundle-check`` knows a pulled registry image on the containerd image store.

The gates scan a registry image in its registry: the record names it by its config digest (``image_id``, from Trivy)
and by its index digest (``repo_digests``, the reference pinned before the scan), per platform. On the containerd
store the local image's Id is the index digest, so authelia, caddy, hapi and vllm read "is not a passing image of
this record" on lane G's box although each passed. The index digest counts only for the platform the gates scanned:
one index names every platform, and a platform that was not scanned did not pass."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from tools.supply_chain import __main__ as cli
from tools.supply_chain import release

pytestmark = pytest.mark.nodb

NOW = dt.datetime(2026, 11, 15, tzinfo=dt.UTC)
CONFIG = "sha256:" + "c" * 64
INDEX = "sha256:" + "1" * 64
REF = f"vllm/vllm-openai:v0.32.0@{INDEX}"


def _record(*, platform: str = "linux/amd64", report_mode: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "created": NOW.isoformat(),
        "images": [
            {
                "ref": REF,
                "platform": platform,
                "ok": True,
                "image_id": CONFIG,
                "repo_digests": [REF],
                "report_mode_findings": [{"id": "CVE-1"}] if report_mode else [],
            }
        ],
    }


def test_the_index_digest_matches_on_the_platform_the_gates_scanned() -> None:
    local = {"vllm/vllm-openai:v0.32.0": (INDEX, INDEX)}  # containerd store: Id and repo digest are the index
    plat = {"vllm/vllm-openai:v0.32.0": "linux/amd64"}
    assert release.bundle_problems(_record(), local, now=NOW, platforms=plat) == []


def test_another_platform_of_the_same_index_did_not_pass() -> None:
    local = {"vllm/vllm-openai:v0.32.0": (INDEX,)}
    assert release.bundle_problems(_record(), local, now=NOW, platforms={"vllm/vllm-openai:v0.32.0": "linux/arm64"})
    assert release.bundle_problems(_record(), local, now=NOW)  # no platform given: the index digest does not count


def test_a_report_mode_pass_or_an_unknown_digest_is_still_refused() -> None:
    plat = {"x": "linux/amd64"}
    assert release.bundle_problems(_record(report_mode=True), {"x": (INDEX,)}, now=NOW, platforms=plat)
    assert release.bundle_problems(_record(), {"x": ("sha256:" + "9" * 64,)}, now=NOW, platforms=plat)


def test_the_config_digest_still_matches_on_the_classic_store() -> None:
    assert release.bundle_problems(_record(), {"x": CONFIG}, now=NOW) == []


def test_bundle_check_passes_the_local_repo_digests_and_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _record()
    record["created"] = dt.datetime.now(dt.UTC).isoformat()
    gates = tmp_path / "gates.json"
    gates.write_text(json.dumps(record), encoding="utf-8")

    def inspect(ref: str) -> dict[str, Any]:  # what docker image inspect says on the containerd store
        return {"image_id": INDEX, "repo_digests": [f"vllm/vllm-openai@{INDEX}"], "platform": "linux/amd64"}

    monkeypatch.setattr(release, "inspect_local", inspect)
    assert cli.main(["bundle-check", "--gates", str(gates), "vllm/vllm-openai:v0.32.0"]) == 0
    assert "PASS" in capsys.readouterr().out
