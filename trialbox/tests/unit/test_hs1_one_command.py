"""HS-1, the hospital's one command (``docs/plan/design/hospital-simple-install.md`` section 2.1 step 1, section 5 row 1).

The stick holds what ``tools/make_bundle.sh`` writes beside the bundle: ``install`` (``deploy/launcher.sh``), the
vendor's public key, the signed bundle, and the bootstrap with its ``.sig``. IT types ``sudo bash <stick>/install``
and nothing else. The launcher shows the key's fingerprint for comparison with the delivery sheet, checks the
bootstrap's signature itself, and runs the bootstrap's box form, which runs ``deploy/box-install.sh``.

The fake host: the release's host tree carries the real ``deploy/box-install.sh`` with the repository's code linked
in; the hardware is a fixture (``TB_BOX_HARDWARE``) and the inner install a stand-in that stops, so the run ends
after the plan. Every key is made inside the test's own temp root. No real stick, no root, no Docker.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from tools import sign_bundle

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "deploy" / "launcher.sh"
BOOT = ROOT / "deploy" / "bootstrap.sh"
PRO6000 = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"
HW = {
    "arch": "x86_64", "cpu_count": 32, "ram_gib": 128, "disk_free_gib": 1800, "tpm": True,
    "disks": [{"path": "/dev/sdb", "size_gib": 3726.0, "transport": "sata", "mounted": ""}],
    "lan": "192.0.2.0/24", "hostname": "box1", "host_tz": "Asia/Tokyo", "gpu_name": PRO6000, "gpu_mem_gib": 96.0,
}  # fmt: skip
# what box-install.sh reads beside itself (as tests/console/test_box_install_rehearsal.py copies them)
DEPLOY_FILES = ("box-install.sh", "gpu_profile.sh", "docker-compose.yml", "docker-compose.identity.yml",
                "docker-compose.rtxpro6000.yml", "docker-compose.box.yml", "systemd/trialbox-firstrun.service")  # fmt: skip
STOP_INSTALL = '#!/bin/sh\necho "inner install: $*" >> "$TB_HS1_CALLS"\necho "inner install: stopped" >&2\nexit 1\n'

pytestmark = pytest.mark.skipif(
    any(shutil.which(c) is None for c in ("openssl", "sha256sum", "tar")),
    reason="the launcher checks with openssl and sha256sum",
)


def _host_tar(path: Path) -> Path:
    """The release's host tree: the real box installer, the code linked to this checkout."""
    with tarfile.open(path, "w:") as tf:
        for name in DEPLOY_FILES:
            tf.add(ROOT / "deploy" / name, f"deploy/{name}")
        data = b'#!/usr/bin/env bash\necho "the IT form: $*"\n'
        info = tarfile.TarInfo("deploy/install.sh")
        info.size, info.mode = len(data), 0o755
        tf.addfile(info, io.BytesIO(data))
        for name in ("libs", "services", "tools", "schemas"):
            link = tarfile.TarInfo(name)
            link.type, link.linkname = tarfile.SYMTYPE, str(ROOT / name)
            tf.addfile(link)
    return path


@pytest.fixture
def stick(tmp_path: Path) -> dict[str, Path]:
    """The stick as make_bundle.sh lays it out, the vendor's private key kept off it."""
    priv, pub = sign_bundle.keygen(tmp_path / "vendor")
    usb = tmp_path / "media" / "usb"
    usb.mkdir(parents=True)
    host = _host_tar(tmp_path / "vendor" / "trialbox-host.tar")
    sign_bundle.build(priv, "1.0.0", [("host", host, "trialbox-host.tar")], usb / "trialbox-1.0.0.tar", release_seq=1)
    shutil.copy2(BOOT, usb / "trialbox-bootstrap.sh")
    sign_bundle.sign_file(priv, usb / "trialbox-bootstrap.sh")
    shutil.copy2(pub, usb / "vendor_ed25519.pub")
    shutil.copy2(LAUNCHER, usb / "install")
    (usb / "install").chmod(0o755)
    stub = tmp_path / "stubs" / "install.sh"
    stub.parent.mkdir()
    stub.write_text(STOP_INSTALL, encoding="utf-8")
    stub.chmod(0o755)
    hw = tmp_path / "hardware.json"
    hw.write_text(json.dumps(HW), encoding="utf-8")
    (tmp_path / "tmp").mkdir()
    return {"tmp": tmp_path, "usb": usb, "priv": priv, "pub": pub, "opt": tmp_path / "opt" / "trialbox",
            "stub": stub, "hw": hw, "calls": tmp_path / "calls.log"}  # fmt: skip


def _env(s: dict[str, Path]) -> dict[str, str]:
    return {
        **os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}",
        "TMPDIR": str(s["tmp"] / "tmp"), "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(s["opt"]),
        "TB_BOX_NO_ROOT": "1", "TB_BOX_HARDWARE": str(s["hw"]), "TB_BOX_INSTALL": str(s["stub"]),
        "TB_BOX_PY": sys.executable, "TB_FIRSTRUN_HOST_DIR": str(s["tmp"] / "firstrun"),
        "TB_ISSUE_DIR": str(s["tmp"] / "issue.d"), "TB_SYSTEMD": "0", "TB_BOX_WSL2": "0",
        "TB_HS1_CALLS": str(s["calls"]),
    }  # fmt: skip


def _run(s: dict[str, Path], answer: str | None, *args: str) -> subprocess.CompletedProcess[str]:
    """``bash <stick>/install``: only the stick's path. ``answer`` None is a closed standard input."""
    argv = ["bash", str(s["usb"] / "install"), *args]
    stdin = subprocess.DEVNULL if answer is None else None
    return subprocess.run(argv, input=answer, stdin=stdin, capture_output=True, text=True, env=_env(s),
                          cwd=s["tmp"], check=False, timeout=120)  # fmt: skip


def _snapshot(root: Path) -> dict[str, str]:
    """Every path under the test's root with what it holds: "nothing changed" is this, equal before and after."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = "link:" + os.readlink(p)
        elif p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            out[rel] = "dir"
    return out


def _fingerprint(pub: Path) -> str:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_public_key(pub.read_bytes())
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    h = hashlib.sha256(der).hexdigest()[:24]
    return " ".join(h[i : i + 4] for i in range(0, 24, 4))


# ------------------------------------------------------------------------------------------- the design's two
def test_a_run_with_only_the_sticks_path_reaches_the_plan(stick: dict[str, Path]) -> None:
    got = _run(stick, "yes\n")
    out = got.stdout + got.stderr
    assert f"Vendor key fingerprint:  {_fingerprint(stick['pub'])}" in got.stdout
    assert "The installer on the stick is signed by this key." in got.stdout
    # the box form ran from the unpacked host tree, with no --pub, --, --tier, --answers or mount path typed
    assert "==> plan from the hardware" in out, out
    answers = json.loads((stick["opt"] / "deploy/site/box/answers.json").read_text(encoding="utf-8"))
    assert answers["tls_mode"] == "internal"
    calls = stick["calls"].read_text(encoding="utf-8")
    assert "--mode gpu --gpu rtxpro6000" in calls and str(stick["usb"] / "trialbox-1.0.0.tar") in calls
    assert (stick["opt"] / "deploy/keys/vendor_ed25519.pub").read_bytes() == stick["pub"].read_bytes()
    # the stand-in install stopped: the box form says so and the launcher passes its exit on
    assert got.returncode == 1 and "the install stopped" in got.stderr
    assert list((stick["tmp"] / "tmp").iterdir()) == []  # the private copies are gone


@pytest.mark.parametrize("answer", ["no\n", "n\n", "\n", "maybe\n", "yes please\n", None], ids=repr)
def test_a_no_to_the_fingerprint_stops_with_nothing_changed(stick: dict[str, Path], answer: str | None) -> None:
    before = _snapshot(stick["tmp"])
    got = _run(stick, answer)
    assert got.returncode == 1
    assert "Nothing was changed." in got.stderr
    assert ("no answer" in got.stderr) is (answer is None)  # a closed standard input is said so, never taken as yes
    assert _snapshot(stick["tmp"]) == before
    assert not stick["opt"].exists() and not (stick["tmp"] / "firstrun").exists()


# ------------------------------------------------------------------------------------------- the trust chain
@pytest.mark.parametrize("how", ["other-key", "changed-after-signing", "empty-sig", "no-sig"])
def test_a_wrong_signature_stops_with_nothing_changed(stick: dict[str, Path], how: str) -> None:
    """The invariant: the bootstrap runs only when its signature checks with the key whose fingerprint was confirmed."""
    usb = stick["usb"]
    boot = usb / "trialbox-bootstrap.sh"
    if how == "other-key":
        other, _ = sign_bundle.keygen(stick["tmp"] / "other")
        sign_bundle.sign_file(other, boot)
    elif how == "changed-after-signing":
        boot.write_text(boot.read_text(encoding="utf-8") + "\ntouch /tmp/planted\n", encoding="utf-8")
    elif how == "empty-sig":
        (usb / "trialbox-bootstrap.sh.sig").write_bytes(b"")
    else:
        (usb / "trialbox-bootstrap.sh.sig").unlink()
    before = _snapshot(stick["tmp"])
    got = _run(stick, "yes\n")
    assert got.returncode == 1
    assert "Nothing was changed." in got.stderr or "trialbox-bootstrap.sh.sig" in got.stderr
    assert "Call the vendor." in got.stderr
    assert _snapshot(stick["tmp"]) == before
    assert not stick["opt"].exists() and not stick["calls"].exists()


def test_a_bundle_signed_by_another_key_still_stops_in_the_bootstrap(stick: dict[str, Path]) -> None:
    """The launcher hands the confirmed key on: the bootstrap's own check of the bundle is kept."""
    other, _ = sign_bundle.keygen(stick["tmp"] / "other")
    host = _host_tar(stick["tmp"] / "other" / "trialbox-host.tar")
    sign_bundle.build(other, "1.0.0", [("host", host, "trialbox-host.tar")], stick["usb"] / "trialbox-1.0.0.tar",
                      release_seq=1)  # fmt: skip
    got = _run(stick, "yes\n")
    assert got.returncode == 1 and "the bundle is refused" in got.stderr
    assert not stick["opt"].exists() and not stick["calls"].exists()


def test_the_fingerprint_is_one_definition_in_the_launcher_the_bootstrap_and_the_bundle_builder() -> None:
    line = re.compile(r"^fingerprint\(\) \{ .* \}$", re.M)
    found = {p: line.findall((ROOT / p).read_text(encoding="utf-8")) for p in
             ("deploy/launcher.sh", "deploy/bootstrap.sh", "tools/make_bundle.sh")}  # fmt: skip
    assert all(len(v) == 1 for v in found.values()), found
    assert len({v[0] for v in found.values()}) == 1, found


def test_the_bootstrap_shows_the_same_fingerprint(stick: dict[str, Path]) -> None:
    env = _env(stick)
    got = subprocess.run(["bash", str(BOOT), str(stick["usb"] / "trialbox-1.0.0.tar"), "--pub", str(stick["pub"]),
                          "--", "--help"], capture_output=True, text=True, env=env, check=False, timeout=60)  # fmt: skip
    assert f"(fingerprint: {_fingerprint(stick['pub'])})" in got.stdout, got.stderr
    assert "the IT form: " in got.stdout  # without --box the bootstrap runs install.sh as before


# -------------------------------------------------------------------------------------------- the surface
def test_the_launcher_takes_no_option(stick: dict[str, Path]) -> None:
    for args in (["--pub", "x"], ["--"], ["--tier", "large"], ["--answers", "site.yaml"], [str(stick["usb"])]):
        before = _snapshot(stick["tmp"])
        got = _run(stick, "yes\n", *args)
        assert got.returncode == 1 and "takes no option" in got.stderr, args
        assert _snapshot(stick["tmp"]) == before
    helped = _run(stick, None, "--help")
    assert helped.returncode == 0 and "sudo bash /media/<stick>/install" in helped.stdout


def test_a_stick_without_one_release_stops(stick: dict[str, Path]) -> None:
    shutil.copy2(stick["usb"] / "trialbox-1.0.0.tar", stick["usb"] / "trialbox-1.0.1.tar")
    got = _run(stick, "yes\n")
    assert got.returncode == 1 and "exactly one TrialBox release" in got.stderr
    (stick["usb"] / "trialbox-1.0.1.tar").unlink()
    (stick["usb"] / "vendor_ed25519.pub").unlink()
    got = _run(stick, "yes\n")
    assert got.returncode == 1 and "no vendor_ed25519.pub" in got.stderr
    assert not stick["opt"].exists()


def test_the_launchers_messages_are_plain_with_one_action_each() -> None:
    """English lines (the deploy scripts' text is not in a catalogue yet: HS-5 moves it). No setting, no D number,
    no RUNBOOK section, no flag; each stop names one thing to do."""
    text = LAUNCHER.read_text(encoding="utf-8")
    shown = re.findall(r'^\s*(?:.*\b)?(?:stop|echo|printf)\s+(?:\'[^\']*\'\s+)?"([^"]*)"', text, re.M)
    assert len(shown) >= 12, shown
    for line in shown:
        assert not re.search(r"\bTB_|\bD-\d|RUNBOOK|§|--(?!help)", line), line
    stops = re.findall(r'\bstop "([^"]*)"', text)
    assert len(stops) >= 8
    for line in stops:
        actions = re.findall(r"\b(?:Call the vendor|Type:|Install Ubuntu|Run the command again)\b", line)
        assert len(actions) <= 1, line


def test_make_bundle_puts_the_launcher_and_the_key_on_the_stick() -> None:
    sh = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert 'install -m 0755 "$ROOT/deploy/launcher.sh" "$(dirname "$OUT")/install"' in sh
    assert 'openssl pkey -in "$KEY" -pubout -out "$STICK_PUB"' in sh
    assert 'the delivery sheet carries the vendor key\'s fingerprint: $(fingerprint "$STICK_PUB")' in sh
