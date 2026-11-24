"""The review of #1305 (install faults F-17, F-19, F-33), the findings fixed in this card besides the cleanup
(``test_install_cleanup_is_fail_closed.py``): the KEK passphrase reaches no Docker container configuration and no
``deploy/.env``, the documented hidden input keeps it exactly as typed, a lost ``createdb`` answer still gets its
scratch database dropped. No Docker daemon: the engine is a stand-in that runs the container's command here."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
IMAGE = "stand-in-image:1"

# The engine: every call recorded (its arguments, never its stdin); `run IMAGE cmd...` runs cmd here with only the
# variables its -e options name, as a container gets them, and the stdin it was given.
ENGINE = rf"""
import json, os, subprocess, sys
args = sys.argv[1:]
with open({{log!r}}, "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:1] != ["run"] or {IMAGE!r} not in args:
    sys.exit(f"stand-in docker: unexpected {{args}}")
opts, cmd = args[1 : args.index({IMAGE!r})], args[args.index({IMAGE!r}) + 1 :]
env = {{"PATH": os.environ["PATH"], "PYTHONPATH": {str(ROOT / "libs")!r} + ":" + {str(ROOT)!r}}}
env |= {{opts[i + 1]: os.environ[opts[i + 1]] for i, o in enumerate(opts) if o == "-e" and opts[i + 1] in os.environ}}
sys.exit(subprocess.run(cmd, cwd={str(ROOT)!r}, env=env, stdin=sys.stdin if "-i" in opts else subprocess.DEVNULL).returncode)
"""


def _sealing_host(tmp: Path) -> dict[str, str]:
    """No TPM, no hardening.conf, and a host python3 without ``cryptography``: the keys commands run in the image."""
    hr = tmp / "host"
    (hr / "dev").mkdir(parents=True)
    sec = tmp / "secrets"
    sec.mkdir()
    for name in ("site_hmac.key", "pid_map.key"):
        (sec / name).write_bytes(os.urandom(32))
    b = tmp / "bin"
    b.mkdir()
    (b / "python").symlink_to(sys.executable)  # the image's interpreter
    py3 = b / "python3"
    py3.write_text(f'#!/bin/sh\n[ "$1 $2" = "-c import cryptography" ] && exit 1\nexec {sys.executable} "$@"\n')
    py3.chmod(0o755)
    engine = b / "docker"
    engine.write_text(f"#!{sys.executable}\n" + ENGINE.replace("{log!r}", repr(str(tmp / "docker.log"))))
    engine.chmod(0o755)
    keep = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    return {**keep, "PATH": f"{b}:/usr/bin:/bin", "TB_HOST_ROOT": str(hr), "TB_SYSTEMD": "0",
            "TB_KEK_FILE": str(tmp / "kek.runtime"), "TB_IMAGE": IMAGE}  # fmt: skip


def test_the_image_fallback_takes_the_passphrase_on_stdin_never_in_the_container_environment(tmp_path: Path) -> None:
    """Review 3: ``docker run -e TB_KEK_PASSPHRASE`` put the passphrase in the container's configuration on disk
    until it was removed. It now goes through the container's stdin; the keys are sealed and unsealed by it."""
    phrase = "  " + os.urandom(12).hex() + " with spaces  "
    env = {**_sealing_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}  # H-96: on stdin (ruling 7094934985)
    res = subprocess.run(["sh", str(SEAL), "--secrets", str(tmp_path / "secrets"), "--conf", str(tmp_path / "none"),
                          "--kek-passphrase-stdin"], input=phrase + "\n",
                         capture_output=True, text=True, env=env, check=False, timeout=300)  # fmt: skip
    assert res.returncode == 0, res.stderr
    calls = [json.loads(x) for x in (tmp_path / "docker.log").read_text().splitlines()]
    assert len(calls) >= 3  # init, unseal, check (and the audit key): every one through the image
    for call in calls:
        given = {call[i + 1] for i, a in enumerate(call) if a == "-e"}
        assert "TB_KEK_PASSPHRASE" not in given and not any(a.startswith("TB_KEK_PASSPHRASE") for a in call), call
        assert not any(phrase.strip() in a for a in call), call
    assert phrase.strip() not in res.stdout + res.stderr
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None and meta["backend"] == "passphrase"
    assert K.derive_from_passphrase(phrase, meta) == (tmp_path / "kek.runtime").read_bytes()  # exactly as typed


def test_an_answers_file_cannot_put_the_kek_passphrase_in_the_env_file() -> None:
    """Review 4: ``env_extra`` took any declared setting, the KEK passphrase too, and wrote it to deploy/.env."""
    from tools import settings_wizard as sw

    for name in ("TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE"):
        errors: list[str] = []
        out = sw.env_extra({name: "synthetic-test-phrase", "TB_TZ": "Asia/Tokyo"}, errors)
        assert name not in out and any(name in e and "never goes in a file" in e for e in errors), (out, errors)
        assert "synthetic-test-phrase" not in json.dumps(out)


def _hidden_inputs() -> dict[str, str]:
    """Every documented hidden-input line for a KEK passphrase: the installers' help and the pages."""
    texts = {s: subprocess.check_output(["bash", s, "--help"], cwd=ROOT, text=True)
             for s in ("deploy/install.sh", "deploy/box-install.sh")}  # fmt: skip
    for page in ("docs/runbook/16-box-install-rehearsal.md", "docs/security/10-key-ceremony-and-escrow.md"):
        texts[page] = (ROOT / page).read_text(encoding="utf-8")
    lines = {}
    for where, text in texts.items():
        for m in re.finditer(r"(?:IFS= )?read -rs (TB_KEK_\w*PASSPHRASE);", text):
            lines[f"{where}:{m.group(1)}"] = m.group(0).rstrip(";")
    return lines


def test_the_documented_hidden_input_keeps_the_passphrase_exactly_as_typed() -> None:
    """Review 11: Bash ``read`` without ``IFS=`` strips leading and trailing blanks, so the keys were sealed under a
    passphrase other than the one the custodian wrote down."""
    lines = _hidden_inputs()
    assert len(lines) == 4, lines
    typed = "  synthetic phrase \t "
    for where, line in lines.items():
        name = line.rsplit(" ", 1)[1]
        got = subprocess.run(["bash", "-c", f'{line}; printf %s "${name}"'], input=typed + "\n", text=True,
                             capture_output=True, check=False).stdout  # fmt: skip
        assert got == typed, (where, got)


def test_a_lost_createdb_answer_still_drops_the_scratch_database(tmp_path: Path) -> None:
    """Review 7: the scratch name was recorded only after Docker acknowledged ``createdb``; a lost answer left a
    database that neither the cleanup nor the result named."""
    from tools.trialbox import box_drill, update
    from tools.trialbox import restore_drill as rd

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_DB_URL=postgresql://trialbox@db:5432/trialbox_wf\n")
    calls: list[list[str]] = []
    manifest = {"created_at": "2026-11-20T00:00:00+00:00", "databases": {"trialbox_wf": {"rows": {}}},
                "_sha256": "0" * 64, "files": [], "site": "SYN"}  # fmt: skip

    def engine(argv: list[str], stdin_file: Path | None = None, env: dict[str, Any] | None = None, **_: Any) -> str:
        calls.append(argv)
        if box_drill.MODULE in argv:
            return json.dumps(manifest)
        if any(a.startswith("exec createdb ") for a in argv):
            raise update.UpdateFailed("the engine's answer was lost after createdb ran")
        return ""

    ops = box_drill.BoxDrill(deploy)
    ops.box.run = engine
    (tmp_path / "b.tbbak").write_bytes(b"synthetic")
    (tmp_path / "usb.key").write_bytes(b"synthetic")
    res = rd.drill(tmp_path / "b.tbbak", tmp_path / "usb.key", {}, work=tmp_path, db_dir=tmp_path,
                   free=lambda _p: 10**12, ops=ops)  # fmt: skip
    assert not res["ok"], res
    assert len(res["scratch_dropped"]) == 1, res
    (name,) = res["scratch_dropped"]
    assert name.startswith(rd.SCRATCH_PREFIX) and "left_behind" not in res
    drops = [c for c in calls if any(a.startswith("exec dropdb ") for a in c)]
    assert len(drops) == 1 and drops[0][-1] == name
