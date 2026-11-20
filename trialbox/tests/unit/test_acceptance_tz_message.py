"""Time-zone resolution at the capacity command's entry point."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import config

from tests.unit.test_acceptance_capacity_power import TZ, _night
from tools import acceptance

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize("zone", [None, "", " \t "], ids=["unset", "empty", "whitespace"])
def test_missing_zone_refuses_without_overwriting_report(tmp_path: Path, repo_root: Path, zone: str | None) -> None:
    jobs = [] if zone is None else _night()
    (tmp_path / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    report = tmp_path / "acceptance" / "capacity.json"
    report.parent.mkdir()
    previous = b'{"passed": true}\n'
    report.write_bytes(previous)
    env = {**os.environ, "PYTHONPATH": str(repo_root)}
    if zone is None:
        env.pop("TB_TZ", None)
    else:
        env["TB_TZ"] = zone

    messages = []
    for _ in range(2):
        run = subprocess.run(
            [sys.executable, "-m", "tools.acceptance", "capacity", "--jobs", "jobs.json"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert run.returncode == 1
        assert run.stdout == ""
        assert len(run.stderr.splitlines()) == 1
        assert "the site's time zone is not set" in run.stderr
        assert "--tz" in run.stderr or "TB_TZ" in run.stderr
        assert "Traceback" not in run.stderr
        assert report.read_bytes() == previous
        messages.append(run.stderr)
    assert messages[0] == messages[1]


def test_configured_zone_and_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps(_night()), encoding="utf-8")
    args = ["capacity", "--jobs", str(jobs), "--ready-by", "07:00"]
    monkeypatch.setenv("TB_TZ", TZ)
    assert acceptance.main(["--out", str(tmp_path), *args]) == 0
    output = capsys.readouterr()
    assert output.err == "" and len(output.out.splitlines()) == 1
    assert output.out.startswith("capacity: PASS")
    report = (tmp_path / "capacity.json").read_bytes()
    assert json.loads(report)["spare_hours"] == 3.42

    for env_zone in (None, "UTC"):
        if env_zone is None:
            monkeypatch.delenv("TB_TZ")
        else:
            monkeypatch.setenv("TB_TZ", env_zone)
        out = tmp_path / (env_zone or "unset")
        assert acceptance.main(["--out", str(out), *args, "--tz", TZ]) == 0
        assert capsys.readouterr() == output
        assert (out / "capacity.json").read_bytes() == report


def test_configured_zone_without_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("TB_TZ", TZ)
    assert acceptance.main(["--out", str(tmp_path), "capacity", "--jobs", str(jobs)]) == 1
    assert "no job" in capsys.readouterr().out
    report = json.loads((tmp_path / "capacity.json").read_bytes())
    assert report["passed"] is False
    assert "spare_hours" not in report


def test_unexpected_zone_error_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    error = RuntimeError("probe")

    def fail(tz: str | None = None) -> str:
        raise error

    jobs = tmp_path / "jobs.json"
    jobs.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config, "site_tz", fail)
    with pytest.raises(RuntimeError, match="^probe$") as caught:
        acceptance.main(["--out", str(tmp_path), "capacity", "--jobs", str(jobs)])
    assert caught.value is error


def test_invalid_configured_zone_keeps_its_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("TB_TZ", "Invalid/Zone")
    with pytest.raises(config.ConfigError, match="not a valid IANA time zone"):
        acceptance.main(["--out", str(tmp_path), "capacity", "--jobs", str(jobs)])
