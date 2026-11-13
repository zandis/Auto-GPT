"""Is this Windows workstation fit to hold TrialBox in WSL2? (T-210a, D-421; CR-041, OPS-061). Standard library only.

    python3 deploy/windows/wsl2_policy.py --facts FILE [--strict]   # FILE: host_facts.ps1 output, "-" for stdin

``deploy/windows/host_facts.ps1`` reads the Windows side and prints ``key=value`` lines in a language-neutral form
(enum names and numbers, never localised text). This file judges them, for both ``preflight.ps1`` (before the install)
and ``check_host.sh --wsl2`` (after it), so the two never disagree. The checks:

* **BitLocker** on the system drive and on the drive that holds the distribution's ``ext4.vhdx``: fully encrypted and
  protection on. On the system drive a plain ``Tpm`` protector FAILs (the TPM alone opens the disk, so a stolen
  workstation boots to a running stack anywhere); a TPM with a PIN or startup key, or Network Unlock, PASSes.
  A recovery password must exist and the operator must say where it is kept (``-RecoveryKeyEscrow``);
* the **page file** only on encrypted drives; **hibernation** and Fast Startup off (``hiberfil.sys`` holds memory,
  WSL2's memory with it); WSL **swap** off in ``.wslconfig`` (``swap=0``); **Remote Desktop** off;
* **Windows Update restarts** under a policy (installs and restarts started by hospital IT, or at a set time), not
  the default that restarts outside active hours, which is the night when the nightly jobs run;
* a **start-at-boot task** that runs whether or not anyone is signed in and starts ``wsl.exe``: without it WSL2 and
  the stack stop when nobody is signed in and do not come back after a restart;
* the **clocks** of Windows and WSL2 agree (audit timestamps); the **disk file** ``ext4.vhdx`` only grows unless
  ``sparseVhd=true``, and its drive keeps room.

``--strict`` (VALIDATION and PRODUCTION) turns the policy WARNs into FAILs, as ``check_host.sh`` does; the data at rest
checks (BitLocker, page file, hibernation, swap) FAIL always. Output: one ``PASS``/``WARN``/``FAIL`` line per check
(the format of ``deploy/check_host.sh``); exit 1 on a FAIL, 2 when the facts cannot be read.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import configparser
import sys
from collections.abc import Callable
from pathlib import Path

FACTS_VERSION = "1"
# BitLocker key protectors (KeyProtectorType names) that need a person or the hospital network at boot
PRE_BOOT = frozenset({"TpmPin", "TpmPinStartupKey", "TpmStartupKey", "TpmNetworkKey", "Password", "ExternalKey"})
TPM_ALONE = "Tpm"
DRIFT_WARN_S = 5
DRIFT_FAIL_S = 60  # the skew beyond which T-211a refuses jobs
TASK_ACTION = "wsl.exe"
BOOT_TRIGGER = "MSFT_TaskBootTrigger"
# Windows Update: AUOptions 2 notify, 3 download and notify, 7 notify install and restart (Server); MDM
# AllowAutoUpdate 0 notify, 5 off. Scheduled installs (AUOptions 4, AllowAutoUpdate 3) are a WARN with their time.
WU_MANUAL_AU = frozenset({"2", "3", "7"})
WU_MANUAL_MDM = frozenset({"0", "5"})

Facts = dict[str, str]


class Verdicts:
    def __init__(self, strict: bool) -> None:
        self.strict = strict
        self.lines: list[str] = []

    def add(self, verdict: str, text: str) -> None:
        self.lines.append(f"{verdict}  {text}")

    def ok(self, text: str) -> None:
        self.add("PASS", text)

    def warn(self, text: str) -> None:
        self.add("WARN", text)

    def fail(self, text: str) -> None:
        self.add("FAIL", text)

    def policy(self, text: str) -> None:
        """A FAIL in VALIDATION and PRODUCTION, a WARN in DEV and TEST."""
        if self.strict:
            self.fail(text)
        else:
            self.warn(f"{text} (FAIL in VALIDATION and PRODUCTION)")

    @property
    def failed(self) -> int:
        return sum(1 for ln in self.lines if ln.startswith("FAIL "))


def parse_facts(text: str) -> Facts:
    """``key=value`` lines; the last value of a key wins (preflight.ps1 appends its own clock lines)."""
    facts: Facts = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        facts[key.strip()] = value.strip()
    return facts


def _int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _drive_tag(drive: str) -> str:
    return drive.strip().rstrip(":\\").upper()


def _protectors(facts: Facts, tag: str) -> list[str]:
    return [p.strip() for p in facts.get(f"bitlocker_{tag}_protectors", "").split(",") if p.strip()]


def _encrypted(facts: Facts, tag: str) -> bool:
    return (
        facts.get(f"bitlocker_{tag}_status") == "FullyEncrypted" and facts.get(f"bitlocker_{tag}_protection") == "On"
    ) or (facts.get(f"bitlocker_{tag}_status", "unknown") == "unknown" and facts.get(f"bitlocker_{tag}_shell") == "1")


# ------------------------------------------------------------------------------------------------ the checks
def check_bitlocker(facts: Facts, v: Verdicts) -> None:
    system = _drive_tag(facts.get("system_drive", "C:"))
    drives = [system]
    vhdx_drive = _drive_tag(facts.get("vhdx_drive", ""))
    if vhdx_drive and vhdx_drive not in drives:
        drives.append(vhdx_drive)
    for tag in drives:
        role = "system drive" if tag == system else "drive of the WSL2 disk"
        status = facts.get(f"bitlocker_{tag}_status", "unknown")
        protection = facts.get(f"bitlocker_{tag}_protection", "")
        method = facts.get(f"bitlocker_{tag}_method", "")
        if status == "unknown":
            shell = facts.get(f"bitlocker_{tag}_shell", "")
            if shell == "1":
                v.policy(f"BitLocker on {tag}: ({role}) on, but its key protectors were not read: run elevated")
            else:
                v.fail(f"BitLocker on {tag}: ({role}) not readable (state '{shell or '?'}'): run as administrator")
            continue
        if status == "EncryptionInProgress" and protection == "On":
            v.policy(f"BitLocker on {tag}: ({role}) still encrypting: run the check again when it is FullyEncrypted")
            continue
        if status != "FullyEncrypted" or protection != "On":
            v.fail(f"BitLocker on {tag}: ({role}) {status}, protection {protection or '?'} (manage-bde -on {tag}:; "
                   "a suspended BitLocker leaves the key on the disk)")  # fmt: skip
            continue
        if tag != system:
            v.ok(f"BitLocker on {tag}: ({role}) FullyEncrypted, {method or 'method ?'}")
            continue
        prot = _protectors(facts, tag)
        if TPM_ALONE in prot:
            v.fail(f"BitLocker on {tag}: the TPM alone opens it, so a stolen workstation boots to a running stack "
                   f"(protectors {','.join(prot)}; add a PIN: manage-bde -protectors -add {tag}: -TPMAndPIN, then "
                   "delete the Tpm protector)")  # fmt: skip
        elif not PRE_BOOT.intersection(prot):
            v.fail(f"BitLocker on {tag}: no pre-boot protector (protectors {','.join(prot) or 'none'}; want TPM+PIN)")
        else:
            v.ok(f"BitLocker on {tag}: ({role}) FullyEncrypted, {method or 'method ?'}, unlock {','.join(prot)}")


def check_recovery(facts: Facts, v: Verdicts) -> None:
    tag = _drive_tag(facts.get("system_drive", "C:"))
    if facts.get(f"bitlocker_{tag}_status", "unknown") == "unknown":
        return  # said by the BitLocker line
    if "RecoveryPassword" not in _protectors(facts, tag):
        v.policy(f"BitLocker recovery: no recovery password on {tag}: (a broken TPM or a forgotten PIN loses the data)")
        return
    where = facts.get("recovery_escrow", "")
    if where:
        v.ok(f"BitLocker recovery: password kept by {where} (as stated at the check)")
    else:
        v.policy("BitLocker recovery: say where the recovery password is kept (-RecoveryKeyEscrow / --escrow; "
                 "hospital IT's sealed envelope or their directory, never on the workstation)")  # fmt: skip


def check_pagefile(facts: Facts, v: Verdicts) -> None:
    if facts.get("pagefile_known") != "1":
        v.warn("page file: not read")
        return
    drives = [_drive_tag(d) for d in facts.get("pagefile_drives", "").split(",") if d.strip()]
    plain = [d for d in drives if not _encrypted(facts, d)]
    if plain:
        v.fail(f"page file on {','.join(plain)}: which BitLocker does not protect (WSL2's memory pages there)")
    else:
        v.ok(f"page file on {','.join(drives) or 'no drive'}: encrypted")


def check_hibernation(facts: Facts, v: Verdicts) -> None:
    hib, fast = facts.get("hibernate_enabled", ""), facts.get("fast_startup", "")
    fil = facts.get("hiberfil_present", "")
    on = [name for name, val in (("hibernation", hib), ("Fast Startup", fast), ("hiberfil.sys", fil)) if val == "1"]
    if on:
        v.fail(f"hibernation: {', '.join(on)} on (memory, WSL2's with it, is written to disk; powercfg /hibernate off)")
    elif hib == "" and fil == "":
        v.warn("hibernation: state not read")
    else:
        v.ok("hibernation and Fast Startup off")


def _wslconfig(facts: Facts) -> configparser.ConfigParser | None:
    if facts.get("wslconfig_found") != "1":
        return None
    try:
        raw = base64.b64decode(facts.get("wslconfig_b64", ""), validate=True)
    except (binascii.Error, ValueError):
        raw = b""
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", "replace")
    cfg = configparser.ConfigParser(strict=False, interpolation=None, inline_comment_prefixes=("#", ";"))
    try:
        cfg.read_string(text)
    except configparser.Error:
        return configparser.ConfigParser()
    return cfg


def _setting(cfg: configparser.ConfigParser, key: str) -> str | None:
    for section in ("wsl2", "experimental"):
        if cfg.has_option(section, key):
            return cfg.get(section, key).strip().strip('"').lower()
    return None


def _size_is_zero(value: str) -> bool:
    num = value.lower().removesuffix("b").rstrip("kmgt")
    try:
        return float(num) == 0
    except ValueError:
        return False


def check_wsl_swap(facts: Facts, v: Verdicts) -> None:
    where = facts.get("wslconfig_path", ".wslconfig")
    cfg = _wslconfig(facts)
    if cfg is None:
        v.fail(f"WSL2 swap: no {where} (WSL2 swaps by default; copy deploy/windows/wslconfig.example)")
        return
    swap = _setting(cfg, "swap")
    if swap is not None and _size_is_zero(swap):
        v.ok(f"WSL2 swap off ({where}: swap={swap})")
    else:
        v.fail(f"WSL2 swap: {where} has swap={swap if swap is not None else '(unset: the default swaps)'}; want swap=0")


def check_rdp(facts: Facts, v: Verdicts) -> None:
    deny = facts.get("rdp_deny_connections", "")
    if deny == "0":
        v.policy("Remote Desktop is on (turn it off; support is the supervised session of RUNBOOK §21)")
    elif deny == "":
        v.warn("Remote Desktop: state not read")
    else:
        v.ok("Remote Desktop off")


def check_windows_update(facts: Facts, v: Verdicts) -> None:
    pending = facts.get("wu_reboot_pending") == "1"
    au, mdm = facts.get("wu_au_options", ""), facts.get("wu_mdm_allow_auto_update", "")
    day, hour = facts.get("wu_scheduled_install_day", ""), facts.get("wu_scheduled_install_time", "")
    if facts.get("wu_no_auto_update") == "1" or au in WU_MANUAL_AU or mdm in WU_MANUAL_MDM:
        v.ok("Windows Update restarts: installs and restarts are started by hospital IT in the window (RUNBOOK §24)")
    elif au == "4" or mdm == "3":
        when = f"day {day or '0'} at {hour}:00" if hour else "the scheduled time"
        v.warn(f"Windows Update restarts at {when}: keep it out of the nightly jobs and agree it with hospital IT")
    elif au or mdm:
        v.policy(f"Windows Update restarts by itself (AUOptions {au or '-'}, AllowAutoUpdate {mdm or '-'}): set a "
                 "policy that only notifies (Configure Automatic Updates = 3)")  # fmt: skip
    else:
        v.policy("Windows Update has no policy: the default installs and restarts outside active hours, which is the "
                 "night of the nightly jobs (Configure Automatic Updates = 3, or a set install time)")  # fmt: skip
    if pending:
        v.warn("Windows Update: a restart is pending (restart in the agreed window; the start-at-boot task brings "
               "WSL2 and the stack back)")  # fmt: skip


def check_keepalive(facts: Facts, v: Verdicts) -> None:
    name = facts.get("keepalive_task_name", "TrialBox-WSL2")
    if facts.get("keepalive_task_found") != "1":
        v.policy(f"start-at-boot task '{name}' missing: WSL2 and the stack stop when nobody is signed in and do not "
                 "come back after a restart (deploy/windows/register_keepalive.ps1)")  # fmt: skip
        return
    problems = []
    if BOOT_TRIGGER not in facts.get("keepalive_task_triggers", "").split(","):
        problems.append("no at-startup trigger")
    if facts.get("keepalive_task_logon_type", "") in ("Interactive", "InteractiveOrPassword", "Group", ""):
        problems.append(f"runs only for a signed-in user (logon {facts.get('keepalive_task_logon_type') or '?'})")
    if facts.get("keepalive_task_state", "") == "Disabled":
        problems.append("disabled")
    action = facts.get("keepalive_task_action", "")
    if TASK_ACTION not in action.lower():
        problems.append("does not start wsl.exe")
    elif facts.get("distro") and f"-d {facts['distro']} " not in action + " ":
        # NEW-WIN-2 (D-602): a task for another distribution keeps the wrong system alive, or none
        problems.append(f"starts another distribution than '{facts['distro']}'")
    if problems:
        v.policy(f"start-at-boot task '{name}': {'; '.join(problems)}")
    else:
        v.ok(f"start-at-boot task '{name}': at startup, signed in or not ({facts.get('keepalive_task_state')})")


def check_clock(facts: Facts, v: Verdicts) -> None:
    w_lo, w_hi = _int(facts.get("clock_windows_lo")), _int(facts.get("clock_windows_hi"))
    l_lo, l_hi = _int(facts.get("clock_linux_lo")), _int(facts.get("clock_linux_hi"))
    if w_lo is None or w_hi is None or l_lo is None or l_hi is None:
        v.warn("clocks: Windows and WSL2 times not both read")
        return
    drift = max(0, l_lo - w_hi, w_lo - l_hi)  # the gap between the two read windows; 0 when they overlap
    service = facts.get("w32time_status", "")
    if drift > DRIFT_FAIL_S:
        v.fail(f"clocks: WSL2 and Windows differ by {drift} s (over {DRIFT_FAIL_S} s; wsl --shutdown resyncs WSL2)")
    elif drift > DRIFT_WARN_S:
        v.warn(f"clocks: WSL2 and Windows differ by {drift} s")
    elif service and service != "Running":
        v.warn(f"clocks: agree, but the Windows Time service is {service} (the hospital's time server keeps both)")
    else:
        v.ok(f"clocks: WSL2 and Windows agree within {max(drift, 1)} s")


def check_vhdx(facts: Facts, v: Verdicts) -> None:
    path = facts.get("vhdx_path", "")
    if not path:
        v.warn("WSL2 disk file: not found (name the distribution: -Distro / --wsl2-distro)")
        return
    cfg = _wslconfig(facts)
    sparse = _setting(cfg, "sparsevhd") if cfg is not None else None
    size = facts.get("vhdx_gb", "?")
    if sparse == "true":
        v.ok(f"WSL2 disk file {path} ({size} GB): sparse, gives back freed space")
    else:
        v.warn(f"WSL2 disk file {path} ({size} GB) only grows: set sparseVhd=true in .wslconfig or compact it "
               "monthly (WINDOWS-INSTALL-CHECKLIST.md)")  # fmt: skip
    total, free = _int(facts.get("vhdx_drive_size_gb")), _int(facts.get("vhdx_drive_free_gb"))
    drive = _drive_tag(facts.get("vhdx_drive", "")) or "?"
    if not total or free is None:
        v.warn(f"free space on {drive}: not read")
        return
    pct = 100 * free // total
    if pct < 10:
        v.fail(f"free space on {drive}: {pct}% ({free} GB; the WSL2 disk cannot grow, below 10%)")
    elif pct < 20:
        v.warn(f"free space on {drive}: {pct}% ({free} GB; below 20%)")
    else:
        v.ok(f"free space on {drive}: {pct}% ({free} GB)")


CHECKS: tuple[Callable[[Facts, Verdicts], None], ...] = (
    check_bitlocker,
    check_recovery,
    check_pagefile,
    check_hibernation,
    check_wsl_swap,
    check_rdp,
    check_windows_update,
    check_keepalive,
    check_clock,
    check_vhdx,
)


def judge(facts: Facts, *, strict: bool) -> list[str]:
    v = Verdicts(strict)
    if facts.get("facts_version") != FACTS_VERSION:
        v.fail(f"Windows facts: version '{facts.get('facts_version', '')}' (want {FACTS_VERSION}): host_facts.ps1 "
               "and wsl2_policy.py are from different releases, or powershell.exe did not run")  # fmt: skip
        return v.lines
    if facts.get("is_admin") != "1":
        v.warn("Windows facts read without administrator rights: BitLocker protectors cannot be read")
    for check in CHECKS:
        check(facts, v)
    return v.lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--facts", required=True, help='host_facts.ps1 output; "-" for stdin')
    ap.add_argument("--strict", action="store_true", help="VALIDATION and PRODUCTION: policy WARNs become FAILs")
    args = ap.parse_args(argv)
    try:
        if args.facts == "-":
            text = sys.stdin.read()
        else:
            raw = Path(args.facts).read_bytes()
            text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"FAIL  Windows facts not read: {exc}")
        return 2
    lines = judge(parse_facts(text), strict=args.strict)
    print("\n".join(lines))
    return 1 if any(ln.startswith("FAIL ") for ln in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
