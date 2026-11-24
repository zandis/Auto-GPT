"""H-124 (the integrator's ruling 7128338428; H-121's finding H121-06): the update's own code is the new release's.

``tools/apply_update.sh`` (the installed one) verifies the bundle with the installed vendor key and the installed
verifier, then unpacks the signed host tree into its 0700 stage and runs THAT tree's start guard and
``tools.trialbox update``. So a fault in the installed release's update code is mended by the next bundle, not only
by a reinstall (the MVP walk's red 7125822972: a box on a release before H-99 could never update).

Each case runs the real ``tools/apply_update.sh`` of an installed box made from this repository's own host tree, on
bundles made by the real signer (``tools/sign_bundle.py``), with a stand-in ``docker`` on ``PATH`` (no container
runs). A "fault" is a ``main_apply`` planted in a release's ``tools/trialbox/update.py`` that fails at once. Keys are
throwaway test keys; no data.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tools import host_tree as ht
from tools.sign_bundle import build, keygen

ROOT = Path(__file__).resolve().parents[2]
UPDATE_PY = "tools/trialbox/update.py"
FAULT = (
    "\n\ndef main_apply(*_a: object, **_k: object) -> int:  # H-124 test: a planted fault in this release's update code\n"
    "    print('update FAILED: PLANTED FAULT in this release', file=sys.stderr)\n"
    "    return 1\n"
)
SLOW = (
    "\n\n_h124_init = Updater.__init__\n\n\n"
    "def _h124_slow_init(self: Updater, *a: Any, **k: Any) -> None:  # H-124 test: an update stopped partway\n"
    "    _h124_init(self, *a, **k)\n"
    "    before = self.on_step\n\n"
    "    def on(name: str) -> None:\n"
    "        if before:\n"
    "            before(name)\n"
    "        if name == 'rollback point':  # the marker is written, nothing is changed yet\n"
    "            (self.dir / 'H124-STARTED').touch()\n"
    "            time.sleep(60)\n\n"
    "    self.on_step = on\n\n\n"
    "Updater.__init__ = _h124_slow_init  # type: ignore[method-assign]\n"
)

STAND_IN_DOCKER = r"""#!PYTHON
import os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
if args[:1] == ["compose"]:
    rest = args[args.index("--project-directory") + 2:] if "--project-directory" in args else args[1:]
    cmd = rest[0] if rest else ""
    if cmd == "ps":
        print("db\norchestrator")
    elif cmd == "exec" and "pg_dump" in rest:
        sys.stdout.write("PGDMP synthetic dump")
    elif cmd == "exec" and any("pg_database_size" in a for a in rest):
        print("1000")
    elif cmd == "exec" and any("orch.jobs" in a for a in rest):
        print("0")
    elif cmd == "run" and "snapshot" in rest:
        print("{}")
    elif cmd == "exec":
        sys.stdin.read() if not sys.stdin.isatty() else None
elif args[:1] == ["info"]:
    print(os.environ["FAKE_DOCKER_ROOT"])
elif args[:2] == ["image", "inspect"]:
    sys.exit("no such image")
"""


def _release(tmp: Path, name: str, plant: str = "") -> Path:
    """A release's host tree: this repository's own release files, with ``plant`` added to its update code."""
    src = tmp / f"src-{name}"
    for rel in ht.tree_files(ROOT):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, src / rel)
    if plant:
        with (src / UPDATE_PY).open("a", encoding="utf-8") as fh:
            fh.write(plant)
    tar = tmp / f"host-{name}.tar"
    ht.pack(src, tar)
    return tar


def _bundle(tmp: Path, key: Path, bid: str, seq: int, host: Path | None) -> Path:
    out = tmp / f"{bid}.tar"
    if host is not None:
        build(key, bid, [("host", host, ht.HOST_TAR)], out, release_seq=seq)
    else:  # an older bundle format: no host tree, one other payload
        other = tmp / f"{bid}-note.txt"
        other.write_text("synthetic\n")
        build(key, bid, [("other", other, "note.txt")], out, release_seq=seq)
    return out


@pytest.fixture()
def box(tmp_path: Path) -> dict[str, Any]:
    """An installed box (``/opt/trialbox`` made by the host tree of release R1), and what runs its update."""
    priv, pub = keygen(tmp_path / "vendor")
    base = tmp_path / "opt-trialbox"
    deploy = base / "deploy"
    (deploy / "keys").mkdir(parents=True)
    (deploy / "updates").mkdir()
    shutil.copy2(pub, deploy / "keys" / "vendor_ed25519.pub")
    (deploy / ".env").write_text("TB_ENV=DEV\n", encoding="utf-8")
    (deploy / "updates" / "installed.json").write_text(json.dumps(
        {"format": "trialbox-installed/1", "release_seq": 1, "bundle_id": "R1", "state": {}}), encoding="utf-8")  # fmt: skip
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(STAND_IN_DOCKER.replace("#!PYTHON", f"#!{sys.executable}"), encoding="utf-8")
    (bin_dir / "python3").symlink_to(sys.executable)  # the host's python3: this test's (it has the host's packages)
    for f in bin_dir.iterdir():
        f.chmod(0o755) if not f.is_symlink() else None
    (tmp_path / "docker-root").mkdir()
    (tmp_path / "tmp").mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON", "FAKE_"))}
    env.update(PATH=f"{bin_dir}{os.pathsep}{env.get('PATH', '')}", TMPDIR=str(tmp_path / "tmp"),
               FAKE_DOCKER_LOG=str(tmp_path / "docker.log"), FAKE_DOCKER_ROOT=str(tmp_path / "docker-root"),
               TB_SECRETS_HOST_DIR=str(tmp_path / "no-secrets"), TB_MODELS_DIR=str(deploy / "models"),
               TB_DOCKER="true")  # fmt: skip
    return {"tmp": tmp_path, "priv": priv, "base": base, "deploy": deploy, "env": env}


def _install(b: dict[str, Any], host: Path, rid: str = "R1") -> None:
    """The installed release, as install.sh leaves it: the host tree under releases/, current and the links."""
    ht.install(host, b["base"], rid)


def _apply(b: dict[str, Any], bundle: Path, *args: str, wait: bool = True) -> Any:
    argv = ["bash", str(b["base"] / "tools" / "apply_update.sh"), str(bundle), "--no-backup", *args]
    if not wait:
        return subprocess.Popen(argv, env=b["env"], cwd=b["tmp"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)  # fmt: skip
    return subprocess.run(argv, env=b["env"], cwd=b["tmp"], capture_output=True, text=True, check=False, timeout=600)


def _current(b: dict[str, Any]) -> str:
    return os.readlink(b["base"] / "current")


def _seq(b: dict[str, Any]) -> int:
    return int(json.loads((b["deploy"] / "updates" / "installed.json").read_text())["release_seq"])


def _said(r: subprocess.CompletedProcess[str]) -> str:
    return (r.stdout + r.stderr)[-3000:]


# ------------------------------------------------------------------------------------------------ the invariant
def test_h124_a_fault_in_the_installed_update_code_does_not_stop_an_update_to_a_fixed_release(
    box: dict[str, Any],
) -> None:
    """The invariant: the installed release's update code is broken; the update to a fixed release still goes."""
    b = box
    _install(b, _release(b["tmp"], "R1-broken", FAULT))
    r = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, _release(b["tmp"], "R2-fixed")))
    assert r.returncode == 0, _said(r)
    assert "update code: the new release's (its signed host tree)" in r.stdout
    assert "PLANTED FAULT" not in _said(r)
    assert _current(b) == "releases/R2" and _seq(b) == 2


def test_h124_the_control_a_fault_in_the_new_release_is_the_one_that_runs(box: dict[str, Any]) -> None:
    """The control: installed code sound, the bundle's broken; the bundle's runs, so the update fails, unchanged."""
    b = box
    _install(b, _release(b["tmp"], "R1-fixed"))
    r = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, _release(b["tmp"], "R2-broken", FAULT)))
    assert r.returncode == 1 and "PLANTED FAULT in this release" in _said(r), _said(r)
    assert _current(b) == "releases/R1" and _seq(b) == 1


# ------------------------------------------------------------------------------------------------ what never runs
def test_h124_a_host_tree_changed_after_signing_is_refused_before_any_of_it_runs(box: dict[str, Any]) -> None:
    b = box
    _install(b, _release(b["tmp"], "R1-fixed"))
    bundle = _bundle(b["tmp"], b["priv"], "R2", 2, _release(b["tmp"], "R2-fixed"))
    data = bytearray(bundle.read_bytes())
    i = data.index(b"def main_apply(")  # one byte of the new release's update code, inside the signed bundle
    data[i] ^= 0x01
    bundle.write_bytes(bytes(data))
    r = _apply(b, bundle)
    assert r.returncode == 1 and "update REJECTED" in _said(r), _said(r)
    assert "update code:" not in r.stdout
    assert _current(b) == "releases/R1" and _seq(b) == 1


def test_h124_a_bundle_without_a_host_tree_runs_the_installed_code_and_says_so(box: dict[str, Any]) -> None:
    """An older bundle format on a PoC box: not one of the five stops (D-1091); the installed release's code runs,
    said plainly, and nothing goes on the PoC list (nothing is skipped)."""
    b = box
    _install(b, _release(b["tmp"], "R1-broken", FAULT))
    r = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, None))
    assert "update code: the installed release's (the bundle carries no host tree)" in r.stdout, _said(r)
    assert "carries no host tree; the installed release's update code runs" in r.stderr and "REFUSED" not in r.stderr
    assert "PLANTED FAULT in this release" in _said(r) and r.returncode == 1  # the installed code ran
    assert not (b["deploy"] / "site" / "poc-stops.jsonl").exists()


def test_h124_production_without_a_host_tree_follows_the_one_constant(box: dict[str, Any]) -> None:
    """Until the integrator rules (#639): PRODUCTION warns as a PoC box does; the constant is the one place, and
    `refuse` stops PRODUCTION only, before anything runs."""
    b = box
    (b["deploy"] / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    _install(b, _release(b["tmp"], "R1-broken", FAULT))
    bundle = _bundle(b["tmp"], b["priv"], "R2", 2, None)
    r = _apply(b, bundle, "--no-backup-reason", "synthetic test box")
    assert "carries no host tree; the installed release's update code runs" in r.stderr, _said(r)
    script = (b["base"] / "tools" / "apply_update.sh").read_text(encoding="utf-8")
    assert script.count("H124_NO_HOST_TREE_PRODUCTION=") == 1 and "H124_NO_HOST_TREE_PRODUCTION=warn" in script
    refusing = b["base"] / "tools" / "apply_update.sh"
    target = refusing.resolve()
    target.unlink()  # the installed release's own file is read-only content of its release: replaced, not edited
    target.write_text(script.replace("H124_NO_HOST_TREE_PRODUCTION=warn", "H124_NO_HOST_TREE_PRODUCTION=refuse"))
    r = _apply(b, bundle, "--no-backup-reason", "synthetic test box")
    assert r.returncode == 1 and "update REFUSED: " in r.stderr and "carries no host tree" in r.stderr, _said(r)
    assert "PLANTED FAULT" not in _said(r) and _current(b) == "releases/R1"
    (b["deploy"] / ".env").write_text("TB_ENV=DEV\n", encoding="utf-8")  # a PoC box goes on under `refuse` too
    r = _apply(b, bundle)
    assert "REFUSED" not in r.stderr and "PLANTED FAULT in this release" in _said(r), _said(r)


def test_h124_the_callers_environment_does_not_choose_the_update_code(box: dict[str, Any]) -> None:
    """A caller's PYTHONPATH (or the constant's name in the environment) changes nothing: the new release's runs."""
    b = box
    _install(b, _release(b["tmp"], "R1-broken", FAULT))
    b["env"].update(PYTHONPATH=str(b["base"]), H124_NO_HOST_TREE_PRODUCTION="refuse")
    r = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, _release(b["tmp"], "R2-fixed")))
    assert r.returncode == 0 and "PLANTED FAULT" not in _said(r), _said(r)


# ------------------------------------------------------------------------------------------------ a stop partway
def test_h124_a_sigterm_partway_leaves_a_marker_the_installed_tree_reads_and_rolls_back(box: dict[str, Any]) -> None:
    """SIGTERM to the update's process group (as a service manager stops it) while the NEW release's code holds the
    marker: the box is still on R1, the stage (and the new code in it) is removed, and the INSTALLED tree's
    `apply_update.sh status` names the step and `rollback R2` clears it, the box on R1."""
    b = box
    _install(b, _release(b["tmp"], "R1-fixed"))
    p = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, _release(b["tmp"], "R2-slow", SLOW)), wait=False)
    started = b["deploy"] / "updates" / "H124-STARTED"
    for _ in range(600):
        if started.exists() or p.poll() is not None:
            break
        time.sleep(0.1)
    assert started.exists(), p.communicate()[0][-3000:]
    os.killpg(p.pid, signal.SIGTERM)
    out = p.communicate(timeout=120)[0]
    assert p.returncode != 0, out[-3000:]
    assert _current(b) == "releases/R1" and _seq(b) == 1
    assert not list((b["tmp"] / "tmp").glob("tb-update.*")), "the stage (and the new code in it) is removed"
    marker = json.loads((b["deploy"] / "updates" / "IN_PROGRESS.json").read_text())
    assert marker["bundle_id"] == "R2" and marker["step"] == "rollback point"
    installed = ["bash", str(b["base"] / "tools" / "apply_update.sh")]
    st = subprocess.run([*installed, "status"], env=b["env"], capture_output=True, text=True, check=False, timeout=120)
    assert "R2" in st.stdout + st.stderr and "Traceback" not in st.stdout + st.stderr, st.stdout + st.stderr
    rb = subprocess.run([*installed, "rollback", "R2"], env=b["env"], capture_output=True, text=True, check=False,
                        timeout=300)  # fmt: skip
    assert rb.returncode == 0, (rb.stdout + rb.stderr)[-3000:]
    assert not (b["deploy"] / "updates" / "IN_PROGRESS.json").exists()
    assert _current(b) == "releases/R1" and _seq(b) == 1


# ------------------------------------------------------------------------------------------------ the hand-off
def test_h124_the_hand_off_runs_the_staged_tree_and_the_installed_verifier(box: dict[str, Any]) -> None:
    """What the installed script runs from where (the mutant `cd "$ROOT"` fails the invariant above)."""
    text = (ROOT / "tools" / "apply_update.sh").read_text(encoding="utf-8")
    verify = text.index('python3 "$ROOT/tools/verify_update.py"')
    stage = text.index("python3 -m tools.host_tree stage-code")
    run = text.index('PYTHONPATH="$CODE/libs:$CODE" python3 -m tools.trialbox update')
    assert verify < stage < run
    guard = text.index('sh "$ROOT/deploy/settings_guard.sh" "$ROOT/deploy"')  # the installed start guard
    assert verify < guard < text.index('cd "$CODE"') < run


def test_h124_the_staged_code_reads_the_boxs_own_deploy_folder(box: dict[str, Any]) -> None:
    """The staged tree's deploy/ is one link to the box's own: its settings, keys and records, never the release's."""
    b = box
    dest = b["tmp"] / "stage" / "code"
    dest.parent.mkdir()
    n = ht.stage_code(_release(b["tmp"], "R2"), dest, b["base"])
    assert n > 100 and (dest / "tools" / "trialbox" / "update.py").is_file()
    assert (dest / "deploy").is_symlink() and (dest / "deploy").resolve() == b["deploy"].resolve()
    with pytest.raises(ht.HostTreeError, match="exists"):
        ht.stage_code(_release(b["tmp"], "R3"), dest, b["base"])
