"""10K-3 (D-1361, review 18 SO-3): the live preflight in ``doctor`` and in the terminal wizard. A fixture per failing
check shows a red line with its next action, in ja; the list is one list (``tb_common.preflight``) with en, ja and
zh-TW texts; the checks are read-only and ask the network only through the probes handed in."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest
from tb_common import audit
from tb_common import preflight as text
from tb_common.wording import check as wording

from tools import settings_wizard
from tools.trialbox import doctor
from tools.trialbox import preflight as pf

ROOT = Path(__file__).resolve().parents[2]
Usage = namedtuple("Usage", "total used free")


def _probes(**over: object) -> pf.Probes:
    """No network, no machine: every probe a fixture."""

    def refused(*_a: object) -> str:
        raise ConnectionRefusedError("refused")

    base: dict[str, object] = {
        "writable": lambda p: Path(p).exists(),
        "resolve": lambda host: ["192.0.2.10"],
        "banner": lambda host, port, t: "220 relay.hospital.test ESMTP",
        "reach": refused,
        "gpu": lambda: ("NVIDIA GeForce RTX 5090", 32607.0),
        "tpm": lambda: True,
        "disk_usage": lambda p: Usage(1000, 500, 500),
        "euid": lambda: 0,
    }
    base.update(over)
    return pf.Probes(**base)  # type: ignore[arg-type]


def _meminfo(tmp: Path, gib: int) -> Path:
    proc = tmp / "proc"
    proc.mkdir(exist_ok=True)
    (proc / "meminfo").write_text(f"MemTotal: {gib * 1024**2} kB\n", encoding="utf-8")
    return proc


@pytest.fixture
def synced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "kernel_clock_synced", lambda: True)


def _failing(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[doctor.DoctorInputs, pf.Probes]:
    """One box on which every preflight check fails, each for its own reason."""
    monkeypatch.setattr(audit, "kernel_clock_synced", lambda: False)  # clock: not NTP-synchronised
    deploy = tmp / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / "site" / "hardening.conf").write_text("KEK_BACKEND=tpm\n", encoding="utf-8")  # tpm_tang: no TPM
    (tmp / "anchor").mkdir()  # audit_share: on the box's own disk
    (tmp / "feed").mkdir()  # feed: empty
    env = {
        "TB_ENV": "PRODUCTION",
        "TB_TLS_HOSTNAME": "trialbox.hospital.test",  # name_cert: does not resolve
        "TB_BACKUP_TARGETS": str(tmp / "no-such-share"),  # backup_share: not mounted
        "TB_AUDIT_ANCHOR_TARGETS": str(tmp / "anchor"),
        "TB_SOURCE_DIR": str(tmp / "feed"),
        "SMTP_HOST": "relay.hospital.test",  # mail_relay: refused
        "TB_PROFILE": "P-5090",  # gpu_tier: another card
    }

    def no_name(host: str) -> list[str]:
        raise OSError("Name or service not known")

    def refused(*_a: object) -> str:
        raise ConnectionRefusedError("refused")

    probes = _probes(
        resolve=no_name, banner=refused, tpm=lambda: False, gpu=lambda: ("NVIDIA RTX A2000", 6138.0),
        disk_usage=lambda p: Usage(1000, 950, 50),
    )  # fmt: skip
    return doctor.DoctorInputs(env=env, deploy=deploy, proc=_meminfo(tmp, 128)), probes


def test_the_list_is_one_list_with_three_languages() -> None:
    assert tuple(pf.CHECKS) == text.IDS
    assert set(text.IDS) >= {"name_cert", "clock", "backup_share", "audit_share", "feed", "mail_relay", "disk",
                             "tpm_tang", "gpu_tier"}  # fmt: skip  # the card's nine
    for item in text.ITEMS:
        assert item.group in text.GROUPS
        for lg in text.LANGS:
            assert item.label[lg].strip() and item.action[lg].strip(), (item.id, lg)
            assert not wording(item.label[lg]) and not wording(item.action[lg]), (item.id, lg)
        assert item.action["ja"] != item.action["en"] != item.action["zh-TW"]


@pytest.mark.parametrize("cid", text.IDS)
def test_a_fixture_per_failing_check_shows_a_red_line_with_its_action_in_ja(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cid: str
) -> None:
    inp, probes = _failing(tmp_path, monkeypatch)
    checks = {c.name: c for c in pf.run(inp, probes)}
    assert checks[cid].status == "FAIL", checks[cid]
    out = pf.render(list(checks.values()), "ja", color=True).splitlines()
    i = next(n for n, line in enumerate(out) if f"FAIL  {cid} " in line)
    assert out[i].startswith(pf.RED) and out[i].endswith(pf.RESET)  # red
    assert text.label(cid, "ja") in out[i]
    assert out[i + 1].strip() == f"-> {text.action(cid, 'ja')}"  # the next action, under the line, in Japanese
    assert "もう一度確認してください" in out[i + 1]


def test_each_check_passes_on_a_box_that_is_ready(
    tmp_path: Path, synced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    share = tmp_path / "share"
    share.mkdir()
    (share / ".trialbox-offbox").write_text("", encoding="utf-8")
    anchor = tmp_path / "anchor"
    (anchor / "heads").mkdir(parents=True)
    head = anchor / "heads" / "20261118T020000Z-000000000042.json"
    head.write_text("{}", encoding="utf-8")
    feed = tmp_path / "feed"
    (feed / "sub").mkdir(parents=True)
    for n in ("a.csv", "b.csv", "sub/c.csv"):
        (feed / n).write_text("x\n", encoding="utf-8")
    devs = iter(range(100, 200))
    monkeypatch.setattr(pf, "_dev", lambda p: next(devs))  # the anchor folder on another device than the box
    env = {
        "TB_ENV": "PRODUCTION", "TB_TLS_HOSTNAME": "trialbox.hospital.test", "TB_TLS_MODE": "internal",
        "TB_BACKUP_TARGETS": str(share), "TB_BACKUP_OFFBOX": str(share), "TB_AUDIT_ANCHOR_TARGETS": str(anchor),
        "TB_SOURCE_DIR": str(feed), "SMTP_HOST": "relay.hospital.test", "SMTP_PORT": "25", "TB_PROFILE": "P-5090",
    }  # fmt: skip
    inp = doctor.DoctorInputs(env=env, deploy=deploy, proc=_meminfo(tmp_path, 128))
    # the box's root cannot write the signed head (a root-squashed or write-once share)
    checks = pf.run(inp, _probes(writable=lambda p: Path(p) != head))
    got = {c.name: (c.status, c.detail) for c in checks}
    assert {k: s for k, (s, _) in got.items()} == dict.fromkeys(text.IDS, "PASS"), got
    assert "3 file(s) readable" in got["feed"][1]
    assert "trialbox.hospital.test is 192.0.2.10" in got["name_cert"][1]
    out = pf.render(checks, "ja")
    assert "->" not in out and out.endswith("事前確認はすべて合格です")


def test_the_audit_share_fails_where_root_can_change_a_signed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor = tmp_path / "anchor"
    (anchor / "heads").mkdir(parents=True)
    (anchor / "heads" / "h.json").write_text("{}", encoding="utf-8")
    devs = iter(range(100, 200))
    monkeypatch.setattr(pf, "_dev", lambda p: next(devs))
    inp = doctor.DoctorInputs(env={"TB_AUDIT_ANCHOR_TARGETS": str(anchor)}, deploy=tmp_path)
    c = pf.check_audit_share(inp, _probes())
    assert c.status == "FAIL" and "root can change a signed head" in c.detail
    c = pf.check_audit_share(inp, _probes(euid=lambda: 1000))
    assert c.status == "WARN" and "run as root" in c.detail  # not judged by another user: said so
    (anchor / "heads" / "h.json").unlink()
    c = pf.check_audit_share(inp, _probes())
    assert c.status == "WARN" and "no signed head yet" in c.detail


def test_a_check_that_raises_is_a_red_line(tmp_path: Path, synced: None) -> None:
    def boom() -> tuple[str, float]:
        raise RuntimeError("nvidia-smi crashed")

    inp = doctor.DoctorInputs(env={"TB_PROFILE": "P-5090"}, deploy=tmp_path)
    c = {c.name: c for c in pf.run(inp, _probes(gpu=boom))}["gpu_tier"]
    assert c.status == "FAIL" and "RuntimeError" in c.detail


def test_the_gpu_is_judged_against_the_tier_record(tmp_path: Path) -> None:
    inp = doctor.DoctorInputs(env={"TB_PROFILE": "P-5090"}, deploy=tmp_path, proc=_meminfo(tmp_path, 32))
    c = pf.check_gpu_tier(inp, _probes(gpu=lambda: ("NVIDIA GeForce RTX 5090", 24000.0)))
    assert c.status == "FAIL" and "24000 MiB" in c.detail and "the host has 32 GiB" in c.detail
    stub = doctor.DoctorInputs(env={"TB_PROFILE": "P-GB10", "TB_LLM_MODE": "stub"}, deploy=tmp_path)
    assert pf.check_gpu_tier(stub, _probes(gpu=lambda: None)).status == "PASS"


def test_json_and_the_first_run_file_carry_the_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inp, probes = _failing(tmp_path, monkeypatch)
    checks = pf.run(inp, probes)
    rows = pf.as_json(checks)
    disk = next(r for r in rows if r["name"] == "disk")
    assert disk["group"] == "hardware" and disk["action"]["ja"] == text.action("disk", "ja")
    assert set(disk["label"]) == set(text.LANGS)
    out = pf.write(checks, tmp_path / "fr" / text.FILE)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["format"] == text.FORMAT and [ln["id"] for ln in doc["lines"]] == list(text.IDS)
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    shown = text.page_lines(doc, "ja")
    assert all(ln["status"] == "FAIL" and ln["action"] == text.action(ln["id"], "ja") for ln in shown)


def test_doctor_preflight_prints_red_lines_with_their_action_in_ja(tmp_path: Path) -> None:
    """The command line, run once without PYTHONUNBUFFERED: an empty box (no name, no shares, nothing chosen)."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_LLM_MODE=stub\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_") and k != "PYTHONUNBUFFERED"}
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))
    out = tmp_path / "fr" / text.FILE
    r = subprocess.run(
        [sys.executable, "-m", "tools.trialbox", "doctor", "--preflight", "--lang", "ja",
         "--env-file", str(deploy / ".env"), "--out", str(out)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert r.returncode == 1, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    for cid in ("name_cert", "backup_share", "audit_share"):  # red here without any network or hardware
        i = next(n for n, line in enumerate(lines) if line.startswith(f"FAIL  {cid} "))
        assert text.label(cid, "ja") in lines[i] and lines[i + 1].strip() == f"-> {text.action(cid, 'ja')}"
    assert "件の確認が不合格です" in lines[-1]
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == text.FORMAT


def test_the_terminal_wizard_prints_the_preflight_after_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inp, probes = _failing(tmp_path, monkeypatch)
    seen: dict[str, object] = {}
    real_run = pf.run

    def run(i: doctor.DoctorInputs, p: pf.Probes | None = None) -> list[doctor.Check]:
        seen["settings"] = dict(i.settings)
        return real_run(inp, probes)

    monkeypatch.setattr(pf, "run", run)
    env_file = tmp_path / "w.env"
    env_file.write_text("TB_ENV=VALIDATION\n", encoding="utf-8")
    settings = tmp_path / "settings.yaml"
    settings.write_text("site: {id: x}\n", encoding="utf-8")
    assert settings_wizard.preflight(settings, env_file, "ja") == 1
    out = capsys.readouterr().out
    assert seen["settings"] == {"site": {"id": "x"}}  # the files just written are what is checked
    assert f"-> {text.action('feed', 'ja')}" in out and text.label("feed", "ja") in out


def test_a_local_name_not_yet_answered_is_amber_not_red(tmp_path: Path) -> None:
    def no_name(host: str) -> list[str]:
        raise OSError("Name or service not known")

    inp = doctor.DoctorInputs(env={"TB_TLS_HOSTNAME": "box1.local"}, deploy=tmp_path)
    c = pf.check_name_cert(inp, _probes(resolve=no_name))
    assert c.status == "WARN" and "once the set-up is applied" in c.detail
