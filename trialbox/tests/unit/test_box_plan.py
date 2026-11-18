"""T-729 (D-466): the owner's answers plus the detected hardware give complete settings, and nothing else is asked.

The plan is fed to the real settings wizard (the same validation the services run at start) and its result to the
static checks of ``trialbox doctor``; the profile comes from ``deploy/gpu_profile.sh``; the memory caps follow the RAM
(OD-10); TLS is ``internal`` under the box's name; the KEK back end follows the TPM. The IT-managed answers file of
the rehearsal still builds as before (v6.1 §4.4)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common.box_answers import BackupKind, SourceKind, owner_accounts, parse

from tools import settings_wizard
from tools.box import plan as bp
from tools.box.__main__ import KEEP, main, merge_env
from tools.trialbox import doctor

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
PRO6000 = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"
OWNER: dict[str, Any] = {
    "site_name": "示範醫院A (synthetic)", "tz": "Asia/Tokyo", "language": "ja",
    "owner": {"full_name": "Dr Owner", "username": "owner", "email": "owner@hospa.test"},
    "box_name": "trialbox", "backup": {"kind": "second_disk", "disk": "/dev/sdb"}, "source": "spreadsheet",
}  # fmt: skip


def _hw(**over: Any) -> bp.Hardware:
    base: dict[str, Any] = {
        "arch": "x86_64", "cpu_count": 32, "ram_gib": 128.0, "disk_free_gib": 1800.0, "gpu_name": PRO6000,
        "gpu_mem_gib": 96.0, "tpm": True, "disks": (bp.Disk("/dev/sdb", 3726.0, "sata"),), "lan": "192.0.2.0/24",
        "hostname": "box1", "host_tz": "Asia/Tokyo",
    }  # fmt: skip
    return bp.Hardware(**(base | over))


def _answers(**over: Any) -> Any:
    a, problems = parse(OWNER | over, disks=("/dev/sdb",))
    assert a is not None, problems
    return a


def _build(p: bp.BoxPlan, tmp_path: Path) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    for rel, text in p.files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return settings_wizard.build(json.loads(json.dumps(p.wizard_answers)), [tmp_path / "site" / "mapping"])


def test_answers_and_hardware_give_complete_settings_that_pass_doctors_static_checks(tmp_path: Path) -> None:
    p = bp.plan(_answers(), _hw())
    assert (p.profile, p.mode, p.install_args) == ("rtxpro6000", "gpu", ["--mode", "gpu", "--gpu", "rtxpro6000"])
    settings, env, _ = _build(p, tmp_path)
    out = tmp_path / "settings.yaml"
    settings_wizard.write(settings, env, out, tmp_path / ".env")  # the services' own validation (load_settings)
    assert settings["site"] == {"id": "A-SYNTHETIC", "name": "示範醫院A (synthetic)",
                                "tz": "Asia/Tokyo", "locale": "ja", "contact": "owner@hospa.test"}  # fmt: skip
    assert env["TB_TLS_MODE"] == "internal" and env["TB_TLS_HOSTNAME"] == "trialbox.local"
    assert env["TB_CONSOLE_URL"] == "https://trialbox.local" and env["TB_TZ"] == "Asia/Tokyo"
    assert env["TB_BACKUP_TARGETS"] == env["TB_BACKUP_OFFBOX"] == bp.SECOND_DISK_MOUNT
    assert settings["retention"] == settings_wizard.build({**p.wizard_answers, "retention_rules": "jp"},
                                                          [tmp_path / "site" / "mapping"])[0]["retention"]  # fmt: skip
    # doctor's static checks on the box's files as install.sh leaves them (PRODUCTION, TOTP default, pair named)
    box_env = env | {"TB_ENV": "PRODUCTION", "TB_GATEWAY_VERIFIER_MODEL": "v-verifier", "TB_GATEWAY_MODEL": "j-workhorse",
                     "TB_GATEWAY_URL": "http://gateway:8020/v1"}  # fmt: skip
    inp = doctor.DoctorInputs(env=box_env, settings=yaml.safe_load(out.read_text(encoding="utf-8")),
                              host_tz="Asia/Tokyo", deploy=tmp_path)  # fmt: skip
    for check in (doctor.check_topology, doctor.check_env_class_ceiling, doctor.check_secure_cookie,
                  doctor.check_console_mfa, doctor.check_site_tz, doctor.check_note_block, doctor.check_channel_engine):  # fmt: skip
        got = check(inp)
        assert got.status == "PASS", got


def test_nothing_is_asked_twice_and_no_answer_needs_a_shell() -> None:
    """The owner's answers are the schema's seven; every other wizard key is derived; none is a path or a command."""
    p = bp.plan(_answers(), _hw())
    asked = {"site_name", "tz", "locale", "contact", "tls_hostname"}  # straight from the owner's answers
    derived = set(p.wizard_answers) - asked
    for key in derived:
        assert key not in OWNER, key
    owner_values = json.dumps(OWNER, ensure_ascii=False)
    for forbidden in ("/etc", "docker", "compose", "sudo", "nft", "ssh"):
        assert forbidden not in owner_values


@pytest.mark.parametrize(
    ("arch", "card", "profile", "mode"),
    [
        ("x86_64", PRO6000, "rtxpro6000", "gpu"),
        ("aarch64", "NVIDIA GB10", "gb10", "gpu"),
        ("x86_64", "NVIDIA GeForce RTX 5090", "rtx5090", "gpu"),
        ("x86_64", "NVIDIA GeForce RTX 4090", "rtx4090", "gpu"),
        ("x86_64", "", "none", "stub"),
    ],
)
def test_the_profile_is_gpu_profile_sh(arch: str, card: str, profile: str, mode: str) -> None:
    p = bp.plan(_answers(), _hw(arch=arch, gpu_name=card))
    assert (p.profile, p.mode) == (profile, mode)


def test_a_shared_card_is_not_a_box() -> None:
    with pytest.raises(bp.PlanError, match="shared platform"):
        bp.plan(_answers(), _hw(gpu_name="NVIDIA B200", mig="Enabled"))


def test_memory_caps_follow_the_ram_od10() -> None:
    def total(caps: dict[str, str]) -> float:
        return sum(int(v[:-1]) for v in caps.values()) / 1024

    small, _ = bp.memory_caps(96, "rtxpro6000")
    big, _ = bp.memory_caps(256, "rtxpro6000")
    var, fixed = bp.compose_caps([ROOT / "deploy" / f for f in ("docker-compose.yml", "docker-compose.identity.yml",
                                                                "docker-compose.rtxpro6000.yml")])  # fmt: skip
    assert set(small) == set(var) and total(small) <= 96 - max(4, 9.6) - fixed + 0.01
    assert int(big["TB_MEM_LAKE"][:-1]) > int(small["TB_MEM_LAKE"][:-1])  # more RAM: the services grow
    assert big["TB_MEM_LLM"] == f"{int(var['TB_MEM_LLM'] * 1024)}m"  # the models keep their default
    # the proportions are the compose files' own: the lake has twice the database's share on both machines
    assert int(big["TB_MEM_LAKE"][:-1]) == pytest.approx(2 * int(big["TB_MEM_DB"][:-1]), abs=2)
    stub, _ = bp.memory_caps(32, "stub")
    assert "TB_MEM_LLM" not in stub and "TB_MEM_VERIFIER" not in stub
    assert bp.memory_caps(128, "gb10") == ({}, [])  # the Spark: its profile is its caps
    with pytest.raises(bp.PlanError, match="needs at least"):
        bp.memory_caps(32, "rtxpro6000")


def test_the_kek_follows_the_tpm_and_the_firewall_the_boxs_network() -> None:
    with_tpm = bp.plan(_answers(), _hw()).files["site/hardening.conf"]
    without = bp.plan(_answers(), _hw(tpm=False))
    assert "KEK_BACKEND=tpm" in with_tpm and 'TANG_URLS=""' in with_tpm and "SSH=off" in with_tpm
    assert 'CLINIC_RANGES="192.0.2.0/24"' in with_tpm
    assert "KEK_BACKEND=passphrase" in without.files["site/hardening.conf"]
    assert any("passphrase" in w for w in without.warnings)


@pytest.mark.parametrize("kind", list(SourceKind))
def test_every_data_source_kind_builds(kind: SourceKind, tmp_path: Path) -> None:
    extra = {"ssmix2_root": "/mnt/ssmix2"} if kind is SourceKind.SSMIX2 else {}  # 10K-1: its one question
    settings, _, _ = _build(bp.plan(_answers(source=kind.value, **extra), _hw()), tmp_path)
    want = {SourceKind.RESEARCH_DB: "cgrd_sql", SourceKind.OWN_DB: "cgrd_sql", SourceKind.SSMIX2: "ssmix2"}.get(
        kind, "csv"
    )
    assert settings["data_source"]["type"] == want and settings["data_source"]["mapping"] == bp.BOX_MAPPING


@pytest.mark.parametrize(
    ("backup", "targets"),
    [({"kind": "share", "share": r"\\nas1\trialbox"}, bp.SHARE_MOUNT), ({"kind": "later"}, None)],
)
def test_backup_destinations(backup: dict[str, str], targets: str | None, tmp_path: Path) -> None:
    p = bp.plan(_answers(backup=backup), _hw())
    assert p.env_extra.get("TB_BACKUP_TARGETS") == targets and p.env_extra["TB_BACKUP_MAILTO"] == "owner@hospa.test"
    _build(p, tmp_path)


def test_the_answers_schema_refuses_what_it_cannot_use() -> None:
    a, problems = parse({**OWNER, "tz": "Mars/Base", "owner": {"full_name": "", "username": "Bad Name!",
                         "email": "nope"}, "backup": {"kind": "second_disk", "disk": "/dev/sdz"}, "source": "fax",
                         "box_name": "-x-"}, disks=("/dev/sdb",))  # fmt: skip
    assert a is None
    assert {p.field for p in problems} == {"tz", "owner_full_name", "owner_username", "owner_email", "backup_disk",
                                           "source", "box_name"}  # fmt: skip
    a, _ = parse({**OWNER, "backup": {"kind": "share", "share": "//nas/backups"}})
    assert a is not None and a.backup.kind is BackupKind.SHARE and a.hostname == "trialbox.local"


def test_owner_accounts_seam_od12() -> None:
    got = [(x.username, x.role) for x in owner_accounts(_answers())]
    assert got == [("owner", "steward"), ("owner-admin", "admin")]


def test_site_id_from_any_name() -> None:
    assert bp.site_id("Chang Gung Research") == "CHANG-GUNG-RESEARCH"
    assert re.fullmatch(r"SITE-[0-9A-F]{8}", bp.site_id("長庚紀念醫院"))
    assert bp.site_id("長庚紀念醫院") == bp.site_id("長庚紀念醫院")


def test_env_extra_takes_only_declared_settings(tmp_path: Path) -> None:
    p = bp.plan(_answers(), _hw())
    with pytest.raises(settings_wizard.WizardError, match="not a declared"):
        _build(
            bp.BoxPlan(p.profile, p.mode, {**p.wizard_answers, "env_extra": {"PATH": "/tmp"}}, {}, p.files), tmp_path
        )


def test_the_it_managed_answers_still_build_unchanged() -> None:
    """v6.1 §4.4: the rehearsal's IT-managed answers (no env_extra) give the same settings as before."""
    rehearsal = ROOT / "tools" / "rehearse_box"
    answers = yaml.safe_load((rehearsal / "site_answers.yaml").read_text(encoding="utf-8"))
    _, env, _ = settings_wizard.build(answers, [rehearsal / "mapping"])
    assert env["TB_TLS_MODE"] == "internal" and not any(k.startswith("TB_MEM_") for k in env)


def test_merge_env_keeps_the_installs_passwords(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("POSTGRES_PASSWORD=kept\nTB_TZ=UTC\nTB_DB_PW_LAKE=x\n", encoding="utf-8")
    changed = merge_env(f, {"POSTGRES_PASSWORD": "new", "TB_TZ": "Asia/Tokyo", "TB_TLS_HOSTNAME": "a.local"})
    text = f.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=kept" in text and "TB_TZ=Asia/Tokyo" in text and "TB_DB_PW_LAKE=x" in text
    assert changed == ["TB_TZ", "TB_TLS_HOSTNAME"] and "POSTGRES_PASSWORD" in KEEP
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_the_host_side_parsers() -> None:
    lsblk = json.dumps({"blockdevices": [
        {"path": "/dev/nvme0n1", "size": 2 * 1024**4, "type": "disk", "tran": "nvme",
         "children": [{"path": "/dev/nvme0n1p2", "type": "part", "mountpoint": "/"}]},
        {"path": "/dev/sdb", "size": 4 * 1024**4, "type": "disk", "tran": "sata"},
        {"path": "/dev/sr0", "size": 1, "type": "rom"},
    ]})  # fmt: skip
    assert [d.path for d in bp.parse_lsblk(lsblk)] == ["/dev/sdb"]
    ip = json.dumps([{"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16}]},
                     {"ifname": "eno1", "addr_info": [{"family": "inet", "local": "192.0.2.40", "prefixlen": 24}]}])  # fmt: skip
    assert bp.parse_ip(ip) == "192.0.2.0/24"
    assert bp.parse_lsblk("not json") == () and bp.parse_ip("") == ""


def test_the_command_line_plans_and_makes_a_code(tmp_path: Path, capsys: Any) -> None:
    hw = tmp_path / "hw.json"
    hw.write_text(json.dumps(_hw().to_json()), encoding="utf-8")
    deploy = tmp_path / "deploy"
    for f in ("docker-compose.yml", "docker-compose.identity.yml", "docker-compose.rtxpro6000.yml", "gpu_profile.sh"):
        (deploy / f).parent.mkdir(parents=True, exist_ok=True)
        (deploy / f).write_text((ROOT / "deploy" / f).read_text(encoding="utf-8"), encoding="utf-8")
    out = deploy / "site" / "box" / "answers.json"
    assert main(["plan", "--hardware", str(hw), "--provisional", "--deploy", str(deploy), "--out", str(out)]) == 0
    assert capsys.readouterr().out.strip().endswith("install-args: --mode gpu --gpu rtxpro6000")
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["tls_hostname"] == "box1.local" and got["tz"] == "Asia/Tokyo"
    assert (deploy / "site" / "hardening.conf").is_file() and (deploy / "site" / bp.BOX_MAPPING).is_file()
    assert main(["code", "--firstrun", str(tmp_path / "fr")]) == 0
    assert re.fullmatch(r"([a-z2-9]{4}-){3}[a-z2-9]{4}", capsys.readouterr().out.strip())
    bad = tmp_path / "owner.json"
    bad.write_text(json.dumps({**OWNER, "tz": "nowhere"}), encoding="utf-8")
    assert main(["plan", "--hardware", str(hw), "--owner", str(bad), "--deploy", str(deploy), "--out", str(out)]) == 1


def test_the_tpm_is_the_one_seal_keys_can_seal_to_not_only_a_device_node(tmp_path: Path) -> None:
    """D-897: the plan decided "tpm" from /dev/tpm* alone, while seal_keys.sh, check_host.sh and install.sh ask
    ``systemd-creds has-tpm2`` (D-836). A node systemd-creds cannot use (a vTPM without its driver, a TPM 1.2) gave a
    hardening.conf with KEK_BACKEND=tpm and a seal step that stopped. Now both must hold."""
    assert not bp.tpm_usable(tmp_path, has_tpm2=lambda: True)  # no device node
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev/tpmrm0").touch()
    assert bp.tpm_usable(tmp_path, has_tpm2=lambda: True)
    assert not bp.tpm_usable(tmp_path, has_tpm2=lambda: False)  # a node systemd-creds cannot use
    no_tpm = bp.plan(_answers(), _hw(tpm=bp.tpm_usable(tmp_path, has_tpm2=lambda: False)))
    assert "KEK_BACKEND=passphrase" in no_tpm.files["site/hardening.conf"]
    assert any("no usable TPM" in w for w in no_tpm.warnings)


def test_has_tpm2_is_false_without_systemd_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_a: object, **_k: object) -> None:
        raise FileNotFoundError("systemd-creds")

    monkeypatch.setattr("tools.box.plan.subprocess.run", missing)
    assert bp._has_tpm2() is False
