"""Review of #1482 (1482-1): on a host whose python3 has no ``cryptography`` the keys commands run in the image, which
sees only the folders the script mounts. The TPM path must still seal, wrap and unseal: the plain KEK's own folder
(run/trialbox-seal) is one of them, and it is never made by the engine (a mount of a missing folder would make it
root's 0755, which the next seal refuses)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from tb_common import kek as K

ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
IMAGE = "trialbox-py:standin"

pytestmark = pytest.mark.nodb

# a container engine that shows the command only the host folders given with -v: a path of the test's own tree that
# no mount covers is not there inside the container
ENGINE = r"""
import json, os, subprocess, sys
args = sys.argv[1:]
with open(@LOG@, "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:1] != ["run"] or @IMAGE@ not in args:
    sys.exit(f"stand-in docker: unexpected {args}")
opts, cmd = args[1 : args.index(@IMAGE@)], args[args.index(@IMAGE@) + 1 :]
mounts = [opts[i + 1].split(":")[0] for i, o in enumerate(opts) if o == "-v"]
for a in cmd:
    if a.startswith(@TMP@) and not any(a == m or a.startswith(m.rstrip("/") + "/") for m in mounts):
        sys.exit(f"stand-in docker: {a} is not mounted into the container: No such file or directory")
env = {"PATH": os.environ["PATH"], "PYTHONPATH": @PYP@}
env |= {opts[i + 1]: os.environ[opts[i + 1]] for i, o in enumerate(opts) if o == "-e" and opts[i + 1] in os.environ}
sys.exit(subprocess.run(cmd, cwd=@ROOT@, env=env, stdin=sys.stdin if "-i" in opts else subprocess.DEVNULL).returncode)
"""


def _tpm_host_without_cryptography(tmp: Path) -> dict[str, str]:
    hr = tmp / "host"
    (hr / "dev").mkdir(parents=True)
    (hr / "dev" / "tpmrm0").write_text("")
    sec = tmp / "secrets"
    sec.mkdir()
    for name in ("site_hmac.key", "pid_map.key"):
        (sec / name).write_bytes(os.urandom(32))
    b = tmp / "bin"
    b.mkdir()
    py = b / "python"  # the image's interpreter (a wrapper, so that a virtual environment stays its own)
    py.write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n')
    py.chmod(0o755)
    py3 = b / "python3"
    py3.write_text(f'#!/bin/sh\n[ "$1 $2" = "-c import cryptography" ] && exit 1\nexec {sys.executable} "$@"\n')
    py3.chmod(0o755)
    creds = b / "systemd-creds"
    creds.write_text(
        '#!/bin/sh\ncase "$1" in has-tpm2) exit 0 ;; encrypt) cp "$4" "$5" ;; decrypt) cp "$3" "$4" ;; esac\n'
    )
    creds.chmod(0o755)
    engine = b / "docker"
    body = (ENGINE.replace("@LOG@", repr(str(tmp / "docker.log"))).replace("@IMAGE@", repr(IMAGE))
            .replace("@TMP@", repr(str(tmp))).replace("@ROOT@", repr(str(ROOT)))
            .replace("@PYP@", repr(f"{ROOT / 'libs'}:{ROOT}")))  # fmt: skip
    engine.write_text(f"#!{sys.executable}\n" + body)
    engine.chmod(0o755)
    keep = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    return {**keep, "PATH": f"{b}:/usr/bin:/bin", "TB_HOST_ROOT": str(hr), "TB_SYSTEMD": "0", "TB_IMAGE": IMAGE,
            "TB_KEK_BACKEND": "tpm"}  # fmt: skip


def test_the_tpm_path_seals_wraps_and_unseals_through_the_image(tmp_path: Path) -> None:
    import subprocess

    env = _tpm_host_without_cryptography(tmp_path)
    res = subprocess.run(["sh", str(SEAL), "--secrets", str(tmp_path / "secrets"), "--conf", str(tmp_path / "none")],
                         capture_output=True, text=True, env=env, check=False, timeout=300)  # fmt: skip
    assert res.returncode == 0, res.stdout + res.stderr
    sec = tmp_path / "secrets"
    meta = K.read_meta(sec)
    assert meta is not None and meta["backend"] == "file"
    assert K.wrapped_path(sec / "site_hmac.key").exists() and not (sec / "site_hmac.key").exists()
    kek = tmp_path / "host" / "run" / "trialbox" / "kek"
    cred = tmp_path / "host" / "etc" / "credstore.encrypted" / "trialbox-kek"
    assert kek.read_bytes() == cred.read_bytes()  # the stand-in "sealed" by copying
    assert not list((tmp_path / "host" / "run").rglob("kek.new"))
    calls = [json.loads(x) for x in (tmp_path / "docker.log").read_text().splitlines()]
    assert len(calls) >= 3  # init, unseal, check: every one through the image
