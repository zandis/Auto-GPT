"""The second independent review of #1305 (install faults F-17, F-19, F-33), the findings fixed in this round besides
the cleanup's states (``test_install_cleanup_is_fail_closed.py``): two installer runs at once (M-2), the drill's
scratch name recorded before the live-name guard (L-1), a passphrase with a line break (L-2), the network sheet's
passphrase row (L-3). No Docker daemon: the engine is a stand-in that records its calls."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"


def _box(tmp: Path) -> tuple[Path, dict[str, str], Path]:
    """An install folder that was a rehearsal box: a run that gets past the lock stops at the REHEARSAL step, the
    first one that writes. The engine answers as a running one and records every call."""
    box = tmp / "box"
    (box / "deploy" / "keys").mkdir(parents=True)
    (box / "deploy" / "site").mkdir()
    (box / "deploy" / "keys" / "vendor_ed25519.pub").write_text("stand-in key\n", encoding="utf-8")
    (box / "deploy" / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    # H-94: the box records PRODUCTION, so the mark stops the run (kept refusal 3); on a PoC box it would go on
    (box / "deploy" / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    shutil.copy2(ROOT / "deploy" / "install.sh", box / "deploy" / "install.sh")
    for name in ("libs", "services", "tools"):
        (box / name).symlink_to(ROOT / name)
    b = tmp / "bin"
    b.mkdir()
    (b / "python3").symlink_to(sys.executable)
    docker = b / "docker"
    docker.write_text(
        f'#!/bin/sh\necho "$*" >> {tmp}/docker.log\ncase "$1 $2" in "version --format") echo 27.0 ;; esac\nexit 0\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    bundle = tmp / "trialbox-1.0.0.tar"
    bundle.write_bytes(b"stand-in bundle")
    env = {"PATH": f"{b}{os.pathsep}/usr/bin:/bin", "HOME": str(tmp)}
    return box, env, bundle


def _tree(box: Path) -> dict[str, bytes]:
    """Every file of the install folder and its content (the linked code is not walked)."""
    out = {}
    for d, dirs, files in os.walk(box):
        for f in files + [x for x in dirs if os.path.islink(os.path.join(d, x))]:
            p = Path(d, f)
            out[str(p.relative_to(box))] = b"link" if p.is_symlink() else p.read_bytes()
    return out


def _install(box: Path, env: dict[str, str], bundle: Path, prefix: str = "") -> subprocess.CompletedProcess[str]:
    script = f'{prefix}exec bash "{box}/deploy/install.sh" "{bundle}" --mode stub --yes'
    return subprocess.run(
        ["bash", "-c", script], cwd=box, env=env, capture_output=True, text=True, check=False, timeout=180
    )


def test_a_second_installer_while_one_runs_refuses_and_changes_nothing(tmp_path: Path) -> None:
    """Review 2 of #1305 (M-2): a second run's cleanup took the first run's containers down while they started. The
    installer holds a lock (flock on the deploy folder itself, no lock file) from before its first write; a second run
    while it is held refuses (exit non-zero, said plainly), writes nothing and asks the engine for nothing that changes
    it. The positive controls: free, the same run goes past the lock to the next step; the run from the signed tree,
    which inherits the lock on fd 9, is not refused by its own lock. No run leaves a file behind."""
    box, env, bundle = _box(tmp_path)
    lock = box / "deploy"
    before = _tree(box)
    held = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX)  # the first installer, still running
        res = _install(box, env, bundle)
        assert res.returncode != 0, res.stdout + res.stderr
        assert "another deploy/install.sh is running" in res.stderr and "nothing was changed or removed" in res.stderr
        assert "rehearsal box" not in res.stderr  # stopped at the lock, before the first step that writes
        assert _tree(box) == before
        calls = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
        changes = {"up", "down", "run", "load", "rm", "stop", "create", "pull", "kill", "pause"}
        assert not [c for c in calls if changes & set(c.split())], calls  # only info and version were asked
    finally:
        os.close(held)
    res = _install(box, env, bundle)
    assert res.returncode != 0 and "another deploy/install.sh" not in res.stderr, res.stderr
    assert "this box was a rehearsal box" in res.stderr, res.stderr  # past the lock: the next step's own stop
    inherited = f'exec 9<"{lock}" && flock -n 9 && '  # the first run, going on from the signed tree (exec)
    res = _install(box, env, bundle, prefix=inherited)
    assert "another deploy/install.sh" not in res.stderr and "this box was a rehearsal box" in res.stderr, res.stderr
    assert _tree(box) == before


def test_the_lock_comes_before_the_first_write_and_the_cleanup() -> None:
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    lock = install.index("flock -n 9 || die")
    assert lock < install.index("# REHEARSAL (D-726): before anything loads")
    assert lock < install.index("mkdir -p deploy/site && printf")
    assert lock < install.index("# PROJECT-CLEANUP (F-19)")
    assert lock < install.index('TB_INSTALL_SIGNED="$RELEASE" exec bash')


def _drill_ops(env: dict[str, str]) -> Any:
    """``LocalDrill`` with the backup's manifest given and the restore stood in; its own create and drop run."""
    from tools.trialbox import restore_drill as rd

    class Drill(rd.LocalDrill):
        def unpack(self, file: Path, key: Path, into: Path) -> dict[str, Any]:
            dbs: dict[str, Any] = {"trialbox_wf": {"rows": {}}}
            return {
                "created_at": "2026-11-20T00:00:00+00:00",
                "databases": dbs,
                "_sha256": "0" * 64,
                "files": [],
                "site": "SYN",
            }

        def restore_compare(self, db: str, name: str, into: Path, want: Any) -> list[str]:
            return []

    return Drill(env)


def test_a_refused_live_name_is_never_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review 2 of #1305 (L-1): the scratch name was recorded before the live-name guard, so a name the guard refused
    was still dropped (``DROP DATABASE ... WITH (FORCE)``, guarded by the prefix alone). A drill whose name would be
    the live database fails and changes nothing (D-892). The positive control: a scratch name is made and dropped."""
    from tools.trialbox import restore_drill as rd

    made: list[str] = []
    dropped: list[str] = []
    monkeypatch.setattr(rd, "_create", lambda _admin, name: made.append(name))
    monkeypatch.setattr(rd, "_drop", lambda _admin, name: dropped.append(name))
    (tmp_path / "b.tbbak").write_bytes(b"synthetic")
    (tmp_path / "usb.key").write_bytes(b"synthetic")
    env = {"TB_DB_URL": "postgresql://u@h:5432/tb_drill_live"}
    files = (tmp_path / "b.tbbak", tmp_path / "usb.key", env)
    kw: dict[str, Any] = {"work": tmp_path, "db_dir": tmp_path, "free": lambda _p: 10**12}
    res = rd.drill(*files, name=lambda _db: "tb_drill_live", ops=_drill_ops(env), **kw)
    assert not res["ok"] and "DrillError" in res["error"], res
    assert made == [] and dropped == [], (made, dropped)
    assert res["scratch_dropped"] == [] and "left_behind" not in res, res
    res = rd.drill(*files, name=lambda _db: "tb_drill_0a1b2c3d_trialbox_wf", ops=_drill_ops(env), **kw)
    assert res["ok"], res
    assert made == dropped == ["tb_drill_0a1b2c3d_trialbox_wf"], (made, dropped)


def _seal(tmp: Path, phrase: str) -> subprocess.CompletedProcess[str]:
    (tmp / "host" / "dev").mkdir(parents=True, exist_ok=True)
    (tmp / "secrets").mkdir(exist_ok=True)
    b = tmp / "bin"
    b.mkdir(exist_ok=True)
    docker = b / "docker"
    docker.write_text(f'#!/bin/sh\necho "$*" >> {tmp}/docker.log\nexit 0\n', encoding="utf-8")
    docker.chmod(0o755)
    keep = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    env = {**keep, "PATH": f"{b}:/usr/bin:/bin", "TB_HOST_ROOT": str(tmp / "host"), "TB_SYSTEMD": "0"}
    env |= {"TB_KEK_FILE": str(tmp / "kek.runtime"), "TB_KEK_BACKEND": "passphrase", "TB_KEK_PASSPHRASE": phrase}
    argv = ["sh", str(SEAL), "--secrets", str(tmp / "secrets"), "--conf", str(tmp / "none"), "--dry-run"]
    return subprocess.run(argv, capture_output=True, text=True, env=env, check=False, timeout=120)


@pytest.mark.parametrize("cut", ["\n", "\r", "\t"])
def test_a_passphrase_with_a_line_break_is_refused_before_sealing(tmp_path: Path, cut: str) -> None:
    """Review 2 of #1305 (L-2): the image fallback reads one line, the host's python3 the whole value: a passphrase
    with a line break would be sealed under different values by the two. Refused before anything, never printed.
    The positive control: the same passphrase on one line goes on (a dry run)."""
    first, second = os.urandom(8).hex(), os.urandom(8).hex()
    res = _seal(tmp_path, f"{first}{cut}{second}")
    assert res.returncode != 0 and "control character" in res.stderr and "nothing was sealed" in res.stderr
    assert first not in res.stdout + res.stderr and second not in res.stdout + res.stderr
    assert not (tmp_path / "docker.log").exists() and list((tmp_path / "secrets").iterdir()) == []
    ok = _seal(tmp_path, f"{first} {second}")
    assert ok.returncode == 0 and "would run: tools.keys init --backend passphrase" in ok.stdout + ok.stderr


def test_the_network_sheet_says_where_the_passphrase_never_is() -> None:
    """Review 2 of #1305 (L-3): without ``cryptography`` on the host the passphrase reaches a container's process
    (its stdin), so "never in a container" was not true. True: never in a container's configuration or a file."""
    from tools import network_sheet as ns

    for lang in ("en", "ja", "zh-TW"):
        md = ns.render_md(list(ns.FILES), None, lang)
        kek = next(x for x in md.splitlines() if x.startswith("| TB_KEK_PASSPHRASE |"))
        operator = next(x for x in md.splitlines() if x.startswith("| operator token |"))
        assert kek.rsplit("|", 2)[1] != operator.rsplit("|", 2)[1], (lang, kek)
        if lang == "en":
            assert kek.rstrip(" |").endswith("never in a container's configuration or in a file"), kek
