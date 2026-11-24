"""T-634 (D-408): the host baseline, run without a box. Every script runs against a fake host root (TB_HOST_ROOT) and
stub commands on PATH, or in its dry-run mode: nothing here touches the machine that runs the tests.

Acceptance (plan row T-634): `check_host` FAILs on plain site keys; the disk unlock policy refuses a TPM-only unlock
(the rental-box run of a moved disk remains); an OS patch bundle applies and the canary passes (stubbed apt)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_update_code_from_the_bundle_h124 import checkout_box
from tools.sign_bundle import build, keygen
from tools.verify_update import verify

ROOT = Path(__file__).resolve().parents[2]
HARD = ROOT / "deploy" / "hardening"
PYBIN = Path(sys.executable).parent


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HARD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


luks = _load("luks_policy")
ospatch = _load("ospatch")


def _stubs(tmp: Path, scripts: dict[str, str]) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in scripts.items():
        p = bin_dir / name
        p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        p.chmod(0o755)
    return bin_dir


def _env(tmp: Path, bin_dir: Path, **extra: str) -> dict[str, str]:
    env = {"PATH": f"{bin_dir}:{PYBIN}:/usr/bin:/bin", "HOME": str(tmp), "TB_HOST_ROOT": str(tmp / "host"),
           "TMPDIR": str(tmp)}  # fmt: skip
    env.update({k: v for k, v in os.environ.items() if k.startswith("LC_")})
    env.update(extra)
    return env


def _jobs(bin_dir: Path, n: int = 0) -> dict[str, str]:
    """T-695 (D-752): a ``docker`` that answers the orchestrator's job count with ``n``, and the tree on the path."""
    _stubs(bin_dir.parent, {"docker": f'case "$*" in *orch.jobs*) echo {n};; esac\n'})
    return {"PYTHONPATH": str(ROOT)}


def _sh(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", *args], capture_output=True, text=True, env=env, timeout=120, check=False, cwd=ROOT)


# ------------------------------------------------------------------------------------------------ the unlock policy
TPM_ONLY = {"tokens": {"0": {"type": "systemd-tpm2", "keyslots": ["1"], "tpm2-pin": False}}}
TPM_PIN = {"tokens": {"0": {"type": "systemd-tpm2", "keyslots": ["1"], "tpm2-pin": True}}}
NO_TOKENS: dict[str, Any] = {"tokens": {}}
TANG_AND_TPM = """1: sss '{"t":2,"pins":{"sss":{"t":1,"pins":{"tang":[{"url":"http://tang1.hospital.invalid"}]}},"tpm2":{"pcr_ids":"7"}}}'"""
TANG_OR_TPM = """1: sss '{"t":1,"pins":{"tang":[{"url":"http://tang1.hospital.invalid"}],"tpm2":{"pcr_ids":"7"}}}'"""


@pytest.mark.parametrize(
    ("dump", "clevis", "verdict"),
    [
        (TPM_ONLY, "", "FAIL"),  # OPS-043: the documented setup of before, a stolen box unlocks itself
        (TPM_PIN, "", "PASS"),
        (NO_TOKENS, '2: tpm2 \'{"pcr_ids":"7"}\'', "FAIL"),
        (NO_TOKENS, TANG_OR_TPM, "FAIL"),  # either one: the TPM alone is enough
        (NO_TOKENS, TANG_AND_TPM, "PASS"),  # both: a moved disk does not open
        (NO_TOKENS, '3: tang \'{"url":"http://tang1.hospital.invalid"}\'', "PASS"),
        (NO_TOKENS, "", "WARN"),
        ({"tokens": {"0": {"type": "clevis", "keyslots": ["1"]}}}, "", "FAIL"),  # cannot be read: not trusted
    ],
)
def test_the_unlock_policy_refuses_any_way_in_without_the_hospital(dump: Any, clevis: str, verdict: str) -> None:
    lines = luks.judge(dump, clevis)
    assert lines and {ln[:4] for ln in lines} == {verdict}, lines


def test_a_tpm_only_token_beside_a_good_binding_still_fails() -> None:
    lines = luks.judge(TPM_ONLY, TANG_AND_TPM)
    assert any(ln.startswith("FAIL") for ln in lines) and any(ln.startswith("PASS") for ln in lines)


def test_disk_unlock_binds_tpm_and_tang_and_its_policy_passes(tmp_path: Path) -> None:
    conf = tmp_path / "h.conf"
    conf.write_text('TANG_URLS="http://tang1.hospital.invalid http://tang2.hospital.invalid"\n', encoding="utf-8")
    r = _sh(["deploy/hardening/disk-unlock.sh", "bind", "--device", "/dev/fake0", "--conf", str(conf), "--dry-run"],
            _env(tmp_path, _stubs(tmp_path, {})))  # fmt: skip
    assert r.returncode == 0, r.stderr
    bind = next(ln for ln in r.stdout.splitlines() if "would run: clevis luks bind" in ln)
    policy = bind.split(" sss ", 1)[1]
    assert json.loads(policy)["t"] == 2
    # the very policy the script binds is the one the host check passes
    assert [ln[:4] for ln in luks.judge(NO_TOKENS, f"1: sss '{policy}'")] == ["PASS"]
    assert "would run: systemd-cryptenroll --wipe-slot=tpm2 /dev/fake0" in r.stdout


def test_disk_unlock_refuses_without_a_tang_server(tmp_path: Path) -> None:
    conf = tmp_path / "h.conf"
    conf.write_text('TANG_URLS=""\n', encoding="utf-8")
    r = _sh(["deploy/hardening/disk-unlock.sh", "bind", "--device", "/dev/fake0", "--conf", str(conf), "--dry-run"],
            _env(tmp_path, _stubs(tmp_path, {})))  # fmt: skip
    assert r.returncode == 1 and "TANG_URLS is empty" in r.stderr


# ------------------------------------------------------------------------------------------------ firewall and SSH
def _conf(tmp: Path, **kw: str) -> Path:
    vals = {"CLINIC_RANGES": "192.0.2.0/24 2001:db8::/32", "SSH": "off", "IT_RANGES": "203.0.113.0/28", **kw}
    p = tmp / "hardening.conf"
    p.write_text("".join(f'{k}="{v}"\n' for k, v in vals.items()), encoding="utf-8")
    return p


def test_the_firewall_renders_443_from_the_clinic_only(tmp_path: Path) -> None:
    env = _env(tmp_path, _stubs(tmp_path, {}))
    r = _sh(["deploy/hardening/apply.sh", "--conf", str(_conf(tmp_path)), "render"], env)
    assert r.returncode == 0, r.stderr
    rules = r.stdout
    assert "table inet trialbox_input {" in rules and "policy drop;" in rules
    assert "elements = { 192.0.2.0/24 }" in rules and "elements = { 2001:db8::/32 }" in rules
    assert "hook prerouting priority -150" in rules and "fib daddr type local tcp dport 443 counter drop" in rules
    assert "dport 22" not in rules  # SSH off
    r = _sh(["deploy/hardening/apply.sh", "--conf", str(_conf(tmp_path, SSH="it")), "render"], env)
    assert "tcp dport 22 ip saddr @it_v4 accept" in r.stdout


@pytest.mark.parametrize("bad", ["", "192.0.2.0/24; flush ruleset", "any"])
def test_the_firewall_refuses_a_missing_or_bad_range(tmp_path: Path, bad: str) -> None:
    r = _sh(["deploy/hardening/apply.sh", "--conf", str(_conf(tmp_path, CLINIC_RANGES=bad)), "render"],
            _env(tmp_path, _stubs(tmp_path, {})))  # fmt: skip
    assert r.returncode == 1 and ("CLINIC_RANGES" in r.stderr), r.stdout + r.stderr


def test_the_rendered_ruleset_parses_in_nft(tmp_path: Path) -> None:
    nft = shutil.which("nft")
    if not nft:
        pytest.skip("nft not installed")
    out = _sh(["deploy/hardening/apply.sh", "--conf", str(_conf(tmp_path, SSH="it")), "render"],
              _env(tmp_path, _stubs(tmp_path, {}))).stdout  # fmt: skip
    f = tmp_path / "input.nft"
    f.write_text(out, encoding="utf-8")
    r = subprocess.run([nft, "-c", "-f", str(f)], capture_output=True, text=True, check=False, timeout=30)
    if r.returncode != 0 and ("Operation not permitted" in r.stderr or "netlink" in r.stderr.lower()):
        pytest.skip("nft -c needs CAP_NET_ADMIN here")
    assert r.returncode == 0, r.stderr  # -c checks only: nothing is loaded


def test_apply_dry_run_changes_nothing(tmp_path: Path) -> None:
    log = tmp_path / "calls.log"
    bin_dir = _stubs(tmp_path, {n: f'echo "{n} $*" >> {log}\n' for n in ("nft", "systemctl", "sshd")})
    r = _sh(["deploy/hardening/apply.sh", "--conf", str(_conf(tmp_path, SSH="it")), "--dry-run", "all"],
            _env(tmp_path, bin_dir))  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert "would write:" in r.stdout and "would run: nft -f" in r.stdout
    assert not log.exists() and not (tmp_path / "host").exists()


def test_apply_writes_the_rules_the_unit_and_sshd_under_the_host_root(tmp_path: Path) -> None:
    log = tmp_path / "calls.log"
    bin_dir = _stubs(tmp_path, {n: f'echo "{n} $*" >> {log}\n' for n in ("nft", "systemctl", "sshd")})
    r = _sh(["deploy/hardening/apply.sh", "--conf", str(_conf(tmp_path, SSH="it")), "all"], _env(tmp_path, bin_dir))
    assert r.returncode == 0, r.stderr
    host = tmp_path / "host"
    assert (host / "etc/trialbox/input.nft").stat().st_mode & 0o777 == 0o600
    unit = (host / "etc/systemd/system/trialbox-input.service").read_text(encoding="utf-8")
    assert "@TB_ROOT@" not in unit and "nft -f /etc/trialbox/input.nft" in unit
    sshd = (host / "etc/ssh/sshd_config.d/50-trialbox.conf").read_text(encoding="utf-8")
    assert "PasswordAuthentication no" in sshd and "PermitRootLogin no" in sshd
    calls = log.read_text(encoding="utf-8")
    assert f"nft -c -f {host}/etc/trialbox/input.nft" in calls and "sshd -t" in calls


# ------------------------------------------------------------------------------------------------ check_host --baseline
def _box(tmp: Path, *, tpm_only: bool = False, plain: bool = False, crypt: bool = True,
         env_name: str = "PRODUCTION") -> tuple[list[str], dict[str, str]]:  # fmt: skip
    host = tmp / "host"
    for d in ("etc/cron.d", "var/lib/docker", "dev", "etc/credstore.encrypted"):
        (host / d).mkdir(parents=True, exist_ok=True)
    (host / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    for c in ("trialbox-retention", "trialbox-backup"):
        (host / "etc/cron.d" / c).write_text("# cron\n", encoding="utf-8")
    (host / "dev/tpmrm0").touch()
    (host / "etc/credstore.encrypted/trialbox-kek").write_bytes(b"sealed")
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "kek.json").write_text('{"backend": "file"}', encoding="utf-8")
    for k in ("site_hmac.key", "pid_map.key"):
        (sec / (k if plain else f"{k}.wrapped")).write_text("x", encoding="utf-8")
    envf = tmp / ".env"
    envf.write_text(f"TB_ENV={env_name}\n", encoding="utf-8")
    envf.chmod(0o600)
    (tmp / "dump.json").write_text(json.dumps(TPM_ONLY if tpm_only else NO_TOKENS), encoding="utf-8")
    (tmp / "clevis.txt").write_text("" if tpm_only else TANG_AND_TPM + "\n", encoding="utf-8")
    lsblk = 'echo "luks-root crypt"; echo "nvme0n1p3 part"' if crypt else 'echo "nvme0n1p2 part"'
    bin_dir = _stubs(tmp, {
        "docker": 'echo /var/lib/docker\n',
        "df": 'case "$1" in --output=source) echo Filesystem; echo /dev/mapper/root ;;\n'
              '  *) echo "Filesystem 1024-blocks Used Available Capacity Mounted"; '
              'echo "/dev/mapper/root 100 40 60 40% /" ;; esac\n',
        "lsblk": lsblk + "\n",
        "cryptsetup": f'case "$1" in status) echo "  device:  /dev/nvme0n1p3" ;; luksDump) cat {tmp}/dump.json ;; esac\n',
        "clevis": f"cat {tmp}/clevis.txt\n",
        "swapon": "exit 0\n",
        "nft": "exit 0\n",
        "systemctl": "exit 3\n",
        "timedatectl": "echo Asia/Taipei\n",
    })  # fmt: skip
    args = ["deploy/check_host.sh", "--baseline", "--env", str(envf), "--secrets", str(sec)]
    return args, _env(tmp, bin_dir)


def test_check_host_baseline_passes_a_hardened_box(tmp_path: Path) -> None:
    args, env = _box(tmp_path)
    r = _sh(args, env)
    assert r.returncode == 0, r.stdout + r.stderr
    for want in ("PASS  host system Ubuntu 24.04", "PASS  LUKS: /var/lib/docker is on the encrypted device luks-root",
                 "needs a Tang server", "PASS  site_hmac.key sealed under the KEK", "PASS  input firewall loaded",
                 "PASS  SSH off", "PASS  cron file /etc/cron.d/trialbox-backup", "PASS  free space on /var/lib/docker: 60%",
                 "host baseline checks passed"):  # fmt: skip
        assert want in r.stdout, r.stdout


def test_check_host_fails_on_plain_site_keys_in_production(tmp_path: Path) -> None:
    r = _sh(*_box(tmp_path, plain=True))
    assert r.returncode == 1
    assert "FAIL  site_hmac.key is a plain file" in r.stdout and "FAIL  pid_map.key is a plain file" in r.stdout


def test_check_host_only_warns_on_plain_keys_in_dev(tmp_path: Path) -> None:
    r = _sh(*_box(tmp_path, plain=True, env_name="DEV"))
    assert r.returncode == 0, r.stdout
    assert "WARN  site_hmac.key is a plain file" in r.stdout


def test_check_host_fails_a_tpm_only_unlock(tmp_path: Path) -> None:
    r = _sh(*_box(tmp_path, tpm_only=True))
    assert r.returncode == 1 and "TPM2 without a PIN opens the disk anywhere" in r.stdout, r.stdout


def test_check_host_fails_when_docker_data_is_not_on_dm_crypt(tmp_path: Path) -> None:
    r = _sh(*_box(tmp_path, crypt=False))
    assert r.returncode == 1 and "FAIL  LUKS: /var/lib/docker is not on a dm-crypt device" in r.stdout, r.stdout


# ------------------------------------------------------------------------------------------------ sealed keys at install
def test_seal_keys_wraps_the_plain_keys_under_a_tpm_sealed_kek(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    host = tmp_path / "host"
    (host / "dev").mkdir(parents=True)
    (host / "dev/tpmrm0").touch()
    sec = tmp_path / "secrets"
    sec.mkdir()
    for k in ("site_hmac.key", "pid_map.key"):
        (sec / k).write_bytes(os.urandom(32))
        (sec / k).chmod(0o600)
    # systemd-creds stand-in: the "sealed" credential is a marked copy (the real one is bound to host key and TPM)
    # D-836: seal_keys.sh asks `systemd-creds has-tpm2` first: the stand-in's TPM is usable
    bin_dir = _stubs(tmp_path, {"systemd-creds": '[ "$1" = has-tpm2 ] && exit 0\n[ "$1" = encrypt ] || exit 2\n'
                                '{ echo SEALED; cat "$4"; } > "$5"\n'})  # fmt: skip
    conf = tmp_path / "h.conf"
    conf.write_text("KEK_BACKEND=tpm\n", encoding="utf-8")
    env = _env(tmp_path, bin_dir, TB_ENV="PRODUCTION", TB_SYSTEMD_DIR=str(tmp_path / "units"))
    (tmp_path / "units").mkdir()
    r = _sh(["deploy/hardening/seal_keys.sh", "--secrets", str(sec), "--conf", str(conf)], env)
    assert r.returncode == 0, r.stdout + r.stderr
    # NEW-STD-2 (D-562): the audit signing key is made here too, wrapped under the same KEK
    assert sorted(p.name for p in sec.iterdir()) == [
        "audit_sign.key.wrapped", "audit_sign.pub", "kek.json", "pid_map.key.wrapped", "site_hmac.key.wrapped",
    ]  # fmt: skip
    kek = host / "run/trialbox/kek"
    assert kek.stat().st_mode & 0o777 == 0o600 and len(kek.read_bytes()) == 32
    cred = host / "etc/credstore.encrypted/trialbox-kek"
    assert cred.read_bytes().startswith(b"SEALED") and not (host / "run/trialbox/kek.new").exists()
    unit = (tmp_path / "units/trialbox-unseal.service").read_text(encoding="utf-8")
    assert f"--secrets {sec}" in unit and "LoadCredentialEncrypted=trialbox-kek" in unit
    # again: idempotent (the KEK exists, nothing is plain)
    r = _sh(["deploy/hardening/seal_keys.sh", "--secrets", str(sec), "--conf", str(conf)], env)
    assert r.returncode == 0 and "no plain key left to wrap" in r.stdout, r.stdout + r.stderr


def test_seal_keys_refuses_tpm_without_a_tpm(tmp_path: Path) -> None:
    sec = tmp_path / "secrets"
    sec.mkdir()
    conf = tmp_path / "h.conf"
    conf.write_text("KEK_BACKEND=tpm\n", encoding="utf-8")
    r = _sh(["deploy/hardening/seal_keys.sh", "--secrets", str(sec), "--conf", str(conf)],
            _env(tmp_path, _stubs(tmp_path, {"systemd-creds": "exit 0\n"})))  # fmt: skip
    assert r.returncode == 1 and "no TPM 2.0 device" in r.stderr


def test_install_seals_before_the_stack_starts_and_applies_the_baseline_after_egress() -> None:
    sh = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    keys, seal = sh.index("adapter.cli keys-init"), sh.index("deploy/hardening/seal_keys.sh --secrets")
    up = sh.index('"${UP_EXTRA[@]}" --wait')
    egress, base = sh.index("deploy/network.sh apply; then"), sh.index("deploy/hardening/apply.sh --conf")
    assert keys < seal < up and egress < base


# ------------------------------------------------------------------------------------------------ OS patch bundles
def _dpkg_stubs(tmp: Path, *, installed: tuple[str, ...], held: tuple[str, ...] = ()) -> tuple[Path, Path]:
    log = tmp / "apt.log"
    inst = " ".join(installed)
    bin_dir = _stubs(tmp, {
        "dpkg-deb": 'n=$(basename "$2" .deb); echo "Package: ${n%%_*}"; echo "Version: 1.0-1"; '
                    'echo "Architecture: amd64"\n',
        "dpkg": 'echo amd64\n',
        "apt-mark": f'echo "{" ".join(held)}"\n',
        "dpkg-query": f'case " {inst} " in *" $3 "*) echo "install ok installed" ;; '
                      '*) echo "unknown ok not-installed" ;; esac\n',
        "apt-get": f'echo "apt-get $*" >> {log}\n',
    })  # fmt: skip
    return bin_dir, log


def _ospatch_bundle(tmp: Path, bin_dir: Path, snapshot: str = "2026-11-01", version: str = "24.04") -> dict[str, Path]:
    debs = tmp / "debs"
    debs.mkdir(exist_ok=True)
    for n in (
        "openssl_3.0.13-0ubuntu3.6_amd64",
        "libssl3t64_3.0.13-0ubuntu3.6_amd64",
        "nvidia-driver-580_580.142_amd64",
    ):
        (debs / f"{n}.deb").write_bytes(os.urandom(256))
    out = tmp / f"payload-{snapshot}"
    r = subprocess.run([sys.executable, str(HARD / "ospatch.py"), "make", "--debs", str(debs), "--out", str(out),
                        "--snapshot", snapshot, "--version", version],
                       env=_env(tmp, bin_dir), capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    keys = tmp / "keys"
    if not (keys / "vendor_ed25519.key").exists():
        keygen(keys)
    items = [("other", p, f"ospatch/{p.relative_to(out).as_posix()}") for p in sorted(out.rglob("*")) if p.is_file()]
    bundle = tmp / f"ospatch-{snapshot}.tar"
    build(keys / "vendor_ed25519.key", f"ospatch-{snapshot}", items, bundle, description="OS patch (synthetic)")
    return {"bundle": bundle, "pub": keys / "vendor_ed25519.pub", "payload": out}


def test_an_os_patch_bundle_dry_run_through_apply_update(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    bin_dir, log = _dpkg_stubs(tmp_path, installed=("openssl", "libssl3t64", "nvidia-driver-580"),
                               held=("nvidia-driver-580",))  # fmt: skip
    b = _ospatch_bundle(tmp_path, bin_dir)
    host = tmp_path / "host/etc"
    host.mkdir(parents=True)
    (host / "os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    env = _env(tmp_path, bin_dir)
    script = str(checkout_box(tmp_path, b["pub"]) / "tools/apply_update.sh")  # H-124: the box's own key file
    r = _sh([script, "ospatch", str(b["bundle"]), "--dry-run"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "verified:" in r.stdout and "would upgrade openssl" in r.stdout
    assert "held, left as it is: nvidia-driver-580" in r.stdout and "dry run: nothing changed" in r.stdout
    assert not log.exists()
    # the same bundle on the TrialBox update path is refused
    r = _sh([script, str(b["bundle"]), "--dry-run"], env)
    assert r.returncode == 1 and "is an OS patch bundle" in r.stderr


def _staged(tmp: Path, b: dict[str, Path]) -> Path:
    stage = tmp / f"stage-{b['bundle'].stem}"
    verify(b["bundle"], b["pub"], stage)
    return stage


def test_an_os_patch_applies_and_the_canary_passes(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    bin_dir, log = _dpkg_stubs(tmp_path, installed=("openssl", "libssl3t64", "nvidia-driver-580"),
                               held=("nvidia-driver-580",))  # fmt: skip
    b = _ospatch_bundle(tmp_path, bin_dir)
    (tmp_path / "host/etc").mkdir(parents=True)
    (tmp_path / "host/etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    deploy = tmp_path / "box/deploy"
    deploy.mkdir(parents=True)
    canary_log = tmp_path / "canary.log"
    conf = tmp_path / "h.conf"
    conf.write_text(f'CANARY_CMD="echo ran >> {canary_log}"\n', encoding="utf-8")
    env = _env(tmp_path, bin_dir, **_jobs(bin_dir))
    args = [sys.executable, str(HARD / "ospatch.py"), "apply", "--stage", str(_staged(tmp_path, b)),
            "--deploy", str(deploy), "--conf", str(conf)]  # fmt: skip
    r = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls[0].endswith(" update") and "Dir::Etc::SourceParts=/dev/null" in calls[0]
    assert "install --only-upgrade libssl3t64 openssl" in calls[1] and "nvidia" not in calls[1]
    src = next(p for p in calls[0].split() if "SourceList=" in p).split("=", 1)[1]
    assert "tb-ospatch-" in src  # a temporary list: the host's own sources are not read
    rec = json.loads((deploy / "updates/ospatch/2026-11-01.json").read_text(encoding="utf-8"))
    assert rec["canary"] == "passed" and rec["held"] == ["nvidia-driver-580"]
    assert canary_log.read_text(encoding="utf-8").strip() == "ran"
    # no going back: the same snapshot again is refused
    r = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "not newer than 2026-11-01" in r.stderr


def test_a_kernel_patch_waits_for_the_reboot_then_the_canary(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    bin_dir, _ = _dpkg_stubs(tmp_path, installed=("openssl", "libssl3t64"))
    b = _ospatch_bundle(tmp_path, bin_dir)
    (tmp_path / "host/etc").mkdir(parents=True)
    (tmp_path / "host/etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    (tmp_path / "host/var/run").mkdir(parents=True)
    (tmp_path / "host/var/run/reboot-required").touch()
    deploy = tmp_path / "box/deploy"
    deploy.mkdir(parents=True)
    conf = tmp_path / "h.conf"
    conf.write_text('CANARY_CMD="false"\n', encoding="utf-8")
    env = _env(tmp_path, bin_dir, **_jobs(bin_dir))
    r = subprocess.run([sys.executable, str(HARD / "ospatch.py"), "apply", "--stage", str(_staged(tmp_path, b)),
                        "--deploy", str(deploy), "--conf", str(conf)], env=env, capture_output=True, text=True,
                       check=False)  # fmt: skip
    assert r.returncode == 0 and "reboot needed" in r.stdout, r.stdout + r.stderr
    assert (deploy / "updates/ospatch/REBOOT_PENDING.json").exists()
    # after the reboot: a failing canary is exit 1 and stays recorded
    chk = [sys.executable, str(HARD / "ospatch.py"), "check", "--deploy", str(deploy), "--conf", str(conf)]
    r = subprocess.run(chk, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "canary FAILED" in r.stderr
    assert json.loads((deploy / "updates/ospatch/2026-11-01.json").read_text(encoding="utf-8"))["canary"] == "failed"
    conf.write_text('CANARY_CMD="true"\n', encoding="utf-8")
    r = subprocess.run(chk, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0 and not (deploy / "updates/ospatch/REBOOT_PENDING.json").exists()


def test_an_os_patch_for_another_system_is_refused(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    bin_dir, log = _dpkg_stubs(tmp_path, installed=("openssl",))
    b = _ospatch_bundle(tmp_path, bin_dir, version="22.04")
    (tmp_path / "host/etc").mkdir(parents=True)
    (tmp_path / "host/etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(HARD / "ospatch.py"), "apply", "--stage", str(_staged(tmp_path, b)),
                        "--deploy", str(tmp_path / "deploy")], env=_env(tmp_path, bin_dir), capture_output=True,
                       text=True, check=False)  # fmt: skip
    assert r.returncode == 1 and "ubuntu 22.04; this host runs ubuntu 24.04" in r.stderr
    assert not log.exists()


def test_an_os_patch_is_refused_under_a_running_job(tmp_path: Path) -> None:
    """T-695 (D-752, F-10): an upgrade can restart the container runtime and the reboot stops every container."""
    pytest.importorskip("cryptography")
    bin_dir, log = _dpkg_stubs(tmp_path, installed=("openssl", "libssl3t64"))
    b = _ospatch_bundle(tmp_path, bin_dir)
    (tmp_path / "host/etc").mkdir(parents=True)
    (tmp_path / "host/etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    deploy = tmp_path / "box/deploy"
    deploy.mkdir(parents=True)
    for n, said in ((2, "2 job(s) running"), (None, "could not be counted")):
        env = _env(tmp_path, bin_dir, **_jobs(bin_dir, 2))
        if n is None:  # the database does not answer
            _stubs(tmp_path, {"docker": "exit 1\n"})
        r = subprocess.run([sys.executable, str(HARD / "ospatch.py"), "apply", "--stage", str(_staged(tmp_path, b)),
                            "--deploy", str(deploy)], env=env, capture_output=True, text=True, check=False)  # fmt: skip
        assert r.returncode == 1 and said in r.stderr, r.stdout + r.stderr
        assert not log.exists() or "install" not in log.read_text(encoding="utf-8")  # nothing upgraded


# ------------------------------------------------------------------------------- a host without a TPM (H-89, item 1)
SECRET_PP = "correct-horse-battery-staple-h89"


@pytest.mark.parametrize(
    ("extra", "kek", "env_name", "status"),
    [
        ({}, "file", "PRODUCTION", "FAIL"),  # no passphrase back end: as before
        # H-96 (the integrator's rulings 7094934985 and 7102655419, L-3): the back end only named, nothing sealed
        # under it: a FAIL on PRODUCTION; on a PoC box a WARN and one line of the PoC list (D-1091)
        ({"TB_KEK_BACKEND": "passphrase"}, "file", "PRODUCTION", "FAIL"),
        ({"TB_KEK_BACKEND": "passphrase"}, "file", "TEST", "WARN"),
        ({"TB_KEK_PASSPHRASE": SECRET_PP}, "file", "PRODUCTION", "FAIL"),  # a passphrase without the back end
        ({"TB_KEK_BACKEND": "passphrase", "TB_KEK_PASSPHRASE": SECRET_PP}, "file", "PRODUCTION", "FAIL"),
        # H-97 (the integrator's ruling 7104745003): the site keys already sealed under it follow the same rule: a
        # FAIL on PRODUCTION that names the action (a WARN before), a listed WARN on a PoC box
        ({}, "passphrase", "PRODUCTION", "FAIL"),
        ({}, "passphrase", "TEST", "WARN"),
        ({"TB_ENV": "TEST"}, "passphrase", "PRODUCTION", "FAIL"),  # a caller's variable does not make it a PoC box
        # the review of #1429, F7 (D-1091): no caller's TB_ENV makes a PRODUCTION box a PoC box, for either line
        ({"TB_ENV": "DEV"}, "passphrase", "PRODUCTION", "FAIL"),
        ({"TB_ENV": "VALIDATION"}, "passphrase", "PRODUCTION", "FAIL"),
        ({"TB_ENV": "DEV", "TB_KEK_BACKEND": "passphrase"}, "file", "PRODUCTION", "FAIL"),
    ],
)
def test_no_tpm_fails_unless_the_passphrase_back_end_is_chosen(
    tmp_path: Path, extra: dict[str, str], kek: str, env_name: str, status: str
) -> None:
    args, env = _box(tmp_path, env_name=env_name)
    (tmp_path / "host" / "dev" / "tpmrm0").unlink()
    (tmp_path / "secrets" / "kek.json").write_text(f'{{"backend": "{kek}"}}', encoding="utf-8")
    r = _sh(args, {**env, **extra})
    line = next(ln for ln in r.stdout.splitlines() if "no TPM device" in ln)
    assert line.startswith(status), r.stdout
    if status == "WARN":
        assert "passphrase back end" in line
    listed = tmp_path / "site" / "poc-stops.jsonl"
    if env_name != "PRODUCTION" and (kek == "passphrase" or extra.get("TB_KEK_BACKEND")):
        key = "check_host.sh/no-tpm-sealed" if kek == "passphrase" else "check_host.sh/no-tpm"
        assert [json.loads(x)["key"] for x in listed.read_text(encoding="utf-8").splitlines()] == [key]
    else:
        assert not listed.exists()  # never listed on PRODUCTION
    if kek == "passphrase":  # the action: on the FAIL line, or on the doctor's line of the PoC list
        from tools.trialbox import stops

        said = line if status == "FAIL" else " ".join(d for _, d in stops.doctor_lines(tmp_path))
        assert "reseal the site keys under a TPM" in said, said
    assert SECRET_PP not in r.stdout + r.stderr


def test_sealed_keys_without_a_tpm_say_when_the_poc_list_line_was_not_written(tmp_path: Path) -> None:
    """H-97 part D, in H-96's form (R2-2): on a TEST box whose list cannot be written (a folder there), keys already
    sealed under the passphrase are a WARN that says it was NOT listed and names the action; never a FAIL."""
    args, env = _box(tmp_path, env_name="TEST")
    (tmp_path / "host" / "dev" / "tpmrm0").unlink()
    (tmp_path / "secrets" / "kek.json").write_text('{"backend": "passphrase"}', encoding="utf-8")
    (tmp_path / "site" / "poc-stops.jsonl").mkdir(parents=True)
    r = _sh(args, env)
    line = next(ln for ln in r.stdout.splitlines() if "no TPM device" in ln)
    assert line.startswith("WARN") and "NOT listed, deploy/site/poc-stops.jsonl cannot be written" in line, r.stdout
    assert "reseal the site keys under a TPM" in line
