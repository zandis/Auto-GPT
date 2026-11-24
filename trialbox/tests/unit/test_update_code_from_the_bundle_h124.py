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
    "            time.sleep(15)\n\n"
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
    assert _audited(b, "R2", "update.applied")["update_code"] == "bundle"


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


def _audited(b: dict[str, Any], bid: str, event: str) -> dict[str, Any]:
    """The audit event as the site box hands it to the audit writer (deploy/updates/<bundle>/<event>.json)."""
    return dict(json.loads((b["deploy"] / "updates" / bid / f"{event}.json").read_text())["detail"])


def test_h124_a_poc_box_warns_runs_the_installed_code_and_names_it_in_the_output_and_the_audit(
    box: dict[str, Any],
) -> None:
    """The integrator's ruling 7131272906: a bundle with no host tree (an older bundle format) on a PoC box is warned
    and listed (D-1091), the installed release's code runs, and the output and the audit event name it."""
    b = box
    _install(b, _release(b["tmp"], "R1-fixed"))
    r = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, None))
    assert r.returncode == 0, _said(r)
    assert "update code: the installed release's (the bundle carries no host tree)" in r.stdout
    assert "warning (PoC box, H-124)" in r.stderr and "REFUSED" not in r.stderr
    listed = [json.loads(ln) for ln in (b["deploy"] / "site" / "poc-stops.jsonl").read_text().splitlines()]
    assert [x["key"] for x in listed] == ["apply_update.sh/update.no-host-tree"]
    assert _audited(b, "R2", "update.applied")["update_code"] == "installed"


def test_h124_production_refuses_a_bundle_without_a_host_tree_saying_why_and_what_to_do(box: dict[str, Any]) -> None:
    b = box
    (b["deploy"] / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    _install(b, _release(b["tmp"], "R1-broken", FAULT))
    r = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, None), "--no-backup-reason", "synthetic test box")
    assert r.returncode == 1, _said(r)
    said = " ".join(r.stderr.split())
    assert "update REFUSED: " in said and "carries no host tree (an older bundle format)" in said
    assert "nothing was changed" in said and "Ask the vendor for the release's full bundle" in said
    assert "PLANTED FAULT" not in _said(r) and "update code:" not in r.stdout  # nothing of either release ran
    assert _current(b) == "releases/R1" and _seq(b) == 1


def test_h124_the_callers_environment_does_not_choose_the_update_code(box: dict[str, Any]) -> None:
    """A caller's PYTHONPATH changes nothing: the new release's code runs."""
    b = box
    _install(b, _release(b["tmp"], "R1-broken", FAULT))
    b["env"].update(PYTHONPATH=str(b["base"]))
    r = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, _release(b["tmp"], "R2-fixed")))
    assert r.returncode == 0 and "PLANTED FAULT" not in _said(r), _said(r)


# ------------------------------------------------------------------------------------------------ a stop partway
def test_h124_a_sigterm_partway_is_handled_by_the_new_code_and_the_box_stays_sound(box: dict[str, Any]) -> None:
    """SIGTERM to the update's process group (as a service manager stops it) while the NEW release's code holds the
    marker: that code's own handling (H-114, #1461) puts the box back, the stage (and the code in it) is removed only
    after it ends, and the INSTALLED tree's `apply_update.sh status` reads what is left without a fault."""
    b = box
    _install(b, _release(b["tmp"], "R1-fixed"))
    p = _apply(b, _bundle(b["tmp"], b["priv"], "R2", 2, _release(b["tmp"], "R2-slow", SLOW)), wait=False)
    started = b["deploy"] / "updates" / "H124-STARTED"
    for _ in range(600):
        if started.exists() or p.poll() is not None:
            break
        time.sleep(0.1)
    assert started.exists(), p.communicate()[0][-3000:]
    assert (b["deploy"] / "updates" / "IN_PROGRESS.json").exists()  # the new code wrote the marker
    os.killpg(p.pid, signal.SIGTERM)
    out = p.communicate(timeout=180)[0]
    assert p.returncode != 0, out[-3000:]
    assert _current(b) == "releases/R1" and _seq(b) == 1
    assert not (b["deploy"] / "updates" / "IN_PROGRESS.json").exists(), out[-3000:]
    assert not list((b["tmp"] / "tmp").glob("tb-update.*")), "the stage (and the new code in it) is removed"
    st = subprocess.run(["bash", str(b["base"] / "tools" / "apply_update.sh"), "status"], env=b["env"],
                        capture_output=True, text=True, check=False, timeout=120)  # fmt: skip
    assert st.returncode == 0 and "Traceback" not in st.stdout + st.stderr, st.stdout + st.stderr


# ------------------------------------------------------------------------------------------------ the hand-off
def test_h124_the_hand_off_runs_the_staged_tree_and_the_installed_verifier(box: dict[str, Any]) -> None:
    """What the installed script runs from where (the mutant `cd "$ROOT"` fails the invariant above)."""
    text = (ROOT / "tools" / "apply_update.sh").read_text(encoding="utf-8")
    verify = text.index('python3 "$ROOT/tools/verify_update.py"')
    stage = text.index("python3 -m tools.host_tree stage-code")
    run = text.index('PYTHONPATH="$CODE/libs:$CODE" python3 -m tools.trialbox update')
    guard = text.index('sh "$ROOT/deploy/settings_guard.sh" "$ROOT/deploy"')  # the installed start guard
    assert verify < guard < stage < text.index('cd "$CODE"') < run


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


def test_h124_03_an_unpacked_tree_is_on_disk_before_it_is_named(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every file and every folder of the unpacked tree is fsynced before the rename, and the parent after it."""
    calls: list[str] = []
    real_fsync, real_rename = os.fsync, Path.rename

    def fsync(fd: int) -> None:
        calls.append(f"fsync {os.readlink(f'/proc/self/fd/{fd}')}")
        real_fsync(fd)

    def rename(self: Path, target: Any) -> Any:
        calls.append(f"rename {self} -> {target}")
        return real_rename(self, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "rename", rename)
    dest = box["tmp"] / "stage" / "code"
    dest.parent.mkdir()
    n = ht.stage_code(_release(box["tmp"], "R2"), dest, box["base"])
    at = next(i for i, c in enumerate(calls) if c.startswith("rename "))
    before, after = calls[:at], calls[at + 1 :]
    assert sum(1 for c in before if "/.code.partial/" in c) >= n  # each file, and each folder inside
    assert f"fsync {dest.parent / '.code.partial'}" in before
    assert after == [f"fsync {dest.parent}"]


def test_h124_01_an_installed_box_does_not_take_its_vendor_key_from_the_caller(box: dict[str, Any]) -> None:
    """A bundle signed by a key of the caller's own, named by TB_VENDOR_PUBKEY: an installed box verifies with its
    own vendor key, so the bundle is rejected and nothing of it runs."""
    b = box
    _install(b, _release(b["tmp"], "R1-fixed"))
    other_priv, other_pub = keygen(b["tmp"] / "not-the-vendor")
    bundle = _bundle(b["tmp"], other_priv, "R2", 2, _release(b["tmp"], "R2-fixed"))
    b["env"]["TB_VENDOR_PUBKEY"] = str(other_pub)
    r = _apply(b, bundle)
    assert r.returncode == 1 and "update REJECTED" in _said(r), _said(r)
    assert "TB_VENDOR_PUBKEY is not read on an installed box" in r.stderr
    assert "update code:" not in r.stdout and _current(b) == "releases/R1" and _seq(b) == 1
