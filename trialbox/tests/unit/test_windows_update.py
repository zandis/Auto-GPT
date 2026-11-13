"""NEW-WIN-5 (D-606): the update window, the driver kept off Windows Update, the shutdown right, and the versions.

Here: ``trialbox doctor``'s ``update_window`` and ``wsl2_versions`` on a fake ``/proc`` and a fake card; the Windows
facts judged by ``deploy/windows/wsl2_policy.py``; the installer's defaults held to the declared settings. The
installer's own logic is in ``tests/windows`` (Pester). Nothing here ran on Windows."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
from tb_common.config import DECLARED

from tools.trialbox.doctor import DoctorInputs, check_update_window, check_wsl2_versions

ROOT = Path(__file__).resolve().parents[2]
PS1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")
FACTS_PS1 = (ROOT / "deploy/windows/host_facts.ps1").read_text(encoding="utf-8")
WSL2 = "6.6.87.2-microsoft-standard-WSL2"
CARD = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"

_spec = importlib.util.spec_from_file_location("wsl2_policy_w5", ROOT / "deploy/windows/wsl2_policy.py")
assert _spec is not None and _spec.loader is not None
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)


def _inp(tmp: Path, *, kernel: str = WSL2, env: dict[str, str] | None = None, night: str | None = "02:00",
         driver: str | None = "581.15", record: dict[str, Any] | None = None, site: dict[str, Any] | None = None) -> DoctorInputs:  # fmt: skip
    proc, deploy = tmp / "proc", tmp / "deploy"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(kernel + "\n")
    for folder, doc in (("measured", record), ("site", site)):
        (deploy / folder).mkdir(parents=True)
        if doc is not None:
            (deploy / folder / "serving_config.rtxpro6000.json").write_text(json.dumps(doc))
    settings: dict[str, Any] = {"data_source": {"type": "csv", "nightly_at": night}} if night else {}
    return DoctorInputs(env=env or {}, settings=settings, deploy=deploy, proc=proc,
                        gpu_query=lambda: (CARD, driver) if driver else None)  # fmt: skip


def _record(driver: str = "581.15", **more: Any) -> dict[str, Any]:
    return {"schema": "tb-serving-config/1", "card": {"name": CARD, "driver": driver}, **more}


# ---------------------------------------------------------------------------------------------- the declared window


def test_the_installers_default_window_is_the_declared_setting() -> None:
    start = re.search(r"\[ValidateRange\(0, 23\)\]\[int\]\$UpdateWindowStart = (\d+)", PS1)
    hours = re.search(r"\[ValidateRange\((\d+), 23\)\]\[int\]\$UpdateWindowHours = (\d+)", PS1)
    assert start and hours
    assert start.group(1) == DECLARED["TB_WIN_UPDATE_WINDOW_START"].default
    assert hours.group(2) == DECLARED["TB_WIN_UPDATE_WINDOW_HOURS"].default
    # Windows protects at most 18 hours from restarts: a window is never shorter than the other six
    assert hours.group(1) == "6"


def test_a_plain_linux_host_has_no_update_window_and_no_windows_driver(tmp_path: Path) -> None:
    inp = _inp(tmp_path, kernel="6.8.0-48-generic")
    assert check_update_window(inp).status == "PASS" and "not WSL2" in check_update_window(inp).detail
    assert check_wsl2_versions(inp).status == "PASS" and "not WSL2" in check_wsl2_versions(inp).detail


def test_the_default_window_and_the_default_night_pass_and_the_room_is_said(tmp_path: Path) -> None:
    c = check_update_window(_inp(tmp_path))
    assert c.status == "PASS"
    assert (
        "from 19:00 to 01:00" in c.detail
        and "the night starts at 02:00 and has 17 h before the window opens" in c.detail
    )
    assert "not recorded on the box yet" in c.detail  # the length is not claimed


@pytest.mark.parametrize(
    ("night", "status"), [("19:00", "FAIL"), ("00:59", "FAIL"), ("23:30", "FAIL"), ("01:00", "PASS"), ("18:59", "PASS")]
)
def test_a_night_that_starts_inside_the_window_fails(tmp_path: Path, night: str, status: str) -> None:
    c = check_update_window(_inp(tmp_path, night=night))
    assert c.status == status, c.detail
    if status == "FAIL":
        assert f"the night starts at {night}, inside it" in c.detail and "-UpdateWindowStart" in c.detail


def test_the_boxs_own_window_is_the_one_judged(tmp_path: Path) -> None:
    env = {"TB_WIN_UPDATE_WINDOW_START": "12", "TB_WIN_UPDATE_WINDOW_HOURS": "8"}
    assert check_update_window(_inp(tmp_path, env=env)).status == "PASS"
    c = check_update_window(_inp(tmp_path / "b", env=env, night="13:00"))
    assert c.status == "FAIL" and "from 12:00 to 20:00" in c.detail


@pytest.mark.parametrize(
    ("key", "value"),
    [("TB_WIN_UPDATE_WINDOW_START", "24"), ("TB_WIN_UPDATE_WINDOW_HOURS", "5"), ("TB_WIN_UPDATE_WINDOW_START", "7pm")],
)
def test_a_window_windows_cannot_hold_is_never_a_pass(tmp_path: Path, key: str, value: str) -> None:
    c = check_update_window(_inp(tmp_path, env={key: value}))
    assert c.status == "FAIL" and key in c.detail


def test_settings_without_a_night_are_said_not_passed(tmp_path: Path) -> None:
    c = check_update_window(_inp(tmp_path, night=None))
    assert c.status == "WARN" and "no nightly_at" in c.detail


# ------------------------------------------------------------------------------------- the driver and the WSL2 kernel


def test_the_measured_driver_and_kernel_pass(tmp_path: Path) -> None:
    c = check_wsl2_versions(_inp(tmp_path, record=_record(wsl_kernel=WSL2)))
    assert c.status == "PASS" and "581.15" in c.detail and WSL2 in c.detail and "measured/serving_config" in c.detail


def test_another_driver_than_the_measured_one_is_red(tmp_path: Path) -> None:
    c = check_wsl2_versions(_inp(tmp_path, driver="591.44", record=_record(wsl_kernel=WSL2)))
    assert c.status == "FAIL"
    assert (
        "the NVIDIA driver is 591.44" in c.detail
        and "measured with 581.15" in c.detail
        and "windows/nvidia" in c.detail
    )


def test_another_wsl2_kernel_than_the_measured_one_is_red(tmp_path: Path) -> None:
    c = check_wsl2_versions(_inp(tmp_path, record=_record(wsl_kernel="5.15.167.4-microsoft-standard-WSL2")))
    assert c.status == "FAIL" and "WSL was updated" in c.detail


def test_a_record_without_a_kernel_is_a_warning_that_names_the_running_one(tmp_path: Path) -> None:
    c = check_wsl2_versions(_inp(tmp_path, record=_record()))
    assert c.status == "WARN" and "names no WSL2 kernel" in c.detail and WSL2 in c.detail


def test_the_sites_own_record_wins_over_the_vendors(tmp_path: Path) -> None:
    c = check_wsl2_versions(_inp(tmp_path, record=_record("570.00", wsl_kernel=WSL2), site=_record(wsl_kernel=WSL2)))
    assert c.status == "PASS" and "site/serving_config" in c.detail


def test_a_card_that_does_not_answer_is_red_and_a_card_without_a_record_is_not_passed(tmp_path: Path) -> None:
    c = check_wsl2_versions(_inp(tmp_path, driver=None, record=_record()))
    assert c.status == "FAIL" and "does not answer" in c.detail
    other = _record()
    other["card"]["name"] = "NVIDIA GeForce RTX 4090"
    c = check_wsl2_versions(_inp(tmp_path / "b", record=other))
    assert c.status == "WARN" and "compared with nothing" in c.detail


def test_the_vendors_shipped_record_has_the_fields_the_check_reads() -> None:
    for path in sorted((ROOT / "deploy/measured").glob("serving_config.*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["card"]["name"] and doc["card"]["driver"], path.name


# -------------------------------------------------------------------------- the Windows facts, judged from inside WSL2

BASE = {"facts_version": "1", "is_admin": "1"}
OURS = {"update_window": "19+6", "wu_au_options": "4", "wu_no_auto_update": "0", "wu_scheduled_install_day": "0",
        "wu_scheduled_install_time": "19", "wu_set_active_hours": "1", "wu_active_hours_start": "1",
        "wu_active_hours_end": "19", "wu_exclude_drivers": "1",
        "shutdown_at_sign_in": "0"}  # fmt: skip


def _lines(facts: dict[str, str], *, strict: bool = True) -> list[str]:
    v = policy.Verdicts(strict)
    for check in (policy.check_windows_update, policy.check_update_drivers, policy.check_shutdown_right):
        check({**BASE, **facts}, v)
    return list(v.lines)


def test_the_installers_window_held_by_windows_passes() -> None:
    lines = _lines(OURS)
    assert all(ln.startswith("PASS") for ln in lines), lines
    text = "\n".join(lines)
    assert "installs at 19:00 and restarts only from 19:00 to 1:00" in text
    assert "takes no drivers" in text and "the sign-in screen does not offer it" in text


@pytest.mark.parametrize("change", [{"wu_scheduled_install_time": "3"}, {"wu_set_active_hours": ""},
                                    {"wu_active_hours_start": "8"}, {"wu_active_hours_end": "17"}])  # fmt: skip
def test_a_window_windows_no_longer_holds_fails_on_a_production_box(change: dict[str, str]) -> None:
    lines = _lines({**OURS, **change})
    assert any(ln.startswith("FAIL") and "the installer set the window 19:00 to 1:00" in ln for ln in lines), lines
    assert any(ln.startswith("WARN") for ln in _lines({**OURS, **change}, strict=False))


def test_a_scheduled_install_the_installer_did_not_set_is_still_only_a_warning() -> None:
    facts = {k: v for k, v in OURS.items() if k != "update_window"}
    lines = _lines(facts)
    assert any(ln.startswith("WARN") and "Windows Update restarts at day 0 at 19:00" in ln for ln in lines), lines


def test_drivers_from_windows_update_fail() -> None:
    lines = _lines({**OURS, "wu_exclude_drivers": ""})
    assert any(ln.startswith("FAIL") and "may replace the NVIDIA driver" in ln for ln in lines), lines


@pytest.mark.parametrize("value", ["1", ""])
def test_a_sign_in_screen_that_offers_shutting_down_fails(value: str) -> None:
    lines = _lines({**OURS, "shutdown_at_sign_in": value})
    assert any(ln.startswith("FAIL") and "the sign-in screen offers shutting down" in ln for ln in lines), lines


def test_the_host_check_does_not_claim_to_have_read_the_shutdown_right() -> None:
    line = next(ln for ln in _lines(OURS) if "shutdown" in ln)
    assert "not read here" in line and "ShutdownWithoutLogon" in FACTS_PS1
    assert "secedit.exe" not in FACTS_PS1  # the facts script writes nothing, not even an export


def test_facts_of_an_earlier_release_are_judged_as_before() -> None:
    lines = _lines({"wu_au_options": "3"})
    assert lines == [
        "PASS  Windows Update restarts: installs and restarts are started by hospital IT in the window (RUNBOOK §24)"
    ]


def test_host_facts_prints_every_fact_the_new_rules_read_and_the_installer_writes_them() -> None:
    for key in ("update_window", "wu_set_active_hours", "wu_active_hours_start", "wu_active_hours_end",
                "wu_exclude_drivers", "shutdown_at_sign_in"):  # fmt: skip
        assert f'Fact "{key}"' in FACTS_PS1, key
    # the same registry values on both sides
    for value in ("SetActiveHours", "ActiveHoursStart", "ActiveHoursEnd", "ExcludeWUDriversInQualityUpdate",
                  "ShutdownWithoutLogon"):  # fmt: skip
        assert value in PS1 and value in FACTS_PS1, value
    assert 'Set-TbMachineSetting "update_window"' in PS1 and '"HKLM:\\SOFTWARE\\TrialBox" "update_window"' in FACTS_PS1
    assert "SeShutdownPrivilege" in PS1 and '$script:TbAdminsSid = "S-1-5-32-544"' in PS1


def test_the_installer_only_adds_policy_values_and_never_switches_updates_off() -> None:
    assert '@("\\AU", "NoAutoUpdate", 0)' in PS1  # updates stay on: the window is when, not whether
    assert not re.search(r'"NoAutoUpdate", 1|DisableWindowsUpdateAccess|wuauserv', PS1)
