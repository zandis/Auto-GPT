"""SC-1b (D-993): the db image drops root with setpriv, not with the upstream image's gosu.

``postgres:16-trixie`` ships ``/usr/local/bin/gosu``, a Go binary (Go 1.24.6 on 2026-11-17) that carried 28 of the
image's 30 allow-list entries (Go ``stdlib`` and ``golang-org/x/sys``), and no newer base digest rebuilds it. The upstream
entrypoint calls ``gosu postgres "$BASH_SOURCE" "$@"``; our image puts a shell shim at the same path that runs
``setpriv --reuid --regid --init-groups`` (util-linux, already in the base: ``/usr/bin/setpriv``), so the entrypoint is
unchanged and the Go binary is gone. The shim is run here for real as root and must leave exactly the user's own uid,
gid and groups.
"""

from __future__ import annotations

import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ROOT / "deploy" / "docker"
SHIM = DOCKER / "db.gosu-setpriv.sh"


def test_the_image_replaces_the_go_binary_with_the_shim() -> None:
    df = (DOCKER / "db.Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"COPY --chmod=0755 db\.gosu-setpriv\.sh /usr/local/bin/gosu\b", df)
    # the shim is copied over the binary's path, so the Go binary is not in the final filesystem; the build proves it
    # is a shell script and that setpriv is there before anything else runs
    assert "head -c 2 /usr/local/bin/gosu" in df and "command -v setpriv" in df


def test_the_shim_runs_setpriv_with_the_users_own_ids_and_groups() -> None:
    sh = SHIM.read_text(encoding="utf-8")
    assert sh.startswith("#!/bin/sh\n")
    assert 'exec setpriv --reuid="$uid" --regid="$gid" --init-groups -- "$@"' in sh
    assert "gosu" not in sh.split("\n", 2)[2].split("exec setpriv")[1]  # nothing after the exec


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(SHIM), *args], capture_output=True, text=True, check=False, timeout=30)


needs_root = pytest.mark.skipif(
    os.geteuid() != 0 or shutil.which("setpriv") is None, reason="the privilege drop needs root and setpriv"
)


@needs_root
def test_it_drops_to_the_user_with_no_other_groups() -> None:
    nobody = pwd.getpwnam("nobody")
    got = _run("nobody", "sh", "-c", 'echo "$(id -u) $(id -g) $(id -G)"')
    assert got.returncode == 0, got.stderr
    uid, gid, *groups = got.stdout.split()
    assert (int(uid), int(gid)) == (nobody.pw_uid, nobody.pw_gid)
    assert set(map(int, groups)) <= {nobody.pw_gid} | set(os.getgrouplist("nobody", nobody.pw_gid))
    assert 0 not in map(int, groups)  # root's group is gone


@needs_root
def test_user_and_group_and_numeric_ids() -> None:
    nobody = pwd.getpwnam("nobody")
    got = _run(f"{nobody.pw_uid}:{nobody.pw_gid}", "id", "-u")
    assert got.returncode == 0 and got.stdout.strip() == str(nobody.pw_uid), got.stderr
    named = _run(f"nobody:{nobody.pw_gid}", "id", "-g")
    assert named.returncode == 0 and named.stdout.strip() == str(nobody.pw_gid), named.stderr


def test_a_bad_call_is_refused() -> None:
    assert _run().returncode != 0
    assert _run("nobody").returncode != 0  # no command
    unknown = _run("no-such-user-tb", "true")
    assert unknown.returncode != 0 and "no-such-user-tb" in unknown.stderr


def test_the_rehearsal_checks_the_server_runs_as_postgres() -> None:
    box = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    install = box[box.index("\ninstall)\n") : box.index("\n  ;;\n", box.index("\ninstall)\n"))]
    assert "/proc/1/status" in install and "999" in install


def test_zlib_is_held_at_the_debian_security_fix() -> None:
    """The base's zlib1g (1:1.3.dfsg+really1.3.1-1+b1) carries CVE-2026-85091; trixie-security has the fix
    (``+deb13u1``) for amd64 and arm64. The image installs and holds it like its other pinned packages."""
    df = (DOCKER / "db.Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^ARG ZLIB1G_VERSION=1:1\.3\.dfsg\+really1\.3\.1-1\+deb13u1$", df, re.M)
    assert '"zlib1g=${ZLIB1G_VERSION}"' in df and "apt-mark hold" in df and " zlib1g" in df.split("apt-mark hold", 1)[1]
    assert 'dpkg-query -W -f \'${Version}\' zlib1g)" = "${ZLIB1G_VERSION}"' in df
    import json

    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    assert lock["images"]["db"]["packages"]["zlib1g"] == "1:1.3.dfsg+really1.3.1-1+deb13u1"
