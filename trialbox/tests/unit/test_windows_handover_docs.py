"""NEW-WIN-9 (D-611): the Windows hand-over documents say what the installer and the checks really have.

The owner's pages exist in en, ja and zh-TW with the same parts; the checklist names only options, checks and
files that exist. Whether the words match what a Windows PC does is the rehearsal's question, not a test's."""

from __future__ import annotations

import re
from pathlib import Path

from tb_common.wording import check

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/handover"
PS1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")
CHECKLIST = (DOCS / "WINDOWS-INSTALL-CHECKLIST.md").read_text(encoding="utf-8")
LANGS = ("en", "ja", "zh-TW")


def _shape(text: str) -> tuple[list[int], int, int, int]:
    lines = text.splitlines()
    return (
        [ln.count("#") for ln in lines if ln.startswith("#")],
        sum(ln.startswith("- ") for ln in lines),
        sum(bool(re.match(r"[1-9]\. ", ln)) for ln in lines),
        sum(ln.startswith("| ") for ln in lines),
    )


def test_the_owners_pages_have_the_same_parts_in_three_languages_and_no_verdict_words() -> None:
    shapes = {}
    for lang in LANGS:
        text = (DOCS / f"windows-owner.{lang}.md").read_text(encoding="utf-8")
        assert check(text) == [], lang
        shapes[lang] = _shape(text)
        # what the owner must find whatever the language: the file to start, the log to send, the address to try
        for must in ("Install-TrialBox.cmd", r"C:\ProgramData\TrialBox\box-install\box-install.log", "https://localhost/",
                     "BitLocker", "19:00", "01:00", "TrialBox is ready", "Docker Desktop", "D-611"):  # fmt: skip
            assert must in text, (lang, must)
    assert shapes["en"] == shapes["ja"] == shapes["zh-TW"] == ([1, 2, 2, 2], 5, 6, 8)


def test_the_owners_page_names_the_installers_default_update_window() -> None:
    start = re.search(r"\[int\]\$UpdateWindowStart = (\d+)", PS1)
    hours = re.search(r"\[int\]\$UpdateWindowHours = (\d+)", PS1)
    assert start and hours
    end = (int(start.group(1)) + int(hours.group(1))) % 24
    for lang in LANGS:
        text = (DOCS / f"windows-owner.{lang}.md").read_text(encoding="utf-8")
        assert f"{int(start.group(1)):02d}:00" in text and f"{end:02d}:00" in text, lang


def test_the_checklist_names_only_options_the_installer_has() -> None:
    options = set(re.findall(r"(?<![A-Za-z0-9])(-[A-Z][a-z][A-Za-z]+)\b", CHECKLIST))  # -DataDrive, not OFFLINE-MEDIA
    assert {"-DataDrive", "-DesktopSharePercent", "-BitLockerUnlock", "-UpdateWindowStart", "-UpdateWindowHours",
            "-BackupDrive"} <= options  # fmt: skip
    for option in options:
        assert re.search(rf"\${option[1:]}\b", PS1), option
    # the figures it shows beside them are the installer's own defaults
    for name, shown in re.findall(r"`(-[A-Z][A-Za-z]+) (\d+)", CHECKLIST):
        default = re.search(rf"\[int\]\${name[1:]} = (\d+)", PS1)
        assert default and default.group(1) == shown, name
    assert "build 19045" in CHECKLIST and "$MinWindowsBuild = 19045" in PS1


def test_the_checklist_names_only_checks_and_files_that_exist() -> None:
    from tools.trialbox import doctor

    names = {c.__name__.removeprefix("check_") for c in doctor.CHECKS}
    line = re.search(r"The lines of this form: ([^.]+)\.", CHECKLIST.replace("\n", " "))
    assert line
    listed = re.findall(r"`([a-z0-9_]+)`", line.group(1))
    assert listed and set(listed) <= names, set(listed) - names
    for doc in re.findall(r"`([A-Za-z0-9-]+\.md)`", CHECKLIST):
        assert (DOCS / doc).is_file(), doc
    for lang in LANGS:
        for stem in ("windows-owner", "desktop-use"):
            assert (DOCS / f"{stem}.{lang}.md").is_file(), (stem, lang)
    for path in ("deploy/check_host.sh", "deploy/windows/Install-TrialBox.cmd", "tools/windows_media.py"):
        assert (ROOT / path).is_file(), path
    # the policy checker points here for the monthly compaction: the sentence must stay
    assert (
        "compact it\n  monthly" in CHECKLIST
        and "WINDOWS-INSTALL-CHECKLIST.md" in (ROOT / "deploy/windows/wsl2_policy.py").read_text()
    )


def test_nothing_in_the_hand_over_pages_tells_anyone_to_remove_the_box() -> None:
    for lang in LANGS:
        text = (DOCS / f"windows-owner.{lang}.md").read_text(encoding="utf-8")
        assert "--unregister" not in text and "wsl --export" not in text, lang
    # the checklist names the command once, under "Never"
    assert CHECKLIST.count("wsl --unregister") == 1 and CHECKLIST.index("Never:") < CHECKLIST.index("wsl --unregister")


def test_the_p0_pages_commands_are_ones_the_media_tools_take() -> None:
    """The owner copies these lines: every option they give must be one the tool accepts (D-611)."""
    import subprocess
    import sys

    page = (DOCS / "P-0-BUILD-THE-MEDIA.md").read_text(encoding="utf-8").replace("\\\n", " ")
    env = {"PYTHONPATH": f"{ROOT / 'libs'}:{ROOT}", "PATH": "/usr/bin:/bin"}
    seen = set()
    for tool, sub in (("windows_media", "build"), ("windows_media", "check"), ("windows_media_debs", "")):
        lines = [ln for ln in page.splitlines() if f"-m tools.{tool} {sub}".rstrip() in ln and "python3" in ln]
        assert lines, (tool, sub)
        args = [tool] + ([sub] if sub else []) + ["--help"]
        helptext = subprocess.run([sys.executable, "-m", f"tools.{args[0]}", *args[1:]], capture_output=True, text=True,
                                  cwd=ROOT, env=env, check=True, timeout=60).stdout  # fmt: skip
        for ln in lines:
            for flag in re.findall(r"(--[a-z][a-z-]+)", ln):
                assert flag in helptext, (tool, sub, flag)
                seen.add(flag)
    assert {"--rootfs", "--out", "--version", "--bundle", "--wsl-msi", "--debs", "--vendor-pub"} <= seen


def test_the_p0_sheet_does_not_wait_for_a_finished_install_where_stage_a_is_enough() -> None:
    sheet = (DOCS / "P-0-windows-rehearsal.md").read_text(encoding="utf-8")
    line_36a = next(ln for ln in sheet.splitlines() if ln.startswith("| 36a |"))
    assert "After the install is finished" not in line_36a and "Stage A" in line_36a
    assert "After step 12 `boot-task` has run" in sheet
    # the key probe needs only the folder the installer makes at its start, not a finished install
    probe = (ROOT / "deploy/windows/key-probe.ps1").read_text(encoding="utf-8")
    assert "run the installer first (it makes that folder" in probe and "windows-install-done" not in probe


def test_the_p0_pages_and_the_checklist_take_windows_10_22h2_at_the_installers_own_build() -> None:
    """Owner ruling D-503 (NEW-WIN-10, D-613): the sites' workstations run Windows 10 Pro 22H2."""
    page = (DOCS / "P-0-BUILD-THE-MEDIA.md").read_text(encoding="utf-8")
    sheet = (DOCS / "P-0-windows-rehearsal.md").read_text(encoding="utf-8")
    build = re.search(r"\[int\]\$MinWindowsBuild = (\d+)", PS1)
    assert build and build.group(1) == "19045"
    for text in (page, sheet, CHECKLIST):
        assert "Windows 10 22H2" in text and "19045" in text
    assert "cannot take P-0" not in page
    assert "## Part 9: NEW-WIN-10" in sheet and "TrialBox-Console-Proxy" in sheet
    # the undo the page gives names the rule, the task and the firewall rule the installer makes
    assert (
        "Unregister-ScheduledTask TrialBox-Console-Proxy" in page
        and "Remove-NetFirewallRule -Name TrialBox-Console" in page
    )
    assert (
        '$script:TbProxyTask = "TrialBox-Console-Proxy"' in PS1 and '$script:TbFirewallRule = "TrialBox-Console"' in PS1
    )


# NEW-WIN-14 (D-617): the page for the BitLocker recovery screen (plan section 2.3, replacing T-730's locked-box page)
def test_the_recovery_screen_page_has_the_same_parts_in_three_languages_and_tells_how_to_find_the_key() -> None:
    shapes = {}
    for lang in LANGS:
        text = (DOCS / f"windows-bitlocker-recovery.{lang}.md").read_text(encoding="utf-8")
        assert check(text) == [], lang
        assert re.search(r"(?m)^\*\*Reader:\*\* the box owner", text), lang
        shapes[lang] = _shape(text)
        for must in (
            "BitLocker",
            "key ID",
            "F1",
            "F10",
            "WINDOWS-BACKUP-RESTORE.md",
            f"windows-owner.{lang}.md",
            "D-617",
        ):
            assert must in text, (lang, must)
        # never told to turn the protection off to get past the screen, nor to send the key anywhere
        for never in ("manage-bde -off", "Disable-BitLocker", "Suspend-BitLocker"):
            assert never not in text, (lang, never)
    assert shapes["en"] == shapes["ja"] == shapes["zh-TW"]


def test_the_owners_pages_send_the_reader_to_the_recovery_screen_page_and_the_media_carries_it() -> None:
    from tools import windows_media

    for lang in LANGS:
        owner = (DOCS / f"windows-owner.{lang}.md").read_text(encoding="utf-8")
        assert f"windows-bitlocker-recovery.{lang}.md" in owner, lang
        assert f"windows-bitlocker-recovery.{lang}.md" in windows_media.HANDOVER_DOCS
