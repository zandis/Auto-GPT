"""H-22 findings 1, 2 and 4 (D-996): the install runbook's first command runs from the USB stick alone.

Lane H followed RUNBOOK §1 on a clean host (D-1136, #993). It stopped at the one command, because nothing put the
release's host tree in ``/opt/trialbox``. It stopped again because the vendor key was placed only at step 6, and
again at "bundle checksum mismatch", because the sidecar named the bundle by the vendor's ``--out`` path. Now:

* ``tools/make_bundle.sh`` writes ``trialbox-bootstrap.sh`` beside the bundle, with ``.sig``: the vendor key's raw
  Ed25519 signature, which a bare Ubuntu checks with ``openssl`` before running it (as ``box-prepare.sh`` checks the
  box media). Its sidecars name each file bare, so they check from wherever the stick is mounted;
* ``deploy/bootstrap.sh`` (the bootstrap) uses only tar, base64, openssl, sha256sum and python3's standard library.
  It verifies the bundle's ``manifest.json.sig`` with the key given out of band, checks the host tree against the
  manifest's sha256, unpacks it to ``/opt/trialbox`` (never over a folder that holds something else), places the key
  where the installer looks for it, and runs ``deploy/install.sh`` with the bundle and the rest of the arguments.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from tools import sign_bundle

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "deploy" / "bootstrap.sh"
INSTALL = '#!/usr/bin/env bash\necho "installer: $0 $*"\n'

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="the bootstrap checks with openssl")


def _host_tar(path: Path, files: dict[str, str]) -> Path:
    with tarfile.open(path, "w:") as tf:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            tf.addfile(info, io.BytesIO(data))
    return path


@pytest.fixture
def stick(tmp_path: Path) -> dict[str, Path]:
    keys = tmp_path / "vendor"
    priv, pub = sign_bundle.keygen(keys)
    usb = tmp_path / "usb"
    usb.mkdir()
    host = _host_tar(tmp_path / "trialbox-host.tar", {"deploy/install.sh": INSTALL, "tools/x.py": ""})
    bundle = usb / "trialbox-1.0.0.tar"
    sign_bundle.build(priv, "1.0.0", [("host", host, "trialbox-host.tar")], bundle, release_seq=1)
    return {"priv": priv, "pub": pub, "bundle": bundle, "opt": tmp_path / "opt" / "trialbox", "tmp": tmp_path}


def _boot(s: dict[str, Path], *args: str, pub: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(s["opt"])}
    argv = ["bash", str(BOOT), str(s["bundle"]), "--pub", str(pub or s["pub"]), *args]
    return subprocess.run(argv, capture_output=True, text=True, env=env, check=False, timeout=60)


def test_it_unpacks_the_signed_host_tree_places_the_key_and_runs_the_installer(stick: dict[str, Path]) -> None:
    got = _boot(stick, "--", "--tier", "large", "--answers", "site.yaml")
    assert got.returncode == 0, got.stderr
    opt = stick["opt"]
    assert (opt / "deploy" / "install.sh").is_file() and (opt / "tools" / "x.py").is_file()
    assert (opt / "deploy" / "keys" / "vendor_ed25519.pub").read_bytes() == stick["pub"].read_bytes()
    assert f"installer: {opt}/deploy/install.sh {stick['bundle']} --tier large --answers site.yaml" in got.stdout


def test_a_second_run_keeps_the_tree_and_runs_the_installer_again(stick: dict[str, Path]) -> None:
    """An install that stopped (no TPM, a missing answer) is run again by the same first command."""
    assert _boot(stick).returncode == 0
    (stick["opt"] / "deploy" / ".env").write_text("TB_ENV=VALIDATION\n")
    again = _boot(stick, "--", "--yes")
    assert again.returncode == 0, again.stderr
    assert "kept" in again.stdout and (stick["opt"] / "deploy" / ".env").is_file()
    assert "--yes" in again.stdout.splitlines()[-1]


def test_another_vendor_key_is_refused_before_anything_is_written(stick: dict[str, Path]) -> None:
    _, other = sign_bundle.keygen(stick["tmp"] / "other")
    got = _boot(stick, pub=other)
    assert got.returncode != 0 and "signature" in got.stderr
    assert not stick["opt"].exists()


def test_a_host_tree_that_is_not_the_signed_one_is_refused(stick: dict[str, Path]) -> None:
    """The manifest is signed; a payload swapped under it fails its sha256."""
    bundle, swapped = stick["bundle"], stick["tmp"] / "swapped.tar"
    with tarfile.open(bundle) as src, tarfile.open(swapped, "w:") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read()  # type: ignore[union-attr]
            if m.name == "files/trialbox-host.tar":
                data = _host_tar(stick["tmp"] / "evil.tar", {"deploy/install.sh": "echo evil\n"}).read_bytes()
                m.size = len(data)
            dst.addfile(m, io.BytesIO(data))
    swapped.replace(bundle)
    got = _boot(stick)
    assert got.returncode != 0 and "trialbox-host.tar" in got.stderr and "sha256" in got.stderr
    assert not stick["opt"].exists()


def test_a_folder_that_holds_something_else_is_never_replaced(stick: dict[str, Path]) -> None:
    stick["opt"].mkdir(parents=True)
    (stick["opt"] / "notes.txt").write_text("the site's\n")
    got = _boot(stick)
    assert got.returncode != 0 and "not a TrialBox host tree" in got.stderr
    assert sorted(p.name for p in stick["opt"].iterdir()) == ["notes.txt"]


def test_a_different_key_already_on_the_box_is_refused(stick: dict[str, Path]) -> None:
    assert _boot(stick).returncode == 0
    _, other = sign_bundle.keygen(stick["tmp"] / "other")
    (stick["opt"] / "deploy" / "keys" / "vendor_ed25519.pub").write_bytes(other.read_bytes())
    got = _boot(stick)
    assert got.returncode != 0 and "differs" in got.stderr


def test_usage_and_root(stick: dict[str, Path]) -> None:
    no_pub = subprocess.run(["bash", str(BOOT), str(stick["bundle"])], capture_output=True, text=True, check=False)
    assert no_pub.returncode == 2 and "--pub" in no_pub.stderr
    if os.geteuid() != 0:
        as_user = subprocess.run(["bash", str(BOOT), str(stick["bundle"]), "--pub", str(stick["pub"])],
                                 capture_output=True, text=True, check=False)  # fmt: skip
        assert as_user.returncode != 0 and "root" in as_user.stderr


def test_it_needs_only_what_a_bare_ubuntu_has() -> None:
    """No pip package and no host tree: the bootstrap runs before either is there."""
    sh = BOOT.read_text(encoding="utf-8")
    assert "python3 -I" in sh and not re.search(r"\bimport (yaml|cryptography)\b", sh)
    assert "tools/" not in sh.replace("$ROOT/deploy/install.sh", "")


# ------------------------------------------------------------------------------------------------- the vendor side
def test_sign_file_is_checked_by_openssl_as_the_runbook_checks_it(stick: dict[str, Path]) -> None:
    script = stick["tmp"] / "trialbox-bootstrap.sh"
    shutil.copy(BOOT, script)
    sign_bundle.main(["sign-file", "--key", str(stick["priv"]), str(script)])
    sig = script.with_name(script.name + ".sig")
    assert len(sig.read_bytes()) == 64  # raw Ed25519
    ok = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(stick["pub"]), "-rawin", "-in",
                         str(script), "-sigfile", str(sig)], capture_output=True, text=True, check=False)  # fmt: skip
    assert ok.returncode == 0, ok.stderr
    script.write_text(script.read_text() + "# changed\n")
    bad = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(stick["pub"]), "-rawin", "-in",
                          str(script), "-sigfile", str(sig)], capture_output=True, text=True, check=False)  # fmt: skip
    assert bad.returncode != 0


def test_make_bundle_puts_the_signed_bootstrap_beside_the_bundle_with_bare_sidecars() -> None:
    sh = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert 'cp "$ROOT/deploy/bootstrap.sh" "$BOOT"' in sh
    assert 'sign_bundle.py" sign-file --key "$KEY" "$BOOT"' in sh
    # finding 4: each sidecar names its file bare, written from the file's own folder
    assert (
        '(cd "$(dirname "$OUT")" && sha256sum "$(basename "$OUT")" "$(basename "$BOOT")" "$(basename "$BOOT").sig")'
        in sh
    )
    assert 'sha256sum "$OUT" | tee' not in sh


def test_the_sidecar_checks_from_another_mount(tmp_path: Path) -> None:
    """Written as make_bundle.sh writes it, then checked as install.sh checks it, from another path."""
    out = tmp_path / "vendor" / "dist" / "trialbox-1.0.0.tar"
    out.parent.mkdir(parents=True)
    for name in ("trialbox-1.0.0.tar", "trialbox-bootstrap.sh", "trialbox-bootstrap.sh.sig"):
        (out.parent / name).write_bytes(name.encode())
    line = re.search(r"^\(cd \"\$\(dirname \"\$OUT\"\)\".*$", (ROOT / "tools/make_bundle.sh").read_text(), re.M)
    assert line
    boot = out.parent / "trialbox-bootstrap.sh"
    subprocess.run(["bash", "-c", line.group(0)], env={**os.environ, "OUT": str(out), "BOOT": str(boot)},
                   check=True, capture_output=True)  # fmt: skip
    usb = tmp_path / "media" / "usb"
    shutil.copytree(out.parent, usb)
    assert _installer_check(usb / "trialbox-1.0.0.tar").returncode == 0
    # the stick may carry the bundle and its sidecar only: the bundle's own line is what the installer checks
    (usb / "trialbox-bootstrap.sh").unlink()
    assert _installer_check(usb / "trialbox-1.0.0.tar").returncode == 0
    (usb / "trialbox-1.0.0.tar").write_bytes(b"not the vendor's")
    bad = _installer_check(usb / "trialbox-1.0.0.tar")
    assert bad.returncode != 0 and "bundle checksum mismatch" in bad.stderr


def test_a_sidecar_that_names_the_vendors_path_says_so(tmp_path: Path) -> None:
    """A bundle made before D-996: its sidecar names the vendor's --out path, which the installer cannot check."""
    b = tmp_path / "trialbox-1.0.0.tar"
    b.write_bytes(b"x")
    digest = subprocess.run(["sha256sum", str(b)], capture_output=True, text=True, check=True).stdout.split()[0]
    (tmp_path / "trialbox-1.0.0.tar.sha256").write_text(f"{digest}  /home/vendor/dist/trialbox-1.0.0.tar\n")
    got = _installer_check(b)
    assert got.returncode != 0 and "does not name trialbox-1.0.0.tar" in got.stderr and "sha256sum" in got.stderr


def _installer_check(bundle: Path) -> subprocess.CompletedProcess[str]:
    """install.sh's own SIDECAR block, run as it runs there."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    block = text[text.index("# ---- SIDECAR") : text.index("# ---- end of SIDECAR")]
    script = 'die() { echo "install: $*" >&2; exit 1; }\n' + block
    return subprocess.run(["bash", "-c", script], env={**os.environ, "BUNDLE": str(bundle)}, capture_output=True,
                          text=True, check=False)  # fmt: skip


# ------------------------------------------------------------------------------------------------- the rehearsal
def _phase(name: str) -> str:
    m = re.search(rf"\n{name}\)\n(.*?)\n  ;;\n", (ROOT / "tools/rehearse_box/box.sh").read_text(encoding="utf-8"), re.S)
    assert m, f"box.sh has no {name} phase"
    return m.group(1)


def test_the_rehearsal_runs_the_first_command_as_the_runbook_writes_it() -> None:
    step = _phase("bootstrap")
    assert 'openssl pkeyutl -verify -pubin -inkey "$pub" -rawin -in "$b" -sigfile "$b.sig"' in step
    assert 'bash "$b" "$BUNDLE" --pub "$pub" -- --ctgov-check' in step and "TB_CTGOV_PROBE=fail" in step
    assert 'cmp -s "$pub" "$opt/deploy/keys/vendor_ed25519.pub"' in step
    steps = re.findall(r"^step ([a-z-]+) ", (ROOT / "tools/rehearse_box/rehearse.sh").read_text(encoding="utf-8"), re.M)
    assert steps.index("host-up") < steps.index("bootstrap") < steps.index("install")
    assert "openssl" in (ROOT / "tools/rehearse_box/host.Dockerfile").read_text(encoding="utf-8")


def test_the_rehearsal_installs_from_media_away_from_the_vendors_folder() -> None:
    """Finding 4 hid because the rehearsal's media was the vendor's --out path: the installer found the file by it."""
    sh = (ROOT / "tools/rehearse_box/rehearse.sh").read_text(encoding="utf-8")
    assert '--out "$W/vendor/dist/$BUNDLE_NAME"' in sh and '--out "$MEDIA/linux/' not in sh
    assert re.search(r'mv "\$W/vendor/dist/\$BUNDLE_NAME" .*"\$MEDIA/linux/" && rmdir "\$W/vendor/dist"', sh, re.S)
