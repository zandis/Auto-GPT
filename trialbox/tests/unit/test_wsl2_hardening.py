"""T-210a (D-421; CR-041 first third, OPS-061): the Windows/WSL2 hardening checks, run without Windows.

No Windows machine runs these tests. ``host_facts.ps1`` output is stood in by fixtures (the ``key=value`` lines it
prints, written by hand from the cmdlets' documented enum names); ``powershell.exe``, ``wslpath`` and the rest are
stub commands on PATH. ``wsl2_policy.py`` is the one judge for ``preflight.ps1`` and ``check_host.sh --wsl2``, so
it is tested directly; the PowerShell files are read as text. The run on a real workstation remains (PR body).

Acceptance (TB-ASSESS-01 T-210, part a): the preflight FAILs without BitLocker (TPM+PIN, recovery key escrowed),
with WSL swap, hibernation or RDP on; ``.wslconfig`` swap=0; a Windows task keeps the distro alive;
``check_host --wsl2``. OPS-061 adds Windows Update restarts, WSL2 stopping when nobody is signed in, clock drift and
the disk file that only grows."""

from __future__ import annotations

import base64
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIN = ROOT / "deploy" / "windows"
PYBIN = Path(sys.executable).parent


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("wsl2_policy", WIN / "wsl2_policy.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


policy = _load()
WSLCONFIG = base64.b64encode((WIN / "wslconfig.example").read_bytes()).decode()
NOW = 1_794_000_000

# A hardened workstation, as host_facts.ps1 prints it (synthetic: no real machine, path or person).
HARDENED = f"""facts_version=1
is_admin=1
system_drive=C:
distro=Ubuntu-24.04
vhdx_path=D:\\WSL\\Ubuntu-24.04\\ext4.vhdx
vhdx_drive=D:
vhdx_gb=212
vhdx_drive_size_gb=1863
vhdx_drive_free_gb=1400
pagefile_known=1
pagefile_drives=C
bitlocker_C_shell=1
bitlocker_C_status=FullyEncrypted
bitlocker_C_protection=On
bitlocker_C_method=XtsAes256
bitlocker_C_protectors=TpmPin,RecoveryPassword
bitlocker_D_shell=1
bitlocker_D_status=FullyEncrypted
bitlocker_D_protection=On
bitlocker_D_method=XtsAes256
bitlocker_D_protectors=ExternalKey,RecoveryPassword
recovery_escrow=hospital IT sealed envelope
hibernate_enabled=0
fast_startup=0
hiberfil_present=0
wslconfig_path=C:\\Users\\tbadmin\\.wslconfig
wslconfig_found=1
wslconfig_b64={WSLCONFIG}
rdp_deny_connections=1
wu_no_auto_update=
wu_au_options=3
wu_scheduled_install_day=
wu_scheduled_install_time=
wu_mdm_allow_auto_update=
wu_reboot_pending=0
keepalive_task_name=TrialBox-WSL2
keepalive_task_found=1
keepalive_task_state=Running
keepalive_task_logon_type=S4U
keepalive_task_triggers=MSFT_TaskBootTrigger
keepalive_task_action=wsl.exe -d Ubuntu-24.04 --exec /bin/sh -c 'exec sleep infinity'
w32time_status=Running
clock_windows_lo={NOW}
clock_windows_hi={NOW}
clock_linux_lo={NOW}
clock_linux_hi={NOW + 1}
"""

# A new Windows 11 Pro laptop as it comes: device encryption with the TPM alone, hibernation and Fast Startup on,
# no .wslconfig, no update policy, no task, Remote Desktop on, a page file on the plain second drive.
FACTORY = f"""facts_version=1
is_admin=1
system_drive=C:
vhdx_path=C:\\Users\\clinic\\AppData\\Local\\Packages\\CanonicalGroupLimited.Ubuntu\\LocalState\\ext4.vhdx
vhdx_drive=C:
vhdx_gb=180
vhdx_drive_size_gb=953
vhdx_drive_free_gb=60
pagefile_known=1
pagefile_drives=C,E
bitlocker_C_shell=1
bitlocker_C_status=FullyEncrypted
bitlocker_C_protection=On
bitlocker_C_method=XtsAes128
bitlocker_C_protectors=Tpm,RecoveryPassword
bitlocker_E_shell=2
bitlocker_E_status=FullyDecrypted
bitlocker_E_protection=Off
bitlocker_E_protectors=
recovery_escrow=
hibernate_enabled=1
fast_startup=1
hiberfil_present=1
wslconfig_path=C:\\Users\\clinic\\.wslconfig
wslconfig_found=0
rdp_deny_connections=0
wu_au_options=
wu_mdm_allow_auto_update=
wu_reboot_pending=1
keepalive_task_name=TrialBox-WSL2
keepalive_task_found=0
w32time_status=Stopped
clock_windows_lo={NOW}
clock_windows_hi={NOW}
clock_linux_lo={NOW + 95}
clock_linux_hi={NOW + 95}
"""


def _facts(base: str, **changes: str) -> dict[str, str]:
    facts: dict[str, str] = policy.parse_facts(base)
    facts.update(changes)
    return facts


def _judge(facts: dict[str, str], *, strict: bool = True) -> list[str]:
    return list(policy.judge(facts, strict=strict))


def _verdict(lines: list[str], prefix: str) -> str:
    hits = [ln for ln in lines if ln[6:].startswith(prefix)]
    assert len(hits) == 1, (prefix, lines)
    return hits[0][:4]


# ------------------------------------------------------------------------------------------------ the judge
def test_a_hardened_workstation_passes_every_check() -> None:
    lines = _judge(policy.parse_facts(HARDENED))
    assert all(ln.startswith("PASS  ") for ln in lines), "\n".join(lines)
    text = "\n".join(lines)
    for want in ("BitLocker on C: (system drive) FullyEncrypted, XtsAes256, unlock TpmPin,RecoveryPassword",
                 "BitLocker on D: (drive of the WSL2 disk)", "kept by hospital IT sealed envelope",
                 "WSL2 swap off", "hibernation and Fast Startup off", "Remote Desktop off",
                 "Windows Update restarts: installs and restarts are started by hospital IT",
                 "start-at-boot task 'TrialBox-WSL2': at startup, signed in or not", "clocks: WSL2 and Windows agree",
                 "sparse, gives back freed space", "free space on D: 75%"):  # fmt: skip
        assert want in text, text


def test_a_factory_laptop_fails_on_every_point_of_the_card() -> None:
    lines = _judge(policy.parse_facts(FACTORY))
    text = "\n".join(lines)
    fails = [ln for ln in lines if ln.startswith("FAIL")]
    for want in ("BitLocker on C: the TPM alone opens it", "BitLocker recovery: say where",
                 "page file on E: which BitLocker does not protect", "hibernation: hibernation, Fast Startup",
                 "WSL2 swap: no C:\\Users\\clinic\\.wslconfig", "Remote Desktop is on", "Windows Update has no policy",
                 "start-at-boot task 'TrialBox-WSL2' missing", "clocks: WSL2 and Windows differ by 95 s",
                 "free space on C: 6%"):  # fmt: skip
        assert any(want in ln for ln in fails), (want, text)
    assert "WARN  Windows Update: a restart is pending" in text and "only grows" in text


def test_dev_and_test_warn_on_policy_but_still_fail_data_at_rest() -> None:
    lines = _judge(policy.parse_facts(FACTORY), strict=False)
    assert _verdict(lines, "Remote Desktop") == "WARN" and _verdict(lines, "Windows Update has") == "WARN"
    assert _verdict(lines, "start-at-boot") == "WARN" and _verdict(lines, "BitLocker recovery") == "WARN"
    # the data at rest checks do not soften: BitLocker, the page file, hibernation, swap
    for prefix in ("BitLocker on C:", "page file", "hibernation", "WSL2 swap"):
        assert _verdict(lines, prefix) == "FAIL", prefix


@pytest.mark.parametrize(
    ("changes", "prefix", "verdict"),
    [
        ({"bitlocker_C_status": "FullyDecrypted", "bitlocker_C_protection": "Off"}, "BitLocker on C:", "FAIL"),
        ({"bitlocker_C_protection": "Off"}, "BitLocker on C:", "FAIL"),  # suspended: the key is on the disk
        ({"bitlocker_C_status": "EncryptionInProgress"}, "BitLocker on C:", "FAIL"),
        ({"bitlocker_C_protectors": "Tpm,TpmPin,RecoveryPassword"}, "BitLocker on C:", "FAIL"),  # the Tpm alone opens it
        ({"bitlocker_C_protectors": "RecoveryPassword"}, "BitLocker on C:", "FAIL"),
        ({"bitlocker_C_protectors": "TpmNetworkKey,TpmPin,RecoveryPassword"}, "BitLocker on C:", "PASS"),
        ({"bitlocker_C_protectors": "TpmPinStartupKey,RecoveryPassword"}, "BitLocker on C:", "PASS"),
        ({"bitlocker_D_status": "FullyDecrypted", "bitlocker_D_protection": "Off"}, "BitLocker on D:", "FAIL"),
        ({"bitlocker_C_status": "unknown"}, "BitLocker on C:", "FAIL"),  # not elevated: protectors unknown
        ({"bitlocker_C_status": "unknown", "bitlocker_C_shell": "2"}, "BitLocker on C:", "FAIL"),
        ({"bitlocker_C_protectors": "TpmPin"}, "BitLocker recovery", "FAIL"),
        ({"recovery_escrow": ""}, "BitLocker recovery", "FAIL"),
        ({"pagefile_drives": "C,D"}, "page file", "PASS"),
        ({"pagefile_known": "0"}, "page file", "WARN"),
        ({"hibernate_enabled": "1"}, "hibernation", "FAIL"),
        ({"fast_startup": "1"}, "hibernation", "FAIL"),
        ({"hiberfil_present": "1"}, "hibernation", "FAIL"),
        ({"wslconfig_found": "0"}, "WSL2 swap", "FAIL"),
        ({"wslconfig_b64": base64.b64encode(b"[wsl2]\nmemory=64GB\n").decode()}, "WSL2 swap", "FAIL"),
        ({"wslconfig_b64": base64.b64encode(b"[wsl2]\nswap=8GB\n").decode()}, "WSL2 swap", "FAIL"),
        ({"wslconfig_b64": base64.b64encode(b"[wsl2]\nswap = 0GB  # off\n").decode()}, "WSL2 swap", "PASS"),
        ({"wslconfig_b64": base64.b64encode("[wsl2]\r\nswap=0\r\n".encode("utf-16")).decode()}, "WSL2 swap", "PASS"),
        ({"rdp_deny_connections": "0"}, "Remote Desktop", "FAIL"),
        ({"wu_au_options": "4", "wu_scheduled_install_day": "0", "wu_scheduled_install_time": "3"},
         "Windows Update restarts at day 0 at 3:00", "WARN"),
        ({"wu_au_options": "", "wu_mdm_allow_auto_update": "2"}, "Windows Update restarts by itself", "FAIL"),
        ({"wu_au_options": "", "wu_mdm_allow_auto_update": "5"}, "Windows Update restarts:", "PASS"),
        ({"wu_au_options": "", "wu_no_auto_update": "1"}, "Windows Update restarts:", "PASS"),
        ({"wu_au_options": ""}, "Windows Update has no policy", "FAIL"),
        ({"keepalive_task_logon_type": "Interactive"}, "start-at-boot task", "FAIL"),  # stops when nobody signs in
        ({"keepalive_task_triggers": "MSFT_TaskLogonTrigger"}, "start-at-boot task", "FAIL"),
        ({"keepalive_task_state": "Disabled"}, "start-at-boot task", "FAIL"),
        ({"keepalive_task_action": "notepad.exe "}, "start-at-boot task", "FAIL"),
        ({"clock_linux_lo": str(NOW + 30), "clock_linux_hi": str(NOW + 30)}, "clocks", "WARN"),
        ({"clock_linux_lo": str(NOW - 61), "clock_linux_hi": str(NOW - 61)}, "clocks", "FAIL"),
        ({"clock_windows_hi": ""}, "clocks", "WARN"),
        ({"w32time_status": "Stopped"}, "clocks", "WARN"),
        ({"wslconfig_b64": base64.b64encode(b"[wsl2]\nswap=0\n").decode()}, "WSL2 disk file", "WARN"),
        ({"vhdx_path": ""}, "WSL2 disk file", "WARN"),
        ({"vhdx_drive_free_gb": "300"}, "free space on D:", "WARN"),
        ({"vhdx_drive_free_gb": "100"}, "free space on D:", "FAIL"),
    ],
)  # fmt: skip
def test_each_check_judges_its_fact(changes: dict[str, str], prefix: str, verdict: str) -> None:
    assert _verdict(_judge(_facts(HARDENED, **changes)), prefix) == verdict


def test_facts_from_another_release_or_none_at_all_fail_once() -> None:
    for text in ("", "facts_version=0\nis_admin=1\n"):
        lines = _judge(policy.parse_facts(text))
        assert len(lines) == 1 and lines[0].startswith("FAIL  Windows facts: version"), lines


def test_the_last_value_of_a_fact_wins_and_a_bom_is_ignored() -> None:
    facts = policy.parse_facts("\ufefffacts_version=1\nclock_linux_lo=1\nclock_linux_lo=2\nx=a=b\n")
    assert facts["facts_version"] == "1" and facts["clock_linux_lo"] == "2" and facts["x"] == "a=b"


def test_the_command_line_reads_a_utf8_bom_file_and_exits_1_on_a_fail(tmp_path: Path) -> None:
    f = tmp_path / "facts.txt"
    f.write_bytes(HARDENED.encode("utf-8-sig"))  # what Set-Content -Encoding UTF8 writes in PowerShell 5.1
    r = subprocess.run([sys.executable, str(WIN / "wsl2_policy.py"), "--facts", str(f), "--strict"],
                       capture_output=True, text=True, timeout=30, check=False)  # fmt: skip
    assert r.returncode == 0, r.stdout
    f.write_bytes(FACTORY.encode("utf-16"))
    r = subprocess.run([sys.executable, str(WIN / "wsl2_policy.py"), "--facts", str(f)],
                       capture_output=True, text=True, timeout=30, check=False)  # fmt: skip
    assert r.returncode == 1 and "FAIL  BitLocker on C: the TPM alone opens it" in r.stdout, r.stdout


# ------------------------------------------------------------------------------------------------ the PowerShell side
def _ps(name: str) -> str:
    return (WIN / name).read_text(encoding="utf-8")


def test_host_facts_prints_every_fact_the_judge_reads() -> None:
    judge_src = (WIN / "wsl2_policy.py").read_text(encoding="utf-8")
    read = set(re.findall(r'facts\.get\(\s*f?"([a-z0-9_]+)"', judge_src))
    read |= {f"bitlocker_{{tag}}_{k}" for k in ("status", "protection", "method", "protectors", "shell")}
    read -= {"clock_linux_lo", "clock_linux_hi"}  # the WSL2 side: check_host.sh and preflight.ps1 add these
    printed = set(re.findall(r'Fact "([a-z0-9_]+(?:\$\{tag\}[a-z_]+)?)"', _ps("host_facts.ps1")))
    printed = {p.replace("${tag}", "{tag}") for p in printed}
    assert {r for r in read if "{tag}" not in r} - printed == set()
    assert {r for r in read if "{tag}" in r} <= printed, sorted(printed)
    assert 'Fact "facts_version" 1' in _ps("host_facts.ps1") and policy.FACTS_VERSION == "1"


def test_host_facts_only_reads() -> None:
    ps = _ps("host_facts.ps1")
    for verb in ("Set-", "New-ItemProperty", "Remove-", "Enable-", "Disable-", "Register-", "Start-", "Stop-",
                 "Invoke-WebRequest", "Invoke-RestMethod", "manage-bde", "powercfg", "reg add", "schtasks"):  # fmt: skip
        assert verb not in ps, verb
    # language-neutral sources only: no parsing of localised tool output
    assert "Get-BitLockerVolume" in ps and "Get-ScheduledTask" in ps and "Win32_PageFileUsage" in ps


def test_preflight_ps1_runs_the_facts_and_the_same_judge() -> None:
    ps = _ps("preflight.ps1")
    i_facts, i_judge = ps.index("host_facts.ps1"), ps.index("wsl2_policy.py", ps.index("# 7. Hardening"))
    assert i_facts < i_judge and '"--strict"' in ps and "clock_linux_lo=" in ps and '"Hardening"' in ps
    assert "Invoke-WebRequest" not in ps


def test_the_shipped_templates_pass_the_judge() -> None:
    assert _verdict(_judge(_facts(HARDENED)), "WSL2 swap") == "PASS"  # HARDENED carries wslconfig.example
    ps = _ps("register_keepalive.ps1")
    assert "-AtStartup" in ps and "-LogonType S4U" in ps and '-Execute "wsl.exe"' in ps
    assert 'TaskName = "TrialBox-WSL2"' in ps and 'TaskName = "TrialBox-WSL2"' in _ps("host_facts.ps1")


# ------------------------------------------------------------------------------------------------ check_host --wsl2
def _stubs(tmp: Path, scripts: dict[str, str]) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in scripts.items():
        p = bin_dir / name
        p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        p.chmod(0o755)
    return bin_dir


def _wsl_box(tmp: Path, facts: str, *, kernel: str = "6.6.87.2-microsoft-standard-WSL2",
             env_name: str = "PRODUCTION") -> tuple[list[str], dict[str, str]]:  # fmt: skip
    host = tmp / "host"
    for d in ("etc/cron.d", "var/lib/docker", "proc/sys/kernel"):
        (host / d).mkdir(parents=True, exist_ok=True)
    (host / "proc/sys/kernel/osrelease").write_text(kernel + "\n", encoding="utf-8")
    (host / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    for c in ("trialbox-retention", "trialbox-backup"):
        (host / "etc/cron.d" / c).write_text("# cron\n", encoding="utf-8")
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    for k in ("site_hmac.key", "pid_map.key"):
        (sec / f"{k}.wrapped").write_text("x", encoding="utf-8")
    envf = tmp / ".env"
    envf.write_text(f"TB_ENV={env_name}\n", encoding="utf-8")
    envf.chmod(0o600)
    # what powershell.exe prints, with Windows line ends; the clock is the real one, read now
    facts = re.sub(r"clock_(windows|linux)_(lo|hi)=\d+\n", "", facts)
    (tmp / "facts.txt").write_text(facts.replace("\n", "\r\n"), encoding="utf-8")
    bin_dir = _stubs(tmp, {
        "powershell.exe": f'printf "%s " "$@" > {tmp}/ps-args.txt\ncat {tmp}/facts.txt\n'
                          'printf "clock_windows_lo=%s\\r\\nclock_windows_hi=%s\\r\\n" "$(date +%s)" "$(date +%s)"\n',
        "wslpath": 'printf "%s\\n" "\\\\\\\\wsl.localhost\\\\Ubuntu-24.04$2"\n',
        "docker": "echo /var/lib/docker\n",
        "df": 'echo "Filesystem 1024-blocks Used Available Capacity Mounted"; echo "/dev/sdc 100 40 60 40% /"\n',
        "lsblk": "exit 1\n",
        "swapon": "exit 0\n",
        "nft": "exit 0\n",
        "systemctl": "exit 3\n",
        "timedatectl": "echo UTC\n",
    })  # fmt: skip
    env = {"PATH": f"{bin_dir}:{PYBIN}:/usr/bin:/bin", "HOME": str(tmp), "TB_HOST_ROOT": str(host), "TMPDIR": str(tmp)}
    env.update({k: v for k, v in os.environ.items() if k.startswith("LC_")})
    args = ["deploy/check_host.sh", "--baseline", "--wsl2", "--env", str(envf), "--secrets", str(sec),
            "--escrow", "hospital IT sealed envelope"]  # fmt: skip
    return args, env


def _sh(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", *args], capture_output=True, text=True, env=env, timeout=120, check=False, cwd=ROOT)


def test_check_host_wsl2_passes_a_hardened_workstation(tmp_path: Path) -> None:
    args, env = _wsl_box(tmp_path, HARDENED)
    r = _sh(args, env)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    for want in ("PASS  host system Ubuntu 24.04 in WSL2 on Windows", "PASS  WSL2 kernel 6.6.87.2-microsoft",
                 "PASS  BitLocker on C: (system drive) FullyEncrypted", "PASS  start-at-boot task",
                 "PASS  clocks: WSL2 and Windows agree", "PASS  swap disabled",
                 "PASS  site_hmac.key sealed under the KEK", "host baseline checks passed"):  # fmt: skip
        assert want in out, out
    # BitLocker takes the place of LUKS and the TPM device on WSL2 (the T-634 lines in their T-634 order otherwise)
    assert "LUKS" not in out and "TPM device" not in out and "TPM 2.0" not in out
    order = [out.index(s) for s in ("host system", "WSL2 kernel", "BitLocker on C:", "swap disabled", "site_hmac.key",
                                    "input firewall", "cron file")]  # fmt: skip
    assert order == sorted(order), out
    ps_args = (tmp_path / "ps-args.txt").read_text(encoding="utf-8")
    assert "-File \\\\wsl.localhost\\Ubuntu-24.04" in ps_args and "host_facts.ps1" in ps_args
    assert "-RecoveryKeyEscrow hospital IT sealed envelope" in ps_args


def test_check_host_wsl2_fails_a_factory_laptop(tmp_path: Path) -> None:
    r = _sh(*_wsl_box(tmp_path, FACTORY))
    assert r.returncode == 1, r.stdout
    for want in ("FAIL  BitLocker on C: the TPM alone opens it", "FAIL  hibernation:", "FAIL  WSL2 swap:",
                 "FAIL  Remote Desktop is on", "FAIL  Windows Update has no policy", "FAIL  start-at-boot task"):  # fmt: skip
        assert want in r.stdout, r.stdout
    assert re.search(r"^(\d+) baseline check\(s\) failed$", r.stdout, re.M)


def test_check_host_wsl2_in_dev_warns_on_policy_only(tmp_path: Path) -> None:
    facts = HARDENED.replace("rdp_deny_connections=1", "rdp_deny_connections=0")
    r = _sh(*_wsl_box(tmp_path, facts, env_name="DEV"))
    assert r.returncode == 0 and "WARN  Remote Desktop is on" in r.stdout, r.stdout


def test_check_host_wsl2_is_on_by_itself_on_a_wsl2_kernel(tmp_path: Path) -> None:
    args, env = _wsl_box(tmp_path, HARDENED)
    args.remove("--wsl2")
    r = _sh(args, env)
    assert "PASS  BitLocker on C:" in r.stdout and "LUKS" not in r.stdout, r.stdout


def test_check_host_wsl2_on_a_plain_linux_kernel_fails(tmp_path: Path) -> None:
    r = _sh(*_wsl_box(tmp_path, HARDENED, kernel="6.8.0-45-generic"))
    assert r.returncode == 1 and "FAIL  --wsl2 on a kernel that is not WSL2" in r.stdout, r.stdout


def test_check_host_wsl2_fails_when_windows_cannot_be_read(tmp_path: Path) -> None:
    args, env = _wsl_box(tmp_path, HARDENED)
    (tmp_path / "bin" / "powershell.exe").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    r = _sh(args, env)
    assert r.returncode == 1 and "FAIL  Windows facts: version ''" in r.stdout, r.stdout
