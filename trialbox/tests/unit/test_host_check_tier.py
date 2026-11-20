"""Plan 10 row 10G-11 (D-1342; review 16-20): the host check knows the box's tier and refuses a TPM-only disk unlock
on a desk-side tier in VALIDATION and PRODUCTION, under the poc host profile too; a server-room tier keeps the old
behaviour; an unknown tier is the stricter case and says so.

Fixtures per tier: the shipped records (``rtx5090``, ``rtxpro6000``: desk-side), a server-room record and a malformed
one in a test folder (``TB_TEST_TIERS_DIR``), a label with no record (``P-GB10``) and no label. Every run is against
the fake host of ``test_host_baseline`` (TB_HOST_ROOT and stub commands): nothing here reads the live host."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_host_baseline as hb

ROOT = Path(__file__).resolve().parents[2]
DESK = "[desk-side rule]"


def _helper() -> Any:
    spec = importlib.util.spec_from_file_location("host_tier", ROOT / "deploy" / "hardening" / "host_tier.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


host_tier = _helper()


def _server_room_records(tmp: Path) -> Path:
    """A tier folder whose ``rtx5090`` record says the box is in a server room (a fixture, not a shipped record)."""
    d = tmp / "tiers"
    d.mkdir(exist_ok=True)
    rec = {"schema": "tb-tier-record/1", "profile": "rtx5090", "tier": "small",
           "fields": {"desk_side": {"basis": "declared", "value": False, "source": "a test fixture"}}}  # fmt: skip
    (d / "rtx5090.json").write_text(json.dumps(rec), encoding="utf-8")
    return d


def _malformed_records(tmp: Path) -> Path:
    d = tmp / "tiers"
    d.mkdir(exist_ok=True)
    (d / "rtx5090.json").write_text("{ not json", encoding="utf-8")
    return d


# label, tiers folder maker (None: the shipped records), the class the host check must take
TIERS = {
    "rtx5090": ("P-5090", None, "desk-side"),
    "rtxpro6000": ("P-PRO6000", None, "desk-side"),
    "server-room": ("P-5090", _server_room_records, "server-room"),
    "gb10 (no record)": ("P-GB10", None, "unknown"),
    "no label": ("", None, "unknown"),
    "malformed record": ("P-5090", _malformed_records, "unknown"),
}


def _run(tmp: Path, tier: str, *, env_name: str, poc: bool, tpm_only: bool = True) -> subprocess.CompletedProcess[str]:
    label, maker, _ = TIERS[tier]
    args, env = hb._box(tmp, tpm_only=tpm_only, env_name=env_name)
    envf = Path(args[args.index("--env") + 1])
    extra = (f"TB_PROFILE={label}\n" if label else "") + ("TB_HOST_PROFILE=poc\n" if poc else "")
    envf.write_text(envf.read_text(encoding="utf-8") + extra, encoding="utf-8")
    if maker is not None:
        env["TB_TEST_TIERS_DIR"] = str(maker(tmp))
    return hb._sh(args, env)


@pytest.mark.parametrize("tier", list(TIERS))
def test_the_helper_classifies_each_tier(tmp_path: Path, tier: str) -> None:
    label, maker, want = TIERS[tier]
    kind, line = host_tier.classify(label, maker(tmp_path) if maker else None)
    assert kind == want, line
    assert line.startswith("WARN  tier unknown" if want == "unknown" else "PASS  tier: "), line
    if want == "unknown":
        assert "treated as a desk-side box, the stricter case" in line


@pytest.mark.parametrize("tier", list(TIERS))
def test_check_host_reports_the_tier(tmp_path: Path, tier: str) -> None:
    r = _run(tmp_path, tier, env_name="PRODUCTION", poc=False, tpm_only=False)
    want = TIERS[tier][2]
    assert r.returncode == 0, r.stdout + r.stderr
    if want == "desk-side":
        assert "PASS  tier: " in r.stdout and "a desk-side box" in r.stdout, r.stdout
    elif want == "server-room":
        assert "PASS  tier: " in r.stdout and "a server-room box" in r.stdout, r.stdout
    else:
        assert "WARN  tier unknown" in r.stdout and "the stricter case" in r.stdout, r.stdout


@pytest.mark.parametrize("env_name", ["VALIDATION", "PRODUCTION"])
@pytest.mark.parametrize("tier", [t for t, v in TIERS.items() if v[2] != "server-room"])
def test_a_desk_side_or_unknown_tier_fails_a_tpm_only_unlock_with_the_reason(
    tmp_path: Path, tier: str, env_name: str
) -> None:
    r = _run(tmp_path, tier, env_name=env_name, poc=False)
    assert r.returncode == 1, r.stdout
    line = next(ln for ln in r.stdout.splitlines() if "TPM2 without a PIN" in ln)
    assert line.startswith("FAIL  ") and DESK in line, line
    for what in ("Tang", "PIN", "passphrase"):
        assert what in line, line
    if TIERS[tier][2] == "unknown":
        assert "the tier is unknown" in line, line


@pytest.mark.parametrize("tier", [t for t, v in TIERS.items() if v[2] != "server-room"])
def test_the_poc_profile_does_not_relax_it_on_validation(tmp_path: Path, tier: str) -> None:
    """Review 16 section 1: nothing stopped an installer choosing TPM-only on a VALIDATION box; before 10G-11 the poc
    profile turned this FAIL into a WARN."""
    r = _run(tmp_path, tier, env_name="VALIDATION", poc=True)
    assert r.returncode == 1, r.stdout
    line = next(ln for ln in r.stdout.splitlines() if "TPM2 without a PIN" in ln)
    assert line.startswith("FAIL  ") and DESK in line and "[host profile poc]" not in line, line
    assert "1 baseline check(s) failed" in r.stdout, r.stdout


def test_a_server_room_tier_keeps_the_old_behaviour(tmp_path: Path) -> None:
    r = _run(tmp_path / "v", "server-room", env_name="VALIDATION", poc=True)
    assert r.returncode == 0, r.stdout
    line = next(ln for ln in r.stdout.splitlines() if "TPM2 without a PIN" in ln)
    assert line.startswith("WARN  ") and line.endswith("[host profile poc]") and DESK not in line, line
    r = _run(tmp_path / "p", "server-room", env_name="PRODUCTION", poc=False)
    assert r.returncode == 1, r.stdout
    line = next(ln for ln in r.stdout.splitlines() if "TPM2 without a PIN" in ln)
    assert line.startswith("FAIL  ") and DESK not in line, line


@pytest.mark.parametrize("env_name", ["DEV", "TEST"])
def test_dev_and_test_are_unchanged_on_a_desk_side_tier(tmp_path: Path, env_name: str) -> None:
    r = _run(tmp_path, "rtx5090", env_name=env_name, poc=True)
    line = next(ln for ln in r.stdout.splitlines() if "TPM2 without a PIN" in ln)
    assert line.startswith("WARN  ") and DESK not in line, line


def test_a_desk_side_tier_passes_tang_and_tpm(tmp_path: Path) -> None:
    r = _run(tmp_path, "rtx5090", env_name="VALIDATION", poc=True, tpm_only=False)
    assert "needs a Tang server" in r.stdout and DESK not in r.stdout, r.stdout


def test_the_helper_runs_as_a_script(tmp_path: Path) -> None:
    envf = tmp_path / ".env"
    envf.write_text("TB_PROFILE=P-PRO6000\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "deploy/hardening/host_tier.py"), "--env", str(envf)],
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 0 and r.stdout.splitlines()[0] == "desk-side", r.stdout + r.stderr


@pytest.mark.parametrize("kind", ["directory", "missing env"])
def test_the_helper_never_raises(tmp_path: Path, kind: str) -> None:
    d = tmp_path / "tiers"
    d.mkdir()
    if kind == "directory":
        (d / "rtx5090.json").mkdir()
        assert host_tier.classify("P-5090", d)[0] == "unknown"
    else:
        assert host_tier.env_label(tmp_path / "absent.env") == ""
