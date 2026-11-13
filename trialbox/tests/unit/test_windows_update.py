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
         driver: str | None = "581.15", record: dict[str, Any] | None = None, site: dict[str, Any] | None = None,
         told: str | None = None, more: dict[str, dict[str, Any]] | None = None) -> DoctorInputs:  # fmt: skip
    proc, deploy = tmp / "proc", tmp / "deploy"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(kernel + "\n")
    for folder, doc in (("measured", record), ("site", site)):
        (deploy / folder).mkdir(parents=True)
        if doc is not None:
            (deploy / folder / "serving_config.rtxpro6000.json").write_text(json.dumps(doc))
    for rel, doc in (more or {}).items():
        (deploy / rel).write_text(json.dumps(doc))
    if told is not None:
        (deploy / "site/box").mkdir(parents=True)
        (deploy / "site/box/windows-update-window").write_text(told + "\n")
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


def test_a_night_outside_the_window_is_never_passed_while_its_length_is_unmeasured(tmp_path: Path) -> None:
    c = check_update_window(_inp(tmp_path, told="19+6"))
    assert (
        c.status == "WARN"
    )  # half the question is answered: the night starts outside; whether it ends before is not known
    assert (
        "from 19:00 to 01:00" in c.detail
        and "the night starts at 02:00, 17 h 00 min before the window opens" in c.detail
    )
    assert "not recorded on the box" in c.detail and "has not said" not in c.detail


@pytest.mark.parametrize(
    ("night", "status"), [("19:00", "FAIL"), ("00:59", "FAIL"), ("23:30", "FAIL"), ("01:00", "WARN"), ("18:59", "WARN")]
)
def test_a_night_that_starts_inside_the_window_fails(tmp_path: Path, night: str, status: str) -> None:
    c = check_update_window(_inp(tmp_path, night=night, told="19+6"))
    assert c.status == status, c.detail
    if status == "FAIL":
        assert f"the night starts at {night}, inside it" in c.detail and "-UpdateWindowStart" in c.detail
    if night == "18:59":
        assert "0 h 01 min before the window opens" in c.detail


def test_the_window_the_windows_installer_recorded_is_the_one_judged(tmp_path: Path) -> None:
    # the owner moved the window with -UpdateWindowStart 0: deploy/.env still says nothing, the box's record does
    c = check_update_window(_inp(tmp_path, told="0+6"))
    assert (
        c.status == "FAIL" and "from 00:00 to 06:00" in c.detail and "the night starts at 02:00, inside it" in c.detail
    )
    # and it wins over deploy/.env
    env = {"TB_WIN_UPDATE_WINDOW_START": "19", "TB_WIN_UPDATE_WINDOW_HOURS": "6"}
    assert check_update_window(_inp(tmp_path / "b", env=env, told="0+6")).status == "FAIL"


def test_without_the_installers_record_the_declared_window_is_judged_and_said_to_be_unconfirmed(tmp_path: Path) -> None:
    c = check_update_window(_inp(tmp_path))
    assert (
        c.status == "WARN"
        and "from 19:00 to 01:00 (the declared window: the Windows installer has not said" in c.detail
    )
    env = {"TB_WIN_UPDATE_WINDOW_START": "12", "TB_WIN_UPDATE_WINDOW_HOURS": "8"}
    c = check_update_window(_inp(tmp_path / "b", env=env, night="13:00"))
    assert c.status == "FAIL" and "from 12:00 to 20:00" in c.detail


def test_a_policy_the_sites_it_holds_is_said_and_not_judged(tmp_path: Path) -> None:
    c = check_update_window(_inp(tmp_path, told="kept"))
    assert (
        c.status == "WARN" and "the site's IT holds the Windows Update policy" in c.detail and "19:00" not in c.detail
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [("TB_WIN_UPDATE_WINDOW_START", "24"), ("TB_WIN_UPDATE_WINDOW_HOURS", "5"), ("TB_WIN_UPDATE_WINDOW_START", "7pm"),
     ("TB_WIN_UPDATE_WINDOW_START", "\u00b2")],
)  # fmt: skip
def test_a_window_windows_cannot_hold_is_never_a_pass(tmp_path: Path, key: str, value: str) -> None:
    c = check_update_window(_inp(tmp_path, env={key: value}))
    assert c.status == "FAIL" and key in c.detail


def test_a_recorded_window_that_is_not_one_falls_back_to_the_declared_and_says_so(tmp_path: Path) -> None:
    c = check_update_window(_inp(tmp_path, told="19 to 1"))
    assert c.status == "WARN" and "has not said which window" in c.detail


def test_a_malformed_night_is_named_as_malformed(tmp_path: Path) -> None:
    c = check_update_window(_inp(tmp_path, night="2:00", told="19+6"))
    assert c.status == "WARN" and "nightly_at '2:00' is not HH:MM" in c.detail


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


def test_the_boxs_profile_names_its_record_and_two_records_of_one_card_are_never_guessed_between(
    tmp_path: Path,
) -> None:
    two = {
        "site/serving_config.a-other.json": _record("570.00"),
        "site/serving_config.rtxpro6000.json": _record(wsl_kernel=WSL2),
    }
    c = check_wsl2_versions(_inp(tmp_path, more=two))
    assert c.status == "WARN" and "2 serving records name the card" in c.detail and "a-other" in c.detail
    c = check_wsl2_versions(_inp(tmp_path / "b", more=two, env={"TB_GPU_PROFILE": "rtxpro6000"}))
    assert c.status == "PASS" and "site/serving_config.rtxpro6000.json" in c.detail
    c = check_wsl2_versions(_inp(tmp_path / "c", more=two, env={"TB_GPU_PROFILE": "a-other"}))
    assert c.status == "FAIL" and "measured with 570.00" in c.detail


def test_a_records_driver_is_compared_without_its_white_space(tmp_path: Path) -> None:
    assert check_wsl2_versions(_inp(tmp_path, record=_record("581.15 ", wsl_kernel=WSL2))).status == "PASS"


def test_the_shipped_record_is_of_another_card_than_a_workstations_so_the_check_waits_for_a_site_record(
    tmp_path: Path,
) -> None:
    # stated in D-606: until a record is captured on the workstation itself, wsl2_versions compares with nothing
    shipped = json.loads((ROOT / "deploy/measured/serving_config.rtxpro6000.json").read_text(encoding="utf-8"))
    c = check_wsl2_versions(_inp(tmp_path, record=shipped))
    assert c.status == "WARN" and "no serving record for the card" in c.detail


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
    assert "installs at 19:00 and restarts by itself only from 19:00 to 1:00" in text
    assert "takes no drivers" in text and "the sign-in screen does not offer it" in text


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"wu_scheduled_install_time": "3"}, "install time '3' (want 19)"),
        ({"wu_set_active_hours": ""}, "active hours set '' (want 1)"),
        ({"wu_active_hours_start": "8"}, "active hours from '8' (want 1)"),
        ({"wu_active_hours_end": "17"}, "active hours to '17' (want 19)"),
        ({"wu_au_options": "2"}, "AUOptions '2' (want 4)"),
        ({"wu_no_auto_update": "1"}, "automatic updates are switched off"),
        # values that, by Microsoft's documentation, take restarts out of the active hours' hands
        ({"wu_no_auto_reboot_logged_on": "1"}, "NoAutoRebootWithLoggedOnUsers is set"),
        ({"wu_always_reboot_at_scheduled": "1"}, "AlwaysAutoRebootAtScheduledTime is set"),
        ({"wu_compliance_deadline": "1"}, "a compliance deadline is set"),
        ({"wu_deadline_quality": "7"}, "a deadline for quality updates is set"),
        ({"wu_deadline_feature": "7"}, "a deadline for feature updates is set"),
        ({"wu_mdm_allow_auto_update": "5"}, "an MDM update policy is set"),
        (
            {"update_window": "19+3", "wu_active_hours_start": "22"},
            "a window of 3 h from 19:00 is not one Windows can hold",
        ),
    ],
)
def test_a_window_windows_does_not_hold_fails_on_a_production_box(change: dict[str, str], says: str) -> None:
    lines = _lines({**OURS, **change})
    hit = [ln for ln in lines if "the installer set the window" in ln]
    assert len(hit) == 1 and hit[0].startswith("FAIL") and says in hit[0], lines
    assert not any("Windows Update restarts" in ln and ln.startswith("PASS") for ln in lines)
    assert any(ln.startswith("WARN") and says in ln for ln in _lines({**OURS, **change}, strict=False))


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
                "wu_exclude_drivers", "shutdown_at_sign_in", "wu_no_auto_reboot_logged_on",
                "wu_always_reboot_at_scheduled", "wu_compliance_deadline", "wu_deadline_quality", "wu_deadline_feature"):  # fmt: skip
        assert f'Fact "{key}"' in FACTS_PS1, key
    # the same registry values on both sides
    for value in ("SetActiveHours", "ActiveHoursStart", "ActiveHoursEnd", "ExcludeWUDriversInQualityUpdate",
                  "ShutdownWithoutLogon"):  # fmt: skip
        assert value in PS1 and value in FACTS_PS1, value
    assert 'Set-TbMachineSetting "update_window"' in PS1 and '"HKLM:\\SOFTWARE\\TrialBox" "update_window"' in FACTS_PS1
    assert "SeShutdownPrivilege" in PS1 and '$script:TbAdminsSid = "S-1-5-32-544"' in PS1


def test_the_installer_and_the_host_check_name_the_same_values_that_defeat_the_window() -> None:
    for value in ("NoAutoRebootWithLoggedOnUsers", "AlwaysAutoRebootAtScheduledTime", "SetComplianceDeadline",
                  "ConfigureDeadlineForQualityUpdates", "ConfigureDeadlineForFeatureUpdates"):  # fmt: skip
        assert value in PS1 and value in FACTS_PS1, value
    assert "PolicyManager\\current\\device\\Update" in PS1 and "PolicyManager\\current\\device\\Update" in FACTS_PS1


def test_the_box_is_told_the_window_or_that_it_was_kept(tmp_path: Path) -> None:
    import os
    import subprocess

    root = tmp_path / "opt"
    env = {**os.environ, "TB_WSL_ROOT": str(root), "TB_WSL_NO_ROOT": "1"}
    script = str(ROOT / "deploy/windows/wsl-setup.sh")
    for value in ("19+6", "kept", "0+23"):
        r = subprocess.run(
            ["bash", script, "update-window", value], env=env, capture_output=True, text=True, check=False
        )
        assert r.returncode == 0, r.stderr
        assert (root / "deploy/site/box/windows-update-window").read_text() == value + "\n"
    for bad in ("", "19", "19+6; rm -rf /", "../x", "kept\n19+6"):
        r = subprocess.run(["bash", script, "update-window", bad], env=env, capture_output=True, text=True, check=False)
        assert r.returncode == 1 and "want <start hour>+<hours> or kept" in r.stderr, bad
    assert (root / "deploy/site/box/windows-update-window").read_text() == "0+23\n"
    assert 'Invoke-TbSetup "update-window"' in PS1


def test_the_installer_only_adds_policy_values_and_never_switches_updates_off() -> None:
    assert '@("\\AU", "NoAutoUpdate", 0)' in PS1  # updates stay on: the window is when, not whether
    assert not re.search(r'"NoAutoUpdate", 1|DisableWindowsUpdateAccess|wuauserv', PS1)
