"""10K-3 (D-1361, review 18 SO-3): the live preflight in ``doctor`` and in the terminal wizard.

A box that is ready is all green; then one fixture per failure reason turns exactly one line red (or amber where the
box cannot tell), and the red line shows its next action in ja under it. The list is one list (``tb_common.preflight``)
with en, ja and zh-TW texts; the checks are read-only and ask the network and the machine only through the probes
handed in; a check that hangs is a red line with the time-out's action, never green."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
import subprocess
import sys
import time
from collections import namedtuple
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit
from tb_common import preflight as text
from tb_common.wording import check as wording

from tools import settings_wizard, text_keys
from tools.trialbox import doctor
from tools.trialbox import preflight as pf

ROOT = Path(__file__).resolve().parents[2]
Usage = namedtuple("Usage", "total used free")
HOST = "trialbox.hospital.test"


def _probes(**over: object) -> pf.Probes:
    """No network, no machine: every probe a fixture of a box that is ready."""

    base: dict[str, object] = {
        "writable": lambda p: Path(p).exists(),
        "resolve": lambda host: ["192.0.2.10"],
        "own_addrs": lambda: {"192.0.2.10", "127.0.0.1"},
        "banner": lambda host, port, t: "220 relay.hospital.test ESMTP",
        "reach": lambda host, port, t: "open",
        "gpus": lambda: [("NVIDIA GeForce RTX 5090", 32607.0)],
        "tpm": lambda: True,
        "disk_usage": lambda p: Usage(1000, 500, 500),
        "docker_root": lambda: None,
        "euid": lambda: 0,
        "offbox": lambda p: True,
    }
    base.update(over)
    return pf.Probes(**base)  # type: ignore[arg-type]


def _meminfo(tmp: Path, gib: int) -> Path:
    proc = tmp / "proc"
    proc.mkdir(exist_ok=True)
    (proc / "meminfo").write_text(f"MemTotal: {gib * 1024**2} kB\n", encoding="utf-8")
    return proc


def _cert(tmp: Path, host: str, days: tuple[int, int], *, self_signed: bool = False) -> dict[str, str]:
    """A hospital certificate for ``host`` valid from ``days[0]`` to ``days[1]`` days from now; signed by a stand-in
    hospital CA unless ``self_signed``. Returns the TLS settings that name it."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = dt.datetime.now(dt.UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    ca_key = key if self_signed else ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    issuer = subject if self_signed else x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Hospital CA (synthetic)")])
    cert = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key())
        .serial_number(7).not_valid_before(now + dt.timedelta(days=days[0]))
        .not_valid_after(now + dt.timedelta(days=days[1]))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False).sign(ca_key, hashes.SHA256())
    )  # fmt: skip
    folder = tmp / f"tls-{host}-{days[0]}-{days[1]}-{self_signed}"
    folder.mkdir()
    (folder / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()))  # fmt: skip
    return {"TB_TLS_MODE": "hospital", "TB_TLS_CERT_FILE": str(folder / "c.pem"),
            "TB_TLS_KEY_FILE": str(folder / "k.pem")}  # fmt: skip


@dataclass
class Box:
    tmp: Path
    deploy: Path
    env: dict[str, str]
    probes: pf.Probes
    paths: dict[str, Path] = field(default_factory=dict)

    def inp(self) -> doctor.DoctorInputs:
        return doctor.DoctorInputs(env=self.env, deploy=self.deploy, proc=self.tmp / "proc")

    def run(self) -> dict[str, doctor.Check]:
        return {c.name: c for c in pf.run(self.inp(), self.probes, per_check_s=10)}

    def probe(self, **over: object) -> Box:
        self.probes = replace(self.probes, **over)  # type: ignore[arg-type]
        return self


def _ready(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    """A box on which every check is green."""
    monkeypatch.setattr(audit, "kernel_clock_synced", lambda: True)
    deploy = tmp / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / "site" / "hardening.conf").write_text(
        "KEK_BACKEND=tpm\nTANG_URLS=http://tang.hospital.test:7500\n", encoding="utf-8"
    )
    share = tmp / "share"
    share.mkdir()
    anchor = tmp / "anchor"
    heads = anchor / "heads"
    heads.mkdir(parents=True)
    head = heads / "20261118T020000Z-000000000042.json"
    head.write_text("{}", encoding="utf-8")
    head.chmod(0o444)
    heads.chmod(0o1777)  # sticky: no one removes another's file
    if os.geteuid() == 0:  # the heads belong to the share's writer, not the box's root
        os.chown(head, 4242, 4242)
        os.chown(heads, 4242, 4242)
    feed = tmp / "feed"
    (feed / "sub").mkdir(parents=True)
    for n in ("a.csv", "b.csv", "sub/c.csv"):
        (feed / n).write_text("x\n", encoding="utf-8")
    for d in (feed, feed / "sub"):
        d.chmod(0o755)
    docker = tmp / "docker"
    docker.mkdir()
    _meminfo(tmp, 128)
    env = {
        "TB_ENV": "PRODUCTION", "TB_TLS_HOSTNAME": HOST, "TB_TLS_MODE": "internal",
        "TB_BACKUP_TARGETS": str(share), "TB_AUDIT_ANCHOR_TARGETS": str(anchor), "TB_SOURCE_DIR": str(feed),
        "SMTP_HOST": "relay.hospital.test", "SMTP_PORT": "25", "TB_PROFILE": "P-5090",
    }  # fmt: skip
    probes = _probes(writable=lambda p: Path(p).exists() and Path(p) != head, docker_root=lambda: docker)
    paths = {"share": share, "anchor": anchor, "heads": heads, "head": head, "feed": feed, "docker": docker}
    return Box(tmp, deploy, env, probes, paths)


def test_a_box_that_is_ready_is_all_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    got = _ready(tmp_path, monkeypatch).run()
    assert {k: c.status for k, c in got.items()} == dict.fromkeys(text.IDS, "PASS"), got
    assert "3 file(s) readable" in got["feed"].detail
    assert f"{HOST} is 192.0.2.10" in got["name_cert"].detail
    assert "sealed to the TPM" in got["tpm_tang"].detail and "TPM and Tang" in got["tpm_tang"].detail
    out = pf.render(list(got.values()), "ja")
    assert "->" not in out and out.endswith("事前確認はすべて合格です")


def _no_name(host: str) -> list[str]:
    raise OSError("Name or service not known")


def _refused(*_a: object) -> str:
    raise ConnectionRefusedError("refused")


def _cert_env(days: tuple[int, int], host: str = HOST) -> Callable[[Box], object]:
    return lambda b: b.env.update(_cert(b.tmp, host, days))


def _set(**env: str) -> Callable[[Box], object]:
    return lambda b: b.env.update(env)


def _drop(*names: str) -> Callable[[Box], object]:
    return lambda b: [b.env.pop(n, None) for n in names]


def _probe(**over: object) -> Callable[[Box], object]:
    return lambda b: b.probe(**over)


def _conf(body: str) -> Callable[[Box], object]:
    return lambda b: (b.deploy / "site" / "hardening.conf").write_text(body, encoding="utf-8")


def _closed(b: Box, name: str) -> None:
    """The box may not write to one folder (and never to the signed head)."""
    shut = {b.paths[name], b.paths["head"]}
    b.probe(writable=lambda p: Path(p).exists() and Path(p) not in shut)


def _on_box(b: Box, name: str) -> None:
    """One folder on the box's own disks, as the mount table says of a temporary folder."""
    b.probe(offbox=lambda p: Path(p) != b.paths[name] and not pf._offbox(b.paths[name], b.inp()))


def test_a_folder_of_the_box_is_not_off_the_box(tmp_path: Path) -> None:
    assert pf._offbox(tmp_path, doctor.DoctorInputs(deploy=tmp_path)) is False  # backup_schedule.target_kind


def _feed_file_mode(b: Box) -> None:
    (b.paths["feed"] / "a.csv").chmod(0)


def _feed_link(b: Box) -> None:
    (b.paths["feed"] / "shadow.csv").symlink_to("/etc/shadow")


def _feed_dir_closed(b: Box) -> None:
    (b.paths["feed"] / "sub").chmod(0o700)


def _feed_empty(b: Box) -> None:
    for f in (b.paths["feed"] / "a.csv", b.paths["feed"] / "b.csv", b.paths["feed"] / "sub" / "c.csv"):
        f.unlink()


def _applied(b: Box) -> None:
    (b.deploy / "site" / "box").mkdir(parents=True)
    (b.deploy / "site" / "box" / "applied").write_text("2026-11-19T01:00:00Z\n", encoding="utf-8")
    b.env["TB_TLS_HOSTNAME"] = "box1.local"
    b.probe(resolve=_no_name)


def _low(where: str) -> Callable[[Box], object]:
    def go(b: Box) -> None:
        low = b.deploy if where == "deploy" else b.paths["docker"]
        b.probe(disk_usage=lambda p: Usage(1000, 950, 50) if Path(p) == low else Usage(1000, 500, 500))

    return go


def _clock_skew(b: Box) -> None:
    b.env["TB_NTP_SERVER"] = "ntp.hospital.test"


#: (reason, check id, how the ready box is changed, words the red line's detail must hold)
REASONS: list[tuple[str, str, Callable[[Box], object], str]] = [
    ("no name", "name_cert", _drop("TB_TLS_HOSTNAME"), "no TB_TLS_HOSTNAME"),
    ("name does not resolve", "name_cert", _probe(resolve=_no_name), "does not resolve here"),
    ("name is another machine", "name_cert", _probe(resolve=lambda h: ["203.0.113.250"]), "not an address of this box"),
    (".local after the apply", "name_cert", _applied, "the set-up was applied"),
    ("certificate expired", "name_cert", _cert_env((-10, -1)), "not valid now"),
    ("certificate not yet valid", "name_cert", _cert_env((1, 300)), "not valid now"),
    ("certificate names another host", "name_cert", _cert_env((-1, 300), "other.hospital.test"), "does not name"),
    (
        "clock not synchronised",
        "clock",
        lambda b: setattr(audit, "kernel_clock_synced", lambda: False),
        "not NTP-synchronised",
    ),
    ("clock skew", "clock", _clock_skew, "+120.0 s"),
    ("no backup target", "backup_share", _drop("TB_BACKUP_TARGETS"), "no backup target"),
    ("backup share not mounted", "backup_share", lambda b: b.paths["share"].rmdir(), "not mounted"),
    ("backup share not writable", "backup_share", lambda b: _closed(b, "share"), "not writable by the box"),
    ("backup only on the box", "backup_share", lambda b: _on_box(b, "share"), "on the box's own disk"),
    ("no audit share", "audit_share", _drop("TB_AUDIT_ANCHOR_TARGETS"), "no audit share"),
    ("audit share not mounted", "audit_share", _set(TB_AUDIT_ANCHOR_TARGETS="/nonexistent/anchor"), "not mounted"),
    ("audit share on the box", "audit_share", lambda b: _on_box(b, "anchor"), "on the box's own disks"),
    ("audit share not writable", "audit_share", lambda b: _closed(b, "heads"), "cannot add the nightly"),
    ("root can change a head", "audit_share", _probe(writable=lambda p: Path(p).exists()), "can change a signed head"),
    ("feed folder missing", "feed", _set(TB_SOURCE_DIR="/nonexistent/feed"), "is not there"),
    ("feed folder empty", "feed", _feed_empty, "holds no file"),
    ("feed file mode 000", "feed", _feed_file_mode, "1 not readable"),
    ("feed link to a host file", "feed", _feed_link, "1 not readable"),
    ("feed folder closed", "feed", _feed_dir_closed, "1 not readable"),
    ("mail relay refuses", "mail_relay", _probe(banner=_refused), "did not answer"),
    ("mail relay is not mail", "mail_relay", _probe(banner=lambda h, p, t: "SSH-2.0-OpenSSH"), "not a mail greeting"),
    ("mail port not a port", "mail_relay", _set(SMTP_PORT="smtp"), "is not a port"),
    ("deploy disk full", "disk", _low("deploy"), "below 10%"),
    ("docker disk full", "disk", _low("docker"), "below 10%"),
    ("TPM seal without a TPM", "tpm_tang", _probe(tpm=lambda: False), "no usable TPM 2.0"),
    (
        "unknown key back end",
        "tpm_tang",
        _conf("KEK_BACKEND=tang\nTANG_URLS=http://tang.hospital.test:7500\n"),
        "not one the box seals with",
    ),
    ("Tang down", "tpm_tang", _probe(reach=_refused), "no Tang server answers"),
    (
        "Tang without a TPM",
        "tpm_tang",
        lambda b: (_conf("KEK_BACKEND=passphrase\nTANG_URLS=http://t:1\n")(b), b.probe(tpm=lambda: False)),
        "needs the TPM too",
    ),
    ("wrong card", "gpu_tier", _probe(gpus=lambda: [("NVIDIA RTX A2000", 32607.0)]), "the record names 5090"),
    ("wrong card memory", "gpu_tier", _probe(gpus=lambda: [("NVIDIA GeForce RTX 5090", 24000.0)]), "24000 MiB"),
    ("host memory too small", "gpu_tier", lambda b: _meminfo(b.tmp, 32), "the host has 32 GiB"),
    ("no card answers", "gpu_tier", _probe(gpus=lambda: []), "no graphics card answers"),
    ("tier record unreadable", "gpu_tier", lambda b: b.probe(tiers_dir=b.tmp / "no-tiers"), "cannot be read"),
]


@pytest.mark.parametrize(("reason", "cid", "change", "words"), REASONS, ids=[r[0] for r in REASONS])
def test_a_fixture_per_failure_reason_shows_a_red_line_with_its_action_in_ja(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, cid: str, change: Callable[[Box], object], words: str
) -> None:
    b = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(audit, "sntp_offset", lambda server, timeout=3.0: 120.0)
    change(b)
    got = b.run()
    assert got[cid].status == "FAIL" and words in got[cid].detail, got[cid]
    assert [k for k, c in got.items() if c.status != "PASS"] == [cid], {k: c for k, c in got.items()}
    out = pf.render(list(got.values()), "ja", color=True).splitlines()
    i = next(n for n, line in enumerate(out) if f"FAIL  {cid} " in line)
    assert out[i].startswith(pf.RED) and out[i].endswith(pf.RESET)  # red
    assert text.label(cid, "ja") in out[i]
    assert out[i + 1].strip() == f"-> {text.action(cid, 'ja')}"  # the next action, under the line, in Japanese
    assert "もう一度確認してください" in out[i + 1]


AMBER: list[tuple[str, str, Callable[[Box], object], str]] = [
    (
        ".local before the apply",
        "name_cert",
        lambda b: (b.env.update(TB_TLS_HOSTNAME="box1.local"), b.probe(resolve=_no_name)),
        "once the set-up is applied",
    ),
    ("own addresses unread", "name_cert", _probe(own_addrs=lambda: None), "could not be read"),
    (
        "certificate signed itself",
        "name_cert",
        lambda b: b.env.update(_cert(b.tmp, HOST, (-1, 300), self_signed=True)),
        "signed itself",
    ),
    ("passphrase keys", "tpm_tang", _conf("KEK_BACKEND=passphrase\n"), "opened only by people"),
    ("host memory unread", "gpu_tier", lambda b: (b.tmp / "proc" / "meminfo").unlink(), "could not be read"),
    (
        "a second card of another kind",
        "gpu_tier",
        _probe(gpus=lambda: [("NVIDIA GeForce RTX 5090", 32607.0), ("NVIDIA T400", 2048.0)]),
        "another card",
    ),
    ("root may remove a head", "audit_share", lambda b: b.paths["heads"].chmod(0o777), "remove and replace"),
    ("no mail relay", "mail_relay", _drop("SMTP_HOST"), "sends no mail"),
]


@pytest.mark.parametrize(("reason", "cid", "change", "words"), AMBER, ids=[r[0] for r in AMBER])
def test_what_the_box_cannot_tell_is_amber_with_its_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, cid: str, change: Callable[[Box], object], words: str
) -> None:
    b = _ready(tmp_path, monkeypatch)
    change(b)
    got = b.run()
    assert got[cid].status == "WARN" and words in got[cid].detail, got[cid]
    out = pf.render(list(got.values()), "ja").splitlines()
    i = next(n for n, line in enumerate(out) if line.startswith(f"WARN  {cid} "))
    assert out[i + 1].strip() == f"-> {text.action(cid, 'ja')}"


def test_root_owning_the_heads_is_amber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = _ready(tmp_path, monkeypatch)
    owner = b.paths["head"].lstat().st_uid
    b.probe(euid=lambda: 0)
    if owner != 0:  # a test run as another user: the head's owner plays the box's root
        b.probe(euid=lambda: owner, writable=lambda p: Path(p).exists() and Path(p) != b.paths["head"])
        c = pf.check_audit_share(b.inp(), b.probes)
        assert c.status == "WARN" and "run as root" in c.detail  # another user than root: not judged, said so
        return
    os.chown(b.paths["head"], 0, 0)
    c = pf.check_audit_share(b.inp(), b.probes)
    assert c.status == "WARN" and "owns the signed heads" in c.detail


def test_a_check_that_hangs_is_red_with_the_time_out_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = _ready(tmp_path, monkeypatch)

    def hangs(host: str) -> list[str]:
        time.sleep(5)
        return ["192.0.2.10"]

    b.probe(resolve=hangs)
    t0 = time.monotonic()
    got = {c.name: c for c in pf.run(b.inp(), b.probes, per_check_s=0.3)}
    assert time.monotonic() - t0 < 4
    c = got["name_cert"]
    assert c.status == "FAIL" and c.detail.startswith(text.TIMEOUT_PREFIX)
    assert text.action("name_cert", "ja", c.detail) == text.TIMED_OUT["ja"] + text.AGAIN["ja"]
    out = pf.render([c], "ja")
    assert text.TIMED_OUT["ja"] in out
    # the run's own budget: what is left when it is used up is red too
    late = pf.run(b.inp(), b.probes, per_check_s=0.3, total_s=0.2)
    assert all(x.status == "FAIL" and x.detail.startswith(text.TIMEOUT_PREFIX) for x in late[1:])


def test_the_feed_walk_stops_in_time_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = _ready(tmp_path, monkeypatch)
    b.probe(feed_time_s=-1.0)
    c = pf.check_feed(b.inp(), b.probes)
    assert c.status == "WARN" and "counting stopped after" in c.detail and "at least" in c.detail


def test_mail_on_port_465_is_asked_over_tls() -> None:
    seen: list[int] = []

    def banner(host: str, port: int, t: float) -> str:
        seen.append(port)
        return "220 relay ESMTP"

    inp = doctor.DoctorInputs(env={"SMTP_HOST": "relay.hospital.test", "SMTP_PORT": "465"})
    c = pf.check_mail_relay(inp, _probes(banner=banner))
    assert c.status == "PASS" and "(TLS)" in c.detail and seen == [465]


def test_the_list_is_one_list_with_three_languages() -> None:
    assert tuple(pf.CHECKS) == text.IDS
    assert set(text.IDS) == {"name_cert", "clock", "backup_share", "audit_share", "feed", "mail_relay", "disk",
                             "tpm_tang", "gpu_tier"}  # fmt: skip  # the card's nine
    for item in text.ITEMS:
        assert item.group in text.GROUPS
        for lg in text.LANGS:
            assert item.label[lg].strip() and item.action[lg].strip(), (item.id, lg)
            assert not wording(item.label[lg]) and not wording(item.action[lg]), (item.id, lg)
    assert text_keys.preflight_problems() == []


def test_text_keys_sees_a_missing_preflight_text(monkeypatch: pytest.MonkeyPatch) -> None:
    item = text.BY_ID["disk"]
    monkeypatch.setattr(text, "ITEMS", (*text.ITEMS[:-1], replace(item, action={**item.action, "zh-TW": ""})))
    monkeypatch.setitem(text.TIMED_OUT, "ja", text.TIMED_OUT["en"])
    got = text_keys.preflight_problems()
    assert any("disk.action has no zh-TW" in p for p in got) and any("timed_out ja is the English" in p for p in got)


def test_the_page_lines_fail_closed() -> None:
    doc = {"format": text.FORMAT, "at": "x", "lines": [
        {"id": "no_such_check", "status": "PASS", "detail": "?"}, {"id": "disk", "status": "maybe", "detail": ""}, 5,
    ]}  # fmt: skip
    shown = text.page_lines(doc, "ja")
    assert [ln["status"] for ln in shown] == ["FAIL", "FAIL"]
    assert shown[0]["action"] == text.UNKNOWN["ja"] and shown[1]["action"] == text.action("disk", "ja")
    assert text.page_lines({"format": text.FORMAT, "lines": "abc"}, "ja") == []


def test_json_and_the_first_run_file_carry_the_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = _ready(tmp_path, monkeypatch)
    b.probe(disk_usage=lambda p: Usage(1000, 950, 50))
    checks = pf.run(b.inp(), b.probes)
    rows = pf.as_json(checks)
    disk = next(r for r in rows if r["name"] == "disk")
    assert disk["group"] == "hardware" and disk["action"]["ja"] == text.action("disk", "ja")
    assert set(disk["label"]) == set(text.LANGS)
    out = pf.write(checks, tmp_path / "fr" / text.FILE)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["format"] == text.FORMAT and [ln["id"] for ln in doc["lines"]] == list(text.IDS)
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    shown = {ln["id"]: ln for ln in text.page_lines(doc, "ja")}
    assert shown["disk"]["status"] == "FAIL" and shown["disk"]["action"] == text.action("disk", "ja")


def _cli(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_") and k != "PYTHONUNBUFFERED"}
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))
    return subprocess.run([sys.executable, "-m", "tools.trialbox", "doctor", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180, check=False)  # fmt: skip


def test_doctor_preflight_prints_red_lines_with_their_action_in_ja(tmp_path: Path) -> None:
    """The command line, run once without PYTHONUNBUFFERED: an empty box (no name, no shares, nothing chosen)."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_LLM_MODE=stub\n", encoding="utf-8")
    out = tmp_path / "fr" / text.FILE
    r = _cli(tmp_path, "--preflight", "--lang", "ja", "--env-file", str(deploy / ".env"), "--out", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    for cid in ("name_cert", "backup_share", "audit_share"):  # red here without any network or hardware
        i = next(n for n, line in enumerate(lines) if line.startswith(f"FAIL  {cid} "))
        assert text.label(cid, "ja") in lines[i] and lines[i + 1].strip() == f"-> {text.action(cid, 'ja')}"
    assert "件の確認が不合格です" in lines[-1]
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == text.FORMAT


def test_lang_and_out_without_preflight_are_refused(tmp_path: Path) -> None:
    for args in (["--lang", "ja"], ["--out", str(tmp_path / "x.json")]):
        r = _cli(tmp_path, *args)
        assert r.returncode == 2 and "go with --preflight" in r.stderr, r.stderr
    assert not (tmp_path / "x.json").exists()


def test_the_terminal_wizard_prints_the_preflight_after_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    b = _ready(tmp_path, monkeypatch)
    b.probe(gpus=lambda: [])
    seen: dict[str, Any] = {}
    real_run = pf.run

    def run(i: doctor.DoctorInputs, p: pf.Probes | None = None) -> list[doctor.Check]:
        seen["settings"] = dict(i.settings)
        return real_run(b.inp(), b.probes)

    monkeypatch.setattr(pf, "run", run)
    env_file = tmp_path / "w.env"
    env_file.write_text("TB_ENV=VALIDATION\n", encoding="utf-8")
    settings = tmp_path / "settings.yaml"
    settings.write_text("site: {id: x}\n", encoding="utf-8")
    assert settings_wizard.preflight(settings, env_file, "ja") == 1
    out = capsys.readouterr().out
    assert seen["settings"] == {"site": {"id": "x"}}  # the files just written are what is checked
    assert f"-> {text.action('gpu_tier', 'ja')}" in out and text.label("gpu_tier", "ja") in out


def test_a_stub_box_has_no_card_to_compare(tmp_path: Path) -> None:
    stub = doctor.DoctorInputs(env={"TB_PROFILE": "P-GB10", "TB_LLM_MODE": "stub"}, deploy=tmp_path)
    assert pf.check_gpu_tier(stub, _probes(gpus=lambda: [])).status == "PASS"


def test_the_checks_write_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = _ready(tmp_path, monkeypatch)

    def tree() -> dict[str, tuple[int, int]]:
        return {str(p): (p.lstat().st_mode, p.lstat().st_mtime_ns) for p in tmp_path.rglob("*")}

    before = tree()
    pf.run(b.inp(), b.probes)
    assert tree() == before
    assert stat.S_IMODE(b.paths["head"].lstat().st_mode) == 0o444
