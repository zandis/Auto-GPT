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
    assert "build\n      22621" in CHECKLIST and "$MinWindowsBuild = 22621" in PS1


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
